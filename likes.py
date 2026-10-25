"""
Botón de "me gusta": consulta y cambia si la canción actual está en tus
favoritas de Spotify, o si le diste "me gusta" al video en YouTube.

Spotify (Web API, tras la migración de febrero de 2026):
  - identifica la canción con GET /me/player/currently-playing (lo que de verdad
    suena en tu cuenta) y, si no coincide, con una búsqueda;
  - GET    /me/library/contains?uris=spotify:track:ID   -> [true|false]
  - PUT    /me/library?uris=spotify:track:ID            (guardar)
  - DELETE /me/library?uris=spotify:track:ID            (quitar)
  Los endpoints antiguos (/me/tracks) solo se usan de respaldo ante un 400/404.
  Hace falta una app propia en developer.spotify.com (su dueño con Premium) y
  añadir http://127.0.0.1:8898/callback como Redirect URI.

YouTube (Data API v3, alcance youtube.force-ssl):
  - el id del video sale de la URL de la miniatura (…/vi/<id>/…), que es lo que
    entrega la extensión; en YouTube Music la carátula no lo trae y no se puede
    identificar el video;
  - GET  /videos/getRating?id=ID                 (1 unidad de cuota)
  - POST /videos/rate?id=ID&rating=like|none     (50 unidades; cuota diaria 10 000)

Todo corre en hilos (QThreadPool); la interfaz solo recibe `LikeInfo`.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

import oauth_pkce
from lyrics import _sim, clean_artist, clean_title

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = ["user-library-read", "user-library-modify", "user-read-currently-playing"]
SPOTIFY_REDIRECT_PORT = 8898

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

_TIMEOUT_S = 10
_VIDEO_ID_RE = re.compile(r"(?:ytimg\.com|youtube\.com)/vi(?:_webp)?/([A-Za-z0-9_-]{11})(?:/|$|\?)")

SERVICE_NAMES = {"spotify": "Spotify", "youtube": "YouTube"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------------- HTTP
def _request(method: str, url: str, token: str = "", timeout: float = _TIMEOUT_S):
    """Devuelve (status, json|None). Lanza ApiError si hay fallo."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if method in ("POST", "PUT", "DELETE"):
        body = b""
        headers["Content-Length"] = "0"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            data = None
            if raw:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except ValueError:
                    data = None
            return resp.status, data
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            err = payload.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or payload.get("message") or ""
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(exc.code, str(detail)) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(0, f"Sin conexión con el servicio ({getattr(exc, 'reason', exc)}).") from exc


def _friendly(service: str, exc: ApiError) -> str:
    name = SERVICE_NAMES.get(service, service)
    if exc.status <= 0:      # 0 = sin conexión, -1 = mensaje propio (no hay error HTTP)
        return exc.message
    if exc.status == 401:
        return f"{name} rechazó la sesión. Vuelve a conectar la cuenta."
    if exc.status == 403:
        if service == "spotify":
            return ("Spotify denegó el acceso (403). Comprueba que tu cuenta esté en «User Management» "
                    "de tu app y que el dueño de la app tenga Premium.")
        return ("YouTube denegó el acceso (403): puede que se agotara la cuota diaria o que falte "
                "activar la YouTube Data API v3 en tu proyecto.")
    if exc.status == 429:
        return f"{name} pide esperar un momento (demasiadas peticiones)."
    return f"{name} respondió con un error ({exc.status}). {exc.message}".strip()


