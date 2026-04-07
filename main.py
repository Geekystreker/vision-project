from __future__ import annotations

import os
import sys
import threading

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication

from config import Config, rover_config
from core.event_bus import SystemEvents, bus
from core.intent_router import IntentRouter
from modules.ai_ollama import OllamaAIEngine
from modules.audio_service import AudioService
from modules.command_handler import CommandHandler
from modules.control_arbiter import ControlArbiter
from modules.knowledge_base import KnowledgeBase
from modules.memory import Memory
from modules.rover_vision_app import RoverVisionApp
from modules.system_control import SystemController
from modules.tts_engine import TTSEngine
from ui.jarvis_hud import JarvisHUD


class SingleInstanceGuard(QObject):
    activation_requested = pyqtSignal()

    def __init__(self, server_name: str):
        super().__init__()
        self._server_name = server_name
        self._server = QLocalServer(self)

    def acquire(self) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self._server_name)
        if socket.waitForConnected(150):
            socket.write(b"ACTIVATE")
            socket.flush()
            socket.waitForBytesWritten(150)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._server_name)
        if not self._server.listen(self._server_name):
            return False
        self._server.newConnection.connect(self._handle_connection)
        return True

    def _handle_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.waitForReadyRead(150)
        _ = bytes(socket.readAll())
        socket.disconnectFromServer()
        self.activation_requested.emit()


def _single_instance_enabled(argv: list[str]) -> bool:
    if "--allow-multi-instance" in argv:
        return False
    env_value = (os.getenv("VISION_ALLOW_MULTI_INSTANCE", "") or "").strip().lower()
    return env_value not in {"1", "true", "yes", "on"}


class MainController:
    def __init__(self):
        self.memory = Memory()
        self.intent_router = IntentRouter()
        self.system_controller = SystemController()
        self.control_arbiter = ControlArbiter()
        self.knowledge_base = KnowledgeBase(rover_config)
        self.ai_engine = OllamaAIEngine(self.knowledge_base)
        self.tts = TTSEngine()
        self.audio_service = AudioService(rover_config)
        self.rover_vision_app = RoverVisionApp(rover_config, self.control_arbiter)

        threading.Thread(
            target=self.rover_vision_app.run,
            daemon=True,
            name="RoverVisionRuntime_Thread",
        ).start()

    def stop(self):
        self.audio_service.stop()
        self.rover_vision_app.stop()

    def handle_request(self, user_input: str, is_raw_command: bool = False):
        if not user_input:
            return

        if is_raw_command:
            self._handle_raw_command(user_input)
            return

        text = user_input.strip()
        if not text:
            return

        bus.emit(SystemEvents.LOG_MESSAGE, f"> Route analyzing: '{text}'")
        bus.emit(SystemEvents.STATE_CHANGE, "THINKING")

        local_cmd = CommandHandler.parse_local_command(text)
        if local_cmd:
            self._execute_control_command(local_cmd, source="VOICE")
            return

        intent = self.intent_router.detect_intent(text)
        if intent == IntentRouter.SYSTEM:
            self._handle_system(text)
            return

        self._handle_chat(text)

    def _handle_raw_command(self, command: str) -> None:
        token = (command or "").strip().upper()
        if token in {"F", "B", "L", "R", "S"}:
            self.rover_vision_app.send_drive_command(token, source="KEYBOARD")
            return

        if token == "__PAN_LEFT__":
            self.rover_vision_app.adjust_servo(pan_delta=-rover_config.servo_step, source="KEYBOARD")
        elif token == "__PAN_RIGHT__":
            self.rover_vision_app.adjust_servo(pan_delta=rover_config.servo_step, source="KEYBOARD")
        elif token == "__TILT_UP__":
            self.rover_vision_app.adjust_servo(tilt_delta=rover_config.servo_step, source="KEYBOARD")
        elif token == "__TILT_DOWN__":
            self.rover_vision_app.adjust_servo(tilt_delta=-rover_config.servo_step, source="KEYBOARD")
        elif token == "__TOGGLE_FOLLOW__":
            mode = self.rover_vision_app.toggle_follow_mode()
            bus.emit(SystemEvents.LOG_MESSAGE, f"[Control] Mode set to {mode.value}")
        elif token == "__INSPECT_SCENE__":
            self._execute_control_command("INSPECT", source="VOICE")
        elif token == "__E_STOP__":
            self._execute_control_command("E_STOP", source="E_STOP")

    def _execute_control_command(self, command: str, source: str) -> None:
        cmd = (command or "").upper()

        if cmd in {"F", "B", "L", "R", "S"}:
            self.memory.update_command(cmd)
            self.rover_vision_app.send_drive_command(cmd, source=source)
            self._speak(CommandHandler.speech_for(cmd), interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        if cmd == "FOLLOW":
            self.rover_vision_app.set_follow_mode()
            self._speak(CommandHandler.speech_for(cmd), interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        if cmd == "MANUAL":
            self.rover_vision_app.set_manual_mode()
            self._speak(CommandHandler.speech_for(cmd), interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        if cmd == "INSPECT":
            self.control_arbiter.begin_scene_inspection()
            description = self.rover_vision_app.describe_scene()
            self._speak(description, interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        if cmd == "E_STOP":
            self.rover_vision_app.emergency_stop()
            self._speak(CommandHandler.speech_for(cmd), interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

    def _handle_system(self, text: str) -> None:
        result = self.system_controller.handle_text(text)
        if result.get("speech"):
            self._speak(result["speech"])
        bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

    def _handle_chat(self, text: str) -> None:
        def callback(response_text: str):
            bus.emit(SystemEvents.LOG_MESSAGE, f"[V.I.S.I.O.N] {response_text}")
            self._speak(response_text)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

        self.ai_engine.run_chat_query_async(text, callback)

    def _speak(self, text: str, interrupt: bool = False):
        line = text.strip() if text and text.strip() else "Sorry, I did not catch that properly."
        try:
            self.tts.speak(
                line,
                on_start=lambda: bus.emit(SystemEvents.STATE_CHANGE, "SPEAKING"),
                on_done=lambda: bus.emit(SystemEvents.STATE_CHANGE, "IDLE"),
                interrupt=interrupt,
            )
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[TTS] Speech failed: {exc}")


def main():
    app = QApplication(sys.argv)

    use_single_instance = _single_instance_enabled(sys.argv[1:])
    guard = SingleInstanceGuard(Config.SINGLE_INSTANCE_SERVER) if use_single_instance else None
    if guard is not None and not guard.acquire():
        print(
            "[V.I.S.I.O.N] Existing instance is already running. "
            "Close it first to load new code changes, or relaunch with "
            "--allow-multi-instance (or VISION_ALLOW_MULTI_INSTANCE=1)."
        )
        return 0

    controller = MainController()
    window = JarvisHUD(request_handler_callback=controller.handle_request, config=rover_config)
    window.show()

    def activate_window():
        window.showNormal()
        window.raise_()
        window.activateWindow()

    if guard is not None:
        guard.activation_requested.connect(activate_window)

    ret = app.exec_()
    controller.stop()
    return ret


if __name__ == "__main__":
    sys.exit(main())
