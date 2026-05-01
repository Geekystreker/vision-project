from modules.kalman_filter import Kalman2D


def test_kalman_filter_predicts_after_measurements():
    kalman = Kalman2D()

    first = kalman.update(100, 80, 0.033)
    second = kalman.update(110, 80, 0.033)
    predicted = kalman.predict(0.033)

    assert first.predicted is False
    assert second.predicted is False
    assert predicted is not None
    assert predicted.predicted is True
    assert predicted.x > 100
    assert kalman.history()


def test_kalman_filter_reset_clears_state():
    kalman = Kalman2D()
    kalman.update(100, 80, 0.033)

    kalman.reset()

    assert kalman.active() is False
    assert kalman.point() is None
    assert kalman.history() == ()


def test_kalman_project_compensates_without_mutating_history():
    kalman = Kalman2D()
    kalman.update(100, 80, 0.1)
    kalman.update(160, 80, 0.1)
    history_before = kalman.history()
    current = kalman.point()

    projected = kalman.project(0.12)

    assert projected is not None
    assert projected.predicted is True
    assert current is not None
    assert projected.x > current[0]
    assert kalman.history() == history_before


def test_kalman_bootstraps_velocity_from_real_measurements():
    kalman = Kalman2D()
    kalman.update(100, 80, 0.05)
    kalman.update(140, 80, 0.05)

    projected = kalman.project(0.10)

    assert projected is not None
    assert projected.x > 170
    assert 75 <= projected.y <= 85


def test_kalman_downweights_large_outlier_measurements():
    kalman = Kalman2D()
    kalman.update(100, 100, 0.05)
    kalman.update(104, 102, 0.05)
    point_before = kalman.point()

    corrected = kalman.update(600, 600, 0.05)

    assert point_before is not None
    assert corrected.x < 320
    assert corrected.y < 320
