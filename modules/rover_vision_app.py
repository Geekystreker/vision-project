from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.autonomous_controller import AutonomousController
from modules.control_arbiter import ControlArbiter
from modules.detection_engine import DetectionEngine
from modules.hud_renderer import JarvisHUDRenderer
from modules.motor_controller import MotorController
from modules.rover_control import RoverController
from modules.rover_types import BoundingBox, ConnectionState, ConnectionStatus, ControlMode, Detection, VisionSnapshot
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
        self._latest_snapshot = VisionSnapshot(frame=None)
        self._last_command = "S"
        self._fps = 0.0
        self._last_loop = 0.0
        self._latest_inference_ms = 0.0
        self._latest_camera_frame: Optional[np.ndarray] = None
        self._frame_handoff_lock = threading.Lock()
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
        self._last_servo_connection_notice = 0.0
        self._last_manual_servo_command_at = 0.0
        self._camera_missing_notice_emitted = False
        self._link_states = {
            "camera": ConnectionState.DISCONNECTED,
            "detector": ConnectionState.DISCONNECTED,
            "motor": ConnectionState.DISCONNECTED,
            "ollama": ConnectionState.DISCONNECTED,
            "servo": ConnectionState.DISCONNECTED,
        }

        self._vision_stream = VisionStream(config.vision_stream_url, config)
        self._servo_controller = ServoController(config.servo_url, config)
        self._motor_controller = MotorController(config.motor_url, config)
        self._rover_controller = RoverController()
        self._detection_engine = DetectionEngine(config)
        self._detection_loaded = False
        self._last_detection_load_attempt = 0.0
        self._target_tracker = TargetTracker(config)
        self._tracking_controller = TrackingController(
            config,
            self._rover_controller,
            self._servo_controller,
            self._motor_controller,
        )
        self._autonomous_controller = AutonomousController(
            config,
            self._rover_controller,
            self._motor_controller,
        )
        self._hud_renderer = JarvisHUDRenderer()
        self._scene_perception = ScenePerceptionService()
        self._lock = threading.Lock()

        bus.subscribe(SystemEvents.CONNECTION_STATUS_CHANGED, self._on_connection_status)

    def run(self) -> None:
        self._running = True
        self._servo_controller.start()
        self._motor_controller.start()
        self._vision_stream.start()
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

    def adjust_servo(self, *, pan_delta: float = 0, tilt_delta: float = 0, source: str = "KEYBOARD") -> tuple[int, int]:
        if source == "KEYBOARD":
            self._arbiter.begin_keyboard_override()
        elif source != "VOICE":
            self._arbiter.begin_keyboard_override()
        elif not self._arbiter.allow_voice():
            return 90, 90
        min_interval = max(0.03, 1.0 / max(1, self._config.servo_send_hz))
        now = time.monotonic()
        if source == "KEYBOARD" and (now - self._last_manual_servo_command_at) < min_interval:
            return self._tracking_controller.current_angles()
        pan, tilt = self._tracking_controller.manual_pan_tilt(pan_delta=pan_delta, tilt_delta=tilt_delta)
        self._last_manual_servo_command_at = now
        is_connected = getattr(self._servo_controller, "is_connected", lambda: True)
        if not is_connected():
            if (now - self._last_servo_connection_notice) >= 2.0:
                self._last_servo_connection_notice = now
                bus.emit(
                    SystemEvents.LOG_MESSAGE,
                    "[Control] Servo command queued. Waiting for the ESP32 Jarvis websocket to connect.",
                )
        else:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[Control] Servo moved to pan {pan}, tilt {tilt}.")
        return pan, tilt

    def toggle_follow_mode(self) -> ControlMode:
        mode = self._arbiter.toggle_follow_mode()
        if mode != ControlMode.FOLLOW_PERSON:
            self._tracking_controller.reset()
            self._autonomous_controller.reset()
            self._target_tracker.clear()
            self._last_command = "S"
        return mode

    def toggle_autonomous_mode(self) -> ControlMode:
        mode = self._arbiter.toggle_autonomous_mode()
        if mode != ControlMode.AUTONOMOUS:
            self._autonomous_controller.reset()
            self._last_command = "S"
        else:
            self._tracking_controller.reset()
            self._target_tracker.clear()
        return mode

    def engage_autonomous_target_lock(self) -> ControlMode:
        self._tracking_controller.reset()
        self._autonomous_controller.reset()
        self._target_tracker.clear()
        self._last_command = "S"
        mode = self._arbiter.set_autonomous_mode()
        self._log_autonomous_readiness()
        return mode

    def set_follow_mode(self) -> ControlMode:
        self._autonomous_controller.reset()
        return self._arbiter.set_follow_mode()

    def set_autonomous_mode(self) -> ControlMode:
        return self.engage_autonomous_target_lock()

    def set_manual_mode(self) -> ControlMode:
        mode = self._arbiter.set_manual_mode()
        self._tracking_controller.reset()
        self._autonomous_controller.reset()
        self._target_tracker.clear()
        self._last_command = "S"
        return mode

    def emergency_stop(self) -> None:
        self.send_drive_command("S", source="E_STOP")
        self._tracking_controller.reset()
        self._autonomous_controller.reset()
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

        frame = self._orient_frame(frame)
        self._camera_missing_notice_emitted = False

        with self._frame_handoff_lock:
            self._latest_camera_frame = frame.copy()

        self._schedule_detection(mode)

        with self._detection_state_lock:
            detections = list(self._latest_detections)
            target = self._latest_target

        if mode in {ControlMode.FOLLOW_PERSON, ControlMode.AUTONOMOUS} and self._vision_stream.frame_age() > self._config.frame_stale_seconds:
            self._tracking_controller.reset()
            self._autonomous_controller.reset()
            self._last_command = "S"

        display = self._render_overlay(frame.copy(), detections, target, mode)
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        self._publish_snapshot(rgb, detections, target, mode)

    def _handle_missing_frame(self, mode: ControlMode) -> None:
        if self._target_tracker.current_target() is not None:
            self._target_tracker.clear()
        with self._detection_state_lock:
            self._latest_detections = []
            self._latest_target = None
            self._detection_frame = None
            self._detection_busy = False
        with self._frame_handoff_lock:
            self._latest_camera_frame = None
        if mode in {ControlMode.FOLLOW_PERSON, ControlMode.AUTONOMOUS}:
            self._tracking_controller.reset()
            self._autonomous_controller.reset()
            self._last_command = "S"
        elif (
            not self._camera_missing_notice_emitted
            and (
                self._link_states.get("motor") == ConnectionState.CONNECTED
                or self._link_states.get("servo") == ConnectionState.CONNECTED
            )
        ):
            self._camera_missing_notice_emitted = True
            bus.emit(
                SystemEvents.LOG_MESSAGE,
                "[RoverVisionApp] Camera unavailable. Driver node controls remain online for manual drive/servo.",
            )

    def _schedule_detection(self, mode: ControlMode) -> None:
        now = time.monotonic()
        if self._detection_busy:
            return
        if (now - self._last_detection_submit) < self._detection_interval:
            return

        with self._frame_handoff_lock:
            if self._latest_camera_frame is None:
                return
            frame = self._latest_camera_frame.copy()

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

            if frame is None:
                with self._detection_state_lock:
                    self._detection_busy = False
                continue

            detections: list[Detection] = []
            target = None
            try:
                self._ensure_detection_loaded()
                if self._detection_loaded:
                    inference_started = time.monotonic()
                    detections = self._detection_engine.detect(frame)
                    self._latest_inference_ms = (time.monotonic() - inference_started) * 1000.0
                else:
                    self._latest_inference_ms = 0.0

                if scale_x != 1.0 or scale_y != 1.0:
                    detections = [self._scale_detection(det, scale_x, scale_y, frame_w, frame_h) for det in detections]
                target = self._target_tracker.update(detections, frame_w, frame_h)
                bus.emit(SystemEvents.DETECTIONS_UPDATED, detections)
                if not detections:
                    bus.emit(SystemEvents.ROVER_NO_DETECTION, None)
                self._apply_detection_actions(mode, target, detections, frame_w, frame_h)
            except Exception as exc:
                self._latest_inference_ms = 0.0
                bus.emit(SystemEvents.LOG_MESSAGE, f"[RoverVisionApp] detection loop error: {exc}")
            finally:
                with self._detection_state_lock:
                    self._latest_detections = list(detections)
                    self._latest_target = target
                    self._detection_busy = False

    def _apply_detection_actions(
        self,
        mode: ControlMode,
        target,
        detections: list[Detection],
        frame_w: int,
        frame_h: int,
    ) -> None:
        if mode == ControlMode.FOLLOW_PERSON:
            if self._arbiter.allow_autonomy():
                self._last_command = self._tracking_controller.update(target, frame_w, frame_h)
            return

        if mode == ControlMode.AUTONOMOUS:
            if self._arbiter.allow_autonomy():
                self._tracking_controller.update_servos(target, frame_w, frame_h)
                self._last_command = self._autonomous_controller.update(detections, frame_w, frame_h)
            return

        if mode != ControlMode.INSPECT_SCENE and self._tracking_controller.target_locked():
            self._tracking_controller.clear_lock_state()

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

    def _orient_frame(self, frame: np.ndarray) -> np.ndarray:
        flip_code = self._config.camera_flip_code
        if flip_code is None:
            return frame
        return cv2.flip(frame, int(flip_code))

    def _ensure_detection_loaded(self) -> None:
        if self._detection_loaded:
            return
        now = time.monotonic()
        if (now - self._last_detection_load_attempt) < 3.0:
            return
        with self._detection_load_lock:
            if self._detection_loaded:
                return
            if (now - self._last_detection_load_attempt) < 3.0:
                return
            self._last_detection_load_attempt = now
            self._detection_engine.load()
            self._detection_loaded = self._detection_engine.ready()
            detector_state = ConnectionState.CONNECTED if self._detection_loaded else ConnectionState.ERROR
            detail = "loaded" if self._detection_loaded else "not loaded"
            bus.emit(
                SystemEvents.CONNECTION_STATUS_CHANGED,
                ConnectionStatus(channel="detector", state=detector_state, detail=detail),
            )

    def _preload_detection(self) -> None:
        try:
            self._ensure_detection_loaded()
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[RoverVisionApp] detector preload failed: {exc}")

    def _render_overlay(self, frame: np.ndarray, detections, target, mode: ControlMode) -> np.ndarray:
        servo_pan, servo_tilt = self._tracking_controller.current_angles()
        target_coords = None
        if target is not None:
            target_coords = (int(target.bbox.center_x), int(target.bbox.center_y))
        predicted_coords = self._tracking_controller.predicted_point()
        predicted_path = self._tracking_controller.prediction_path()
        telemetry = {
            "fps": self._fps,
            "source_fps": self._vision_stream.source_fps(),
            "inference_ms": self._latest_inference_ms,
            "servo_pan": servo_pan,
            "servo_tilt": servo_tilt,
            "target_coords": target_coords,
            "predicted_target_coords": predicted_coords,
            "predicted_target_path": predicted_path,
            "network_latency_ms": self._tracking_controller.latency_ms(),
            "target_locked": self._tracking_controller.target_locked(),
            "locked_target_id": self._target_tracker.locked_target_id(),
            "last_command": self._last_command,
        }
        return self._hud_renderer.render(frame, list(detections), target, mode, telemetry)

    def _publish_snapshot(self, frame, detections, target, mode: ControlMode) -> None:
        now = time.monotonic()
        if self._last_loop:
            dt = max(1e-3, now - self._last_loop)
            self._fps = (0.85 * self._fps) + (0.15 * (1.0 / dt)) if self._fps else (1.0 / dt)
        self._last_loop = now
        servo_pan, servo_tilt = self._tracking_controller.current_angles()
        target_coords = None
        if target is not None:
            target_coords = (int(target.bbox.center_x), int(target.bbox.center_y))
        predicted_coords = self._tracking_controller.predicted_point()

        snapshot = VisionSnapshot(
            frame=frame,
            detections=list(detections),
            target=target,
            mode=mode,
            fps=self._fps,
            source_fps=self._vision_stream.source_fps(),
            inference_ms=self._latest_inference_ms,
            last_command=self._last_command,
            servo_pan=servo_pan,
            servo_tilt=servo_tilt,
            target_coords=target_coords,
            predicted_target_coords=predicted_coords,
            predicted_target_path=self._tracking_controller.prediction_path(),
            network_latency_ms=self._tracking_controller.latency_ms(),
            target_locked=self._tracking_controller.target_locked(),
            locked_target_id=self._target_tracker.locked_target_id(),
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

    def _log_autonomous_readiness(self) -> None:
        missing = [
            channel
            for channel in ("camera", "detector", "servo", "motor")
            if self._link_states.get(channel) != ConnectionState.CONNECTED
        ]
        if missing:
            bus.emit(
                SystemEvents.LOG_MESSAGE,
                "[Autonomous] Target-lock mode armed. Waiting on: " + ", ".join(missing) + ".",
            )
            return
        bus.emit(
            SystemEvents.LOG_MESSAGE,
            "[Autonomous] Target-lock mode engaged. YOLO will lock target and keep servos centered.",
        )
