"""Pantalla de carga: la escena 3D de sonido mientras arranca el programa, que
al terminar se TRANSFORMA en la ventana que usa el usuario (completa, compacta
o panel lateral).

Cómo se mantiene viva mientras carga: lo pesado del arranque es importar los
módulos de la interfaz (app_controller y todo lo que arrastra). Eso se hace en
un hilo (`import_with_splash`) mientras el hilo principal sigue repintando la
escena. Solo se importa en el hilo (se definen clases); los widgets se crean
después, en el hilo principal, como manda Qt. Si la importación falla en el
hilo, se repite en el principal para que el error salga como siempre.

La transformación (`morph_into`) cuesta poco: la escena se congela en una
imagen, se ocultan sus widgets y una sola animación de ~420 ms mueve y
redimensiona la tarjeta hasta el rectángulo de la ventana real mientras se
desvanece encima de ella (la ventana hace su propio fundido de entrada). Al
terminar, la pantalla de carga se destruye: no queda ningún temporizador.

Con «reducir movimiento» no hay animación: se cierra y ya.
"""
from __future__ import annotations

import importlib
import threading

from PyQt6.QtCore import QEasingCurve, QEventLoop, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from theme import FONT_BODY, Palette
import welcome_fx

SIZE = (300, 250)
MORPH_MS = 420
FADE_MS = 180


class Splash(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("YefriPlayer")
        self.resize(*SIZE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(2)
        self.stage = welcome_fx.SoundStage()
        self.stage.setMinimumHeight(120)
        lay.addWidget(self.stage, 1)
        self.title = QLabel("YefriPlayer")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title.setStyleSheet(f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; font-size: 17px; "
                                 "font-weight: 700; background: transparent;")
        lay.addWidget(self.title)
        self.caption = QLabel("Cargando…")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.caption.setStyleSheet(f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
                                   "font-size: 10.5px; background: transparent;")
        lay.addWidget(self.caption)

        self._radius = 18.0
        self._snapshot = None           # imagen congelada de la escena durante la transformación
        self._snap_opacity = 1.0
        self._done = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_morph)
        self._anim.finished.connect(self._finish)
        self._from = QRect()
        self._to = QRect()
        self._to_radius = 14.0
        self._fade_only = False
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def set_caption(self, text: str):
        self.caption.setText(text)

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, QColor(*Palette.BG_BASE, 250))
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)
        if self._snapshot is not None and self._snap_opacity > 0.01:
            # La escena congelada se encoge hacia el centro mientras se desvanece.
            p.setClipPath(path)
            p.setOpacity(self._snap_opacity)
            dpr = self._snapshot.devicePixelRatio() or 1.0
            sw, sh = self._snapshot.width() / dpr, self._snapshot.height() / dpr
            k = min(r.width() / max(1.0, sw), r.height() / max(1.0, sh), 1.0)
            w, h = sw * k, sh * k
            p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h),
                         self._snapshot, QRectF(0, 0, self._snapshot.width(), self._snapshot.height()))
        p.end()

    # ------------------------------------------------------- transformación
    def morph_into(self, target: QRect | None, radius: float = 14.0):
        """Se transforma en `target` (rectángulo de la ventana en pantalla) y
        desaparece. Sin destino (arranque minimizado), se encoge y se va."""
        if self._done or not self.isVisible():
            self._finish()
            return
        if welcome_fx.reduced_motion():
            self._finish()
            return
        self._snapshot = self.grab(self.stage.geometry())
        for w in (self.stage, self.title, self.caption):
            w.hide()                       # la escena deja de animarse (su reloj se para al ocultarse)
        self._from = self.geometry()
        if target is None or target.isEmpty():
            c = self._from.center()
            target = QRect(c.x() - 40, c.y() - 30, 80, 60)
            self._fade_only = True
        self._to = QRect(target)
        self._to_radius = radius
        self._anim.stop()
        self._anim.setDuration(MORPH_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.start()

    def dismiss(self):
        """Se va con un fundido corto (p. ej. antes de mostrar la bienvenida)."""
        if self._done or not self.isVisible() or welcome_fx.reduced_motion():
            self._finish()
            return
        self._from = self._to = self.geometry()
        self._fade_only = True
        self._anim.stop()
        self._anim.setDuration(FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _on_morph(self, value):
        t = float(value)
        f, to = self._from, self._to
        self.setGeometry(QRect(round(f.x() + (to.x() - f.x()) * t), round(f.y() + (to.y() - f.y()) * t),
                               round(f.width() + (to.width() - f.width()) * t),
                               round(f.height() + (to.height() - f.height()) * t)))
        self._radius = 18.0 + (self._to_radius - 18.0) * t
        self._snap_opacity = max(0.0, 1.0 - t * 1.8)
        # La tarjeta se desvanece en la segunda mitad, encima de la ventana real que aparece.
        self.setWindowOpacity(1.0 if t < 0.45 else max(0.0, 1.0 - (t - 0.45) / 0.55))
        self.update()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self._snapshot = None
        self.hide()
        self.deleteLater()

    @property
    def finished(self) -> bool:
        return self._done


def import_with_splash(module_name: str, splash: Splash | None, poll_ms: int = 15) -> None:
    """Importa `module_name` en un hilo mientras el hilo principal sigue
    atendiendo eventos (la escena de la pantalla de carga se sigue moviendo).
    Sin pantalla de carga, importa directamente. Si falla en el hilo, se repite
    aquí para que la excepción salga con su traceback normal."""
    if splash is None:
        importlib.import_module(module_name)
        return
    error: list[BaseException] = []

    def work():
        try:
            importlib.import_module(module_name)
        except BaseException as exc:          # noqa: BLE001 — se re-lanza en el hilo principal
            error.append(exc)

    thread = threading.Thread(target=work, name="yefriplayer-carga", daemon=True)
    thread.start()
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(poll_ms)
    timer.timeout.connect(lambda: None if thread.is_alive() else loop.quit())
    timer.start()
    if thread.is_alive():
        loop.exec()
    timer.stop()
    thread.join()
    if error:
        importlib.import_module(module_name)
