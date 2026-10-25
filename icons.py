"""
Íconos dibujados por código (QPainterPath) en un lienzo lógico de 24x24.
Evita depender de archivos .png externos: el reproductor es 100% autocontenido.
"""
import math
from PyQt6.QtCore import QRectF, QPointF
from PyQt6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF
from PyQt6.QtCore import Qt


def _stroke(path: QPainterPath, width: float = 2.3) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def _arrow_head(tip: tuple, angle_deg: float, size: float = 4.6) -> QPainterPath:
    a = math.radians(angle_deg)
    tip_p = QPointF(*tip)
    back = QPointF(tip_p.x() - size * math.cos(a), tip_p.y() - size * math.sin(a))
    perp = a + math.pi / 2
    spread = size * 0.6
    p2 = QPointF(back.x() + spread * math.cos(perp), back.y() + spread * math.sin(perp))
    p3 = QPointF(back.x() - spread * math.cos(perp), back.y() - spread * math.sin(perp))
    path = QPainterPath()
    path.addPolygon(QPolygonF([tip_p, p2, p3]))
    path.closeSubpath()
    return path


def play() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(6.5, 4.5)
    p.lineTo(20, 12)
    p.lineTo(6.5, 19.5)
    p.closeSubpath()
    return p


def pause() -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(5.5, 4, 4.6, 16), 2, 2)
    p.addRoundedRect(QRectF(13.9, 4, 4.6, 16), 2, 2)
    return p


def skip(reverse: bool = False) -> QPainterPath:
    p = QPainterPath()
    if not reverse:
        p.moveTo(4.5, 5)
        p.lineTo(15.5, 12)
        p.lineTo(4.5, 19)
        p.closeSubpath()
        p.addRoundedRect(QRectF(17, 5, 2.6, 14), 1.2, 1.2)
    else:
        p.moveTo(19.5, 5)
        p.lineTo(8.5, 12)
        p.lineTo(19.5, 19)
        p.closeSubpath()
        p.addRoundedRect(QRectF(4.4, 5, 2.6, 14), 1.2, 1.2)
    return p


def shuffle() -> QPainterPath:
    lines = QPainterPath()
    lines.moveTo(3, 6.5)
    lines.lineTo(8, 6.5)
    lines.lineTo(19, 17.5)
    lines.moveTo(3, 17.5)
    lines.lineTo(8, 17.5)
    lines.lineTo(19, 6.5)
    result = _stroke(lines, 2.1)
    result.addPath(_arrow_head((19, 17.5), 45))
    result.addPath(_arrow_head((19, 6.5), -45))
    return result


def repeat_loop(with_one: bool = False) -> QPainterPath:
    rect = QRectF(3.4, 3.4, 17.2, 17.2)
    arc = QPainterPath()
    start_angle = 205
    sweep = -290
    arc.arcMoveTo(rect, start_angle)
    arc.arcTo(rect, start_angle, sweep)
    result = _stroke(arc, 2.1)

    end_angle_deg = start_angle + sweep
    rad = math.radians(end_angle_deg)
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2, rect.height() / 2
    end_point = (cx + rx * math.cos(rad), cy - ry * math.sin(rad))
    tangent_angle = -end_angle_deg - 90
    result.addPath(_arrow_head(end_point, tangent_angle, size=4.2))

    if with_one:
        one = QPainterPath()
        one.moveTo(11.1, 9.3)
        one.lineTo(12.6, 8.5)
        one.lineTo(12.6, 15.5)
        result.addPath(_stroke(one, 1.9))
    return result


def chevron(direction: str = "up") -> QPainterPath:
    p = QPainterPath()
    if direction == "up":
        p.moveTo(5, 15)
        p.lineTo(12, 8)
        p.lineTo(19, 15)
    elif direction == "left":
        p.moveTo(15, 5)
        p.lineTo(8, 12)
        p.lineTo(15, 19)
    elif direction == "right":
        p.moveTo(9, 5)
        p.lineTo(16, 12)
        p.lineTo(9, 19)
    else:
        p.moveTo(5, 9)
        p.lineTo(12, 16)
        p.lineTo(19, 9)
    return _stroke(p, 2.2)


def close_x() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(6, 6)
    p.lineTo(18, 18)
    p.moveTo(18, 6)
    p.lineTo(6, 18)
    return _stroke(p, 2.1)


def minus() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(6, 12)
    p.lineTo(18, 12)
    return _stroke(p, 2.3)


def dots() -> QPainterPath:
    p = QPainterPath()
    for cx in (6, 12, 18):
        p.addEllipse(QPointF(cx, 12), 1.6, 1.6)
    return p


def gear() -> QPainterPath:
    outer = QPainterPath()
    outer.addEllipse(QPointF(12, 12), 8.2, 8.2)
    teeth = QPainterPath()
    for i in range(8):
        ang = math.radians(i * 45)
        x1, y1 = 12 + 8.2 * math.cos(ang), 12 + 8.2 * math.sin(ang)
        x2, y2 = 12 + 10.6 * math.cos(ang), 12 + 10.6 * math.sin(ang)
        seg = QPainterPath()
        seg.moveTo(x1, y1)
        seg.lineTo(x2, y2)
        teeth.addPath(_stroke(seg, 2.4))
    result = _stroke(outer, 2.1)
    result.addPath(teeth)
    inner = QPainterPath()
    inner.addEllipse(QPointF(12, 12), 3.0, 3.0)
    result.addPath(_stroke(inner, 2.0))
    return result


def note() -> QPainterPath:
    p = QPainterPath()
    p.addEllipse(QPointF(7.2, 18), 3.2, 2.6)
    p.addEllipse(QPointF(16.2, 16), 3.2, 2.6)
    stem = QPainterPath()
    stem.addRect(QRectF(9.9, 4, 1.8, 14))
    stem2 = QPainterPath()
    stem2.addRect(QRectF(18.9, 3, 1.8, 13))
    beam = QPainterPath()
    beam.moveTo(9.9, 4)
    beam.lineTo(20.7, 3)
    beam.lineTo(20.7, 6.4)
    beam.lineTo(9.9, 7.4)
    beam.closeSubpath()
    p.addPath(stem)
    p.addPath(stem2)
    p.addPath(beam)
    # Las partes se solapan (plica/cabeza/barra): con el relleno par-impar por
    # defecto el solape quedaba como huecos; con relleno por devanado se unen.
    p.setFillRule(Qt.FillRule.WindingFill)
    return p


def speaker() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(4, 9.5)
    p.lineTo(7.6, 9.5)
    p.lineTo(12, 5.5)
    p.lineTo(12, 18.5)
    p.lineTo(7.6, 14.5)
    p.lineTo(4, 14.5)
    p.closeSubpath()
    waves = QPainterPath()
    waves.moveTo(15.3, 8.3)
    waves.arcTo(QRectF(13.3, 6.3, 8, 11.4), 60, -120)
    p.addPath(_stroke(waves, 1.9))
    return p


def speaker_mute() -> QPainterPath:
    """Parlante sin ondas + una X: estado silenciado del ícono de volumen."""
    p = QPainterPath()
    p.moveTo(4, 9.5)
    p.lineTo(7.6, 9.5)
    p.lineTo(12, 5.5)
    p.lineTo(12, 18.5)
    p.lineTo(7.6, 14.5)
    p.lineTo(4, 14.5)
    p.closeSubpath()
    cross = QPainterPath()
    cross.moveTo(15.2, 9.2)
    cross.lineTo(20.6, 14.8)
    cross.moveTo(20.6, 9.2)
    cross.lineTo(15.2, 14.8)
    p.addPath(_stroke(cross, 1.9))
    return p


def alert() -> QPainterPath:
    circle = QPainterPath()
    circle.addEllipse(QPointF(12, 12), 9.2, 9.2)
    result = _stroke(circle, 2.0)
    bar = QPainterPath()
    bar.addRoundedRect(QRectF(11, 6.6, 2, 7.4), 1, 1)
    result.addPath(bar)
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 16.6), 1.2, 1.2)
    result.addPath(dot)
    return result


def mic() -> QPainterPath:
    body = QPainterPath()
    body.addRoundedRect(QRectF(9.2, 2.6, 5.6, 10.4), 2.8, 2.8)
    stand = QPainterPath()
    stand.moveTo(6.3, 10.5)
    stand.arcTo(QRectF(6.3, 6.5, 11.4, 11.4), 180, 180)
    result = _stroke(stand, 1.9)
    result.addPath(body)
    leg = QPainterPath()
    leg.addRoundedRect(QRectF(11.1, 17.9, 1.8, 3.2), 0.9, 0.9)
    result.addPath(leg)
    foot = QPainterPath()
    foot.addRoundedRect(QRectF(7.6, 20.4, 8.8, 1.8), 0.9, 0.9)
    result.addPath(foot)
    return result


