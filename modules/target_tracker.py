from __future__ import annotations

import time
from dataclasses import replace

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import BoundingBox, Detection, TrackedTarget


def _iou(first: BoundingBox, second: BoundingBox) -> float:
    x1 = max(first.x, second.x)
    y1 = max(first.y, second.y)
    x2 = min(first.x + first.w, second.x + second.w)
    y2 = min(first.y + first.h, second.y + second.h)
    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    union = first.area + second.area - inter
    if union <= 0:
        return 0.0
    return inter / union


class TargetTracker:
    """Lightweight tracker that keeps follow mode locked on a stable target."""

    def __init__(self, config: RoverConfig) -> None:
        self._config = config
        self._current: TrackedTarget | None = None
        self._next_id = 1

    def update(self, detections: list[Detection]) -> TrackedTarget | None:
        candidates = [
            item
            for item in detections
            if item.label.lower() == self._config.target_label.lower()
        ]
        if not candidates:
            if self._current is not None:
                self._current = replace(
                    self._current,
                    lost_frames=self._current.lost_frames + 1,
                )
                if self._current.lost_frames > self._config.max_target_lost_frames:
                    self._current = None
                    bus.emit(SystemEvents.TRACK_TARGET_CHANGED, None)
            return self._current

        selected = self._select_candidate(candidates)
        if self._current and _iou(self._current.bbox, selected.bbox) >= self._config.track_iou_threshold:
            self._current = TrackedTarget(
                target_id=self._current.target_id,
                detection=selected,
                stable_frames=self._current.stable_frames + 1,
                lost_frames=0,
                last_seen=time.monotonic(),
            )
        else:
            self._current = TrackedTarget(
                target_id=self._next_id,
                detection=selected,
                stable_frames=1,
                lost_frames=0,
                last_seen=time.monotonic(),
            )
            self._next_id += 1

        bus.emit(SystemEvents.TRACK_TARGET_CHANGED, self._current)
        return self._current

    def clear(self) -> None:
        self._current = None
        bus.emit(SystemEvents.TRACK_TARGET_CHANGED, None)

    def current_target(self) -> TrackedTarget | None:
        return self._current

    @staticmethod
    def _select_candidate(candidates: list[Detection]) -> Detection:
        return max(candidates, key=lambda item: item.area)
