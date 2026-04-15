from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class KalmanPoint:
    x: float
    y: float
    predicted: bool = False


@dataclass(slots=True)
class Kalman2D:
    """Small constant-velocity Kalman filter for target center tracking."""

    process_noise: float = 35.0
    measurement_noise: float = 90.0
    history_limit: int = 18
    _x: np.ndarray = field(default_factory=lambda: np.zeros((4, 1), dtype=np.float64))
    _p: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64) * 500.0)
    _active: bool = False
    _history: list[tuple[int, int]] = field(default_factory=list)

    def reset(self) -> None:
        self._x = np.zeros((4, 1), dtype=np.float64)
        self._p = np.eye(4, dtype=np.float64) * 500.0
        self._active = False
        self._history.clear()

    def active(self) -> bool:
        return self._active

    def update(self, x: float, y: float, dt: float) -> KalmanPoint:
        if not self._active:
            self._x = np.array([[float(x)], [float(y)], [0.0], [0.0]], dtype=np.float64)
            self._p = np.eye(4, dtype=np.float64) * 120.0
            self._active = True
            return self._record(predicted=False)

        self.predict(dt, record=False)
        z = np.array([[float(x)], [float(y)]], dtype=np.float64)
        h = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
            ],
            dtype=np.float64,
        )
        r = np.eye(2, dtype=np.float64) * self.measurement_noise
        innovation = z - (h @ self._x)
        innovation_cov = h @ self._p @ h.T + r
        gain = self._p @ h.T @ np.linalg.inv(innovation_cov)
        self._x = self._x + (gain @ innovation)
        self._p = (np.eye(4, dtype=np.float64) - gain @ h) @ self._p
        return self._record(predicted=False)

    def predict(self, dt: float, *, record: bool = True) -> KalmanPoint | None:
        if not self._active:
            return None

        dt = max(1e-3, min(0.25, float(dt)))
        f = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        q_scale = self.process_noise
        q = np.array(
            [
                [dt**4 / 4.0, 0.0, dt**3 / 2.0, 0.0],
                [0.0, dt**4 / 4.0, 0.0, dt**3 / 2.0],
                [dt**3 / 2.0, 0.0, dt**2, 0.0],
                [0.0, dt**3 / 2.0, 0.0, dt**2],
            ],
            dtype=np.float64,
        ) * q_scale
        self._x = f @ self._x
        self._p = f @ self._p @ f.T + q
        if record:
            return self._record(predicted=True)
        return KalmanPoint(float(self._x[0, 0]), float(self._x[1, 0]), predicted=True)

    def point(self) -> tuple[int, int] | None:
        if not self._active:
            return None
        return int(round(float(self._x[0, 0]))), int(round(float(self._x[1, 0])))

    def history(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._history)

    def _record(self, *, predicted: bool) -> KalmanPoint:
        point = KalmanPoint(float(self._x[0, 0]), float(self._x[1, 0]), predicted=predicted)
        self._history.append((int(round(point.x)), int(round(point.y))))
        if len(self._history) > self.history_limit:
            del self._history[: len(self._history) - self.history_limit]
        return point
