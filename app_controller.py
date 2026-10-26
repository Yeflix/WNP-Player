"""Coordina el backend, las dos interfaces gráficas (completa/compacta), la
bandeja del sistema, la configuración persistente, notificaciones, historial
y letras de canciones."""
from PyQt6.QtCore import QObject, QPropertyAnimation, QEasingCurve, QTimer, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QDesktopServices, QCursor
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from backend import WNPBackend, PlayerState, POLL_INTERVAL_MS, IDLE_POLL_INTERVAL_MS
from cover_loader import CoverArtLoader
from main_window import MainWindow, MIN_WIDTH as MAIN_MIN_WIDTH, MAX_WIDTH as MAIN_MAX_WIDTH
from mini_window import MiniWindow
from app_icon import build_app_icon
from config import AppConfig
from hotkeys import HotkeyManager
from lyrics import LyricsLoader
from dialogs import HotkeyDialog, SettingsDialog, HistoryDialog, StatsDialog, RecentlyPlayedDialog
from onboarding import WelcomeWizard
from weekly_recap import WeeklyRecapToast
from scrobbling import ScrobbleManager
from spotify_theme import SpotifyThemeBridge, make_theme_menu
import datetime
import time
import ad_filter
import player_launcher
from likes import LikeManager
import ad_log
import history
import stats

# Cada cuánto se autoguarda la posición/tamaño de ventana mientras la app
# sigue corriendo, además de al cerrar limpiamente — así un cierre abrupto
# (falla, "matar" el proceso) pierde como mucho unos segundos, no la sesión
# completa.
AUTOSAVE_INTERVAL_MS = 20_000


class AppController(QObject):
    def __init__(self, port: "int | None" = None, parent=None):
        super().__init__(parent)
        self.icon = build_app_icon()

        self.config = AppConfig.load()
        effective_port = port if port is not None else self.config.port

        # Debe llamarse antes de construir main_window/mini_window: el
        # tamaño de fuente y el contraste se "hornean" en el QSS de cada
        # widget al crearse, no se recalculan después (ver theme.py).
        from theme import apply_accessibility
        apply_accessibility(self.config.font_scale, self.config.high_contrast)

        self.backend = WNPBackend(port=effective_port)
        self.cover_loader = CoverArtLoader()
        self.lyrics_loader = LyricsLoader()
        self.scrobbler = ScrobbleManager(lambda: self.config)
        # Los anuncios de Spotify que ya estaban en el historial se mueven al
        # registro aparte (anuncios.csv). Idempotente; nunca debe impedir el arranque.
        try:
            self._migrated_ads = history.purge_ads_from_history()
        except Exception:
            self._migrated_ads = 0

        from dock_window import DockWindow
        self.main_window = MainWindow(self.backend, self.cover_loader, self.lyrics_loader)
        self.mini_window = MiniWindow(self.backend, self.cover_loader)
        self.dock_window = DockWindow(self.backend, self.cover_loader, lyrics_loader=self.lyrics_loader)
        self.main_window.setWindowIcon(self.icon)

        # Puente con el tema de Spicetify (Cosmos / Cover / YefriDev...). Se
        # crea antes de la bandeja porque su menú incluye "Tema de Spotify".
        self.theme_bridge = SpotifyThemeBridge(
            port=self.config.spotify_theme_port, last_mode=self.config.spotify_theme_mode)
        self.theme_bridge.modeChanged.connect(self._on_spotify_theme_mode)
        self.theme_bridge.error.connect(self._on_theme_bridge_error)
        self.main_window.set_theme_bridge(self.theme_bridge)

        self.tray = self._build_tray()

        self._wire_windows()
        self._fade_anims = {}  # ventana -> QPropertyAnimation de fundido en curso
        self._current_mode = "main"
        self._main_positioned = False
        self._mini_positioned = False
        self._current_state = PlayerState()
        self._last_track_key = None  # (title, artist) — para no duplicar en historial/notis
        # Una canción se registra solo cuando (título, artista) lleva este
        # tiempo estable: la extensión manda título, artista y duración en
        # mensajes separados y el sondeo puede caer entre ellos, lo que
        # guardaba entradas mezcladas ("Song B | Artist A") y las enviaba a
        # Last.fm. 0 = registrar de inmediato (usado por los tests).
        self.TRACK_SETTLE_MS = 500
        self._pending_track_key = None
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._commit_pending_track)
        self._shut_down = False
        self._last_error_message = None
        self._last_error_notified_at = None  # datetime — throttle de notificaciones (ver _on_server_error)

        self.hotkeys = HotkeyManager()
        app = QApplication.instance()
        if app is not None:
            self.hotkeys.install(app)
        self.hotkeys.triggered.connect(self._on_hotkey_triggered)

        self.backend.serverError.connect(self._on_server_error)
        self.backend.logMessage.connect(
            lambda level, msg: print(f"[WNP:{level}] {msg}")
        )
        self.backend.started.connect(lambda p: self.tray.showMessage(
            "WNP Player", f"Escuchando en el puerto {p}. Conecta la extensión del navegador.",
            self.icon, 4000
        ))
        self.backend.stateChanged.connect(self._on_playback_state_changed)
        self.backend.noPlayerPlayRequested.connect(self._on_no_player_play)
        self.main_window.startPlayerRequested.connect(self._start_player)
        self._apply_play_idle_setting()
        # "Me gusta" (Spotify / YouTube): el gestor consulta la API en segundo plano
        # y las ventanas solo reciben el resultado (ver likes.py).
        self.likes = LikeManager(self.config, self)
        self.likes.changed.connect(self.main_window.set_like_info)
        self.likes.changed.connect(self.dock_window.set_like_info)
        self.main_window.likeToggleRequested.connect(self.likes.toggle)
        self.dock_window.likeToggleRequested.connect(self.likes.toggle)
        self.likes.setupRequested.connect(self._open_likes_dialog)
        # Tras abrir Spotify por "reproducir": hasta cuando se espera su sesion
        # para darle play una vez (monotonic; 0 = nada pendiente).
        self._autoplay_until = 0.0
        self._start_menu_open = False
        self.cover_loader.coverReady.connect(self._on_cover_ready_for_tray)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._save_config)

        self._restore_config()

    # ------------------------------------------------------------- arranque
    def start(self):
        self.backend.start()
        if self.config.spotify_theme_enabled:
            self.theme_bridge.start()
        self._autosave_timer.start()
        # En cada arranque el registro se alinea con la configuración (por
        # defecto: activado). Así el .exe, al moverlo de carpeta, corrige solo
        # su ruta de inicio.
        self._apply_start_with_windows(self.config.start_with_windows)

        if not self.config.onboarding_completed:
            # Primera ejecución (da igual si es `python main.py` o el
            # `.exe` empaquetado: la condición es el config guardado, no
            # la forma de arrancar). El asistente elige el modo por
            # defecto; una vez cerrado, seguimos el flujo normal de abrir
            # esa ventana (salvo que el usuario ya tuviera activado
            # "iniciar minimizado", poco probable en la primera vez pero
            # se respeta igual).
            self._run_onboarding()

        if self.config.start_minimized:
            self.backend.set_poll_interval(IDLE_POLL_INTERVAL_MS)
        elif self._current_mode == "mini":
            self._show_mini()
        elif self._current_mode == "dock":
            self._show_dock()
        else:
            self._show_main()

        # Con un pequeño retraso para no competir visualmente con el
        # fundido de entrada de la ventana recién abierta.
        QTimer.singleShot(3000, self._maybe_show_weekly_recap)

    def _apply_start_with_windows(self, enabled: bool):
        """Aplica "Iniciar con Windows" al registro y guarda lo que quedó
        realmente (si el registro falla, la casilla no miente)."""
        import autostart
        if autostart.is_supported():
            autostart.sync(enabled)
            enabled = autostart.is_enabled()
        self.config.start_with_windows = bool(enabled)

    def _maybe_show_weekly_recap(self):
        """Como mucho una vez por semana (ver stats.should_show_weekly_recap),
        y nunca en la primerísima ejecución (todavía no hay nada que
        resumir). Si la semana estuvo vacía, se actualiza igual la fecha
        —para no seguir intentando cada arranque— pero no se muestra
        nada: no hay ningún dato interesante que mostrar."""
        if not self.config.onboarding_completed:
            return
        if not stats.should_show_weekly_recap(self.config.last_weekly_recap_shown):
            return
        self.config.last_weekly_recap_shown = datetime.datetime.now().isoformat(timespec="seconds")
        self._save_config()

        summary = stats.summary(history.load(), days=7)
        if summary["plays"] == 0:
            return

        toast = WeeklyRecapToast(summary)
        toast.show()
        WeeklyRecapToast.position_bottom_right(toast)
        self._weekly_recap_toast = toast  # referencia viva, evita que el GC lo cierre antes de tiempo

    def _run_onboarding(self):
        wizard = WelcomeWizard(
            port=self.backend.port, initial_mode=self._current_mode,
            start_with_windows=self.config.start_with_windows,
        )
        wizard.exec()  # modal: bloquea hasta "Empezar a usar..." u "Omitir"

        self._apply_start_with_windows(wizard.result_start_with_windows)
        self._current_mode = wizard.result_default_mode
        self.config.last_mode = self._current_mode
        self.config.onboarding_completed = True
        self.config.save()

    def _reopen_onboarding(self):
        """Vuelve a mostrar el mismo asistente a pedido del usuario (menú
        contextual → 'Ver bienvenida de nuevo...'), sin tocar
        onboarding_completed: no es la primera ejecución, solo quiere
        repasar la guía o cambiar el modo por defecto.

        `initial_mode` arranca la página de modos con el modo ACTUAL ya
        seleccionado (antes siempre arrancaba en "main" sin importar cuál
        tenía el usuario) -- si no, tocar "Omitir" sin pasar por esa
        página pisaba en silencio el modo guardado con "main" cada vez que
        alguien reabría la guía solo para repasar la parte de la
        extensión, por ejemplo."""
        wizard = WelcomeWizard(
            port=self.backend.port, parent=self.main_window, initial_mode=self._current_mode,
            start_with_windows=self.config.start_with_windows,
        )
        wizard.exec()
        self._apply_start_with_windows(wizard.result_start_with_windows)
        self._current_mode = wizard.result_default_mode
        self.config.last_mode = self._current_mode
        self.config.save()

    def shutdown(self):
        if self._shut_down:
            return
        self._shut_down = True
        self._settle_timer.stop()
        self._autosave_timer.stop()
        self._save_config()
        self.hotkeys.unregister_all()
        self.backend.stop()
        self.theme_bridge.stop()
        self.tray.hide()
        toast = getattr(self, "_weekly_recap_toast", None)
        if toast is not None:
            toast.close()

    def show_current(self):
        """Llamado por SingleInstanceGuard cuando alguien intenta abrir una
        segunda instancia: mostramos la ventana que corresponda en vez de
        arrancar de nuevo."""
        if self._current_mode == "mini":
            self._show_mini()
        elif self._current_mode == "dock":
            self._show_dock()
        else:
            self._show_main()

    # ------------------------------------------------- historial y notificaciones
    # ---------------------------------------------- "reproducir" sin reproductor
    AUTOPLAY_WINDOW_S = 40.0

    # ------------------------------------------------------------ "me gusta"
    def _open_likes_dialog(self, _service: str = ""):
        from likes_dialog import LikesDialog
        LikesDialog(self.config, on_changed=self._on_likes_account_changed, parent=self.main_window).exec()

    def _on_likes_account_changed(self):
        """Se conectó/desconectó una cuenta o se (des)activó el botón."""
        self.likes.forget_credentials()
        self.likes.track_changed(self._current_state if self._current_state.has_media else None)

    def _apply_play_idle_setting(self):
        enabled = getattr(self.config, "empty_play_action", "ask") != "none"
        for win in (self.main_window, self.mini_window, self.dock_window):
            win.set_play_idle_enabled(enabled)

    def _on_no_player_play(self):
        """Se pulso reproducir (boton, bandeja o atajo) y no hay ningun
        reproductor: abre Spotify/YouTube segun el ajuste, o pregunta."""
        action = getattr(self.config, "empty_play_action", "ask")
        if action == "none":
            return
        if action not in player_launcher.ACTIONS:
            action = self._choose_player_from_menu()
            if action is None:
                return
        self._start_player(action)

    def _choose_player_from_menu(self):
        """Menu junto al cursor con las opciones; None si se cierra sin elegir."""
        if self._start_menu_open:
            return None
        self._start_menu_open = True
        try:
            menu = QMenu()
            for key in player_launcher.ACTIONS:
                menu.addAction(player_launcher.LABELS[key]).setData(key)
            chosen = menu.exec(QCursor.pos())
            return chosen.data() if chosen is not None else None
        finally:
            self._start_menu_open = False

    def _start_player(self, action: str):
        if not player_launcher.launch(action):
            self.tray.showMessage("WNP Player",
                                  "No se pudo abrir el reproductor. Ábrelo manualmente.",
                                  self.icon, 5000)
            return
        # Spotify de escritorio abre en pausa (o con lo ultimo que sonaba): cuando
        # aparezca su sesion se le da play UNA vez. YouTube solo abre la pagina:
        # no hay nada concreto que reproducir hasta que el usuario elija.
        if action == "spotify":
            self._autoplay_until = time.monotonic() + self.AUTOPLAY_WINDOW_S

    def _maybe_autoplay(self, state: PlayerState):
        if not self._autoplay_until:
            return
        if time.monotonic() > self._autoplay_until:
            self._autoplay_until = 0.0
            return
        if not state.has_media or "spotify" not in (state.player_name or "").lower():
            return
        if state.state == "PLAYING":
            self._autoplay_until = 0.0        # ya suena solo
            return
        if state.can_play_pause:              # si aun no hay controles, se sigue esperando
            self._autoplay_until = 0.0
            self.backend.toggle_play_pause()

    def _on_playback_state_changed(self, state: PlayerState):
        self._maybe_autoplay(state)
        self._current_state = state
        if not state.has_media:
            self._settle_timer.stop()
            self._pending_track_key = None
            self._last_track_key = None
            self.likes.track_changed(None)
            self.scrobbler.stop_pending()
            self._set_tray_icon(self.icon)
            return

        key = (state.title, state.artist)
        if key == self._last_track_key:
            # Volvió a la canción ya registrada (o nunca cambió): cancela
            # cualquier registro pendiente de una lectura a medias.
            self._settle_timer.stop()
            self._pending_track_key = None
            return
        if self.TRACK_SETTLE_MS > 0:
            # Solo se reinicia la espera cuando la clave CAMBIA; los cambios
            # de posición (cada sondeo) no deben aplazarla indefinidamente.
            if key != self._pending_track_key:
                self._pending_track_key = key
                self._settle_timer.start(self.TRACK_SETTLE_MS)
            return
        self._register_track(state)

    def _commit_pending_track(self):
        self._pending_track_key = None
        state = self._current_state
        if not state.has_media or (state.title, state.artist) == self._last_track_key:
            return
        self._register_track(state)

    def _register_track(self, state: PlayerState):
        key = (state.title, state.artist)
        self._last_track_key = key

        # Anuncio de Spotify: va al registro aparte, y NO al historial, a las
        # estadísticas, al scrobbling (se enviaría a Last.fm/ListenBrainz como
        # si fuera música) ni a las notificaciones de "nueva canción".
        reason = ad_filter.detect(state.title, state.artist, state.player_name)
        if reason:
            ad_log.add_entry(state.title, state.artist, state.player_name,
                             state.duration_seconds, reason)
            self.scrobbler.stop_pending()   # lo que estaba por scrobblearse ya no suena
            self.likes.track_changed(None)  # un anuncio no se puede "guardar"
            return

        self.likes.track_changed(state)     # ya estable (pasó el debounce): consulta "me gusta"
        history.add_entry(state.title, state.artist, state.player_name, state.duration_seconds)
        self.scrobbler.track_changed(state.artist, state.title, state.album, state.duration_seconds)
        # La carátula puede no estar cacheada todavía (recién empieza a
        # descargarse) — se pone lo que haya ahora mismo (ícono de la app
        # como fallback) y _on_cover_ready_for_tray la actualiza sola en
        # cuanto termine de bajar.
        self._set_tray_icon(self._notification_icon())

        if self.config.notifications_enabled and state.state == "PLAYING":
            self._show_track_notification(state)

    def _on_cover_ready_for_tray(self, url: str, image):
        """Ícono de bandeja dinámico: apenas termina de bajar la carátula
        de la canción actual, se usa como ícono en miniatura en vez del
        logo genérico de la app."""
        if not self._current_state.has_media or url != self._current_state.cover_url:
            return
        if image is None or image.isNull():
            return
        self._set_tray_icon(QIcon(QPixmap.fromImage(image)))

    def _set_tray_icon(self, icon: QIcon):
        self.tray.setIcon(icon)

    def _show_track_notification(self, state: PlayerState):
        icon = self._notification_icon()
        subtitle = state.artist or "Artista desconocido"
        self.tray.showMessage(state.title or "Reproduciendo", subtitle, icon, 5000)

    def _notification_icon(self) -> QIcon:
        """Usa la carátula actual como ícono de la notificación si ya está
        cargada; si no, cae de vuelta al ícono de la app."""
        cached = self.cover_loader._cache.get(self._current_state.cover_url)
        if cached is not None and not cached.isNull():
            return QIcon(QPixmap.fromImage(cached))
        return self.icon

    # ------------------------------------------------------ config guardada
    def _restore_config(self):
        cfg = self.config
        self._current_mode = cfg.last_mode if cfg.last_mode in ("main", "mini", "dock") else "main"

        if cfg.main_width:
            width = max(MAIN_MIN_WIDTH, min(MAIN_MAX_WIDTH, cfg.main_width))
            self.main_window.set_content_width(width)
        # (0, 0) exacto = valor basura guardado por versiones anteriores para
        # ventanas que nunca se mostraron: se trata como "sin posición".
        if cfg.main_x is not None and cfg.main_y is not None and (cfg.main_x, cfg.main_y) != (0, 0):
            self._move_within_screen(self.main_window, cfg.main_x, cfg.main_y)
            self._main_positioned = True

        if cfg.mini_scale:
            self.mini_window.set_scale(cfg.mini_scale)
        if cfg.mini_x is not None and cfg.mini_y is not None and (cfg.mini_x, cfg.mini_y) != (0, 0):
            self._move_within_screen(self.mini_window, cfg.mini_x, cfg.mini_y)
            self._mini_positioned = True

        self.dock_window.set_edge(cfg.dock_edge)
        self.dock_window.set_hide_mode(cfg.dock_hide_mode)
        self.dock_window.set_style(cfg.dock_style)
        self.dock_window.set_waves_enabled(cfg.bar_waves_enabled)

        self.main_window.set_always_on_top(cfg.always_on_top)
        self.main_window.start_minimized_enabled = cfg.start_minimized
        self.main_window.set_lyrics_panel_side(cfg.lyrics_panel_side)
        self.main_window.set_lyrics_panel_enabled(cfg.lyrics_panel_enabled, animate=False)
        self._apply_window_opacity(cfg.window_opacity)
        self.main_window.set_youtube_api_key(cfg.youtube_api_key)

        if cfg.hotkeys_enabled and self.hotkeys.available:
            self._register_saved_hotkeys()

    def _register_saved_hotkeys(self):
        cfg = self.config
        combos = {
            "play_pause": cfg.hotkey_play_pause,
            "next": cfg.hotkey_next,
            "previous": cfg.hotkey_previous,
        }
        for action, combo in combos.items():
            if combo:
                self.hotkeys.register(action, combo)

    def _apply_window_opacity(self, value: float):
        """Se aplica en caliente (a diferencia de font_scale/high_contrast):
        setWindowOpacity() es una propiedad normal de Qt, no requiere
        reconstruir ningún widget. Guarda el valor para que _fade_in()
        anime hacia acá en vez de hacia 1.0 siempre."""
        value = max(0.5, min(1.0, value))
        self.config.window_opacity = value
        self.main_window.setWindowOpacity(value)
        self.mini_window.setWindowOpacity(value)

    def _move_within_screen(self, window, x: int, y: int):
        """Deja la ventana donde estaba la última vez, pero sin permitir que
        quede fuera de la pantalla (por ejemplo si cambió la resolución o
        se desconectó un segundo monitor desde la última sesión)."""
        # Antes se acotaba SIEMPRE contra la pantalla principal: si la ventana
        # estaba en un segundo monitor (que sigue conectado), en cada arranque
        # se la arrastraba de vuelta al monitor principal. Ahora se elige la
        # pantalla que contiene la posición guardada (o la más cercana, si ese
        # monitor ya no existe) y se acota contra ESA.
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QGuiApplication
        pos = QPoint(x, y)
        screens = QGuiApplication.screens() or [QApplication.primaryScreen()]
        target = None
        for s in screens:
            if s.geometry().contains(pos):
                target = s
                break
        if target is None:
            def _dist2(s):
                g = s.geometry()
                dx = max(g.left() - x, 0, x - g.right())
                dy = max(g.top() - y, 0, y - g.bottom())
                return dx * dx + dy * dy
            target = min(screens, key=_dist2)
        screen = target.availableGeometry()
        x = max(screen.left(), min(x, screen.right() - 60))
        y = max(screen.top(), min(y, screen.bottom() - 60))
        window.move(x, y)

    def _save_config(self):
        cfg = self.config
        cfg.port = self.backend.port
        cfg.last_mode = self._current_mode
        cfg.always_on_top = self.main_window.is_always_on_top()
        cfg.main_width = self.main_window.content_width()
        if self._main_positioned:   # una ventana nunca mostrada reporta (0, 0)
            cfg.main_x = self.main_window.x()
            cfg.main_y = self.main_window.y()
        cfg.lyrics_panel_enabled = self.main_window.is_lyrics_panel_enabled()
        cfg.lyrics_panel_side = self.main_window.lyrics_panel_side()
        cfg.mini_scale = self.mini_window.scale()
        if self._mini_positioned:
            cfg.mini_x = self.mini_window.x()
            cfg.mini_y = self.mini_window.y()
        cfg.save()

    # -------------------------------------------------------------- bandeja
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self.icon)
        tray.setToolTip("WNP Player")

        menu = QMenu()
        self.tray_playpause_action = menu.addAction("Reproducir / Pausar")
        self.tray_playpause_action.triggered.connect(self.backend.toggle_play_pause)
        menu.addAction("Anterior", self.backend.previous)
        menu.addAction("Siguiente", self.backend.next)
        menu.addSeparator()
        menu.addAction("Mostrar reproductor", self._show_main)
        menu.addAction("Modo compacto", self._show_mini)
        menu.addSeparator()
        menu.addMenu(make_theme_menu("Tema de Spotify", self.theme_bridge, menu))
        menu.addAction("Configuración...", self._open_settings_dialog)
        menu.addAction("Registro de anuncios (CSV)...", self._open_ad_log)
        menu.addSeparator()
        menu.addAction("Salir", self._quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _open_ad_log(self):
        """Abre anuncios.csv con la aplicación predeterminada (Excel, etc.)."""
        p = ad_log.path()
        if not p.exists():
            self.tray.showMessage(
                "WNP Player", "Todavía no se registró ningún anuncio de Spotify.",
                self.icon, 3000,
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.main_window.isVisible() or self.mini_window.isVisible():
                self._hide_all()
            else:
                self.show_current()

    # -------------------------------------------------------------- paneles
    def _open_settings_dialog(self):
        dlg = SettingsDialog(
            self.config, self.backend.port,
            open_hotkeys_callback=self._open_hotkey_dialog,
            open_history_callback=self._open_history_dialog,
            open_stats_callback=self._open_stats_dialog,
            theme_bridge=self.theme_bridge,
            theme_enabled=self.config.spotify_theme_enabled,
            parent=self.main_window,
        )
        dlg.on_likes_changed = self._on_likes_account_changed
        if dlg.exec() == dlg.DialogCode.Accepted:
            cfg = self.config
            self._apply_spotify_theme_settings(
                dlg.result_spotify_theme_enabled, dlg.result_spotify_theme_mode)
            if dlg.result_port != self.backend.port:
                self._change_port(dlg.result_port)
            self.main_window.set_always_on_top(dlg.result_always_on_top)
            self.main_window.start_minimized_enabled = dlg.result_start_minimized
            self.main_window.set_lyrics_panel_enabled(dlg.result_lyrics_panel_enabled)
            self._apply_window_opacity(dlg.result_window_opacity)
            cfg.start_minimized = dlg.result_start_minimized
            self._apply_start_with_windows(dlg.result_start_with_windows)
            cfg.notifications_enabled = dlg.result_notifications
            cfg.empty_play_action = dlg.result_empty_play_action
            self._apply_play_idle_setting()
            cfg.lyrics_panel_enabled = dlg.result_lyrics_panel_enabled

            cfg.dock_edge = dlg.result_dock_edge
            cfg.dock_hide_mode = dlg.result_dock_hide_mode
            cfg.dock_style = dlg.result_dock_style
            self.dock_window.set_edge(cfg.dock_edge)
            self.dock_window.set_hide_mode(cfg.dock_hide_mode)
            self.dock_window.set_style(cfg.dock_style)
            cfg.bar_waves_enabled = dlg.result_bar_waves
            self.dock_window.set_waves_enabled(cfg.bar_waves_enabled)

            cfg.scrobble_service = dlg.result_scrobble_service
            cfg.lastfm_api_key = dlg.result_lastfm_api_key
            cfg.lastfm_api_secret = dlg.result_lastfm_api_secret
            cfg.lastfm_session_key = dlg.result_lastfm_session_key
            cfg.lastfm_username = dlg.result_lastfm_username
            cfg.listenbrainz_token = dlg.result_listenbrainz_token
            cfg.youtube_api_key = dlg.result_youtube_api_key
            self.main_window.set_youtube_api_key(cfg.youtube_api_key)

            restart_needed = (
                dlg.result_font_scale != cfg.font_scale
                or dlg.result_high_contrast != cfg.high_contrast
                or dlg.result_ui_scale != cfg.ui_scale
                or dlg.result_player_theme != cfg.player_theme
            )
            cfg.player_theme = dlg.result_player_theme
            cfg.font_scale = dlg.result_font_scale
            cfg.ui_scale = dlg.result_ui_scale
            cfg.high_contrast = dlg.result_high_contrast
            self._save_config()
            if restart_needed:
                self.tray.showMessage(
                    "WNP Player",
                    "El aspecto / tamaño de letra / escala / alto contraste se aplica la "
                    "próxima vez que abras el reproductor.",
                    self.icon, 5000,
                )

    def _apply_spotify_theme_settings(self, enabled: bool, mode_id: str):
        """Se aplica en caliente (no pide reiniciar). mode_id vacío = el
        usuario no eligió ningún modo (no se toca el que tiene Spotify)."""
        self.config.spotify_theme_enabled = enabled
        if not enabled:
            self.theme_bridge.stop()
            return
        self.theme_bridge.start()   # no hace nada si ya está corriendo
        if mode_id and mode_id != self.theme_bridge.mode():
            self.theme_bridge.set_mode(mode_id)

    def _on_spotify_theme_mode(self, mode_id: str):
        # Spotify informó (o se eligió aquí) un modo: se recuerda para mostrarlo
        # la próxima vez aunque Spotify esté cerrado. Se guarda con el autoguardado.
        self.config.spotify_theme_mode = mode_id

    def _on_theme_bridge_error(self, message: str):
        self.tray.showMessage("WNP Player", message, self.icon, 5000)

    def _open_history_dialog(self):
        dlg = HistoryDialog(
            history.load(), self.main_window,
            initial_scroll_pos=self.config.history_scroll_pos,
        )
        dlg.exec()
        self.config.history_scroll_pos = dlg.result_scroll_pos
        self._save_config()

    def _open_stats_dialog(self):
        state = self._current_state
        dlg = StatsDialog(
            history.load(),
            current_title=state.title if state.has_media else "",
            current_artist=state.artist if state.has_media else "",
            parent=self.main_window,
            initial_scroll_pos=self.config.stats_scroll_pos,
        )
        dlg.exec()
        self.config.stats_scroll_pos = dlg.result_scroll_pos
        self._save_config()

    def _open_recently_played_dialog(self):
        # can_open (tocar una entrada abre/reproduce esa canción) solo
        # cuando no hay nada sonando ahora mismo — así se evita
        # interrumpir sin querer algo que ya está sonando.
        can_open = not self._current_state.has_media
        RecentlyPlayedDialog(
            history.load(), can_open, self.main_window,
            youtube_api_key=self.config.youtube_api_key,
        ).exec()

    def _open_hotkey_dialog(self):
        dlg = HotkeyDialog(self.config, self.hotkeys, self.main_window)
        if dlg.exec() == dlg.DialogCode.Accepted:
            cfg = self.config
            cfg.hotkeys_enabled = dlg.result_enabled
            cfg.hotkey_play_pause = dlg.result_combos["play_pause"]
            cfg.hotkey_next = dlg.result_combos["next"]
            cfg.hotkey_previous = dlg.result_combos["previous"]
            cfg.save()

            # El diálogo ya probó registrar todo antes de aceptar (para
            # avisar de conflictos), pero lo dejó registrado bajo prueba;
            # si el usuario desactivó el interruptor general, hay que
            # soltarlo todo igual.
            if not cfg.hotkeys_enabled:
                self.hotkeys.unregister_all()

    # -------------------------------------------------------------- ventanas
    def _wire_windows(self):
        mw = self.main_window
        mw.compactModeRequested.connect(self._show_mini)
        mw.dockModeRequested.connect(self._show_dock)
        mw.hideToTrayRequested.connect(self._hide_all)
        mw.quitRequested.connect(self._quit)
        mw.portChangeRequested.connect(self._change_port)
        mw.startMinimizedToggleRequested.connect(self._on_start_minimized_toggled)
        mw.hotkeyDialogRequested.connect(self._open_hotkey_dialog)
        mw.settingsDialogRequested.connect(self._open_settings_dialog)
        mw.welcomeDialogRequested.connect(self._reopen_onboarding)
        mw.recentlyPlayedRequested.connect(self._open_recently_played_dialog)

        miw = self.mini_window
        miw.expandRequested.connect(self._show_main)
        miw.hideToTrayRequested.connect(self._hide_all)

        dw = self.dock_window
        dw.restoreMainRequested.connect(self._show_main)

    def _show_main(self):
        self.mini_window.hide()
        self.dock_window.hide()
        self.backend.set_poll_interval(POLL_INTERVAL_MS)
        was_hidden = not self.main_window.isVisible()
        if was_hidden and not self._main_positioned:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.main_window.width() - 40
            y = screen.top() + 60
            self.main_window.move(x, y)
            self._main_positioned = True
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        if was_hidden:
            self._fade_in(self.main_window)
        self._current_mode = "main"

    def _show_mini(self):
        self.main_window.hide()
        self.dock_window.hide()
        self.backend.set_poll_interval(POLL_INTERVAL_MS)
        was_hidden = not self.mini_window.isVisible()
        if was_hidden and not self._mini_positioned:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.mini_window.width() - 30
            y = screen.bottom() - self.mini_window.height() - 30
            self.mini_window.move(x, y)
            self._mini_positioned = True
        self.mini_window.show()
        self.mini_window.raise_()
        if was_hidden:
            self._fade_in(self.mini_window)
        self._current_mode = "mini"

    def _show_dock(self):
        """Modo panel lateral (dock_window.py): a diferencia de main/mini,
        no tiene sentido un fundido de entrada acá — arranca colapsada
        (solo la pestaña asomando en el borde) y es la propia animación de
        deslizamiento la que se encarga de cualquier transición visible."""
        self.main_window.hide()
        self.mini_window.hide()
        self.backend.set_poll_interval(POLL_INTERVAL_MS)
        self.dock_window.set_edge(self.config.dock_edge)
        self.dock_window.set_hide_mode(self.config.dock_hide_mode)
        self.dock_window.set_style(self.config.dock_style)
        self.dock_window.show_on_edge()
        self._current_mode = "dock"

    def _fade_in(self, window, duration_ms: int = 160):
        """Pequeño fundido de entrada al aparecer, en vez de aparecer de
        golpe. Si ya había un fundido a medias sobre esta misma ventana
        (por ejemplo, el usuario alternó rápido entre completa y compacta
        antes de que terminara), lo cancelamos y continuamos suavemente
        desde donde iba, en vez de dejar que compitan dos animaciones a la
        vez sobre la misma propiedad (eso es lo que causaba el parpadeo)."""
        existing = self._fade_anims.pop(window, None)
        if existing is not None and existing.state() == QPropertyAnimation.State.Running:
            existing.stop()
            start_opacity = window.windowOpacity()
        else:
            start_opacity = 0.0
            window.setWindowOpacity(0.0)

        anim = QPropertyAnimation(window, b"windowOpacity", window)
        anim.setDuration(duration_ms)
        anim.setStartValue(start_opacity)
        anim.setEndValue(self.config.window_opacity)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _cleanup():
            if self._fade_anims.get(window) is anim:
                del self._fade_anims[window]
        anim.finished.connect(_cleanup)

        self._fade_anims[window] = anim
        anim.start()

    def _hide_all(self):
        self.main_window.hide()
        self.mini_window.hide()
        self.dock_window.hide()
        # Nada que animar/mostrar si no se ve ninguna ventana: sondear cada
        # 150ms ahí es CPU desperdiciada. Vuelve a la normalidad en
        # _show_main/_show_mini/_show_dock apenas se muestra cualquiera.
        self.backend.set_poll_interval(IDLE_POLL_INTERVAL_MS)

    def _change_port(self, port: int):
        # Solo se guarda el puerto si el servidor realmente quedó escuchando
        # en él; si estaba ocupado, restart_on_port conserva el anterior.
        if self.backend.restart_on_port(port):
            self.config.port = port
            self.config.save()

    def _on_start_minimized_toggled(self, enabled: bool):
        self.config.start_minimized = enabled
        self.config.save()

    def _on_hotkey_triggered(self, action: str):
        if action == "play_pause":
            self.backend.toggle_play_pause()
        elif action == "next":
            self.backend.next()
        elif action == "previous":
            self.backend.previous()

    def _on_server_error(self, message: str):
        # Sin esto, si el sondeo (cada 150ms en uso normal) empieza a
        # fallar de forma persistente, cada intento dispara una
        # notificación nueva — decenas por segundo, inundando al usuario.
        # Con throttle: la MISMA notificación amistosa en el reproductor
        # (platform_label, vía backend.serverError → main_window) sigue
        # actualizándose siempre, pero el AVISO de la bandeja del sistema
        # (más intrusivo, con sonido/popup del SO) se limita a como mucho
        # uno cada 30s por el mismo mensaje.
        now = datetime.datetime.now()
        same_as_last = message == self._last_error_message
        recently_notified = (
            self._last_error_notified_at is not None
            and (now - self._last_error_notified_at).total_seconds() < 30
        )
        self._last_error_message = message
        if same_as_last and recently_notified:
            return
        self._last_error_notified_at = now
        self.tray.showMessage("WNP Player", message, self.icon, 5000)

    def _quit(self):
        self.shutdown()
        QApplication.instance().quit()
