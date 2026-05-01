from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import websocket

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.jarvis_protocol import move_packet, uses_json_protocol, uses_legacy_protocol
from modules.rover_types import ConnectionState, ConnectionStatus


@dataclass(slots=True)
class PendingMotorCommand:
    command: str
    payloads: tuple[str, ...]
    enqueued_at: float


class MotorController:
    """Persistent WebSocket sender for motor commands."""

    def __init__(self, url: str, config: RoverConfig) -> None:
        self._url = url
        self._config = config
        self._transport = self._resolve_transport(url)
        self._udp_target = self._resolve_udp_target(url)
        self._lock = threading.Lock()
        self._running = False
        self._started = False
        self._thread: Optional[threading.Thread] = None
        self._sender_thread: Optional[threading.Thread] = None
        self._app: Optional[websocket.WebSocketApp] = None
        self._udp_socket: Optional[socket.socket] = None
        self._connected = False
        self._connected_event = threading.Event()
        self._send_event = threading.Event()
        self._disabled = not bool((url or "").strip()) or (self._transport == "udp" and self._udp_target is None)
        self._pending_command: PendingMotorCommand | None = None
        self._pending_followup_command: PendingMotorCommand | None = None
        self._last_sent_command = ""
        self._last_sent_at = 0.0
        self._last_waiting_log_at = 0.0

    def start(self) -> None:
        if self._disabled or self._started:
            if self._disabled:
                self._set_state(ConnectionState.DISCONNECTED, "motor endpoint disabled")
                bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] Motor endpoint disabled until a dev-board URL is configured.")
            return
        self._running = True
        self._started = True
        if self._transport == "udp":
            self._start_udp_transport()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True, name="MotorController_Thread")
            self._thread.start()
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            daemon=True,
            name="MotorControllerSender_Thread",
        )
        self._sender_thread.start()

    def stop(self) -> None:
        self._running = False
        self._started = False
        self._connected_event.clear()
        self._send_event.set()
        app = self._app
        udp_socket = self._udp_socket
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        if udp_socket is not None:
            try:
                udp_socket.close()
            except Exception:
                pass
            self._udp_socket = None
        self._set_state(ConnectionState.DISCONNECTED)

    def is_connected(self) -> bool:
        return self._connected and not self._disabled

    def send(self, command: str) -> bool:
        if self._disabled:
            return False
        if not self._started:
            self.start()
        payloads = self._payloads_for_command(command)
        if not payloads:
            return False
        command_key = (command or "").strip().upper()
        now = time.monotonic()
        pending = PendingMotorCommand(
            command=command_key,
            payloads=payloads,
            enqueued_at=now,
        )
        with self._lock:
            # A quick key tap can produce F then S before the sender thread wakes up.
            # Preserve that order so movement is not swallowed by the stop command.
            if command_key == "S" and self._pending_command is not None and self._pending_command.command != "S":
                self._pending_followup_command = pending
                self._send_event.set()
                return True
            if command_key != "S":
                self._pending_followup_command = None
            if self._pending_command is not None and self._pending_command.command == command_key:
                return True
            if (
                self._last_sent_command == command_key
                and (now - self._last_sent_at) < (1.0 / max(1, self._config.motor_send_hz))
            ):
                return True
            self._pending_command = pending
        self._send_event.set()
        return True

    def send_stop_now(self) -> bool:
        return self._send_payloads(self._payloads_for_command("S"), "S", time.monotonic())

    def force_stop(self) -> bool:
        """Clear queued movement and prioritize a stop packet immediately."""
        payloads = self._payloads_for_command("S")
        now = time.monotonic()
        with self._lock:
            stop_was_recent = (
                self._last_sent_command == "S"
                and (now - self._last_sent_at) < (1.0 / max(1, self._config.motor_send_hz))
            )
            self._pending_command = None
            self._pending_followup_command = None
        if stop_was_recent:
            return True

        if self._send_payloads(payloads, "S", now):
            return True

        with self._lock:
            self._pending_command = PendingMotorCommand("S", payloads, now)
            self._pending_followup_command = None
        self._send_event.set()
        return True

    def _send_payloads(self, payloads: tuple[str, ...], command_key: str, enqueued_at: float) -> bool:
        try:
            if self._transport == "udp":
                return self._send_udp_payloads(payloads, command_key, enqueued_at)
            with self._lock:
                app = self._app
            if app and app.sock and app.sock.connected:
                for payload in payloads:
                    app.send(payload)
                with self._lock:
                    self._last_sent_command = command_key
                    self._last_sent_at = time.monotonic()
                return True
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] send error: {exc}")
        return False

    def _payloads_for_command(self, command: str) -> tuple[str, ...]:
        text = (command or "").strip()
        if not text:
            return ()
        if "," in text:
            return (text,)

        cmd = text.upper()
        drive_speed = self._clamp_speed(self._config.motor_drive_speed)
        turn_speed = self._clamp_speed(self._config.motor_turn_speed)
        command_speeds = {
            "F": (drive_speed, drive_speed),
            "B": (-drive_speed, -drive_speed),
            "L": (-turn_speed, turn_speed),
            "R": (turn_speed, -turn_speed),
            "S": (0, 0),
        }.get(cmd)
        if command_speeds is None:
            return ()
        left_speed, right_speed = command_speeds
        payloads: list[str] = []
        if uses_json_protocol(self._config):
            payloads.append(move_packet(self._config, direction=cmd, left=left_speed, right=right_speed))
        if uses_legacy_protocol(self._config):
            payloads.extend((f"L,{left_speed}", f"R,{right_speed}"))
        return tuple(payloads)

    @staticmethod
    def _clamp_speed(speed: int) -> int:
        return max(0, min(255, int(speed)))

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        connected = state == ConnectionState.CONNECTED
        if self._connected != connected or detail:
            self._connected = connected
            if connected:
                self._connected_event.set()
            else:
                self._connected_event.clear()
            bus.emit(
                SystemEvents.CONNECTION_STATUS_CHANGED,
                ConnectionStatus(channel="motor", state=state, detail=detail),
            )

    def _on_open(self, _app) -> None:
        self._connected_event.set()
        self._set_state(ConnectionState.CONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] Connected to motor websocket.")
        self.send_stop_now()

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
        self._connected_event.clear()
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

    def _start_udp_transport(self) -> None:
        if self._udp_target is None:
            self._disabled = True
            self._set_state(ConnectionState.DISCONNECTED, "invalid UDP motor endpoint")
            return
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setblocking(False)
            self._udp_socket = udp_socket
            self._set_state(ConnectionState.CONNECTED, f"udp://{self._udp_target[0]}:{self._udp_target[1]}")
            bus.emit(SystemEvents.LOG_MESSAGE, "[MotorController] UDP transport ready for low-latency drive commands.")
            self.send_stop_now()
        except Exception as exc:
            self._disabled = True
            self._set_state(ConnectionState.ERROR, str(exc))
            bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] UDP setup error: {exc}")

    def _sender_loop(self) -> None:
        interval = 1.0 / max(1, self._config.motor_send_hz)
        while self._running:
            self._send_event.wait(timeout=0.1)
            if not self._running:
                return
            command = self._take_pending_command()
            if command is None:
                continue

            if self._is_stale_motion_command(command):
                bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] Dropped stale motor command: {command.command}")
                continue

            if not self._connected:
                self._connected_event.wait(timeout=min(self._config.ws_recv_timeout, interval))
                if not self._connected:
                    now = time.monotonic()
                    if (now - self._last_waiting_log_at) >= 2.0:
                        self._last_waiting_log_at = now
                        bus.emit(
                            SystemEvents.LOG_MESSAGE,
                            "[MotorController] Waiting for the persistent Jarvis websocket before sending motors.",
                        )
                    self._restore_pending_command(command)
                    time.sleep(interval)
                    continue

            sent = self._send_payloads(command.payloads, command.command, command.enqueued_at)
            if not sent and self._running:
                self._restore_pending_command(command)
                time.sleep(interval)
                continue
            time.sleep(interval)

    def _take_pending_command(self) -> PendingMotorCommand | None:
        with self._lock:
            command = self._pending_command
            self._pending_command = self._pending_followup_command
            self._pending_followup_command = None
            if self._pending_command is None:
                self._send_event.clear()
            else:
                self._send_event.set()
            return command

    def _restore_pending_command(self, command: PendingMotorCommand) -> None:
        with self._lock:
            if self._pending_command is None:
                self._pending_command = command
            elif command.command == "S":
                self._pending_followup_command = command
        self._send_event.set()

    def _is_stale_motion_command(self, command: PendingMotorCommand) -> bool:
        if command.command == "S":
            return False
        ttl = max(0.05, float(self._config.motor_command_ttl_seconds))
        return (time.monotonic() - command.enqueued_at) > ttl

    def _send_udp_payloads(self, payloads: tuple[str, ...], command_key: str, enqueued_at: float) -> bool:
        if self._udp_target is None:
            return False
        with self._lock:
            udp_socket = self._udp_socket
        if udp_socket is None:
            return False
        try:
            host, port = self._udp_target
            for payload in payloads:
                udp_socket.sendto(payload.encode("utf-8"), (host, port))
            with self._lock:
                self._last_sent_command = command_key
                self._last_sent_at = time.monotonic()
            return True
        except Exception as exc:
            self._set_state(ConnectionState.ERROR, str(exc))
            bus.emit(SystemEvents.LOG_MESSAGE, f"[MotorController] UDP send error: {exc}")
            return False

    @staticmethod
    def _resolve_transport(url: str) -> str:
        scheme = urlparse(str(url or "")).scheme.lower()
        if scheme == "udp":
            return "udp"
        return "websocket"

    @staticmethod
    def _resolve_udp_target(url: str) -> tuple[str, int] | None:
        parsed = urlparse(str(url or ""))
        if parsed.scheme.lower() != "udp":
            return None
        if not parsed.hostname or parsed.port is None:
            return None
        return parsed.hostname, int(parsed.port)
