"""Efectos animados y en 3D del asistente de bienvenida (onboarding.py).

Sin OpenGL ni módulos extra de Qt (el .exe no los lleva): todo es QPainter con
una proyección en perspectiva hecha a mano (`Camera`) o con QTransform.

- `SoundScene` / `SoundStage`: la escena central, temática de sonido (`SoundScene`
  es solo el dibujo; `SoundStage` el widget de la bienvenida y la carga;
  `IdleScene` la pinta dentro de las carátulas cuando no hay imagen). Un disco de vinilo en 3D
  que gira sobre un plato, con su brazo, rodeado por un anillo de barras de
  ecualizador que laten al ritmo (120 BPM sintético), ondas de sonido que se
  expanden por el suelo y notas musicales que suben con profundidad. La
  cámara oscila despacio alrededor de la escena para que se lea el volumen.
- `ProgressDots`: los puntos de progreso; el actual es una píldora que se
  estira y se desliza.
- `PageFlip`: cambio de paso como una tarjeta que gira, con profundidad.
- `Confetti`: confeti con profundidad al terminar.

Reglas de la casa (README, sección 7): todo va por reloj real
(time.monotonic), cada temporizador se para al ocultarse y no arranca oculto,
y con «reducir movimiento» (theme.REDUCED_MOTION) se dibuja quieto.
"""
from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from theme import Palette

FPS_MS = 33                 # ~30 fps


def reduced_motion() -> bool:
    import theme
    return bool(getattr(theme, "REDUCED_MOTION", False))


def tilt_transform(w: float, h: float, rot_x: float = 0.0, rot_y: float = 0.0, scale: float = 1.0) -> QTransform:
    """Giro con perspectiva alrededor del centro de un rectángulo w×h (grados)."""
    t = QTransform()
    t.translate(w / 2, h / 2)
    if rot_y:
        t.rotate(rot_y, Qt.Axis.YAxis)
    if rot_x:
        t.rotate(rot_x, Qt.Axis.XAxis)
    if scale != 1.0:
        t.scale(scale, scale)
    t.translate(-w / 2, -h / 2)
    return t


