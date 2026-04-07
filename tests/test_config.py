from pathlib import Path

from config import PROJECT_ROOT, RoverConfig, build_rover_config


DUMMY_CONFIG = RoverConfig(
    vision_stream_url="ws://localhost/Camera",
    servo_url="ws://localhost/ServoInput",
    motor_url="ws://localhost/Motors",
)


def test_required_fields_exist():
    cfg = DUMMY_CONFIG
    assert cfg.detector_backend == "yolo26"
    assert cfg.target_label == "person"
    assert cfg.detector_half_precision is True
    assert cfg.detector_max_detections == 6
    assert cfg.audio_sample_rate > 0
    assert cfg.key_repeat_hz > 0
    assert cfg.stt_backend
    assert cfg.tts_backend


def test_url_fields_are_strings():
    assert DUMMY_CONFIG.vision_stream_url.startswith(("ws://", "wss://", "http://", "https://"))
    assert DUMMY_CONFIG.servo_url.startswith("ws://")
    assert DUMMY_CONFIG.motor_url.startswith("ws://")


def test_legacy_yolo_properties_map_to_detector_fields():
    assert DUMMY_CONFIG.yolo_model == DUMMY_CONFIG.detector_model
    assert DUMMY_CONFIG.yolo_confidence == DUMMY_CONFIG.detector_confidence


def test_bbox_thresholds_are_ordered():
    assert DUMMY_CONFIG.bbox_min_fraction < DUMMY_CONFIG.bbox_max_fraction


def test_knowledge_paths_resolve_relative_to_project_root():
    resolved = DUMMY_CONFIG.resolved_knowledge_paths
    assert all(isinstance(path, Path) for path in resolved)
    assert all(path.is_absolute() for path in resolved)
    assert resolved[0].parent == PROJECT_ROOT


def test_build_rover_config_uses_mx330_profile_defaults():
    cfg = build_rover_config("mx330")

    assert cfg.performance_profile == "mx330"
    assert cfg.vision_loop_hz == 30
    assert cfg.ui_frame_hz == 30
    assert cfg.detection_hz == 8
    assert cfg.snapshot_poll_hz == 12
    assert cfg.detector_input_width == 416


def test_build_rover_config_uses_rtx5060_profile_defaults():
    cfg = build_rover_config("rtx5060")

    assert cfg.performance_profile == "rtx5060"
    assert cfg.vision_loop_hz == 60
    assert cfg.ui_frame_hz == 60
    assert cfg.detection_hz == 24
    assert cfg.snapshot_poll_hz == 30
    assert cfg.detector_input_width == 960


def test_build_rover_config_falls_back_to_mx330_for_unknown_profile():
    cfg = build_rover_config("mystery-gpu")

    assert cfg.performance_profile == "mx330"
    assert cfg.vision_loop_hz == 30
    assert cfg.ui_frame_hz == 30
