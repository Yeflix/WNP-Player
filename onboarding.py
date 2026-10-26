"""
Asistente de bienvenida: se muestra una única vez, la primera vez que se
ejecuta el programa (tanto si se corre con `python main.py` como si es el
`.exe` empaquetado — la condición es `AppConfig.onboarding_completed`, no
la forma de arrancar). Cuatro pasos:

1. Qué es y qué hace WNP Player.
2. Modos disponibles (completo / compacto), con una vista previa
   esquemática de cada uno, y elegir cuál abrir por defecto.
3. Cómo instalar y configurar la extensión del navegador WebNowPlaying.
4. Confirmación / resumen antes de empezar a usarlo, con la opción de
   iniciar el programa junto con Windows (activada por defecto).

No depende de ningún archivo de imagen externo (igual que el resto de la
app): el ícono se genera con `app_icon.build_app_icon()` y las vistas
previas de los modos se dibujan a mano con QPainter (`_ModePreview`).
"""
from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QUrl, pyqtSignal, pyqtProperty, QRectF, QPropertyAnimation,
    QEasingCurve,
)
from PyQt6.QtGui import QDesktopServices, QPainter, QColor, QLinearGradient
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsOpacityEffect, QCheckBox,
)

from theme import Palette, FONT_BODY
from dialogs import _DialogBase
from app_icon import build_app_icon

STEP_TITLES = [
    "Bienvenido",
    "Elige tu modo",
    "Conectar el navegador",
    "Todo listo",
]

CHROME_STORE_URL = "https://chromewebstore.google.com/search/WebNowPlaying"
FIREFOX_ADDONS_URL = "https://addons.mozilla.org/firefox/search/?q=WebNowPlaying"


def _label(text, size=11.5, color=Palette.TEXT_DIM, weight=400, wrap=True):
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    w = "700" if weight >= 700 else ("600" if weight >= 600 else "400")
    lbl.setStyleSheet(
        f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: {size}px; "
        f"font-weight: {w}; background: transparent;"
    )
    return lbl


DEVELOPER_NAME = "YefriDev"


class _DeveloperCard(QFrame):
    """Firma del desarrollador: círculo con degradado + nombre. Se usa en la
    bienvenida y en el cierre del asistente."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("devCard")
        a, b = Palette.ACCENT_A, Palette.ACCENT_B
        self.setStyleSheet(
            "QFrame#devCard { background: rgba(255,255,255,0.045); "
            "border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 14, 9)
        row.setSpacing(11)

        badge = QLabel(DEVELOPER_NAME[0])
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, "
            f"stop:0 rgb{a}, stop:1 rgb{b}); color: white; border-radius: 17px; "
            f"font-family:'{FONT_BODY}'; font-size: 15px; font-weight: 700;"
        )
        row.addWidget(badge)

        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(f"Desarrollado por <b>{DEVELOPER_NAME}</b>")
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; font-size: 12px; "
            f"background: transparent;"
        )
        col.addWidget(name)
        col.addWidget(_label("Proyecto de código abierto · GPL-3.0", size=10,
                             color=Palette.TEXT_FAINT, wrap=False))
        row.addLayout(col, 1)


class _ModePreview(QWidget):
    """Vista previa esquemática (no una captura real) de cómo se ve cada
    modo, dibujada con QPainter para no depender de imágenes externas."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind  # "main" | "mini" | "dock"
        self.setFixedSize(112, 82)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(*Palette.ACCENT_A, 40))
        grad.setColorAt(1.0, QColor(*Palette.ACCENT_B, 40))

        if self.kind == "main":
            # Tarjeta vertical: carátula arriba, un par de líneas de
            # texto, y una fila de puntos representando los controles.
            body = QRectF(20, 3, w - 40, h - 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*Palette.BG_PANEL, 235))
            painter.drawRoundedRect(body, 10, 10)

            cover = QRectF(body.center().x() - 15, body.top() + 7, 30, 30)
            painter.setBrush(grad)
            painter.drawRoundedRect(cover, 6, 6)

            painter.setBrush(QColor(*Palette.TEXT, 200))
            painter.drawRoundedRect(
                QRectF(body.center().x() - 19, body.top() + 41, 38, 4), 2, 2
            )
            painter.setBrush(QColor(*Palette.ACCENT_A, 180))
            painter.drawRoundedRect(
                QRectF(body.center().x() - 12, body.top() + 48, 24, 3), 1.5, 1.5
            )

            dot_y = body.bottom() - 9
            for i, dx in enumerate((-10, 0, 10)):
                painter.setBrush(
                    QColor(*Palette.ACCENT_A, 230) if i == 1
                    else QColor(*Palette.TEXT_DIM, 200)
                )
                painter.drawEllipse(QRectF(body.center().x() + dx - 3, dot_y - 3, 6, 6))

        elif self.kind == "mini":
            # Barra horizontal delgada: carátula pequeña a la izquierda +
            # una línea de texto, como la barra compacta real.
            body = QRectF(5, h / 2 - 13, w - 10, 26)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*Palette.BG_PANEL, 235))
            painter.drawRoundedRect(body, 13, 13)

            cover = QRectF(body.left() + 3, body.top() + 3, 20, 20)
            painter.setBrush(grad)
            painter.drawRoundedRect(cover, 5, 5)

            painter.setBrush(QColor(*Palette.TEXT, 200))
            painter.drawRoundedRect(
                QRectF(cover.right() + 8, body.top() + 8, body.width() - 52, 4), 2, 2
            )
            painter.setBrush(QColor(*Palette.ACCENT_A, 200))
            painter.drawEllipse(QRectF(body.right() - 13, body.top() + 9, 7, 7))

        else:  # "dock": una pestaña asomando del borde de una pantalla
            screen = QRectF(4, 4, w - 8, h - 8)
            painter.setPen(QColor(*Palette.TEXT_FAINT, 160))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = painter.pen()
            pen.setWidthF(1.4)
            painter.setPen(pen)
            painter.drawRoundedRect(screen, 6, 6)

            tab = QRectF(screen.right() - 9, screen.center().y() - 13, 18, 26)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawRoundedRect(tab, 6, 6)
            painter.setBrush(QColor(*Palette.ACCENT_A, 230))
            painter.drawEllipse(QRectF(tab.center().x() - 2.5, tab.center().y() - 2.5, 5, 5))

        painter.end()


