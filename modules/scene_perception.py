from __future__ import annotations

from collections import Counter

from modules.rover_types import Detection


class ScenePerceptionService:
    """Turn object detections into short spoken summaries."""

    def describe(self, detections: list[Detection]) -> str:
        if not detections:
            return "I do not have a confident object detection in front of me right now."

        counts = Counter(det.label for det in detections)
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        parts = []
        for label, count in ordered[:4]:
            quantity = "1" if count == 1 else str(count)
            noun = label if count == 1 else f"{label}s"
            parts.append(f"{quantity} {noun}")

        nearest = max(detections, key=lambda det: det.area)
        summary = ", ".join(parts)
        return (
            f"I can currently see {summary}. "
            f"The closest visible object looks like {nearest.label}."
        )
