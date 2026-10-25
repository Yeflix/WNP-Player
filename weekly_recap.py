"""
Recordatorio semanal: un aviso chico, no modal, que aparece solo (sin que
el usuario lo pida) una vez por semana como mucho — ver
stats.should_show_weekly_recap(), consultado desde app_controller.py.
Muestra 2-4 datos breves en secuencia con un fundido cruzado y se cierra
solo; también tiene una X por si se quiere cerrar antes.

No es una QDialog a propósito: no debe bloquear la app ni robarle el
foco de golpe, es un aviso de esquina, como una notificación con más
onda visual.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QPainterPath, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect,
)

from theme import Palette, FONT_BODY
from widgets import IconButton

SLIDE_MS = 2600
FADE_MS = 240
ENTRANCE_MS = 320


def _build_slides(summary: dict) -> list[str]:
    slides = ["🎧  Tu semana en música"]

    plays = summary.get("plays", 0)
    slides.append(
        f"Escuchaste <b>{plays}</b> {'canción' if plays == 1 else 'canciones'} esta semana."
    )

    total_text = summary.get("total_duration_text", "0 min")
    slides.append(f"Eso son <b>{total_text}</b> de música.")

    most_played = summary.get("most_played")
    if most_played:
        title, artist, count = most_played
        if count > 1:
            slides.append(
                f"Repetiste más <b>“{title}”</b>{f' de {artist}' if artist else ''} "
                f"— {count} veces."
            )

    top_artists = summary.get("top_artists") or []
    if top_artists:
        artist_name, _ = top_artists[0]
        slides.append(f"Tu artista de la semana: <b>{artist_name}</b>.")

    return slides


class WeeklyRecapToast(QWidget):
    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.Tool)  # sin entrada en la barra de tareas
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(280, 118)
        self.setWindowOpacity(0.0)

        self._slides = _build_slides(summary)
        self._index = 0
        self._closing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        close_btn = IconButton("close", size=20, icon_scale=0.4, bg=None)
        close_btn.clicked.connect(self._start_close)
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        self.text_label = QLabel(self._slides[0])
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.text_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 12.5px; background: transparent;"
        )
        layout.addWidget(self.text_label, 1)

        self._label_opacity = QGraphicsOpacityEffect(self.text_label)
        self._label_opacity.setOpacity(1.0)
        self.text_label.setGraphicsEffect(self._label_opacity)

        self._fade_anim = QPropertyAnimation(self._label_opacity, b"opacity", self)
        self._fade_anim.setDuration(FADE_MS)

        self._slide_timer = QTimer(self)
        self._slide_timer.setInterval(SLIDE_MS)
        self._slide_timer.timeout.connect(self._advance_slide)

        self._window_anim = QPropertyAnimation(self, b"windowOpacity", self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()),
                             float(rect.height()), 16, 16)
        painter.fillPath(path, QColor(*Palette.BG_BASE, 245))
        painter.setPen(QColor(*Palette.ACCENT_A, 140))
        painter.drawPath(path)

    def showEvent(self, event):
        super().showEvent(event)
        self._window_anim.stop()
        self._window_anim.setDuration(ENTRANCE_MS)
        self._window_anim.setStartValue(0.0)
        self._window_anim.setEndValue(1.0)
        self._window_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._window_anim.start()
        if len(self._slides) > 1:
            self._slide_timer.start()

    def _advance_slide(self):
        if self._closing:
            return
        self._fade_anim.stop()
        try:
            self._fade_anim.finished.disconnect()
        except TypeError:
            pass
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_out_finished)
        self._fade_anim.start()

    def _on_fade_out_finished(self):
        try:
            self._fade_anim.finished.disconnect(self._on_fade_out_finished)
        except TypeError:
            pass
        self._index += 1
        if self._index >= len(self._slides):
            self._start_close()
            return
        self.text_label.setText(self._slides[self._index])
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _start_close(self):
        if self._closing:
            return
        self._closing = True
        self._slide_timer.stop()
        self._window_anim.stop()
        self._window_anim.setDuration(FADE_MS)
        self._window_anim.setStartValue(self.windowOpacity())
        self._window_anim.setEndValue(0.0)
        self._window_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        try:
            self._window_anim.finished.disconnect()
        except TypeError:
            pass
        self._window_anim.finished.connect(self.close)
        self._window_anim.start()

    @staticmethod
    def position_bottom_right(widget: WeeklyRecapToast, margin: int = 24):
        from PyQt6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - widget.width() - margin
        y = geo.bottom() - widget.height() - margin
        widget.move(x, y)
