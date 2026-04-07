from __future__ import annotations

import json
import random
import threading
from typing import Callable, Optional
from urllib import request

from config import Config
from core.event_bus import SystemEvents, bus
from modules.knowledge_base import KnowledgeBase

SYSTEM_CONTEXT = """
You are V.I.S.I.O.N., a grounded assistant for a student-built ESP32-CAM rover project.

How to answer:
- Speak naturally and clearly, like a confident real project operator.
- Keep answers practical and demo-friendly.
- When project context is provided, stay faithful to it and do not invent features.
- If the user asks about the project scope, architecture, controls, or capabilities, answer using the supplied project context first.
- No markdown in spoken responses.
"""

_FILLERS = ["Alright,", "Sure,", "Okay,"]
_MAX_WORDS = 65


def clean_response(text: str) -> str:
    text = (text or "").replace("*", "").replace("#", "")
    words = text.split()
    if len(words) > _MAX_WORDS:
        text = " ".join(words[:_MAX_WORDS]).rstrip(",") + "."
    return text.strip()


def humanize(text: str) -> str:
    text = clean_response(text)
    if not text:
        return ""
    if random.random() < 0.25:
        return random.choice(_FILLERS) + " " + text
    return text


class OllamaAIEngine:
    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None):
        self._endpoint = Config.OLLAMA_ENDPOINT
        self._model = Config.OLLAMA_MODEL
        self._timeout = Config.API_TIMEOUT
        self._knowledge_base = knowledge_base
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

    def run_chat_query_async(self, text: str, callback: Callable[[str], None] | None = None) -> None:
        def task() -> None:
            context = ""
            if self._knowledge_base is not None:
                context = self._knowledge_base.format_context(text, limit=4)

            prompt = (
                f"{SYSTEM_CONTEXT}\n"
                "Project context:\n"
                f"{context or 'No additional project context was found.'}\n\n"
                f"User: {text}\n"
                "Assistant:"
            )
            response = self._post_generate(prompt, timeout=45)
            if callback:
                callback(humanize(response or "Sorry, I'm having trouble answering right now."))

        threading.Thread(target=task, daemon=True).start()

    def run_command_extraction_async(self, text: str, callback: Callable[[str | None], None]) -> None:
        def task() -> None:
            prompt = (
                "You are a command parser for a rover. "
                "Extract the single best rover motion command from the text. "
                "Reply with exactly one token from: F, B, L, R, S, FOLLOW, INSPECT, MANUAL, UNKNOWN.\n"
                f"Text: {text}\n"
                "Command:"
            )
            response = (self._post_generate(prompt, timeout=15) or "").strip().upper()
            token = response.split()[0] if response else "UNKNOWN"
            token = token.replace(".", "")
            callback(token if token in {"F", "B", "L", "R", "S", "FOLLOW", "INSPECT", "MANUAL"} else None)

        threading.Thread(target=task, daemon=True).start()
