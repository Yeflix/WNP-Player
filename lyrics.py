"""
Busca la letra de la canción actual en lrclib.net — una API pública y
gratuita para letras de canciones, sin necesidad de cuenta ni API key.
Se cachea en memoria por (artista, título) para no repetir la búsqueda si
se vuelve a abrir el panel de letras mientras suena la misma canción.

Por qué a veces fallaba y qué se hace ahora:
- Los títulos de YouTube traen ruido ("(Official Video)", "[HD]", "Artista - Topic",
  "Artista - Canción"…) y lrclib busca por nombre casi exacto: se limpian y se
  prueban varias variantes (`query_candidates`).
- La búsqueda difusa tomaba el PRIMER resultado sin comprobar que fuera la
  canción: ahora se puntúan por parecido de título/artista y cercanía de
  duración (`_best_entry`) y se descarta lo que no se parece.
- Un fallo de red puntual se reintentaba solo al volver a abrir el panel: ahora
  se reintenta una vez automáticamente, y el panel tiene botón de recarga
  (`request(..., force=True)` se salta la caché, incluida la de "no encontrada").

Dos endpoints, con respaldo:
- `/api/get`: coincidencia EXACTA. Según la documentación oficial (y la
  librería oficial en Python), todos sus parámetros son obligatorios
  (título, artista, álbum Y duración) — si falta alguno o la duración no
  coincide al segundo con lo que tiene registrado lrclib, responde "no
  encontrado" aunque la canción sí esté en su base de datos. `pywnp` no
  siempre entrega álbum, y la duración puede venir imprecisa según la
  fuente, así que depender solo de este endpoint deja muchos falsos
  negativos.
- `/api/search`: búsqueda difusa por título/artista, sin exigir
  coincidencia exacta de álbum ni duración. Se usa como respaldo cuando
  `/api/get` no encuentra nada.

También se distingue un error real (sin conexión, tiempo agotado, servidor
caído) de un "no encontrada" genuino, para poder avisar cuál de los dos
pasó en vez de mostrar siempre el mismo mensaje ambiguo.

La búsqueda corre en un hilo aparte (QThreadPool) para no bloquear la
interfaz mientras se espera la respuesta de la red — mismo patrón que
`cover_loader.py`.
"""
from __future__ import annotations

import difflib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

_GET_URL = "https://lrclib.net/api/get"
_SEARCH_URL = "https://lrclib.net/api/search"
_TIMEOUT_SECONDS = 8
_HEADERS = {"User-Agent": "WNP-Player/1.0 (+https://lrclib.net)"}

_LRC_TIME_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_synced_lyrics(text: str) -> list[tuple[float, str]]:
    """Convierte el formato LRC ('[mm:ss.xx]texto por línea') en una lista
    de (segundos, texto) ordenada por tiempo. Ignora líneas sin marca de
    tiempo (metadatos como [ar:], [ti:], etc)."""
    lines = []
    for raw_line in text.splitlines():
        matches = list(_LRC_TIME_RE.finditer(raw_line))
        if not matches:
            continue
        content = _LRC_TIME_RE.sub("", raw_line).strip()
        for m in matches:
            minutes = int(m.group(1))
            seconds = float(m.group(2))
            lines.append((minutes * 60 + seconds, content))
    lines.sort(key=lambda pair: pair[0])
    return lines


# ---------------------------------------------------------------- limpieza
_NOISE_WORDS = (r"official|oficial|video|vídeo|videoclip|audio|lyrics?|letra|visuali[sz]er|"
                r"remaster(?:ed)?|hd|hq|4k|mv|m/v|clip|live|en vivo|explicit|subtitulad[oa]|"
                r"karaoke|full album|ost|soundtrack")
_BRACKET_NOISE_RE = re.compile(
    r"\s*[\(\[\{【][^\)\]\}】]*?\b(?:" + _NOISE_WORDS + r")\b[^\)\]\}】]*?[\)\]\}】]", re.I)
_TRAILING_NOISE_RE = re.compile(
    r"\s*[-–—|:]\s*(?:official\s+)?(?:music\s+)?(?:video|audio|lyric\s*video|lyrics|visuali[sz]er|oficial)\s*$", re.I)
_FEAT_RE = re.compile(r"\s*[\(\[]?\s*\b(?:feat\.?|ft\.?|featuring|con)\b.*$", re.I)
_ARTIST_TITLE_RE = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+)$")


def clean_title(title: str) -> str:
    t = _BRACKET_NOISE_RE.sub("", title or "")
    t = _TRAILING_NOISE_RE.sub("", t)
    t = re.sub(r"''|[\"“”«»]", "", t)     # comillas decorativas: ''Título'', "Título"
    t = re.sub(r"\s+", " ", t).strip(" -–—|'")
    return t


