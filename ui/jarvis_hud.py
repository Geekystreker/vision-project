from __future__ import annotations

import threading

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import RoverConfig
from core.event_bus import SystemEvents, bus
from ui.arc_reactor_widget import ArcReactorWidget
from ui.theme import JARVIS_THEME


class UIEventBridge(QObject):
    log_signal = pyqtSignal(str)
    state_signal = pyqtSignal(str)
    voice_captured_signal = pyqtSignal(str)
    cmd_executed_signal = pyqtSignal(str)
    frame_signal = pyqtSignal(object)
    mode_signal = pyqtSignal(str)
    connection_signal = pyqtSignal(object)

    def __init__(self, frame_hz: int = 30):
        super().__init__()
        self._frame_lock = threading.Lock()
        self._pending_frame = None
        bus.subscribe(SystemEvents.LOG_MESSAGE, self.log_signal.emit)
        bus.subscribe(SystemEvents.STATE_CHANGE, self.state_signal.emit)
        bus.subscribe(SystemEvents.VOICE_TEXT_CAPTURED, self.voice_captured_signal.emit)
        bus.subscribe(SystemEvents.COMMAND_EXECUTED, self.cmd_executed_signal.emit)
        bus.subscribe(SystemEvents.FRAME_READY, self._queue_frame)
        bus.subscribe(SystemEvents.CONTROL_MODE_CHANGED, self.mode_signal.emit)
        bus.subscribe(SystemEvents.CONNECTION_STATUS_CHANGED, self.connection_signal.emit)

        self._frame_timer = QTimer(self)
        interval_ms = max(10, int(round(1000 / max(1, frame_hz))))
        self._frame_timer.setInterval(interval_ms)
        self._frame_timer.timeout.connect(self._flush_frame)
        self._frame_timer.start()

    def _queue_frame(self, snapshot) -> None:
        with self._frame_lock:
            self._pending_frame = snapshot

    def _flush_frame(self) -> None:
        with self._frame_lock:
            snapshot = self._pending_frame
            self._pending_frame = None
        if snapshot is not None:
            self.frame_signal.emit(snapshot)