# ------------------------------------------------------------------ tokens
class _Tokens:
    """access_token en memoria; se renueva con el refresh_token guardado."""

    def __init__(self, token_url: str, creds, save_refresh):
        self._token_url = token_url
        self._creds = creds              # () -> (client_id, client_secret, refresh_token)
        self._save_refresh = save_refresh
        self._access = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def access(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._access and time.time() < self._expires_at - 60:
                return self._access
            client_id, secret, refresh = self._creds()
            if not (client_id and refresh):
                raise ApiError(401, "Cuenta no conectada.")
            try:
                tok = oauth_pkce.refresh_access_token(self._token_url, client_id, refresh, secret)
            except oauth_pkce.OAuthError as exc:
                raise ApiError(401, str(exc)) from exc
            self._access = tok["access_token"]
            self._expires_at = time.time() + float(tok.get("expires_in") or 3600)
            new_refresh = tok.get("refresh_token")
            if new_refresh and new_refresh != refresh:
                self._save_refresh(new_refresh)
            return self._access

    def forget(self):
        with self._lock:
            self._access, self._expires_at = "", 0.0


class _Client:
    service = ""

    def __init__(self, tokens: _Tokens):
        self._tokens = tokens

    def _call(self, method: str, url: str):
        try:
            return _request(method, url, self._tokens.access())
        except ApiError as exc:
            if exc.status != 401:
                raise
            return _request(method, url, self._tokens.access(force=True))   # un reintento tras renovar


class SpotifyLikes(_Client):
    service = "spotify"

    def identify(self, snap: dict) -> dict | None:
        title, artist = snap.get("title") or "", snap.get("artist") or ""
        ct, ca = clean_title(title), clean_artist(artist)

        # 1) Lo que suena de verdad en la cuenta, si coincide con lo que muestra la app.
        _status, cur = self._call("GET", f"{SPOTIFY_API}/me/player/currently-playing")
        item = (cur or {}).get("item") if isinstance(cur, dict) else None
        if isinstance(item, dict) and item.get("uri") and item.get("type", "track") == "track":
            if max(_sim(item.get("name", ""), ct), _sim(item.get("name", ""), title)) >= 0.75:
                return {"uri": item["uri"], "id": item.get("id") or item["uri"].split(":")[-1]}

        # 2) Búsqueda.
        q = f"track:{ct} artist:{ca}" if ca else ct
        url = f"{SPOTIFY_API}/search?" + urllib.parse.urlencode({"q": q, "type": "track", "limit": 5})
        _status, data = self._call("GET", url)
        best, best_score = None, 0.0
        dur = snap.get("duration_seconds") or 0
        for it in ((data or {}).get("tracks") or {}).get("items") or []:
            if not isinstance(it, dict) or not it.get("uri"):
                continue
            artists = [a.get("name", "") for a in it.get("artists") or []]
            a_s = max([_sim(a, ca) for a in artists] or [0.0]) if ca else 0.5
            d = (it.get("duration_ms") or 0) / 1000.0
            ds = 0.5 if not (dur and d) else (1.0 if abs(d - dur) <= 3 else max(0.0, 1 - (abs(d - dur) - 3) / 20))
            score = 0.6 * _sim(it.get("name", ""), ct) + 0.25 * a_s + 0.15 * ds
            if score > best_score:
                best, best_score = it, score
        if best is not None and best_score >= 0.7:
            return {"uri": best["uri"], "id": best.get("id") or best["uri"].split(":")[-1]}
        return None

    def is_liked(self, ident: dict) -> bool:
        try:
            _s, data = self._call("GET", f"{SPOTIFY_API}/me/library/contains?" +
                                  urllib.parse.urlencode({"uris": ident["uri"]}))
        except ApiError as exc:
            if exc.status not in (400, 404, 410):
                raise
            _s, data = self._call("GET", f"{SPOTIFY_API}/me/tracks/contains?" +
                                  urllib.parse.urlencode({"ids": ident["id"]}))
        return bool(isinstance(data, list) and data and data[0])

    def set_liked(self, ident: dict, liked: bool):
        method = "PUT" if liked else "DELETE"
        try:
            self._call(method, f"{SPOTIFY_API}/me/library?" + urllib.parse.urlencode({"uris": ident["uri"]}))
        except ApiError as exc:
            if exc.status not in (400, 404, 410):
                raise
            self._call(method, f"{SPOTIFY_API}/me/tracks?" + urllib.parse.urlencode({"ids": ident["id"]}))


class YouTubeLikes(_Client):
    service = "youtube"

    def identify(self, snap: dict) -> dict | None:
        m = _VIDEO_ID_RE.search(snap.get("cover_url") or "")
        return {"id": m.group(1)} if m else None

    def is_liked(self, ident: dict) -> bool:
        _s, data = self._call("GET", f"{YOUTUBE_API}/videos/getRating?" +
                              urllib.parse.urlencode({"id": ident["id"]}))
        items = (data or {}).get("items") or []
        return bool(items) and items[0].get("rating") == "like"

    def set_liked(self, ident: dict, liked: bool):
        self._call("POST", f"{YOUTUBE_API}/videos/rate?" +
                   urllib.parse.urlencode({"id": ident["id"], "rating": "like" if liked else "none"}))


# --------------------------------------------------------------- el gestor
@dataclass(frozen=True)
class LikeInfo:
    service: str | None = None      # None = no aplica (otro reproductor / nada sonando)
    configured: bool = False
    liked: bool | None = None       # None = desconocido
    busy: bool = False
    message: str = ""

    @property
    def visible(self) -> bool:
        return self.service is not None

    @property
    def tooltip(self) -> str:
        if self.service is None:
            return ""
        name = SERVICE_NAMES[self.service]
        if not self.configured:
            return f"Me gusta · conecta tu cuenta de {name}"
        if self.message:
            return self.message
        if self.busy and self.liked is None:
            return "Comprobando…"
        if self.service == "youtube":
            return "Quitar tu «me gusta» del video" if self.liked else "Dar «me gusta» al video"
        return "Quitar de tus canciones que te gustan" if self.liked else "Guardar en tus canciones que te gustan"


class _JobSignals(QObject):
    done = pyqtSignal(int, str, object, str)    # seq, kind, resultado, error


class _Job(QRunnable):
    def __init__(self, seq: int, kind: str, service: str, fn, signals: _JobSignals):
        super().__init__()
        self._seq, self._kind, self._service, self._fn, self._signals = seq, kind, service, fn, signals

    def run(self):
        result, error = None, ""
        try:
            result = self._fn()
        except ApiError as exc:
            error = _friendly(self._service, exc)
        except Exception as exc:  # noqa: BLE001
            error = f"Error inesperado: {exc}"
        try:
            self._signals.done.emit(self._seq, self._kind, result, error)
        except RuntimeError:
            pass    # la app se está cerrando


class LikeManager(QObject):
    changed = pyqtSignal(object)        # LikeInfo
    setupRequested = pyqtSignal(str)    # servicio sin cuenta conectada

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._pool = QThreadPool.globalInstance()
        self._signals = _JobSignals()
        self._signals.done.connect(self._on_done)
        self._seq = 0
        self._snap: dict | None = None
        self._ident: dict | None = None
        self.info = LikeInfo()
        self._clients: dict = {}

    # -- configuración
    def is_configured(self, service: str) -> bool:
        c = self.config
        if service == "spotify":
            return bool(c.spotify_client_id and c.spotify_refresh_token)
        if service == "youtube":
            return bool(c.google_client_id and c.google_refresh_token)
        return False

    def _client(self, service: str):
        if service not in self._clients:
            c = self.config
            if service == "spotify":
                tokens = _Tokens(SPOTIFY_TOKEN_URL, lambda: (c.spotify_client_id, "", c.spotify_refresh_token),
                                 self._save_spotify_refresh)
                self._clients[service] = SpotifyLikes(tokens)
            else:
                tokens = _Tokens(GOOGLE_TOKEN_URL,
                                 lambda: (c.google_client_id, c.google_client_secret, c.google_refresh_token),
                                 self._save_google_refresh)
                self._clients[service] = YouTubeLikes(tokens)
        return self._clients[service]

    def forget_credentials(self):
        """Tras conectar/desconectar una cuenta: descarta clientes y tokens en memoria."""
        self._clients.clear()

    def _save_spotify_refresh(self, token: str):
        self.config.spotify_refresh_token = token
        self.config.save()

    def _save_google_refresh(self, token: str):
        self.config.google_refresh_token = token
        self.config.save()

    @staticmethod
    def service_for(state) -> str | None:
        name = (getattr(state, "player_name", "") or "").lower()
        if "spotify" in name:
            return "spotify"
        if "youtube" in name:
            return "youtube"
        return None

    # -- eventos de la app
    def track_changed(self, state):
        """Llamar cuando cambia la canción (ya estable) o cuando no queda nada."""
        self._seq += 1
        self._ident = None
        self._snap = None
        if (state is None or not getattr(state, "has_media", False)
                or not getattr(self.config, "likes_enabled", True)):
            self._publish(LikeInfo())
            return
        service = self.service_for(state)
        if service is None:
            self._publish(LikeInfo())
            return
        self._snap = {"title": state.title, "artist": state.artist,
                      "duration_seconds": state.duration_seconds,
                      "cover_url": getattr(state, "cover_url", ""), "player_name": state.player_name}
        if not self.is_configured(service):
            self._publish(LikeInfo(service=service, configured=False))
            return
        self._publish(LikeInfo(service=service, configured=True, busy=True))
        snap, seq = self._snap, self._seq

        def work():
            client = self._client(service)
            ident = client.identify(snap)
            if ident is None:
                raise ApiError(-1, _not_identified(service, snap))
            return {"ident": ident, "liked": client.is_liked(ident)}
        self._start(seq, "status", service, work)

    def toggle(self):
        info = self.info
        if info.service is None:
            return
        if not info.configured:
            self.setupRequested.emit(info.service)
            return
        if info.busy or self._snap is None:
            return
        service, snap, ident, seq = info.service, self._snap, self._ident, self._seq
        target = not bool(info.liked)
        self._publish(replace(info, liked=target, busy=True, message=""))
        previous = info

        def work():
            client = self._client(service)
            found = ident or client.identify(snap)
            if found is None:
                raise ApiError(-1, _not_identified(service, snap))
            client.set_liked(found, target)
            return {"ident": found, "liked": target}
        self._start(seq, "set", service, work, previous)

    # -- internos
    def _start(self, seq, kind, service, fn, previous=None):
        self._previous = previous
        self._pool.start(_Job(seq, kind, service, fn, self._signals))

    def _publish(self, info: LikeInfo):
        self.info = info
        self.changed.emit(info)

    def _on_done(self, seq: int, kind: str, result, error: str):
        if seq != self._seq:
            return                      # la canción cambió mientras tanto
        info = self.info
        if error:
            if kind == "set" and self._previous is not None:
                self._publish(replace(self._previous, busy=False, message=error))
            else:
                self._publish(replace(info, busy=False, liked=None, message=error))
            return
        self._ident = result.get("ident")
        self._publish(replace(info, busy=False, liked=bool(result.get("liked")), message=""))


def _not_identified(service: str, snap: dict) -> str:
    if service == "youtube":
        if "music" in (snap.get("player_name") or "").lower():
            return "No se puede identificar el video en YouTube Music (su carátula no incluye el id)."
        return "No pude identificar el video de YouTube a partir de su miniatura."
    return "No encontré esta canción en Spotify."