def clean_artist(artist: str) -> str:
    a = re.sub(r"\s*-\s*topic\s*$", "", artist or "", flags=re.I)
    a = re.sub(r"(?<=[a-z0-9])vevo\s*$", "", a, flags=re.I)
    a = re.sub(r"\s+(?:official|oficial)(?:\s+channel)?\s*$", "", a, flags=re.I)
    return a.strip(" -–—|")


def query_candidates(artist: str, title: str) -> list[tuple[str, str]]:
    """Variantes (artista, título) a probar, de la más fiel a la más limpia."""
    out: list[tuple[str, str]] = []

    def add(a: str, t: str):
        a, t = (a or "").strip(), (t or "").strip()
        if t and (a, t) not in out:
            out.append((a, t))

    add(artist, title)
    ca, ct = clean_artist(artist), clean_title(title)
    add(ca, ct)
    m = _ARTIST_TITLE_RE.match(ct)          # "Artista - Canción" dentro del título
    base = m.group(2) if m else ct
    if m:
        add(m.group(1), base)
        add(ca, base)
    no_feat = _FEAT_RE.sub("", base).strip()
    if no_feat and no_feat != base:
        add(m.group(1) if m else ca, no_feat)
    return out


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:                # "Canción" vs "Canción - Remastered"
        return max(0.9, difflib.SequenceMatcher(None, na, nb).ratio())
    return difflib.SequenceMatcher(None, na, nb).ratio()


_MIN_SCORE = 0.6


def _score_entry(entry: dict, artist: str, title: str, duration: int) -> float:
    name = entry.get("trackName") or entry.get("name") or ""
    ts = _sim(name, title)
    a_s = _sim(entry.get("artistName") or "", artist) if artist else 0.5
    d = entry.get("duration")
    if not duration or not isinstance(d, (int, float)) or d <= 0:
        ds = 0.5
    else:
        diff = abs(d - duration)
        if diff > 25:
            return 0.0                      # otra versión/otra canción
        ds = 1.0 if diff <= 3 else max(0.0, 1 - (diff - 3) / 22)
    return 0.55 * ts + 0.20 * a_s + 0.25 * ds


def _best_entry(data, artist: str, title: str, duration: int) -> dict | None:
    """El resultado de la búsqueda que de verdad se parece a la canción."""
    best, best_score = None, 0.0
    for entry in data if isinstance(data, list) else []:
        result = _entry_to_result(entry)
        if result is None or not (result["plain"] or result["synced"] or result["instrumental"]):
            continue
        sc = _score_entry(entry, artist, title, duration)
        if result["synced"]:
            sc += 0.02                      # a igualdad, mejor la sincronizada
        if sc > best_score:
            best, best_score = result, sc
    return best if best_score >= _MIN_SCORE else None


def _cache_key(artist: str, title: str) -> str:
    return f"{artist.strip().lower()}::{title.strip().lower()}"


