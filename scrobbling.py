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

import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer

_TIMEOUT_SECONDS = 8
_LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"
_LISTENBRAINZ_SUBMIT_URL = "https://api.listenbrainz.org/1/submit-listens"

# Reglas de scrobbling estándar (las mismas que usa Last.fm y que
# ListenBrainz adoptó igual, para no reinventar nada): no vale la pena
# contar canciones muy cortas, y no hace falta esperar más de 4 minutos
# aunque la canción sea muy larga.
MIN_TRACK_SECONDS_TO_SCROBBLE = 30
MAX_WAIT_SECONDS = 240


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
        headers={"User-Agent": "WNP-Player", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            return None, data.get("message", f"Error HTTP {exc.code}")
        except Exception:
            return None, f"Error HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 — red, timeout, JSON inválido, lo que sea
        return None, f"No se pudo conectar con Last.fm: {exc}"

    if isinstance(data, dict) and "error" in data:
        return None, str(data.get("message") or f"Error {data['error']}")
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
            "User-Agent": "WNP-Player",
            "Content-Type": "application/json",
            "Authorization": f"Token {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            resp.read()
        return None
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            return str(data.get("error") or f"Error HTTP {exc.code}")
        except Exception:
            return f"Error HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return f"No se pudo conectar con ListenBrainz: {exc}"


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


# ============================ Orquestador Qt ================================

class ScrobbleManager(QObject):
    """Escucha cambios de canción (llamar a `track_changed` desde
    app_controller, en el mismo lugar donde ya se agrega al historial) y
    hace el resto sola: notifica "ahora suena" enseguida y programa el
    scrobble real para cuando corresponda. Nunca bloquea la interfaz — el
    trabajo de red vive en un ThreadPoolExecutor chico; los errores solo
    se registran (no interrumpen al usuario con diálogos por un scrobble
    que falló)."""

    def __init__(self, config_provider, parent=None):
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

    def track_changed(self, artist: str, title: str, album: str, duration_seconds: int):
        self._timer.stop()
        self._pending = None
        cfg = self._config_provider()
        if cfg.scrobble_service == "NONE" or not artist or not title:
            return

        self._pool.submit(self._safe, self._send_now_playing, cfg, artist, title, album, duration_seconds)

        if duration_seconds < MIN_TRACK_SECONDS_TO_SCROBBLE:
            return  # muy corta, ninguno de los dos servicios la contaría igual
        wait_seconds = min(duration_seconds / 2, MAX_WAIT_SECONDS)
        self._pending = (artist, title, album, duration_seconds, int(time.time()))
        self._timer.start(int(wait_seconds * 1000))

    def stop_pending(self):
        """Llamado si la canción se detiene/pausa antes de llegar al
        scrobble programado — Last.fm/ListenBrainz solo cuentan una
        canción que efectivamente se escuchó, no una que se cortó a los
        pocos segundos."""
        self._timer.stop()
        self._pending = None

    def _do_scrobble(self):
        if self._pending is None:
            return
        artist, title, album, duration_seconds, started_at = self._pending
        self._pending = None
        cfg = self._config_provider()
        if cfg.scrobble_service == "NONE":
            return
        self._pool.submit(
            self._safe, self._send_scrobble, cfg, artist, title, album, duration_seconds, started_at
        )

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

    def _send_scrobble(self, cfg, artist, title, album, duration_seconds, started_at):
        if cfg.scrobble_service == "LASTFM":
            if not cfg.lastfm_session_key:
                return
            lastfm_scrobble(
                cfg.lastfm_api_key, cfg.lastfm_api_secret, cfg.lastfm_session_key,
                artist, title, started_at, album, duration_seconds,
            )
        elif cfg.scrobble_service == "LISTENBRAINZ":
            if not cfg.listenbrainz_token:
                return
            listenbrainz_submit_listen(
                cfg.listenbrainz_token, artist, title, started_at, album, duration_seconds
            )

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except Exception:
            pass  # ver docstring del módulo: un scrobble fallido nunca debe tumbar nada