class _ModeCard(QFrame):
    """Tarjeta seleccionable con la vista previa de un modo + su
    descripción. Actúa como un radio-button grande y visual.

    La selección se anima (borde y fondo interpolados con un
    QPropertyAnimation sobre `highlight`, 0..1) en vez de saltar de golpe
    con un cambio de stylesheet instantáneo — mismo lenguaje visual que ya
    usa el resto de la app (ver `_transition_progress` en main_window.py)."""

    clicked = pyqtSignal(str)

    def __init__(self, mode_key: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.mode_key = mode_key
        self._selected = False
        self._highlight = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(134)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setStyleSheet("QFrame { background: transparent; }")

        self._anim = QPropertyAnimation(self, b"highlight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(_ModePreview(mode_key))
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

        layout.addWidget(_label(title, size=12.5, color=Palette.TEXT, weight=700, wrap=False))
        layout.addWidget(_label(subtitle, size=10, color=Palette.TEXT_DIM))
        # Las tres tarjetas se igualan en altura; sin este resorte el sobrante se
        # repartía entre sus elementos y los títulos quedaban a distinta altura.
        layout.addStretch(1)

    def getHighlight(self) -> float:
        return self._highlight

    def setHighlight(self, value: float):
        self._highlight = value
        self.update()

    highlight = pyqtProperty(float, getHighlight, setHighlight)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from widgets import _lerp_color

        bg_off = QColor(255, 255, 255, 8)
        bg_on = QColor(*Palette.ACCENT_A, 20)
        border_off = QColor(255, 255, 255, 35)
        border_on = QColor(*Palette.ACCENT_A)

        bg = _lerp_color(bg_off, bg_on, self._highlight)
        border = _lerp_color(border_off, border_on, self._highlight)
        border_width = 1.5 + 0.5 * self._highlight

        rect = QRectF(self.rect()).adjusted(
            border_width / 2, border_width / 2, -border_width / 2, -border_width / 2
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QColor(border.red(), border.green(), border.blue(), border.alpha()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(border_width)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()
        super().paintEvent(event)

    def set_selected(self, selected: bool):
        if selected == self._selected:
            return
        self._selected = selected
        self._anim.stop()
        self._anim.setStartValue(self._highlight)
        self._anim.setEndValue(1.0 if selected else 0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.mode_key)


class _CurrentPageStack(QStackedWidget):
    """QStackedWidget por diseño reporta como sizeHint/minimumSizeHint el
    MÁXIMO entre TODAS sus páginas, no el de la página que se ve en ese
    momento — así que WelcomeWizard.adjustSize() (llamado en _show_page al
    cambiar de página) terminaba pidiendo una altura inconsistente con lo
    que esa página en particular necesitaba. Con las fuentes más grandes
    (ver theme.DEFAULT_FONT_SCALE) la diferencia entre páginas creció lo
    suficiente como para que Windows rechace directamente el cambio de
    geometría (warning "QWindowsWindow::setGeometry: Unable to set
    geometry..."). Esta subclase resuelve el problema de raíz: reporta el
    tamaño de la página ACTUAL nada más, que es lo que en realidad se
    quiere en un asistente paso a paso."""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class _StepRow(QWidget):
    """Un paso numerado dentro de las instrucciones de la extensión
    (evita depender de ningún widget de lista pesado para tres líneas)."""

    def __init__(self, number: int, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        badge = QLabel(str(number))
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: rgb{Palette.ACCENT_BUTTON}; color: white; border-radius: 10px; "
            f"font-family:'{FONT_BODY}'; font-size: 10.5px; font-weight: 700;"
        )
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(_label(text, size=11), 1)


class WelcomeWizard(_DialogBase):
    """Asistente de 4 pasos mostrado una sola vez, la primera ejecución.

    Uso:
        wizard = WelcomeWizard(port=1234)
        wizard.exec()
        modo = wizard.result_default_mode   # "main" | "mini" | "dock"
    """

    def __init__(self, port: int, parent=None, initial_mode: str = "main",
                 start_with_windows: bool = True):
        # Alto FIJO en vez de recalcularlo por página (adjustSize()) — con
        # QStackedWidget, Qt se resiste a ENCOGER la ventana entre páginas
        # aunque la página actual necesite menos (es la causa real del
        # warning "QWindowsWindow::setGeometry: Unable to set geometry..."
        # que aparecía en Windows). Más simple y robusto: una altura fija
        # que entra cómoda en la página más alta (medida con la letra
        # "grande" fija que usan todos los diálogos) — las páginas más
        # cortas quedan con un poco de aire abajo, sin ningún forcejeo de
        # geometría con el sistema operativo.
        super().__init__(parent, title="Bienvenido", width=468, height=530)
        self.port = port
        self.result_default_mode = initial_mode if initial_mode in ("main", "mini", "dock") else "main"
        self._initial_mode = self.result_default_mode
        self.result_start_with_windows = bool(start_with_windows)
        self._initial_start_with_windows = self.result_start_with_windows
        self._page_index = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(16)

        top_row = QHBoxLayout()
        self.step_label = _label("", size=10.5, color=Palette.TEXT_FAINT, wrap=False)
        top_row.addWidget(self.step_label)
        top_row.addStretch(1)
        skip_btn = QPushButton("Omitir")
        skip_btn.setObjectName("dialogButton")
        skip_btn.clicked.connect(self.accept)
        top_row.addWidget(skip_btn)
        outer.addLayout(top_row)

        self.stack = _CurrentPageStack()
        self.stack.addWidget(self._build_page_welcome())
        self.stack.addWidget(self._build_page_modes())
        self.stack.addWidget(self._build_page_extension())
        self.stack.addWidget(self._build_page_finish())
        outer.addWidget(self.stack, 1)

        # Transición animada entre páginas: fundido de salida de la página
        # actual, cambio de índice, fundido de entrada de la nueva — en vez
        # del salto instantáneo por defecto de QStackedWidget. 110ms de
        # salida (rápido, para no sentirse lento al avanzar) + 180ms de
        # entrada (un poco más suave, es lo que el usuario realmente mira).
        self._page_opacity = QGraphicsOpacityEffect(self.stack)
        self._page_opacity.setOpacity(1.0)
        self.stack.setGraphicsEffect(self._page_opacity)
        self._fade_anim = QPropertyAnimation(self._page_opacity, b"opacity", self)
        self._pending_page_index = 0

        nav_row = QHBoxLayout()
        self.back_btn = QPushButton("Atrás")
        self.back_btn.setObjectName("dialogButton")
        self.back_btn.clicked.connect(self._go_back)
        nav_row.addWidget(self.back_btn)
        nav_row.addStretch(1)
        self.next_btn = QPushButton("Siguiente")
        self.next_btn.setObjectName("dialogButtonAccent")
        self.next_btn.clicked.connect(self._go_next)
        nav_row.addWidget(self.next_btn)
        outer.addLayout(nav_row)

        self._refresh_nav()

    # ---------------------------------------------------------------- páginas
    def _build_page_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 2, 4, 4)
        layout.setSpacing(11)

        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_label = QLabel()
        icon_label.setPixmap(build_app_icon(96).pixmap(64, 64))
        icon_row.addWidget(icon_label)
        icon_row.addStretch(1)
        layout.addLayout(icon_row)

        title = _label("Bienvenido a WNP Player", size=17, color=Palette.TEXT, weight=700, wrap=False)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        body = _label(
            "Controla desde un solo lugar la música que suena en tu navegador "
            "(YouTube, Spotify, SoundCloud, Deezer, Apple Music, Tidal…) y en "
            "las apps de escritorio de Windows, como Spotify.",
            size=11.5,
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(body)

        for line in (
            "Tres modos: completo, barra compacta y panel lateral.",
            "Letras, historial, estadísticas y teclas multimedia globales.",
            "Colores que se adaptan a la carátula de cada canción.",
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            bullet = _label("•", size=12, color=Palette.ACCENT_A, wrap=False)
            row.addWidget(bullet, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(_label(line, size=10.5), 1)
            layout.addLayout(row)

        layout.addStretch(1)
        layout.addWidget(_DeveloperCard())
        return page

    def _build_page_modes(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        layout.addWidget(_label(
            "¿Cuál quieres que se abra al iniciar? Puedes cambiar de uno a "
            "otro cuando quieras desde el menú del reproductor o el ícono "
            "de la bandeja.",
            size=11,
        ))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        cards_row.addStretch(1)
        self.main_card = _ModeCard(
            "main", "Completo",
            "Carátula grande, progreso y controles."
        )
        self.mini_card = _ModeCard(
            "mini", "Compacto",
            "Barra flotante minimalista."
        )
        self.dock_card = _ModeCard(
            "dock", "Panel lateral",
            "Pestaña en el borde de la pantalla."
        )
        self.main_card.clicked.connect(self._on_mode_card_clicked)
        self.mini_card.clicked.connect(self._on_mode_card_clicked)
        self.dock_card.clicked.connect(self._on_mode_card_clicked)
        cards_row.addWidget(self.main_card)
        cards_row.addWidget(self.mini_card)
        cards_row.addWidget(self.dock_card)
        cards_row.addStretch(1)
        layout.addLayout(cards_row)
        layout.addStretch(1)

        self._set_selected_mode(self._initial_mode)
        return page

    def _build_page_extension(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        layout.addWidget(_label(
            "Para leer la música del navegador necesitas la extensión gratuita "
            "\"WebNowPlaying\", que le envía a WNP Player lo que estás "
            "escuchando. Las apps de escritorio, como Spotify, no la necesitan.",
            size=11,
        ))

        for i, text in enumerate((
            "Instala la extensión “WebNowPlaying” en tu navegador "
            "(Chrome, Edge, Brave, Opera o Firefox).",
            "Abre las opciones de la extensión → “Add custom adapter / "
            "Agregar adaptador personalizado”.",
            f"Usa el puerto {self.port}, el mismo que usa este programa "
            "(puedes cambiarlo después en Configuración).",
        ), start=1):
            layout.addWidget(_StepRow(i, text))

        links_row = QHBoxLayout()
        links_row.setSpacing(10)
        chrome_btn = QPushButton("Abrir Chrome Web Store")
        chrome_btn.setObjectName("dialogButton")
        chrome_btn.clicked.connect(lambda: self._open_store_link(CHROME_STORE_URL))
        links_row.addWidget(chrome_btn)
        firefox_btn = QPushButton("Abrir Firefox Add-ons")
        firefox_btn.setObjectName("dialogButton")
        firefox_btn.clicked.connect(lambda: self._open_store_link(FIREFOX_ADDONS_URL))
        links_row.addWidget(firefox_btn)
        layout.addLayout(links_row)

        self.extension_link_status = _label("", size=9.5, color=Palette.ERROR)
        self.extension_link_status.setVisible(False)
        layout.addWidget(self.extension_link_status)

        layout.addWidget(_label(
            "Si el sitio es compatible, la música aparece en el reproductor "
            "en cuanto guardes el adaptador. No hace falta reiniciar nada.",
            size=10, color=Palette.TEXT_FAINT,
        ))
        layout.addStretch(1)
        return page

    def _build_page_finish(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(12)

        title = _label("Todo listo", size=16, color=Palette.TEXT, weight=700, wrap=False)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.finish_summary = _label("", size=11.5)
        self.finish_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.finish_summary)

        self.start_with_windows_check = QCheckBox("Iniciar WNP Player junto con Windows")
        self.start_with_windows_check.setChecked(self.result_start_with_windows)
        self.start_with_windows_check.toggled.connect(self._on_start_with_windows_toggled)
        layout.addWidget(self.start_with_windows_check)
        layout.addWidget(_label(
            "Puedes cambiarlo cuando quieras en Configuración.",
            size=10, color=Palette.TEXT_FAINT,
        ))

        layout.addWidget(_label(
            "Este asistente no vuelve a aparecer solo. Para repasarlo: clic "
            "derecho en el reproductor → \u201cVer bienvenida de nuevo...\u201d.",
            size=10, color=Palette.TEXT_FAINT,
        ))
        layout.addStretch(1)
        layout.addWidget(_DeveloperCard())
        return page

    def _on_start_with_windows_toggled(self, checked: bool):
        self.result_start_with_windows = bool(checked)

    # ------------------------------------------------------------- navegación
    def _open_store_link(self, url: str):
        """QDesktopServices.openUrl() devuelve un bool y antes se
        ignoraba: si fallaba (sin navegador/manejador de enlaces
        configurado, por ejemplo en una instalación mínima o portable),
        el clic no hacía absolutamente nada, sin ningún aviso. Ahora, si
        falla, se muestra el link como texto para copiarlo a mano."""
        opened = QDesktopServices.openUrl(QUrl(url))
        if opened:
            self.extension_link_status.setVisible(False)
            return
        self.extension_link_status.setText(
            f"No se pudo abrir el navegador automáticamente. Copia este enlace: {url}"
        )
        self.extension_link_status.setVisible(True)

    def _on_mode_card_clicked(self, mode_key: str):
        self._set_selected_mode(mode_key)

    def _set_selected_mode(self, mode_key: str):
        self.result_default_mode = mode_key
        self.main_card.set_selected(mode_key == "main")
        self.mini_card.set_selected(mode_key == "mini")
        self.dock_card.set_selected(mode_key == "dock")

    def _go_next(self):
        if self._page_index >= self.stack.count() - 1:
            self.accept()
            return
        self._page_index += 1
        self._show_page(self._page_index)

    def _go_back(self):
        if self._page_index == 0:
            return
        self._page_index -= 1
        self._show_page(self._page_index)

    def _show_page(self, index: int):
        if index == self.stack.count() - 1:  # página final: arma el resumen
            mode_text = {
                "main": "Reproductor completo",
                "mini": "Modo compacto",
                "dock": "Panel lateral",
            }.get(self.result_default_mode, "Reproductor completo")
            self.finish_summary.setText(
                f"WNP Player se abrirá en modo \"{mode_text}\".\n"
                "Puedes cambiarlo cuando quieras."
            )
        self._pending_page_index = index
        self._animate_page_change()
        self._refresh_nav()

    def _animate_page_change(self):
        self._fade_anim.stop()
        try:
            self._fade_anim.finished.disconnect()
        except TypeError:
            pass  # no había ninguna conexión previa, nada que desconectar
        self._fade_anim.setDuration(110)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.setStartValue(self._page_opacity.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_out_finished)
        self._fade_anim.start()

    def _on_fade_out_finished(self):
        self.stack.setCurrentIndex(self._pending_page_index)
        try:
            self._fade_anim.finished.disconnect()
        except TypeError:
            pass
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _refresh_nav(self):
        self.step_label.setText(
            f"Paso {self._page_index + 1} de {self.stack.count()} · "
            f"{STEP_TITLES[self._page_index]}"
        )
        self.back_btn.setEnabled(self._page_index > 0)
        is_last = self._page_index == self.stack.count() - 1
        self.next_btn.setText("Empezar a usar WNP Player" if is_last else "Siguiente")
