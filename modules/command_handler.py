from dataclasses import dataclass
from typing import Optional
from rapidfuzz import fuzz
from core.event_bus import bus, SystemEvents

@dataclass
class CommandResolution:
    command: Optional[str]
    route: str

class CommandHandler:
    VALID_COMMANDS = {"F", "B", "L", "R", "S", "RADAR_ON", "RADAR_OFF", "SCAN", "MAP"}

    DISPLAY_MAP = {
        "F": "MOVE_FORWARD",
        "B": "MOVE_BACKWARD",
        "L": "TURN_LEFT",
        "R": "TURN_RIGHT",
        "S": "STOP",
        "RADAR_ON": "RADAR_ON",
        "RADAR_OFF": "RADAR_OFF",
        "SCAN": "SCAN",
        "MAP": "MAP",
    }

    SPEECH_MAP = {
        "F": "Moving forward",
        "B": "Moving backward",
        "L": "Turning left",
        "R": "Turning right",
        "S": "Stopping",
        "RADAR_ON": "Radar enabled",
        "RADAR_OFF": "Radar disabled",
        "SCAN": "Initiating scan",
        "MAP": "Starting map mode",
    }
    
    FUZZY_TARGETS = {
        "move forward": "F",
        "go ahead": "F",
        "move backward": "B",
        "reverse": "B",
        "turn left": "L",
        "left": "L",
        "turn right": "R",
        "right": "R",
        "stop": "S",
        "halt": "S",
        "radar on": "RADAR_ON",
        "enable radar": "RADAR_ON",
        "radar off": "RADAR_OFF",
        "disable radar": "RADAR_OFF",
        "scan": "SCAN",
        "map": "MAP"
    }

    @staticmethod
    def _log(message: str) -> None:
        bus.emit(SystemEvents.LOG_MESSAGE, f"[COMMAND] {message}")

    @classmethod
    def parse_local_command(cls, user_input: str) -> Optional[str]:
        """Parses the command logically through rapidfuzz before keyword matching."""
        text = (user_input or "").lower().strip()
        if not text:
            return None

        # 1. FUZZY MATCH
        best_match = None
        best_ratio = 0.0

        for phrase, cmd in cls.FUZZY_TARGETS.items():
            ratio = fuzz.partial_ratio(text, phrase)
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = cmd

        cls._log(f"Input: '{text}' | Match: {best_match} | Confidence: {best_ratio:.2f}%")

        if best_ratio > 70:
            return best_match
            
        # 2. KEYWORD MATCH (safeguard)
        if "forward" in text or "ahead" in text:
            return "F"
        if "back" in text or "reverse" in text:
            return "B"
        if "left" in text:
            return "L"
        if "right" in text:
            return "R"
        if "stop" in text or "halt" in text:
            return "S"
        if "radar" in text:
            if "off" in text or "disable" in text: return "RADAR_OFF"
            if "on" in text or "enable" in text or "start" in text: return "RADAR_ON"
        if "scan" in text: return "SCAN"
        if "map" in text: return "MAP"

        # 3. ASK CLARIFICATION
        if 50 < best_ratio <= 70 and best_match:
            return f"CLARIFY_{best_match}"

        # 4. FALLBACK LOGIC
        return None

    @classmethod
    def display_for(cls, command: str) -> str:
        if command.startswith("CLARIFY_"):
            return "CLARIFICATION_REQUIRED"
        return cls.DISPLAY_MAP.get(command, command)

    @classmethod
    def speech_for(cls, command: str) -> str:
        if command.startswith("CLARIFY_"):
            base_cmd = command.replace("CLARIFY_", "")
            phrase = cls.DISPLAY_MAP.get(base_cmd, base_cmd).lower().replace("_", " ")
            return f"Did you mean {phrase}?"
        return cls.SPEECH_MAP.get(command, "Command executed")
