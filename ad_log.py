"""Registro APARTE de anuncios (Spotify), para estadísticas propias.

Los anuncios no van al historial ni a las estadísticas de la app (ver
ad_filter.py), pero se siguen guardando aquí, en un CSV que se abre directo
con Excel / Hojas de cálculo / pandas:

    played_at,title,artist,player_name,duration_seconds,reason

A diferencia del historial (que conserva solo las últimas 300 entradas), este
archivo NO se recorta: el objetivo es poder contar anuncios a lo largo del
tiempo. Se escribe solo por el final (append), así que un fallo a mitad de
escritura no puede corromper lo ya guardado.
"""
from __future__ import annotations

import csv
import datetime
from pathlib import Path

from config import _config_dir

AD_LOG_FILENAME = "anuncios.csv"
FIELDS = ["played_at", "title", "artist", "player_name", "duration_seconds", "reason"]


def path() -> Path:
    return _config_dir() / AD_LOG_FILENAME


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value) -> str:
    """Los títulos de anuncios vienen de páginas web. Si un texto empieza por
    = + - @ (o tab/CR), Excel/Hojas de cálculo lo interpretan como fórmula
    (inyección CSV). Se antepone un apóstrofo, que las hojas muestran como
    texto normal."""
    text = str(value or "")
    return "'" + text if text.startswith(_FORMULA_START) else text


def _row(title, artist, player_name, duration_seconds, reason, played_at) -> dict:
    try:
        duration_seconds = max(0, int(duration_seconds or 0))
    except (TypeError, ValueError):
        duration_seconds = 0
    return {
        "played_at": played_at or datetime.datetime.now().isoformat(timespec="seconds"),
        "title": _safe_cell(title),
        "artist": _safe_cell(artist),
        "player_name": _safe_cell(player_name),
        "duration_seconds": duration_seconds,
        "reason": _safe_cell(reason),
    }


def add_entries(rows: list[dict]) -> bool:
    """Agrega varias filas ya armadas (ver _row). Devuelve False si no pudo
    escribir (nunca lanza: un fallo aquí no debe afectar a la reproducción)."""
    if not rows:
        return True
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        is_new = (not p.exists()) or p.stat().st_size == 0
        # utf-8-sig solo al crear: el BOM hace que Excel abra bien tildes y ñ.
        with open(p, "a", newline="", encoding="utf-8-sig" if is_new else "utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerows(rows)
        return True
    except Exception:
        return False


def add_entry(title, artist, player_name="", duration_seconds=0, reason="", played_at=None) -> bool:
    return add_entries([_row(title, artist, player_name, duration_seconds, reason, played_at)])


def load() -> list[dict]:
    """Todas las filas del registro (para pruebas y para quien quiera
    procesarlas desde Python). Nunca falla."""
    try:
        p = path()
        if not p.exists():
            return []
        with open(p, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []
