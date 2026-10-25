"""Genera el ícono de la aplicación (ventana y bandeja) dibujándolo por código."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QLinearGradient, QIcon, QTransform

from theme import Palette
import icons


def build_app_icon(size: int = 256) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, Palette.c(Palette.ACCENT_A))
    grad.setColorAt(1.0, Palette.c(Palette.ACCENT_B))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawEllipse(rect)

    play_path = icons.get_icon_path("play")
    icon_size = size * 0.38
    transform = QTransform()
    transform.translate(
        rect.center().x() - icon_size / 2 + size * 0.02,
        rect.center().y() - icon_size / 2,
    )
    transform.scale(icon_size / 24, icon_size / 24)
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawPath(transform.map(play_path))
    painter.end()

    return QIcon(pixmap)
