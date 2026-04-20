from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

import numpy as np

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import BoundingBox, Detection


class DetectionBackend(ABC):
    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    def ready(self) -> bool:
        return True

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
        tracker_path = Path(config.resolved_tracker_config_path)
        self._tracker_config = str(tracker_path) if tracker_path.exists() else "botsort.yaml"

    def load(self) -> None:
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
                from ultralytics import YOLO

                model = YOLO(name)
                try:
                    model.to(self._device)
                except Exception:
                    pass
                self._model = model
                self._model_name = name
                raw_names = getattr(model, "names", {}) or {}
                self._names = {int(key): str(value) for key, value in raw_names.items()}
                self._warmup_model()
                bus.emit(
                    SystemEvents.LOG_MESSAGE,
                    "[DetectionEngine] Loaded "
                    f"{name} on {self._device} "
                    f"({'fp16' if self._use_half else 'fp32'}) "
                    f"with tracker {self._tracker_config}.",
                )
                return
            except Exception as exc:
                last_error = str(exc)

        self._model = None
        bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Failed to load detector: {last_error}")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._model is None:
            return []
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            bus.emit(SystemEvents.LOG_MESSAGE, "[DetectionEngine] Skipping inference because the frame source is empty.")
            return []
        if frame.ndim < 2:
            bus.emit(SystemEvents.LOG_MESSAGE, "[DetectionEngine] Skipping inference because the frame source is malformed.")
            return []

        try:
            kwargs = self._predict_kwargs(frame)
            kwargs["conf"] = self._config.detector_tracking_confidence
            kwargs["iou"] = self._config.detector_tracking_iou
            if self._config.detector_track_classes is not None:
                kwargs["classes"] = list(self._config.detector_track_classes)
            results = self._model.track(
                frame,
                tracker=self._tracker_config,
                persist=True,
                **kwargs,
            )
            return list(self._filter_detections(results))
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[DetectionEngine] Inference error: {exc}")
            return []

    def ready(self) -> bool:
        return self._model is not None

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
        return kwargs

    def _resolve_image_size(self, frame: np.ndarray | None) -> int:
        if frame is not None and len(frame.shape) >= 2:
            return max(64, int(max(frame.shape[0], frame.shape[1])))
        return max(64, min(int(self._config.detector_input_width), 640))

    def _warmup_model(self) -> None:
        if self._model is None:
            return
        try:
            warmup_width = max(64, min(int(self._config.detector_input_width), 640))
            warmup_height = max(64, int(round(warmup_width * 3 / 4)))
            warmup = np.zeros((warmup_height, warmup_width, 3), dtype=np.uint8)
            self._model.predict(warmup, **self._predict_kwargs(warmup))
        except Exception:
            pass

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
                track_id = None
                if getattr(box, "id", None) is not None:
                    try:
                        track_id = int(box.id[0])
                    except Exception:
                        track_id = None
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
                    track_id=track_id,
                )


class DetectionEngine:
    def __init__(self, config: RoverConfig, backend: DetectionBackend | None = None) -> None:
        self._config = config
        self._backend = backend or YOLO26Backend(config)

    def load(self) -> None:
        self._backend.load()

    def ready(self) -> bool:
        return self._backend.ready()

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            return []
        detections = self._backend.detect(frame)
        return self._deduplicate_detections(detections)

    def select_primary(self, detections: list[Detection], label: str | None = None) -> Detection | None:
        label = label or self._config.target_label
        filtered = [item for item in detections if item.label.lower() == label.lower()]
        if not filtered:
            return None
        primary = max(filtered, key=lambda item: item.area)
        bus.emit(SystemEvents.ROVER_DETECTION, primary)
        return primary

    def _deduplicate_detections(self, detections: list[Detection]) -> list[Detection]:
        if not detections:
            return []
        ordered = sorted(detections, key=self._dedupe_priority, reverse=True)
        kept: list[Detection] = []
        for candidate in ordered:
            if any(self._is_duplicate(candidate, existing) for existing in kept):
                continue
            kept.append(candidate)
        return kept

    def _dedupe_priority(self, detection: Detection) -> tuple[float, float]:
        if (detection.label or "").strip().lower() == self._config.target_label.lower():
            return float(detection.area), float(detection.confidence)
        return float(detection.confidence), float(detection.area)

    def _is_duplicate(self, candidate: Detection, existing: Detection) -> bool:
        if candidate.label.strip().lower() != existing.label.strip().lower():
            return False
        if self._iou(candidate.bbox, existing.bbox) >= self._config.duplicate_detection_iou_threshold:
            return True
        if (candidate.label or "").strip().lower() != self._config.target_label.lower():
            return False
        candidate_center_inside = self._contains_point(
            existing.bbox,
            candidate.bbox.center_x,
            candidate.bbox.center_y,
        )
        return candidate_center_inside and existing.area >= (candidate.area * 1.85)

    @staticmethod
    def _contains_point(box: BoundingBox, x: float, y: float) -> bool:
        return box.x <= x <= (box.x + box.w) and box.y <= y <= (box.y + box.h)

    @staticmethod
    def _iou(left: BoundingBox, right: BoundingBox) -> float:
        x1 = max(left.x, right.x)
        y1 = max(left.y, right.y)
        x2 = min(left.x + left.w, right.x + right.w)
        y2 = min(left.y + left.h, right.y + right.h)
        overlap_w = max(0, x2 - x1)
        overlap_h = max(0, y2 - y1)
        intersection = overlap_w * overlap_h
        if intersection <= 0:
            return 0.0
        union = left.area + right.area - intersection
        if union <= 0:
            return 0.0
        return intersection / union
