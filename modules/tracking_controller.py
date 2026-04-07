from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.motor_controller import MotorController
from modules.rover_control import RoverController
from modules.rover_types import TrackedTarget
from modules.servo_controller import ServoController


@dataclass(slots=True)
class TrackingState:
    pan_angle: float = 90.0
    tilt_angle: float = 90.0
    last_detection_time: float = field(default_factory=time.monotonic)


class TrackingController:
    """Drive and pan / tilt follow logic for the active tracked target."""

    def __init__(
        self,
        config: RoverConfig,
        rover: RoverController,
        servo: ServoController,
        motor: MotorController,
    ) -> None:
        self._config = config
        self._rover = rover
        self._servo = servo
        self._motor = motor
        self._state = TrackingState()

    def update(self, target: Optional[TrackedTarget], frame_w: int, frame_h: int) -> str:
        try:
            if target is None:
                elapsed = time.monotonic() - self._state.last_detection_time
                if elapsed > self._config.no_detection_timeout:
                    return self._dispatch_drive("S")
                return "IDLE"

            self._state.last_detection_time = time.monotonic()
            offset_x, offset_y = self._compute_offsets(target, frame_w, frame_h)

            if abs(offset_x) > self._config.dead_zone_px:
                self._state.pan_angle -= offset_x * self._config.pan_tilt_gain
                self._state.pan_angle = self._clamp_angle(self._state.pan_angle)
                self._servo.send(f"Pan,{int(self._state.pan_angle)}")

            if abs(offset_y) > self._config.dead_zone_px:
                self._state.tilt_angle += offset_y * self._config.pan_tilt_gain
                self._state.tilt_angle = self._clamp_angle(self._state.tilt_angle)
                self._servo.send(f"Tilt,{int(self._state.tilt_angle)}")

            return self._dispatch_drive(self._drive_command(target, frame_w, frame_h))
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[TrackingController] update error: {exc}")
            return "ERROR"

    def manual_pan_tilt(self, *, pan_delta: int = 0, tilt_delta: int = 0) -> tuple[int, int]:
        self._state.pan_angle = self._clamp_angle(self._state.pan_angle + pan_delta)
        self._state.tilt_angle = self._clamp_angle(self._state.tilt_angle + tilt_delta)
        if pan_delta:
            self._servo.send(f"Pan,{int(self._state.pan_angle)}")
        if tilt_delta:
            self._servo.send(f"Tilt,{int(self._state.tilt_angle)}")
        return int(self._state.pan_angle), int(self._state.tilt_angle)

    def reset(self) -> None:
        try:
            self._dispatch_drive("S")
            self._servo.send("Pan,90")
            self._servo.send("Tilt,90")
            self._state.pan_angle = 90.0
            self._state.tilt_angle = 90.0
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[TrackingController] reset error: {exc}")

    def _dispatch_drive(self, command: str) -> str:
        self._rover.send_command(command)
        self._motor.send(command)
        return command

    def _clamp_angle(self, angle: float) -> float:
        return max(0.0, min(180.0, angle))

    def _compute_offsets(
        self,
        target: TrackedTarget,
        frame_w: int,
        frame_h: int,
    ) -> tuple[float, float]:
        offset_x = target.bbox.center_x - frame_w / 2
        offset_y = target.bbox.center_y - frame_h / 2
        return offset_x, offset_y

    def _drive_command(self, target: TrackedTarget, frame_w: int, frame_h: int) -> str:
        fraction = target.bbox.area / (frame_w * frame_h)
        if fraction < self._config.bbox_min_fraction:
            return "F"
        if fraction > self._config.bbox_max_fraction:
            return "B"
        return "S"
