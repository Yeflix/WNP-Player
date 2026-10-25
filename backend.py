"""
Backend de comunicación con la extensión de navegador WebNowPlaying.

Usa la librería `pywnp`, que implementa el servidor WebSocket compatible con
la extensión oficial de WebNowPlaying (https://wnp.keifufu.dev). Ese servidor
es exactamente lo mismo que usa el plugin de Rainmeter (WebNowPlaying.dll):
la extensión del navegador se conecta a nuestro programa igual que se
conectaría a Rainmeter, por eso esto funciona como reproductor independiente
para YouTube, Spotify (web) y cualquier otro sitio soportado por la extensión.

En Windows, pywnp también expone automáticamente las sesiones multimedia
nativas de Windows (SMTC) para apps de escritorio como Spotify.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

APP_VERSION = "1.0.0"
DEFAULT_PORT = 1234
POLL_INTERVAL_MS = 150
IDLE_POLL_INTERVAL_MS = 700  # cuando ninguna ventana está visible (ver set_poll_interval)


@dataclass
class PlayerState:
    connected: bool = False
    clients: int = 0
    player_name: str = ""
    state: str = "STOPPED"          # STOPPED | PLAYING | PAUSED
    title: str = ""
    artist: str = ""
    album: str = ""
    cover_url: str = ""
    duration: str = "0:00"
    duration_seconds: int = 0
    position: str = "0:00"
    position_seconds: int = 0
    position_percent: float = 0.0
    volume: int = 100
    shuffle_active: bool = False
    repeat_mode: str = "NONE"       # NONE | ONE | ALL
    can_play_pause: bool = False
    can_prev: bool = False
    can_next: bool = False
    can_seek: bool = False
    can_volume: bool = False
    can_shuffle: bool = False
    can_repeat: bool = False

    @property
    def has_media(self) -> bool:
        return bool(self.title) or self.state != "STOPPED"

    @property
    def duration_known(self) -> bool:
        """False para fuentes que exponen controles (play/pausa/siguiente/
        anterior) pero nunca informaron una duración real -- típicamente
        apps de escritorio en Windows que registran una sesión SMTC mínima
        (solo botones) sin metadata ni línea de tiempo, como Telegram. Con
        esto la interfaz puede diferenciar "0:00 real, recién empezó" de
        "no tenemos ese dato", en vez de mostrar una barra de progreso
        engañosa. Ver Bug #10 en pywnp_patch.py."""
        return self.duration_seconds > 0

    @property
    def controls_available(self) -> bool:
        """Muchos sitios (y a veces incluso sesiones nativas) no reportan bien
        los flags `supports_*` de forma individual, así que en vez de deshabilitar
        botones uno por uno por eso, los habilitamos con que haya una fuente
        conectada. Los métodos `try_*` de pywnp son seguros de invocar aunque la
        acción no esté realmente soportada por el reproductor: no hacen nada."""
        return self.connected and self.has_media


