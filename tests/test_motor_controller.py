from config import RoverConfig
from modules.motor_controller import MotorController


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
