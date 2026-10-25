"""Ventana principal: reproductor completo con carátula, progreso y controles."""
import math
import time

from PyQt6.QtCore import (
    Qt, QPoint, QPointF, QRect, QRectF, QUrl, pyqtSignal, pyqtProperty, QPropertyAnimation, QEasingCurve, QTimer,
)
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QLinearGradient, QFont, QPen, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMenu
)

from theme import Palette, FONT_BODY, FONT_MONO, font_px, mark_configurable_scale
import theme as theme_module
from widgets import (IconButton, SeekBar, VolumeBar, CoverArt, MarqueeLabel, LyricsPanel, PlayingIndicator,
                     ElidedLabel, PlatformPickerButton, LIKE_RGB, blur_image_hq)
import player_launcher
from backend import PlayerState
from dialogs import PortDialog, AboutDialog
from youtube_api import VideoLinkResolver

WIDTH = 356
COVER_SIZE = 196

# Rango de tamaño alcanzable con el zoom (rueda del mouse). El ancho de la
# carátula escala en proporción al ancho de la columna de contenido; el
# alto se recalcula solo a partir del layout, así que nunca queda un hueco
# en blanco ni se recorta nada. Estos rangos aplican solo a la columna de
# contenido (carátula, controles...), no al panel de letra opcional.
MIN_WIDTH = 320   # antes 300: la fila de controles necesita 306 px como mínimo (ver _apply_content_width)
MAX_WIDTH = 460
MIN_COVER = 150
MAX_COVER = 260

# Ancho fijo del panel de letra opcional que puede mostrarse a la
# izquierda o a la derecha de la columna de contenido (según qué flecha
# lateral se use). No escala con el zoom (a propósito, para simplicidad):
# es un ancho fijo razonable para leer letras cómodamente.
LYRICS_PANEL_WIDTH = 240
LYRICS_PANEL_ANIM_MS = 240

# Flechas laterales que abren el panel de letra hacia ese lado con un
# clic (ver _build_lyrics_arrows / _on_lyrics_arrow_clicked). Se dibujan
# como una "montañita": un semicírculo que sobresale del borde redondeado
# de la tarjeta principal, no un botón flotando por dentro. Para lograrlo,
# se reserva un margen transparente a cada lado (BUMP_MARGIN) por fuera de
# la tarjeta, y en ese margen se pinta un círculo cuya mitad interior queda
# tapada por la propia tarjeta (ver paintEvent / _draw_lyrics_bumps) — solo
# se ve la mitad exterior, como un bulto pegado al borde.
LYRICS_ARROW_SIZE = 26
BUMP_MARGIN = 30
BUMP_RADIUS = 20

STATE_LABELS = {
    "PLAYING": "REPRODUCIENDO",
    "PAUSED": "EN PAUSA",
    "STOPPED": "EN ESPERA",
}

# Mismo orden que usa el ciclo real en pywnp_patch.py (apagado -> todo ->
# una canción -> apagado), para que la reacción optimista al hacer clic
# adivine el mismo estado que va a confirmar el backend.
REPEAT_CYCLE = {"NONE": "ALL", "ALL": "ONE", "ONE": "NONE"}


# Cuánto cambia el ancho de la ventana por cada "muesca" de la rueda del
# mouse (una muesca estándar = 120 en angleDelta).
WHEEL_WIDTH_STEP = 22


