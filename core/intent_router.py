import re

class IntentRouter:
    COMMAND = "COMMAND"
    SYSTEM = "SYSTEM"  
    CHAT = "CHAT"

    _COMMAND_KEYWORDS = {"forward", "back", "backward", "left", "right", "stop", "radar", "scan", "move", "turn", "rotate"}
    _SYSTEM_KEYWORDS = {"open", "close", "shutdown", "launch", "restart", "system", "app"}
    _QUESTION_KEYWORDS = {"what", "how", "why", "explain", "who", "where", "when", "can", "could", "would"}
    _MIXED_HINTS = {"tell", "describe", "explain", "say"}

    @classmethod
    def detect_intent(cls, user_input: str) -> str:
        """
        Ultra-fast intent resolution to prevent API calls on trivial tasks.
        Returns the mapped intent type enum string.
        """
        text = (user_input or "").strip().lower()
        if not text:
            return cls.CHAT

        words = set(re.findall(r"[a-z0-9]+", text))
        has_command = any(word in words for word in cls._COMMAND_KEYWORDS)
        has_system = any(word in words for word in cls._SYSTEM_KEYWORDS)
        has_question = ("?" in text) or any(word in words for word in cls._QUESTION_KEYWORDS)
        
        # Explicit questions / long complex prompts route to chat
        if has_question or len(words) > 10:
            return cls.CHAT

        if has_system:
            return cls.SYSTEM

        if has_command:
            return cls.COMMAND

        return cls.CHAT
