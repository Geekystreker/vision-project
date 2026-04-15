from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoverMode(Enum):
    MANUAL = "MANUAL"
    AUTONOMOUS = "AUTONOMOUS"


class ControlMode(Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    AUTONOMOUS = "AUTONOMOUS"
    FOLLOW_PERSON = "FOLLOW_PERSON"
    VOICE_NAV = "VOICE_NAV"
    INSPECT_SCENE = "INSPECT_SCENE"


class ConnectionState(Enum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


@dataclass(slots=True)
class BoundingBox:
    x: int
    y: int
    w: int
    h: int
    confidence: float = 0.0

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2


@dataclass(slots=True)
class Detection:
    label: str
    confidence: float
    bbox: BoundingBox
    source: str = "detector"
    class_id: int | None = None
    track_id: int | None = None

    @property
    def area(self) -> int:
        return self.bbox.area


@dataclass(slots=True)
class TrackedTarget:
    target_id: int
    detection: Detection
    source_track_id: int | None = None
    stable_frames: int = 1
    lost_frames: int = 0
    last_seen: float = field(default_factory=time.monotonic)

    @property
    def bbox(self) -> BoundingBox:
        return self.detection.bbox

    @property
    def label(self) -> str:
        return self.detection.label


@dataclass(slots=True)
class ConnectionStatus:
    channel: str
    state: ConnectionState
    detail: str = ""


@dataclass(slots=True)
class VisionSnapshot:
    frame: Any | None
    detections: list[Detection] = field(default_factory=list)
    target: TrackedTarget | None = None
    mode: ControlMode = ControlMode.IDLE
    fps: float = 0.0
    source_fps: float = 0.0
    inference_ms: float = 0.0
    last_command: str = "S"
    servo_pan: int = 90
    servo_tilt: int = 90
    target_coords: tuple[int, int] | None = None
    predicted_target_coords: tuple[int, int] | None = None
    predicted_target_path: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    network_latency_ms: float = 0.0
    target_locked: bool = False
    locked_target_id: int | None = None
    links: dict[str, ConnectionState] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