def _heart_shape() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(12, 20.4)
    p.cubicTo(5.2, 14.9, 2.6, 11.5, 2.6, 8.3)
    p.cubicTo(2.6, 5.5, 4.8, 3.5, 7.4, 3.5)
    p.cubicTo(9.3, 3.5, 11.0, 4.6, 12, 6.5)
    p.cubicTo(13.0, 4.6, 14.7, 3.5, 16.6, 3.5)
    p.cubicTo(19.2, 3.5, 21.4, 5.5, 21.4, 8.3)
    p.cubicTo(21.4, 11.5, 18.8, 14.9, 12, 20.4)
    p.closeSubpath()
    return p


def heart() -> QPainterPath:
    """Corazón relleno: la canción está en tus favoritas."""
    return _heart_shape()


def heart_outline() -> QPainterPath:
    """Corazón solo contorno: aún no está en tus favoritas."""
    return _stroke(_heart_shape(), 2.0)


def refresh() -> QPainterPath:
    """Flecha circular (recargar / reintentar)."""
    cx, cy, r, start, sweep = 12.0, 12.0, 7.4, 55.0, 270.0
    arc = QPainterPath()
    arc.moveTo(cx + r * math.cos(math.radians(start)), cy - r * math.sin(math.radians(start)))
    arc.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), start, sweep)
    path = _stroke(arc, 2.1)
    # Punta en el final del arco, en el sentido de giro (antihorario en pantalla).
    end = arc.currentPosition()
    theta = math.radians(start + sweep)
    heading = math.degrees(math.atan2(-math.cos(theta), -math.sin(theta)))
    path.addPath(_arrow_head((end.x(), end.y()), heading, 5.8))
    return path


def clock() -> QPainterPath:
    circle = QPainterPath()
    circle.addEllipse(QPointF(12, 12.5), 8.6, 8.6)
    result = _stroke(circle, 2.0)
    hands = QPainterPath()
    hands.moveTo(12, 12.5)
    hands.lineTo(12, 6.9)
    hands.moveTo(12, 12.5)
    hands.lineTo(16.1, 14.6)
    result.addPath(_stroke(hands, 1.8))
    return result


def chart() -> QPainterPath:
    """Tres barras verticales de altura creciente, tipo gráfico de
    estadísticas — usado en el panel de estadísticas de escucha."""
    p = QPainterPath()
    p.addRoundedRect(QRectF(3.2, 13.5, 4.4, 7.0), 1.1, 1.1)
    p.addRoundedRect(QRectF(9.8, 8.5, 4.4, 12.0), 1.1, 1.1)
    p.addRoundedRect(QRectF(16.4, 4.0, 4.4, 16.5), 1.1, 1.1)
    return p


_BUILDERS = {
    "play": lambda: play(),
    "pause": lambda: pause(),
    "prev": lambda: skip(reverse=True),
    "next": lambda: skip(reverse=False),
    "shuffle": lambda: shuffle(),
    "repeat": lambda: repeat_loop(with_one=False),
    "repeat_one": lambda: repeat_loop(with_one=True),
    "chevron_up": lambda: chevron("up"),
    "chevron_down": lambda: chevron("down"),
    "chevron_left": lambda: chevron("left"),
    "chevron_right": lambda: chevron("right"),
    "close": lambda: close_x(),
    "minus": lambda: minus(),
    "dots": lambda: dots(),
    "gear": lambda: gear(),
    "note": lambda: note(),
    "speaker": lambda: speaker(),
    "speaker_mute": lambda: speaker_mute(),
    "alert": lambda: alert(),
    "mic": lambda: mic(),
    "clock": lambda: clock(),
    "heart": lambda: heart(),
    "heart_outline": lambda: heart_outline(),
    "refresh": lambda: refresh(),
    "chart": lambda: chart(),
}

_cache = {}


def get_icon_path(name: str) -> QPainterPath:
    if name not in _cache:
        builder = _BUILDERS.get(name)
        if builder is None:
            raise KeyError(f"Ícono desconocido: {name}")
        path = builder()
        # Todas las piezas de un ícono se UNEN (relleno por devanado). Con el
        # relleno par-impar de Qt, donde dos trazos se cruzan quedaba un hueco
        # (centro de la X de silencio, punta del altavoz, muesca del corazón).
        path.setFillRule(Qt.FillRule.WindingFill)
        _cache[name] = path
    return _cache[name]
