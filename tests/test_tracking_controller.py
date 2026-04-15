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

    def send_pan_tilt(self, pan: int, tilt: int):
        self.commands.extend([f"Pan,{pan}", f"Tilt,{tilt}"])
        return True

    def latency_ms(self) -> float:
        return 3.5


def make_target(w: int, h: int, x: int = 10, y: int = 10, stable_frames: int = 4) -> TrackedTarget:
    detection = Detection(
        label="person",
        confidence=0.9,
        bbox=BoundingBox(x=x, y=y, w=w, h=h, confidence=0.9),
    )
    return TrackedTarget(target_id=1, detection=detection, stable_frames=stable_frames)


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


def test_update_turns_rover_when_camera_pan_is_far_off_center():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        follow_pan_align_threshold_deg=8.0,
        servo_manual_pan_direction=-1,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)
    controller._state.pan_angle = 70

    result = controller.update(make_target(60, 90, x=110, y=60), 240, 200)

    assert result == "R"
    assert rover.commands[-1] == "R"
    assert motor.commands[-1] == "R"


def test_update_servos_tracks_target_without_motor_commands():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    result = controller.update_servos(make_target(40, 60, x=150, y=80), 240, 200)

    assert result == "TRACK"
    assert any(command.startswith("Pan,") for command in servo.commands)
    assert rover.commands == []
    assert motor.commands == []


def test_update_servos_uses_physical_direction_mapping_for_auto_centering():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        servo_center_angle=90,
        servo_manual_pan_direction=-1,
        servo_manual_tilt_direction=-1,
        tracking_deadband_px=1,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    controller.update_servos(make_target(40, 60, x=150, y=120), 240, 200)

    pan, tilt = controller.current_angles()
    assert pan < 90
    assert tilt < 90
    assert any(command.startswith("Pan,") for command in servo.commands)
    assert any(command.startswith("Tilt,") for command in servo.commands)


def test_update_servos_stays_inside_safe_servo_envelope():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        servo_pan_min_angle=10,
        servo_pan_max_angle=170,
        servo_tilt_min_angle=10,
        servo_tilt_max_angle=155,
        tracking_deadband_px=1,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)
    controller._state.pan_angle = 169
    controller._state.tilt_angle = 11

    controller.update_servos(make_target(40, 60, x=0, y=0), 240, 200)

    pan, tilt = controller.current_angles()
    assert 10 <= pan <= 170
    assert 10 <= tilt <= 155


def test_update_servos_ignores_tiny_jitter_below_min_servo_delta():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        tracking_deadband_px=1,
        servo_min_delta_deg=5.0,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    result = controller.update_servos(make_target(40, 60, x=101, y=101), 200, 200)

    assert result == "TRACK"
    assert controller.current_angles() == (90, 90)
    assert servo.commands == []


def test_update_servos_smooths_target_measurements_before_tracking():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        tracking_deadband_px=1,
        tracking_measurement_alpha=0.5,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    controller.update_servos(make_target(40, 60, x=180, y=100), 240, 200)
    controller.update_servos(make_target(40, 60, x=60, y=100), 240, 200)

    smoothed = controller._state.smoothed_target_point
    assert smoothed is not None
    assert 60 < smoothed[0] < 180


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

    assert pan == 170
    assert tilt == 10
    assert servo.commands[-2:] == ["Pan,170", "Tilt,10"]


def test_manual_pan_tilt_clamps_tilt_to_155_only():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", servo_tilt_max_angle=155)
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    pan, tilt = controller.manual_pan_tilt(pan_delta=500, tilt_delta=500)

    assert pan == 170
    assert tilt == 155
    assert servo.commands[-2:] == ["Pan,170", "Tilt,155"]


def test_manual_pan_only_sends_single_axis_command():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    pan, tilt = controller.manual_pan_tilt(pan_delta=5)

    assert (pan, tilt) == (95, 90)
    assert servo.commands[-1] == "Pan,95"


def test_tracking_controller_reset_uses_configured_servo_center():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", servo_center_angle=90)
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    controller.manual_pan_tilt(pan_delta=20, tilt_delta=-15)
    controller.reset()

    assert controller.current_angles() == (90, 90)
    assert servo.commands[-2:] == ["Pan,90", "Tilt,90"]


def test_target_locked_only_when_dead_center_and_stable():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor", dead_zone_px=20, target_lock_frames=3)
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    controller.update(make_target(40, 60, x=85, y=70, stable_frames=4), 200, 200)

    assert controller.target_locked() is True
    assert controller.latency_ms() == 3.5


def test_tracking_uses_kalman_prediction_during_short_occlusion():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        kalman_max_prediction_frames=3,
        tracking_deadband_px=1,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)
    controller.update(make_target(40, 60, x=120, y=80), 240, 200)
    before_count = len(servo.commands)

    result = controller.update(None, 240, 200)

    assert result == "S"
    assert controller.predicted_point() is not None
    assert controller.tracking_status() == "PREDICT"
    assert rover.commands[-1] == "S"
    assert motor.commands[-1] == "S"
    assert len(servo.commands) >= before_count


def test_tracking_drops_prediction_after_configured_window():
    cfg = RoverConfig(
        "ws://cam",
        "ws://servo",
        "ws://motor",
        kalman_max_prediction_frames=1,
        no_detection_timeout=999,
    )
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)
    controller.update(make_target(40, 60, x=120, y=80), 240, 200)

    first = controller.update(None, 240, 200)
    second = controller.update(None, 240, 200)

    assert first == "S"
    assert second == "S"
    assert controller.tracking_status() == "IDLE"
    assert controller.predicted_point() is None


def test_duplicate_reset_does_not_resend_identical_stop_and_center_commands():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    rover = DummyRover()
    servo = DummyTransport()
    motor = DummyTransport()
    controller = TrackingController(cfg, rover, servo, motor)

    controller.reset()
    controller.reset()

    assert rover.commands == ["S"]
    assert motor.commands == ["S"]
    assert len(servo.commands) == 2
    assert servo.commands == ["Pan,90", "Tilt,90"]
