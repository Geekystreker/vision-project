from threading import RLock
from typing import Callable, List


class StateManager:
    IDLE = "IDLE"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"

    _VALID_STATES = {IDLE, THINKING, SPEAKING}

    def __init__(self):
        self._state = self.IDLE
        self._listeners: List[Callable[[str], None]] = []
        self._lock = RLock()

    def register_listener(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def set_state(self, state: str) -> None:
        normalized = (state or "").strip().upper()
        if normalized not in self._VALID_STATES:
            return

        listeners: List[Callable[[str], None]]
        with self._lock:
            if normalized == self._state:
                return
            self._state = normalized
            listeners = list(self._listeners)

        for callback in listeners:
            try:
                callback(normalized)
            except Exception:
                pass

    def get_state(self) -> str:
        with self._lock:
            return self._state
