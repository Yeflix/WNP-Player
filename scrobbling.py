"""
Envía cada canción escuchada a Last.fm o ListenBrainz (a elección, ver
SettingsDialog), además de guardarla en el historial local de siempre —
ítem #2 de las propuestas pendientes.

Diseño:
- Las funciones de bajo nivel (`lastfm_*`, `listenbrainz_*`) son
  sincrónicas y solo dependen de la librería estándar (`urllib.request`,
  `hashlib`, `json`): sin agregar `requests` ni ninguna otra dependencia
  nueva al empaquetado (ver main.spec, que ya lidia con bastante por el
  lado de aiohttp/pywnp). Nunca lanzan: cualquier error de red, HTTP o de
  datos se devuelve como string en vez de propagarse, porque un scrobble
  fallido no debe interrumpir nada de la reproducción.
- `ScrobbleManager` es la pieza que usa app_controller.py: escucha los
  cambios de canción, dispara "ahora suena" de inmediato y programa el
  scrobble real (el que cuenta como "escuchada" en Last.fm/ListenBrainz)
  para más adelante, respetando la regla estándar que usan ambos
  servicios: recién a partir de la mitad de la duración (o a los 4
  minutos, lo que ocurra primero), y solo si la canción dura más de 30
  segundos. Todo el trabajo de red corre en un hilo de fondo
  (ThreadPoolExecutor) para no bloquear la interfaz ni el sondeo de
  reproducción.
"""
from __future__ import annotations

from version import user_agent

import contextlib
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from diag import soft

_TIMEOUT_SECONDS = 8
_LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
_LISTENBRAINZ_SUBMIT_URL = "https://api.listenbrainz.org/1/submit-listens"

# Reglas de scrobbling estándar (las mismas que usa Last.fm y que
# ListenBrainz adoptó igual, para no reinventar nada): no vale la pena
# contar canciones muy cortas, y no hace falta esperar más de 4 minutos
# aunque la canción sea muy larga.
MIN_TRACK_SECONDS_TO_SCROBBLE = 30
MAX_WAIT_SECONDS = 240


class SendError(str):
    """Texto de error de un envío (sigue siendo un `str`, como antes) que además
    dice si vale la pena reintentarlo más tarde: sin conexión, servidor caído o
    límite de peticiones → sí; credenciales o datos inválidos → no (reintentar
    no lo arreglaría y la cola crecería para nada)."""

    retryable: bool = False

    def __new__(cls, text: str, retryable: bool = False):
        obj = super().__new__(cls, text)
        obj.retryable = retryable
        return obj


def _http_retryable(code: int) -> bool:
    return code == 429 or code >= 500


# Códigos de error de Last.fm que son temporales (last.fm/api/errorcodes):
# 11 servicio desconectado, 16 error temporal, 29 límite de peticiones.
_LASTFM_RETRYABLE_CODES = {11, 16, 29}


# ============================== Last.fm ===================================

def _lastfm_sign(params: dict, api_secret: str) -> str:
    """api_sig de Last.fm: los parámetros (sin 'format' ni 'callback')
    ordenados alfabéticamente por clave, concatenados como clave+valor sin
    separadores, más el secreto al final, todo en un solo hash MD5. Está
    documentado así en last.fm/api/authspec — no es una elección nuestra,
    es el algoritmo que exige la API."""
    parts = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    return hashlib.md5((parts + api_secret).encode("utf-8"), usedforsecurity=False).hexdigest()


