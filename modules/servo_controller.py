from __future__ import annotations

import threading
import time
from typing import Optional

import websocket

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.rover_types import ConnectionState, ConnectionStatus


class ServoController:
    """Persistent WebSocket sender for camera pan / tilt commands."""

    def __init__(self, url: str, config: RoverConfig) -> None:
        self._url = url
        self._config = config
        self._lock = threading.Lock()
        self._running = False
        self._started = False
        self._thread: Optional[threading.Thread] = None
        self._app: Optional[websocket.WebSocketApp] = None
        self._connected = False
        self._connected_event = threading.Event()
        self._disabled = not bool((url or "").strip())

    def start(self) -> None:
        if self._disabled or self._started:
            if self._disabled:
                self._set_state(ConnectionState.DISCONNECTED, "servo endpoint disabled")
            return
        self._running = True
        self._started = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="ServoController_Thread")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._started = False
        self._connected_event.clear()
        app = self._app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass

    def send(self, command: str) -> bool:
        if self._disabled:
            return False
        if not self._started:
            self.start()
        if not self._connected:
            self._connected_event.wait(timeout=min(0.35, self._config.ws_recv_timeout))
        try:
            with self._lock:
                app = self._app
            if app and app.sock and app.sock.connected:
                app.send(command)
                return True
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] send error: {exc}")
        return False

    def is_connected(self) -> bool:
        return self._connected

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        connected = state == ConnectionState.CONNECTED
        if self._connected != connected or detail:
            self._connected = connected
            bus.emit(
                SystemEvents.CONNECTION_STATUS_CHANGED,
                ConnectionStatus(channel="servo", state=state, detail=detail),
            )

    def _on_open(self, _app) -> None:
        self._connected_event.set()
        self._set_state(ConnectionState.CONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[ServoController] Connected to servo websocket.")

    def _on_error(self, _app, error) -> None:
        self._set_state(ConnectionState.ERROR, str(error))
        bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] {error}")

    def _on_close(self, _app, _status_code, _message) -> None:
        self._connected_event.clear()
        self._set_state(ConnectionState.DISCONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[ServoController] Connection closed.")

    def _run(self) -> None:
        self._set_state(ConnectionState.CONNECTING)
        try:
            while self._running:
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
                    bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] run error: {exc}")

                if self._running:
                    self._set_state(ConnectionState.CONNECTING)
                    time.sleep(self._config.reconnect_interval)
        finally:
            self._set_state(ConnectionState.DISCONNECTED)
