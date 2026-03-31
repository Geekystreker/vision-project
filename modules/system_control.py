import os
import platform
import re
import subprocess
from typing import Dict, Optional

try:
    import pyautogui
except Exception:  
    pyautogui = None

from core.event_bus import bus, SystemEvents

class SystemController:
    def _log(self, message: str) -> None:
        bus.emit(SystemEvents.LOG_MESSAGE, f"[SYSTEM] {message}")

    def open_app(self, app_name: str) -> Dict[str, object]:
        app = (app_name or "").strip().lower()
        app_map = {
            "chrome": "chrome",
            "browser": "chrome",
            "notepad": "notepad",
            "calculator": "calc",
            "cmd": "cmd",
            "terminal": "cmd",
        }
        target = app_map.get(app, app)
        if not target:
            return {"ok": False, "message": "No app specified", "speech": "Please tell me which app to open"}

        system = platform.system().lower()
        try:
            if "windows" in system:
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
            elif "darwin" in system:
                subprocess.Popen(["open", "-a", target], shell=False)
            else:
                subprocess.Popen([target], shell=False)
            message = f"Opened {target}"
            self._log(message)
            return {"ok": True, "message": message, "speech": f"Opening {target}"}
        except Exception as exc:
            message = f"Failed to open {target}: {exc}"
            self._log(message)
            return {"ok": False, "message": message, "speech": f"I could not open {target}"}

    def close_window(self) -> Dict[str, object]:
        if pyautogui is None:
            return {
                "ok": False,
                "message": "pyautogui is not installed",
                "speech": "I cannot close windows because pyautogui is unavailable",
            }
        try:
            pyautogui.hotkey("alt", "f4")
            message = "Active window close command sent"
            self._log(message)
            return {"ok": True, "message": message, "speech": "Closing the current window"}
        except Exception as exc:
            message = f"Failed to close window: {exc}"
            self._log(message)
            return {"ok": False, "message": message, "speech": "I could not close the window"}

    def shutdown_pc(self, confirmed: bool = False) -> Dict[str, object]:
        if not confirmed:
            return {
                "ok": False,
                "message": "Shutdown requires confirmation",
                "speech": "Shutdown requires confirmation. Say confirm shutdown to continue",
            }

        system = platform.system().lower()
        try:
            if "windows" in system:
                os.system("shutdown /s /t 10")
            elif "darwin" in system:
                os.system("sudo shutdown -h +0")
            else:
                os.system("shutdown -h now")
            message = "Shutdown sequence started"
            self._log(message)
            return {"ok": True, "message": message, "speech": "Shutting down the system"}
        except Exception as exc:
            message = f"Failed to initiate shutdown: {exc}"
            self._log(message)
            return {"ok": False, "message": message, "speech": "I could not start shutdown"}

    def handle_text(self, user_input: str) -> Dict[str, object]:
        text = (user_input or "").strip().lower()
        if not text:
            return {"ok": False, "message": "Empty system command", "speech": "I did not hear a system command"}

        if "open" in text:
            match = re.search(r"open\s+([a-zA-Z0-9_.-]+)", text)
            app_name = match.group(1) if match else ""
            return self.open_app(app_name)

        if "close" in text:
            return self.close_window()

        if "shutdown" in text:
            confirmed = "confirm" in text or "yes" in text
            return self.shutdown_pc(confirmed=confirmed)

        return {
            "ok": False,
            "message": "System command not recognized",
            "speech": "I could not recognize that system command",
        }