class Camera:
    """Proyección en perspectiva. Mundo: suelo en y = 0, «y» hacia arriba.
    `yaw` gira la escena alrededor del eje vertical; `pitch` inclina la cámara
    hacia abajo. Devuelve (x, y en pantalla, profundidad) — más profundidad =
    más lejos."""

    def __init__(self, cx: float, cy: float, focal: float, distance: float,
                 yaw_deg: float = 0.0, pitch_deg: float = 62.0):
        self.cx, self.cy, self.focal, self.distance = cx, cy, focal, distance
        self.cy_yaw, self.sy_yaw = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
        self.cp, self.sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))

    def project(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        xr = x * self.cy_yaw - z * self.sy_yaw
        zr = x * self.sy_yaw + z * self.cy_yaw
        # cámara por encima mirando hacia abajo: lo lejano (z+) sube en pantalla
        yp = y * self.cp + zr * self.sp
        zp = -y * self.sp + zr * self.cp
        depth = max(1.0, zp + self.distance)
        k = self.focal / depth
        return self.cx + xr * k, self.cy - yp * k, depth

    def circle(self, radius: float, y: float = 0.0, steps: int = 56, start: float = 0.0,
               span: float = 2 * math.pi) -> QPolygonF:
        pts = []
        for i in range(steps + 1):
            a = start + span * i / steps
            sx, sy, _d = self.project(radius * math.cos(a), y, radius * math.sin(a))
            pts.append(QPointF(sx, sy))
        return QPolygonF(pts)


def beat_levels(t: float, bars: int, energy: float = 1.0) -> list[float]:
    """Niveles 0..1 de un ecualizador sintético: un pulso de bombo a 120 BPM que
    recorre el anillo como una ola, más algo de movimiento propio de cada barra.
    Función pura (se prueba sin Qt)."""
    beat = math.exp(-((t * 2.0) % 1.0) * 5.0)                 # golpe cada 0,5 s que decae
    out = []
    for i in range(bars):
        a = 2 * math.pi * i / bars
        wave = 0.5 + 0.5 * math.sin(a * 3 - t * 2.4)
        jitter = 0.5 + 0.5 * math.sin(t * (3.1 + (i % 5) * 0.7) + i * 1.9)
        level = 0.18 + 0.42 * wave * (0.55 + 0.45 * jitter) + 0.4 * beat * (0.6 + 0.4 * wave)
        out.append(max(0.05, min(1.0, level * energy)))
    return out


class SoundScene:
    """La escena 3D de sonido, sin widget: se pinta en cualquier rectángulo con
    `paint`. La usan la bienvenida y la pantalla de carga (vía `SoundStage`) y las
    carátulas cuando no hay imagen (vía `IdleScene`).

    `detail`: "full" (todo) o "mini" (para huecos chicos, < 110 px: menos barras,
    menos notas, sin surcos ni brazo — a ese tamaño no se distinguían y costaban)."""

    BARS = 30
    DISTANCE = 5.0
    PITCH = 52.0             # inclinación de la cámara (± 4° de vaivén)
    WAVE_MAX = 1.75          # radio máximo de las ondas del suelo
    NOTE_TOP = 1.35          # altura máxima de las notas
    BAR_MAX = 1.2            # altura máxima de las barras
    MINI_BELOW = 110         # lado (px) por debajo del cual se usa el detalle "mini"

    def __init__(self, detail: str = "full"):
        self.detail = detail if detail in ("full", "mini") else "full"
        self._fit_cache: tuple | None = None
        rnd = random.Random(7)
        # notas: (ángulo, radio, fase, velocidad, símbolo)
        self._notes = [(rnd.uniform(0, 2 * math.pi), rnd.uniform(1.2, 1.6), rnd.uniform(0, 1),
                        rnd.uniform(0.12, 0.22), rnd.choice("♪♫♩")) for _ in range(7)]

    @classmethod
    def detail_for(cls, w: float, h: float) -> str:
        return "mini" if min(w, h) < cls.MINI_BELOW else "full"

    @property
    def bars(self) -> int:
        return 18 if self.detail == "mini" else self.BARS

    # -------------------------------------------------------------- encaje
    def fit(self, w: float, h: float) -> tuple[float, float, float]:
        """(escala, cx, cy) para que la escena quepa entera en w×h con cualquier
        giro de cámara. Se mide la caja de la escena en unidades y se encaja;
        se recalcula solo si cambia el tamaño."""
        if self._fit_cache and self._fit_cache[0] == (w, h):
            return self._fit_cache[1]
        xs, ys = [], []
        for yaw in (-18, 0, 18):
            for pitch in (self.PITCH - 4, self.PITCH + 4):
                cam = Camera(0, 0, self.DISTANCE, self.DISTANCE, yaw, pitch)
                for a in range(0, 360, 15):
                    ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
                    for r, y in ((self.WAVE_MAX, 0), (1.45, 0), (1.45, self.BAR_MAX + 0.15),
                                 (1.6, self.NOTE_TOP + 0.2), (1.12, 0)):
                        x2, y2, _ = cam.project(r * ca, y, r * sa)
                        xs.append(x2)
                        ys.append(y2)
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        scale = max(1.0, min(w * 0.98 / bw, h * 0.98 / bh))
        cx = w / 2 - (max(xs) + min(xs)) / 2 * scale
        cy = h / 2 - (max(ys) + min(ys)) / 2 * scale
        self._fit_cache = ((w, h), (scale, cx, cy))
        return scale, cx, cy

    # -------------------------------------------------------------- dibujo
    def paint(self, p: QPainter, rect: QRectF, t: float, a_col: QColor, b_col: QColor,
              font: QFont | None = None, energy: float = 1.0):
        w, h = rect.width(), rect.height()
        if w < 24 or h < 24:
            return
        mini = self.detail == "mini"
        p.save()
        p.translate(rect.x(), rect.y())
        scale, cx, cy = self.fit(w, h)
        cam = Camera(cx, cy, focal=scale * self.DISTANCE, distance=self.DISTANCE,
                     yaw_deg=18 * math.sin(t * 0.35), pitch_deg=self.PITCH + 4 * math.sin(t * 0.23))

        # resplandor bajo el plato
        gx, gy, _ = cam.project(0, 0, 0)
        glow = QRadialGradient(QPointF(gx, gy), scale * 1.6)
        glow.setColorAt(0.0, QColor(a_col.red(), a_col.green(), a_col.blue(), 70))
        glow.setColorAt(1.0, QColor(a_col.red(), a_col.green(), a_col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(gx, gy), scale * 1.6, scale * 0.8)

        # ondas de sonido por el suelo, una por golpe
        waves = 2 if mini else 3
        steps = 36 if mini else 56
        for k in range(waves):
            phase = ((t * 2.0) + k / waves) % 1.0
            radius = 1.05 + (self.WAVE_MAX - 1.05) * phase
            alpha = int(120 * (1 - phase) * min(1.0, energy))
            p.setPen(QPen(QColor(b_col.red(), b_col.green(), b_col.blue(), alpha), 1.2 if mini else 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(cam.circle(radius, 0.0, steps=steps))

        # barras: las de detrás del disco primero, luego el disco, luego las de delante
        n = self.bars
        half = 0.09 * self.BARS / n
        levels = beat_levels(t, n, energy)
        bars = []
        for i, lvl in enumerate(levels):
            a = 2 * math.pi * i / n + t * 0.25
            bars.append((a, lvl, cam.project(1.38 * math.cos(a), 0, 1.38 * math.sin(a))[2]))
        _, _, disc_depth = cam.project(0, 0, 0)
        back = sorted((b for b in bars if b[2] >= disc_depth), key=lambda b: -b[2])
        front = sorted((b for b in bars if b[2] < disc_depth), key=lambda b: -b[2])
        for a, lvl, _d in back:
            self._bar(p, cam, a, lvl, half, a_col, b_col)
        self._disc(p, cam, t, a_col, b_col, mini)
        for a, lvl, _d in front:
            self._bar(p, cam, a, lvl, half, a_col, b_col)

        # notas que suben
        f = QFont(font) if font is not None else QFont()
        for ang, rad, ph, speed, sym in (self._notes[:3] if mini else self._notes):
            life = (ph + t * speed) % 1.0
            x, z = rad * math.cos(ang + t * 0.1), rad * math.sin(ang + t * 0.1)
            sx, sy, depth = cam.project(x, 0.2 + life * (self.NOTE_TOP - 0.2), z)
            size = max(6.0 if mini else 7.0, scale * 0.30 * cam.distance / depth)
            alpha = int(200 * math.sin(math.pi * life))
            f.setPixelSize(int(size))
            p.setFont(f)
            col = QColor(b_col if (ang * 10) % 2 > 1 else a_col)
            col.setAlpha(alpha)
            p.setPen(col)
            p.drawText(QPointF(sx - size / 3, sy), sym)
        p.restore()

    def _bar(self, p: QPainter, cam: Camera, a: float, level: float, half: float,
             a_col: QColor, b_col: QColor):
        """Barra con volumen: cara frontal + tapa superior."""
        r, height = 1.38, 0.15 + (self.BAR_MAX - 0.15) * level
        ca, sa = math.cos(a), math.sin(a)
        tx, tz = -sa * half, ca * half                    # tangente al anillo
        nx, nz = ca * 0.06, sa * 0.06                     # grosor hacia fuera
        x0, z0 = r * ca, r * sa
        base = [(x0 - tx, z0 - tz), (x0 + tx, z0 + tz)]
        outer = [(x0 - tx + nx, z0 - tz + nz), (x0 + tx + nx, z0 + tz + nz)]
        face = QPolygonF([QPointF(*cam.project(base[0][0], 0, base[0][1])[:2]),
                          QPointF(*cam.project(base[1][0], 0, base[1][1])[:2]),
                          QPointF(*cam.project(base[1][0], height, base[1][1])[:2]),
                          QPointF(*cam.project(base[0][0], height, base[0][1])[:2])])
        top = QPolygonF([QPointF(*cam.project(base[0][0], height, base[0][1])[:2]),
                         QPointF(*cam.project(base[1][0], height, base[1][1])[:2]),
                         QPointF(*cam.project(outer[1][0], height, outer[1][1])[:2]),
                         QPointF(*cam.project(outer[0][0], height, outer[0][1])[:2])])
        y_bottom = cam.project(x0, 0, z0)[1]
        y_top = cam.project(x0, height, z0)[1]
        grad = QLinearGradient(0, y_bottom, 0, y_top)
        grad.setColorAt(0.0, QColor(a_col.red(), a_col.green(), a_col.blue(), 210))
        grad.setColorAt(1.0, QColor(b_col.red(), b_col.green(), b_col.blue(), 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPolygon(face)
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawPolygon(top)

    def _disc(self, p: QPainter, cam: Camera, t: float, a_col: QColor, b_col: QColor, mini: bool = False):
        """Plato + vinilo girando + brazo."""
        spin = t * 2 * math.pi * 0.55                     # ~33 rpm
        steps = 36 if mini else 56
        # plato (base) y canto del disco: dos círculos a distinta altura
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawPolygon(cam.circle(1.12, -0.02, steps=steps))
        p.setBrush(QColor(10, 10, 14, 255))
        p.drawPolygon(cam.circle(1.0, 0.0, steps=steps))
        top = cam.circle(1.0, 0.06, steps=steps)
        grad = QRadialGradient(QPointF(*cam.project(0, 0.06, 0)[:2]), cam.focal / cam.distance * 1.0)
        grad.setColorAt(0.0, QColor(34, 34, 42))
        grad.setColorAt(1.0, QColor(14, 14, 18))
        p.setBrush(QBrush(grad))
        p.drawPolygon(top)
        if not mini:
            # surcos
            for r in (0.92, 0.82, 0.72, 0.62, 0.52):
                p.setPen(QPen(QColor(255, 255, 255, 14), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolyline(cam.circle(r, 0.061, steps=48))
        # reflejo que gira con el disco (así se ve que gira)
        for offset in (0.0, math.pi):
            arc_out = cam.circle(0.95, 0.062, steps=10, start=spin + offset, span=0.55)
            arc_in = cam.circle(0.45, 0.062, steps=10, start=spin + offset, span=0.55)
            poly = QPolygonF(list(arc_out) + list(reversed(list(arc_in))))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawPolygon(poly)
        # etiqueta central con los colores de la app
        center = QPointF(*cam.project(0, 0.063, 0)[:2])
        label_grad = QLinearGradient(center.x() - 30, center.y() - 10, center.x() + 30, center.y() + 10)
        label_grad.setColorAt(0.0, a_col)
        label_grad.setColorAt(1.0, b_col)
        p.setBrush(QBrush(label_grad))
        p.drawPolygon(cam.circle(0.34, 0.063, steps=24 if mini else 40))
        dot = 0.6 if mini else 1.0
        mx, my, _ = cam.project(0.22 * math.cos(spin), 0.064, 0.22 * math.sin(spin))
        p.setBrush(QColor(255, 255, 255, 200))
        p.drawEllipse(QPointF(mx, my), 2.2 * dot, 1.6 * dot)
        p.setBrush(QColor(10, 10, 14))
        p.drawEllipse(center, 2.6 * dot, 2.0 * dot)
        if mini:
            return
        # brazo: pivote fuera del disco, aguja sobre un surco exterior
        pivot = cam.project(1.05, 0.22, -0.85)
        elbow = cam.project(0.78, 0.2, -0.05)
        needle = cam.project(0.62, 0.09, 0.32)
        arm_pen = QPen(QColor(220, 222, 230, 230), max(2.0, cam.focal / pivot[2] * 0.05))
        arm_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        arm_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(arm_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(pivot[0], pivot[1]), QPointF(elbow[0], elbow[1]),
                                  QPointF(needle[0], needle[1])]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(200, 202, 210))
        p.drawEllipse(QPointF(pivot[0], pivot[1]), 5, 4)
        p.setBrush(a_col)
        p.drawEllipse(QPointF(needle[0], needle[1]), 2.4, 2.0)


class SoundStage(QWidget):
    """Escena 3D de la bienvenida y la pantalla de carga: vinilo girando,
    ecualizador en anillo, ondas y notas. Se adapta al tamaño que le den."""

    BARS = SoundScene.BARS
    DISTANCE = SoundScene.DISTANCE
    PITCH = SoundScene.PITCH
    WAVE_MAX = SoundScene.WAVE_MAX
    NOTE_TOP = SoundScene.NOTE_TOP
    BAR_MAX = SoundScene.BAR_MAX

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(110)
        self._t0 = time.monotonic()
        self._energy = 1.0
        self._energy_target = 1.0
        self._scene = SoundScene("full")
        self._clock = QTimer(self)
        self._clock.setInterval(FPS_MS)
        self._clock.timeout.connect(self._tick)

    # -------------------------------------------------------------- control
    def set_energy(self, value: float):
        """1 = normal; más = celebración (las barras saltan más)."""
        self._energy_target = max(0.2, float(value))

    def showEvent(self, event):
        super().showEvent(event)
        if not reduced_motion() and not self._clock.isActive():
            self._clock.start()

    def hideEvent(self, event):
        self._clock.stop()
        super().hideEvent(event)

    def _tick(self):
        self._energy += (self._energy_target - self._energy) * 0.08
        self.update()

    def elapsed(self) -> float:
        return 0.0 if reduced_motion() else time.monotonic() - self._t0

    def fit(self, w: float, h: float) -> tuple[float, float, float]:
        return self._scene.fit(w, h)

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._scene.paint(p, QRectF(0, 0, w, h), self.elapsed(), QColor(*Palette.ACCENT_A),
                          QColor(*Palette.ACCENT_B), self.font(), self._energy)
        p.end()


class IdleScene(QObject):
    """La escena 3D como marcador de posición de una carátula (CoverArt,
    VinylCover): sustituye a la nota musical cuando no hay imagen.

    No es un widget: la pinta su dueño en su propio paintEvent (así respeta sus
    esquinas, su borde y su caché). Solo pide repintados mientras hace falta:
    sin imagen, con el dueño visible, sin minimizar, sin «pausa» (p. ej. el panel
    lateral recogido fuera de la pantalla) y sin «reducir movimiento». A 25 fps y
    con menos detalle en huecos chicos, porque puede quedarse a la vista horas."""

    FPS_MS = 40               # 25 fps: de sobra para algo decorativo
    ENERGY = 0.8              # más tranquila que en la bienvenida: está «esperando»

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = owner
        self._active = False
        self._paused = False
        self._t0 = time.monotonic()
        self._scene: SoundScene | None = None        # se crea al primer uso
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(self.FPS_MS)
        self._timer.timeout.connect(self._tick)

    # ---------------------------------------------------------------- estado
    def is_running(self) -> bool:
        return self._timer.isActive()

    def set_active(self, active: bool):
        """True cuando el dueño no tiene imagen (se ve la escena)."""
        if bool(active) != self._active:
            self._active = bool(active)
            self.sync()

    def set_paused(self, paused: bool):
        """Pausa externa: el dueño está fuera de la vista aunque Qt lo crea visible."""
        if bool(paused) != self._paused:
            self._paused = bool(paused)
            self.sync()

    def _should_run(self) -> bool:
        owner = self._owner
        if not (self._active and not self._paused and owner.isVisible() and not reduced_motion()):
            return False
        win = owner.window()
        return win is None or not win.isMinimized()

    def sync(self):
        run = self._should_run()
        if run and not self._timer.isActive():
            self._timer.start()
        elif not run and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        if not self._should_run():          # p. ej. se minimizó sin avisar
            self._timer.stop()
            return
        self._owner.update()

    # ---------------------------------------------------------------- dibujo
    def paint(self, p: QPainter, rect: QRectF, a_col: QColor, b_col: QColor):
        detail = SoundScene.detail_for(rect.width(), rect.height())
        if self._scene is None or self._scene.detail != detail:
            self._scene = SoundScene(detail)
        t = 0.0 if reduced_motion() else time.monotonic() - self._t0
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        self._scene.paint(p, rect, t, a_col, b_col, self._owner.font(), self.ENERGY)
        p.restore()


# ---------------------------------------------------------- puntos de progreso
class ProgressDots(QWidget):
    """Puntos de progreso: el paso actual es una píldora alargada que se desliza."""

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self._count = count
        self._pos = 0.0
        self.setFixedSize(16 * count + 22, 12)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(380)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.valueChanged.connect(self._on_value)

    def set_current(self, index: int):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(float(index))
        self._anim.start()

    def current_position(self) -> float:
        return self._pos

    def _on_value(self, value):
        self._pos = float(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self._count):
            p.setBrush(QColor(255, 255, 255, 45))
            x = 6 + i * 16 + (22 if i > self._pos else 0)
            p.drawEllipse(QPointF(x, 6), 3.2, 3.2)
        x = 2 + self._pos * 16
        grad = QLinearGradient(x, 0, x + 30, 0)
        grad.setColorAt(0.0, QColor(*Palette.ACCENT_A))
        grad.setColorAt(1.0, QColor(*Palette.ACCENT_B))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(x, 2.5, 30, 7), 3.5, 3.5)
        p.end()


# --------------------------------------------------------- giro de página
class PageFlip(QWidget):
    """Capa encima de las páginas que hace el cambio como una tarjeta que gira:
    la vieja gira hasta quedar de canto y la nueva sigue el giro hasta quedar de
    frente. Mientras, la página real queda invisible (la oculta el asistente)."""

    finished = pyqtSignal()
    MARGIN = 32                     # el giro con perspectiva sobresale (borde cercano más alto)
    DURATION_MS = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._old = self._new = None
        self._dir = 1
        self._p = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self.DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._done)
        self.hide()

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def start(self, page_rect, old: QPixmap, new: QPixmap, forward: bool):
        """`page_rect`: dónde está la página (coordenadas del padre). Las dos
        fotos se dibujan a su tamaño real, arriba y centradas: si miden distinto
        no se deforman."""
        m = self.MARGIN

        def logical(pm):
            dpr = pm.devicePixelRatio() or 1.0
            return pm.width() / dpr, pm.height() / dpr

        tallest = max(page_rect.height(), int(logical(old)[1]), int(logical(new)[1]))
        rect = page_rect.adjusted(-m, -m, m, m)
        rect.setHeight(tallest + 2 * m)
        self.setGeometry(rect)
        self._old, self._new, self._dir = old, new, (1 if forward else -1)
        self._p = 0.0
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.start()

    def _on_value(self, value):
        self._p = float(value)
        self.update()

    def _done(self):
        self.hide()
        self._old = self._new = None
        self.finished.emit()

    def paintEvent(self, event):
        if self._old is None or self._new is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        m = self.MARGIN
        prog = self._p
        if prog < 0.5:
            pix, angle = self._old, -90.0 * (prog / 0.5) * self._dir
        else:
            pix, angle = self._new, 90.0 * (1.0 - (prog - 0.5) / 0.5) * self._dir
        dpr = pix.devicePixelRatio() or 1.0
        pw, ph = pix.width() / dpr, pix.height() / dpr
        depth = 1.0 - 0.10 * math.sin(math.pi * prog)            # se aleja un poco a mitad del giro
        shade = abs(angle) / 90.0
        p.translate(m + max(0.0, (self.width() - 2 * m - pw) / 2), m)
        p.setTransform(tilt_transform(pw, ph, 0.0, angle, depth), True)
        p.setOpacity(1.0 - 0.55 * shade)
        p.drawPixmap(QRectF(0, 0, pw, ph), pix, QRectF(0, 0, pix.width(), pix.height()))
        p.end()


# ------------------------------------------------------------------ confeti
class Confetti(QWidget):
    """Confeti con profundidad: cada pieza tiene x, y, z (más lejos = más pequeña
    y más tenue) y gira en 3D (se ve más ancha o más fina)."""

    DURATION_S = 2.6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pieces: list[list[float]] = []
        self._colors = (Palette.ACCENT_A, Palette.ACCENT_B, (255, 255, 255), (255, 214, 102))
        self._t0 = self._last = time.monotonic()
        self._clock = QTimer(self)
        self._clock.setInterval(FPS_MS)
        self._clock.timeout.connect(self._step)
        self.hide()

    def burst(self, count: int = 70, origin_y: float = 0.35):
        if reduced_motion():
            return
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        w, h = self.width(), self.height()
        rnd = random.Random()
        self._pieces = [[w * (0.5 + rnd.uniform(-0.15, 0.15)), h * origin_y, rnd.uniform(0, 600),
                         rnd.uniform(-240, 240), rnd.uniform(-480, -200),
                         rnd.uniform(0, 360), rnd.uniform(-420, 420), rnd.randrange(len(self._colors)),
                         rnd.uniform(5, 9)] for _ in range(count)]
        self._t0 = self._last = time.monotonic()
        self.show()
        self.raise_()
        self._clock.start()

    def hideEvent(self, event):
        self._clock.stop()
        super().hideEvent(event)

    def _step(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        for pc in self._pieces:
            pc[4] += 900 * dt                 # gravedad
            pc[3] *= (1 - 0.6 * dt)           # rozamiento del aire
            pc[0] += pc[3] * dt
            pc[1] += pc[4] * dt
            pc[5] += pc[6] * dt
        if now - self._t0 > self.DURATION_S:
            self._pieces = []
            self.hide()
            return
        self.update()

    def paintEvent(self, event):
        if not self._pieces:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        fade = max(0.0, min(1.0, (self.DURATION_S - (time.monotonic() - self._t0)) / 0.8))
        focal = 700.0
        cx = self.width() / 2
        for x, y, z, _vx, _vy, rot, _vr, ci, size in self._pieces:
            k = focal / (focal + z)                          # perspectiva
            col = QColor(*self._colors[ci])
            col.setAlpha(int(230 * k * fade))
            p.save()
            p.translate(cx + (x - cx) * k, y * k + self.height() * 0.1 * (1 - k))
            p.rotate(rot)
            flip = abs(math.cos(math.radians(rot * 1.7)))     # giro 3D sobre su eje: se ve de canto
            p.scale(k, k * (0.25 + 0.75 * flip))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(-size / 2, -size / 4, size, size / 2), 1.5, 1.5)
            p.restore()
        p.end()
