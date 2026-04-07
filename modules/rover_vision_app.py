from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.control_arbiter import ControlArbiter
from modules.detection_engine import DetectionEngine
from modules.motor_controller import MotorController
from modules.rover_control import RoverController
from modules.rover_types import BoundingBox, ConnectionState, ControlMode, Detection, VisionSnapshot
from modules.scene_perception import ScenePerceptionService
from modules.servo_controller import ServoController
from modules.target_tracker import TargetTracker
from modules.tracking_controller import TrackingController
from modules.vision_stream import VisionStream

logger = logging.getLogger(__name__)


class RoverVisionApp:
    """Runtime service for camera streaming, detection, tracking, and transport."""

    def __init__(self, config: RoverConfig, arbiter: ControlArbiter | None = None) -> None:
        self._config = config
        self._arbiter = arbiter or ControlArbiter()
        self._running = False

        self._last_good_frame: Optional[np.ndarray] = None
        self._last_decoded_payload: bytes | None = None
        self._last_render_key = None
        self._last_rendered_rgb: Optional[np.ndarray] = None
        self._latest_snapshot = VisionSnapshot(frame=None)
        self._last_command = "S"
        self._fps = 0.0
        self._last_loop = 0.0
        self._latest_detections = []
        self._latest_target = None
        self._latest_detection_mode = ControlMode.IDLE
        self._detection_interval = 1.0 / max(1, self._config.detection_hz)
        self._last_detection_submit = 0.0
        self._detection_busy = False
        self._detection_frame: Optional[np.ndarray] = None
        self._detection_frame_size: tuple[int, int] = (0, 0)
        self._detection_scale: tuple[float, float] = (1.0, 1.0)
        self._detection_event = threading.Event()
        self._detection_load_lock = threading.Lock()
        self._detection_state_lock = threading.Lock()
        self._link_states = {
            "camera": ConnectionState.DISCONNECTED,
            "motor": ConnectionState.DISCONNECTED,
            "servo": ConnectionState.DISCONNECTED,
        }

        self._vision_stream = VisionStream(config.vision_stream_url, config)
        self._servo_controller = ServoController(config.servo_url, config)
        self._motor_controller = MotorController(config.motor_url, config)
        self._rover_controller = RoverController()
        self._detection_engine = DetectionEngine(config)
        self._detection_loaded = False
        self._target_tracker = TargetTracker(config)
        self._tracking_controller = TrackingController(
            config,
            self._rover_controller,
            self._servo_controller,
            self._motor_controller,
        )
        self._scene_perception = ScenePerceptionService()
        self._lock = threading.Lock()

        bus.subscribe(SystemEvents.CONNECTION_STATUS_CHANGED, self._on_connection_status)

    def run(self) -> None:
        self._running = True
        self._vision_stream.start()
        self._motor_controller.start()
        threading.Thread(
            target=self._detection_loop,
            daemon=True,
            name="DetectionWorker_Thread",
        ).start()
        threading.Thread(
            target=self._preload_detection,
            daemon=True,
            name="DetectionPreload_Thread",
        ).start()

        loop_interval = 1.0 / max(1, self._config.vision_loop_hz)
        while self._running:
            started = time.monotonic()
            try:
                self._step()
            except Exception as exc:
                bus.emit(SystemEvents.LOG_MESSAGE, f"[RoverVisionApp] loop error: {exc}")
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, loop_interval - elapsed))

        self._vision_stream.stop()
        self._servo_controller.stop()
        self._motor_controller.stop()

    def stop(self) -> None:
        self._running = False
        self._detection_event.set()
        self._tracking_controller.reset()
        self._last_command = "S"

    def latest_snapshot(self) -> VisionSnapshot:
        with self._lock:
            return self._latest_snapshot

    def send_drive_command(self, command: str, source: str = "VOICE") -> bool:
        cmd = (command or "").upper().strip()
        if cmd not in {"F", "B", "L", "R", "S"}:
            return False

        if source == "E_STOP":
            self._arbiter.trigger_emergency_stop()
            cmd = "S"
        elif source == "KEYBOARD":
            self._arbiter.begin_keyboard_override()
        else:
            if not self._arbiter.allow_voice():
                return False
            self._arbiter.begin_voice_nav()

        self._rover_controller.send_command(cmd)
        self._motor_controller.send(cmd)
        self._last_command = cmd
        return True

    def adjust_servo(self, *, pan_delta: int = 0, tilt_delta: int = 0, source: str = "KEYBOARD") -> tuple[int, int]:
        if source == "KEYBOARD":
            self._arbiter.begin_keyboard_override()
        elif source != "VOICE":
            self._arbiter.begin_keyboard_override()
        elif not self._arbiter.allow_voice():
            return 90, 90
        return self._tracking_controller.manual_pan_tilt(pan_delta=pan_delta, tilt_delta=tilt_delta)

    def toggle_follow_mode(self) -> ControlMode:
        mode = self._arbiter.toggle_follow_mode()
        if mode != ControlMode.FOLLOW_PERSON:
            self._tracking_controller.reset()
            self._target_tracker.clear()
            self._last_command = "S"
        return mode

    def set_follow_mode(self) -> ControlMode:
        return self._arbiter.set_follow_mode()

    def set_manual_mode(self) -> ControlMode:
        mode = self._arbiter.set_manual_mode()
        self._tracking_controller.reset()
        self._target_tracker.clear()
        self._last_command = "S"
        return mode

    def emergency_stop(self) -> None:
        self.send_drive_command("S", source="E_STOP")
        self._tracking_controller.reset()
        self._target_tracker.clear()

    def describe_scene(self) -> str:
        snapshot = self.latest_snapshot()
        detections = snapshot.detections
        if not detections and snapshot.frame is not None:
            self._ensure_detection_loaded()
            bgr = cv2.cvtColor(snapshot.frame, cv2.COLOR_RGB2BGR)
            detections = self._detection_engine.detect(bgr)
        return self._scene_perception.describe(detections)

    def _step(self) -> None:
        mode = self._arbiter.current_mode()

        raw = self._vision_stream.get_latest_frame()
        frame = self._decode_frame(raw) if raw is not None else None
        if frame is None:
            self._handle_missing_frame(mode)
            self._publish_snapshot(None, [], None, mode)
            return

        if mode in {ControlMode.FOLLOW_PERSON, ControlMode.INSPECT_SCENE}:
            self._schedule_detection(frame, mode)
        elif self._latest_target is not None or self._latest_detections:
            with self._detection_state_lock:
                self._latest_detections = []
                self._latest_target = None
                self._latest_detection_mode = mode
            if self._target_tracker.current_target() is not None:
                self._target_tracker.clear()

        with self._detection_state_lock:
            detections = list(self._latest_detections)
            target = self._latest_target

        if mode == ControlMode.FOLLOW_PERSON and self._vision_stream.frame_age() > self._config.frame_stale_seconds:
            self._tracking_controller.reset()
            self._last_command = "S"

        render_key = self._build_render_key(raw, detections, target, mode)
        if render_key == self._last_render_key and self._last_rendered_rgb is not None:
            rgb = self._last_rendered_rgb
        else:
            needs_overlay = bool(detections) or target is not None or mode in {
                ControlMode.FOLLOW_PERSON,
                ControlMode.INSPECT_SCENE,
            }
            display = self._render_overlay(frame.copy(), detections, target, mode) if needs_overlay else frame
            rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
            self._last_render_key = render_key
            self._last_rendered_rgb = rgb
        self._publish_snapshot(rgb, detections, target, mode)

    def _handle_missing_frame(self, mode: ControlMode) -> None:
        if self._target_tracker.current_target() is not None:
            self._target_tracker.clear()
        with self._detection_state_lock:
            self._latest_detections = []
            self._latest_target = None
            self._detection_frame = None
            self._detection_busy = False
        self._last_render_key = None
        self._last_rendered_rgb = None
        if mode == ControlMode.FOLLOW_PERSON:
            self._tracking_controller.reset()
            self._last_command = "S"

    def _schedule_detection(self, frame: np.ndarray, mode: ControlMode) -> None:
        now = time.monotonic()
        if self._detection_busy:
            return
        if (now - self._last_detection_submit) < self._detection_interval:
            return

        detect_frame = frame
        scale_x = 1.0
        scale_y = 1.0
        target_width = max(0, self._config.detector_input_width)
        if target_width and frame.shape[1] > target_width:
            ratio = target_width / frame.shape[1]
            target_height = max(1, int(frame.shape[0] * ratio))
            detect_frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
            scale_x = frame.shape[1] / target_width
            scale_y = frame.shape[0] / target_height

        with self._detection_state_lock:
            self._detection_frame = detect_frame
            self._detection_frame_size = (frame.shape[1], frame.shape[0])
            self._detection_scale = (scale_x, scale_y)
            self._latest_detection_mode = mode
            self._detection_busy = True
            self._last_detection_submit = now
        self._detection_event.set()

    def _detection_loop(self) -> None:
        while self._running:
            self._detection_event.wait(timeout=0.2)
            if not self._running:
                return

            with self._detection_state_lock:
                frame = self._detection_frame
                frame_w, frame_h = self._detection_frame_size
                scale_x, scale_y = self._detection_scale
                mode = self._latest_detection_mode
                self._detection_frame = None
                self._detection_event.clear()

            if frame is None or mode not in {ControlMode.FOLLOW_PERSON, ControlMode.INSPECT_SCENE}:
                with self._detection_state_lock:
                    self._detection_busy = False
                continue

            self._ensure_detection_loaded()
            detections = self._detection_engine.detect(frame)
            if scale_x != 1.0 or scale_y != 1.0:
                detections = [self._scale_detection(det, scale_x, scale_y, frame_w, frame_h) for det in detections]
            target = None

            if mode == ControlMode.FOLLOW_PERSON:
                target = self._target_tracker.update(detections)
                if self._arbiter.allow_autonomy():
                    self._last_command = self._tracking_controller.update(target, frame_w, frame_h)
            else:
                if self._target_tracker.current_target() is not None:
                    self._target_tracker.clear()

            with self._detection_state_lock:
                self._latest_detections = list(detections)
                self._latest_target = target
                self._detection_busy = False

    @staticmethod
    def _scale_detection(detection: Detection, scale_x: float, scale_y: float, max_w: int, max_h: int) -> Detection:
        bbox = detection.bbox
        x = max(0, min(max_w - 1, int(round(bbox.x * scale_x))))
        y = max(0, min(max_h - 1, int(round(bbox.y * scale_y))))
        w = max(0, min(max_w - x, int(round(bbox.w * scale_x))))
        h = max(0, min(max_h - y, int(round(bbox.h * scale_y))))
        return Detection(
            label=detection.label,
            confidence=detection.confidence,
            bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=bbox.confidence),
            source=detection.source,
            class_id=detection.class_id,
            track_id=detection.track_id,
        )

    def _decode_frame(self, data) -> Optional[np.ndarray]:
        try:
            if data is None:
                return self._last_good_frame
            if isinstance(data, np.ndarray):
                self._last_good_frame = data
                self._last_decoded_payload = None
                return data
            if data is self._last_decoded_payload and self._last_good_frame is not None:
                return self._last_good_frame
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return self._last_good_frame
            self._last_good_frame = frame
            self._last_decoded_payload = data
            return frame
        except Exception:
            return self._last_good_frame

    def _ensure_detection_loaded(self) -> None:
        if self._detection_loaded:
            return
        with self._detection_load_lock:
            if self._detection_loaded:
                return
            self._detection_engine.load()
            self._detection_loaded = True

    def _preload_detection(self) -> None:
        try:
            self._ensure_detection_loaded()
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[RoverVisionApp] detector preload failed: {exc}")

    def _build_render_key(self, raw, detections, target, mode: ControlMode):
        detection_key = tuple(
            (
                det.label,
                round(det.confidence, 3),
                det.bbox.x,
                det.bbox.y,
                det.bbox.w,
                det.bbox.h,
                det.track_id,
            )
            for det in detections
        )
        target_key = None
        if target is not None:
            bbox = target.bbox
            target_key = (
                target.target_id,
                bbox.x,
                bbox.y,
                bbox.w,
                bbox.h,
            )
        return (
            id(raw),
            mode.value,
            self._last_command,
            detection_key,
            target_key,
        )

    def _render_overlay(self, frame: np.ndarray, detections, target, mode: ControlMode) -> np.ndarray:
        h, w = frame.shape[:2]
        if mode in {ControlMode.FOLLOW_PERSON, ControlMode.INSPECT_SCENE}:
            self._draw_reticle(frame, w // 2, h // 2, active=target is not None)

        for det in detections:
            color = (84, 188, 255)
            if target and det.bbox == target.bbox:
                color = (80, 255, 170)
            x, y, bw, bh = det.bbox.x, det.bbox.y, det.bbox.w, det.bbox.h
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            label = f"{det.label.upper()} {int(det.confidence * 100)}%"
            (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            chip_top = max(0, y - text_h - 12)
            chip_bottom = max(text_h + 8, y)
            chip_right = min(w - 1, x + text_w + 12)
            cv2.rectangle(frame, (x, chip_top), (chip_right, chip_bottom), color, -1)
            cv2.putText(
                frame,
                label,
                (x + 6, chip_bottom - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (6, 14, 24),
                1,
                cv2.LINE_AA,
            )

        if target:
            cx = int(target.bbox.center_x)
            cy = int(target.bbox.center_y)
            cv2.circle(frame, (cx, cy), 7, (32, 255, 96), 2)
            cv2.putText(
                frame,
                f"TRACK #{target.target_id}",
                (max(12, target.bbox.x), max(22, target.bbox.y - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (32, 255, 96),
                1,
                cv2.LINE_AA,
            )

        return frame

    @staticmethod
    def _draw_reticle(frame: np.ndarray, cx: int, cy: int, active: bool = False) -> None:
        color = (92, 150, 188) if not active else (86, 222, 255)
        gap = 16
        arm = 46
        thickness = 1 if not active else 2
        cv2.line(frame, (cx - arm, cy), (cx - gap, cy), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (cx + gap, cy), (cx + arm, cy), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (cx, cy - arm), (cx, cy - gap), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (cx, cy + gap), (cx, cy + arm), color, thickness, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), 8, color, 1, cv2.LINE_AA)

    def _publish_snapshot(self, frame, detections, target, mode: ControlMode) -> None:
        now = time.monotonic()
        if self._last_loop:
            dt = max(1e-3, now - self._last_loop)
            self._fps = (0.85 * self._fps) + (0.15 * (1.0 / dt)) if self._fps else (1.0 / dt)
        self._last_loop = now

        snapshot = VisionSnapshot(
            frame=frame,
            detections=list(detections),
            target=target,
            mode=mode,
            fps=self._fps,
            source_fps=self._vision_stream.source_fps(),
            last_command=self._last_command,
            links=self._link_states.copy(),
        )
        with self._lock:
            self._latest_snapshot = snapshot
        bus.emit(SystemEvents.FRAME_READY, snapshot)

    def _on_connection_status(self, status) -> None:
        if status is None:
            return
        channel = getattr(status, "channel", None)
        state = getattr(status, "state", None)
        if channel in self._link_states and state is not None:
            self._link_states[channel] = state
