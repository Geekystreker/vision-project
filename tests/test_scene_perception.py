from modules.rover_types import BoundingBox, Detection
from modules.scene_perception import ScenePerceptionService


def test_describe_prefers_person_ahead_callout_for_nearest_person():
    service = ScenePerceptionService()
    detections = [
        Detection(label="person", confidence=0.91, bbox=BoundingBox(0, 0, 80, 160)),
        Detection(label="bottle", confidence=0.75, bbox=BoundingBox(20, 20, 30, 60)),
    ]

    description = service.describe(detections)

    assert description.startswith("Person ahead.")


def test_brief_target_callout_for_person():
    service = ScenePerceptionService()
    detection = Detection(label="person", confidence=0.91, bbox=BoundingBox(0, 0, 80, 160))

    assert service.brief_target_callout(detection) == "Person ahead."


def test_detection_callout_prefers_person():
    service = ScenePerceptionService()

    assert service.detection_callout(["chair", "person"]) == "Person detected."


def test_detection_callout_for_generic_object():
    service = ScenePerceptionService()

    assert service.detection_callout(["chair"]) == "Object detected."


def test_live_scene_line_for_person_without_lock():
    service = ScenePerceptionService()

    assert service.live_scene_line(["person"], locked=False) == "I have a person in view."


def test_live_scene_line_for_locked_person():
    service = ScenePerceptionService()

    assert service.live_scene_line(["person"], locked=True) == "Target locked on one person ahead."
