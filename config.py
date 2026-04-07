from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

# Try to load python-dotenv if available.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_KNOWLEDGE_PATHS = (
    "README.md",
    ".kiro/specs",
    "config.py",
    "modules",
)
DEFAULT_ESP32_IP = os.getenv("ROVER_ESP32_IP", "192.168.137.110")
DEFAULT_CAMERA_STREAM_URL = os.getenv("ROVER_CAMERA_STREAM_URL", f"http://{DEFAULT_ESP32_IP}:81/stream")
DEFAULT_SERVO_WS_URL = os.getenv("ROVER_SERVO_WS_URL", f"ws://{DEFAULT_ESP32_IP}/ServoInput")
DEFAULT_MOTOR_WS_URL = os.getenv("ROVER_MOTOR_WS_URL", "")
DEFAULT_PERFORMANCE_PROFILE = (os.getenv("VISION_PERF_PROFILE", "rtx5060") or "rtx5060").strip().lower()


class Config:
    API_TIMEOUT = 20

    OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "qwen3:1.7b"
    OLLAMA_VLM_MODEL = "qwen2.5vl:3b"

    SINGLE_INSTANCE_SERVER = "VISIONControlPanel"
    LAUNCHER_APP_NAME = "V.I.S.I.O.N Launcher"
    MAIN_WINDOW_TITLE = "V.I.S.I.O.N Control Panel"


@dataclass(slots=True)
class RoverConfig:
    # Network
    vision_stream_url: str
    servo_url: str
    motor_url: str

    # UI / timing
    performance_profile: str = "rtx5060"
    vision_loop_hz: int = 30
    ui_frame_hz: int = 30
    detection_hz: int = 8
    snapshot_poll_hz: int = 12
    key_repeat_hz: int = 15
    frame_stale_seconds: float = 2.5
    camera_disconnect_timeout: float = 1.0
    camera_initial_frame_timeout: float = 8.0
    camera_reconnect_timeout: float = 12.0

    # Manual pan / tilt
    servo_step: int = 5

    # Follow-person tracking
    dead_zone_px: int = 30
    pan_tilt_gain: float = 0.05
    bbox_min_fraction: float = 0.10
    bbox_max_fraction: float = 0.30
    no_detection_timeout: float = 2.0
    max_target_lost_frames: int = 10
    track_iou_threshold: float = 0.20

    # Transport
    ws_recv_timeout: float = 2.0
    reconnect_interval: float = 3.0

    # Detector
    detector_backend: str = "yolo26"
    detector_model: str = "yolo26n.pt"
    detector_fallback_model: str = "yolov8n.pt"
    detector_confidence: float = 0.50
    detector_device: str = "auto"
    detector_half_precision: bool = True
    detector_max_detections: int = 6
    detector_input_width: int = 416
    target_label: str = "person"

    # Audio
    audio_sample_rate: int = 16_000
    audio_chunk_size: int = 1_024
    speech_activation_threshold: float = 0.02
    speech_silence_seconds: float = 0.90
    clap_amplitude_threshold: float = 0.18
    clap_window_seconds: float = 0.85
    clap_cooldown_seconds: float = 2.0

    # STT / TTS
    stt_backend: str = "faster_whisper"
    stt_model_size: str = "base.en"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_language: str = "en"
    tts_backend: str = "offline"
    tts_voice_hint: str = "firm"

    # Local knowledge + scene reasoning
    knowledge_paths: tuple[str, ...] = field(default_factory=lambda: DEFAULT_KNOWLEDGE_PATHS)
    vlm_endpoint: str | None = None
    vlm_model: str | None = None

    # App / launcher
    single_instance_server: str = Config.SINGLE_INSTANCE_SERVER
    main_window_title: str = Config.MAIN_WINDOW_TITLE
    launcher_name: str = Config.LAUNCHER_APP_NAME

    @property
    def yolo_model(self) -> str:
        return self.detector_model

    @property
    def yolo_confidence(self) -> float:
        return self.detector_confidence

    @property
    def resolved_knowledge_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for value in self.knowledge_paths:
            path = Path(value)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            paths.append(path)
        return tuple(paths)


PERFORMANCE_PROFILES: dict[str, dict[str, int | float | str]] = {
    "mx330": {
        "performance_profile": "mx330",
        "vision_loop_hz": 30,
        "ui_frame_hz": 30,
        "detection_hz": 8,
        "snapshot_poll_hz": 12,
        "detector_input_width": 416,
    },
    "rtx5060": {
        "performance_profile": "rtx5060",
        "vision_loop_hz": 60,
        "ui_frame_hz": 60,
        "detection_hz": 24,
        "snapshot_poll_hz": 30,
        "detector_input_width": 960,
    },
}


def build_rover_config(profile: str | None = None) -> RoverConfig:
    selected = (profile or DEFAULT_PERFORMANCE_PROFILE or "mx330").strip().lower()
    if selected not in PERFORMANCE_PROFILES:
        selected = "mx330"
    overrides = PERFORMANCE_PROFILES[selected]
    return RoverConfig(
        vision_stream_url=DEFAULT_CAMERA_STREAM_URL,
        servo_url=DEFAULT_SERVO_WS_URL,
        motor_url=DEFAULT_MOTOR_WS_URL,
        ws_recv_timeout=5.0,
        reconnect_interval=2.0,
        **overrides,
    )


rover_config = build_rover_config()