class CameraFeedWidget(QLabel):
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._placeholder = placeholder
        self._base_pixmap: QPixmap | None = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(self.FRAME_WIDTH, self.FRAME_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        if width <= 0:
            return self.FRAME_HEIGHT
        return int(width * self.FRAME_HEIGHT / self.FRAME_WIDTH)

    def show_placeholder(self, text: str | None = None) -> None:
        self._base_pixmap = None
        self.clear()
        self.setText(text or self._placeholder)

    def set_frame_image(self, image: QImage) -> None:
        self._base_pixmap = QPixmap.fromImage(image.copy())
        self._apply_viewport_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_viewport_pixmap()

    def _apply_viewport_pixmap(self) -> None:
        if self._base_pixmap is None:
            return
        viewport = self.contentsRect().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return
        transform_mode = (
            Qt.SmoothTransformation
            if self._base_pixmap.width() < viewport.width() or self._base_pixmap.height() < viewport.height()
            else Qt.FastTransformation
        )
        scaled = self._base_pixmap.scaled(
            viewport,
            Qt.KeepAspectRatio,
            transform_mode,
        )
        self.clear()
        self.setPixmap(scaled)


class JarvisHUD(QMainWindow):
    DRIVE_KEY_MAP = {
        Qt.Key_W: "F",
        Qt.Key_S: "B",
        Qt.Key_A: "L",
        Qt.Key_D: "R",
    }

    SERVO_KEY_MAP = {
        Qt.Key_Left: "__PAN_LEFT__",
        Qt.Key_Right: "__PAN_RIGHT__",
        Qt.Key_Up: "__TILT_UP__",
        Qt.Key_Down: "__TILT_DOWN__",
    }

    def __init__(self, request_handler_callback, config: RoverConfig | None = None):
        super().__init__()
        self.request_handler = request_handler_callback
        self._config = config
        frame_hz = config.ui_frame_hz if config is not None else 30
        self.bridge = UIEventBridge(frame_hz=frame_hz)

        self._pressed_drive_keys: set[int] = set()
        self._pressed_servo_keys: set[int] = set()
        self._key_timestamps: dict[int, int] = {}
        self._key_counter = 0
        self._last_drive_command = "S"

        self._build_ui()
        self.setStyleSheet(JARVIS_THEME)

        self.bridge.log_signal.connect(self._append_log)
        self.bridge.state_signal.connect(self._update_core_state)
        self.bridge.voice_captured_signal.connect(self._handle_voice_input)
        self.bridge.cmd_executed_signal.connect(self._update_telemetry)
        self.bridge.frame_signal.connect(self._update_frame)
        self.bridge.mode_signal.connect(self._update_mode)
        self.bridge.connection_signal.connect(self._update_connections)

        self._input_timer = QTimer(self)
        key_repeat_hz = self._config.key_repeat_hz if self._config is not None else 15
        self._input_timer.setInterval(max(16, int(round(1000 / max(1, key_repeat_hz)))))
        self._input_timer.timeout.connect(self._dispatch_held_keys)
        self._input_timer.start()

    def _build_ui(self) -> None:
        self.setWindowTitle("V.I.S.I.O.N Control Panel")
        self.resize(1560, 960)
        self.setFocusPolicy(Qt.StrongFocus)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        title = QLabel("V.I.S.I.O.N CONTROL PANEL")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Local AI rover operator for manual drive, follow mode, and scene awareness")
        subtitle.setObjectName("subtitleLabel")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        header.addLayout(title_stack)
        header.addStretch(1)

        self.mode_label = QLabel("IDLE")
        self.mode_label.setObjectName("modeBadge")
        header.addWidget(self.mode_label)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)
        content.addWidget(self._build_left_column(), 1)
        content.addWidget(self._build_right_column(), 2)
        root.addLayout(content, 1)

        root.addWidget(self._build_input_panel())

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setSpacing(14)
        layout.addWidget(self._build_core_panel())
        layout.addWidget(self._build_status_panel())
        layout.addStretch(1)
        return column

    def _build_right_column(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setSpacing(14)
        layout.addWidget(self._build_camera_panel(), 2)
        layout.addWidget(self._build_console_panel(), 1)
        return column

    def _build_core_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("COMMAND CORE")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.reactor = ArcReactorWidget()
        layout.addWidget(self.reactor, 1, alignment=Qt.AlignCenter)

        chips = QHBoxLayout()
        self.camera_chip = QLabel("CAM OFFLINE")
        self.motor_chip = QLabel("MOTOR OFFLINE")
        self.servo_chip = QLabel("SERVO OFFLINE")
        for widget in (self.camera_chip, self.motor_chip, self.servo_chip):
            widget.setObjectName("chip")
            chips.addWidget(widget)
        layout.addLayout(chips)

        actions = QHBoxLayout()
        self.follow_btn = QPushButton("FOLLOW")
        self.follow_btn.setCheckable(True)
        self.follow_btn.clicked.connect(lambda: self.request_handler("__TOGGLE_FOLLOW__", is_raw_command=True))
        self.estop_btn = QPushButton("E-STOP")
        self.estop_btn.setObjectName("dangerButton")
        self.estop_btn.clicked.connect(lambda: self.request_handler("__E_STOP__", is_raw_command=True))
        actions.addWidget(self.follow_btn)
        actions.addWidget(self.estop_btn)
        layout.addLayout(actions)
        return panel

    def _build_status_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QGridLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(12)

        title = QLabel("ROVER STATUS")
        title.setObjectName("panelTitle")
        layout.addWidget(title, 0, 0, 1, 2)

        self.motion_value = QLabel("STOPPED")
        self.last_cmd_value = QLabel("S")
        self.fps_value = QLabel("0.0")
        self.target_value = QLabel("NONE")

        metrics = [
            ("MOTION", self.motion_value),
            ("LAST CMD", self.last_cmd_value),
            ("FPS R/C", self.fps_value),
            ("TARGET", self.target_value),
        ]
        for row, (label_text, value_label) in enumerate(metrics, start=1):
            key = QLabel(label_text)
            key.setObjectName("metricKey")
            value_label.setObjectName("metricValue")
            layout.addWidget(key, row, 0)
            layout.addWidget(value_label, row, 1)
        return panel

    def _build_camera_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("heroPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("LIVE VISION")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        hud_strip = QHBoxLayout()
        hud_strip.setSpacing(8)
        self.camera_mode_badge = QLabel("IDLE")
        self.camera_mode_badge.setObjectName("cameraHudBadgeStrong")
        self.camera_cmd_badge = QLabel("CMD S")
        self.camera_cmd_badge.setObjectName("cameraHudBadge")
        self.camera_fps_badge = QLabel("FPS 0.0 / 0.0")
        self.camera_fps_badge.setObjectName("cameraHudBadge")
        self.camera_link_badge = QLabel("CAM OFFLINE")
        self.camera_link_badge.setObjectName("cameraHudBadge")
        self.camera_target_badge = QLabel("TARGET NONE")
        self.camera_target_badge.setObjectName("cameraHudBadge")
        for widget in (
            self.camera_mode_badge,
            self.camera_cmd_badge,
            self.camera_fps_badge,
            self.camera_link_badge,
            self.camera_target_badge,
        ):
            hud_strip.addWidget(widget)
        hud_strip.addStretch(1)
        layout.addLayout(hud_strip)

        self.camera_feed = CameraFeedWidget("Waiting for ESP32-CAM stream...")
        self.camera_feed.setObjectName("cameraFeed")
        self.camera_feed.setFixedSize(760, 570)
        feed_row = QHBoxLayout()
        feed_row.addStretch(1)
        feed_row.addWidget(self.camera_feed, 1)
        feed_row.addStretch(1)
        layout.addLayout(feed_row, 1)

        self.camera_caption = QLabel(
            "640x480 optimized live view (4:3). W/A/S/D drive, arrows pan/tilt, T follow, Space E-stop"
        )
        self.camera_caption.setObjectName("cameraCaption")
        layout.addWidget(self.camera_caption)
        return panel

    def _build_console_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("MISSION LOG")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.console = QTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        layout.addWidget(self.console, 1)
        return panel

    def _build_input_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.mic_btn = QPushButton("MIC OFF")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self._toggle_mic)
        layout.addWidget(self.mic_btn)

        inspect_btn = QPushButton("INSPECT")
        inspect_btn.clicked.connect(lambda: self.request_handler("__INSPECT_SCENE__", is_raw_command=True))
        layout.addWidget(inspect_btn)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Ask V.I.S.I.O.N to explain the project, move the rover, or inspect the scene...")
        self.input_box.returnPressed.connect(self._submit_text)
        layout.addWidget(self.input_box, 1)

        send_btn = QPushButton("EXECUTE")
        send_btn.clicked.connect(self._submit_text)
        layout.addWidget(send_btn)
        return panel

    def _toggle_mic(self) -> None:
        is_on = self.mic_btn.isChecked()
        self.mic_btn.setText("MIC LIVE" if is_on else "MIC OFF")
        bus.emit(SystemEvents.MIC_TOGGLE, is_on)

    def _append_log(self, text: str) -> None:
        self.console.append(text)

    def _update_core_state(self, state: str) -> None:
        state_upper = (state or "IDLE").upper()
        if state_upper == "THINKING":
            self.reactor.set_thinking()
        elif state_upper == "SPEAKING":
            self.reactor.set_speaking()
        else:
            self.reactor.set_idle()

    def _update_mode(self, mode: str) -> None:
        mode = (mode or "IDLE").upper()
        self.mode_label.setText(mode)
        self.camera_mode_badge.setText(mode)
        self.follow_btn.setChecked(mode == "FOLLOW_PERSON")

    def _update_connections(self, status) -> None:
        if status is None:
            return
        channel = getattr(status, "channel", "")
        state = getattr(status, "state", None)
        state_text = getattr(state, "value", "UNKNOWN")
        detail = (getattr(status, "detail", "") or "").lower()
        if channel == "camera":
            self.camera_chip.setText(f"CAM {state_text}")
            self.camera_link_badge.setText(f"CAM {state_text}")
        elif channel == "motor":
            self.motor_chip.setText("MOTOR STANDBY" if "disabled" in detail else f"MOTOR {state_text}")
        elif channel == "servo":
            self.servo_chip.setText("SERVO STANDBY" if "disabled" in detail else f"SERVO {state_text}")

    def _update_telemetry(self, cmd: str) -> None:
        cmd = (cmd or "").upper()
        self.last_cmd_value.setText(cmd or "S")
        mapping = {
            "F": "FORWARD",
            "B": "REVERSE",
            "L": "TURN LEFT",
            "R": "TURN RIGHT",
            "S": "STOPPED",
        }
        self.motion_value.setText(mapping.get(cmd, cmd or "STOPPED"))
        self.camera_cmd_badge.setText(f"CMD {cmd or 'S'}")

    def _update_frame(self, snapshot) -> None:
        if snapshot is None:
            return
        frame = getattr(snapshot, "frame", None)
        render_fps = getattr(snapshot, "fps", 0.0)
        source_fps = getattr(snapshot, "source_fps", 0.0)
        self.fps_value.setText(f"{render_fps:.1f}/{source_fps:.1f}")
        self.camera_fps_badge.setText(f"FPS {render_fps:.1f} / {source_fps:.1f}")
        target = getattr(snapshot, "target", None)
        self.target_value.setText(f"#{target.target_id}" if target else "NONE")
        self.camera_target_badge.setText(f"TARGET #{target.target_id}" if target else "TARGET NONE")

        if frame is None:
            self.camera_feed.show_placeholder("Waiting for ESP32-CAM stream...")
            return

        height, width, _ = frame.shape
        image = QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888)
        self.camera_feed.set_frame_image(image)

    def _handle_voice_input(self, text: str) -> None:
        self.request_handler(text)

    def _submit_text(self) -> None:
        text = self.input_box.text().strip()
        if text:
            self.input_box.clear()
            self._append_log(f"[USER] {text}")
            self.request_handler(text)

    def _dispatch_held_keys(self) -> None:
        if self.input_box.hasFocus():
            return

        drive_key = self._most_recent_key(self._pressed_drive_keys)
        if drive_key is not None:
            command = self.DRIVE_KEY_MAP[drive_key]
            self.request_handler(command, is_raw_command=True)
            self._last_drive_command = command
        elif self._last_drive_command != "S":
            self.request_handler("S", is_raw_command=True)
            self._last_drive_command = "S"

        servo_key = self._most_recent_key(self._pressed_servo_keys)
        if servo_key is not None:
            self.request_handler(self.SERVO_KEY_MAP[servo_key], is_raw_command=True)

    def keyPressEvent(self, event) -> None:
        if self.input_box.hasFocus():
            super().keyPressEvent(event)
            return

        key = event.key()
        if event.isAutoRepeat():
            event.accept()
            return

        if key == Qt.Key_M:
            self.mic_btn.setChecked(not self.mic_btn.isChecked())
            self._toggle_mic()
            return
        if key == Qt.Key_T:
            self.request_handler("__TOGGLE_FOLLOW__", is_raw_command=True)
            return
        if key == Qt.Key_I:
            self.request_handler("__INSPECT_SCENE__", is_raw_command=True)
            return
        if key == Qt.Key_Space:
            self.request_handler("__E_STOP__", is_raw_command=True)
            self._last_drive_command = "S"
            return

        if key in self.DRIVE_KEY_MAP:
            self._pressed_drive_keys.add(key)
            self._key_counter += 1
            self._key_timestamps[key] = self._key_counter
            event.accept()
            return

        if key in self.SERVO_KEY_MAP:
            self._pressed_servo_keys.add(key)
            self._key_counter += 1
            self._key_timestamps[key] = self._key_counter
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        key = event.key()
        if event.isAutoRepeat():
            event.accept()
            return

        self._pressed_drive_keys.discard(key)
        self._pressed_servo_keys.discard(key)
        if key in self.DRIVE_KEY_MAP and not self._pressed_drive_keys:
            self.request_handler("S", is_raw_command=True)
            self._last_drive_command = "S"
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _most_recent_key(self, keys: set[int]) -> int | None:
        if not keys:
            return None
        return max(keys, key=lambda item: self._key_timestamps.get(item, 0))
