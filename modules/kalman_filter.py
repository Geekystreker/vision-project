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
    innovation_gate: float = 16.0
    velocity_blend: float = 0.35
    _x: np.ndarray = field(default_factory=lambda: np.zeros((4, 1), dtype=np.float64))
    _p: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64) * 500.0)
    _active: bool = False
    _history: list[tuple[int, int]] = field(default_factory=list)
    _last_measurement: tuple[float, float] | None = None
    _measurement_count: int = 0

    def reset(self) -> None:
        self._x = np.zeros((4, 1), dtype=np.float64)
        self._p = np.eye(4, dtype=np.float64) * 500.0
        self._active = False
        self._history.clear()
        self._last_measurement = None
        self._measurement_count = 0

    def active(self) -> bool:
        return self._active

    def update(self, x: float, y: float, dt: float) -> KalmanPoint:
        dt = self._sanitize_dt(dt)
        measurement = (float(x), float(y))
        if not self._active:
            self._x = np.array([[measurement[0]], [measurement[1]], [0.0], [0.0]], dtype=np.float64)
            self._p = np.eye(4, dtype=np.float64) * 120.0
            self._active = True
            self._last_measurement = measurement
            self._measurement_count = 1
            return self._record(predicted=False)

        self.predict(dt, record=False)
        z = np.array([[measurement[0]], [measurement[1]]], dtype=np.float64)
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
        nis = float((innovation.T @ np.linalg.inv(innovation_cov) @ innovation).item())
        if nis > self.innovation_gate:
            inflation = max(1.0, min(12.0, nis / max(1e-6, self.innovation_gate)))
            r = r * inflation
            innovation_cov = h @ self._p @ h.T + r
        gain = np.linalg.solve(innovation_cov, h @ self._p).T
        self._x = self._x + (gain @ innovation)
        identity = np.eye(4, dtype=np.float64)
        innovation_factor = identity - (gain @ h)
        self._p = (innovation_factor @ self._p @ innovation_factor.T) + (gain @ r @ gain.T)
        self._p = self._symmetrize_covariance(self._p)
        self._blend_velocity_from_measurement(measurement, dt)
        self._last_measurement = measurement
        self._measurement_count += 1
        return self._record(predicted=False)

    def predict(self, dt: float, *, record: bool = True) -> KalmanPoint | None:
        if not self._active:
            return None

        dt = self._sanitize_dt(dt)
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
        self._p = self._symmetrize_covariance((f @ self._p @ f.T) + q)
        if record:
            return self._record(predicted=True)
        return KalmanPoint(float(self._x[0, 0]), float(self._x[1, 0]), predicted=True)

    def point(self) -> tuple[int, int] | None:
        if not self._active:
            return None
        return int(round(float(self._x[0, 0]))), int(round(float(self._x[1, 0])))

    def project(self, dt: float) -> KalmanPoint | None:
        if not self._active:
            return None
        dt = max(0.0, min(0.35, float(dt)))
        return KalmanPoint(
            float(self._x[0, 0] + (self._x[2, 0] * dt)),
            float(self._x[1, 0] + (self._x[3, 0] * dt)),
            predicted=True,
        )

    def history(self) -> tuple[tuple[int, int], ...]:
        return tuple(self._history)

    @staticmethod
    def _sanitize_dt(dt: float) -> float:
        return max(1e-3, min(0.25, float(dt)))

    @staticmethod
    def _symmetrize_covariance(covariance: np.ndarray) -> np.ndarray:
        return (covariance + covariance.T) * 0.5

    def _blend_velocity_from_measurement(self, measurement: tuple[float, float], dt: float) -> None:
        previous = self._last_measurement
        if previous is None:
            return
        measured_vx = (measurement[0] - previous[0]) / dt
        measured_vy = (measurement[1] - previous[1]) / dt
        blend = float(self.velocity_blend)
        if self._measurement_count <= 1:
            blend = max(blend, 0.65)
        blend = max(0.0, min(1.0, blend))
        self._x[2, 0] = ((1.0 - blend) * self._x[2, 0]) + (blend * measured_vx)
        self._x[3, 0] = ((1.0 - blend) * self._x[3, 0]) + (blend * measured_vy)

    def _record(self, *, predicted: bool) -> KalmanPoint:
        point = KalmanPoint(float(self._x[0, 0]), float(self._x[1, 0]), predicted=predicted)
        self._history.append((int(round(point.x)), int(round(point.y))))
        if len(self._history) > self.history_limit:
            del self._history[: len(self._history) - self.history_limit]
        return point
