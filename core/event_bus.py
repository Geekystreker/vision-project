import threading
from typing import Callable, Dict, List, Any

class EventBus:
    """
    A simple thread-safe synchronous/asynchronous Event Bus for decoupling modules from the UI.
    Modules emit generic strings for topics, UI or other modules subscribe to callbacks.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._subscribers = {}
        return cls._instance

    def subscribe(self, event_type: str, callback: Callable[[Any], None]) -> None:
        """Subscribe a callback to an event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[Any], None]) -> None:
        """Unsubscribe a callback from an event type."""
        with self._lock:
            if event_type in self._subscribers and callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)

    def emit(self, event_type: str, payload: Any = None) -> None:
        """Emit an event, triggering all subscribed callbacks iteratively."""
        with self._lock:
            subs = list(self._subscribers.get(event_type, []))
        
        for callback in subs:
            # Note: For strict PyQt thread safety, the UI layer will often need to 
            # dispatch these via PySide signals or QMetaObject.invokeMethod,
            # or the UI subscribes by emitting a custom PyQtSignal.
            try:
                callback(payload)
            except Exception as e:
                print(f"[EventBus] Error in callback for {event_type}: {e}")

# Global singleton instance
bus = EventBus()

# Defined Event Types Constants (To avoid hardcoded strings across files)
class SystemEvents:
    VOICE_TEXT_CAPTURED = "VOICE_TEXT_CAPTURED"
    LOG_MESSAGE = "LOG_MESSAGE"
    STATE_CHANGE = "STATE_CHANGE"
    COMMAND_EXECUTED = "COMMAND_EXECUTED"
    TTS_STARTED = "TTS_STARTED"
    TTS_FINISHED = "TTS_FINISHED"
    MIC_TOGGLE = "MIC_TOGGLE"
    ROVER_MODE_CHANGE = "ROVER_MODE_CHANGE"
    ROVER_NO_DETECTION = "ROVER_NO_DETECTION"
    ROVER_DETECTION = "ROVER_DETECTION"
    FRAME_READY = "FRAME_READY"
    DETECTIONS_UPDATED = "DETECTIONS_UPDATED"
    TRACK_TARGET_CHANGED = "TRACK_TARGET_CHANGED"
    CONTROL_MODE_CHANGED = "CONTROL_MODE_CHANGED"
    AUDIO_WAKE_TRIGGERED = "AUDIO_WAKE_TRIGGERED"
    APP_LAUNCH_REQUESTED = "APP_LAUNCH_REQUESTED"
    CONNECTION_STATUS_CHANGED = "CONNECTION_STATUS_CHANGED"
