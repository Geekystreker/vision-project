import numpy as np

from config import RoverConfig
from modules.control_arbiter import ControlArbiter
from modules.rover_types import BoundingBox, ConnectionState, ControlMode, Detection, VisionSnapshot
from modules.rover_vision_app import RoverVisionApp


class DummySender:
    def __init__(self):
        self.commands = []

    def send(self, command: str):
        self.commands.append(command)
        return True


class DummyRover:
    def __init__(self):
        self.commands = []

    def send_command(self, command: str):
        self.commands.append(command)


def test_keyboard_drive_command_enters_manual_mode():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._rover_controller = DummyRover()

    ok = app.send_drive_command("F", source="KEYBOARD")

    assert ok is True
    assert arbiter.current_mode() == ControlMode.MANUAL
    assert app._motor_controller.commands[-1] == "F"
    assert app._rover_controller.commands[-1] == "F"


def test_toggle_follow_mode_returns_to_manual_and_stops():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller

    first = app.toggle_follow_mode()
    second = app.toggle_follow_mode()

    assert first == ControlMode.FOLLOW_PERSON
    assert second == ControlMode.MANUAL
    assert app._rover_controller.commands[-1] == "S"


def test_describe_scene_uses_latest_snapshot_detections():
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    app._latest_snapshot = VisionSnapshot(
        frame=np.zeros((32, 32, 3), dtype=np.uint8),
        detections=[
            Detection(label="person", confidence=0.9, bbox=BoundingBox(0, 0, 10, 10)),
            Detection(label="bottle", confidence=0.8, bbox=BoundingBox(0, 0, 8, 8)),
        ],
        links={"camera": ConnectionState.CONNECTED},
    )

    description = app.describe_scene()

    assert "person" in description.lower()
    assert "bottle" in description.lower()


def test_missing_frame_in_follow_mode_stops_and_clears_target():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app.set_follow_mode()
    app._latest_detections = [
        Detection(label="person", confidence=0.9, bbox=BoundingBox(0, 0, 10, 10))
    ]
    app._latest_target = None

    app._handle_missing_frame(ControlMode.FOLLOW_PERSON)

    assert app._latest_detections == []
    assert app._rover_controller.commands[-1] == "S"


def test_scale_detection_maps_bbox_back_to_full_frame():
    det = Detection(label="person", confidence=0.9, bbox=BoundingBox(10, 20, 30, 40), track_id=7)

    scaled = RoverVisionApp._scale_detection(det, 2.0, 1.5, 640, 480)

    assert scaled.bbox.x == 20
    assert scaled.bbox.y == 30
    assert scaled.bbox.w == 60
    assert scaled.bbox.h == 60
    assert scaled.track_id == 7
