from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import websocket

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from modules.jarvis_protocol import servo_packet, uses_json_protocol, uses_legacy_protocol
from modules.rover_types import ConnectionState, ConnectionStatus


@dataclass(slots=True)
class PendingServoCommand:
    payload: str
    enqueued_at: float


class ServoController:
    """Persistent WebSocket sender for camera pan / tilt commands."""

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
        self._pending_command: PendingServoCommand | None = None
        self._transport_latency_ms = 0.0
        self._pan_angle = int(config.servo_center_angle)
        self._tilt_angle = int(config.servo_center_angle)
        self._last_sent_payload = ""
        self._last_sent_at = 0.0
        self._last_waiting_log_at = 0.0

    def start(self) -> None:
        if self._disabled or self._started:
            if self._disabled:
                self._set_state(ConnectionState.DISCONNECTED, "servo endpoint disabled")
            return
        self._running = True
        self._started = True
        if self._transport == "udp":
            self._start_udp_transport()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True, name="ServoControllerSocket_Thread")
            self._thread.start()
        self._sender_thread = threading.Thread(
            target=self._sender_loop,
            daemon=True,
            name="ServoControllerSender_Thread",
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

    def send(self, command: str) -> bool:
        if self._disabled:
            return False
        if not self._started:
            self.start()
        payload = self._payload_for_command(command)
        if not payload:
            return False
        now = time.monotonic()
        with self._lock:
            self._update_cached_angles(command)
            if self._pending_command is not None and self._pending_command.payload == payload:
                return True
            if (
                self._last_sent_payload == payload
                and (now - self._last_sent_at) < (1.0 / max(1, self._config.servo_send_hz))
            ):
                return True
            self._pending_command = PendingServoCommand(payload=payload, enqueued_at=time.monotonic())
        self._send_event.set()
        return True

    def send_pan_tilt(self, pan: int, tilt: int) -> bool:
        pan = max(self._config.servo_pan_min_angle, min(self._config.servo_pan_max_angle, int(pan)))
        tilt = max(self._config.servo_tilt_min_angle, min(self._config.servo_tilt_max_angle, int(tilt)))
        with self._lock:
            self._pan_angle = pan
            self._tilt_angle = tilt
        return self.send(self._format_servo_payload(pan=pan, tilt=tilt))

    def current_angles(self) -> tuple[int, int]:
        with self._lock:
            return self._pan_angle, self._tilt_angle

    def latency_ms(self) -> float:
        with self._lock:
            return self._transport_latency_ms

    def is_connected(self) -> bool:
        return self._connected

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
                ConnectionStatus(channel="servo", state=state, detail=detail),
            )

    def _on_open(self, _app) -> None:
        self._connected_event.set()
        self._set_state(ConnectionState.CONNECTED)
        bus.emit(SystemEvents.LOG_MESSAGE, "[ServoController] Connected to servo websocket.")
        with self._lock:
            has_prior_pose = bool(self._last_sent_payload or self._pending_command is not None)
        if has_prior_pose:
            pan, tilt = self.current_angles()
            self.send_pan_tilt(pan, tilt)

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

    def _start_udp_transport(self) -> None:
        if self._udp_target is None:
            self._set_state(ConnectionState.DISCONNECTED, "invalid UDP servo endpoint")
            self._disabled = True
            return
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setblocking(False)
            self._udp_socket = udp_socket
            self._set_state(ConnectionState.CONNECTED, f"udp://{self._udp_target[0]}:{self._udp_target[1]}")
            bus.emit(SystemEvents.LOG_MESSAGE, "[ServoController] UDP transport ready for low-latency pan/tilt.")
        except Exception as exc:
            self._disabled = True
            self._set_state(ConnectionState.ERROR, str(exc))
            bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] UDP setup error: {exc}")

    def _sender_loop(self) -> None:
        interval = 1.0 / max(1, self._config.servo_send_hz)
        while self._running:
            self._send_event.wait(timeout=0.1)
            if not self._running:
                return
            command = self._take_pending_command()
            if command is None:
                continue

            if not self._connected:
                self._connected_event.wait(timeout=min(self._config.ws_recv_timeout, interval))
                if not self._connected:
                    now = time.monotonic()
                    if (now - self._last_waiting_log_at) >= 2.0:
                        self._last_waiting_log_at = now
                        bus.emit(
                            SystemEvents.LOG_MESSAGE,
                            "[ServoController] Waiting for the persistent Jarvis websocket before sending pan/tilt.",
                        )
                    self._restore_pending_command(command)
                    time.sleep(interval)
                    continue

            sent = self._send_immediately(command)
            if not sent and self._running:
                self._restore_pending_command(command)
                time.sleep(interval)
                continue
            time.sleep(interval)

    def _take_pending_command(self) -> PendingServoCommand | None:
        with self._lock:
            command = self._pending_command
            self._pending_command = None
            self._send_event.clear()
            return command

    def _restore_pending_command(self, command: PendingServoCommand) -> None:
        with self._lock:
            if self._pending_command is None:
                self._pending_command = command
        self._send_event.set()

    def _send_immediately(self, command: PendingServoCommand) -> bool:
        try:
            if self._transport == "udp":
                return self._send_udp_payload(command)
            with self._lock:
                app = self._app
            if app and app.sock and app.sock.connected:
                started = time.monotonic()
                for payload in command.payload.splitlines():
                    payload = payload.strip()
                    if payload:
                        app.send(payload)
                latency_ms = (time.monotonic() - command.enqueued_at) * 1000.0
                transport_ms = (time.monotonic() - started) * 1000.0
                with self._lock:
                    self._transport_latency_ms = max(latency_ms, transport_ms)
                    self._last_sent_payload = command.payload
                    self._last_sent_at = time.monotonic()
                return True
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] send error: {exc}")
        return False

    def _send_udp_payload(self, command: PendingServoCommand) -> bool:
        if self._udp_target is None:
            return False
        with self._lock:
            udp_socket = self._udp_socket
        if udp_socket is None:
            return False
        try:
            started = time.monotonic()
            host, port = self._udp_target
            for payload in command.payload.splitlines():
                payload = payload.strip()
                if payload:
                    udp_socket.sendto(payload.encode("utf-8"), (host, port))
            latency_ms = (time.monotonic() - command.enqueued_at) * 1000.0
            transport_ms = (time.monotonic() - started) * 1000.0
            with self._lock:
                self._transport_latency_ms = max(latency_ms, transport_ms)
                self._last_sent_payload = command.payload
                self._last_sent_at = time.monotonic()
            return True
        except Exception as exc:
            self._set_state(ConnectionState.ERROR, str(exc))
            bus.emit(SystemEvents.LOG_MESSAGE, f"[ServoController] UDP send error: {exc}")
            return False

    def _update_cached_angles(self, payload: str) -> None:
        for axis, value in self._extract_servo_axes(payload).items():
            if axis == "pan":
                self._pan_angle = max(self._config.servo_pan_min_angle, min(self._config.servo_pan_max_angle, value))
            elif axis == "tilt":
                self._tilt_angle = max(self._config.servo_tilt_min_angle, min(self._config.servo_tilt_max_angle, value))

    def _payload_for_command(self, payload: str) -> str:
        text = str(payload or "").strip()
        if not text:
            return ""
        axes = self._extract_servo_axes(text)
        if axes:
            return self._format_servo_payload(pan=axes.get("pan"), tilt=axes.get("tilt"))
        return text

    def _format_servo_payload(self, *, pan: int | None = None, tilt: int | None = None) -> str:
        lines: list[str] = []
        if uses_json_protocol(self._config):
            lines.append(servo_packet(self._config, pan=pan, tilt=tilt))
        if not uses_legacy_protocol(self._config):
            return "\n".join(lines)
        if pan is not None:
            lines.append(f"Pan,{pan}")
        if tilt is not None:
            lines.append(f"Tilt,{tilt}")
        return "\n".join(lines)

    def _extract_servo_axes(self, payload: str) -> dict[str, int]:
        text = str(payload or "").strip()
        if not text:
            return {}
        if text.startswith("{"):
            try:
                packet = json.loads(text.splitlines()[0])
            except json.JSONDecodeError:
                return {}
            axes: dict[str, int] = {}
            for axis in ("pan", "tilt"):
                if axis in packet:
                    try:
                        axes[axis] = int(float(packet[axis]))
                    except (TypeError, ValueError):
                        pass
            return axes

        axes: dict[str, int] = {}
        for line in text.splitlines():
            tokens = [part.strip() for part in line.split(",") if part.strip()]
            if len(tokens) < 2:
                continue
            axis = tokens[0].lower()
            try:
                value = int(float(tokens[1]))
            except ValueError:
                continue
            if axis == "pan":
                axes["pan"] = value
            elif axis == "tilt":
                axes["tilt"] = value
        return axes

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
