import time

from config import RoverConfig
from modules.rover_types import BoundingBox, Detection, TrackedTarget
from modules.tracking_controller import TrackingController


class DummyRover:
    def __init__(self):
        self.commands = []

    def send_command(self, command: str):
        self.commands.append(command)


class DummyTransport:
    def __init__(self):
        self.commands = []

    def send(self, command: str):
        self.commands.append(command)
        return True


def make_target(w: int, h: int, x: int = 10, y: int = 10) -> TrackedTarget:
    detection = Detection(
        label="person",
        confidence=0.9,
        bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=0.9),
    )
    return TrackedTarget(target_id=1, detection=detection)


def test_update_drives_forward_for_small_far_target():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    result = controller.update(make_target(10, 10, x=0, y=0), 200, 200)

    assert result == "F"
    assert rover.commands[-1] == "F"
    assert motor.commands[-1] == "F"
    assert any(command.startswith("Pan,") for command in servo.commands)


def test_no_detection_timeout_stops_rover():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", no_detection_timeout=0.01)
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)
    controller._state.last_detection_time = time.monotonic() - 1.0

    result = controller.update(None, 200, 200)

    assert result == "S"
    assert rover.commands[-1] == "S"
    assert motor.commands[-1] == "S"


def test_manual_pan_tilt_clamps_servo_angles():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    pan, tilt = controller.manual_pan_tilt(pan_delta=500, tilt_delta=-500)

    assert pan == 180
    assert tilt == 0
    assert servo.commands[-2:] == ["Pan,180", "Tilt,0"]
