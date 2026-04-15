import numpy as np

from config import RoverConfig
import modules.rover_vision_app as rover_vision_module
from modules.control_arbiter import ControlArbiter
from modules.rover_types import BoundingBox, ConnectionState, ConnectionStatus, ControlMode, Detection, VisionSnapshot
from modules.rover_vision_app import RoverVisionApp


class DummySender:
    def __init__(self):
        self.commands = []

    def send(self, command: str):
        self.commands.append(command)
        return True

    def send_pan_tilt(self, pan: int, tilt: int):
        self.commands.extend([f"Pan,{pan}", f"Tilt,{tilt}"])
        return True

    def current_angles(self):
        return (90, 90)

    def latency_ms(self):
        return 0.0


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


def test_adjust_servo_updates_angles_and_enters_manual_mode():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._servo_controller = DummySender()
    app._tracking_controller._servo = app._servo_controller

    pan, tilt = app.adjust_servo(pan_delta=10, tilt_delta=-5, source="KEYBOARD")

    assert arbiter.current_mode() == ControlMode.MANUAL
    assert (pan, tilt) == (100, 85)
    assert app._servo_controller.commands[-2:] == ["Pan,100", "Tilt,85"]


def test_adjust_servo_rate_limits_keyboard_bursts(monkeypatch):
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._servo_controller = DummySender()
    app._tracking_controller._servo = app._servo_controller
    app._arbiter.begin_keyboard_override = lambda: ControlMode.MANUAL
    times = iter([100.0, 100.01])
    monkeypatch.setattr(rover_vision_module.time, "monotonic", lambda: next(times))

    first = app.adjust_servo(pan_delta=5, source="KEYBOARD")
    second = app.adjust_servo(pan_delta=5, source="KEYBOARD")

    assert first == (95, 90)
    assert second == (95, 90)
    assert app._servo_controller.commands == ["Pan,95"]


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


def test_missing_camera_still_allows_manual_driver_node_commands():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app._link_states["motor"] = ConnectionState.CONNECTED
    app._link_states["servo"] = ConnectionState.CONNECTED

    app._handle_missing_frame(ControlMode.MANUAL)
    drive_ok = app.send_drive_command("F", source="KEYBOARD")
    pan, tilt = app.adjust_servo(pan_delta=5, source="KEYBOARD")

    assert drive_ok is True
    assert app._motor_controller.commands[-1] == "F"
    assert app._rover_controller.commands[-1] == "F"
    assert (pan, tilt) == (95, 90)
    assert app._servo_controller.commands[-1] == "Pan,95"


def test_follow_mode_missing_target_preserves_current_servo_angles():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app.set_follow_mode()
    app._tracking_controller._state.pan_angle = 132
    app._tracking_controller._state.tilt_angle = 74
    app._tracking_controller._state.target_locked = True

    app._apply_detection_actions(ControlMode.FOLLOW_PERSON, None, [], 240, 200)

    assert app._tracking_controller.current_angles() == (132, 74)
    assert app._rover_controller.commands[-1] == "S"
    assert app._motor_controller.commands[-1] == "S"
    assert app._servo_controller.commands == []


def test_follow_mode_short_occlusion_keeps_prediction_alive_without_reset():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app.set_follow_mode()
    target = app._target_tracker.update(
        [Detection(label="person", confidence=0.9, bbox=BoundingBox(140, 70, 40, 70), track_id=4)],
        240,
        200,
    )

    app._apply_detection_actions(ControlMode.FOLLOW_PERSON, target, [target.detection], 240, 200)
    before_servo_count = len(app._servo_controller.commands)
    app._apply_detection_actions(ControlMode.FOLLOW_PERSON, None, [], 240, 200)

    assert app._tracking_controller.tracking_status() == "PREDICT"
    assert app._tracking_controller.predicted_point() is not None
    assert app._last_command == "S"
    assert len(app._servo_controller.commands) >= before_servo_count


