"""Estadísticas ACUMULADAS de escucha (sin el límite de 300 del historial).

El historial (`history.py`) guarda solo las últimas 300 canciones; las
estadísticas que se calculaban a partir de él «olvidaban» todo lo anterior.
Aquí se lleva una cuenta aparte, pequeña y que no caduca: por canción
(veces, segundos, última vez) y por artista (veces), más totales.

- Se actualiza desde `history.add_entry` cada vez que entra una canción nueva
  al historial (mismas reglas: sin anuncios, sin duplicar la misma canción
  seguida). Así «veces escuchada» significa lo mismo en los dos sitios.
- La primera vez se siembra con lo que ya haya en el historial, para no
  empezar de cero al actualizar.
- `history.clear()` también la borra: quien borra su historial espera que se
  olvide lo que escuchó.
- Solo biblioteca estándar, sin Qt: funciones fáciles de probar.

Archivo: `estadisticas.json` en la carpeta de datos.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import threading
from pathlib import Path

from diag import soft

FILENAME = "estadisticas.json"
FORMAT_VERSION = 1
# Tope de canciones distintas guardadas. Al pasarlo se descartan primero las
# escuchadas una sola vez y hace más tiempo (no afectan a los tops).
MAX_SONGS = 20_000
_SEP = "\u0001"          # separa título y artista en la clave (no aparece en textos reales)

_lock = threading.RLock()
_path_override: Path | None = None   # para las pruebas


def path() -> Path:
    if _path_override is not None:
        return _path_override
    from config import _config_dir
    return _config_dir() / FILENAME


def _empty() -> dict:
    return {"version": FORMAT_VERSION,
            "since": datetime.datetime.now().isoformat(timespec="seconds"),
            "plays": 0, "seconds": 0, "songs": {}, "artists": {}}


def _valid(data) -> bool:
    return (isinstance(data, dict) and isinstance(data.get("songs"), dict)
            and isinstance(data.get("artists"), dict) and isinstance(data.get("plays"), int)
            and isinstance(data.get("seconds"), int))


def load() -> dict | None:
    """Datos acumulados, o None si todavía no hay (o el archivo no se puede leer)."""
    with _lock:
        try:
            data = json.loads(path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if _valid(data) else None


def _save(data: dict) -> None:
    with soft("stats_store._save"):
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        from config import _replace_with_retry
        _replace_with_retry(tmp, p)


def _add(data: dict, title: str, artist: str, seconds: int, when: str) -> None:
    key = f"{title}{_SEP}{artist}"
    song = data["songs"].get(key)
    if not isinstance(song, list) or len(song) != 3:
        song = [0, 0, ""]
    song[0] += 1
    song[1] += seconds
    song[2] = when or song[2]
    data["songs"][key] = song
    if artist:
        data["artists"][artist] = int(data["artists"].get(artist, 0)) + 1
    data["plays"] += 1
    data["seconds"] += seconds


def _prune(data: dict) -> None:
    songs = data["songs"]
    if len(songs) <= MAX_SONGS:
        return
    # Las de una sola escucha y más antiguas primero.
    order = sorted(songs.items(), key=lambda kv: (kv[1][0], kv[1][2]))
    for key, _ in order[: len(songs) - MAX_SONGS]:
        del songs[key]


def _clean_seconds(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def seed_from(entries: list[dict]) -> dict:
    """Datos nuevos a partir de entradas del historial (la primera vez)."""
    data = _empty()
    dates = [str(e.get("played_at") or "") for e in entries if e.get("played_at")]
    if dates:
        data["since"] = min(dates)
    for e in entries:
        title = str(e.get("title") or "").strip()
        if not title:
            continue
        _add(data, title, str(e.get("artist") or "").strip(),
             _clean_seconds(e.get("duration_seconds")), str(e.get("played_at") or ""))
    return data


def record(title: str, artist: str, duration_seconds: int, played_at: str = "",
           history_before: list[dict] | None = None) -> None:
    """Suma una escucha. `history_before`: el historial SIN esta entrada, para
    sembrar los datos si es la primera vez (si no se pasa, se empieza de cero)."""
    title = str(title or "").strip()
    if not title:
        return
    with _lock:
        data = load()
        if data is None:
            data = seed_from(history_before or [])
        _add(data, title, str(artist or "").strip(), _clean_seconds(duration_seconds),
             played_at or datetime.datetime.now().isoformat(timespec="seconds"))
        _prune(data)
        _save(data)


def clear() -> None:
    with _lock, contextlib.suppress(FileNotFoundError, OSError):
        path().unlink()


def play_count(title: str, artist: str) -> int:
    data = load()
    if data is None:
        return 0
    song = data["songs"].get(f"{title or ''}{_SEP}{artist or ''}")
    return int(song[0]) if isinstance(song, list) and song else 0


def summary(n: int = 5) -> dict | None:
    """Mismo formato que `stats.summary` para «todo el tiempo», o None si aún no
    hay datos acumulados (entonces se usa el historial, como antes)."""
    data = load()
    if data is None or data["plays"] <= 0:
        return None
    from stats import format_duration
    songs = []
    for key, val in data["songs"].items():
        if not (isinstance(val, list) and len(val) == 3):
            continue
        title, _, artist = key.partition(_SEP)
        songs.append((title, artist, int(val[0]), str(val[2])))
    # Más escuchadas; a igualdad, la más reciente primero.
    songs.sort(key=lambda s: (-s[2], _neg_iso(s[3])))
    top = [(t, a, c) for t, a, c, _ in songs[:n]]
    artists = sorted(((str(k), int(v)) for k, v in data["artists"].items() if k),
                     key=lambda kv: -kv[1])[:n]
    return {
        "plays": data["plays"],
        "unique_songs": len(songs),
        "total_seconds": data["seconds"],
        "total_duration_text": format_duration(data["seconds"]),
        "top_songs": top,
        "top_artists": artists,
        "most_played": top[0] if top else None,
        "since": str(data.get("since") or ""),
    }


def _neg_iso(iso: str) -> str:
    # Orden descendente por fecha ISO dentro de un sort ascendente.
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in iso)
