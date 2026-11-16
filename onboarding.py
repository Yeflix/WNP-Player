"""
Asistente de bienvenida (1.5.3: simple y animado).

Se muestra la primera vez que se ejecuta el programa, tras una instalación
nueva (`--bienvenida`, lo pide el instalador) y una vez más cuando cambia su
contenido (`WELCOME_REVISION`). La condición es la configuración guardada, no
la forma de arrancar: igual con `python main.py` que con el `.exe`.

Pensado para no abrumar: TRES pasos cortos con una escena 3D de sonido arriba
(welcome_fx.SoundStage: vinilo girando, ecualizador en anillo que late, ondas
y notas):

1. Qué es, en una frase (controla lo que ya suena; no reproduce audio).
2. Conectar la música (las apps de escritorio solas; el navegador con la
   extensión WebNowPlaying, explicada en tres pasos). Con el backend en marcha
   comprueba EN VIVO si la extensión está conectada y si ya llega lo que suena
   (`extension_status`), y la escena lo celebra cuando funciona.
3. Listo: las teclas rápidas y «Iniciar con Windows».

El resto de preferencias se aplican con los valores recomendados
(config.RECOMMENDED_PREFS) y se cambian en Configuración. «Omitir» acepta lo
mismo. Todo se aplica en AppController._apply_welcome_result.

Tamaño: se calcula con la pantalla disponible (cabe en portátiles con escala
alta); la escena 3D se queda con el alto que sobre.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from theme import Palette, FONT_BODY, FONT_MONO
from dialogs import _DialogBase
import welcome_fx

# Súbelo cuando cambie lo que explica el asistente: los usuarios que ya lo
# vieron lo verán una vez más (AppController.start).
WELCOME_REVISION = 4

STEP_TITLES = [
    "Tu música, en un solo lugar",
    "Conecta tu música",
    "¡Listo para sonar!",
]

CHROME_STORE_URL = "https://chromewebstore.google.com/search/WebNowPlaying"
FIREFOX_ADDONS_URL = "https://addons.mozilla.org/firefox/search/?q=WebNowPlaying"

HOTKEY_ACTIONS = (("play_pause", "Reproducir / pausar"), ("next", "Siguiente"), ("previous", "Anterior"))

# Tamaño deseado y mínimo del asistente (se ajusta a la pantalla disponible).
WIDTH, HEIGHT = 540, 600
MIN_WIDTH, MIN_HEIGHT = 360, 420


def _label(text, size=11.5, color=Palette.TEXT_DIM, weight=400, wrap=True, center=False):
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    w = "700" if weight >= 700 else ("600" if weight >= 600 else "400")
    lbl.setStyleSheet(
        f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: {size}px; "
        f"font-weight: {w}; background: transparent;"
    )
    if center:
        lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    return lbl


def _chip(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; font-size: 10.5px; "
        f"background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); "
        f"border-radius: 10px; padding: 3px 10px;"
    )
    return lbl


def _keycap_style(pressed: bool) -> str:
    """Tecla de teclado; «pulsada» se hunde (borde inferior fino) y se ilumina."""
    if pressed:
        return (f"color: white; font-family:'{FONT_MONO}'; font-size: 10.5px; font-weight: 700; "
                f"background: rgba{(*Palette.ACCENT_A, 150)}; border: 1px solid rgb{Palette.ACCENT_A}; "
                f"border-bottom: 1px solid rgb{Palette.ACCENT_A}; border-radius: 5px; "
                f"padding: 3px 7px 2px 7px; margin-top: 1px;")
    return (f"color: rgb{Palette.TEXT}; font-family:'{FONT_MONO}'; font-size: 10.5px; font-weight: 600; "
            f"background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18); "
            f"border-bottom: 3px solid rgba(255,255,255,0.22); border-radius: 5px; padding: 2px 7px;")


def _keycap(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(_keycap_style(False))
    return lbl


def _combo_keys(combo: str) -> list[str]:
    names = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win", "space": "Espacio"}
    return [names.get(p, p.upper() if len(p) <= 3 else p.capitalize()) for p in (combo or "").split("+") if p]


YOUTUBE_TEST_URL = "https://www.youtube.com"

# Colores del indicador de la extensión por estado.
_STATUS_COLORS = {
    "error": Palette.ERROR, "waiting": (255, 190, 80), "connected": Palette.ACCENT_B,
    "ok": (80, 210, 120), "desktop": (80, 210, 120),
}


def extension_status(info: dict | None) -> tuple[str, str]:
    """(tipo, texto) del indicador «¿funciona la extensión?» a partir de
    WNPBackend.connection_info(). Tipos: error | waiting | connected | ok |
    desktop. Función pura (se prueba sin Qt)."""
    if not info:
        return "waiting", "La comprobación se activa con YefriPlayer abierto."
    port = info.get("port", "")
    if not info.get("running"):
        return "error", (f"YefriPlayer no está escuchando en el puerto {port} (¿lo usa otro programa?). "
                         "Cámbialo luego en Configuración → General.")
    title, artist = info.get("title") or "", info.get("artist") or ""
    song = f"«{title}»" + (f" — {artist}" if artist else "")
    if info.get("browsers", 0) > 0:
        if info.get("has_media"):
            return "ok", f"¡Funciona! Sonando {song}."
        return "connected", "Extensión conectada ✓  Pon algo a sonar en el navegador para terminar la prueba."
    if info.get("has_media"):
        player = info.get("player") or "Una app de escritorio"
        return "desktop", f"{player} detectado ✓ {song}. El navegador aún no está conectado."
    return "waiting", f"Esperando a la extensión en el puerto {port}…"


def _step(number: int, text: str) -> QWidget:
    """Paso numerado (círculo con el número + texto que se parte en líneas)."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    badge = QLabel(str(number))
    badge.setFixedSize(18, 18)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(
        f"background: rgb{Palette.ACCENT_BUTTON}; color: white; border-radius: 9px; "
        f"font-family:'{FONT_BODY}'; font-size: 10px; font-weight: 700;")
    lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
    lay.addWidget(_label(text, size=11, color=Palette.TEXT), 1)
    return row


