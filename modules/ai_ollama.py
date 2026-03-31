import json
import random
import threading
from urllib import error, request
from typing import Optional, Callable

from config import Config
from core.event_bus import bus, SystemEvents

SYSTEM_CONTEXT = """
You are Jarvis, a smart assistant for a student-built rover project using Arduino and AI.

The rover can:
- Be controlled using voice commands (forward, left, right, stop)
- Explore autonomously and navigate around obstacles
- Scan the surrounding environment

Your speaking style:
- Natural and conversational, like a helpful human assistant
- Clear and complete: give 2-3 sentences, not just 1 word
- Explain like you are presenting a real project demo
- Do NOT sound futuristic or sci-fi
- Do NOT give generic AI answers
- No markdown formatting (no asterisks, bullets, or headers)

Examples:

User: explain this project
Jarvis: This is a smart rover system that you can control using voice commands. It can also run in an autonomous mode where it explores the area on its own and avoids obstacles. It combines simple robotics with AI to make interaction more natural.

User: what are you doing
Jarvis: I'm currently idle and waiting for your command.

User: scan the area
Jarvis: Sure, starting a scan now. I'll report back if I detect anything.

User: how do you work
Jarvis: You can give me voice commands or type them in. I understand things like move forward, turn left, or stop. I also have an autonomous mode where I explore on my own.

IMPORTANT:
- Do NOT use phrases like "advanced AI system", "mission objectives", or "neural interface"
- Keep it realistic and demo-friendly
- Always give at least 2 complete sentences unless a very short reply is obviously correct
"""

_FILLERS = ["Alright,", "Sure,", "Got it,", "Okay,"]
_MIN_WORDS = 8
_MAX_WORDS = 50

def clean_response(text: str) -> str:
    """Make AI text sound more natural when spoken aloud."""
    replacements = [
        ("This system", "This rover"),
        ("The system", "It"),
        ("V.I.S.I.O.N.", "the system"),
        ("*", ""),
        ("#", ""),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    # Pad responses that are too short to sound natural
    words = text.split()
    if len(words) < _MIN_WORDS:
        text = text.rstrip(".") + ". It works using simple sensors and voice control logic."
    return text.strip()


def humanize(text: str) -> str:
    """Optionally prepend a natural filler word and cap length."""
    text = clean_response(text)
    words = text.split()
    if len(words) > _MAX_WORDS:
        text = " ".join(words[:_MAX_WORDS]).rstrip(",") + "."
    if random.random() < 0.3:
        text = random.choice(_FILLERS) + " " + text
    return text


class OllamaAIEngine:
    def __init__(self):
        self._endpoint = Config.OLLAMA_ENDPOINT
        self._model = Config.OLLAMA_MODEL
        self._timeout = Config.API_TIMEOUT
        self._is_ready = True

        bus.emit(SystemEvents.LOG_MESSAGE, f"[Ollama] Initialized using local model: {self._model}")

    def _post_generate(self, prompt: str, timeout: Optional[int] = None) -> Optional[str]:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout or self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            return str(parsed.get("response", "")).strip()
        except Exception as exc:
            bus.emit(SystemEvents.LOG_MESSAGE, f"[Ollama] Request failed: {exc}")
            return None

    def run_chat_query_async(self, text: str, callback=None):
        """Runs the query async to prevent UI blocking."""
        def task():
            prompt = (
                f"{SYSTEM_CONTEXT}"
                f"\nUser: {text}"
                f"\nJarvis:"
            )
            response = self._post_generate(prompt, timeout=30)
            if response:
                if callback: callback(humanize(response))
            else:
                if callback: callback("Sorry, I'm having trouble connecting right now.")

        threading.Thread(target=task, daemon=True).start()

    def run_command_extraction_async(self, text: str, callback: Callable):
        """If IntentRouter failed, fallback to Ollama to extract command."""
        def task():
            prompt = (
                "You are a command parser for a rover. "
                "Extract the ONLY logical action from the text. "
                "Respond with EXACTLY ONE of: F, B, L, R, S. "
                "If none apply, output UNKNOWN. "
                f"Text: {text}\n"
                "Command:"
            )
            response = self._post_generate(prompt, timeout=15)
            ans = (response or "").strip().upper()
            
            # Clean response to ensure it's just the letter
            if ans and len(ans) > 0:
                ans = ans.split()[0]
                ans = ''.join(c for c in ans if c in "FBLRS")
                
            if ans in ["F", "B", "L", "R", "S"]:
                callback(ans)
            else:
                callback(None)

        threading.Thread(target=task, daemon=True).start()
