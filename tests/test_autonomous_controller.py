from config import RoverConfig
from modules.autonomous_controller import AutonomousController
from modules.rover_types import BoundingBox, Detection


class DummyRover:
    def __init__(self):
        self.commands = []

    def send_command(self, command: str):
        self.commands.append(command)


class DummyMotor:
    def __init__(self):
        self.commands = []

    def send(self, command: str):
        self.commands.append(command)
        return True


def make_detection(label: str, x: int, y: int, w: int, h: int, confidence: float = 0.9) -> Detection:
    return Detection(
        label=label,
        confidence=confidence,
        bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=confidence),
    )


def test_autonomy_moves_forward_when_scene_is_clear():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    motor = DummyMotor()
    controller = AutonomousController(cfg, rover, motor)

    first = controller.update([], 320, 240)
    second = controller.update([], 320, 240)

    assert first == "S"
    assert second == "F"
    assert rover.commands[-1] == "F"
    assert motor.commands[-1] == "F"


def test_autonomy_stops_for_large_center_obstacle():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    motor = DummyMotor()
    controller = AutonomousController(cfg, rover, motor)

    command = controller.update([make_detection("person", 90, 30, 140, 170)], 320, 240)

    assert command == "S"
    assert rover.commands == []
    assert motor.commands == []
    assert "too close" in controller.last_reason().lower()


def test_autonomy_prefers_opener_side():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    motor = DummyMotor()
    controller = AutonomousController(cfg, rover, motor)
    detections = [
        make_detection("chair", 0, 20, 110, 150),
        make_detection("box", 30, 120, 80, 80),
    ]

    command = controller.update(detections, 320, 240)

    assert command == "R"


def test_autonomy_requires_fresh_clear_confirmation_after_obstacle():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        autonomous_clear_frames_required=2,
        autonomous_turn_hold_seconds=0.0,
    )
    rover = DummyRover()
    motor = DummyMotor()
    controller = AutonomousController(cfg, rover, motor)
    obstacle = [make_detection("chair", 80, 20, 140, 100)]

    blocked = controller.update(obstacle, 320, 240)
    first_clear = controller.update([], 320, 240)
    second_clear = controller.update([], 320, 240)

    assert blocked in {"L", "R"}
    assert first_clear == "S"
    assert second_clear == "F"
