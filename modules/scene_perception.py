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
        if nearest.label.lower() == "person":
            return f"Person ahead. I can currently see {summary}."
        return (
            f"I can currently see {summary}. "
            f"The closest visible object looks like {nearest.label}."
        )

    def brief_target_callout(self, detection: Detection | None) -> str:
        if detection is None:
            return ""
        label = (detection.label or "").strip().lower()
        if label == "person":
            return "Person ahead."
        return f"{detection.label.capitalize()} ahead."

    def detection_callout(self, labels: list[str]) -> str:
        normalized = [label.strip().lower() for label in labels if label and label.strip()]
        if not normalized:
            return ""
        if "person" in normalized:
            return "Person detected."
        return "Object detected."

    def live_scene_line(self, labels: list[str], *, locked: bool) -> str:
        normalized = [label.strip().lower() for label in labels if label and label.strip()]
        if not normalized:
            return ""
        counts = Counter(normalized)
        if "person" in counts:
            person_count = counts["person"]
            if locked:
                if person_count > 1:
                    return "Target locked. Multiple people are in view."
                return "Target locked on one person ahead."
            if person_count > 1:
                return "I have multiple people in view."
            return "I have a person in view."
        primary = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
        article = "an" if primary[:1] in {"a", "e", "i", "o", "u"} else "a"
        return f"I can see {article} {primary} ahead."
