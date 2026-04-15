import json

from core.event_bus import SystemEvents, bus
from modules.ai_ollama import OllamaAIEngine
from modules.rover_types import ConnectionState


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"response": "Ready."}).encode("utf-8")


def test_ollama_generate_emits_connection_status(monkeypatch):
    statuses = []
    bus.subscribe(SystemEvents.CONNECTION_STATUS_CHANGED, statuses.append)
    monkeypatch.setattr("modules.ai_ollama.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    try:
        engine = OllamaAIEngine()

        response = engine._post_generate("hello", timeout=0.1)
    finally:
        bus.unsubscribe(SystemEvents.CONNECTION_STATUS_CHANGED, statuses.append)

    assert response == "Ready."
    assert statuses
    assert statuses[-1].channel == "ollama"
    assert statuses[-1].state == ConnectionState.CONNECTED


def test_ollama_generate_failure_emits_error_status(monkeypatch):
    statuses = []
    bus.subscribe(SystemEvents.CONNECTION_STATUS_CHANGED, statuses.append)

    def fail(*_args, **_kwargs):
        raise TimeoutError("offline")

    monkeypatch.setattr("modules.ai_ollama.request.urlopen", fail)
    try:
        engine = OllamaAIEngine()

        response = engine._post_generate("hello", timeout=0.1, suppress_log=True)
    finally:
        bus.unsubscribe(SystemEvents.CONNECTION_STATUS_CHANGED, statuses.append)

    assert response is None
    assert statuses
    assert statuses[-1].channel == "ollama"
    assert statuses[-1].state == ConnectionState.ERROR
