from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PIDController:
    kp: float
    ki: float
    kd: float
    integral_limit: float
    output_limit: float
    integral: float = 0.0
    previous_error: float = 0.0
    initialized: bool = False

    def reset(self) -> None:
        self.integral = 0.0
        self.previous_error = 0.0
        self.initialized = False

    def update(self, error: float, dt: float) -> float:
        dt = max(1e-3, dt)
        self.integral += error * dt
        self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))

        derivative = 0.0
        if self.initialized:
            derivative = (error - self.previous_error) / dt
        else:
            self.initialized = True

        self.previous_error = error
        output = (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)
        return max(-self.output_limit, min(self.output_limit, output))
