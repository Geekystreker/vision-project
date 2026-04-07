from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import numpy as np

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import BoundingBox, Detection


class DetectionBackend(ABC):
    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[Detection]:
        raise NotImplementedError


class YOLO26Backend(DetectionBackend):
    """Primary detector adapter.

    The project targets a YOLO26-class detector, but the adapter gracefully falls
    back to any compatible Ultralytics YOLO checkpoint when the exact runtime is
    not yet available on the machine.
    """

    def __init__(self, config: RoverConfig) -> None:
        self._config = config
        self._model = None
        self._names: dict[int, str] = {}
        self._model_name = config.detector_model
        self._device = "cpu"
        self._use_half = False
        self._target_class_ids: list[int] | None = None

    def load(self) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Ultralytics unavailable: {exc}")
            self._model = None
            return

        try:
            import torch

            if self._config.detector_device != "auto":
                self._device = self._config.detector_device
            else:
                self._device = "cuda:0" if torch.cuda.is_available() else "cpu"

            if self._device.startswith("cuda") and torch.cuda.is_available():
                self._use_half = bool(self._config.detector_half_precision)
                torch.backends.cudnn.benchmark = True
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                if hasattr(torch, "set_float32_matmul_precision"):
                    torch.set_float32_matmul_precision("high")
            else:
                self._use_half = False
        except Exception:
            self._device = "cpu"
            self._use_half = False

        candidates = [self._config.detector_model, self._config.detector_fallback_model]
        last_error = ""
        for name in candidates:
            if not name:
                continue
            try:
                model = YOLO(name)
                try:
                    model.to(self._device)
                except Exception:
                    pass
                self._model = model
                self._model_name = name
                raw_names = getattr(model, "names", {}) or {}
                self._names = {int(key): str(value) for key, value in raw_names.items()}
                self._target_class_ids = self._resolve_target_class_ids()
                self._warmup_model()
                bus.emit(
                    SystemEvents.LOG_MESSAGE,
                    "[DetectionEngine] Loaded "
                    f"{name} on {self._device} "
                    f"({'fp16' if self._use_half else 'fp32'}) "
                    f"for backend {self._config.detector_backend}.",
                )
                return
            except Exception as exc:
                last_error = str(exc)

        self._model = None
        bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Failed to load detector: {last_error}")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._model is None:
            return []

        try:
            results = self._model.predict(frame, **self._predict_kwargs(frame))
            detections = list(self._filter_detections(results))
            bus.emit(SystemEvents.DETECTIONS_UPDATED, detections)
            if not detections:
                bus.emit(SystemEvents.ROVER_NO_DETECTION, None)
            return detections
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Inference error: {exc}")
            bus.emit(SystemEvents.ROVER_NO_DETECTION, None)
            return []

    def _predict_kwargs(self, frame: np.ndarray | None = None) -> dict[str, object]:
        imgsz = self._resolve_image_size(frame)
        kwargs: dict[str, object] = {
            "verbose": False,
            "device": self._device,
            "conf": self._config.detector_confidence,
            "imgsz": imgsz,
            "max_det": self._config.detector_max_detections,
        }
        if self._use_half:
            kwargs["half"] = True
        if self._target_class_ids:
            kwargs["classes"] = self._target_class_ids
        return kwargs

    def _resolve_image_size(self, frame: np.ndarray | None) -> int:
        if frame is not None and len(frame.shape) >= 2:
            return max(64, int(max(frame.shape[0], frame.shape[1])))
        return max(64, min(int(self._config.detector_input_width), 640))

    def _resolve_target_class_ids(self) -> list[int] | None:
        target_label = (self._config.target_label or "").strip().lower()
        if not target_label:
            return None
        matched = [class_id for class_id, label in self._names.items() if label.strip().lower() == target_label]
        return matched or None

    def _warmup_model(self) -> None:
        if self._model is None:
            return
        try:
            warmup_width = max(64, min(int(self._config.detector_input_width), 640))
            warmup_height = max(64, int(round(warmup_width * 3 / 4)))
            warmup = np.zeros((warmup_height, warmup_width, 3), dtype=np.uint8)
            self._model.predict(warmup, **self._predict_kwargs(warmup))
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Warmup skipped: {exc}")

    def _filter_detections(self, results) -> Iterable[Detection]:
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls = int(box.cls[0])
                confidence = float(box.conf[0])
                label = self._names.get(cls, str(cls))
                if confidence < self._config.detector_confidence:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                yield Detection(
                    label=label,
                    confidence=confidence,
                    bbox=BoundingBox(
                        x=int(x1),
                        y=int(y1),
                        w=max(0, int(x2 - x1)),
                        h=max(0, int(y2 - y1)),
                        confidence=confidence,
                    ),
                    source=self._config.detector_backend,
                    class_id=cls,
                )


class DetectionEngine:
    def __init__(self, config: RoverConfig, backend: DetectionBackend | None = None) -> None:
        self._config = config
        self._backend = backend or YOLO26Backend(config)

    def load(self) -> None:
        self._backend.load()

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return self._backend.detect(frame)

    def select_primary(self, detections: list[Detection], label: str | None = None) -> Detection | None:
        label = label or self._config.target_label
        filtered = [item for item in detections if item.label.lower() == label.lower()]
        if not filtered:
            return None
        primary = max(filtered, key=lambda item: item.area)
        bus.emit(SystemEvents.ROVER_DETECTION, primary)
        return primary
