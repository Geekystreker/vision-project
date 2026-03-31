import sys
from PyQt5.QtWidgets import QApplication

from config import Config
from core.intent_router import IntentRouter
from core.event_bus import bus, SystemEvents

from modules.voice_engine import VoiceEngine
from modules.tts_engine import TTSEngine
from modules.ai_ollama import OllamaAIEngine
from modules.system_control import SystemController
from modules.rover_control import RoverController
from modules.command_handler import CommandHandler
from modules.memory import Memory
from ui.jarvis_hud import JarvisHUD

class MainController:
    def __init__(self):
        self.intent_router = IntentRouter()
        self.ai_engine = OllamaAIEngine()
        self.system_controller = SystemController()
        self.rover_controller = RoverController()
        self.memory = Memory()
        
        self.voice_engine = VoiceEngine()
        self.tts = TTSEngine()

        # Connect UI Toggle to Voice Engine
        bus.subscribe(SystemEvents.MIC_TOGGLE, self.voice_engine.toggle_listening)

    def stop(self):
        self.voice_engine.toggle_listening(False)

    def handle_request(self, user_input: str, is_raw_command: bool = False):
        if not user_input: return
        
        # Immediate shortcut for keyboard raw commands
        if is_raw_command:
            self._execute_rover_cmd(user_input)
            return

        text = user_input.lower().strip()
        
        # Log Memory state
        bus.emit(SystemEvents.LOG_MESSAGE, f"[Memory] Last Command: {self.memory.last_command} | Last Suggestion: {self.memory.last_suggestion}")

        # Memory Context Intercepts
        if text in ["yes", "yeah", "do it"] and self.memory.last_suggestion:
            bus.emit(SystemEvents.LOG_MESSAGE, f"> Memory confirmation matched: {self.memory.last_suggestion}")
            self._execute_rover_cmd(self.memory.last_suggestion)
            return
            
        if text == "stop" and self.memory.last_command in ["F", "B", "L", "R"]:
            bus.emit(SystemEvents.LOG_MESSAGE, "> Memory intercept: Halting previous movement")
            self._execute_rover_cmd("S")
            return

        bus.emit(SystemEvents.LOG_MESSAGE, f"> Route analyzing: '{user_input}'")
        bus.emit(SystemEvents.STATE_CHANGE, "THINKING")

        intent = self.intent_router.detect_intent(user_input)
        
        if intent == IntentRouter.SYSTEM:
            self._handle_system(user_input)

        elif intent == IntentRouter.COMMAND:
            cmd = CommandHandler.parse_local_command(user_input)
            if cmd:
                self._execute_rover_cmd(cmd)
            else:
                self.ai_engine.run_command_extraction_async(user_input, self._execute_rover_cmd)
        else:
            self._handle_chat(user_input)

    def _execute_rover_cmd(self, cmd: str):
        if not cmd or cmd == "UNKNOWN":
            bus.emit(SystemEvents.LOG_MESSAGE, "[Rover] Failed to extract command.")
            self._speak("I didn't understand that command.", interrupt=True)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")
            return

        # Handle Memory resets and suggestions
        if cmd.startswith("CLARIFY_"):
            self.memory.set_suggestion(cmd.replace("CLARIFY_", ""))
        else:
            self.memory.update_command(cmd)
            self.memory.clear_suggestion()

        response = self.rover_controller.send_command(cmd)
        speech = CommandHandler.speech_for(cmd)
        self._speak(speech, interrupt=True)
        
        bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

    def _handle_system(self, text: str):
        res = self.system_controller.handle_text(text)
        if res.get("speech"):
            self._speak(res["speech"])
        bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

    def _handle_chat(self, text: str):
        def callback(response_text: str):
            bus.emit(SystemEvents.LOG_MESSAGE, f"[Jarvis] {response_text}")
            self._speak(response_text)
            bus.emit(SystemEvents.STATE_CHANGE, "IDLE")

        self.ai_engine.run_chat_query_async(text, callback)

    def _speak(self, text: str, interrupt: bool = False):
        if not text or not text.strip():
            text = "Sorry, I didn't catch that properly."
        print(f"[SPEAKING]: {text}")
        try:
            self.tts.speak(
                text,
                on_start=lambda: bus.emit(SystemEvents.STATE_CHANGE, "SPEAKING"),
                on_done=lambda: bus.emit(SystemEvents.STATE_CHANGE, "IDLE"),
                interrupt=interrupt
            )
        except Exception as e:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[TTS] Speech failed: {e}")


def main():
    app = QApplication(sys.argv)
    
    # Init central controller
    controller = MainController()
    
    # Init UI, pass the request callback
    window = JarvisHUD(request_handler_callback=controller.handle_request)
    window.show()
    
    # Let app run
    ret = app.exec_()
    
    # Cleanup background threads gracefully
    controller.stop()
    sys.exit(ret)

if __name__ == "__main__":
    main()