class _StatusPill(QFrame):
    """Indicador en vivo de la conexión con la extensión (punto + texto)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("wnpStatus")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        self.text = _label("", size=10.5, color=Palette.TEXT)
        lay.addWidget(self.text, 1)
        self.kind = ""
        self._blink = False
        self.set_status("waiting", "")

    def set_status(self, kind: str, text: str, blink: bool = False):
        self.kind = kind
        r, g, b = _STATUS_COLORS.get(kind, Palette.TEXT_DIM)
        alpha = 90 if (blink and kind == "waiting") else 255
        self.dot.setStyleSheet(f"background: rgba({r},{g},{b},{alpha}); border-radius: 5px;")
        self.setStyleSheet(
            f"QFrame#wnpStatus {{ background: rgba({r},{g},{b},22); "
            f"border: 1px solid rgba({r},{g},{b},70); border-radius: 10px; }}")
        if text:
            self.text.setText(text)


def fit_size(avail_w: int, avail_h: int) -> tuple[int, int]:
    """Tamaño del asistente para una pantalla disponible de avail_w×avail_h
    (píxeles lógicos). Función pura: se prueba sin Qt."""
    w = min(WIDTH, max(MIN_WIDTH, int(avail_w * 0.92)))
    h = min(HEIGHT, max(MIN_HEIGHT, int(avail_h * 0.90)))
    return min(w, max(300, avail_w - 16)), min(h, max(320, avail_h - 16))


class _CurrentPageStack(QStackedWidget):
    """Informa del tamaño de la página VISIBLE (no del máximo de todas): así la
    escena 3D se queda con todo el alto que sobre en cada paso."""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class WelcomeWizard(_DialogBase):
    """Asistente de bienvenida en 3 pasos.

    Uso:
        wizard = WelcomeWizard(port=1234, prefs={...}, hotkeys={...})
        wizard.exec()
        wizard.result_prefs        # dict con las claves de config.RECOMMENDED_PREFS
        wizard.result_hotkeys      # {"play_pause": "ctrl+shift+space", ...}
        wizard.result_default_mode # el modo con el que abrirá (no se pregunta aquí)
    """

    def __init__(self, port: int, parent=None, initial_mode: str = "main",
                 start_with_windows: bool = True, prefs: dict | None = None,
                 hotkeys: dict | None = None, backend=None):
        """`backend`: el WNPBackend en marcha; con él, el paso «Conecta tu música»
        comprueba en vivo si la extensión funciona (sin él, solo explica)."""
        self._backend = backend
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            width, height = fit_size(geo.width(), geo.height())
        else:
            width, height = WIDTH, HEIGHT
        super().__init__(parent, title="Bienvenido", width=width, height=height)
        from config import RECOMMENDED_PREFS, DEFAULT_HOTKEYS
        self.port = port
        self.result_default_mode = initial_mode if initial_mode in ("main", "mini", "dock") else "main"
        self.result_prefs = dict(RECOMMENDED_PREFS)
        if prefs:
            self.result_prefs.update({k: bool(v) for k, v in prefs.items() if k in RECOMMENDED_PREFS})
        if prefs is None or "start_with_windows" not in prefs:
            self.result_prefs["start_with_windows"] = bool(start_with_windows)
        self.result_start_with_windows = self.result_prefs["start_with_windows"]
        self.result_hotkeys = dict(DEFAULT_HOTKEYS)
        if hotkeys:
            self.result_hotkeys.update({k: v for k, v in hotkeys.items() if k in DEFAULT_HOTKEYS and v})
        self._page_index = 0
        compact = height < 520                       # pantallas bajas: menos aire y textos más cortos
        self._compact = compact
        self._narrow = width < 460                   # estrecho: plataformas en texto, no en chips

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 16, 22, 18)
        outer.setSpacing(8 if compact else 12)

        top = QHBoxLayout()
        self.dots = welcome_fx.ProgressDots(len(STEP_TITLES))
        top.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        skip_btn = QPushButton("Omitir")
        skip_btn.setObjectName("dialogButton")
        skip_btn.setToolTip("Cierra la bienvenida con los valores recomendados (se cambian en Configuración).")
        skip_btn.clicked.connect(self.accept)
        top.addWidget(skip_btn)
        outer.addLayout(top)

        # Escena 3D: se queda con el alto sobrante (factor de estiramiento).
        self.stage = welcome_fx.SoundStage()
        self.stage.setMinimumHeight(80 if compact else 110)
        outer.addWidget(self.stage, 1)

        self.stack = _CurrentPageStack()
        self.stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.stack.addWidget(self._build_page_intro())
        self.stack.addWidget(self._build_page_connect())
        self.stack.addWidget(self._build_page_ready())
        outer.addWidget(self.stack, 0)

        nav = QHBoxLayout()
        self.back_btn = QPushButton("Atrás")
        self.back_btn.setObjectName("dialogButton")
        self.back_btn.clicked.connect(self._go_back)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        self.next_btn = QPushButton("Siguiente")
        self.next_btn.setObjectName("dialogButtonAccent")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._go_next)
        nav.addWidget(self.next_btn)
        outer.addLayout(nav)

        # Efectos: giro 3D entre pasos, confeti al final y teclas que se pulsan solas.
        self._page_opacity = QGraphicsOpacityEffect(self.stack)
        self._page_opacity.setOpacity(1.0)
        self._page_opacity.setEnabled(False)          # solo durante el giro
        self.stack.setGraphicsEffect(self._page_opacity)
        self._pending_page_index = 0
        self._flip = welcome_fx.PageFlip(self)
        self._flip.finished.connect(self._on_flip_finished)
        self._confetti = welcome_fx.Confetti(self)
        self._key_step = 0
        self._key_timer = QTimer(self)
        self._key_timer.setInterval(650)
        self._key_timer.timeout.connect(self._press_next_key)

        self._refresh_nav()

    # ---------------------------------------------------------------- páginas
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6 if self._compact else 8)
        layout.addWidget(_label(title, size=17 if self._compact else 20, color=Palette.TEXT,
                                weight=700, center=True))
        layout.addWidget(_label(subtitle, size=11.5 if self._compact else 12, center=True))
        return page, layout

    def _build_page_intro(self) -> QWidget:
        page, layout = self._page(
            STEP_TITLES[0],
            "Controla desde aquí lo que ya suena en tu navegador y en tus apps. "
            "No reproduce audio: lo muestra y lo maneja.")
        names = ("YouTube", "Spotify", "SoundCloud", "y más")
        if self._narrow:
            # En estrecho, una línea de texto que se parte sola (los chips no se parten).
            layout.addWidget(_label(" · ".join(names), size=10.5, color=Palette.TEXT, center=True))
            return page
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        for name in names:
            row.addWidget(_chip(name))
        row.addStretch(1)
        layout.addSpacing(2)
        layout.addLayout(row)
        return page

    def _build_page_connect(self) -> QWidget:
        page, layout = self._page(
            STEP_TITLES[1],
            "Las apps de escritorio se detectan solas. Para el navegador, la extensión "
            "WebNowPlaying:" if self._compact else
            "Spotify y las apps de escritorio se detectan solas. Para la música del "
            "navegador, la extensión gratuita WebNowPlaying:")
        if self._compact:
            layout.addWidget(_label(
                f"Instálala → en sus opciones pulsa «Add custom adapter» → puerto {self.port} → guardar.",
                size=10.5, color=Palette.TEXT, center=True))
        else:
            steps = QWidget()
            steps.setMaximumWidth(420)
            steps_layout = QVBoxLayout(steps)
            steps_layout.setContentsMargins(0, 2, 0, 2)
            steps_layout.setSpacing(5)
            steps_layout.addWidget(_step(1, "Instálala en tu navegador con uno de estos botones."))
            steps_layout.addWidget(_step(2, "Abre sus opciones (clic en su icono) y pulsa «Add custom "
                                            "adapter» / «Adaptador personalizado»."))
            steps_layout.addWidget(_step(3, f"Escribe el puerto {self.port}, déjalo activado y guarda."))
            centered = QHBoxLayout()
            centered.addStretch(1)
            centered.addWidget(steps, 20)
            centered.addStretch(1)
            layout.addLayout(centered)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        chrome_btn = QPushButton("Chrome" if self._narrow else "Chrome / Edge")
        chrome_btn.setObjectName("dialogButton")
        chrome_btn.setToolTip("Abre la Chrome Web Store (sirve también para Edge, Brave y Opera)")
        chrome_btn.clicked.connect(lambda: self._open_store_link(CHROME_STORE_URL))
        row.addWidget(chrome_btn)
        firefox_btn = QPushButton("Firefox")
        firefox_btn.setObjectName("dialogButton")
        firefox_btn.clicked.connect(lambda: self._open_store_link(FIREFOX_ADDONS_URL))
        row.addWidget(firefox_btn)
        self.test_btn = QPushButton("Probar" if self._narrow else "Probar con YouTube")
        self.test_btn.setObjectName("dialogButton")
        self.test_btn.setToolTip("Abre YouTube: pon cualquier vídeo y mira el indicador de abajo")
        self.test_btn.clicked.connect(lambda: self._open_store_link(YOUTUBE_TEST_URL))
        self.test_btn.setVisible(self._backend is not None)
        row.addWidget(self.test_btn)
        row.addStretch(1)
        layout.addLayout(row)

        # Comprobación en vivo: se consulta al backend mientras se ve este paso.
        self.status_pill = _StatusPill()
        self.status_pill.setVisible(self._backend is not None)
        status_row = QHBoxLayout()
        status_row.addStretch(1)
        status_row.addWidget(self.status_pill, 20)
        status_row.addStretch(1)
        layout.addLayout(status_row)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status)
        self._celebrated = False
        self.extension_link_status = _label("", size=9.5, color=Palette.ERROR, center=True)
        self.extension_link_status.setVisible(False)
        layout.addWidget(self.extension_link_status)
        return page

    def _refresh_status(self):
        info = None
        if self._backend is not None:
            try:
                info = self._backend.connection_info()
            except Exception:
                info = None
        kind, text = extension_status(info)
        self._status_blink = not getattr(self, "_status_blink", False)
        self.status_pill.set_status(kind, text, blink=self._status_blink)
        if kind == "ok" and not self._celebrated:
            # ¡Funciona!: la escena lo celebra un momento.
            self._celebrated = True
            self.stage.set_energy(1.8)
            QTimer.singleShot(2500, self._calm_stage)

    def _calm_stage(self):
        if self.stack.currentIndex() != self.stack.count() - 1:
            self.stage.set_energy(1.0)

    def _build_page_ready(self) -> QWidget:
        page, layout = self._page(STEP_TITLES[2], "Controla la música desde cualquier programa:")
        card = QFrame()
        card.setObjectName("welcomeKeys")
        card.setStyleSheet(
            "QFrame#welcomeKeys { background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }")
        card.setMaximumWidth(340)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 6 if self._compact else 8, 12, 6 if self._compact else 8)
        card_layout.setSpacing(4 if self._compact else 6)
        self.hotkey_rows = {}
        self._keycaps: list[list[QLabel]] = []
        for action, title in HOTKEY_ACTIONS:
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(_label(title, size=11, color=Palette.TEXT, weight=600), 1)
            keys = _combo_keys(self.result_hotkeys.get(action, ""))
            caps = []
            for j, key in enumerate(keys):
                if j:
                    row.addWidget(_label("+", size=10, color=Palette.TEXT_FAINT, wrap=False))
                cap = _keycap(key)
                caps.append(cap)
                row.addWidget(cap)
            self._keycaps.append(caps)
            self.hotkey_rows[action] = keys
            card_layout.addLayout(row)
        card_row = QHBoxLayout()
        card_row.addStretch(1)
        card_row.addWidget(card, 10)
        card_row.addStretch(1)
        layout.addLayout(card_row)

        check_row = QHBoxLayout()
        check_row.addStretch(1)
        self.start_with_windows_check = QCheckBox("Iniciar con Windows")
        self.start_with_windows_check.setChecked(self.result_start_with_windows)
        self.start_with_windows_check.toggled.connect(self._on_start_with_windows_toggled)
        check_row.addWidget(self.start_with_windows_check)
        check_row.addStretch(1)
        layout.addLayout(check_row)
        if not self._compact:
            layout.addWidget(_label("Todo lo demás está listo con los valores recomendados; "
                                    "se cambia cuando quieras en Configuración.",
                                    size=9.5, color=Palette.TEXT_FAINT, center=True))
        return page

    def _on_start_with_windows_toggled(self, checked: bool):
        self.result_start_with_windows = bool(checked)
        self.result_prefs["start_with_windows"] = bool(checked)

    def summary_text(self) -> str:
        keys = " · ".join(f"{t}: {'+'.join(_combo_keys(self.result_hotkeys.get(a, '')))}"
                          for a, t in HOTKEY_ACTIONS)
        start = "sí" if self.result_prefs.get("start_with_windows") else "no"
        return f"Teclas rápidas: {keys}.\nIniciar con Windows: {start}."

    # ------------------------------------------------------------------ fondo
    def paintEvent(self, event):
        super().paintEvent(event)                     # fondo y borde de _DialogBase
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        glow = QRadialGradient(QPointF(r.center().x(), r.top() + r.height() * 0.3), r.width() * 0.7)
        glow.setColorAt(0.0, QColor(*Palette.ACCENT_B, 26))
        glow.setColorAt(1.0, QColor(*Palette.ACCENT_B, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawRoundedRect(r, 16, 16)
        p.end()

    # ------------------------------------------------------------------ efectos
    def showEvent(self, event):
        super().showEvent(event)
        self._sync_page_effects()

    def hideEvent(self, event):
        self._key_timer.stop()
        self._status_timer.stop()
        super().hideEvent(event)

    def _sync_page_effects(self):
        last = self.stack.count() - 1
        on_keys = self.isVisible() and self.stack.currentIndex() == last and not welcome_fx.reduced_motion()
        if on_keys and not self._key_timer.isActive():
            self._key_step = 0
            self._key_timer.start()
        elif not on_keys:
            self._key_timer.stop()
            for caps in self._keycaps:
                for cap in caps:
                    cap.setStyleSheet(_keycap_style(False))
        on_connect = self.isVisible() and self.stack.currentIndex() == 1 and self._backend is not None
        if on_connect and not self._status_timer.isActive():
            self._refresh_status()
            self._status_timer.start()
        elif not on_connect:
            self._status_timer.stop()
        # La escena «se anima» más en el paso final.
        if self.stack.currentIndex() == last:
            self.stage.set_energy(1.6)
        elif not (self.stack.currentIndex() == 1 and self._celebrated and self.status_pill.kind == "ok"):
            self.stage.set_energy(1.0)

    def _press_next_key(self):
        rows = self._keycaps
        if not rows:
            return
        active = self._key_step % (len(rows) + 1)       # un hueco sin pulsar entre vueltas
        for i, caps in enumerate(rows):
            for cap in caps:
                cap.setStyleSheet(_keycap_style(i == active))
        self._key_step += 1

    def _on_flip_finished(self):
        self._page_opacity.setOpacity(1.0)
        self._page_opacity.setEnabled(False)
        self._after_page_shown()

    def _after_page_shown(self):
        self._sync_page_effects()
        if self.stack.currentIndex() == self.stack.count() - 1:
            self._confetti.burst(origin_y=0.30)

    # ------------------------------------------------------------- navegación
    def _open_store_link(self, url: str):
        """Si no se puede abrir el navegador, se muestra el enlace para copiarlo."""
        if QDesktopServices.openUrl(QUrl(url)):
            self.extension_link_status.setVisible(False)
            return
        self.extension_link_status.setText(f"No se pudo abrir el navegador. Copia este enlace: {url}")
        self.extension_link_status.setVisible(True)

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
        old_index = self.stack.currentIndex()
        self._pending_page_index = index
        self._refresh_nav()
        if index == old_index or not self.isVisible() or welcome_fx.reduced_motion():
            self.stack.setCurrentIndex(index)
            self._after_page_shown()
            return
        # Giro de tarjeta en 3D: foto de la página actual y de la nueva; la capa
        # PageFlip las gira y la página real queda invisible hasta que termina.
        old_pm = self.stack.currentWidget().grab()
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if page.layout() is not None:
            page.layout().activate()
        self.layout().activate()                      # la página nueva puede medir distinto
        new_pm = page.grab()
        self._page_opacity.setEnabled(True)
        self._page_opacity.setOpacity(0.0)
        self._sync_page_effects()
        self._flip.start(self.stack.geometry(), old_pm, new_pm, forward=index > old_index)

    def _refresh_nav(self):
        i = self._page_index
        self.dots.set_current(i)
        self.back_btn.setEnabled(i > 0)
        is_last = i == self.stack.count() - 1
        self.next_btn.setText("Empezar" if is_last else "Siguiente")
