from __future__ import annotations

import math
import time
from typing import Sequence

import cv2
import numpy as np

from modules.rover_types import ControlMode, Detection, TrackedTarget


class JarvisHUDRenderer:
    def __init__(self) -> None:
        self._boot_time = time.monotonic()

    def render(
        self,
        frame: np.ndarray,
        detections: Sequence[Detection],
        target: TrackedTarget | None,
        mode: ControlMode,
        telemetry: dict[str, object],
    ) -> np.ndarray:
        hud = frame.copy()
        h, w = hud.shape[:2]
        phase = time.monotonic() - self._boot_time
        active_lock = bool(telemetry.get("target_locked", False) and target is not None)

        self._draw_background_grid(hud, phase)
        self._draw_heading_bands(hud)

        locked_track_id = getattr(target, "source_track_id", None) if target is not None else None
        for detection in detections:
            is_locked = detection.track_id is not None and detection.track_id == locked_track_id
            if is_locked:
                continue
            self._draw_detection_box(hud, detection, is_locked)

        if target is not None:
            self._draw_detection_box(hud, target.detection, active_lock)
            self._draw_target_link(hud, target, phase, active_lock)
        self._draw_kalman_overlay(hud, telemetry, phase)

        self._draw_telemetry_cards(hud, telemetry, mode, active_lock)
        self._draw_corner_frame(hud, phase)
        return hud

    @staticmethod
    def _draw_background_grid(frame: np.ndarray, phase: float) -> None:
        h, w = frame.shape[:2]
        grid = np.zeros_like(frame)
        spacing = 40
        pulse = int(12 + 8 * (0.5 + 0.5 * math.sin(phase * 2.2)))
        color = (20, 60 + pulse, 110 + pulse)

        for x in range(0, w, spacing):
            cv2.line(grid, (x, 0), (x, h), color, 1, cv2.LINE_AA)
        for y in range(0, h, spacing):
            cv2.line(grid, (0, y), (w, y), color, 1, cv2.LINE_AA)

        vignette = np.zeros_like(frame)
        cv2.rectangle(vignette, (0, 0), (w, h), (6, 10, 18), -1)
        cv2.addWeighted(frame, 0.84, vignette, 0.16, 0.0, frame)
        cv2.addWeighted(frame, 1.0, grid, 0.12, 0.0, frame)

    @staticmethod
    def _draw_heading_bands(frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        top = np.zeros_like(frame)
        bottom = np.zeros_like(frame)
        cv2.rectangle(top, (0, 0), (w, 62), (8, 18, 30), -1)
        cv2.rectangle(bottom, (0, h - 78), (w, h), (7, 14, 24), -1)
        cv2.addWeighted(frame, 1.0, top, 0.35, 0.0, frame)
        cv2.addWeighted(frame, 1.0, bottom, 0.30, 0.0, frame)

    @staticmethod
    def _draw_detection_box(frame: np.ndarray, detection: Detection, active: bool) -> None:
        x, y, w, h = detection.bbox.x, detection.bbox.y, detection.bbox.w, detection.bbox.h
        if w <= 0 or h <= 0:
            return
        color = (44, 255, 106) if active else (128, 136, 142)
        thickness = 2 if active else 1
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness, cv2.LINE_AA)
        prefix = "LOCKED" if active else detection.label.upper()
        label = f"{prefix} {int(detection.confidence * 100)}%"
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.48, 1)
        chip_top = max(0, y - text_h - 12)
        chip_bottom = max(text_h + 8, y)
        chip_right = min(frame.shape[1] - 1, x + text_w + 14)
        cv2.rectangle(frame, (x, chip_top), (chip_right, chip_bottom), color, -1, cv2.LINE_AA)
        cv2.putText(
            frame,
            label,
            (x + 7, chip_bottom - 6),
            cv2.FONT_HERSHEY_DUPLEX,
            0.48,
            (8, 22, 10),
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _draw_kalman_overlay(frame: np.ndarray, telemetry: dict[str, object], phase: float) -> None:
        point = telemetry.get("predicted_target_coords")
        path = telemetry.get("predicted_target_path")
        if isinstance(path, tuple) and len(path) >= 2:
            pts = [
                (int(x), int(y))
                for item in path
                if isinstance(item, tuple) and len(item) == 2
                for x, y in (item,)
            ]
            for start, end in zip(pts, pts[1:]):
                cv2.line(frame, start, end, (36, 218, 255), 1, cv2.LINE_AA)

        if not (isinstance(point, tuple) and len(point) == 2):
            return
        x, y = int(point[0]), int(point[1])
        radius = 11 + int(3 * (0.5 + 0.5 * math.sin(phase * 8.0)))
        color = (24, 216, 255)
        cv2.circle(frame, (x, y), radius, color, 2, cv2.LINE_AA)
        cv2.line(frame, (x - 18, y), (x - 6, y), color, 1, cv2.LINE_AA)
        cv2.line(frame, (x + 6, y), (x + 18, y), color, 1, cv2.LINE_AA)
        cv2.line(frame, (x, y - 18), (x, y - 6), color, 1, cv2.LINE_AA)
        cv2.line(frame, (x, y + 6), (x, y + 18), color, 1, cv2.LINE_AA)
        cv2.putText(
            frame,
            "KALMAN",
            (max(10, x + 14), max(18, y - 12)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.44,
            color,
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _draw_target_link(frame: np.ndarray, target: TrackedTarget, phase: float, active: bool) -> None:
        h, w = frame.shape[:2]
        tx = int(target.bbox.center_x)
        ty = int(target.bbox.center_y)
        center = (w // 2, h // 2)
        color = (90, 255, 170) if active else (250, 212, 82)
        cv2.line(frame, center, (tx, ty), color, 1, cv2.LINE_AA)
        cv2.circle(frame, (tx, ty), 12 + int(3 * math.sin(phase * 7.0)), color, 2, cv2.LINE_AA)
        cv2.putText(
            frame,
            "TARGET LOCK",
            (max(12, target.bbox.x), min(h - 14, target.bbox.y + target.bbox.h + 22)),
            cv2.FONT_HERSHEY_DUPLEX,
            0.54,
            color,
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def _draw_telemetry_cards(
        frame: np.ndarray,
        telemetry: dict[str, object],
        mode: ControlMode,
        active_lock: bool,
    ) -> None:
        h, w = frame.shape[:2]
        panel = np.zeros_like(frame)
        cv2.rectangle(panel, (18, 16), (388, 136), (10, 18, 32), -1)
        cv2.rectangle(panel, (w - 258, 16), (w - 18, 156), (10, 18, 32), -1)
        cv2.addWeighted(frame, 1.0, panel, 0.36, 0.0, frame)

        fps = float(telemetry.get("fps", 0.0) or 0.0)
        source_fps = float(telemetry.get("source_fps", 0.0) or 0.0)
        inference_ms = float(telemetry.get("inference_ms", 0.0) or 0.0)
        servo_pan = int(telemetry.get("servo_pan", 90) or 90)
        servo_tilt = int(telemetry.get("servo_tilt", 90) or 90)
        latency_ms = float(telemetry.get("network_latency_ms", 0.0) or 0.0)
        target_coords = telemetry.get("target_coords")
        predicted_coords = telemetry.get("predicted_target_coords")
        last_command = str(telemetry.get("last_command", "S") or "S")
        lock_text = "LOCKED TARGET" if telemetry.get("locked_target_id") is not None else "LOCKED TARGET NONE"

        left_lines = (
            f"MODE   {mode.value}",
            f"FPS    {fps:05.1f} / SRC {source_fps:05.1f}",
            f"AI     {inference_ms:05.1f} ms",
            lock_text,
            f"CMD    {last_command}",
        )
        for index, text in enumerate(left_lines):
            cv2.putText(
                frame,
                text,
                (34, 42 + (index * 20)),
                cv2.FONT_HERSHEY_DUPLEX,
                0.56,
                (240, 225, 202),
                1,
                cv2.LINE_AA,
            )

        coord_text = "NONE"
        if isinstance(target_coords, tuple) and len(target_coords) == 2:
            coord_text = f"{target_coords[0]:04d},{target_coords[1]:04d}"
        elif isinstance(predicted_coords, tuple) and len(predicted_coords) == 2:
            coord_text = f"P {predicted_coords[0]:04d},{predicted_coords[1]:04d}"

        right_lines = (
            f"PAN    {servo_pan:03d}",
            f"TILT   {servo_tilt:03d}",
            f"TARGET {coord_text}",
            f"NET    {latency_ms:05.1f} ms",
        )
        for index, text in enumerate(right_lines):
            cv2.putText(
                frame,
                text,
                (w - 238, 42 + (index * 24)),
                cv2.FONT_HERSHEY_DUPLEX,
                0.56,
                (170, 241, 255),
                1,
                cv2.LINE_AA,
            )

    @staticmethod
    def _draw_corner_frame(frame: np.ndarray, phase: float) -> None:
        h, w = frame.shape[:2]
        color = (72, 202, 255)
        glow = 40 + int(16 * (0.5 + 0.5 * math.sin(phase * 3.5)))
        edge = 34 + glow // 6

        for x1, y1, x2, y2 in (
            (20, 20, 20 + edge, 20),
            (20, 20, 20, 20 + edge),
            (w - 20 - edge, 20, w - 20, 20),
            (w - 20, 20, w - 20, 20 + edge),
            (20, h - 20, 20 + edge, h - 20),
            (20, h - 20 - edge, 20, h - 20),
            (w - 20 - edge, h - 20, w - 20, h - 20),
            (w - 20, h - 20 - edge, w - 20, h - 20),
        ):
            cv2.line(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
