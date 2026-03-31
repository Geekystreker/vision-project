from dataclasses import dataclass
from typing import Dict, Optional
from core.event_bus import bus, SystemEvents

@dataclass
class RoverState:
    motion: str = "STOPPED"
    radar_on: bool = False
    last_command: str = "S"


class RoverController:
    VALID_COMMANDS = {"F", "B", "L", "R", "S", "RADAR_ON", "RADAR_OFF", "SCAN", "MAP"}

    def __init__(self):
        self.state = RoverState()

    def _log(self, message: str) -> None:
        bus.emit(SystemEvents.LOG_MESSAGE, f"[ROVER] {message}")

    def send_command(self, command: str) -> Dict[str, object]:
        cmd = (command or "").strip().upper()
        if cmd.startswith("CLARIFY_"):
            message = f"Pending clarification: {cmd}"
            self._log(message)
            return {"ok": True, "message": message, **self.get_state()}

        if cmd not in self.VALID_COMMANDS:
            message = f"Invalid command: {cmd or '<EMPTY>'}"
            self._log(message)
            return {"ok": False, "message": message, **self.get_state()}

        self.state.last_command = cmd
        if cmd == "F":
            self.state.motion = "FORWARD"
            message = "Moving forward"
        elif cmd == "B":
            self.state.motion = "BACKWARD"
            message = "Moving backward"
        elif cmd == "L":
            self.state.motion = "TURN_LEFT"
            message = "Turning left"
        elif cmd == "R":
            self.state.motion = "TURN_RIGHT"
            message = "Turning right"
        elif cmd == "S":
            self.state.motion = "STOPPED"
            message = "Stopped"
        elif cmd == "RADAR_ON":
            self.state.radar_on = True
            message = "Radar enabled"
        elif cmd == "RADAR_OFF":
            self.state.radar_on = False
            message = "Radar disabled"
        elif cmd == "SCAN":
            message = "Scan requested (simulation placeholder)"
        else:  # MAP
            message = "Map requested (simulation placeholder)"

        self._log(message)
        bus.emit(SystemEvents.COMMAND_EXECUTED, cmd)
        return {"ok": True, "message": message, **self.get_state()}

    def get_state(self) -> Dict[str, object]:
        return {
            "motion": self.state.motion,
            "radar_on": self.state.radar_on,
            "last_command": self.state.last_command,
        }
