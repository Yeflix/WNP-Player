"""Fondo del aspecto "Cosmos" (réplica ligera del modo Cosmos del tema Switch
de Spicetify): nebulosas violeta/celeste, banda tipo Vía Láctea, viñeta y
estrellas, más estrellas fugaces ocasionales.

Rendimiento:
  - El cielo estático se dibuja UNA vez en un QPixmap y se cachea; en cada
    repintado solo se copia ese pixmap (se rehace únicamente si cambia el
    tamaño de la ventana).
  - Las estrellas fugaces solo existen mientras suena música, la ventana está
    visible, el equipo está conectado a la corriente y el sistema no pide
    movimiento reducido (igual que en el tema de Spotify, que en batería deja
    todo estático). Entre estrellas no corre ninguna animación, y mientras
    cruza una solo se repinta el rectángulo que ocupa.
"""
from __future__ import annotations

import math
import random
import sys

from PyQt6.QtCore import QObject, QPointF, QRect, QRectF, QSize, QTimer, QVariantAnimation, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient

import theme

ACCENT = (167, 139, 250)     # violeta  (--cosmos-accent)
ACCENT_2 = (125, 211, 252)   # celeste  (--cosmos-accent-2)
PINK = (236, 72, 153)


def _color(rgb, alpha: float) -> QColor:
    return QColor(rgb[0], rgb[1], rgb[2], max(0, min(255, round(255 * alpha))))


