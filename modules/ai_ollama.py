from __future__ import annotations

import json
import random
import threading
import time
from collections import Counter
from typing import Callable, Optional
from urllib import request
from urllib.parse import urlparse, urlunparse

from config import Config
from core.event_bus import SystemEvents, bus
from modules.knowledge_base import KnowledgeBase
from modules.rover_types import ConnectionState, ConnectionStatus

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
    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None, *, healthcheck: bool = True):
        self._endpoint = Config.OLLAMA_ENDPOINT
        self._model = Config.OLLAMA_MODEL
        self._timeout = Config.API_TIMEOUT
        self._knowledge_base = knowledge_base
        self._scene_timeout = 0.6
        self._scene_backoff_until = 0.0
        self._scene_lock = threading.Lock()
        bus.emit(SystemEvents.LOG_MESSAGE, f"[Ollama] Initialized using local model: {self._model}")
        if healthcheck:
            self.refresh_status_async()

    def refresh_status_async(self) -> None:
        threading.Thread(
            target=self._refresh_status,
            daemon=True,
            name="OllamaHealth_Thread",
        ).start()

    def _refresh_status(self) -> None:
        self._emit_status(ConnectionState.CONNECTING, "checking local Ollama")
        try:
            req = request.Request(self._tags_endpoint(), method="GET")
            with request.urlopen(req, timeout=2.0) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            models = parsed.get("models")
            if isinstance(models, list):
                names = {
                    str(item.get("name", "")).strip()
                    for item in models
                    if isinstance(item, dict) and str(item.get("name", "")).strip()
                }
                if names and self._model not in names:
                    self._emit_status(ConnectionState.ERROR, f"model missing: {self._model}")
                    return
            self._emit_status(ConnectionState.CONNECTED, self._model)
        except Exception as exc:
            self._emit_status(ConnectionState.ERROR, str(exc))

    def _tags_endpoint(self) -> str:
        parsed = urlparse(self._endpoint)
        return urlunparse((parsed.scheme, parsed.netloc, "/api/tags", "", "", ""))

    @staticmethod
    def _emit_status(state: ConnectionState, detail: str = "") -> None:
        bus.emit(
            SystemEvents.CONNECTION_STATUS_CHANGED,
            ConnectionStatus(channel="ollama", state=state, detail=detail),
        )

    def _post_generate(
        self,
        prompt: str,
        timeout: Optional[float] = None,
        *,
        suppress_log: bool = False,
    ) -> Optional[str]:
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
            self._emit_status(ConnectionState.CONNECTED, self._model)
            return str(parsed.get("response", "")).strip()
        except Exception as exc:
            self._emit_status(ConnectionState.ERROR, str(exc))
            if not suppress_log:
                bus.emit(SystemEvents.LOG_MESSAGE, f"[Ollama] Request failed: {exc}")
            return None

    def run_chat_query_async(
        self,
        text: str,
        callback: Callable[[str], None] | None = None,
        *,
        runtime_context: str = "",
    ) -> None:
        def task() -> None:
            context = ""
            if self._knowledge_base is not None:
                context = self._knowledge_base.format_context(text, limit=4)

            prompt = (
                f"{SYSTEM_CONTEXT}\n"
                "Project context:\n"
                f"{context or 'No additional project context was found.'}\n\n"
                "Live rover runtime context:\n"
                f"{runtime_context or 'No live runtime context is available.'}\n\n"
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
                "Reply with exactly one token from: F, B, L, R, S, FOLLOW, AUTO, INSPECT, MANUAL, UNKNOWN.\n"
                f"Text: {text}\n"
                "Command:"
            )
            response = (self._post_generate(prompt, timeout=15) or "").strip().upper()
            token = response.split()[0] if response else "UNKNOWN"
            token = token.replace(".", "")
            callback(token if token in {"F", "B", "L", "R", "S", "FOLLOW", "AUTO", "INSPECT", "MANUAL"} else None)

        threading.Thread(target=task, daemon=True).start()

    def run_scene_update_async(
        self,
        detections: list[str],
        *,
        locked: bool,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        def task() -> None:
            with self._scene_lock:
                if time.monotonic() < self._scene_backoff_until:
                    if callback:
                        callback("")
                    return

            counts = Counter(label.strip().lower() for label in detections if label and label.strip())
            if not counts:
                if callback:
                    callback("")
                return

            parts = [f"{label}:{count}" for label, count in sorted(counts.items())]
            prompt = (
                "You are the live voice layer for an ESP32 rover named Jarvis.\n"
                "A YOLO tracker has reported a fresh scene change.\n"
                "Turn the structured observation into one short natural spoken line.\n"
                "Rules:\n"
                "- Keep it under 10 words.\n"
                "- No filler words.\n"
                "- No markdown.\n"
                "- Sound calm and smart.\n"
                "- If a person is visible and locked, say something like 'Target locked on one person ahead.'\n"
                "- If a person is visible but not locked, say something like 'I have a person in view.'\n"
                "- If there is no person, briefly mention the main object.\n"
                "- If the update is not worth speaking, reply exactly with SILENT.\n\n"
                f"Detections: {', '.join(parts)}\n"
                f"Target locked: {'yes' if locked else 'no'}\n"
                "Speech:"
            )
            response = clean_response(
                self._post_generate(
                    prompt,
                    timeout=self._scene_timeout,
                    suppress_log=True,
                )
                or ""
            )
            with self._scene_lock:
                self._scene_backoff_until = 0.0 if response else (time.monotonic() + 15.0)
            if callback:
                callback("" if response.upper() == "SILENT" else response)

        threading.Thread(target=task, daemon=True).start()
