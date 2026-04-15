from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass

from config import RoverConfig
from modules.motor_controller import MotorController
from modules.rover_control import RoverController
from modules.rover_types import Detection


@dataclass(slots=True)
class AutonomousState:
    last_command: str = "S"
    last_reason: str = "Standing by."
    turn_until: float = 0.0
    last_turn_command: str = "L"
    clear_frames: int = 0


class AutonomousController:
    """Lightweight scene-driven autonomy using live detections."""

    def __init__(self, config: RoverConfig, rover: RoverController, motor: MotorController) -> None:
        self._config = config
        self._rover = rover
        self._motor = motor
        self._state = AutonomousState()

    def update(self, detections: list[Detection], frame_w: int, frame_h: int) -> str:
        if frame_w <= 0 or frame_h <= 0:
            return self._dispatch("S", "No valid frame geometry.")

        now = time.monotonic()
        command, reason = self._plan_command(detections, frame_w, frame_h, now)
        return self._dispatch(command, reason)

    def reset(self) -> None:
        self._state.turn_until = 0.0
        self._state.clear_frames = 0
        self._dispatch("S", "Autonomy reset.")

    def last_reason(self) -> str:
        return self._state.last_reason

    def _plan_command(
        self,
        detections: list[Detection],
        frame_w: int,
        frame_h: int,
        now: float,
    ) -> tuple[str, str]:
        if now < self._state.turn_until and self._state.last_turn_command in {"L", "R"}:
            direction = "left" if self._state.last_turn_command == "L" else "right"
            return self._state.last_turn_command, f"Finishing a short corrective turn to the {direction}."

        if not detections:
            return self._clear_path_command("No confident obstacles are visible.")

        frame_area = max(1.0, float(frame_w * frame_h))
        left_load = 0.0
        right_load = 0.0
        center_load = 0.0
        notable_labels: Counter[str] = Counter()
        urgent_stop = False

        for detection in detections:
            fraction = detection.area / frame_area
            if fraction < self._config.autonomous_min_detection_fraction:
                continue

            label = (detection.label or "").strip().lower() or "object"
            notable_labels[label] += 1
            weight = max(0.01, fraction * max(0.2, detection.confidence))
            if label == self._config.target_label.lower():
                weight *= 1.2

            left_edge = detection.bbox.x / max(1.0, frame_w)
            right_edge = (detection.bbox.x + detection.bbox.w) / max(1.0, frame_w)
            center_x = detection.bbox.center_x / max(1.0, frame_w)
            overlaps_center = left_edge < 0.68 and right_edge > 0.32

            if overlaps_center:
                center_load += weight * 1.35
            elif center_x < 0.5:
                left_load += weight
            else:
                right_load += weight

            if overlaps_center and fraction >= self._config.autonomous_stop_fraction:
                urgent_stop = True

        if not notable_labels:
            return self._clear_path_command("Only tiny detections are visible.")

        self._state.clear_frames = 0
        primary = notable_labels.most_common(1)[0][0]
        if urgent_stop:
            return "S", f"{primary.capitalize()} is too close ahead, holding position."

        if center_load >= self._config.autonomous_turn_fraction:
            turn = self._choose_turn(left_load, right_load)
            return turn, f"{primary.capitalize()} is blocking the center lane, steering around it."

        lane_bias = left_load - right_load
        if lane_bias >= self._config.autonomous_lane_margin:
            return "R", "Left side is crowded, steering right."
        if lane_bias <= -self._config.autonomous_lane_margin:
            return "L", "Right side is crowded, steering left."

        return self._clear_path_command(f"{primary.capitalize()} is visible but the center path is open.")

    def _clear_path_command(self, ready_reason: str) -> tuple[str, str]:
        self._state.clear_frames += 1
        required = max(1, int(self._config.autonomous_clear_frames_required))
        if self._state.clear_frames < required:
            return "S", f"{ready_reason} Confirming one more frame before moving."
        return "F", f"{ready_reason} Moving forward."

    def _choose_turn(self, left_load: float, right_load: float) -> str:
        if abs(left_load - right_load) <= self._config.autonomous_lane_margin:
            command = "R" if self._state.last_turn_command == "L" else "L"
        else:
            command = "R" if left_load >= right_load else "L"
        self._state.last_turn_command = command
        self._state.turn_until = time.monotonic() + self._config.autonomous_turn_hold_seconds
        return command

    def _dispatch(self, command: str, reason: str) -> str:
        self._state.last_reason = reason
        if command != self._state.last_command:
            self._rover.send_command(command)
            self._motor.send(command)
            self._state.last_command = command
        return command
