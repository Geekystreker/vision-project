from modules.control_arbiter import ControlArbiter
from modules.rover_types import ControlMode


def test_keyboard_override_preempts_follow_mode():
    arbiter = ControlArbiter()
    arbiter.set_follow_mode()

    arbiter.begin_keyboard_override()

    assert arbiter.current_mode() == ControlMode.MANUAL
    assert arbiter.allow_autonomy() is False


def test_emergency_stop_blocks_voice_and_autonomy():
    arbiter = ControlArbiter()
    arbiter.set_follow_mode()
    arbiter.trigger_emergency_stop()

    assert arbiter.emergency_stop_active is True
    assert arbiter.allow_voice() is False
    assert arbiter.allow_autonomy() is False
