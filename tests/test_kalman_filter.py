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
