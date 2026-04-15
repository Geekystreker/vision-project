from types import SimpleNamespace

from config import RoverConfig
from modules.motor_controller import MotorController, PendingMotorCommand


def test_motor_controller_disables_on_404_error():
    controller = MotorController("ws://motor", RoverConfig("ws://cam", "ws://servo", "ws://motor"))

    controller._on_error(None, "Handshake status 404 Not Found")

    assert controller.is_connected() is False
    assert controller._disabled is True


def test_motor_controller_starts_disabled_when_url_missing():
    controller = MotorController("", RoverConfig("ws://cam", "ws://servo", ""))

    controller.start()

    assert controller.is_connected() is False
    assert controller._disabled is True


def test_motor_controller_translates_drive_command_to_left_right_pwm_payloads():
    controller = MotorController(
        "ws://motor",
        RoverConfig("ws://cam", "ws://servo", "ws://motor", motor_drive_speed=170),
    )
    recorded = []
    controller._app = SimpleNamespace(
        sock=SimpleNamespace(connected=True),
        send=lambda command: recorded.append(command),
    )

    ok = controller._send_payloads(controller._payloads_for_command("F"), "F", 0.0)

    assert ok is True
    assert recorded == ["L,170", "R,170"]


def test_motor_controller_translates_turn_and_stop_commands():
    controller = MotorController(
        "ws://motor",
        RoverConfig("ws://cam", "ws://servo", "ws://motor", motor_turn_speed=150),
    )
    recorded = []
    controller._app = SimpleNamespace(
        sock=SimpleNamespace(connected=True),
        send=lambda command: recorded.append(command),
    )

    assert controller._send_payloads(controller._payloads_for_command("L"), "L", 0.0) is True
    assert controller._send_payloads(controller._payloads_for_command("S"), "S", 0.0) is True

    assert recorded == ["L,-150", "R,150", "L,0", "R,0"]


def test_motor_controller_send_queues_latest_command_without_direct_io():
    controller = MotorController("ws://motor", RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    controller._started = True

    ok = controller.send("F")

    assert ok is True
    assert controller._pending_command is not None
    assert controller._pending_command.command == "F"
    assert controller._pending_command.payloads == ("L,170", "R,170")


def test_motor_controller_drops_stale_motion_but_never_stop(monkeypatch):
    controller = MotorController(
        "ws://motor",
        RoverConfig("ws://cam", "ws://servo", "ws://motor", motor_command_ttl_seconds=0.35),
    )
    monkeypatch.setattr("modules.motor_controller.time.monotonic", lambda: 10.0)

    stale_forward = PendingMotorCommand("F", ("L,170", "R,170"), 9.0)
    stale_stop = PendingMotorCommand("S", ("L,0", "R,0"), 9.0)

    assert controller._is_stale_motion_command(stale_forward) is True
    assert controller._is_stale_motion_command(stale_stop) is False


def test_motor_controller_sends_stop_when_socket_opens():
    controller = MotorController("ws://motor", RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    recorded = []
    controller._app = SimpleNamespace(
        sock=SimpleNamespace(connected=True),
        send=lambda command: recorded.append(command),
    )

    controller._on_open(None)

    assert controller.is_connected() is True
    assert recorded == ["L,0", "R,0"]
