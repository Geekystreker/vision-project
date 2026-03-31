from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget, QApplication
)
from ui.arc_reactor_widget import ArcReactorWidget
from ui.theme import JARVIS_THEME
from core.event_bus import bus, SystemEvents

class UIEventBridge(QObject):
    """Bridges non-Qt EventBus signals into PyQt thread-safe signals."""
    log_signal = pyqtSignal(str)
    state_signal = pyqtSignal(str)
    voice_captured_signal = pyqtSignal(str)
    cmd_executed_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        # Subscribe to EventBus, which runs in background threads
        bus.subscribe(SystemEvents.LOG_MESSAGE, self.log_signal.emit)
        bus.subscribe(SystemEvents.STATE_CHANGE, self.state_signal.emit)
        bus.subscribe(SystemEvents.VOICE_TEXT_CAPTURED, self.voice_captured_signal.emit)
        bus.subscribe(SystemEvents.COMMAND_EXECUTED, self.cmd_executed_signal.emit)

class JarvisHUD(QMainWindow):
    KEY_TO_COMMAND = {
        Qt.Key_W: "F", Qt.Key_S: "B", Qt.Key_A: "L", Qt.Key_D: "R", Qt.Key_Space: "S",
    }

    def __init__(self, request_handler_callback):
        super().__init__()
        self.request_handler = request_handler_callback
        self.bridge = UIEventBridge()
        
        self._build_ui()
        self.setStyleSheet(JARVIS_THEME)
        
        # Connect internal Qt signals to UI elements
        self.bridge.log_signal.connect(self._append_log)
        self.bridge.state_signal.connect(self._update_core_state)
        self.bridge.voice_captured_signal.connect(self._handle_voice_input)
        self.bridge.cmd_executed_signal.connect(self._update_telemetry)

    def _build_ui(self) -> None:
        self.setWindowTitle("V.I.S.I.O.N. Protocol - JARVIS HUD")
        self.resize(1450, 900)
        self.setFocusPolicy(Qt.StrongFocus)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        title = QLabel("V.I.S.I.O.N. SYSTEM")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        hud_row = QHBoxLayout()
        hud_row.setSpacing(10)
        hud_row.addWidget(self._build_console_panel(), 2)
        hud_row.addWidget(self._build_core_panel(), 2)
        hud_row.addWidget(self._build_camera_panel(), 2)
        root.addLayout(hud_row, 1)

        root.addWidget(self._build_input_panel())

    def _build_console_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("hudPanel")
        layout = QVBoxLayout(panel)
        title = QLabel("CONSOLE / LOGS")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        
        self.console = QTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        layout.addWidget(self.console, 1)
        return panel

    def _build_core_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("corePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("ARC REACTOR CORE")
        title.setObjectName("panelTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.reactor = ArcReactorWidget()
        self.mode_label = QLabel("IDLE")
        self.mode_label.setObjectName("modeBadge")
        self.mode_label.setAlignment(Qt.AlignCenter)

        layout.addStretch(1)
        layout.addWidget(self.reactor, 1, alignment=Qt.AlignCenter)
        layout.addWidget(self.mode_label, alignment=Qt.AlignCenter)
        layout.addStretch(1)
        return panel

    def _build_camera_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("hudPanel")
        layout = QVBoxLayout(panel)
        title = QLabel("VISION PANEL")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.camera_placeholder = QLabel("CAMERA FEED (YOLOv8 PLACEHOLDER)")
        self.camera_placeholder.setObjectName("cameraBox")
        self.camera_placeholder.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.camera_placeholder, 1)

        telemetry_grid = QGridLayout()
        self.motion_value = QLabel("STOPPED")
        self.radar_value = QLabel("OFF")
        self.last_cmd_value = QLabel("NONE")

        rows = [("MOTION", self.motion_value), ("RADAR", self.radar_value), ("LAST CMD", self.last_cmd_value)]
        for index, (name, value) in enumerate(rows):
            key = QLabel(name)
            key.setObjectName("statKey")
            value.setObjectName("statValue")
            telemetry_grid.addWidget(key, index, 0)
            telemetry_grid.addWidget(value, index, 1)

        layout.addLayout(telemetry_grid)
        return panel

    def _build_input_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("hudPanel")
        layout = QHBoxLayout(panel)
        
        self.mic_btn = QPushButton("MIC: OFF")
        self.mic_btn.setObjectName("micBtn")
        self.mic_btn.setCheckable(True)
        self.mic_btn.clicked.connect(self._toggle_mic)
        layout.addWidget(self.mic_btn)
        
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type command...")
        self.input_box.returnPressed.connect(self._submit_text)
        layout.addWidget(self.input_box, 1)

        send_btn = QPushButton("EXECUTE")
        send_btn.clicked.connect(self._submit_text)
        layout.addWidget(send_btn)
        return panel

    def _toggle_mic(self):
        is_on = self.mic_btn.isChecked()
        if is_on:
            self.mic_btn.setText("MIC: LIVE")
            self.mic_btn.setStyleSheet("background-color: darkred; color: white; font-weight: bold;")
        else:
            self.mic_btn.setText("MIC: OFF")
            self.mic_btn.setStyleSheet("")
        bus.emit(SystemEvents.MIC_TOGGLE, is_on)

    def _append_log(self, text: str):
        self.console.append(text)

    def _update_core_state(self, state: str):
        state_upper = state.upper()
        
        # Init auto-resume flag if not present
        if not hasattr(self, "_mic_auto_suspended"):
            self._mic_auto_suspended = False

        if state_upper == "THINKING":
            self.reactor.set_thinking()
            
        elif state_upper == "SPEAKING":
            self.reactor.set_speaking()
            # Auto-suspend mic so it doesn't hear its own voice
            if self.mic_btn.isChecked():
                self._mic_auto_suspended = True
                self.mic_btn.setChecked(False)
                self._toggle_mic()
                
        else: # IDLE
            self.reactor.set_idle()
            # Auto-resume mic if it was suspended for speaking
            if self._mic_auto_suspended:
                self._mic_auto_suspended = False
                if not self.mic_btn.isChecked(): # Only check if user hasn't already manually turned it on
                    self.mic_btn.setChecked(True)
                    self._toggle_mic()

        self.mode_label.setText(state_upper)

    def _update_telemetry(self, cmd: str):
        self.last_cmd_value.setText(cmd)
        if cmd == "S": self.motion_value.setText("STOPPED")
        elif cmd == "F": self.motion_value.setText("FORWARD")
        elif cmd == "B": self.motion_value.setText("REVERSE")
        elif cmd == "RADAR_ON": self.radar_value.setText("ON")
        elif cmd == "RADAR_OFF": self.radar_value.setText("OFF")

    def _handle_voice_input(self, text: str):
        self.request_handler(text)

    def _submit_text(self):
        text = self.input_box.text().strip()
        if text:
            self.input_box.clear()
            self._append_log(f"[USER] {text}")
            self.request_handler(text)

    def keyPressEvent(self, event):
        if self.input_box.hasFocus():
            super().keyPressEvent(event)
            return

        if event.isAutoRepeat():
            return

        if event.key() == Qt.Key_M:
            self.mic_btn.setChecked(not self.mic_btn.isChecked())
            self._toggle_mic()
            return

        command = self.KEY_TO_COMMAND.get(event.key())
        if command:
            self.request_handler(command, is_raw_command=True)
        else:
            super().keyPressEvent(event)
