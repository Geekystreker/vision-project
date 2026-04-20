from __future__ import annotations

import math
import time

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import BoundingBox, Detection, TrackedTarget


class TargetTracker:
    """Persistent target-lock tracker based on detector-provided track IDs."""

    def __init__(self, config: RoverConfig) -> None:
        self._config = config
        self._current: TrackedTarget | None = None
        self._locked_target_id: int | None = None
        self._locked_track_id: int | None = None
        self._logical_target_serial = 0
        self._lost_frames = 0
        self._max_lost_frames = max(2, config.max_target_lost_frames)
        self._acquisition_frames_required = max(1, int(getattr(config, "target_acquisition_frames", 1)))
        self._rebind_frames_required = max(1, int(getattr(config, "target_rebind_frames", 2)))
        self._pending_candidate: Detection | None = None
        self._pending_candidate_frames = 0
        self._pending_rebind: Detection | None = None
        self._pending_rebind_frames = 0

    def update(self, detections: list[Detection], frame_w: int, frame_h: int) -> TrackedTarget | None:
        candidates = [
            item
            for item in detections
            if (item.label or "").strip().lower() == self._config.target_label.lower()
            and item.bbox.w > 0
            and item.bbox.h > 0
        ]
        if not candidates:
            return self._handle_target_missing()

        if self._locked_target_id is None:
            selected = self._acquire_target(candidates, frame_w, frame_h)
            if selected is None:
                return self._handle_target_missing()
            confirmed = self._confirm_candidate(selected, self._acquisition_frames_required)
            if confirmed is None:
                self._current = None
                return None
            self._reset_pending_candidate()
            return self._lock_target(confirmed, stable_frames=self._acquisition_frames_required)

        selected = None
        if self._locked_track_id is not None:
            same_track = next((item for item in candidates if item.track_id == self._locked_track_id), None)
            if same_track is not None and self._is_valid_locked_update(same_track):
                selected = same_track
        if selected is None:
            rebind = self._rebind_target(candidates, frame_w, frame_h)
            if rebind is not None:
                selected = self._confirm_rebind(rebind)
        if selected is None:
            return self._handle_target_missing(candidates, frame_w, frame_h)

        self._reset_pending_rebind()
        previous_stable_frames = self._current.stable_frames if self._current is not None else 0
        return self._lock_target(selected, stable_frames=previous_stable_frames + 1, reuse_logical_id=True)

    def clear(self) -> None:
        self._current = None
        self._locked_target_id = None
        self._locked_track_id = None
        self._lost_frames = 0
        self._reset_pending_candidate()
        self._reset_pending_rebind()
        bus.emit(SystemEvents.TRACK_TARGET_CHANGED, None)

    def current_target(self) -> TrackedTarget | None:
        return self._current

    def locked_target_id(self) -> int | None:
        return self._locked_target_id

    def _handle_target_missing(
        self,
        candidates: list[Detection] | None = None,
        frame_w: int | None = None,
        frame_h: int | None = None,
    ) -> TrackedTarget | None:
        if self._locked_target_id is None:
            self._current = None
            bus.emit(SystemEvents.TRACK_TARGET_CHANGED, None)
            return None

        self._lost_frames += 1
        if self._current is not None:
            self._current = TrackedTarget(
                target_id=self._current.target_id,
                detection=self._current.detection,
                stable_frames=self._current.stable_frames,
                lost_frames=self._lost_frames,
                last_seen=self._current.last_seen,
                source_track_id=self._current.source_track_id,
            )
        if self._lost_frames > self._max_lost_frames:
            self.clear()
            if candidates and frame_w is not None and frame_h is not None:
                selected = self._acquire_target(candidates, frame_w, frame_h)
                if selected is not None:
                    confirmed = self._confirm_candidate(selected, self._acquisition_frames_required)
                    if confirmed is not None:
                        self._reset_pending_candidate()
                        return self._lock_target(confirmed, stable_frames=self._acquisition_frames_required)
            return None
        bus.emit(SystemEvents.TRACK_TARGET_CHANGED, None)
        return None

    def _lock_target(
        self,
        detection: Detection,
        *,
        stable_frames: int,
        reuse_logical_id: bool = False,
    ) -> TrackedTarget:
        if reuse_logical_id and self._current is not None:
            detection = self._stabilize_detection(self._current.detection, detection)
        if not reuse_logical_id or self._locked_target_id is None:
            self._logical_target_serial += 1
            self._locked_target_id = self._logical_target_serial
        self._locked_track_id = detection.track_id
        self._lost_frames = 0
        self._current = TrackedTarget(
            target_id=self._locked_target_id,
            detection=detection,
            source_track_id=detection.track_id,
            stable_frames=stable_frames,
            lost_frames=0,
            last_seen=time.monotonic(),
        )
        bus.emit(SystemEvents.TRACK_TARGET_CHANGED, self._current)
        return self._current

    def _stabilize_detection(self, previous: Detection, current: Detection) -> Detection:
        alpha = max(0.0, min(1.0, float(self._config.target_box_smoothing_alpha)))
        if alpha >= 1.0:
            return current

        prev_box = previous.bbox
        curr_box = current.bbox
        center_distance = math.hypot(curr_box.center_x - prev_box.center_x, curr_box.center_y - prev_box.center_y)
        prev_diag = max(1.0, math.hypot(prev_box.w, prev_box.h))
        area_ratio = current.area / max(1.0, float(previous.area))

        box_alpha = alpha
        if center_distance <= (prev_diag * 0.45) and (area_ratio < 0.60 or area_ratio > 1.65):
            box_alpha = min(alpha, 0.10)

        x = int(round((prev_box.x * (1.0 - box_alpha)) + (curr_box.x * box_alpha)))
        y = int(round((prev_box.y * (1.0 - box_alpha)) + (curr_box.y * box_alpha)))
        w = max(1, int(round((prev_box.w * (1.0 - box_alpha)) + (curr_box.w * box_alpha))))
        h = max(1, int(round((prev_box.h * (1.0 - box_alpha)) + (curr_box.h * box_alpha))))

        return Detection(
            label=current.label,
            confidence=current.confidence,
            bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=current.bbox.confidence),
            source=current.source,
            class_id=current.class_id,
            track_id=current.track_id,
        )

    def _confirm_candidate(self, detection: Detection, required_frames: int) -> Detection | None:
        required_frames = max(1, int(required_frames))
        if self._pending_candidate is None or not self._detections_match_for_confirmation(
            self._pending_candidate,
            detection,
        ):
            self._pending_candidate = detection
            self._pending_candidate_frames = 1
        else:
            self._pending_candidate = self._stabilize_detection(self._pending_candidate, detection)
            self._pending_candidate_frames += 1
        if self._pending_candidate_frames >= required_frames:
            return self._pending_candidate
        return None

    def _confirm_rebind(self, detection: Detection) -> Detection | None:
        if self._pending_rebind is None or not self._detections_match_for_confirmation(
            self._pending_rebind,
            detection,
        ):
            self._pending_rebind = detection
            self._pending_rebind_frames = 1
        else:
            self._pending_rebind = self._stabilize_detection(self._pending_rebind, detection)
            self._pending_rebind_frames += 1
        if self._pending_rebind_frames >= self._rebind_frames_required:
            return self._pending_rebind
        return None

    def _is_valid_locked_update(self, detection: Detection) -> bool:
        if self._current is None:
            return True

        previous = self._current.bbox
        current = detection.bbox
        area_ratio = current.area / max(1.0, float(previous.area))
        if area_ratio < 0.28 or area_ratio > 3.20:
            return False

        prev_diag = max(1.0, math.hypot(previous.w, previous.h))
        center_distance = math.hypot(current.center_x - previous.center_x, current.center_y - previous.center_y)
        if self._iou(previous, current) >= 0.03:
            return True
        return center_distance <= (prev_diag * 0.62)

    def _rebind_target(self, candidates: list[Detection], frame_w: int, frame_h: int) -> Detection | None:
        if self._current is None:
            return None

        previous_box = self._current.bbox
        frame_diag_sq = max(1.0, float(frame_w * frame_w + frame_h * frame_h))
        best: tuple[float, Detection] | None = None

        for detection in candidates:
            iou = self._iou(previous_box, detection.bbox)
            center_dx = detection.bbox.center_x - previous_box.center_x
            center_dy = detection.bbox.center_y - previous_box.center_y
            center_distance_sq = (center_dx * center_dx) + (center_dy * center_dy)
            center_score = center_distance_sq / frame_diag_sq
            area_ratio = detection.area / max(1.0, float(previous_box.area))

            if iou < self._config.track_iou_threshold and center_score > 0.012:
                continue
            if area_ratio < 0.48 or area_ratio > 2.05:
                continue

            score = center_score - (iou * 0.75)
            if best is None or score < best[0]:
                best = (score, detection)

        return best[1] if best is not None else None

    def _detections_match_for_confirmation(self, previous: Detection, current: Detection) -> bool:
        if previous.track_id is not None and current.track_id is not None:
            if previous.track_id == current.track_id:
                return True

        area_ratio = current.area / max(1.0, float(previous.area))
        if area_ratio < 0.45 or area_ratio > 2.20:
            return False

        iou = self._iou(previous.bbox, current.bbox)
        if iou >= 0.10:
            return True

        prev_diag = max(1.0, math.hypot(previous.bbox.w, previous.bbox.h))
        center_distance = math.hypot(
            current.bbox.center_x - previous.bbox.center_x,
            current.bbox.center_y - previous.bbox.center_y,
        )
        return center_distance <= (prev_diag * 0.40)

    def _reset_pending_candidate(self) -> None:
        self._pending_candidate = None
        self._pending_candidate_frames = 0

    def _reset_pending_rebind(self) -> None:
        self._pending_rebind = None
        self._pending_rebind_frames = 0

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

    @staticmethod
    def _acquire_target(candidates: list[Detection], frame_w: int, frame_h: int) -> Detection | None:
        center_x = frame_w / 2.0
        center_y = frame_h / 2.0
        return min(
            candidates,
            key=lambda item: (
                (item.bbox.center_x - center_x) ** 2 + (item.bbox.center_y - center_y) ** 2,
                -item.area,
            ),
        )
