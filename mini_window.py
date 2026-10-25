"""Ventana compacta: barra horizontal flotante con la carátula del tema
actual como fondo difuminado, y un 'vinilo' circular que se asoma por
fuera del marco (esquina superior izquierda).

Al pulsar el vinilo, la barra se repliega y solo queda flotando el disco
circular con tres controles básicos (anterior / reproducir / siguiente).
Al volver a pulsarlo, la barra reaparece exactamente donde estaba: el
punto de anclaje siempre es el propio vinilo, así que la transición no
'salta' en la pantalla.

Ambos modos cambian de tamaño con la rueda del mouse sobre la ventana:
todo (barra, vinilo, botones, texto) escala junto a partir de un único
factor de zoom que se conserva al alternar entre barra y disco.
"""
from PyQt6.QtCore import Qt, QRect, QRectF, QEvent, QTimer, pyqtSignal, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QLinearGradient, QPen, QPixmap, QFont, QCursor, QFontMetrics
from PyQt6.QtWidgets import QWidget

from theme import Palette, FONT_BODY
import theme as theme_module
from widgets import IconButton, SeekBar, MarqueeLabel, VinylCover, blur_image, _lerp_color
from backend import PlayerState

# --- Geometría base (a escala 1.0) del modo expandido (barra) -------------
BASE_MARGIN = 16                 # margen para que la sombra no se recorte
BASE_OVERFLOW = 34               # espacio reservado arriba de la barra para el vinilo
BASE_BAR_W = 380      # antes 300: tras los controles el título quedaba con 66 px
BASE_BAR_H = 74
BASE_CIRCLE_D = 78               # diámetro visible del vinilo en modo barra
BASE_CIRCLE_OVERLAP_X = 18       # cuánto se asoma el vinilo a la izquierda de la barra
SHADOW_MARGIN = 9                # borde extra del VinylCover reservado para su sombra (no escala)

# --- Geometría base del modo colapsado (solo el disco) ---------------------
BASE_COLLAPSED_CIRCLE_D = 104
BASE_COLLAPSED_PAD = 16

MIN_SCALE = 0.75
MAX_SCALE = 1.6
_WHEEL_SCALE_STEP = 0.08  # cuánto escala cada "muesca" de la rueda del mouse