def _lastfm_call(params: dict, api_secret: str) -> tuple[dict | None, str | None]:
    """POST firmado genérico a la API de Last.fm. Devuelve (datos, error);
    exactamente uno de los dos es None."""
    signed = dict(params)
    signed["api_sig"] = _lastfm_sign(params, api_secret)
    signed["format"] = "json"
    from urllib.parse import urlencode
    body = urlencode(signed).encode("utf-8")
    req = urllib.request.Request(
        _LASTFM_API_URL, data=body, method="POST",
        headers={"User-Agent": user_agent(), "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        retry = _http_retryable(exc.code)
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            code = data.get("error")
            retry = retry or (isinstance(code, int) and code in _LASTFM_RETRYABLE_CODES)
            return None, SendError(data.get("message", f"Error HTTP {exc.code}"), retry)
        except Exception:
            return None, SendError(f"Error HTTP {exc.code}", retry)
    except Exception as exc:
        return None, SendError(f"No se pudo conectar con Last.fm: {exc}", True)

    if isinstance(data, dict) and "error" in data:
        code = data.get("error")
        return None, SendError(str(data.get("message") or f"Error {code}"),
                               isinstance(code, int) and code in _LASTFM_RETRYABLE_CODES)
    return data, None


def lastfm_get_mobile_session(username: str, password: str, api_key: str,
                               api_secret: str) -> tuple[str, str, str | None]:
    """Autenticación 'mobile session' de Last.fm: usuario+contraseña van
    UNA sola vez en este pedido puntual (nunca se guardan) y a cambio se
    obtiene una session key de larga duración, que es lo único que queda
    persistido. Es el mismo mecanismo que usan varios scrobblers de
    escritorio clásicos para no depender de un navegador ni de un
    servidor de callback local. Devuelve (session_key, nombre_a_mostrar,
    error) — session_key es '' si hubo error."""
    if not (username and password and api_key and api_secret):
        return "", "", "Faltan datos."
    params = {
        "method": "auth.getMobileSession",
        "username": username,
        "password": password,
        "api_key": api_key,
    }
    data, error = _lastfm_call(params, api_secret)
    if error:
        return "", "", error
    try:
        session = data["session"]
        return str(session["key"]), str(session.get("name") or username), None
    except Exception:
        return "", "", "Respuesta inesperada de Last.fm."


def lastfm_update_now_playing(api_key: str, api_secret: str, session_key: str,
                               artist: str, title: str, album: str = "",
                               duration_seconds: int = 0) -> str | None:
    params = {
        "method": "track.updateNowPlaying",
        "api_key": api_key,
        "sk": session_key,
        "artist": artist,
        "track": title,
    }
    if album:
        params["album"] = album
    if duration_seconds > 0:
        params["duration"] = str(duration_seconds)
    _, error = _lastfm_call(params, api_secret)
    return error


def lastfm_scrobble(api_key: str, api_secret: str, session_key: str,
                     artist: str, title: str, timestamp: int, album: str = "",
                     duration_seconds: int = 0) -> str | None:
    params = {
        "method": "track.scrobble",
        "api_key": api_key,
        "sk": session_key,
        "artist": artist,
        "track": title,
        "timestamp": str(timestamp),
    }
    if album:
        params["album"] = album
    if duration_seconds > 0:
        params["duration"] = str(duration_seconds)
    _, error = _lastfm_call(params, api_secret)
    return error


# ============================ ListenBrainz =================================

def _listenbrainz_submit(token: str, listen_type: str, payload: list) -> str | None:
    body = json.dumps({"listen_type": listen_type, "payload": payload}).encode("utf-8")
    req = urllib.request.Request(
        _LISTENBRAINZ_SUBMIT_URL, data=body, method="POST",
        headers={
            "User-Agent": user_agent(),
            "Content-Type": "application/json",
            "Authorization": f"Token {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            resp.read()
        return None
    except urllib.error.HTTPError as exc:
        retry = _http_retryable(exc.code)
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            return SendError(str(data.get("error") or f"Error HTTP {exc.code}"), retry)
        except Exception:
            return SendError(f"Error HTTP {exc.code}", retry)
    except Exception as exc:
        return SendError(f"No se pudo conectar con ListenBrainz: {exc}", True)


def listenbrainz_submit_playing_now(token: str, artist: str, title: str,
                                     album: str = "") -> str | None:
    metadata = {"artist_name": artist, "track_name": title}
    if album:
        metadata["release_name"] = album
    return _listenbrainz_submit(token, "playing_now", [{"track_metadata": metadata}])


def listenbrainz_submit_listen(token: str, artist: str, title: str, listened_at: int,
                                album: str = "", duration_seconds: int = 0) -> str | None:
    metadata = {"artist_name": artist, "track_name": title}
    if album:
        metadata["release_name"] = album
    if duration_seconds > 0:
        metadata["additional_info"] = {"duration": duration_seconds}
    payload = [{"listened_at": listened_at, "track_metadata": metadata}]
    return _listenbrainz_submit(token, "single", payload)


# ======================== Cola sin conexión ================================

# Last.fm ignora los scrobbles con más de 14 días; ListenBrainz los acepta, pero
# una cola sin límite no tiene sentido. Lo más viejo se descarta primero.
QUEUE_MAX_ENTRIES = 2000
LASTFM_MAX_AGE_S = 14 * 24 * 3600
QUEUE_FILENAME = "scrobbles_pendientes.json"


class ScrobbleQueue:
    """Scrobbles que no se pudieron enviar (sin internet, servidor caído...).
    Se guardan en la carpeta de datos y se reenvían en orden más tarde.
    Segura entre hilos: el envío corre en hilos de fondo."""

    def __init__(self, path=None):
        self._path = path
        self._lock = threading.RLock()
        self._items: list[dict] | None = None   # se carga la primera vez que hace falta

    def path(self):
        if self._path is None:
            from config import _config_dir
            self._path = _config_dir() / QUEUE_FILENAME
        return self._path

    def _load(self) -> list[dict]:
        if self._items is None:
            items = []
            with contextlib.suppress(OSError, ValueError, TypeError):
                raw = json.loads(self.path().read_text(encoding="utf-8"))
                items = [it for it in raw if isinstance(it, dict) and it.get("service") in ("LASTFM", "LISTENBRAINZ")
                         and it.get("artist") and it.get("title") and isinstance(it.get("ts"), int)]
            self._items = items
        return self._items

    def _save(self) -> None:
        with soft("scrobbling.ScrobbleQueue._save"):
            path = self.path()
            items = self._items or []
            if not items:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            from config import _replace_with_retry
            _replace_with_retry(tmp, path)

    def add(self, service: str, artist: str, title: str, album: str, duration_seconds: int, ts: int) -> None:
        with self._lock:
            items = self._load()
            items.append({"service": service, "artist": artist, "title": title, "album": album or "",
                          "duration": int(duration_seconds or 0), "ts": int(ts)})
            del items[:-QUEUE_MAX_ENTRIES]
            self._save()

    def __len__(self) -> int:
        with self._lock:
            return len(self._load())

    def items(self) -> list[dict]:
        with self._lock:
            return list(self._load())

    def flush(self, send, now: float | None = None) -> tuple[int, int]:
        """Reenvía en orden con `send(item) -> SendError | None`. Se detiene en el
        primer error reintentable (sigue sin conexión: no tiene sentido seguir);
        lo que falla sin remedio, o es demasiado viejo para Last.fm, se descarta.
        Devuelve (enviados, descartados)."""
        now = time.time() if now is None else now
        sent = dropped = 0
        with self._lock:
            pending = list(self._load())
        keep_from = len(pending)
        for i, item in enumerate(pending):
            if item["service"] == "LASTFM" and now - item["ts"] > LASTFM_MAX_AGE_S:
                dropped += 1
                continue
            error = send(item)
            if error is None:
                sent += 1
            elif getattr(error, "retryable", False):
                keep_from = i
                break
            else:
                dropped += 1
        with self._lock:
            items = self._load()
            done = pending[:keep_from]
            # Quita lo procesado sin pisar lo que se haya añadido mientras tanto.
            for it in done:
                with contextlib.suppress(ValueError):
                    items.remove(it)
            self._save()
        return sent, dropped


# ============================ Orquestador Qt ================================

class ScrobbleManager(QObject):
    """Escucha cambios de canción (llamar a `track_changed` desde
    app_controller, en el mismo lugar donde ya se agrega al historial) y el
    estado de reproducción (`set_playing`), y hace el resto sola: notifica
    "ahora suena" enseguida y envía el scrobble cuando la canción lleva
    ESCUCHADA (sin contar pausas) la mitad de su duración o 4 minutos.

    Si no hay conexión, el scrobble va a una cola en disco (`ScrobbleQueue`)
    que se reenvía sola: tras cada envío bueno, al arrancar y cada pocos
    minutos mientras quede algo. Nunca bloquea la interfaz — la red vive en
    un ThreadPoolExecutor chico; los errores solo se registran."""

    # Se emite desde los hilos de envío; al estar conectada, PyQt la entrega en
    # el hilo de la interfaz (los QTimer solo se pueden tocar allí).
    _queueChanged = pyqtSignal()

    RETRY_INTERVAL_MS = 5 * 60 * 1000
    STARTUP_FLUSH_DELAY_MS = 15_000

    def __init__(self, config_provider, parent=None, queue: ScrobbleQueue | None = None):
        super().__init__(parent)
        # config_provider: función sin argumentos que devuelve el
        # AppConfig ACTUAL (no una copia vieja) — así, si el usuario
        # cambia de servicio o credenciales a mitad de una canción, el
        # scrobble programado usa los datos nuevos al dispararse, no los
        # que había al arrancar la canción.
        self._config_provider = config_provider
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scrobble")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_scrobble)
        self._pending = None  # (artist, title, album, duration_seconds, started_at)
        # Tiempo escuchado de la canción pendiente: lo acumulado en tramos
        # anteriores + el tramo actual (si está sonando, desde _play_since).
        self._threshold_s = 0.0
        self._listened_s = 0.0
        self._play_since: float | None = None
        self._playing = True      # hasta saber otra cosa (la canción suele llegar ya sonando)
        self.queue = queue if queue is not None else ScrobbleQueue()
        self._flush_lock = threading.Lock()
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(self.RETRY_INTERVAL_MS)
        self._retry_timer.timeout.connect(self.flush_queue)
        self._queueChanged.connect(self._sync_retry_timer)
        QTimer.singleShot(self.STARTUP_FLUSH_DELAY_MS, self.flush_queue)

    # ---------------------------------------------------------------- canción
    def track_changed(self, artist: str, title: str, album: str, duration_seconds: int):
        self._cancel()
        cfg = self._config_provider()
        if cfg.scrobble_service == "NONE" or not artist or not title:
            return

        self._pool.submit(self._safe, self._send_now_playing, cfg, artist, title, album, duration_seconds)

        if duration_seconds < MIN_TRACK_SECONDS_TO_SCROBBLE:
            return  # muy corta, ninguno de los dos servicios la contaría igual
        self._threshold_s = min(duration_seconds / 2, MAX_WAIT_SECONDS)
        self._pending = (artist, title, album, duration_seconds, int(time.time()))
        self._listened_s = 0.0
        self._play_since = time.monotonic() if self._playing else None
        self._arm()

    def set_playing(self, playing: bool):
        """Lo llama app_controller con cada estado. Una pausa congela la cuenta:
        antes el scrobble se programaba por reloj y una canción pausada media
        hora contaba como escuchada."""
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        if self._pending is None:
            return
        now = time.monotonic()
        if playing:
            self._play_since = now
        else:
            if self._play_since is not None:
                self._listened_s += now - self._play_since
            self._play_since = None
        self._arm()

    def listened_seconds(self) -> float:
        extra = (time.monotonic() - self._play_since) if self._play_since is not None else 0.0
        return self._listened_s + extra

    def _arm(self):
        self._timer.stop()
        if self._pending is None or self._play_since is None:
            return
        remaining = max(0.0, self._threshold_s - self.listened_seconds())
        self._timer.start(int(remaining * 1000))

    def _cancel(self):
        self._timer.stop()
        self._pending = None
        self._listened_s = 0.0
        self._play_since = None

    def stop_pending(self):
        """Llamado si la canción se detiene antes de llegar al scrobble —
        Last.fm/ListenBrainz solo cuentan una canción que efectivamente se
        escuchó, no una que se cortó a los pocos segundos."""
        self._cancel()

    def _do_scrobble(self):
        if self._pending is None:
            return
        if self.listened_seconds() + 0.5 < self._threshold_s:   # el temporizador se adelantó
            self._arm()
            return
        artist, title, album, duration_seconds, started_at = self._pending
        self._cancel()
        cfg = self._config_provider()
        if cfg.scrobble_service == "NONE":
            return
        self._pool.submit(
            self._safe, self._send_scrobble, cfg, artist, title, album, duration_seconds, started_at
        )

    # ------------------------------------------------------------------ envío
    def _send_now_playing(self, cfg, artist, title, album, duration_seconds):
        if cfg.scrobble_service == "LASTFM":
            if not cfg.lastfm_session_key:
                return
            lastfm_update_now_playing(
                cfg.lastfm_api_key, cfg.lastfm_api_secret, cfg.lastfm_session_key,
                artist, title, album, duration_seconds,
            )
        elif cfg.scrobble_service == "LISTENBRAINZ":
            if not cfg.listenbrainz_token:
                return
            listenbrainz_submit_playing_now(cfg.listenbrainz_token, artist, title, album)

    @staticmethod
    def _send_item(cfg, item: dict):
        """Envía un scrobble (de la cola o recién escuchado). None = enviado;
        SendError = falló; también SendError (no reintentable) si ya no hay
        credenciales para ese servicio."""
        service = item["service"]
        if service == "LASTFM":
            if not cfg.lastfm_session_key:
                return SendError("Last.fm sin conectar", retryable=True)   # se conserva por si reconecta
            return lastfm_scrobble(
                cfg.lastfm_api_key, cfg.lastfm_api_secret, cfg.lastfm_session_key,
                item["artist"], item["title"], item["ts"], item.get("album", ""), item.get("duration", 0),
            )
        if service == "LISTENBRAINZ":
            if not cfg.listenbrainz_token:
                return SendError("ListenBrainz sin conectar", retryable=True)
            return listenbrainz_submit_listen(
                cfg.listenbrainz_token, item["artist"], item["title"], item["ts"],
                item.get("album", ""), item.get("duration", 0),
            )
        return SendError(f"servicio desconocido: {service}")

    def _send_scrobble(self, cfg, artist, title, album, duration_seconds, started_at):
        service = cfg.scrobble_service
        if service not in ("LASTFM", "LISTENBRAINZ"):
            return
        if service == "LASTFM" and not cfg.lastfm_session_key:
            return
        if service == "LISTENBRAINZ" and not cfg.listenbrainz_token:
            return
        item = {"service": service, "artist": artist, "title": title, "album": album or "",
                "duration": int(duration_seconds or 0), "ts": int(started_at)}
        # Si ya hay cola, este va detrás (Last.fm/ListenBrainz no exigen orden,
        # pero así el historial del servicio queda en el orden real).
        if len(self.queue) > 0:
            self.queue.add(service, artist, title, album, duration_seconds, started_at)
            self._flush_now(cfg)
            return
        error = self._send_item(cfg, item)
        if error is not None and getattr(error, "retryable", False):
            self.queue.add(service, artist, title, album, duration_seconds, started_at)
            self._ensure_retry_timer()
        elif error is None and len(self.queue) > 0:
            self._flush_now(cfg)

    def _flush_now(self, cfg):
        """Reenvía la cola (en el hilo que llama: ya es un hilo de fondo)."""
        if not self._flush_lock.acquire(blocking=False):
            return          # ya hay otro reenvío en marcha
        try:
            if cfg.scrobble_service == "NONE":
                return      # scrobbling apagado: se respeta, la cola se conserva
            self.queue.flush(lambda item: self._send_item(cfg, item))
        finally:
            self._flush_lock.release()
            self._ensure_retry_timer()

    def flush_queue(self):
        """Reenvío desde la interfaz (temporizador, arranque): en segundo plano."""
        if len(self.queue) == 0:
            self._retry_timer.stop()
            return
        cfg = self._config_provider()
        self._pool.submit(self._safe, self._flush_now, cfg)

    def _ensure_retry_timer(self):
        # Puede llamarse desde un hilo de fondo: el temporizador se ajusta en el
        # hilo de la interfaz a través de la señal.
        self._queueChanged.emit()

    def _sync_retry_timer(self):
        if len(self.queue) > 0:
            if not self._retry_timer.isActive():
                self._retry_timer.start()
        else:
            self._retry_timer.stop()

    def pending_count(self) -> int:
        return len(self.queue)

    @staticmethod
    def _safe(fn, *args):
        with soft("scrobbling.ScrobbleManager._safe"):  # ver docstring del módulo: un scrobble fallido nunca debe tumbar nada
            fn(*args)