class WNPBackend(QObject):
    """Envuelve pywnp y expone su estado mediante señales de Qt (sondeo por temporizador)."""

    stateChanged = pyqtSignal(object)      # PlayerState
    connectionChanged = pyqtSignal(bool)   # hay al menos un cliente (extensión) conectado
    logMessage = pyqtSignal(str, str)      # nivel, mensaje
    serverError = pyqtSignal(str)
    started = pyqtSignal(int)              # puerto
    stopped = pyqtSignal()
    # Se pulso "reproducir" (boton, bandeja o atajo) sin ningun reproductor
    # abierto: la app decide si abrir Spotify/YouTube (ver app_controller).
    noPlayerPlayRequested = pyqtSignal()

    def __init__(self, port: int = DEFAULT_PORT, poll_interval_ms: int = POLL_INTERVAL_MS,
                 parent=None):
        super().__init__(parent)
        self.port = port
        self._running = False
        self._last_connected: bool | None = None
        self._last_state: PlayerState | None = None
        # Desde cuando NO hay nada reproducible (None = ahora mismo hay algo).
        # Se exige un margen (NO_PLAYER_GRACE_S) para no confundir el hueco
        # de 1-2 s entre dos canciones de YouTube con "no hay reproductor".
        self._no_media_since: float | None = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll)

    @property
    def is_running(self) -> bool:
        return self._running

    def set_poll_interval(self, ms: int):
        """AppController lo llama con IDLE_POLL_INTERVAL_MS cuando ninguna
        de las dos ventanas está visible (minimizado a la bandeja) y con
        POLL_INTERVAL_MS al volver a mostrar cualquiera. No hay nada que
        animar si no se ve, así que sondear tan seguido ahí es CPU
        desperdiciada; el cambio es transparente para quien escucha
        stateChanged, no afecta el resto de la lógica."""
        if self._timer.interval() == ms:
            return
        self._timer.setInterval(ms)

    # --- Ciclo de vida --------------------------------------------------
    def start(self):
        if self._running:
            return
        # pywnp no avisa de ninguna forma si el puerto ya está en uso: se
        # queda reintentando en silencio cada 5s para siempre (lo verificamos
        # directamente). Por eso comprobamos el puerto nosotros mismos antes.
        if not self._port_is_free(self.port):
            self.serverError.emit(
                f"El puerto {self.port} ya está en uso por otro programa. "
                f"Cambia de puerto desde el menú (clic derecho)."
            )
            return
        try:
            import pywnp_patch
            pywnp_patch.apply()  # corrige el bug de pywnp con sesiones nativas (ver pywnp_patch.py)

            from pywnp import WNPRedux
            self._wnp = WNPRedux
            self._wnp.start(self.port, APP_VERSION, self._on_log)
            self._running = True
            self._last_connected = None
            self._timer.start()
            self.started.emit(self.port)
        except Exception as exc:  # noqa: BLE001
            self.serverError.emit(self._format_start_error(exc))

    @staticmethod
    def _port_is_free(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

    def stop(self):
        if not self._running:
            return
        self._timer.stop()
        try:
            self._wnp.stop()
        except Exception:  # noqa: BLE001
            pass
        self._running = False
        self._last_state = None   # tras reiniciar hay que volver a emitir el estado
        self.stopped.emit()

    def restart_on_port(self, port: int) -> bool:
        """Mueve el servidor a `port`. Devuelve True si quedó escuchando ahí.

        Si el puerto nuevo está ocupado NO se toca el servidor actual (antes se
        paraba primero y el usuario se quedaba sin servidor). Si el arranque en
        el puerto nuevo falla igualmente, se vuelve al anterior.
        """
        if port != self.port or not self._running:
            if not self._port_is_free(port) and not (self._running and port == self.port):
                self.serverError.emit(
                    f"El puerto {port} ya está en uso por otro programa. "
                    f"Se mantiene el puerto {self.port}."
                )
                return False
        old_port = self.port
        self.stop()
        self.port = port
        self.start()
        if not self._running and port != old_port:
            self.port = old_port
            self.start()
            return False
        return self._running

    def _format_start_error(self, exc: Exception) -> str:
        text = str(exc)
        if "Address already in use" in text or "10048" in text or "OSError" in type(exc).__name__:
            return (f"El puerto {self.port} ya está en uso. Prueba con otro puerto "
                    f"desde el menú de configuración.")
        return f"No se pudo iniciar el servidor WebNowPlaying: {text}"

    def _on_log(self, level: str, message: str):
        self.logMessage.emit(level, message)

    # --- Sondeo del estado -----------------------------------------------
    def _poll(self):
        try:
            mi = self._wnp.media_info
            ctr = mi.controls
            # `self._wnp.clients` solo cuenta clientes WebSocket (la extensión
            # del navegador). Los reproductores nativos de Windows (p. ej. la
            # app de escritorio de Spotify) no pasan por ahí: pywnp les asigna
            # player_name = "Windows Media Session" en su lugar, así que
            # "conectado" debe considerar ambas vías.
            connected = self._wnp.clients > 0 or bool(mi.player_name)
            state = PlayerState(
                connected=connected,
                clients=self._wnp.clients,
                player_name=mi.player_name,
                state=mi.state,
                title=mi.title,
                artist=mi.artist,
                album=mi.album,
                cover_url=mi.cover_url,
                duration=mi.duration,
                duration_seconds=mi.duration_seconds,
                position=mi.position,
                position_seconds=mi.position_seconds,
                # Sin duración conocida (directos, apps nativas sin timeline)
                # pywnp reporta 100 %: la barra se veía llena. Se fuerza a 0.
                position_percent=(float(mi.position_percent or 0.0)
                                  if (mi.duration_seconds or 0) > 0 else 0.0),
                volume=mi.volume,
                shuffle_active=mi.shuffle_active,
                repeat_mode=mi.repeat_mode,
                can_play_pause=ctr.supports_play_pause,
                can_prev=ctr.supports_skip_previous,
                can_next=ctr.supports_skip_next,
                can_seek=ctr.supports_set_position,
                can_volume=ctr.supports_set_volume,
                can_shuffle=ctr.supports_toggle_shuffle_active,
                can_repeat=ctr.supports_toggle_repeat_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.serverError.emit(f"Error leyendo el estado de reproducción: {exc}")
            return

        if state.has_media:
            self._no_media_since = None
        elif self._no_media_since is None:
            self._no_media_since = time.monotonic()

        if connected != self._last_connected:
            self._last_connected = connected
            self.connectionChanged.emit(connected)

        # Mientras suena algo, position_seconds/position_percent cambian
        # en cada sondeo, así que esto NO frena la barra de progreso. Solo
        # ahorra trabajo río abajo (3 suscriptores: main_window,
        # mini_window, app_controller) cuando está pausado/detenido y el
        # estado es literalmente idéntico al del sondeo anterior.
        if state == self._last_state:
            return
        self._last_state = state
        self.stateChanged.emit(state)

    # --- Controles (siempre seguros de invocar) --------------------------
    def _controls(self):
        return self._wnp.media_info.controls

    NO_PLAYER_GRACE_S = 1.0

    def has_no_player(self) -> bool:
        """True si lleva al menos NO_PLAYER_GRACE_S sin ningun reproductor."""
        since = self._no_media_since
        return since is not None and (time.monotonic() - since) >= self.NO_PLAYER_GRACE_S

    def toggle_play_pause(self):
        if self._running and self.has_no_player():
            # No hay a quien mandarle el "play": en vez de no hacer nada,
            # se avisa para ofrecer abrir Spotify o YouTube.
            self.noPlayerPlayRequested.emit()
            return
        self._safe(lambda: self._controls().try_toggle_play_pause())

    def previous(self):
        self._safe(lambda: self._controls().try_skip_previous())

    def next(self):
        self._safe(lambda: self._controls().try_skip_next())

    def seek_percent(self, percent: float):
        self._safe(lambda: self._controls().try_set_position_percent(percent))

    def set_volume(self, volume: int):
        self._safe(lambda: self._controls().try_set_volume(int(volume)))

    def toggle_shuffle(self):
        self._safe(lambda: self._controls().try_toggle_shuffle_active())

    def toggle_repeat(self):
        self._safe(lambda: self._controls().try_toggle_repeat_mode())

    def _safe(self, fn):
        if not self._running:
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            self.serverError.emit(f"No se pudo ejecutar el control: {exc}")
