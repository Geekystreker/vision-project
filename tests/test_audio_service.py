from modules.audio_service import ClapDetector


def test_clap_detector_requires_two_peaks_within_window():
    detector = ClapDetector(threshold=0.5, window_seconds=0.8, cooldown_seconds=1.0)

    assert detector.register_peak(0.6, 1.0) is False
    assert detector.register_peak(0.4, 1.2) is False
    assert detector.register_peak(0.7, 1.4) is True


def test_clap_detector_respects_cooldown():
    detector = ClapDetector(threshold=0.5, window_seconds=0.8, cooldown_seconds=1.0)
    detector.register_peak(0.7, 1.0)
    assert detector.register_peak(0.7, 1.4) is True
    assert detector.register_peak(0.8, 1.6) is False