def _lerp_qcolor(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


class MainWindow(QWidget):
    compactModeRequested = pyqtSignal()
    dockModeRequested = pyqtSignal()
    hideToTrayRequested = pyqtSignal()
    quitRequested = pyqtSignal()
    portChangeRequested = pyqtSignal(int)
    startMinimizedToggleRequested = pyqtSignal(bool)
    hotkeyDialogRequested = pyqtSignal()
    settingsDialogRequested = pyqtSignal()
    welcomeDialogRequested = pyqtSignal()
    recentlyPlayedRequested = pyqtSignal()
    startPlayerRequested = pyqtSignal(str)    # acción de player_launcher.ALL_ACTIONS
    likeToggleRequested = pyqtSignal()        # clic en el corazón de "me gusta"

    def __init__(self, backend, cover_loader, lyrics_loader=None, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cover_loader = cover_loader
        self.lyrics_loader = lyrics_loader
        self._always_on_top = False
        self.start_minimized_enabled = False
        self._current_cover_url = ""
        self._last_state: PlayerState | None = None
        self._youtube_api_key = ""
        self._video_resolver = VideoLinkResolver()
        self._video_resolver.linkResolved.connect(
            lambda url: QDesktopServices.openUrl(QUrl(url)) if url else None
        )

        # Ancho de la columna de contenido (carátula, controles...), la
        # parte que responde al zoom con la rueda del mouse. self.width()
        # ya no representa esto solo: ahora es content_width + panel_width
        # (el panel de letra puede sumar ancho extra a la derecha).
        self._content_width = WIDTH
        self._panel_width = 0.0
        self._lyrics_panel_enabled = False
        self._lyrics_panel_side = "right"   # "left" | "right"
        self._panel_track_key = None
        self._duration_seconds = 0

        # Espacio transparente reservado a cada lado, POR FUERA de la
        # tarjeta redondeada, para que las flechas de letra sobresalgan
        # como una montañita en vez de flotar por dentro (ver
        # _draw_lyrics_bumps). Solo existe si hay letras disponibles.
        self._side_margin = BUMP_MARGIN if lyrics_loader is not None else 0

        # --- Acento de color dinámico + fondo ambiente (ver accent.py) ---
        # Colores "actuales" mostrados ahora mismo y colores "anteriores"
        # (para poder animar la transición entre uno y otro en vez de
        # saltar de golpe cuando cambia la canción).
        self._accent_a_from = Palette.c(Palette.ACCENT_A)
        self._accent_b_from = Palette.c(Palette.ACCENT_B)
        self._accent_a_to = Palette.c(Palette.ACCENT_A)
        self._accent_b_to = Palette.c(Palette.ACCENT_B)
        self._accent_a = Palette.c(Palette.ACCENT_A)  # valor ya interpolado de este frame
        self._accent_b = Palette.c(Palette.ACCENT_B)
        # Imagen fuente (sin difuminar) de la carátula actual/anterior —
        # guardamos la referencia liviana; el difuminado en sí (blur_image,
        # de widgets.py) se calcula bajo demanda al tamaño real de la
        # ventana en _regenerate_ambient_bg, así que no repetimos ese
        # trabajo salvo cuando cambia la canción o el tamaño de la ventana.
        self._ambient_source_from = None
        self._ambient_source_to = None
        self._ambient_big_from = None   # QImage ya difuminada y cacheada al tamaño actual
        self._ambient_big_to = None
        self._ambient_cache_size = None
        # Velo oscuro adaptativo: alpha mínimo para que el texto secundario
        # alcance 4.5:1 sobre la parte MÁS clara de la carátula (antes fijo en
        # 195: con una portada blanca el texto tenue quedaba en 1.7-3.3:1).
        self._scrim_from = 195
        self._scrim_to = 195
        self._text_bg = Palette.BG_BASE     # fondo estimado detrás del texto (para el acento como texto)

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        # Qt.WindowType.Tool: la ventana no aparece en la barra de tareas de
        # Windows (solo queda el ícono de la bandeja/system tray). No afecta
        # el foco ni el arrastre — sigue siendo una ventana normal en todo
        # lo demás, Windows simplemente no le crea entrada en la taskbar.
        self.setWindowFlag(Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("WNP Player")
        self.resize(WIDTH, self.height())

        self._adjusting = False
        self._drag_pos = None
        self._press_local_pos = None
        self._press_on_link_area = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()
        self._wire_events()
        self._apply_content_width(self._content_width)  # incluye self._side_margin

        self._panel_anim = QPropertyAnimation(self, b"panelWidth", self)
        self._panel_anim.setDuration(LYRICS_PANEL_ANIM_MS)
        self._panel_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Anima a la vez: el color de acento (borde, halo, barra de
        # progreso, botón de play) Y el crossfade del fondo ambiente. Van
        # juntos porque ambos representan lo mismo (la transición de una
        # canción a la siguiente) y así se ven perfectamente sincronizados
        # en vez de como dos animaciones independientes por casualidad
        # parecidas.
        self._transition_progress = 1.0
        self._transition_anim = QPropertyAnimation(self, b"transitionProgress", self)
        self._transition_anim.setDuration(420)
        self._transition_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Halo "respirando" detrás de la carátula: solo corre mientras hay
        # reproducción activa (PLAYING), para que la ventana se sienta viva
        # sin gastar CPU de más cuando no hay nada sonando. Se maneja con
        # un QTimer propio de baja frecuencia (igual que PlayingIndicator
        # en widgets.py) en vez de QPropertyAnimation: el driver de
        # animaciones de Qt tick-ea por defecto a ~60fps, y para un efecto
        # tan lento y sutil como este alcanza y sobra con ~12fps — un
        # cuarto del costo de repintado, sin diferencia perceptible.
        self._glow_phase = 0.0
        self._glow_last = None
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(80)  # ~12fps
        self._glow_timer.timeout.connect(self._on_glow_tick)
        self._glow_playing = False

        # Debounce para _regenerate_ambient_bg(): cada llamada cuesta unos
        # 5-8ms (es un blur gaussiano real, ver blur_image_hq en
        # widgets.py) — barato una vez, pero durante un resize CONTINUO
        # (la animación de abrir el panel de letra, o hacer zoom con la
        # rueda) el tamaño cambia en casi cada frame, y regenerar en cada
        # uno competía por tiempo de CPU con la propia animación,
        # sintiéndose como tirones. En vez de regenerar en cada tamaño
        # intermedio, se sigue mostrando la última imagen buena (estirada
        # gratis por Qt si hace falta) mientras el tamaño sigue cambiando,
        # y recién se regenera en calidad completa cuando el tamaño se
        # "asienta" (sin cambios por 120ms).
        self._ambient_resize_timer = QTimer(self)
        self._ambient_resize_timer.setSingleShot(True)
        self._ambient_resize_timer.setInterval(120)
        self._ambient_resize_timer.timeout.connect(self._regenerate_ambient_bg)

        self.cover_loader.coverReady.connect(self._on_cover_ready)
        self.cover_loader.colorsReady.connect(self._on_colors_ready)
        self.backend.stateChanged.connect(self.apply_state)
        self.backend.connectionChanged.connect(self._on_connection_changed)
        self.backend.serverError.connect(self._on_server_error)

        # Aspecto Cosmos: cielo estrellado cacheado + estrellas fugaces ocasionales
        # (solo suenan/visibles/con corriente; ver cosmos_sky.py). En el aspecto
        # predeterminado ambos quedan en None y paintEvent se comporta como siempre.
        self._sky = None
        self._stars = None
        if theme_module.is_cosmos():
            from cosmos_sky import CosmosSky, ShootingStars
            self._sky = CosmosSky()
            self._stars = ShootingStars(self, self._shooting_stars_allowed)
            self._stars.start()

        self.apply_state(PlayerState())

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(self._side_margin, 0, self._side_margin, 0)
        outer.setSpacing(0)

        # --- Columna de contenido (todo lo que había antes: carátula,
        # título, controles...). Vive en su propio widget para que el
        # panel de letra opcional pueda sumarse como segunda columna sin
        # que el zoom (que solo afecta a esta columna) se vea alterado.
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_widget.setFixedWidth(self._content_width)
        outer.addWidget(self.content_widget)

        root = QVBoxLayout(self.content_widget)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(0)

        # --- Barra superior ---
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.playing_indicator = PlayingIndicator()
        top_row.addWidget(self.playing_indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self.eyebrow_label = mark_configurable_scale(ElidedLabel("EN ESPERA"))
        self.eyebrow_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: {font_px(10)}px; font-weight: 700; letter-spacing: 1px; background: transparent;"
        )
        top_row.addWidget(self.eyebrow_label, 1)

        self.menu_btn = IconButton("gear", size=26, icon_scale=0.5)
        self.menu_btn.setToolTip("Menú")
        top_row.addWidget(self.menu_btn)

        self.compact_btn = IconButton("chevron_down", size=26, icon_scale=0.55)
        self.compact_btn.setToolTip("Modo compacto")
        top_row.addWidget(self.compact_btn)

        self.minimize_btn = IconButton("minus", size=26, icon_scale=0.5)
        self.minimize_btn.setToolTip("Minimizar a la bandeja")
        top_row.addWidget(self.minimize_btn)

        self.close_btn = IconButton("close", size=26, icon_scale=0.42)
        self.close_btn.setToolTip("Cerrar")
        top_row.addWidget(self.close_btn)

        root.addLayout(top_row)
        root.addSpacing(18)

        # --- Carátula ---
        cover_row = QHBoxLayout()
        cover_row.addStretch(1)
        self.cover = CoverArt(size=COVER_SIZE)
        self.cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cover_row.addWidget(self.cover)
        cover_row.addStretch(1)
        root.addLayout(cover_row)
        root.addSpacing(18)

        # --- Título / artista ---
        # MarqueeLabel: si el texto no cabe, se desliza en vez de solo
        # cortarlo con "...". Al ser un widget pintado a mano (no un
        # QLabel), la fuente y el color se pasan directo, no por QSS.
        self.title_label = MarqueeLabel(
            "Sin reproducción",
            font=QFont(FONT_BODY, font_px(17), QFont.Weight.Bold),
            color=Palette.c(Palette.TEXT),
        )
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self.title_label)
        root.addSpacing(4)

        self.artist_label = MarqueeLabel(
            "Abre YouTube, Spotify u otro sitio compatible",
            font=QFont(FONT_BODY, font_px(12), QFont.Weight.DemiBold),
            color=Palette.c(Palette.ACCENT_A),
        )
        self.artist_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        root.addWidget(self.artist_label)
        root.addSpacing(20)

        # --- Progreso ---
        self.seek_bar = SeekBar()
        root.addWidget(self.seek_bar)

        time_row = QHBoxLayout()
        self.position_label = mark_configurable_scale(QLabel("0:00"))
        self.position_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_MONO}'; font-size: {font_px(10.5)}px; "
            f"background: transparent;"
        )
        self.duration_label = mark_configurable_scale(QLabel("0:00"))
        # AlignRight a secas REEMPLAZA el valor por defecto (derecha + centro vertical) y
        # deja la etiqueta pegada ARRIBA; si la fila se estira (ventana alta / letra grande)
        # la hora izquierda quedaba centrada y la derecha más arriba.
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.duration_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_MONO}'; font-size: {font_px(10.5)}px; "
            f"background: transparent;"
        )
        time_row.addWidget(self.position_label)
        time_row.addWidget(self.duration_label)
        root.addLayout(time_row)
        root.addSpacing(18)

        # --- Controles ---
        controls_row = QHBoxLayout()
        controls_row.setSpacing(14)
        controls_row.addStretch(1)

        self.shuffle_btn = IconButton("shuffle", size=34, icon_scale=0.44)
        self.shuffle_btn.setToolTip("Reproducción aleatoria")
        controls_row.addWidget(self.shuffle_btn)

        self.prev_btn = IconButton("prev", size=42, icon_scale=0.5)
        self.prev_btn.setToolTip("Anterior")
        controls_row.addWidget(self.prev_btn)

        self.play_btn = IconButton("play", size=58, icon_scale=0.42, gradient_bg=True)
        self.play_btn.setToolTip("Reproducir / Pausar")
        controls_row.addWidget(self.play_btn)

        self.next_btn = IconButton("next", size=42, icon_scale=0.5)
        self.next_btn.setToolTip("Siguiente")
        controls_row.addWidget(self.next_btn)

        self.repeat_btn = IconButton("repeat", size=34, icon_scale=0.44)
        self.repeat_btn.setToolTip("Repetir")
        controls_row.addWidget(self.repeat_btn)

        controls_row.addStretch(1)
        root.addLayout(controls_row)
        root.addSpacing(18)

        # --- Volumen ---
        volume_row = QHBoxLayout()
        volume_row.setSpacing(10)
        self.volume_icon = IconButton("speaker", size=22, icon_scale=0.62, bg=None)
        self.volume_icon.setEnabled(False)   # se habilita en apply_state si la fuente permite volumen
        self._premute_volume = 0
        volume_row.addWidget(self.volume_icon)
        self.volume_bar = VolumeBar(height=16, bar_height=6)
        self.volume_bar.set_percent(100)
        volume_row.addWidget(self.volume_bar)
        root.addLayout(volume_row)
        root.addSpacing(16)

        # --- Pie: plataforma actual (antes decía "Conectado · N
        # cliente(s)", texto que no aportaba nada útil en el uso diario;
        # ahora este mismo lugar muestra la plataforma que está sonando,
        # y sigue sirviendo para mostrar un error puntual si lo hay, ver
        # _on_server_error). ---
        footer_row = QHBoxLayout()
        # Ahora es un botón: muestra el reproductor actual y, al pulsarlo, ofrece
        # abrir otro (Spotify, YouTube, ...) por si no está abierto.
        self.platform_label = mark_configurable_scale(PlatformPickerButton(""))
        self.platform_label.setStyleSheet(self._platform_style(Palette.TEXT_FAINT))
        self.platform_label.setToolTip("Elegir o abrir otro reproductor")
        self.platform_label.clicked.connect(self._show_platform_menu)
        footer_row.addWidget(self.platform_label)
        footer_row.addStretch(1)

        # "Me gusta" (Spotify / YouTube): solo aparece cuando suena una de esas dos fuentes.
        self.like_btn = IconButton("heart_outline", size=20, icon_scale=0.62, bg=None)
        self.like_btn.setVisible(False)
        self.like_btn.clicked.connect(self.likeToggleRequested.emit)
        footer_row.addWidget(self.like_btn)

        self.recently_played_btn = IconButton("clock", size=20, icon_scale=0.6, bg=None)
        self.recently_played_btn.setToolTip("Recién sonaron")
        footer_row.addWidget(self.recently_played_btn)

        root.addLayout(footer_row)

        # --- Panel de letra opcional (segunda columna) ---
        # Ancho fijo animado entre 0 (oculto) y LYRICS_PANEL_WIDTH. Vive
        # dentro de un contenedor propio para poder darle sus propios
        # márgenes sin afectar el contentsMargins de la columna principal.
        self.lyrics_panel_container = QWidget()
        self.lyrics_panel_container.setStyleSheet("background: transparent;")
        self.lyrics_panel_container.setFixedWidth(0)
        panel_layout = QVBoxLayout(self.lyrics_panel_container)
        panel_layout.setContentsMargins(0, 18, 20, 20)
        panel_layout.setSpacing(0)

        self.lyrics_panel = None
        if self.lyrics_loader is not None:
            self.lyrics_panel = LyricsPanel(self.lyrics_loader)
            panel_layout.addWidget(self.lyrics_panel)

        outer.addWidget(self.lyrics_panel_container)

        self._build_lyrics_arrows()
        self._position_side_arrows()

    def _build_lyrics_arrows(self):
        """Dos flechas flotantes (no forman parte del layout: son hijas
        directas de la ventana, posicionadas a mano en _position_side_arrows)
        pegadas a los bordes izquierdo y derecho. Cada una abre el panel de
        letra hacia su lado con un solo clic, sin pasar por el menú. Si no
        hay lyrics_loader (letras deshabilitadas) no se crean."""
        self.lyrics_left_arrow = None
        self.lyrics_right_arrow = None
        if self.lyrics_panel is None:
            return

        # En Cosmos las "montañitas" de acento son claras (violeta -> celeste): el glifo
        # gris-lavanda de siempre casi no se vería, así que usa el color "sobre acento".
        on_accent = theme_module.is_cosmos()
        self.lyrics_left_arrow = IconButton(
            "chevron_left", size=LYRICS_ARROW_SIZE, icon_scale=0.62, bg=None, parent=self,
            glyph_on_accent=on_accent
        )
        self.lyrics_left_arrow.clicked.connect(lambda: self._on_lyrics_arrow_clicked("left"))
        self.lyrics_left_arrow.raise_()

        self.lyrics_right_arrow = IconButton(
            "chevron_right", size=LYRICS_ARROW_SIZE, icon_scale=0.62, bg=None, parent=self,
            glyph_on_accent=on_accent
        )
        self.lyrics_right_arrow.clicked.connect(lambda: self._on_lyrics_arrow_clicked("right"))
        self.lyrics_right_arrow.raise_()

        self._update_lyrics_arrows_visual()

    def _wire_events(self):
        self.play_btn.clicked.connect(self._on_play_clicked)
        self.prev_btn.clicked.connect(self.backend.previous)
        self.next_btn.clicked.connect(self.backend.next)
        self.shuffle_btn.clicked.connect(self._on_shuffle_clicked)
        self.repeat_btn.clicked.connect(self._on_repeat_clicked)
        self.seek_bar.seekRequested.connect(self.backend.seek_percent)
        self.seek_bar.seekPreview.connect(self._on_seek_preview)
        self.volume_bar.volumeChanged.connect(self._on_volume_changed)
        self.volume_icon.clicked.connect(self._on_mute_clicked)

        self.compact_btn.clicked.connect(self.compactModeRequested.emit)
        self.menu_btn.clicked.connect(self._show_menu)
        self.recently_played_btn.clicked.connect(self.recentlyPlayedRequested.emit)
        self.minimize_btn.clicked.connect(self.hideToTrayRequested.emit)
        self.close_btn.clicked.connect(self.hideToTrayRequested.emit)

    # -------------------------------------------------- reacción optimista
    # El siguiente sondeo real (<=150ms) confirma o corrige estos cambios;
    # mientras tanto la interfaz ya reacciona al instante al clic.
    #
    # IMPORTANTE: la predicción se basa en lo que el botón YA está
    # mostrando (self.play_btn.icon_name, etc.), no en self._last_state.
    # self._last_state solo se refresca con cada sondeo real (~150ms), así
    # que si el usuario hace doble clic rápido, ambos clics leerían la
    # MISMA base vieja y calcularían la misma predicción en vez de
    # alternar entre sí — el ícono terminaba mostrando lo contrario de lo
    # que realmente pasó hasta que el siguiente sondeo lo corregía.

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

    def set_like_info(self, info):
        """Refleja el estado de "me gusta" (ver likes.LikeInfo)."""
        self.like_btn.setVisible(info.visible)
        liked = bool(info.liked)
        self.like_btn.set_icon("heart" if liked else "heart_outline")
        self.like_btn.set_color_override(LIKE_RGB if liked else None)
        self.like_btn.setToolTip(info.tooltip)

    def _on_play_clicked(self):
        if self.backend.has_no_player():
            # Sin reproductor no hay estado que corregir el icono: no se voltea.
            self.backend.toggle_play_pause()
            return
        will_play = self.play_btn.icon_name != "pause"
        self.play_btn.set_icon("pause" if will_play else "play")
        self.backend.toggle_play_pause()

    def _on_mute_clicked(self):
        """Clic en el ícono de parlante: silencia o restaura el volumen previo."""
        current = round(self.volume_bar._percent)
        if current > 0:
            self._premute_volume = current
            target = 0
        else:
            target = self._premute_volume or 50
        self.volume_bar.set_percent(target)
        self.volume_icon.set_icon("speaker_mute" if target <= 0 else "speaker")
        self._on_volume_changed(target)

    def _on_shuffle_clicked(self):
        self.shuffle_btn.set_active(not self.shuffle_btn.is_active())
        self.backend.toggle_shuffle()

    def _on_repeat_clicked(self):
        if self.repeat_btn.icon_name == "repeat_one":
            current = "ONE"
        elif self.repeat_btn.is_active():
            current = "ALL"
        else:
            current = "NONE"
        next_mode = REPEAT_CYCLE.get(current, "ALL")
        self.repeat_btn.set_icon("repeat_one" if next_mode == "ONE" else "repeat")
        self.repeat_btn.set_active(next_mode != "NONE")
        self.backend.toggle_repeat()

    # ------------------------------------------------------------- estado
    def set_youtube_api_key(self, key: str):
        self._youtube_api_key = key or ""

    def apply_state(self, state: PlayerState):
        # El backend sondea cada 150ms y emite el estado exista o no un
        # cambio real; si es idéntico al último aplicado, no hay nada que
        # actualizar en la interfaz (evita reelaboraciones y repintados
        # innecesarios de labels, barra de progreso, botones, etc).
        if self._last_state is not None and self._last_state == state:
            return
        self._last_state = state

        self.eyebrow_label.setText(STATE_LABELS.get(state.state, "EN ESPERA"))
        is_playing = state.state == "PLAYING"
        self.playing_indicator.set_playing(is_playing and state.connected)
        self.playing_indicator.set_idle_color(self._dot_idle_color(state))
        self._set_glow_playing(is_playing and state.has_media)

        if state.has_media:
            self.title_label.setText(state.title or "Sin título")
            self.artist_label.setText(state.artist or "Artista desconocido")
        else:
            self.title_label.setText("Sin reproducción")
            self.artist_label.setText("Abre YouTube, Spotify u otro sitio compatible")

        self.seek_bar.set_percent(state.position_percent)
        # Sin duración real conocida (p. ej. Telegram: sesión SMTC nativa
        # con solo botones, sin línea de tiempo — ver Bug #10 en
        # pywnp_patch.py) no tiene sentido ofrecer arrastre: el resultado
        # de cualquier búsqueda sería siempre "posición 0", así que se
        # deshabilita en vez de dejar una barra interactiva que no hace
        # nada útil.
        self.seek_bar.set_seekable(state.controls_available and state.duration_known)
        self._duration_seconds = state.duration_seconds
        self.seek_bar.set_duration_seconds(state.duration_seconds)
        # Mientras el usuario arrastra la barra, _on_seek_preview ya está
        # mostrando en vivo el tiempo al que saltaría — no lo pisamos acá
        # con la posición real, que sigue llegando del sondeo cada 150ms.
        if state.has_media and not state.duration_known:
            # "--:--" en vez de "0:00": distingue "no tenemos ese dato" de
            # "recién empezó, va en el segundo 0" (que sí es un 0:00 real).
            self.position_label.setText("--:--")
            self.duration_label.setText("--:--")
        else:
            if not self.seek_bar.is_dragging():
                self.position_label.setText(state.position or "0:00")
            self.duration_label.setText(state.duration or "0:00")

        self.play_btn.set_icon("pause" if state.state == "PLAYING" else "play")
        self._apply_play_enabled(state)
        self.prev_btn.setEnabled(state.controls_available)
        self.next_btn.setEnabled(state.controls_available)

        self.shuffle_btn.setEnabled(state.controls_available)
        self.shuffle_btn.set_active(state.shuffle_active)

        self.repeat_btn.setEnabled(state.controls_available)
        self.repeat_btn.set_icon("repeat_one" if state.repeat_mode == "ONE" else "repeat")
        self.repeat_btn.set_active(state.repeat_mode != "NONE")

        self.volume_bar.set_interactive(state.can_volume)
        self.volume_icon.setToolTip(
            "Silenciar / activar sonido"
            if state.can_volume else
            "El volumen no está disponible para esta fuente\n"
            "(las apps de escritorio de Windows no exponen esa opción)"
        )
        self.volume_icon.setEnabled(state.can_volume)
        self.volume_icon.set_icon("speaker_mute" if state.volume <= 0 else "speaker")
        if not self.volume_bar.is_dragging():
            self.volume_bar.set_percent(max(0, min(100, state.volume)))

        if state.cover_url != self._current_cover_url:
            self._current_cover_url = state.cover_url
            if state.cover_url:
                self.cover_loader.request(state.cover_url)
            else:
                # Sin carátula (canción sin cover_url, o nada reproduciéndose):
                # el color de acento y el fondo ambiente vuelven a la
                # paleta por defecto, con la misma transición animada que
                # se usa al cambiar de canción, para que no se sienta como
                # un salto brusco.
                self.cover.set_image(None)
                self._scrim_from = self._scrim_to
                self._scrim_to = 195
                self._text_bg = Palette.BG_BASE
                self._ambient_source_from = self._ambient_source_to
                self._ambient_source_to = None
                self._regenerate_ambient_bg(shift=True)
                self._start_accent_transition(Palette.ACCENT_A, Palette.ACCENT_B)

        if getattr(self, "_platform_error_shown", False):
            # Tras un error de servidor el label quedó en rojo; se restaura el
            # estilo normal en cuanto hay un estado real que mostrar.
            self._platform_error_shown = False
            self.platform_label.setStyleSheet(self._platform_style(Palette.TEXT_FAINT))
        self.platform_label.setText(
            state.player_name if (state.has_media and state.player_name) else ""
        )

        self._update_lyrics_panel(state)

    def _dot_idle_color(self, state: PlayerState) -> tuple:
        """Color del punto estático cuando NO está sonando nada (las barras
        animadas solo aparecen en PLAYING; acá se conserva la misma
        semántica de color que tenía el indicador original: gris = sin
        conexión, azul = conectado pero pausado/detenido)."""
        if not state.connected:
            return Palette.TEXT_FAINT
        return Palette.ACCENT_B

    def _on_cover_ready(self, url: str, image):
        if url != self._current_cover_url:
            return
        has_image = not image.isNull()
        self.cover.set_image(image if has_image else None)

        # Preparamos el fondo ambiente para la próxima transición (ver
        # _on_colors_ready, que llega justo después de esta misma señal y
        # es quien realmente arranca la animación — acá solo dejamos todo
        # listo, guardando la imagen fuente; el difuminado en sí se calcula
        # perezosamente al tamaño real de la ventana, ver
        # _regenerate_ambient_bg).
        self._ambient_source_from = self._ambient_source_to
        self._ambient_source_to = image if has_image else None
        self._scrim_from = self._scrim_to
        if has_image:
            self._scrim_to = theme_module.scrim_alpha_for(
                image, fg=Palette.TEXT_FAINT, scrim=Palette.BG_BASE, lo=195, hi=235)
            cell = theme_module.brightest_cell_rgb(image)
            self._text_bg = theme_module.blend_over(Palette.BG_BASE, cell, self._scrim_to / 255.0)
        else:
            self._scrim_to = 195
            self._text_bg = Palette.BG_BASE
        self._regenerate_ambient_bg(shift=True)

    def _on_volume_changed(self, value: int):
        self.backend.set_volume(value)

    def _on_connection_changed(self, connected: bool):
        if self._last_state is not None:
            self._last_state.connected = connected

    def _on_server_error(self, message: str):
        self._platform_error_shown = True
        self.platform_label.setText(message)
        self.platform_label.setStyleSheet(self._platform_style(Palette.ERROR))

    @staticmethod
    def _platform_style(color) -> str:
        return (f"QPushButton {{ color: rgb{color}; font-family:'{FONT_BODY}'; font-size: {font_px(10)}px; "
                f"background: transparent; border: none; text-align: left; padding: 2px 0px; }} "
                f"QPushButton:hover {{ color: rgb{Palette.TEXT}; }}")

    def _show_platform_menu(self):
        """Menú para abrir otro reproductor. El que está sonando va marcado."""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addSection("Abrir reproductor")
        current = player_launcher.action_for_player_name(
            self._last_state.player_name if self._last_state is not None else "")
        for key in player_launcher.ALL_ACTIONS:
            act = menu.addAction(player_launcher.SHORT_NAMES[key])
            act.setData(key)
            act.setCheckable(True)
            act.setChecked(key == current)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        pos = self.platform_label.mapToGlobal(QPoint(0, 0))
        pos.setY(pos.y() - menu.sizeHint().height() - 4)   # el pie está abajo: abre hacia arriba
        chosen = menu.exec(pos)
        if chosen is not None and chosen.data():
            self.startPlayerRequested.emit(str(chosen.data()))

    # -------------------------------------------------------------- pintura
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        # self._side_margin reserva un margen transparente a cada lado
        # (fuera de la tarjeta) para las "montañitas" del panel de letra;
        # si no hay letras disponibles vale 0 y esto se comporta igual
        # que antes (tarjeta pegada a los bordes de la ventana).
        r = rect.adjusted(3 + self._side_margin, 3, -3 - self._side_margin, -3)

        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(float(r.x()), float(r.y() + 3), float(r.width()),
                                    float(r.height()), 30, 30)
        painter.fillPath(shadow_path, QColor(0, 0, 0, 90))

        if self._side_margin > 0:
            self._draw_lyrics_bumps(painter, r)

        bg_path = QPainterPath()
        bg_path.addRoundedRect(float(r.x()), float(r.y()), float(r.width()),
                                float(r.height()), 28, 28)
        painter.fillPath(bg_path, Palette.c(Palette.BG_BASE))

        # --- Fondo ambiente: versión difuminada y oscurecida de la
        # carátula actual, de pared a pared, para que la ventana se sienta
        # "vestida" con los colores de lo que suena en vez de un panel
        # plano siempre igual (inspirado en el fondo "ambient" de
        # Spotify/Apple Music). Se regenera perezosamente acá si cambió el
        # tamaño de la ventana desde la última vez (zoom, panel de letra
        # abriéndose...); reescalar una miniatura de 20x20 es barato.
        if self._ambient_big_from is not None or self._ambient_big_to is not None:
            if self._ambient_cache_size != self.size():
                # No regenerar ACÁ mismo (ver el comentario junto a
                # _ambient_resize_timer en __init__): mientras el tamaño
                # sigue cambiando, se sigue dibujando la última imagen
                # buena aunque no calce exacto con el tamaño actual — Qt
                # ya la estira gratis al dibujarla (drawImage), apenas
                # perceptible en un fondo difuminado. La regeneración de
                # calidad completa llega sola 120ms después de que el
                # tamaño deje de cambiar.
                self._ambient_resize_timer.start()
            painter.save()
            painter.setClipPath(bg_path)
            target_rect = QRectF(0, 0, self.width(), self.height())
            if self._ambient_big_from is not None and self._transition_progress < 0.999:
                painter.setOpacity(1.0)
                painter.drawImage(target_rect, self._ambient_big_from)
            if self._ambient_big_to is not None:
                opacity = self._transition_progress if self._ambient_big_from is not None else 1.0
                painter.setOpacity(opacity)
                painter.drawImage(target_rect, self._ambient_big_to)
            painter.setOpacity(1.0)
            # Oscurecemos bastante encima: el fondo es un toque atmosférico,
            # no debe competir con el texto ni con la carátula real.
            if self._ambient_big_from is not None and self._ambient_big_to is not None:
                t = max(0.0, min(1.0, self._transition_progress))
                scrim_alpha = round(self._scrim_from + (self._scrim_to - self._scrim_from) * t)
            else:
                scrim_alpha = self._scrim_to
            painter.fillPath(bg_path, QColor(*Palette.BG_BASE, scrim_alpha))
            painter.restore()

        if self._sky is not None:
            painter.save()
            painter.setClipPath(bg_path)
            self._sky.paint(painter, self.size(), self.devicePixelRatioF())
            if self._stars is not None:
                self._stars.paint(painter)
            painter.restore()

        pen_grad = QLinearGradient(QPointF(r.topLeft()), QPointF(r.bottomRight()))
        pen_grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                         self._accent_a.blue(), 180))
        pen_grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                         self._accent_b.blue(), 180))
        pen = QPen(pen_grad, 1.5)
        painter.setPen(pen)
        painter.drawPath(bg_path)
        painter.end()

    def _shooting_stars_allowed(self) -> bool:
        st = self._last_state
        return self.isVisible() and st is not None and st.state == "PLAYING"

    def _draw_lyrics_bumps(self, painter: QPainter, r: QRect):
        """Dibuja los dos círculos de acento centrados en el borde
        izquierdo/derecho de la tarjeta (r). Se pintan ANTES de rellenar
        la tarjeta (bg_path), así su mitad interior queda tapada por ella
        y solo se ve la mitad exterior — el efecto de "montañita" pegada
        al borde, sin necesidad de recortar un semicírculo a mano.

        IMPORTANTE: painter.save()/restore() alrededor de todo esto. Sin
        eso, el pincel con degradé quedaba "pegado" en el painter, y el
        drawPath(bg_path) del borde (más abajo en paintEvent) lo usaba
        para RELLENAR toda la tarjeta de nuevo (drawPath rellena con el
        brush activo antes de trazar el pen) — eso era el bug real detrás
        de la tarjeta apareciendo teñida de rojo/azul de punta a punta."""
        painter.save()
        cy = r.y() + r.height() / 2.0
        grad = QLinearGradient(QPointF(0, cy - BUMP_RADIUS), QPointF(0, cy + BUMP_RADIUS))
        grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                     self._accent_a.blue(), 215))
        grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                     self._accent_b.blue(), 215))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(QPointF(float(r.x()), cy), BUMP_RADIUS, BUMP_RADIUS)
        painter.drawEllipse(QPointF(float(r.x() + r.width()), cy), BUMP_RADIUS, BUMP_RADIUS)
        painter.restore()

    # ------------------------------------------------------------ responsive
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_side_arrows()

        if self._adjusting or not hasattr(self, "cover"):
            return
        self._adjusting = True
        try:
            # El alto no lo controla el usuario: se recalcula a partir del
            # layout para que nunca quede un hueco en blanco ni se recorte.
            target_h = self.layout().sizeHint().height()
            if abs(target_h - self.height()) > 1:
                self.resize(self.width(), target_h)
        finally:
            self._adjusting = False

    def wheelEvent(self, event):
        """Zoom con la rueda del mouse (como en la mini ventana): agranda o
        encoge la columna de contenido, anclado al centro para que no
        'salte' hacia una esquina mientras se hace zoom. El panel de letra
        (si está visible) no escala con el zoom, mantiene su ancho fijo."""
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        steps = delta / 120.0  # una "muesca" estándar de rueda
        new_content_width = self._content_width + round(steps * WHEEL_WIDTH_STEP)
        new_content_width = max(MIN_WIDTH, min(MAX_WIDTH, new_content_width))
        if new_content_width == self._content_width:
            event.accept()
            return

        old_center = self.frameGeometry().center()
        self._apply_content_width(new_content_width)
        new_center = self.frameGeometry().center()
        if new_center != old_center:
            self.move(self.pos() + (old_center - new_center))
        event.accept()

    def content_width(self) -> int:
        """Ancho actual de la columna de contenido (la parte afectada por
        el zoom), sin contar el panel de letra opcional."""
        return self._content_width

    def set_content_width(self, width: int):
        """Fija el ancho de la columna de contenido directamente (usado al
        restaurar el zoom guardado), sin pasar por el gesto de rueda."""
        width = max(MIN_WIDTH, min(MAX_WIDTH, width))
        self._apply_content_width(width)

    def _apply_content_width(self, new_content_width: int):
        """Aplica un nuevo ancho de columna de contenido: escala la
        carátula en proporción, y hace un único resize() atómico (ancho
        total = contenido + panel, alto recalculado a partir del layout).

        Calculamos todo esto ANTES de tocar la ventana para hacer un solo
        resize() atómico. Si en cambio dejáramos que resizeEvent
        encadenara un segundo resize() por su cuenta (como hace al
        arrastrar normalmente), Qt a veces difiere ese segundo cambio a la
        siguiente vuelta del loop de eventos y el resultado se
        desincroniza. self._adjusting=True evita ese segundo resize,
        porque aquí ya hacemos el trabajo completo.
        """
        self._adjusting = True
        try:
            # Nunca por debajo del mínimo REAL del layout (con MIN_WIDTH=300 la
            # fila de 5 botones necesitaba 306 px y se recortaba/solapaba en los
            # bordes; con letra grande el mínimo sube todavía más).
            lay_min = self.content_widget.layout().minimumSize().width()
            new_content_width = max(new_content_width, lay_min)
            self._content_width = new_content_width
            self.content_widget.setFixedWidth(new_content_width)
            ratio = new_content_width / WIDTH
            cover_size = int(max(MIN_COVER, min(MAX_COVER, COVER_SIZE * ratio)))
            if cover_size != self.cover.width():
                self.cover.setFixedSize(cover_size, cover_size)
            total_width = new_content_width + round(self._panel_width) + 2 * self._side_margin
            # setFixedWidth() en un hijo invalida su sizeHint pero el layout
            # padre solo se re-evalúa en el próximo ciclo de eventos (vía un
            # QEvent::LayoutRequest pendiente). Si llamamos a resize() antes
            # de eso, Qt puede seguir imponiendo el minimumSize CACHEADO (más
            # grande) del layout y "rechazar" el encogimiento. activate()
            # fuerza a recalcularlo ya mismo, antes del resize().
            self.layout().activate()
            new_height = self.layout().sizeHint().height()
            self.resize(total_width, new_height)
        finally:
            self._adjusting = False

    # -------------------------------------------------------- panel de letra
    def _get_panel_width(self) -> float:
        return self._panel_width

    def _set_panel_width(self, value: float):
        self._panel_width = value
        self.lyrics_panel_container.setFixedWidth(round(value))
        if not self._adjusting:
            self._adjusting = True
            try:
                total_width = self._content_width + round(value) + 2 * self._side_margin
                self.layout().activate()  # ver nota en _apply_content_width
                new_height = self.layout().sizeHint().height()
                self.resize(total_width, new_height)
            finally:
                self._adjusting = False

    panelWidth = pyqtProperty(float, _get_panel_width, _set_panel_width)

    # -------------------------------------------------- acento / ambiente
    def _get_transition_progress(self) -> float:
        return self._transition_progress

    def _set_transition_progress(self, value: float):
        self._transition_progress = value
        a = _lerp_qcolor(self._accent_a_from, self._accent_a_to, value)
        b = _lerp_qcolor(self._accent_b_from, self._accent_b_to, value)
        self._accent_a = a
        self._accent_b = b
        rgb_a = (a.red(), a.green(), a.blue())
        rgb_b = (b.red(), b.green(), b.blue())
        self.cover.set_accent(rgb_a, rgb_b)
        self.seek_bar.set_accent(rgb_a, rgb_b)
        self.volume_bar.set_accent(rgb_a, rgb_b)
        self.play_btn.set_accent(rgb_a, rgb_b)
        if self.lyrics_left_arrow is not None and theme_module.is_cosmos():
            self.lyrics_left_arrow.set_accent(rgb_a, rgb_b)
            self.lyrics_right_arrow.set_accent(rgb_a, rgb_b)
        self.playing_indicator.set_color(rgb_a)
        # El acento sale de la carátula: como TEXTO puede caer en 1.8:1 (azul
        # oscuro). Se aclara solo lo necesario hasta 4.5:1 contra el fondo real.
        self.artist_label.set_color(QColor(*theme_module.ensure_contrast(rgb_a, self._text_bg, 4.5)))
        self.update()  # repinta el borde de la ventana con el color interpolado

    transitionProgress = pyqtProperty(float, _get_transition_progress, _set_transition_progress)

    def _on_glow_tick(self):
        # Onda seno lenta entre 0.55 y 1.0 (mismo rango que antes con
        # QPropertyAnimation), pero maneja el propio timer así controlamos
        # la frecuencia de repintado directamente (ver por qué en el
        # comentario de self._glow_timer, en __init__).
        # Por reloj real: 0.975 rad/s = los 0.078 rad por tick de 80 ms de antes
        # (ciclo de ~6.4 s), pero sin atrasarse si el timer grueso de Qt se
        # retrasa bajo carga. La frecuencia (12 fps) se conserva a propósito.
        now = time.monotonic()
        dt = 0.08 if self._glow_last is None else min(now - self._glow_last, 0.25)
        self._glow_last = now
        self._glow_phase += 0.975 * dt
        wave = (math.sin(self._glow_phase) + 1) / 2  # 0..1
        self.cover.set_glow_intensity(0.55 + wave * 0.45)

    def _on_colors_ready(self, url: str, accent_a: tuple, accent_b: tuple):
        if url != self._current_cover_url:
            return
        self._start_accent_transition(accent_a, accent_b)

    def _start_accent_transition(self, accent_a: tuple, accent_b: tuple):
        self._transition_anim.stop()
        # El punto de partida de la animación es el color YA interpolado de
        # este instante (no necesariamente self._accent_a_to de la
        # transición anterior), para que si dos canciones cambian rápido
        # seguidas la segunda transición arranque desde donde quedó la
        # primera a medio camino, en vez de saltar hacia atrás.
        self._accent_a_from = self._accent_a
        self._accent_b_from = self._accent_b
        self._accent_a_to = QColor(*accent_a)
        self._accent_b_to = QColor(*accent_b)
        self._transition_progress = 0.0
        self._transition_anim.setStartValue(0.0)
        self._transition_anim.setEndValue(1.0)
        self._transition_anim.start()

    def _set_glow_playing(self, playing: bool):
        if playing == self._glow_playing:
            return
        self._glow_playing = playing
        if playing and self.isVisible() and not theme_module.REDUCED_MOTION:
            self._glow_last = None
            self._glow_timer.start()
        else:
            self._glow_timer.stop()
            self.cover.set_glow_intensity(1.0)

    def showEvent(self, event):
        super().showEvent(event)
        # Si "debería" estar animando el glow (canción sonando) pero el
        # timer estaba parado porque la ventana estuvo oculta, lo
        # retomamos ahora que vuelve a verse. No tiene sentido gastar
        # este timer (~12fps) mientras nadie puede verlo.
        if (self._glow_playing and not self._glow_timer.isActive()
                and not theme_module.REDUCED_MOTION):
            self._glow_last = None
            self._glow_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._glow_timer.stop()

    def _regenerate_ambient_bg(self, shift: bool = False):
        """(Re)genera el fondo ambiente difuminado al tamaño actual de la
        ventana a partir de las imágenes fuente cacheadas (ver
        _on_cover_ready). Usa blur_image_hq() de widgets.py: blur
        gaussiano real sobre una versión intermedia que conserva la
        calidad de la carátula original, no una miniatura minúscula
        estirada (eso se veía "con menos calidad" en vez de borroso)."""
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        # shift=True: la carátula acaba de cambiar y la "anterior" es
        # exactamente la que ya estaba difuminada como "nueva". Si el tamaño
        # no cambió desde entonces, se reutiliza en vez de volver a difuminarla
        # (antes cada cambio de canción hacía DOS blurs; ahora uno).
        reuse_previous = shift and self._ambient_cache_size == size
        previous_blur = self._ambient_big_to if reuse_previous else None
        self._ambient_cache_size = size
        if self._ambient_source_to is not None:
            blurred = blur_image_hq(self._ambient_source_to, size.width(), size.height())
            self._ambient_big_to = blurred if not blurred.isNull() else None
        else:
            self._ambient_big_to = None
        if reuse_previous:
            self._ambient_big_from = previous_blur if self._ambient_source_from is not None else None
        elif self._ambient_source_from is not None:
            blurred = blur_image_hq(self._ambient_source_from, size.width(), size.height())
            self._ambient_big_from = blurred if not blurred.isNull() else None
        else:
            self._ambient_big_from = None

    def _on_seek_preview(self, percent: float):
        """Mientras se arrastra la barra, se muestra en vivo el tiempo al
        que se saltaría en vez de la posición real (que sigue llegando
        del sondeo normal) — así el usuario ve exactamente dónde va a
        caer antes de soltar el clic."""
        if self._duration_seconds <= 0:
            return
        seconds = max(0, round(percent / 100.0 * self._duration_seconds))
        m, s = divmod(seconds, 60)
        self.position_label.setText(f"{m}:{s:02d}")

    def is_lyrics_panel_enabled(self) -> bool:
        return self._lyrics_panel_enabled

    def lyrics_panel_side(self) -> str:
        return self._lyrics_panel_side

    def set_lyrics_panel_side(self, side: str):
        """Fija de qué lado vive el panel (sin animar ni tocar si está
        visible ahora mismo) — se usa al restaurar la config guardada."""
        if side not in ("left", "right") or side == self._lyrics_panel_side:
            return
        self._lyrics_panel_side = side
        self._reorder_panel_in_layout()
        self._update_lyrics_arrows_visual()

    def _reorder_panel_in_layout(self):
        """Mueve lyrics_panel_container al extremo izquierdo o derecho del
        QHBoxLayout principal según self._lyrics_panel_side. No anima nada
        por sí sola (ver _on_lyrics_arrow_clicked para el efecto de
        deslizamiento al cambiar de lado con el panel ya abierto)."""
        outer = self.layout()
        outer.removeWidget(self.lyrics_panel_container)
        if self._lyrics_panel_side == "left":
            outer.insertWidget(0, self.lyrics_panel_container)
        else:
            outer.addWidget(self.lyrics_panel_container)

    def set_lyrics_panel_enabled(self, enabled: bool, animate: bool = True):
        """Muestra/oculta el panel de letra junto a la carátula, animando
        el ancho de la ventana. Si se activa y hay una canción sonando,
        dispara la búsqueda de letra de inmediato."""
        if self.lyrics_panel is None or enabled == self._lyrics_panel_enabled:
            return
        self._lyrics_panel_enabled = enabled
        target = float(LYRICS_PANEL_WIDTH) if enabled else 0.0

        self._panel_anim.stop()
        if animate:
            self._panel_anim.setStartValue(self._panel_width)
            self._panel_anim.setEndValue(target)
            self._panel_anim.start()
        else:
            self._set_panel_width(target)

        if enabled:
            self._panel_track_key = None  # fuerza a refrescar la letra actual
            if self._last_state is not None:
                self._update_lyrics_panel(self._last_state)
        else:
            # Detiene la interpolación local de posición (widgets.py) mientras
            # el panel está oculto: no tiene sentido seguir calculándola (ni
            # gastar el timer de 10fps) si nadie la puede ver.
            self.lyrics_panel.set_playing(False)

        self._update_lyrics_arrows_visual()

    # ------------------------------------------------ flechas laterales
    def _card_edges_x(self) -> tuple[float, float]:
        """Coordenadas x (izquierda, derecha) del borde real de la
        tarjeta redondeada — deben coincidir exactamente con el `r` que
        usa paintEvent, para que la flecha quede centrada sobre la parte
        visible de la montañita."""
        left = 3 + self._side_margin
        right = self.width() - 3 - self._side_margin
        return float(left), float(right)

    def _position_side_arrows(self):
        """Ancla las dos flechas sobre la mitad visible de cada
        montañita (ver _draw_lyrics_bumps), centradas verticalmente. Son
        hijas directas de la ventana (no del layout), así que hay que
        ubicarlas a mano cada vez que cambia el tamaño total (zoom, panel
        abriéndose/cerrándose)."""
        if not hasattr(self, "lyrics_left_arrow") or self.lyrics_left_arrow is None:
            return
        card_left, card_right = self._card_edges_x()
        y = (self.height() - LYRICS_ARROW_SIZE) // 2
        # Centro de la flecha corrido hacia afuera del borde, para caer
        # dentro del semicírculo visible (la mitad interior del bulto
        # queda tapada por la tarjeta, ver _draw_lyrics_bumps).
        left_center = card_left - BUMP_RADIUS * 0.6
        right_center = card_right + BUMP_RADIUS * 0.6
        self.lyrics_left_arrow.move(round(left_center - LYRICS_ARROW_SIZE / 2), y)
        self.lyrics_right_arrow.move(round(right_center - LYRICS_ARROW_SIZE / 2), y)

    def _update_lyrics_arrows_visual(self):
        """Refleja en las flechas si el panel está abierto de ese lado:
        la flecha activa se tiñe con el acento y apunta 'hacia adentro'
        (invitando a cerrar), la inactiva apunta 'hacia afuera' (invitando
        a abrir de ese lado)."""
        if self.lyrics_left_arrow is None:
            return
        left_open = self._lyrics_panel_enabled and self._lyrics_panel_side == "left"
        right_open = self._lyrics_panel_enabled and self._lyrics_panel_side == "right"

        self.lyrics_left_arrow.set_icon("chevron_right" if left_open else "chevron_left")
        self.lyrics_left_arrow.set_active(left_open)
        self.lyrics_left_arrow.setToolTip(
            "Ocultar letra" if left_open else "Mostrar letra (izquierda)"
        )

        self.lyrics_right_arrow.set_icon("chevron_left" if right_open else "chevron_right")
        self.lyrics_right_arrow.set_active(right_open)
        self.lyrics_right_arrow.setToolTip(
            "Ocultar letra" if right_open else "Mostrar letra (derecha)"
        )

    def _on_lyrics_arrow_clicked(self, side: str):
        if self.lyrics_panel is None:
            return
        if self._lyrics_panel_enabled and self._lyrics_panel_side == side:
            # Ya está abierto de este lado: la flecha pasa a funcionar
            # como botón de cerrar.
            self.set_lyrics_panel_enabled(False)
        elif self._lyrics_panel_enabled:
            # Está abierto del OTRO lado: se cierra, se reubica el panel
            # en el layout, y se vuelve a abrir ya del lado nuevo — se ve
            # como un deslizamiento de un lado hacia el otro en vez de un
            # salto brusco.
            self._switch_lyrics_panel_side(side)
        else:
            # Estaba cerrado: se abre directo del lado que se presionó.
            self._lyrics_panel_side = side
            self._reorder_panel_in_layout()
            self.set_lyrics_panel_enabled(True)

    def _switch_lyrics_panel_side(self, new_side: str):
        def _after_close():
            self._panel_anim.finished.disconnect(_after_close)
            self._lyrics_panel_side = new_side
            self._reorder_panel_in_layout()
            self._update_lyrics_arrows_visual()
            self._panel_anim.setStartValue(0.0)
            self._panel_anim.setEndValue(float(LYRICS_PANEL_WIDTH))
            self._panel_anim.start()

        self._panel_anim.stop()
        self._panel_anim.finished.connect(_after_close)
        self._panel_anim.setStartValue(self._panel_width)
        self._panel_anim.setEndValue(0.0)
        self._panel_anim.start()

    def _update_lyrics_panel(self, state: PlayerState):
        if self.lyrics_panel is None or not self._lyrics_panel_enabled:
            return
        track_key = (state.artist, state.title)
        if track_key != self._panel_track_key:
            self._panel_track_key = track_key
            if state.artist or state.title:
                self.lyrics_panel.set_track_debounced(
                    state.artist, state.title, state.album, state.duration_seconds
                )
            else:
                self.lyrics_panel.set_track("", "", "", 0)
        self.lyrics_panel.set_position(state.position_seconds)
        self.lyrics_panel.set_playing(state.state == "PLAYING")

    # ------------------------------------------------------------- arrastre
    # Distinguimos "clic" de "arrastre": si sueltas el mouse cerca de donde
    # lo presionaste (sin moverlo más que CLICK_DRAG_THRESHOLD) Y lo hiciste
    # sobre la carátula o el título/artista, abrimos una búsqueda de la
    # canción. Si te moviste más que eso, fue un arrastre normal de
    # ventana. La carátula y los labels tienen WA_TransparentForMouseEvents
    # (para poder arrastrar la ventana agarrándolos), así que estos eventos
    # SIEMPRE llegan aquí, nunca a los widgets hijos directamente.
    CLICK_DRAG_THRESHOLD = 6

    def _mapped_rect(self, widget):
        """geometry() de un widget es relativa a SU padre directo. Antes
        carátula/título/artista eran hijos directos de self, así que
        coincidía con las coordenadas de los eventos de mouse (relativas a
        self). Ahora que viven dentro de content_widget (columna interna),
        hay que mapear explícitamente a las coordenadas de self."""
        top_left = widget.mapTo(self, QPoint(0, 0))
        return QRect(top_left, widget.size())

    def _is_link_area(self, pos) -> bool:
        return (
            self._mapped_rect(self.cover).contains(pos)
            or self._mapped_rect(self.title_label).contains(pos)
            or self._mapped_rect(self.artist_label).contains(pos)
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_local_pos = event.position().toPoint()
            self._press_on_link_area = self._is_link_area(self._press_local_pos)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        # Sin botón presionado: solo actualiza el cursor para insinuar que
        # la carátula/título son clicables.
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self._is_link_area(event.position().toPoint())
            else Qt.CursorShape.ArrowCursor
        )
        if self.cursor().shape() != cursor:
            self.setCursor(cursor)

    def mouseReleaseEvent(self, event):
        if self._press_on_link_area and self._press_local_pos is not None:
            moved = (event.position().toPoint() - self._press_local_pos).manhattanLength()
            if moved <= self.CLICK_DRAG_THRESHOLD:
                self._open_source_link()
        self._drag_pos = None
        self._press_local_pos = None
        self._press_on_link_area = False

    def _open_source_link(self):
        """Abre una búsqueda de la canción actual en el navegador (o, si
        hay una clave de API de YouTube configurada y la canción viene de
        YouTube/YouTube Music, el video exacto — ver youtube_api.py). WNP
        no expone la URL exacta de la canción/pestaña (ver links.py), así
        que esto es lo más cercano y útil que se puede ofrecer."""
        state = self._last_state
        if state is None or not state.has_media:
            return
        self._video_resolver.resolve(
            state.player_name, state.artist, state.title, self._youtube_api_key
        )

    # ------------------------------------------------------- atajos de teclado
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

    # -------------------------------------------------------- menú contextual
    def contextMenuEvent(self, event):
        # El menú ahora solo se abre con el botón de engranaje (o con clic
        # derecho en el ícono oculto de la bandeja) — a pedido, se quitó
        # del clic derecho sobre la ventana en sí. No llamar a
        # super().contextMenuEvent(event) tampoco: así ni el menú por
        # defecto de Qt aparece.
        event.ignore()

    def _show_menu(self):
        menu = self._build_menu()
        # Aparece justo debajo del botón que lo abrió, como un desplegable
        # normal, en vez de en la posición del cursor (eso tenía sentido
        # para un clic derecho en cualquier parte, no para un botón fijo).
        pos = self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomRight())
        menu.exec(pos - QPoint(menu.sizeHint().width(), 0))

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        # Se crea una instancia NUEVA cada vez que se abre el menú (cada
        # clic en el botón de engranaje) — sin esto quedaba viva para
        # siempre como hijo de la ventana, igual que pasaba con los
        # diálogos antes de corregirlo (ver sección 12.1 de PROYECTO.md).
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        compact_action = menu.addAction("Modo compacto")
        dock_action = menu.addAction("Panel lateral")
        top_action = menu.addAction("Siempre visible")
        top_action.setCheckable(True)
        top_action.setChecked(self._always_on_top)
        menu.addSeparator()
        lyrics_panel_action = None
        if self.lyrics_panel is not None:
            lyrics_panel_action = menu.addAction("Letra junto a la carátula")
            lyrics_panel_action.setCheckable(True)
            lyrics_panel_action.setChecked(self._lyrics_panel_enabled)
        theme_bridge = getattr(self, "_theme_bridge", None)
        if theme_bridge is not None:
            from spotify_theme import make_theme_menu
            menu.addMenu(make_theme_menu("Tema de Spotify", theme_bridge, menu))
        settings_action = menu.addAction("Configuración...")
        menu.addSeparator()
        about_action = menu.addAction("Acerca de")
        welcome_action = menu.addAction("Ver bienvenida de nuevo...")
        quit_action = menu.addAction("Salir")

        def _on_triggered(action):
            if action == compact_action:
                self.compactModeRequested.emit()
            elif action == dock_action:
                self.dockModeRequested.emit()
            elif action == top_action:
                self._toggle_always_on_top()
            elif lyrics_panel_action is not None and action == lyrics_panel_action:
                self.set_lyrics_panel_enabled(not self._lyrics_panel_enabled)
            elif action == settings_action:
                self.settingsDialogRequested.emit()
            elif action == about_action:
                AboutDialog(self.backend.port, self).exec()
            elif action == welcome_action:
                self.welcomeDialogRequested.emit()
            elif action == quit_action:
                self.quitRequested.emit()

        menu.triggered.connect(_on_triggered)
        return menu

    def set_theme_bridge(self, bridge):
        """AppController entrega el puente con el tema de Spicetify; con él, el
        menú del engranaje muestra el submenú "Tema de Spotify"."""
        self._theme_bridge = bridge

    def _toggle_always_on_top(self):
        self.set_always_on_top(not self._always_on_top)

    def is_always_on_top(self) -> bool:
        return self._always_on_top

    def set_always_on_top(self, enabled: bool):
        self._always_on_top = enabled
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)
        if was_visible:
            self.show()

    def _open_port_dialog(self):
        dlg = PortDialog(self.backend.port, self)
        geo = self.geometry()
        dlg.move(geo.center().x() - dlg.width() // 2, geo.center().y() - dlg.height() // 2)
        if dlg.exec() == dlg.DialogCode.Accepted:
            port = dlg.selected_port()
            if port:
                self.portChangeRequested.emit(port)