def _http_get_json(url: str):
    """Hace la petición y devuelve (json, None) en éxito, (None, None) si
    el servidor respondió 'no encontrado' (404 — caso normal, no es un
    error), o (None, mensaje_de_error) si algo realmente falló (sin
    conexión, tiempo agotado, servidor caído, etc)."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None  # "no encontrada", no es un error real
        return None, f"El servidor de letras respondió con un error ({exc.code})."
    except urllib.error.URLError as exc:
        return None, f"No se pudo conectar con el servidor de letras: {exc.reason}"
    except TimeoutError:
        return None, "El servidor de letras tardó demasiado en responder."
    except Exception as exc:  # noqa: BLE001
        return None, f"Error inesperado al buscar la letra: {exc}"


_RETRY_DELAY_S = 1.0


def _http_get_json_retry(url: str):
    """Como _http_get_json pero reintenta UNA vez un fallo transitorio (sin
    conexión puntual, timeout, 5xx). Un 404 no se reintenta: no es un fallo."""
    data, error = _http_get_json(url)
    if error:
        time.sleep(_RETRY_DELAY_S)
        data, error = _http_get_json(url)
    return data, error


def _entry_to_result(entry: dict) -> dict | None:
    if not isinstance(entry, dict):
        return None
    instrumental = bool(entry.get("instrumental"))
    plain = (entry.get("plainLyrics") or "").strip()
    synced_raw = (entry.get("syncedLyrics") or "").strip()
    synced = parse_synced_lyrics(synced_raw) if synced_raw else None
    if not plain and not synced and not instrumental:
        return None
    return {"plain": plain, "synced": synced, "instrumental": instrumental}


def _fetch_get(artist: str, title: str, album: str, duration_seconds: int):
    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration_seconds:
        params["duration"] = str(duration_seconds)
    url = _GET_URL + "?" + urllib.parse.urlencode(params)
    data, error = _http_get_json_retry(url)
    if error:
        return None, error
    return _entry_to_result(data) if data else None, None


def _fetch_search(artist: str, title: str, duration_seconds: int = 0, q: str = ""):
    """Búsqueda difusa. Con `q` es texto libre ("artista canción"); sin él,
    por título/artista. Devuelve solo un resultado que SE PAREZCA a lo pedido."""
    if q:
        params = {"q": q}
    else:
        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist
    url = _SEARCH_URL + "?" + urllib.parse.urlencode(params)
    data, error = _http_get_json_retry(url)
    if error:
        return None, error
    return _best_entry(data, artist, title, duration_seconds), None


def _fetch(artist: str, title: str, album: str = "", duration_seconds: int = 0) -> dict | None:
    """Retorna:
    - {'plain': str, 'synced': list[(seg,texto)]|None, 'instrumental': bool} -> encontrada
    - {'error': str}                         -> falló la consulta de verdad
    - None                                    -> se buscó bien pero no existe
    """
    if not artist or not title:
        return None

    candidates = query_candidates(artist, title)
    first_error = None

    # 1) Coincidencia exacta: la versión original y la limpia.
    for i, (a, t) in enumerate(candidates[:2]):
        result, error = _fetch_get(a, t, album if i == 0 else "", duration_seconds)
        if result is not None:
            return result
        if error:
            first_error = first_error or error
            break                           # sin red no tiene sentido seguir con /get

    # 2) Búsqueda difusa por cada variante, y por texto libre.
    searches = []
    for a, t in candidates[:3]:
        searches.append((a, t, ""))
    ca, ct = candidates[1] if len(candidates) > 1 else candidates[0]
    searches.append((ca, ct, f"{ca} {ct}".strip()))
    if ca:
        searches.append(("", ct, ct))       # solo el título
    seen = set()
    for a, t, q in searches:
        if (a, t, q) in seen:
            continue
        seen.add((a, t, q))
        result, error = _fetch_search(a, t, duration_seconds, q)
        if result is not None:
            return result
        if error:
            return {"error": error}         # ya se reintentó; no insistir con más consultas
    if first_error:
        return {"error": first_error}
    return None  # de verdad no existe en lrclib


class _JobSignals(QObject):
    finished = pyqtSignal(str, object)  # cache_key, dict|None


class _LyricsJob(QRunnable):
    def __init__(self, cache_key, artist, title, album, duration_seconds, signals):
        super().__init__()
        self.cache_key = cache_key
        self.artist = artist
        self.title = title
        self.album = album
        self.duration_seconds = duration_seconds
        self._signals = signals

    def run(self):
        result = _fetch(self.artist, self.title, self.album, self.duration_seconds)
        try:
            self._signals.finished.emit(self.cache_key, result)
        except RuntimeError:
            # El QObject de señales ya fue destruido (la app se está cerrando
            # con una búsqueda en vuelo): no hay a quién avisar, se descarta.
            pass


class LyricsLoader(QObject):
    """Punto único para pedir letras; emite lyricsReady(cache_key, dict|None).
    Solo se cachean resultados reales (encontrada o no encontrada); los
    errores técnicos NO se cachean, para que reabrir el panel reintente en
    vez de repetir el mismo error para siempre."""

    lyricsReady = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._cache: dict[str, dict | None] = {}
        self._pending: set[str] = set()
        self._signals = _JobSignals()
        self._signals.finished.connect(self._on_job_finished)

    def request(self, artist: str, title: str, album: str = "", duration_seconds: int = 0,
                force: bool = False):
        """`force=True` (botón de recarga) ignora la caché —incluido un "no
        encontrada" anterior— y vuelve a consultar."""
        key = _cache_key(artist, title)
        if force:
            self._cache.pop(key, None)
        if key in self._cache:
            self.lyricsReady.emit(key, self._cache[key])
            return
        if key in self._pending:
            return
        self._pending.add(key)
        self._pool.start(_LyricsJob(key, artist, title, album, duration_seconds, self._signals))

    def _on_job_finished(self, key: str, result):
        self._pending.discard(key)
        if not (isinstance(result, dict) and "error" in result):
            self._cache[key] = result
        self.lyricsReady.emit(key, result)
