import math

from PyQt5.QtCore import QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QWidget


class ArcReactorWidget(QWidget):
    IDLE = "IDLE"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"

    _VALID_STATES = {IDLE, THINKING, SPEAKING}

    def __init__(self, parent=None):
        super().__init__(parent)

        # Requested state variable.
        self.state = self.IDLE

        # Requested animation variables.
        self.base_radius = 78.0
        self.radius = self.base_radius
        self.angle = 0.0
        self.pulse_speed = 0.8

        self._rotation_speed = 0.0
        self._glow_strength = 0.42
        self._radius_variation = 6.5

        self._target_pulse_speed = self.pulse_speed
        self._target_rotation_speed = self._rotation_speed
        self._target_glow_strength = self._glow_strength
        self._target_radius_variation = self._radius_variation

        self._pulse_phase = 0.0

        self._clock = QElapsedTimer()
        self._clock.start()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(12)  # Smooth animation loop
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(340, 340)
        self.set_idle()

    @property
    def mode(self) -> str:
        # Backward-compatible alias for existing UI usage.
        return self.state

    @property
    def energy_level(self) -> float:
        return max(0.0, min(1.0, self._glow_strength))

    def sizeHint(self) -> QSize:
        return QSize(480, 480)

    def set_mode(self, mode: str) -> None:
        mode = (mode or "").strip().upper()
        if mode == self.THINKING:
            self.set_thinking()
        elif mode == self.SPEAKING:
            self.set_speaking()
        else:
            self.set_idle()

    def set_idle(self) -> None:
        self.state = self.IDLE
        self._target_pulse_speed = 0.75
        self._target_rotation_speed = 0.0
        self._target_glow_strength = 0.42
        self._target_radius_variation = 5.8

    def set_thinking(self) -> None:
        self.state = self.THINKING
        self._target_pulse_speed = 1.25
        self._target_rotation_speed = 34.0
        self._target_glow_strength = 0.62
        self._target_radius_variation = 7.0

    def set_speaking(self) -> None:
        self.state = self.SPEAKING
        self._target_pulse_speed = 2.95
        self._target_rotation_speed = 0.0
        self._target_glow_strength = 0.98
        self._target_radius_variation = 12.2

    def _tick(self) -> None:
        elapsed_ms = self._clock.restart()
        if elapsed_ms <= 0:
            elapsed_ms = 12
        dt = min(max(elapsed_ms / 1000.0, 0.004), 0.050)

        # Smooth interpolation between states.
        smoothing = 1.0 - math.exp(-dt * 8.0)
        self.pulse_speed += (self._target_pulse_speed - self.pulse_speed) * smoothing
        self._rotation_speed += (self._target_rotation_speed - self._rotation_speed) * smoothing
        self._glow_strength += (self._target_glow_strength - self._glow_strength) * smoothing
        self._radius_variation += (self._target_radius_variation - self._radius_variation) * smoothing

        self._pulse_phase = (self._pulse_phase + (2.0 * math.pi * self.pulse_speed * dt)) % (2.0 * math.pi)
        self.radius = self.base_radius + (math.sin(self._pulse_phase) * self._radius_variation)

        # Rotation affects outer ring only.
        self.angle = (self.angle + (self._rotation_speed * dt)) % 360.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.HighQualityAntialiasing, True)

        rect = self.rect()
        side = min(rect.width(), rect.height())
        center = QPointF(float(rect.center().x()), float(rect.center().y()))
        scale = side / 420.0

        core_radius = self.radius * scale
        outer_radius = core_radius * 1.95
        glow_radius = outer_radius * 1.55

        self._draw_background_glow(painter, center, glow_radius)
        self._draw_static_depth_rings(painter, center, outer_radius * 1.15)
        self._draw_outer_rotating_ring(painter, center, outer_radius)
        self._draw_inner_core(painter, center, core_radius)

    def _draw_background_glow(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setCompositionMode(QPainter.CompositionMode_Screen)

        outer = QRadialGradient(center, radius)
        outer.setColorAt(0.00, QColor(0, 255, 255, int(130 * self._glow_strength)))
        outer.setColorAt(0.42, QColor(0, 180, 255, int(78 * self._glow_strength)))
        outer.setColorAt(0.80, QColor(0, 100, 170, int(20 * self._glow_strength)))
        outer.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.setBrush(outer)
        painter.drawEllipse(center, radius, radius)

        inner_radius = radius * 0.62
        inner = QRadialGradient(center, inner_radius)
        inner.setColorAt(0.00, QColor(150, 255, 255, int(110 * self._glow_strength)))
        inner.setColorAt(0.55, QColor(20, 185, 255, int(44 * self._glow_strength)))
        inner.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.setBrush(inner)
        painter.drawEllipse(center, inner_radius, inner_radius)
        painter.restore()

    @staticmethod
    def _draw_static_depth_rings(painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)

        ring_pen = QPen(QColor(45, 170, 220, 42))
        ring_pen.setWidthF(1.2)
        painter.setPen(ring_pen)
        for factor in (0.55, 0.75, 0.93, 1.08):
            r = radius * factor
            painter.drawEllipse(center, r, r)

        spoke_pen = QPen(QColor(85, 230, 255, 36))
        spoke_pen.setWidthF(1.0)
        painter.setPen(spoke_pen)
        for idx in range(12):
            ang = math.radians(idx * 30.0)
            inner = radius * 0.36
            outer = radius * 1.08
            x1 = center.x() + math.cos(ang) * inner
            y1 = center.y() + math.sin(ang) * inner
            x2 = center.x() + math.cos(ang) * outer
            y2 = center.y() + math.sin(ang) * outer
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.restore()

    def _draw_outer_rotating_ring(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()
        painter.setBrush(Qt.NoBrush)

        ring_color = QColor(0, 235, 255, int(110 + (120 * self._glow_strength)))
        pen = QPen(ring_color)
        pen.setWidthF(max(2.0, radius * 0.06))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        segments = ((0, 46), (66, 20), (109, 32), (168, 44), (239, 31), (300, 27))
        for offset, span in segments:
            start = int((offset + self.angle) * 16.0)
            painter.drawArc(rect, start, int(span * 16.0))

        tick_pen = QPen(QColor(120, 245, 255, int(80 + 90 * self._glow_strength)))
        tick_pen.setWidthF(1.3)
        painter.setPen(tick_pen)
        for i in range(36):
            a = math.radians((i * 10.0) + self.angle * 0.15)
            outer = radius * 1.16
            inner = radius * (1.05 if i % 3 else 1.00)
            x1 = center.x() + math.cos(a) * outer
            y1 = center.y() + math.sin(a) * outer
            x2 = center.x() + math.cos(a) * inner
            y2 = center.y() + math.sin(a) * inner
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.restore()

    def _draw_inner_core(self, painter: QPainter, center: QPointF, radius: float) -> None:
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Screen)

        core = QRadialGradient(center, radius)
        core.setColorAt(0.00, QColor(230, 255, 255, int(235 * self._glow_strength + 20)))
        core.setColorAt(0.30, QColor(85, 235, 255, int(215 * self._glow_strength + 20)))
        core.setColorAt(0.70, QColor(0, 140, 255, int(180 * self._glow_strength + 16)))
        core.setColorAt(1.00, QColor(0, 12, 30, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(center, radius, radius)

        ring_pen = QPen(QColor(160, 252, 255, int(145 + 90 * self._glow_strength)))
        ring_pen.setWidthF(max(2.0, radius * 0.11))
        painter.setPen(ring_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius * 0.58, radius * 0.58)

        inner_pulse = radius * (0.20 + 0.05 * math.sin(self._pulse_phase * 1.2))
        pulse_glow = QRadialGradient(center, inner_pulse * 2.5)
        pulse_glow.setColorAt(0.00, QColor(220, 255, 255, int(140 * self._glow_strength)))
        pulse_glow.setColorAt(0.45, QColor(65, 220, 255, int(75 * self._glow_strength)))
        pulse_glow.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(pulse_glow)
        painter.drawEllipse(center, inner_pulse * 2.5, inner_pulse * 2.5)
        painter.restore()
