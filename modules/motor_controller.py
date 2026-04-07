from __future__ import annotations

import threading
import time
from typing import Optional

import websocket

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import ConnectionState, ConnectionStatus


class MotorController:
    """Persistent WebSocket sender for motor commands."""

    def __init__(self, url: str, config: RoverConfig) -> None:
        self._url = url
        self._config = config
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._app: Optional[websocket.WebSocketApp] = None
        self._connected = False
        self._disabled = not bool((url or "").strip())

    def start(self) -> None:
        if self._disabled:
            self._set_state(ConnectionState.DISCONNECTED, "motor endpoint disabled")
            bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] Motor endpoint disabled until a dev-board URL is configured.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="MotorController_Thread")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._connected and not self._disabled

    def send(self, command: str) -> bool:
        if self._disabled:
            return False
        try:
            with self._lock:
                app = self._app
            if app and app.sock and app.sock.connected:
                app.send(command)
                return True
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] send error: {exc}")
        return False

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        connected = state == ConnectionState.CONNECTED
        if self._connected != connected or detail:
            self._connected = connected
            bus.emit(
                SystemEvents.CONNECTION_STATUS_CHANGED,
                ConnectionStatus(channel="motor", state=state, detail=detail),
            )

    def _on_open(self, _app) -> None:
        self._set_state(ConnectionState.CONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] Connected to motor websocket.")

    def _on_error(self, _app, error) -> None:
        error_text = str(error)
        if "Handshake status 404" in error_text or "404 Not Found" in error_text:
            self._disabled = True
            self._set_state(ConnectionState.DISCONNECTED, "motor endpoint not found")
            bus.emit(
                SystemEvents.LOG_MESSAGE,
                "[MotorController] Motor websocket endpoint returned 404. Disabling motor socket retries until restart.",
            )
            return
        self._set_state(ConnectionState.ERROR, str(error))
        bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] {error}")

    def _on_close(self, _app, _status_code, _message) -> None:
        self._set_state(ConnectionState.DISCONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] Connection closed.")

    def _run(self) -> None:
        if self._disabled:
            return
        self._set_state(ConnectionState.CONNECTING)
        try:
            while self._running:
                if self._disabled:
                    break
                try:
                    app = websocket.WebSocketApp(
                        self._url,
                        on_open=self._on_open,
                        on_error=self._on_error,
                        on_close=self._on_close,
                    )
                    with self._lock:
                        self._app = app
                    app.run_forever(ping_interval=0)
                except Exception as exc:
                    self._set_state(ConnectionState.ERROR, str(exc))
                    bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] run error: {exc}")

                if self._running:
                    self._set_state(ConnectionState.CONNECTING)
                    time.sleep(self._config.reconnect_interval)
        finally:
            self._set_state(ConnectionState.DISCONNECTED)
