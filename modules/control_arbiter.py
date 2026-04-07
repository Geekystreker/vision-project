from __future__ import annotations

import time

from core.event_bus import SystemEvents, bus
from modules.rover_types import ControlMode


class ControlArbiter:
    """Prioritise emergency, keyboard, voice, and autonomous control sources."""

    def __init__(
        self,
        keyboard_override_seconds: float = 0.35,
        voice_override_seconds: float = 1.25,
        inspect_mode_seconds: float = 2.50,
    ) -> None:
        self._base_mode = ControlMode.IDLE
        self._current_mode = ControlMode.IDLE
        self._keyboard_override_until = 0.0
        self._voice_override_until = 0.0
        self._temporary_mode_until = 0.0
        self._inspect_mode_seconds = inspect_mode_seconds
        self._keyboard_override_seconds = keyboard_override_seconds
        self._voice_override_seconds = voice_override_seconds
        self._emergency_stop = False

    @property
    def emergency_stop_active(self) -> bool:
        return self._emergency_stop

    def current_mode(self) -> ControlMode:
        self._expire_temporary_modes()
        return self._current_mode

    def follow_enabled(self) -> bool:
        return self._base_mode == ControlMode.FOLLOW_PERSON and not self._emergency_stop

    def set_manual_mode(self) -> ControlMode:
        return self._set_mode(ControlMode.MANUAL, sticky=True)

    def set_idle_mode(self) -> ControlMode:
        return self._set_mode(ControlMode.IDLE, sticky=True)

    def set_follow_mode(self) -> ControlMode:
        self._emergency_stop = False
        return self._set_mode(ControlMode.FOLLOW_PERSON, sticky=True)

    def toggle_follow_mode(self) -> ControlMode:
        if self._base_mode == ControlMode.FOLLOW_PERSON:
            return self.set_manual_mode()
        return self.set_follow_mode()

    def begin_keyboard_override(self) -> ControlMode:
        self._emergency_stop = False
        self._keyboard_override_until = time.monotonic() + self._keyboard_override_seconds
        return self._set_mode(ControlMode.MANUAL, sticky=True)

    def begin_voice_nav(self) -> ControlMode:
        if self._emergency_stop:
            return self.current_mode()
        self._voice_override_until = time.monotonic() + self._voice_override_seconds
        return self._set_temporary_mode(ControlMode.VOICE_NAV, self._voice_override_seconds)

    def begin_scene_inspection(self) -> ControlMode:
        if self._emergency_stop:
            return self.current_mode()
        return self._set_temporary_mode(ControlMode.INSPECT_SCENE, self._inspect_mode_seconds)

    def trigger_emergency_stop(self) -> ControlMode:
        self._emergency_stop = True
        self._keyboard_override_until = 0.0
        self._voice_override_until = 0.0
        return self._set_mode(ControlMode.MANUAL, sticky=True)

    def clear_emergency_stop(self) -> ControlMode:
        self._emergency_stop = False
        return self._set_mode(self._base_mode, sticky=False)

    def allow_keyboard(self) -> bool:
        return True

    def allow_voice(self) -> bool:
        return not self._emergency_stop

    def allow_autonomy(self) -> bool:
        self._expire_temporary_modes()
        if self._emergency_stop:
            return False
        now = time.monotonic()
        if now < self._keyboard_override_until or now < self._voice_override_until:
            return False
        return self._base_mode == ControlMode.FOLLOW_PERSON and self._current_mode == ControlMode.FOLLOW_PERSON

    def _set_mode(self, mode: ControlMode, *, sticky: bool) -> ControlMode:
        if sticky:
            self._base_mode = mode
            self._temporary_mode_until = 0.0
        if self._current_mode != mode:
            self._current_mode = mode
            bus.emit(SystemEvents.CONTROL_MODE_CHANGED, mode.value)
            bus.emit(SystemEvents.ROVER_MODE_CHANGE, mode.value)
        return self._current_mode

    def _set_temporary_mode(self, mode: ControlMode, duration: float) -> ControlMode:
        self._temporary_mode_until = time.monotonic() + duration
        return self._set_mode(mode, sticky=False)

    def _expire_temporary_modes(self) -> None:
        if self._temporary_mode_until and time.monotonic() >= self._temporary_mode_until:
            self._temporary_mode_until = 0.0
            self._set_mode(self._base_mode, sticky=False)
