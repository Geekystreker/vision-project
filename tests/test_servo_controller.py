from types import SimpleNamespace

from config import RoverConfig
from modules.servo_controller import ServoController


def test_send_writes_to_connected_socket():
    controller = ServoController("ws://servo", RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    controller._started = True
    recorded = []
    controller._app = SimpleNamespace(
        sock=SimpleNamespace(connected=True),
        send=lambda command: recorded.append(command),
    )

    ok = controller.send("Pan,120")

    assert ok is True
    assert recorded == ["Pan,120"]


def test_send_suppresses_errors_and_returns_false():
    controller = ServoController("ws://servo", RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    controller._started = True
    controller._app = SimpleNamespace(
        sock=SimpleNamespace(connected=True),
        send=lambda _command: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    ok = controller.send("Tilt,80")

    assert ok is False


def test_send_starts_controller_on_first_use(monkeypatch):
    controller = ServoController("ws://servo", RoverConfig("ws://cam", "ws://servo", "ws://motor"))
    calls = []

    def fake_start():
        controller._started = True
        controller._connected = True
        controller._connected_event.set()
        controller._app = SimpleNamespace(
            sock=SimpleNamespace(connected=True),
            send=lambda command: calls.append(command),
        )

    monkeypatch.setattr(controller, "start", fake_start)

    ok = controller.send("Pan,120")

    assert ok is True
    assert calls == ["Pan,120"]


def test_servo_controller_starts_disabled_when_url_missing():
    controller = ServoController("", RoverConfig("ws://cam", "", "ws://motor"))

    controller.start()

    assert controller.is_connected() is False
    assert controller._disabled is True
