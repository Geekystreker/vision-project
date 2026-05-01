from config import RoverConfig
from modules.rover_types import BoundingBox, Detection
from modules.target_tracker import TargetTracker


def make_detection(track_id: int | None, x: int, y: int, w: int, h: int) -> Detection:
    return Detection(
        label="person",
        confidence=0.9,
        bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=0.9),
        track_id=track_id,
    )


def test_tracker_locks_closest_to_center_first():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    tracker = TargetTracker(cfg)
    detections = [
        make_detection(7, 5, 5, 30, 30),
        make_detection(8, 90, 80, 35, 35),
    ]

    target = tracker.update(detections, 200, 200)

    assert target is not None
    assert target.target_id == 1
    assert target.source_track_id == 8
    assert tracker.locked_target_id() == 1


def test_tracker_prefers_large_front_target_over_tiny_background_center():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    tracker = TargetTracker(cfg)
    detections = [
        make_detection(21, 95, 95, 10, 10),
        make_detection(22, 65, 58, 70, 84),
    ]

    target = tracker.update(detections, 200, 200)

    assert target is not None
    assert target.source_track_id == 22


def test_tracker_ignores_other_ids_while_locked():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    tracker = TargetTracker(cfg)
    first = tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)
    second = tracker.update(
        [
            make_detection(4, 85, 82, 40, 40),
            make_detection(9, 95, 85, 60, 60),
        ],
        200,
        200,
    )

    assert first is not None
    assert second is not None
    assert second.target_id == first.target_id
    assert second.source_track_id == 4


def test_tracker_rebinds_new_raw_id_to_same_logical_target():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", track_iou_threshold=0.10, target_rebind_frames=1)
    tracker = TargetTracker(cfg)

    first = tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)
    second = tracker.update([make_detection(17, 84, 82, 42, 42)], 200, 200)

    assert first is not None
    assert second is not None
    assert second.target_id == first.target_id
    assert second.source_track_id == 17


def test_tracker_falls_back_to_box_rebind_when_track_ids_are_missing():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", track_iou_threshold=0.10, target_rebind_frames=1)
    tracker = TargetTracker(cfg)

    first = tracker.update([make_detection(None, 80, 80, 40, 40)], 200, 200)
    second = tracker.update([make_detection(None, 84, 82, 42, 42)], 200, 200)

    assert first is not None
    assert second is not None
    assert second.target_id == first.target_id
    assert second.source_track_id is None
    assert second.stable_frames == first.stable_frames + 1


def test_tracker_returns_none_while_temporarily_missing():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", max_target_lost_frames=5)
    tracker = TargetTracker(cfg)
    tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)

    target = tracker.update([], 200, 200)

    assert target is None
    assert tracker.current_target() is not None


def test_tracker_reacquires_new_person_after_old_target_leaves():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", max_target_lost_frames=6, target_lock_frames=3)
    tracker = TargetTracker(cfg)
    first = tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)

    second = None
    for _ in range(7):
        second = tracker.update([make_detection(11, 150, 75, 42, 42)], 200, 200)

    assert first is not None
    assert second is not None
    assert second.target_id != first.target_id
    assert second.source_track_id == 11


def test_tracker_does_not_snap_to_different_person_while_lock_is_alive():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", max_target_lost_frames=6)
    tracker = TargetTracker(cfg)
    first = tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)

    second = tracker.update([make_detection(11, 150, 75, 42, 42)], 200, 200)

    assert first is not None
    assert second is None
    assert tracker.locked_target_id() == first.target_id


def test_tracker_requires_stable_acquisition_when_configured():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", target_acquisition_frames=3)
    tracker = TargetTracker(cfg)

    first = tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)
    second = tracker.update([make_detection(4, 82, 80, 40, 40)], 200, 200)
    third = tracker.update([make_detection(4, 84, 80, 40, 40)], 200, 200)

    assert first is None
    assert second is None
    assert third is not None
    assert third.source_track_id == 4


def test_tracker_can_acquire_same_person_despite_raw_id_churn():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", target_acquisition_frames=3)
    tracker = TargetTracker(cfg)

    first = tracker.update([make_detection(10, 80, 80, 40, 40)], 200, 200)
    second = tracker.update([make_detection(11, 82, 80, 40, 40)], 200, 200)
    third = tracker.update([make_detection(12, 84, 80, 40, 40)], 200, 200)

    assert first is None
    assert second is None
    assert third is not None
    assert third.source_track_id == 12


def test_tracker_rejects_same_track_id_when_box_jumps_to_face_crop():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", max_target_lost_frames=6)
    tracker = TargetTracker(cfg)
    first = tracker.update([make_detection(4, 40, 10, 110, 180)], 200, 200)

    second = tracker.update([make_detection(4, 70, 36, 24, 32)], 200, 200)

    assert first is not None
    assert second is None
    assert tracker.locked_target_id() == first.target_id


def test_tracker_clears_after_long_target_loss():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", max_target_lost_frames=10)
    tracker = TargetTracker(cfg)
    tracker.update([make_detection(4, 80, 80, 40, 40)], 200, 200)

    target = None
    for _ in range(11):
        target = tracker.update([], 200, 200)

    assert target is None
    assert tracker.locked_target_id() is None


def test_tracker_holds_lock_instead_of_accepting_sudden_face_crop():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", target_box_smoothing_alpha=0.22)
    tracker = TargetTracker(cfg)

    first = tracker.update([make_detection(4, 40, 10, 110, 180)], 200, 200)
    second = tracker.update([make_detection(4, 68, 36, 34, 52)], 200, 200)

    assert first is not None
    assert second is None
    assert tracker.locked_target_id() == first.target_id
