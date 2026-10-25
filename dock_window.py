"""
Tercer modo de ventana, a pedido del usuario: una pestaña delgada anclada
a un borde de la pantalla (izquierdo o derecho, a elección en
Configuración) que, al hacer clic (o pasar el mouse, según el modo
elegido), despliega un panel con una interfaz propia. Tiene DOS estilos
(dock_style en Configuración): "card", vertical, con una carátula grande
(el diseño original) — y "compact", que reproduce el tamaño y la
disposición reales de la barra del modo compacto (`mini_window.py`),
sin su vinilo giratorio: carátula chica, título/artista al lado,
controles y barra de progreso, tal cual pidió el usuario tras ver la
primera versión.

Geometría (la parte más delicada): en vez de cambiar el ANCHO de la
ventana en cada frame para animar el deslizamiento (recalcular layouts
en cada frame sería caro y se vería con tirones), la ventana SIEMPRE mide
su tamaño completo (que depende del estilo elegido — ver CARD_WIDTH/
CARD_HEIGHT y COMPACT_BAR_W/COMPACT_BAR_H más abajo) y lo que se anima es
su posición X: para el borde derecho, expandida su borde derecho toca el
borde de la pantalla; colapsada, se desplaza hacia la derecha hasta que
solo el sector de la "pestaña" (HANDLE_SIZE px) queda dentro del área
visible — el resto de la ventana simplemente queda fuera del escritorio
virtual, que es una posición perfectamente válida para una ventana en Qt
(igual que arrastrar cualquier ventana a medias fuera de la pantalla). El
borde izquierdo es el espejo exacto de esta misma idea.

Se pintan dos formas separadas en vez de una sola: la "pestaña" (una
píldora chica, siempre en el mismo lugar exacto del borde) y la "tarjeta"
de contenido (la que se desliza detrás/al lado de la pestaña) — más
simple de dibujar bien (dos `addRoundedRect` comunes) que intentar
redondear distinto cada esquina de una sola forma gigante.
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import (
    Qt, QRectF, QRect, QTimer, pyqtSignal, pyqtProperty,
    QPropertyAnimation, QEasingCurve, QPoint,
)
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QLinearGradient, QRadialGradient, QCursor, QPen
from PyQt6.QtWidgets import QWidget, QApplication, QAbstractButton

from theme import Palette
import theme as theme_module
from widgets import (IconButton, SeekBar, MarqueeLabel, CoverArt, LyricsPanel, LIKE_RGB,
                     blur_image, _lerp_color)
from backend import PlayerState

RIPPLE_M = 12         # margen transparente alrededor de la píldora para las ondas
                      # (no mueve la píldora: se añade por su lado exterior)
HANDLE_SIZE = 34 + RIPPLE_M   # grosor de la pestaña (lo que asoma cuando está colapsada)
HANDLE_LENGTH = 96    # alto máximo de la pestaña a lo largo del borde (se
                       # recorta solo si el panel actual es más bajo que esto)

# Estilo "card" (el original): panel vertical, carátula grande arriba.
CARD_WIDTH = 248
CARD_HEIGHT = 408
CARD_COVER_SIZE = 148

# Estilo "compact": mismo tamaño y layout que la barra real del modo
# compacto (BASE_BAR_W/BASE_BAR_H en mini_window.py), sin el vinilo — una
# carátula cuadrada chica en vez del disco giratorio, a pedido del
# usuario ("del mismo tamaño y layout del compacto, no una inspirada en
# el reproductor"). Horizontal, no vertical, aunque siga saliendo de un
# borde vertical (izquierda/derecha): es exactamente lo que se pidió.
WAVE_DOT_W, WAVE_DOT_H = 34, 42   # el círculo de ondas de la pestaña (más grande que antes)
COMPACT_BAR_W = 380     # = BASE_BAR_W de mini_window.py (antes 300: el título quedaba con 86 px)
COMPACT_BAR_H = 96     # más que BASE_BAR_H (74): mini_window tiene margen
                        # extra reservado arriba para el vinilo que acá no
                        # hace falta, y la barra vertical de la pestaña ahora
                        # lleva 3 botones apilados (mostrar/ocultar, play,
                        # siguiente) que necesitan >= 24 px de alto cada uno
                        # (tamaño mínimo de objetivo táctil, WCAG 2.5.8).
                        # Antes era 84.
COMPACT_COVER_SIZE = 56


class DockWindow(QWidget):
    """Ventana anclada a un borde de pantalla, con pestaña + panel
    deslizante. `apply_state`/manejo de carátula y acento siguen el mismo
    patrón que MainWindow/MiniWindow (ver esos archivos)."""

    restoreMainRequested = pyqtSignal()   # "volver al reproductor completo"
    likeToggleRequested = pyqtSignal()    # clic en el corazón de la barra

    RIPPLE_PERIOD_S = 2.4
    RIPPLE_COUNT = 3

    def __init__(self, backend, cover_loader, parent=None, lyrics_loader=None):
        super().__init__(parent)
        self.backend = backend
        self.cover_loader = cover_loader
        self.lyrics_loader = lyrics_loader
        self._lyrics_mode = False        # la letra reemplaza a la carátula (solo estilo tarjeta)
        self._waves_enabled = True       # ondas alrededor de la barra (ver set_waves_enabled)
        self._is_playing = False
        self._ripple_t0 = time.monotonic()
        self._like_info = None

        self._edge = "right"          # "left" | "right" — ver set_edge()
        self._hide_mode = "both"      # "click" | "hover" | "both" — ver set_hide_mode()
        self._style = "card"          # "card" | "compact" — ver set_style()
        self._card_radius = 18
        self._collapsed = True
        self._last_state: PlayerState | None = None
        self._current_cover_url = ""
        self._cover_image = None
        self._card_bg = None
        self._card_bg_size = (0, 0)
        self._scrim_lo = 150      # velo adaptativo (ver theme.scrim_alpha_for)

        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self._accent_a_from = self._accent_a
        self._accent_b_from = self._accent_b
        self._accent_a_to = self._accent_a
        self._accent_b_to = self._accent_b
        self._transition_progress = 1.0
        self._transition_anim = QPropertyAnimation(self, b"transitionProgress", self)
        self._transition_anim.setDuration(420)
        self._transition_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Progreso 0..1 de la animación de deslizamiento (0 = colapsada, 1
        # = expandida) — se traduce a una posición X concreta en
        # _apply_slide_progress, distinta según el borde.
        self._slide_progress = 0.0
        self._slide_anim = QPropertyAnimation(self, b"slideProgress", self)
        self._slide_anim.setDuration(260)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.Tool)  # sin entrada en la barra de tareas
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)

        self._build_ui()
        self._wire_events()

        # Sondeo de hover (igual que mini_window.py: Enter/Leave por sí
        # solos resultaron poco confiables con varios widgets hijos
        # superpuestos en Windows real). Corre siempre que el modo de
        # ocultamiento sea "hover"/"both"; decide expandir/colapsar según
        # dónde esté el cursor de verdad, con un margen de gracia antes de
        # colapsar para no parpadear si el mouse solo pasó de largo.
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(150)
        self._hover_timer.timeout.connect(self._poll_hover)
        self._ms_outside = 0
        self._HOVER_GRACE_MS = 650

        # Ondas alrededor de la barra: solo repinta la franja de la pestaña.
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._ripple_timer.setInterval(40)      # 25 fps: sobra para ondas lentas y cuesta ~20 % menos
        self._ripple_timer.timeout.connect(self._ripple_tick)

        self.cover_loader.coverReady.connect(self._on_cover_ready)
        self.cover_loader.colorsReady.connect(self._on_colors_ready)
        self.backend.stateChanged.connect(self.apply_state)
        self.apply_state(PlayerState())

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.handle_icon = _WaveDot(self)

        self.restore_btn = IconButton("chevron_up", size=22, icon_scale=0.55, parent=self)
        self.restore_btn.setToolTip("Reproductor completo")

        self.cover = CoverArt(size=CARD_COVER_SIZE, radius_ratio=0.16, parent=self)
        self.cover_small = CoverArt(size=COMPACT_COVER_SIZE, radius_ratio=0.2, parent=self)
        self.cover_small.setVisible(False)
        self.title_label = MarqueeLabel("Sin reproducción", self, align=Qt.AlignmentFlag.AlignHCenter)
        self.artist_label = MarqueeLabel("WNP Player", self, align=Qt.AlignmentFlag.AlignHCenter)

        self.prev_btn = IconButton("prev", size=30, icon_scale=0.5, parent=self)
        self.play_btn = IconButton("play", size=42, icon_scale=0.42, gradient_bg=True, parent=self)
        self.next_btn = IconButton("next", size=30, icon_scale=0.5, parent=self)
        self.prev_btn.setToolTip("Anterior")
        self.play_btn.setToolTip("Reproducir / Pausar")
        self.next_btn.setToolTip("Siguiente")

        self.seek_bar = SeekBar(self, height=12, bar_height=4)

        # --- Botones de la pestaña (barra vertical, SIEMPRE visible aunque el
        # panel esté colapsado) ---
        # Estilo "card":    mostrar/ocultar, volver al reproductor normal,
        #                   anterior, play/pausa, siguiente + círculo de ondas.
        # Estilo "compact": mostrar/ocultar, play/pausa, siguiente (sin círculo).
        # Son instancias propias (no las del panel): el panel sigue igual.
        self.bar_toggle_btn = _DockArrowButton(self)
        self.bar_restore_btn = IconButton("chevron_up", size=26, icon_scale=0.55, parent=self)
        self.bar_prev_btn = IconButton("prev", size=26, icon_scale=0.5, parent=self)
        self.bar_play_btn = IconButton("play", size=32, icon_scale=0.42, gradient_bg=True, parent=self)
        self.bar_next_btn = IconButton("next", size=26, icon_scale=0.5, parent=self)
        self.bar_mic_btn = IconButton("mic", size=26, icon_scale=0.55, parent=self)
        self.bar_mic_btn.setToolTip("Mostrar la letra")
        self.bar_like_btn = IconButton("heart_outline", size=26, icon_scale=0.55, parent=self)
        self.bar_like_btn.setVisible(False)
        self.lyrics_panel = None
        if self.lyrics_loader is not None:
            self.lyrics_panel = LyricsPanel(self.lyrics_loader, parent=self)
            self.lyrics_panel.setVisible(False)
        self.bar_restore_btn.setToolTip("Volver al reproductor normal")
        self.bar_prev_btn.setToolTip("Anterior")
        self.bar_play_btn.setToolTip("Reproducir / Pausar")
        self.bar_next_btn.setToolTip("Siguiente")
        # Los que ejecutan una acción directa: pasar el mouse por encima NO
        # debe desplegar el panel (ver _poll_hover).
        self._bar_action_btns = [self.bar_restore_btn, self.bar_prev_btn, self.bar_play_btn,
                                 self.bar_next_btn, self.bar_mic_btn, self.bar_like_btn]
        self._apply_style_visibility()

    def _wire_events(self):
        self.restore_btn.clicked.connect(self.restoreMainRequested.emit)
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.prev_btn.clicked.connect(self.backend.previous)
        self.next_btn.clicked.connect(self.backend.next)
        self.seek_bar.seekRequested.connect(self.backend.seek_percent)

        self.bar_toggle_btn.clicked.connect(self._toggle)
        self.bar_restore_btn.clicked.connect(self.restoreMainRequested.emit)
        self.bar_play_btn.clicked.connect(self._on_play_clicked)
        self.bar_prev_btn.clicked.connect(self.backend.previous)
        self.bar_next_btn.clicked.connect(self.backend.next)
        self.bar_mic_btn.clicked.connect(self._toggle_lyrics)
        self.bar_like_btn.clicked.connect(self.likeToggleRequested.emit)

    def _apply_style_visibility(self):
        """Qué botones lleva la pestaña según el estilo, y de qué tamaño."""
        compact = self._style == "compact"
        # Compacto: sin círculo de color, sin "volver" ni "anterior".
        self.handle_icon.setVisible(not compact)
        self.bar_restore_btn.setVisible(not compact)
        self.bar_prev_btn.setVisible(not compact)
        # En la tarjeta grande la pestaña ya lleva "volver al reproductor": el
        # botón de la esquina del panel sobraba (en el compacto no hay otro).
        self.restore_btn.setVisible(compact)
        self.bar_mic_btn.setVisible(not compact and self.lyrics_panel is not None)
        self.bar_like_btn.setVisible(not compact and self._like_info is not None and self._like_info.visible)
        if compact:
            self.bar_toggle_btn.setFixedSize(24, 24)
            self.bar_play_btn.setFixedSize(28, 28)
            self.bar_next_btn.setFixedSize(24, 24)
        else:
            self.bar_toggle_btn.setFixedSize(26, 26)
            self.bar_play_btn.setFixedSize(32, 32)
            self.bar_next_btn.setFixedSize(26, 26)
        self._sync_toggle()

    def _sync_toggle(self):
        self.bar_toggle_btn.refresh()


    # Sin ningun reproductor el play queda ACTIVO (si el ajuste no es "No hacer
    # nada"): al pulsarlo la app abre Spotify/YouTube. AppController lo fija.
    play_idle_enabled = True

    def _play_enabled(self, state) -> bool:
        return bool(state.controls_available or (not state.has_media and self.play_idle_enabled))

    def set_play_idle_enabled(self, enabled: bool):
        self.play_idle_enabled = bool(enabled)
        st = self._last_state
        if st is not None:
            self._apply_play_enabled(st)

    def _apply_play_enabled(self, state):
        for btn in (self.play_btn, self.bar_play_btn):
            btn.setEnabled(self._play_enabled(state))

    def _on_play_clicked(self):
        # El backend solo expone toggle_play_pause(): antes se llamaba a
        # backend.pause() / backend.play(), que NO existen, y el botón de play
        # del dock lanzaba AttributeError en cada clic.
        self.backend.toggle_play_pause()

    # -------------------------------------------------------- configuración
    def set_edge(self, edge: str):
        edge = edge if edge in ("left", "right") else "right"
        if edge == self._edge:
            return
        self._edge = edge
        self._layout_children()
        self._reposition(animate=False)
        self.update()

    def set_hide_mode(self, mode: str):
        self._hide_mode = mode if mode in ("click", "hover", "both") else "both"
        wants_poll = self._hide_mode in ("hover", "both")
        if wants_poll and not self._hover_timer.isActive():
            self._ms_outside = 0
            self._hover_timer.start()
        elif not wants_poll and self._hover_timer.isActive():
            self._hover_timer.stop()

    def set_style(self, style: str):
        """'card': panel vertical con carátula grande (el diseño original).
        'compact': misma medida y disposición que la barra del modo
        compacto real, sin el vinilo — carátula cuadrada chica a la
        izquierda, título/artista al lado, controles a la derecha y la
        barra de progreso pegada abajo.

        Cambiar de estilo cambia el TAMAÑO de la ventana (no solo cómo se
        acomodan las cosas adentro), así que se fuerza siempre a quedar
        colapsada y se reposiciona desde cero: es mucho más simple que
        intentar reconciliar una animación de deslizamiento a medias con
        una geometría nueva, y se llama desde Configuración, donde el
        panel casi nunca está abierto de todos modos."""
        style = style if style in ("card", "compact") else "card"
        if style == self._style:
            return
        self._style = style
        self._card_radius = 22 if style == "compact" else 18

        w, h = self._panel_dims()
        self._slide_anim.stop()
        self._collapsed = True
        self._slide_progress = 0.0
        self.setFixedSize(w, h)

        compact = style == "compact"
        if compact:
            self._lyrics_mode = False
        self.cover.setVisible(not compact)
        self.cover_small.setVisible(compact)
        # Texto centrado bajo una carátula grande (columna angosta), pero
        # alineado a la izquierda junto a una carátula chica (barra ancha).
        align = Qt.AlignmentFlag.AlignLeft if compact else Qt.AlignmentFlag.AlignHCenter
        self.title_label._align = align
        self.artist_label._align = align
        self.title_label.update()
        self.artist_label.update()

        self._card_bg_size = (0, 0)
        self._refresh_card_bg()
        self._apply_style_visibility()
        self._layout_children()
        self._reposition(animate=False)
        self._sync_lyrics()
        self._sync_ripples()
        self.update()

    def _panel_dims(self) -> tuple[int, int]:
        if self._style == "compact":
            return HANDLE_SIZE + COMPACT_BAR_W, COMPACT_BAR_H
        return CARD_WIDTH, CARD_HEIGHT

    # -------------------------------------------------------- mostrar/ocultar
    def show_on_edge(self):
        """Llamado por AppController al entrar a este modo: arranca
        siempre colapsada (la pestaña asomando), en el borde configurado."""
        self._collapsed = True
        self._slide_progress = 0.0
        self._sync_toggle()
        self._reposition(animate=False)
        self.show()
        self.raise_()
        if self._hide_mode in ("hover", "both") and not self._hover_timer.isActive():
            self._hover_timer.start()

    def hide(self):
        self._hover_timer.stop()
        super().hide()

    def _toggle(self):
        self._collapse() if not self._collapsed else self._expand()

    def _expand(self):
        if not self._collapsed:
            return
        self._collapsed = False
        self._ms_outside = 0
        self._sync_toggle()
        self._animate_slide(1.0)
        self._sync_lyrics()

    def _collapse(self):
        if self._collapsed:
            return
        self._collapsed = True
        self._sync_toggle()
        self._animate_slide(0.0)
        self._sync_lyrics()

    def _animate_slide(self, target: float):
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide_progress)
        self._slide_anim.setEndValue(target)
        self._slide_anim.start()

    # -------------------------------------------------- geometría / pantalla
    def _screen_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _reposition(self, animate: bool):
        """Recalcula X (según progreso de deslizamiento actual) e Y
        (centrada verticalmente en el borde elegido) y mueve la ventana.
        `animate` no anima acá (eso ya lo hace slideProgress vía
        _apply_slide_progress en cada tick) — solo decide si, al llamar
        desde afuera (p. ej. al cambiar de borde en Configuración), hay
        que saltar directo o dejar que la próxima animación lo resuelva."""
        geo = self._screen_geometry()
        y = geo.top() + (geo.height() - self.height()) // 2
        if animate:
            self.move(self.x(), y)
        else:
            self._apply_slide_progress(self._slide_progress, y_override=y)

    def _apply_slide_progress(self, progress: float, y_override: int | None = None):
        geo = self._screen_geometry()
        y = y_override if y_override is not None else self.y()
        w = self.width()
        if self._edge == "right":
            collapsed_x = geo.right() - HANDLE_SIZE
            expanded_x = geo.right() - w
        else:
            collapsed_x = geo.left() - (w - HANDLE_SIZE)
            expanded_x = geo.left()
        x = round(collapsed_x + (expanded_x - collapsed_x) * progress)
        self.move(x, y)

    def getSlideProgress(self) -> float:
        return self._slide_progress

    def setSlideProgress(self, value: float):
        self._slide_progress = value
        self._apply_slide_progress(value)

    slideProgress = pyqtProperty(float, getSlideProgress, setSlideProgress)

    # -------------------------------------------------------------- layout
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_children()

    def _content_zone(self) -> QRectF:
        w, h = self.width(), self.height()
        if self._edge == "right":
            return QRectF(HANDLE_SIZE, 0, w - HANDLE_SIZE, h)
        return QRectF(0, 0, w - HANDLE_SIZE, h)

    def _handle_zone(self) -> QRectF:
        w, h = self.width(), self.height()
        if self._edge == "right":
            return QRectF(0, 0, HANDLE_SIZE, h)
        return QRectF(w - HANDLE_SIZE, 0, HANDLE_SIZE, h)

    def _pill_rect(self) -> QRectF:
        """La píldora visible de la pestaña. Queda EXACTAMENTE donde estaba antes
        (3 px del borde y de la tarjeta); el margen RIPPLE_M extra de la zona de
        la pestaña va por su lado exterior (y arriba/abajo en el estilo tarjeta)
        y es solo espacio transparente para las ondas."""
        h = self._handle_zone()
        vert = 3 + (RIPPLE_M if self._style == "card" else 0)
        if self._edge == "right":
            return QRectF(h.left() + 3 + RIPPLE_M, h.top() + vert, h.width() - 6 - RIPPLE_M, h.height() - 2 * vert)
        return QRectF(h.left() + 3, h.top() + vert, h.width() - 6 - RIPPLE_M, h.height() - 2 * vert)

    def _layout_children(self):
        content = self._content_zone()
        handle_rect = self._handle_zone()
        self._layout_bar(handle_rect)
        if self._style == "compact":
            self._layout_children_compact(content)
        else:
            self._layout_children_card(content)

    def _layout_bar(self, handle_rect: QRectF):
        """Acomoda los botones de la pestaña, apilados en vertical y
        centrados en su eje.

        Tarjeta (pestaña alta):  arriba mostrar/ocultar y "volver"; al centro
        anterior / play / siguiente; abajo el círculo de ondas.
        Compacto (pestaña baja): mostrar/ocultar, play y siguiente, juntos y
        centrados (sin círculo)."""
        pill = self._pill_rect()
        cx = pill.center().x()
        cy = pill.center().y()
        top = pill.top()
        bottom = pill.bottom()

        def put(widget, center_y):
            widget.move(round(cx - widget.width() / 2), round(center_y - widget.height() / 2))

        if self._style == "compact":
            gap = 4
            widgets = [self.bar_toggle_btn, self.bar_play_btn, self.bar_next_btn]
            total = sum(w.height() for w in widgets) + gap * (len(widgets) - 1)
            y = cy - total / 2
            for w in widgets:
                put(w, y + w.height() / 2)
                y += w.height() + gap
            return

        pad = 10
        put(self.bar_toggle_btn, top + pad + self.bar_toggle_btn.height() / 2)
        put(self.bar_restore_btn,
            top + pad + self.bar_toggle_btn.height() + 4 + self.bar_restore_btn.height() / 2)

        gap = 6
        group = [self.bar_prev_btn, self.bar_play_btn, self.bar_next_btn]
        total = sum(w.height() for w in group) + gap * (len(group) - 1)
        y = cy - total / 2
        for w in group:
            put(w, y + w.height() / 2)
            y += w.height() + gap

        # Letra y "me gusta" debajo del grupo de reproducción (el hueco hasta el círculo).
        below = y + 8
        put(self.bar_mic_btn, below + self.bar_mic_btn.height() / 2)
        put(self.bar_like_btn, below + self.bar_mic_btn.height() + 6 + self.bar_like_btn.height() / 2)

        dot_h = 34
        # Más grande que la píldora a propósito: las ondas del círculo salen un poco de ella.
        self.handle_icon.setGeometry(
            round(cx - WAVE_DOT_W / 2), round(bottom - pad - dot_h - (WAVE_DOT_H - dot_h) / 2),
            WAVE_DOT_W, WAVE_DOT_H)

    def _layout_children_card(self, content: QRectF):
        pad = 18
        cx = content.left() + content.width() / 2

        # Sin el botón de la esquina (la pestaña ya lo tiene), el bloque
        # carátula + título + controles + barra se centra verticalmente.
        block_h = CARD_COVER_SIZE + 16 + 22 + 18 + 14 + 54 + 12
        cover_y = round(content.top() + max(14.0, (content.height() - block_h) / 2))
        cover_x = round(cx - CARD_COVER_SIZE / 2)
        self.cover.move(cover_x, cover_y)

        text_w = round(content.width() - 2 * pad)
        title_y = cover_y + CARD_COVER_SIZE + 16
        self.title_label.setGeometry(round(content.left() + pad), title_y, text_w, 22)
        self.artist_label.setGeometry(round(content.left() + pad), title_y + 22, text_w, 18)

        controls_y = title_y + 22 + 18 + 14
        self.prev_btn.move(round(cx - 56), controls_y + 6)
        self.play_btn.move(round(cx - 21), controls_y)
        self.next_btn.move(round(cx + 26), controls_y + 6)

        seek_y = controls_y + 54
        self.seek_bar.setGeometry(round(content.left() + pad), seek_y, text_w, 12)

        # La letra ocupa el lugar de carátula + título/artista (los controles y la
        # barra de progreso siguen visibles debajo).
        if self.lyrics_panel is not None:
            top = round(content.top()) + 14
            self.lyrics_panel.setGeometry(
                round(content.left()) + 10, top, round(content.width()) - 20, controls_y - 8 - top)

    def _layout_children_compact(self, content: QRectF):
        """Misma disposición que la barra real del modo compacto: carátula
        chica a la izquierda, título/artista al lado, controles a la
        derecha, barra de progreso pegada abajo — sin vinilo."""
        pad = 10

        # "Volver al reproductor completo": a 8 px de los bordes cae dentro de la
        # esquina redondeada de la tarjeta (a 6 px o menos la pisaba) y los
        # controles bajan un poco para que no se toquen (antes quedaban a 1 px).
        self.restore_btn.move(
            round(content.right() - self.restore_btn.width() - 8), round(content.top() + 8)
        )

        cover_y = round(content.top() + (content.height() - COMPACT_COVER_SIZE) / 2) - 4
        cover_y = max(round(content.top()) + pad, cover_y)
        cover_x = round(content.left() + pad)
        self.cover_small.move(cover_x, cover_y)

        controls_w = self.prev_btn.width() + self.play_btn.width() + self.next_btn.width() + 16
        controls_x = round(content.right() - pad - controls_w)
        row_cy = round(content.top() + content.height() / 2) + 6
        self.play_btn.move(controls_x + self.prev_btn.width() + 8, row_cy - self.play_btn.height() // 2)
        self.prev_btn.move(controls_x, row_cy - self.prev_btn.height() // 2)
        self.next_btn.move(
            controls_x + self.prev_btn.width() + 8 + self.play_btn.width() + 8,
            row_cy - self.next_btn.height() // 2,
        )

        text_x = cover_x + COMPACT_COVER_SIZE + 10
        text_w = max(20, controls_x - text_x - 10)
        # Altura por las métricas reales de la fuente (antes 18 y 16 px fijos,
        # menos que el alto de línea de una fuente de 12 pt: el texto se cortaba).
        th = self.title_label.text_height() + 2
        ah = self.artist_label.text_height() + 2
        text_top = round(content.top() + pad + 4)
        self.title_label.setGeometry(text_x, text_top, text_w, th)
        self.artist_label.setGeometry(text_x, text_top + th, text_w, ah)

        seek_h = 6
        seek_y = round(content.bottom() - pad - seek_h)
        self.seek_bar.setGeometry(
            round(content.left() + pad), seek_y, round(content.width() - 2 * pad), seek_h
        )

    # -------------------------------------------------------------- estado
    def apply_state(self, state: PlayerState):
        if self._last_state is not None and self._last_state == state:
            return
        self._last_state = state

        self.title_label.setText(state.title or "Sin reproducción")
        self.artist_label.setText(state.artist or "WNP Player")

        is_playing = state.state == "PLAYING"
        # Panel y pestaña muestran exactamente el mismo estado.
        for btn in (self.play_btn, self.bar_play_btn):
            btn.set_icon("pause" if is_playing else "play")
            btn.setEnabled(self._play_enabled(state))
        for btn in (self.prev_btn, self.bar_prev_btn):
            btn.setEnabled(state.controls_available and state.can_prev)
        for btn in (self.next_btn, self.bar_next_btn):
            btn.setEnabled(state.controls_available and state.can_next)

        self.seek_bar.set_percent(state.position_percent)
        self.seek_bar.set_seekable(state.controls_available and state.duration_known)
        self.seek_bar.set_duration_seconds(state.duration_seconds)

        self.handle_icon.set_playing(is_playing)
        self._is_playing = is_playing
        self._sync_ripples()
        self._sync_lyrics()

        if state.cover_url != self._current_cover_url:
            self._current_cover_url = state.cover_url
            if state.cover_url:
                self.cover_loader.request(state.cover_url)
            else:
                self._set_cover_image(None)
                self._transition_anim.stop()
                self._accent_a_from, self._accent_b_from = self._accent_a, self._accent_b
                self._accent_a_to = Palette.c(Palette.ACCENT_A)
                self._accent_b_to = Palette.c(Palette.ACCENT_B)
                self._transition_progress = 0.0
                self._transition_anim.setStartValue(0.0)
                self._transition_anim.setEndValue(1.0)
                self._transition_anim.start()

    def _on_cover_ready(self, url, image):
        if url == self._current_cover_url:
            self._set_cover_image(image if not image.isNull() else None)

    def _on_colors_ready(self, url, accent_a, accent_b):
        if url != self._current_cover_url:
            return
        self._transition_anim.stop()
        self._accent_a_from, self._accent_b_from = self._accent_a, self._accent_b
        self._accent_a_to = QColor(*accent_a)
        self._accent_b_to = QColor(*accent_b)
        self._transition_progress = 0.0
        self._transition_anim.setStartValue(0.0)
        self._transition_anim.setEndValue(1.0)
        self._transition_anim.start()

    def getTransitionProgress(self) -> float:
        return self._transition_progress

    def setTransitionProgress(self, value: float):
        self._transition_progress = value
        self._accent_a = _lerp_color(self._accent_a_from, self._accent_a_to, value)
        self._accent_b = _lerp_color(self._accent_b_from, self._accent_b_to, value)
        self.cover.set_accent((self._accent_a.red(), self._accent_a.green(), self._accent_a.blue()),
                               (self._accent_b.red(), self._accent_b.green(), self._accent_b.blue()))
        rgb_a = (self._accent_a.red(), self._accent_a.green(), self._accent_a.blue())
        rgb_b = (self._accent_b.red(), self._accent_b.green(), self._accent_b.blue())
        self.cover_small.set_accent(rgb_a, rgb_b)
        self.play_btn.set_accent(rgb_a, rgb_b)
        self.bar_play_btn.set_accent(rgb_a, rgb_b)
        self.seek_bar.set_accent(rgb_a, rgb_b)
        self.handle_icon.set_accent(self._accent_a, self._accent_b)
        self.update()

    transitionProgress = pyqtProperty(float, getTransitionProgress, setTransitionProgress)

    def _set_cover_image(self, image):
        self._cover_image = image
        self.cover.set_image(image)
        self.cover_small.set_image(image)
        if image is not None and not image.isNull():
            self._scrim_lo = theme_module.scrim_alpha_for(
                image, fg=Palette.TEXT, scrim=(8, 8, 14), minimum=4.5, lo=150, hi=230)
        else:
            self._scrim_lo = 150
        self._card_bg_size = (0, 0)
        self._refresh_card_bg()
        self.update()

    def _refresh_card_bg(self):
        content = self._content_zone()
        size = (round(content.width()), round(content.height()))
        if self._cover_image is None:
            self._card_bg = None
            self._card_bg_size = (0, 0)
            return
        if size == self._card_bg_size:
            return
        from PyQt6.QtGui import QPixmap
        blurred = blur_image(self._cover_image, size[0], size[1], strength=6)
        self._card_bg = QPixmap.fromImage(blurred) if not blurred.isNull() else None
        self._card_bg_size = size

    # -------------------------------------------------------------- hover
    # ------------------------------------------------------------ "me gusta"
    def set_like_info(self, info):
        """Refleja el estado de "me gusta" (ver likes.LikeInfo) en el corazón de la barra."""
        self._like_info = info
        liked = bool(info.liked)
        self.bar_like_btn.set_icon("heart" if liked else "heart_outline")
        self.bar_like_btn.set_color_override(LIKE_RGB if liked else None)
        self.bar_like_btn.setToolTip(info.tooltip)
        self.bar_like_btn.setVisible(self._style == "card" and info.visible)

    # ------------------------------------------------------------------ letra
    def _toggle_lyrics(self):
        """Micrófono de la barra: la letra de lo que suena sustituye a la carátula."""
        if self.lyrics_panel is None or self._style != "card":
            return
        self._lyrics_mode = not self._lyrics_mode
        if self._lyrics_mode and self._collapsed:
            self._expand()          # si el panel está recogido, se abre para poder leerla
        self._sync_lyrics()

    def is_lyrics_mode(self) -> bool:
        return self._lyrics_mode

    def _sync_lyrics(self):
        """Aplica el modo letra: visibilidad del panel y datos de la canción."""
        on = self._lyrics_mode and self._style == "card" and self.lyrics_panel is not None
        for w in (self.cover, self.title_label, self.artist_label):
            w.setVisible(not on and self._style == "card")
        self.bar_mic_btn.set_active(on)
        self.bar_mic_btn.setToolTip("Ocultar la letra" if on else "Mostrar la letra")
        if self.lyrics_panel is None:
            return
        self.lyrics_panel.setVisible(on)
        if not on:
            self.lyrics_panel.set_playing(False)     # nadie la ve: sin timers
            self.update()
            return
        st = self._last_state
        if st is not None and (st.artist or st.title):
            self.lyrics_panel.set_track_debounced(st.artist, st.title, st.album, st.duration_seconds)
            self.lyrics_panel.set_position(st.position_seconds)
            self.lyrics_panel.set_playing(st.state == "PLAYING" and not self._collapsed)
        else:
            self.lyrics_panel.set_track("", "", "", 0)
        self.update()

    # ------------------------------------------------------------------ ondas
    def set_waves_enabled(self, enabled: bool):
        """Ondas alrededor de la barra mientras suena algo (ajuste de Configuración)."""
        self._waves_enabled = bool(enabled)
        self._sync_ripples()
        self.update(self._ripple_rect())

    def waves_enabled(self) -> bool:
        return self._waves_enabled

    def _ripples_wanted(self) -> bool:
        return (self._waves_enabled and self._style == "card" and self._is_playing
                and self.isVisible() and not theme_module.REDUCED_MOTION)

    def _sync_ripples(self):
        want = self._ripples_wanted()
        if want and not self._ripple_timer.isActive():
            self._ripple_timer.start()
        elif not want and self._ripple_timer.isActive():
            self._ripple_timer.stop()
            self.update(self._ripple_rect())     # borra la última onda

    def _ripple_rect(self) -> QRect:
        # Recortado a la zona de la pestaña: nunca invade la tarjeta (así el repintado
        # de las ondas no obliga a repintar la tarjeta, que es lo caro).
        rect = self._pill_rect().adjusted(-RIPPLE_M - 3, -RIPPLE_M - 3, RIPPLE_M + 3, RIPPLE_M + 3).toAlignedRect()
        return rect.intersected(self._handle_zone().toAlignedRect())

    def _ripple_tick(self):
        self.update(self._ripple_rect())     # solo la franja de la pestaña, no toda la tarjeta

    def _paint_ripples(self, painter: QPainter):
        """Ondas que salen de la píldora hacia fuera, por reloj real (no por tick)."""
        pill = self._pill_rect()
        phase = ((time.monotonic() - self._ripple_t0) / self.RIPPLE_PERIOD_S) % 1.0
        painter.save()
        painter.setClipRect(self._handle_zone())        # solo hacia fuera de la tarjeta
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(self.RIPPLE_COUNT):
            t = (phase + i / self.RIPPLE_COUNT) % 1.0
            grow = RIPPLE_M * (1.0 - (1.0 - t) ** 2)              # sale rápido, frena al final
            fade = (1.0 - t) ** 1.15
            if fade < 0.03:
                continue
            c = _lerp_color(self._accent_a, self._accent_b, t).lighter(125)
            rect = pill.adjusted(-grow, -grow, grow, grow)
            radius = 14 + grow
            # Resplandor ancho y suave debajo de cada onda, y encima el trazo nítido.
            if fade > 0.25:      # el resplandor (trazo ancho) es lo más caro y en las ondas casi apagadas no se aprecia
                glow = QColor(c)
                glow.setAlpha(int(70 * fade))
                painter.setPen(QPen(glow, 7.0 - 3.0 * t))
                painter.drawRoundedRect(rect, radius, radius)
            c.setAlpha(int(255 * fade))
            painter.setPen(QPen(c, 3.0 - 1.8 * t))
            painter.drawRoundedRect(rect, radius, radius)
        painter.restore()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_ripples()

    def hideEvent(self, event):
        self._ripple_timer.stop()
        super().hideEvent(event)

    def _poll_hover(self):
        cursor = QCursor.pos()
        if self._collapsed:
            handle_rect_global = self._handle_zone().translated(self.x(), self.y())
            if handle_rect_global.toRect().contains(cursor):
                self._ms_outside = 0
                # Sobre un botón de acción (play, siguiente...) el usuario
                # quiere USARLO, no abrir el panel: sin esto, apuntar al play
                # desplegaba la tarjeta encima. La flecha y el resto de la
                # pestaña siguen abriendo el panel al pasar el mouse.
                if not self._cursor_over_action_button(cursor):
                    self._expand()
            return
        inside = self.geometry().contains(cursor)
        if inside:
            self._ms_outside = 0
            return
        self._ms_outside += self._hover_timer.interval()
        if self._ms_outside >= self._HOVER_GRACE_MS:
            self._collapse()

    def _cursor_over_action_button(self, cursor: QPoint) -> bool:
        for btn in self._bar_action_btns:
            if btn.isVisible() and QRect(btn.mapToGlobal(QPoint(0, 0)), btn.size()).contains(cursor):
                return True
        return False

    # -------------------------------------------------------------- clics
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        local = event.position().toPoint()
        if self._handle_zone().toRect().contains(local):
            self._toggle()
            event.accept()

    # -------------------------------------------------------------- pintura
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        content = self._content_zone()
        handle = self._handle_zone()

        if self._ripple_timer.isActive():
            self._paint_ripples(painter)      # debajo de la tarjeta y de la píldora

        # --- Tarjeta de contenido (la parte que se desliza) ---
        # Las ondas repintan solo la franja de la pestaña (30 veces/s): si la zona sucia
        # no toca la tarjeta, se salta TODO este bloque (ruta recortada con antialiasing,
        # carátula y degradados eran el grueso del coste de cada fotograma).
        if event.rect().intersects(content.toAlignedRect()):
            card_path = QPainterPath()
            card_path.addRoundedRect(content.adjusted(1, 1, -1, -1), self._card_radius, self._card_radius)
            painter.save()
            painter.setClipPath(card_path)
            if self._card_bg is not None:
                painter.drawPixmap(content.toRect(), self._card_bg)
            else:
                painter.fillPath(card_path, Palette.c(Palette.BG_PANEL, 250))
            scrim = QLinearGradient(content.topLeft(), content.bottomRight())
            scrim.setColorAt(0.0, QColor(8, 8, 14, self._scrim_lo))
            scrim.setColorAt(1.0, QColor(8, 8, 14, max(210, min(245, self._scrim_lo + 30))))
            painter.fillPath(card_path, scrim)
            painter.restore()

            grad = QLinearGradient(content.topLeft(), content.bottomRight())
            grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                         self._accent_a.blue(), 160))
            grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                         self._accent_b.blue(), 160))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = painter.pen()
            pen.setBrush(grad)
            pen.setWidthF(1.3)
            painter.setPen(pen)
            painter.drawPath(card_path)

            # Modo letra: un fondo suave detrás del texto para que se lea sobre cualquier carátula.
            if self._lyrics_mode and self.lyrics_panel is not None and self._style == "card":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(8, 8, 14, 125))
                painter.drawRoundedRect(QRectF(self.lyrics_panel.geometry()), 14, 14)

        # --- Pestaña (siempre visible, en el borde real) ---
        handle_path = QPainterPath()
        handle_path.addRoundedRect(self._pill_rect(), 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*Palette.BG_PANEL, 250))
        painter.drawPath(handle_path)
        handle_grad = QLinearGradient(handle.topLeft(), handle.bottomRight())
        handle_grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                            self._accent_a.blue(), 220))
        handle_grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                            self._accent_b.blue(), 220))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen2 = painter.pen()
        pen2.setBrush(handle_grad)
        pen2.setWidthF(1.6)
        painter.setPen(pen2)
        painter.drawPath(handle_path)

        painter.end()


class _WaveDot(QWidget):
    """El círculo de color de la pestaña (solo estilo tarjeta).

    Sonando: del círculo salen ondas concéntricas que se expanden y se
    desvanecen (tipo "transmitiendo"). En pausa: queda ESTÁTICO, con el
    círculo atenuado y los anillos apenas insinuados.

    La animación va por reloj real (no por "N px por tick", los timers de Qt
    se atrasan bajo carga), solo corre mientras suena Y el widget está
    visible, y se apaga con "reducir movimiento" (entonces "sonando" se
    distingue de "pausa" por el brillo, sin movimiento)."""

    PERIOD_S = 1.7      # una onda tarda esto en ir del círculo al borde
    RINGS = 4
    CORE_R = 5.6
    BREATH_S = 1.1      # latido del núcleo y del halo

    def __init__(self, parent: DockWindow):
        super().__init__(parent)
        self._playing = False
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self._t0 = time.monotonic()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(33)   # ~30 fps: suficiente para ondas suaves
        self._timer.timeout.connect(self.update)

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def _sync_timer(self):
        should_run = self._playing and self.isVisible() and not theme_module.REDUCED_MOTION
        if should_run and not self._timer.isActive():
            self._timer.start()
        elif not should_run and self._timer.isActive():
            self._timer.stop()

    def set_playing(self, playing: bool):
        if playing == self._playing:
            return
        self._playing = playing
        self._sync_timer()
        self.update()

    def set_accent(self, a: QColor, b: QColor):
        self._accent_a, self._accent_b = a, b
        self.update()

    def showEvent(self, event):
        self._sync_timer()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _ring_color(self, t: float, alpha: float) -> QColor:
        c = _lerp_color(self._accent_a, self._accent_b, t)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        max_r = min(self.width(), self.height()) / 2.0 - 1.0
        core = self.CORE_R
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._timer.isActive():
            now = time.monotonic() - self._t0
            phase = (now / self.PERIOD_S) % 1.0
            breath = 0.5 + 0.5 * math.sin(2 * math.pi * (now / self.BREATH_S))   # 0..1
            core = core * (1.0 + 0.2 * breath)            # el núcleo late
            # Halo difuso que respira detrás del círculo.
            halo_r = max_r * (0.78 + 0.22 * breath)
            halo = QRadialGradient(cx, cy, halo_r)
            halo.setColorAt(0.0, self._ring_color(0.2, 0.55 + 0.25 * breath))
            halo.setColorAt(1.0, self._ring_color(0.8, 0.0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(cx - halo_r, cy - halo_r, 2 * halo_r, 2 * halo_r))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(self.RINGS):
                t = (phase + i / self.RINGS) % 1.0
                r = core + (max_r - core) * (1.0 - (1.0 - t) ** 2)   # sale rápido, frena al final
                painter.setPen(QPen(self._ring_color(t, 0.95 * (1.0 - t) ** 1.2),
                                    2.4 - 1.2 * t))
                painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        else:
            # Estático. Sonando sin animación (movimiento reducido): anillos
            # más visibles; en pausa: casi invisibles.
            a1, a2 = (0.36, 0.20) if self._playing else (0.14, 0.07)
            for r, al, t in ((core + 4.0, a1, 0.35), (core + 8.0, a2, 0.7)):
                painter.setPen(QPen(self._ring_color(t, al), 1.5))
                painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        grad = QLinearGradient(cx - core, cy - core, cx + core, cy + core)
        core_alpha = 1.0 if self._playing else 0.5
        grad.setColorAt(0.0, self._ring_color(0.0, core_alpha))
        grad.setColorAt(1.0, self._ring_color(1.0, core_alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(QRectF(cx - core, cy - core, 2 * core, 2 * core))
        painter.end()


class _DockArrowButton(QAbstractButton):
    """Botón de la flecha de la pestaña: mostrar / ocultar el panel.

    Es la misma flecha que ya tenía la pestaña (antes solo era un dibujo; el
    clic lo recibía la pestaña entera), ahora como botón real: con hover,
    foco de teclado y nombre accesible que cambia según el estado."""

    def __init__(self, dock: DockWindow):
        super().__init__(dock)
        self._dock = dock
        self._hover = False
        self._kbd_focus = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)

    def refresh(self):
        text = "Mostrar reproductor lateral" if self._dock._collapsed else "Ocultar reproductor lateral"
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._kbd_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._kbd_focus = False
        self.update()
        super().focusOutEvent(event)

    def points_right(self) -> bool:
        """Flecha apuntando a la derecha. Colapsada apunta hacia adentro de la
        pantalla (invita a "tirar" del panel); expandida, hacia el borde
        (invita a "empujarlo de vuelta")."""
        pointing_in = self._dock._collapsed
        if self._dock._edge == "right":
            return not pointing_in
        return pointing_in

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.drawEllipse(QRectF(1, 1, w - 2, h - 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*Palette.TEXT, 255 if self._hover else 220))
        path = QPainterPath()
        if self.points_right():
            path.moveTo(cx - 3.5, cy - 5)
            path.lineTo(cx + 4.5, cy)
            path.lineTo(cx - 3.5, cy + 5)
        else:
            path.moveTo(cx + 3.5, cy - 5)
            path.lineTo(cx - 4.5, cy)
            path.lineTo(cx + 3.5, cy + 5)
        path.closeSubpath()
        painter.drawPath(path)
        if self._kbd_focus and self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*Palette.TEXT), 2.0))
            painter.drawEllipse(QRectF(1, 1, w - 2, h - 2))
        painter.end()