class MiniWindow(QWidget):
    expandRequested = pyqtSignal()
    hideToTrayRequested = pyqtSignal()

    def __init__(self, backend, cover_loader, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cover_loader = cover_loader
        self._current_cover_url = ""
        self._cover_image = None
        self._bar_bg = None            # QPixmap difuminado para el fondo de la barra
        self._bar_bg_size = (0, 0)     # tamaño con el que se calculó, para no repetir trabajo
        # Velo oscuro adaptativo (ver theme.scrim_alpha_for): el alpha del
        # extremo claro se dimensiona para que el título alcance 4.5:1 sobre la
        # zona MÁS clara de la carátula. Antes era fijo (120 -> 195) y con una
        # portada blanca el texto caía a 2.9:1 y el artista en rojo a 1.0-3.0:1.
        self._scrim_lo = 120
        self._text_bg = (8, 8, 14)
        self._collapsed = False
        self._scale = 1.0
        self._last_state = None
        # En modo vinilo (colapsado), los controles (prev/play/next) están
        # ocultos por defecto y solo aparecen con un fundido mientras el
        # mouse está encima del disco — así el vinilo se ve "limpio" la
        # mayor parte del tiempo. No aplica al modo barra expandida, donde
        # los controles siempre están visibles como siempre.
        self._collapsed_controls_visible = False

        # Mismo sistema de acento dinámico que main_window.py (ver
        # accent.py): la carátula actual tiñe el borde, el anillo del
        # vinilo, la barra de progreso y el botón de play.
        self._accent_a_from = Palette.c(Palette.ACCENT_A)
        self._accent_b_from = Palette.c(Palette.ACCENT_B)
        self._accent_a_to = Palette.c(Palette.ACCENT_A)
        self._accent_b_to = Palette.c(Palette.ACCENT_B)
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self._transition_progress = 1.0
        self._transition_anim = QPropertyAnimation(self, b"transitionProgress", self)
        self._transition_anim.setDuration(420)
        self._transition_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.Tool)  # sin entrada en la barra de tareas
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._wire_events()
        self._apply_mode()

        self.cover_loader.coverReady.connect(self._on_cover_ready)
        self.cover_loader.colorsReady.connect(self._on_colors_ready)
        self.backend.stateChanged.connect(self.apply_state)
        self.apply_state(PlayerState())

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.vinyl = VinylCover(diameter=BASE_CIRCLE_D, shadow_margin=SHADOW_MARGIN, parent=self)
        self.vinyl.clicked.connect(self._toggle_collapsed)

        self.title_label = MarqueeLabel("Sin reproducción", self, align=Qt.AlignmentFlag.AlignLeft)
        self.artist_label = MarqueeLabel("WNP Player", self, align=Qt.AlignmentFlag.AlignLeft)
        self.seek_bar = SeekBar(self, height=10, bar_height=3)

        # Estos mismos botones se reutilizan (se reposicionan y redimensionan)
        # tanto en la barra expandida como superpuestos sobre el vinilo colapsado.
        self.prev_btn = IconButton("prev", size=30, icon_scale=0.5, parent=self)
        self.play_btn = IconButton("play", size=38, icon_scale=0.42, gradient_bg=True, parent=self)
        self.next_btn = IconButton("next", size=30, icon_scale=0.5, parent=self)
        self.prev_btn.setToolTip("Anterior")
        self.play_btn.setToolTip("Reproducir / Pausar")
        self.next_btn.setToolTip("Siguiente")

        self.expand_btn = IconButton("chevron_up", size=22, icon_scale=0.55, parent=self)
        self.expand_btn.setToolTip("Modo completo")
        self.close_btn = IconButton("close", size=22, icon_scale=0.4, parent=self)
        self.close_btn.setToolTip("Minimizar a la bandeja")

    def _wire_events(self):
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.prev_btn.clicked.connect(self.backend.previous)
        self.next_btn.clicked.connect(self.backend.next)
        self.seek_bar.seekRequested.connect(self.backend.seek_percent)
        self.expand_btn.clicked.connect(self.expandRequested.emit)
        self.close_btn.clicked.connect(self.hideToTrayRequested.emit)

        # El vinilo y los 3 botones son hijos que cubren casi toda el área
        # del modo colapsado — Qt manda leaveEvent al padre apenas el mouse
        # pasa a un hijo (y enterEvent de nuevo al volver), lo que causaría
        # parpadeo si confiáramos solo en enterEvent/leaveEvent de la
        # ventana. Por eso se escuchan Enter/Leave de LOS CINCO widgets acá,
        # y un Leave solo esconde los controles si, tras confirmar con la
        # posición real del cursor (_recheck_hover), el mouse quedó
        # realmente afuera de toda la ventana.
        for w in (self, self.vinyl, self.prev_btn, self.play_btn, self.next_btn):
            w.installEventFilter(self)

        # Red de seguridad: Enter/Leave puede fallar de forma intermitente
        # en Windows real cuando hay varios widgets hijos superpuestos
        # (comportamiento del sistema operativo al entregar esos eventos,
        # no controlable desde acá con certeza) — el síntoma reportado fue
        # exactamente "a veces oculta los controles bien, a veces no". En
        # vez de perseguir cada caso posible de evento perdido, este timer
        # reverifica la posición real del cursor cada 150ms mientras está
        # en modo vinilo: si un Enter/Leave se perdió, el estado se
        # autocorrige solo en menos de 150ms, sin que se note. Barato
        # (una comparación de distancias, nada de repintado si no cambia
        # nada) y solo corre en modo colapsado.
        self._hover_poll_timer = QTimer(self)
        self._hover_poll_timer.setInterval(150)
        self._hover_poll_timer.timeout.connect(self._recheck_hover)

    def eventFilter(self, obj, event):
        if self._collapsed:
            t = event.type()
            if t in (QEvent.Type.Enter, QEvent.Type.Leave):
                # Tanto Enter como Leave solo reflejan que el mouse cruzó el
                # borde del RECTÁNGULO de algún widget — ninguno de los dos
                # alcanza para decidir mostrar/ocultar por sí solo (el
                # rectángulo incluye las esquinas transparentes fuera del
                # disco). Por eso ambos casos delegan en la misma
                # verificación real: círculo del vinilo vs. posición actual
                # del cursor (ver _point_in_vinyl_hover_zone). El
                # singleShot(0) espera a que Qt termine de entregar este
                # lote de eventos (p. ej. el Enter del widget vecino al que
                # se pasó el mouse) antes de decidir.
                QTimer.singleShot(0, self._recheck_hover)
        return super().eventFilter(obj, event)

    def _recheck_hover(self):
        if not self._collapsed:
            return
        local = self.mapFromGlobal(QCursor.pos())
        if self._point_in_vinyl_hover_zone(local):
            self._show_collapsed_controls()
        else:
            self._hide_collapsed_controls()

    def _point_in_vinyl_hover_zone(self, point) -> bool:
        """El área de hover real es el CÍRCULO del disco, no el cuadrado
        invisible que lo contiene (self.rect() incluye las esquinas
        transparentes alrededor del disco, que visualmente están "afuera
        de la carátula" — de ahí el bug: los controles quedaban visibles
        con el mouse en una esquina vacía, fuera del vinilo)."""
        center = self.vinyl.geometry().center()
        dx = point.x() - center.x()
        dy = point.y() - center.y()
        # Un pelín más que el radio visible (hasta el borde del margen de
        # sombra) para que no se sienta "esquivo" justo en el borde.
        radius = self.vinyl._diameter / 2 + SHADOW_MARGIN
        return (dx * dx + dy * dy) <= radius * radius

    def _show_collapsed_controls(self):
        if self._collapsed_controls_visible:
            return
        self._collapsed_controls_visible = True
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.set_reveal_animated(1.0)

    def _hide_collapsed_controls(self):
        if not self._collapsed_controls_visible:
            return
        self._collapsed_controls_visible = False
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.set_reveal_animated(0.0)


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
        self.play_btn.setEnabled(self._play_enabled(state))

    def _on_play_clicked(self):
        # Reacción optimista, basada en lo que el botón YA muestra (no en
        # self._last_state, que solo se refresca cada ~150ms y haría que
        # un doble clic rápido calculara la misma predicción dos veces en
        # vez de alternar entre sí). Ver la nota más larga en main_window.py.
        if self.backend.has_no_player():
            self.backend.toggle_play_pause()
            return
        will_play = self.play_btn.icon_name != "pause"
        self.play_btn.set_icon("pause" if will_play else "play")
        self.vinyl.set_spinning(will_play)
        self.backend.toggle_play_pause()

    # --------------------------------------------------------- modo barra/disco
    _MODE_FADE_MS = 110

    def _toggle_collapsed(self):
        self._set_collapsed(not self._collapsed)

    def _set_collapsed(self, collapsed: bool):
        if collapsed == self._collapsed:
            return
        if getattr(self, "_mode_anim", None) is not None:
            self._mode_anim.stop()
            self._mode_anim = None
        # Ancla: el centro del vinilo debe quedar en el mismo punto de pantalla
        # antes y después del cambio de modo, para que no "salte".
        self._pending_anchor_global = self.mapToGlobal(self._vinyl_rect(self._collapsed).center())
        self._pending_collapsed = collapsed
        self._animate_to_pending_mode()

    def _animate_to_pending_mode(self):
        """Pequeño fundido cruzado al alternar barra <-> vinilo: en vez de
        que el layout cambie de golpe, la ventana se desvanece un poco,
        cambia de modo (ya con el tamaño/posición nuevos) y vuelve a
        aparecer. Es una transición leve, no un morphing de geometría."""
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(self._MODE_FADE_MS)
        fade_out.setStartValue(self.windowOpacity())
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade_out.finished.connect(self._apply_pending_mode_and_fade_in)
        self._mode_anim = fade_out
        fade_out.start()

    def _apply_pending_mode_and_fade_in(self):
        self._collapsed = self._pending_collapsed
        self._apply_mode()
        new_rect = self._vinyl_rect(self._collapsed)
        self.move(self._pending_anchor_global - new_rect.center())

        fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        fade_in.setDuration(self._MODE_FADE_MS + 30)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._mode_anim = fade_in
        fade_in.start()

    # -------------------------------------------------------------- acento
    def _get_transition_progress(self) -> float:
        return self._transition_progress

    def _set_transition_progress(self, value: float):
        self._transition_progress = value
        a = _lerp_color(self._accent_a_from, self._accent_a_to, value)
        b = _lerp_color(self._accent_b_from, self._accent_b_to, value)
        self._accent_a = a
        self._accent_b = b
        rgb_a = (a.red(), a.green(), a.blue())
        rgb_b = (b.red(), b.green(), b.blue())
        self.vinyl.set_accent(rgb_a, rgb_b)
        self.seek_bar.set_accent(rgb_a, rgb_b)
        self.play_btn.set_accent(rgb_a, rgb_b)
        self._refresh_artist_color()
        self.update()

    transitionProgress = pyqtProperty(float, _get_transition_progress, _set_transition_progress)

    def _refresh_artist_color(self):
        """Acento dinámico como texto del artista, aclarado solo lo necesario
        para llegar a 4.5:1 contra el fondo real detrás del texto."""
        a = self._accent_a
        rgb = theme_module.ensure_contrast((a.red(), a.green(), a.blue()), self._text_bg, 4.5)
        self.artist_label.set_color(QColor(*rgb))

    def _on_colors_ready(self, url: str, accent_a: tuple, accent_b: tuple):
        if url != self._current_cover_url:
            return
        self._transition_anim.stop()
        self._accent_a_from = self._accent_a
        self._accent_b_from = self._accent_b
        self._accent_a_to = QColor(*accent_a)
        self._accent_b_to = QColor(*accent_b)
        self._transition_progress = 0.0
        self._transition_anim.setStartValue(0.0)
        self._transition_anim.setEndValue(1.0)
        self._transition_anim.start()

    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float):
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        if abs(scale - self._scale) < 0.004:
            return
        # Al redimensionar (a diferencia de al alternar de modo) internamente
        # se conserva la esquina superior izquierda de la ventana; quien
        # llama a set_scale (p.ej. wheelEvent) se encarga de recentrar si
        # quiere que el zoom se sienta anclado a otro punto.
        self._scale = scale
        self._apply_mode()

    def _vinyl_rect(self, collapsed: bool) -> QRect:
        s = self._scale
        if collapsed:
            d = round((BASE_COLLAPSED_CIRCLE_D) * s) + SHADOW_MARGIN * 2
            pad = round(BASE_COLLAPSED_PAD * s)
            return QRect(pad, pad, d, d)
        d = round(BASE_CIRCLE_D * s) + SHADOW_MARGIN * 2
        margin = round(BASE_MARGIN * s)
        return QRect(margin - SHADOW_MARGIN, margin - SHADOW_MARGIN, d, d)

    def _apply_mode(self):
        if self._collapsed:
            self._layout_collapsed()
        else:
            self._layout_expanded()
        self.update()

    def _layout_expanded(self):
        # En modo barra los controles son siempre visibles (el hover con
        # fundido es exclusivo del modo vinilo/colapsado).
        self._collapsed_controls_visible = False
        self._hover_poll_timer.stop()
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn._reveal_anim.stop()
            btn._reveal = 1.0

        s = self._scale
        margin = round(BASE_MARGIN * s)
        overflow = round(BASE_OVERFLOW * s)
        bar_w = round(BASE_BAR_W * s)
        bar_h = round(BASE_BAR_H * s)
        circle_d = round(BASE_CIRCLE_D * s)
        overlap_x = round(BASE_CIRCLE_OVERLAP_X * s)

        bar_x = margin + overlap_x
        bar_y = margin + overflow
        total_w = bar_x + bar_w + margin
        total_h = bar_y + bar_h + margin
        self.setFixedSize(total_w, total_h)
        self._cur_bar_rect = QRect(bar_x, bar_y, bar_w, bar_h)

        self.vinyl.set_diameter(circle_d)
        self.vinyl.move(margin - SHADOW_MARGIN, margin - SHADOW_MARGIN)
        self.vinyl.raise_()

        intrusion = circle_d - overlap_x   # cuánto invade el vinilo la barra
        pad = round(12 * s)
        content_x = bar_x + intrusion + round(12 * s)
        content_right = bar_x + bar_w - pad
        content_top = bar_y + pad
        content_bottom = bar_y + bar_h - pad

        side = round(22 * s)
        self.expand_btn.setFixedSize(side, side)
        self.close_btn.setFixedSize(side, side)
        side_x = content_right - side
        self.expand_btn.move(side_x, content_top - round(2 * s))
        self.close_btn.move(side_x, content_top + round(24 * s))

        btn_prev_next = round(30 * s)
        btn_play = round(38 * s)
        self.prev_btn.setFixedSize(btn_prev_next, btn_prev_next)
        self.play_btn.setFixedSize(btn_play, btn_play)
        self.next_btn.setFixedSize(btn_prev_next, btn_prev_next)
        gap = round(4 * s)
        controls_w = btn_prev_next * 2 + btn_play + gap * 2
        controls_x = side_x - round(10 * s) - controls_w
        controls_y = content_top + (content_bottom - content_top - btn_play) // 2
        self.prev_btn.move(controls_x, controls_y + (btn_play - btn_prev_next) // 2)
        self.play_btn.move(controls_x + btn_prev_next + gap, controls_y)
        self.next_btn.move(controls_x + btn_prev_next + gap + btn_play + gap,
                            controls_y + (btn_play - btn_prev_next) // 2)

        text_right = controls_x - round(12 * s)
        text_w = max(40, text_right - content_x)
        # Antes: QFont(familia, N) interpreta N como PUNTOS (~33 % más grande que
        # los píxeles que el cálculo pretendía) y las etiquetas medían 18 y 14 px
        # fijos: el título se salía de su caja y pisaba al artista. Ahora el
        # tamaño va en píxeles y la altura sale de las métricas reales de la fuente.
        title_font = QFont(FONT_BODY)
        title_font.setPixelSize(max(11, round(15 * s)))
        title_font.setWeight(QFont.Weight.Bold)
        artist_font = QFont(FONT_BODY)
        artist_font.setPixelSize(max(10, round(12 * s)))
        artist_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.set_color(Palette.c(Palette.TEXT))
        self.artist_label.setFont(artist_font)
        self._refresh_artist_color()
        title_h = QFontMetrics(title_font).height() + 2
        artist_h = QFontMetrics(artist_font).height() + 2
        # Bloque título + artista centrado entre el borde superior del contenido y la barra de progreso
        block_h = title_h + artist_h
        avail_h = (content_bottom - 10 - 4) - content_top
        block_top = content_top + max(0, (avail_h - block_h) // 2)
        self.title_label.setGeometry(content_x, block_top, text_w, title_h)
        self.artist_label.setGeometry(content_x, block_top + title_h, text_w, artist_h)
        self.seek_bar.setGeometry(content_x, content_bottom - 10, text_w, 10)

        for w in (self.title_label, self.artist_label, self.seek_bar,
                  self.prev_btn, self.play_btn, self.next_btn,
                  self.expand_btn, self.close_btn):
            w.setVisible(True)
            w.raise_()
        self.vinyl.raise_()

        self._refresh_bar_background()

    def _layout_collapsed(self):
        # Arranca oculto; el timer de sondeo (ver _wire_events) lo corrige
        # solo en <=150ms si el mouse ya estaba encima al cambiar de modo
        # — no hace falta detectarlo de entrada acá.
        self._collapsed_controls_visible = False
        if self.isVisible():
            self._hover_poll_timer.start()

        s = self._scale
        circle_d = round(BASE_COLLAPSED_CIRCLE_D * s)
        pad = round(BASE_COLLAPSED_PAD * s)
        outer = circle_d + SHADOW_MARGIN * 2
        total = outer + pad * 2
        self.setFixedSize(total, total)

        self.vinyl.set_diameter(circle_d)
        self.vinyl.move(pad, pad)
        self.vinyl.raise_()

        for w in (self.title_label, self.artist_label, self.seek_bar,
                  self.expand_btn, self.close_btn):
            w.setVisible(False)

        btn_prev_next = round(26 * s)
        btn_play = round(34 * s)
        self.prev_btn.setFixedSize(btn_prev_next, btn_prev_next)
        self.play_btn.setFixedSize(btn_play, btn_play)
        self.next_btn.setFixedSize(btn_prev_next, btn_prev_next)
        gap = round(8 * s)

        # Los controles se dibujan como círculos flotando sobre el disco, así
        # que hay que garantizar que cada botón (círculo completo, no solo su
        # caja) quepa dentro del radio del vinilo. Se calcula geométricamente
        # en vez de usar un desplazamiento fijo, para que nunca se salgan del
        # disco sea cual sea la escala.
        disc_cx = pad + SHADOW_MARGIN + circle_d / 2   # == total / 2
        disc_cy = pad + SHADOW_MARGIN + circle_d / 2   # == total / 2 (disco cuadrado)
        r = circle_d / 2
        safe_r = r * 0.94  # deja un pequeño margen respecto al borde del disco

        rp = btn_play / 2
        rs = btn_prev_next / 2

        # Offset vertical del centro de la fila de botones respecto al
        # centro del disco (hacia abajo, para no tapar la etiqueta central).
        dy = min(r * 0.40, max(0.0, safe_r - rp))

        # Offset horizontal del centro de prev/next, ajustado para que su
        # círculo (radio rs) quepa dentro de safe_r junto con ese dy.
        max_reach_sq = max(0.0, (safe_r - rs) ** 2 - dy ** 2)
        dx = min(rp + gap + rs, max_reach_sq ** 0.5)

        btn_y_center = disc_cy + dy
        self.play_btn.move(int(disc_cx - rp), int(btn_y_center - rp))
        self.prev_btn.move(int(disc_cx - dx - rs), int(btn_y_center - rs))
        self.next_btn.move(int(disc_cx + dx - rs), int(btn_y_center - rs))

        for w in (self.prev_btn, self.play_btn, self.next_btn):
            w.setVisible(True)
            w.raise_()
            w._reveal_anim.stop()
            w._reveal = 0.0 if not self._collapsed_controls_visible else 1.0

    # ------------------------------------------------------------- estado
    def apply_state(self, state: PlayerState):
        if self._last_state is not None and state == self._last_state:
            return
        self._last_state = state

        if state.has_media:
            self.title_label.setText(state.title or "Sin título")
            self.artist_label.setText(state.artist or "Artista desconocido")
        else:
            self.title_label.setText("Sin reproducción")
            self.artist_label.setText("WNP Player")

        self.seek_bar.set_percent(state.position_percent)
        # Ver comentario equivalente en main_window.py: sin duración real
        # conocida (p. ej. Telegram, Bug #10 en pywnp_patch.py) el arrastre
        # no serviría de nada, así que se deshabilita.
        self.seek_bar.set_seekable(state.controls_available and state.duration_known)
        self.seek_bar.set_duration_seconds(state.duration_seconds)

        self.play_btn.set_icon("pause" if state.state == "PLAYING" else "play")
        self._apply_play_enabled(state)
        self.prev_btn.setEnabled(state.controls_available)
        self.next_btn.setEnabled(state.controls_available)

        self.vinyl.set_spinning(state.state == "PLAYING")

        if state.cover_url != self._current_cover_url:
            self._current_cover_url = state.cover_url
            if state.cover_url:
                self.cover_loader.request(state.cover_url)
            else:
                self._set_cover_image(None)
                self._transition_anim.stop()
                self._accent_a_from = self._accent_a
                self._accent_b_from = self._accent_b
                self._accent_a_to = Palette.c(Palette.ACCENT_A)
                self._accent_b_to = Palette.c(Palette.ACCENT_B)
                self._transition_progress = 0.0
                self._transition_anim.setStartValue(0.0)
                self._transition_anim.setEndValue(1.0)
                self._transition_anim.start()

    def _on_cover_ready(self, url, image):
        if url == self._current_cover_url:
            self._set_cover_image(image if not image.isNull() else None)

    def _set_cover_image(self, image):
        self._cover_image = image
        self.vinyl.set_image(image)
        if image is not None and not image.isNull():
            self._scrim_lo = theme_module.scrim_alpha_for(
                image, fg=Palette.TEXT, scrim=(8, 8, 14), minimum=4.5, lo=120, hi=225)
            cell = theme_module.brightest_cell_rgb(image)
            self._text_bg = theme_module.blend_over((8, 8, 14), cell, self._scrim_lo / 255.0)
        else:
            self._scrim_lo = 120
            self._text_bg = (8, 8, 14)
        self._refresh_artist_color()
        self._bar_bg_size = (0, 0)  # fuerza recalcular el fondo con la nueva carátula
        self._refresh_bar_background()
        self.update()

    def _refresh_bar_background(self):
        """Recalcula el fondo difuminado de la barra solo si hace falta
        (cambió la carátula o cambió el tamaño por zoom con la rueda): es
        la clave de que sea barato en CPU incluso mientras se escala."""
        if self._collapsed:
            return
        rect = getattr(self, "_cur_bar_rect", None)
        if rect is None:
            return
        size = (rect.width(), rect.height())
        if self._cover_image is None:
            if self._bar_bg is not None:
                self._bar_bg = None
                self._bar_bg_size = (0, 0)
                self.update()
            return
        if size == self._bar_bg_size:
            return
        blurred = blur_image(self._cover_image, size[0], size[1], strength=1)  # o 0 para sin blur
        self._bar_bg = QPixmap.fromImage(blurred) if not blurred.isNull() else None
        self._bar_bg_size = size
        self.update()

    # -------------------------------------------------------------- pintura
    def paintEvent(self, event):
        if self._collapsed:
            return  # en modo disco no hay barra que dibujar (el vinilo se pinta solo)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_rect = QRectF(self._cur_bar_rect)
        radius = 20 * self._scale

        shadow = QPainterPath()
        shadow.addRoundedRect(bar_rect.translated(0, 3), radius, radius)
        painter.fillPath(shadow, QColor(0, 0, 0, 90))

        bg_path = QPainterPath()
        bg_path.addRoundedRect(bar_rect, radius, radius)

        painter.save()
        painter.setClipPath(bg_path)
        if self._bar_bg is not None:
            # El pixmap ya viene escalado al ancho exacto de la barra, pero
            # puede ser más alto (o más bajo) que ella: se centra
            # verticalmente y se deja que el clip recorte lo que sobre, en
            # vez de estirarlo para que encaje exacto.
            bg_x = bar_rect.left() + (bar_rect.width() - self._bar_bg.width()) / 2
            bg_y = bar_rect.top() + (bar_rect.height() - self._bar_bg.height()) / 2
            painter.drawPixmap(QRectF(bg_x, bg_y, self._bar_bg.width(), self._bar_bg.height()).toRect(),
                                self._bar_bg)
        else:
            painter.fillPath(bg_path, Palette.c(Palette.BG_BASE, 245))
        # velo oscuro para que el texto se lea bien sobre cualquier carátula
        scrim = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomRight())
        scrim.setColorAt(0.0, QColor(8, 8, 14, self._scrim_lo))
        scrim.setColorAt(1.0, QColor(8, 8, 14, max(195, min(245, self._scrim_lo + 30))))
        painter.fillPath(bg_path, scrim)
        painter.restore()

        grad = QLinearGradient(bar_rect.topLeft(), bar_rect.bottomRight())
        grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                     self._accent_a.blue(), 170))
        grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                     self._accent_b.blue(), 170))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(grad, 1.3))
        painter.drawPath(bg_path)
        painter.end()

    # -------------------------------------------------------------- arrastre
    # (el arrastre normal de la ventana se hace por el propio VinylCover;
    # esto cubre el arrastre al pulsar sobre el resto de la barra)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, "_drag_pos", None) is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def showEvent(self, event):
        super().showEvent(event)
        if self._collapsed and not self._hover_poll_timer.isActive():
            self._hover_poll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._hover_poll_timer.stop()
        # Con la ventana oculta no tiene sentido dejar los controles
        # "revelados" esperando — al volver a mostrarla debe arrancar
        # igual que cualquier otra vez: oculta, hasta que el sondeo (o un
        # Enter real) confirme que el mouse está encima.
        if self._collapsed:
            self._hide_collapsed_controls()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            if self.play_btn.isEnabled():
                self._on_play_clicked()
            event.accept()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_MediaNext):
            if self.next_btn.isEnabled():
                self.backend.next()
            event.accept()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_MediaPrevious):
            if self.prev_btn.isEnabled():
                self.backend.previous()
            event.accept()
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------------------- zoom
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        steps = delta / 120.0  # una "muesca" estándar de rueda
        old_center = self.frameGeometry().center()
        self.set_scale(self._scale + steps * _WHEEL_SCALE_STEP)
        new_center = self.frameGeometry().center()
        if new_center != old_center:
            # el tamaño cambia desde la esquina superior izquierda; se
            # recoloca para que el centro de la ventana no "salte".
            self.move(self.pos() + (old_center - new_center))
        event.accept()