class CosmosSky:
    """Cielo estático cacheado. paint() lo dibuja en el painter ya recortado."""

    def __init__(self):
        self._pm: QPixmap | None = None
        self._key = None

    def paint(self, painter: QPainter, size: QSize, dpr: float = 1.0):
        key = (size.width(), size.height(), round(dpr, 2))
        if self._pm is None or key != self._key:
            self._pm = self._build(size.width(), size.height(), dpr)
            self._key = key
        painter.drawPixmap(0, 0, self._pm)

    # ------------------------------------------------------------ construcción
    @staticmethod
    def _nebula(p: QPainter, w: int, h: int, cx: float, cy: float,
                rx: float, ry: float, rgb, alpha: float):
        p.save()
        p.translate(cx * w, cy * h)
        p.scale(rx * w, ry * h)
        g = QRadialGradient(0.0, 0.0, 1.0)
        g.setColorAt(0.0, _color(rgb, alpha))
        g.setColorAt(0.7, _color(rgb, 0.0))
        g.setColorAt(1.0, _color(rgb, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0.0, 0.0), 1.0, 1.0)
        p.restore()

    def _build(self, w: int, h: int, dpr: float) -> QPixmap:
        w, h = max(1, w), max(1, h)
        pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Nebulosas (intensidad algo menor que en Spotify para no restar contraste al texto)
        self._nebula(p, w, h, 0.15, 0.05, 0.70, 0.55, ACCENT, 0.20)
        self._nebula(p, w, h, 0.90, 0.95, 0.60, 0.50, ACCENT_2, 0.14)
        self._nebula(p, w, h, 0.70, 0.20, 0.50, 0.40, PINK, 0.09)
        self._nebula(p, w, h, 0.24, 0.66, 0.38, 0.26, ACCENT, 0.08)
        self._nebula(p, w, h, 0.78, 0.31, 0.34, 0.24, ACCENT_2, 0.07)

        # Banda diagonal tipo Vía Láctea
        band = QLinearGradient(QPointF(0.0, 0.0), QPointF(w * 0.9, h))
        band.setColorAt(0.38, _color(ACCENT, 0.0))
        band.setColorAt(0.47, _color(ACCENT, 0.05))
        band.setColorAt(0.52, _color(ACCENT_2, 0.06))
        band.setColorAt(0.62, _color(ACCENT_2, 0.0))
        p.fillRect(QRectF(0.0, 0.0, float(w), float(h)), QBrush(band))

        # Viñeta: oscurece los bordes para dar profundidad
        p.save()
        p.translate(w * 0.5, h * 0.4)
        p.scale(w * 1.2, h * 1.0)
        vg = QRadialGradient(0.0, 0.0, 1.0)
        vg.setColorAt(0.55, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 105))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(vg)
        p.drawRect(QRectF(-2.0, -2.0, 4.0, 4.0))
        p.restore()

        self._stars(p, w, h)
        p.end()
        return pm

    @staticmethod
    def _stars(p: QPainter, w: int, h: int):
        rng = random.Random(7)   # mismo cielo en cada arranque
        count = max(28, min(150, (w * h) // 6500))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(count):
            x, y = rng.uniform(0, w), rng.uniform(0, h)
            roll = rng.random()
            if roll < 0.72:      # estrella chica
                p.setBrush(_color((255, 255, 255), rng.uniform(0.30, 0.65)))
                p.drawEllipse(QPointF(x, y), rng.uniform(0.5, 0.95), rng.uniform(0.5, 0.95))
            elif roll < 0.96:    # mediana con un halo suave
                tint = rng.choice(((255, 255, 255), (220, 210, 255), (190, 230, 255)))
                g = QRadialGradient(x, y, 3.6)
                g.setColorAt(0.0, _color((255, 255, 255), 0.75))
                g.setColorAt(0.3, _color(tint, 0.40))
                g.setColorAt(1.0, _color(tint, 0.0))
                p.setBrush(g)
                p.drawEllipse(QPointF(x, y), 3.6, 3.6)
            else:                # brillante con halo de color de acento
                col = ACCENT if rng.random() < 0.5 else ACCENT_2
                g = QRadialGradient(x, y, 7.0)
                g.setColorAt(0.0, _color((255, 255, 255), 0.85))
                g.setColorAt(0.25, _color(col, 0.45))
                g.setColorAt(1.0, _color(col, 0.0))
                p.setBrush(g)
                p.drawEllipse(QPointF(x, y), 7.0, 7.0)


# ------------------------------------------------------------ estrellas fugaces
def on_ac_power() -> bool:
    """True si el equipo está conectado a la corriente. Si no se puede saber
    (otros sistemas, error), False: en ese caso todo se queda estático."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryLifeFullTime", ctypes.c_ulong)]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return False
        return status.ACLineStatus == 1
    except Exception:
        return False


# (x inicial, y inicial, ángulo de viaje en grados, color) — mismos puntos de partida
# y direcciones que las cuatro estelas del tema de Spotify.
_PRESETS = (
    (0.88, 0.04, 140.0, (255, 255, 255), 130),
    (0.62, 0.00, 155.0, (255, 255, 255), 160),
    (0.96, 0.12, 125.0, ACCENT_2, 130),
    (0.04, 0.08, 40.0, ACCENT, 130),
)


class ShootingStars(QObject):
    """Una estrella fugaz cada 5-9 s, solo cuando is_allowed() es verdadero."""

    def __init__(self, widget, is_allowed):
        super().__init__(widget)
        self._w = widget
        self._is_allowed = is_allowed
        self._rng = random.Random()
        self._n = 0
        self._star = None          # (cabeza, cola, opacidad, color) del cuadro actual
        self._last_rect: QRect | None = None
        self._cur = None           # preset en curso: (inicio, dir, recorrido, largo, color)

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(800)
        self._anim.valueChanged.connect(self._on_tick)
        self._anim.finished.connect(self._on_done)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._launch)

    def start(self):
        if not self._timer.isActive() and self._anim.state() != QVariantAnimation.State.Running:
            self._timer.start(self._rng.randint(2500, 5000))

    def _launch(self):
        if theme.REDUCED_MOTION or not self._is_allowed() or not on_ac_power():
            self._timer.start(4000)   # revisa de nuevo más tarde; nada se anima mientras tanto
            return
        w, h = self._w.width(), self._w.height()
        sx, sy, ang, color, length = _PRESETS[self._n % len(_PRESETS)]
        self._n += 1
        rad = math.radians(ang)
        direction = QPointF(math.cos(rad), math.sin(rad))
        travel = min(math.hypot(w, h) * 0.85, 760.0)
        self._cur = (QPointF(sx * w, sy * h), direction, travel, length, color)
        self._anim.start()

    def _on_tick(self, value):
        if self._cur is None:
            return
        t = float(value)
        start, d, travel, length, color = self._cur
        head = QPointF(start.x() + d.x() * travel * t, start.y() + d.y() * travel * t)
        tail = QPointF(head.x() - d.x() * length, head.y() - d.y() * length)
        opacity = min(1.0, t / 0.10) * (1.0 - max(0.0, (t - 0.55) / 0.45))
        self._star = (head, tail, max(0.0, opacity), color)
        rect = QRect(int(min(head.x(), tail.x())) - 6, int(min(head.y(), tail.y())) - 6,
                     int(abs(head.x() - tail.x())) + 12, int(abs(head.y() - tail.y())) + 12)
        dirty = rect if self._last_rect is None else rect.united(self._last_rect)
        self._last_rect = rect
        self._w.update(dirty)

    def _on_done(self):
        self._star = None
        self._cur = None
        if self._last_rect is not None:
            self._w.update(self._last_rect)
            self._last_rect = None
        self._timer.start(self._rng.randint(5000, 9000))

    def paint(self, painter: QPainter):
        if self._star is None:
            return
        head, tail, opacity, color = self._star
        if opacity <= 0.01:
            return
        grad = QLinearGradient(tail, head)
        grad.setColorAt(0.0, _color(color, 0.0))
        grad.setColorAt(1.0, _color(color, 0.95 * opacity))
        pen = QPen(grad, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(tail, head)