def test_autonomous_mode_aims_servos_at_locked_target_and_drives():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app._autonomous_controller._motor = app._motor_controller
    app._autonomous_controller._rover = app._rover_controller
    app.set_autonomous_mode()
    detection = Detection(
        label="person",
        confidence=0.9,
        bbox=BoundingBox(150, 80, 40, 60),
        track_id=42,
    )
    target = app._target_tracker.update([detection], 240, 200)

    app._apply_detection_actions(ControlMode.AUTONOMOUS, target, [detection], 240, 200)

    assert target is not None
    assert any(command.startswith("Pan,") for command in app._servo_controller.commands)
    assert app._rover_controller.commands
    assert app._last_command in {"F", "B", "L", "R", "S"}


def test_engage_autonomous_target_lock_centers_servos_and_sets_mode():
    arbiter = ControlArbiter()
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"), arbiter)
    app._motor_controller = DummySender()
    app._servo_controller = DummySender()
    app._rover_controller = DummyRover()
    app._tracking_controller._motor = app._motor_controller
    app._tracking_controller._servo = app._servo_controller
    app._tracking_controller._rover = app._rover_controller
    app._tracking_controller.manual_pan_tilt(pan_delta=20, tilt_delta=-15)

    mode = app.engage_autonomous_target_lock()

    assert mode == ControlMode.AUTONOMOUS
    assert app._tracking_controller.current_angles() == (90, 90)
    assert app._servo_controller.commands[-2:] == ["Pan,90", "Tilt,90"]
    assert app._target_tracker.locked_target_id() is None
    assert app._last_command == "S"


def test_scale_detection_maps_bbox_back_to_full_frame():
    det = Detection(label="person", confidence=0.9, bbox=BoundingBox(10, 20, 30, 40), track_id=7)

    scaled = RoverVisionApp._scale_detection(det, 2.0, 1.5, 640, 480)

    assert scaled.bbox.x == 20
    assert scaled.bbox.y == 30
    assert scaled.bbox.w == 60
    assert scaled.bbox.h == 60
    assert scaled.track_id == 7


def test_publish_snapshot_carries_tracking_telemetry():
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    app._tracking_controller._state.pan_angle = 111
    app._tracking_controller._state.tilt_angle = 77
    app._tracking_controller._state.target_locked = True
    app._latest_inference_ms = 12.5
    app._tracking_controller._servo = DummySender()
    target = Detection(label="person", confidence=0.9, bbox=BoundingBox(50, 60, 40, 80))
    tracked = app._target_tracker.update([target], 320, 240)

    app._publish_snapshot(np.zeros((32, 32, 3), dtype=np.uint8), [target], tracked, ControlMode.FOLLOW_PERSON)
    snapshot = app.latest_snapshot()

    assert snapshot.servo_pan == 111
    assert snapshot.servo_tilt == 77
    assert snapshot.target_locked is True
    assert snapshot.inference_ms == 12.5


def test_publish_snapshot_carries_locked_target_id():
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    target = Detection(
        label="person",
        confidence=0.9,
        bbox=BoundingBox(50, 60, 40, 80),
        track_id=12,
    )
    tracked = app._target_tracker.update([target], 320, 240)

    app._publish_snapshot(np.zeros((32, 32, 3), dtype=np.uint8), [target], tracked, ControlMode.FOLLOW_PERSON)
    snapshot = app.latest_snapshot()

    assert snapshot.locked_target_id == 1


def test_connection_status_updates_model_and_transport_links():
    app = RoverVisionApp(RoverConfig("ws://cam", "ws://servo", "ws://motor"))

    app._on_connection_status(ConnectionStatus(channel="detector", state=ConnectionState.CONNECTED))
    app._on_connection_status(ConnectionStatus(channel="ollama", state=ConnectionState.ERROR))

    app._publish_snapshot(None, [], None, ControlMode.MANUAL)
    snapshot = app.latest_snapshot()

    assert snapshot.links["detector"] == ConnectionState.CONNECTED
    assert snapshot.links["ollama"] == ConnectionState.ERROR
