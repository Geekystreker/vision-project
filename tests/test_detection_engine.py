import numpy as np

from config import RoverConfig
from modules.detection_engine import DetectionBackend, DetectionEngine
from modules.rover_types import BoundingBox, Detection


class FakeBackend(DetectionBackend):
    def __init__(self, detections):
        self.detections = detections
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def detect(self, frame: np.ndarray) -> list[Detection]:
        assert frame.shape == (8, 8, 3)
        return list(self.detections)


def make_detection(label: str, area_scale: int) -> Detection:
    return Detection(
        label=label,
        confidence=0.9,
        bbox=BoundingBox(x=0, y=0, w=area_scale, h=area_scale, confidence=0.9),
    )


def test_detection_engine_uses_backend():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    backend = FakeBackend([make_detection("person", 12)])
    engine = DetectionEngine(cfg, backend=backend)
    engine.load()
    detections = engine.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    assert backend.loaded is True
    assert len(detections) == 1
    assert detections[0].label == "person"


def test_select_primary_prefers_largest_target_label():
    cfg = RoverConfig("ws://cam", "ws://servo", "ws://motor")
    detections = [
        make_detection("person", 8),
        make_detection("bottle", 20),
        make_detection("person", 14),
    ]
    engine = DetectionEngine(cfg, backend=FakeBackend(detections))
    primary = engine.select_primary(detections)
    assert primary is not None
    assert primary.label == "person"
    assert primary.area == 196
