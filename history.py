"""
Historial local de reproducción: guarda las últimas canciones reproducidas
(título, artista, reproductor, cuándo) en un archivo aparte de la
configuración principal, para no mezclar datos que crecen sin límite claro
con la configuración (que es pequeña y de tamaño fijo).
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import ad_filter
import ad_log
from config import _config_dir

HISTORY_FILENAME = "history.json"
MAX_ENTRIES = 300


def _history_path() -> Path:
    return _config_dir() / HISTORY_FILENAME


def _load_checked() -> list[dict] | None:
    """Como _load_raw pero distingue "no se pudo leer" (None) de "vacío" ([]).

    - Archivo inexistente → [].
    - Error de E/S transitorio (antivirus, OneDrive, archivo bloqueado) → None:
      quien vaya a ESCRIBIR no debe hacerlo, o pisaría todo el historial con
      una lista casi vacía.
    - JSON corrupto → se conserva una copia en history.json.corrupt (una sola
      vez) y se devuelve [] para poder empezar de nuevo."""
    try:
        path = _history_path()
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    except Exception:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        try:
            backup = path.with_name(path.name + ".corrupt")
            if not backup.exists():
                backup.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return []
    return data if isinstance(data, list) else []


def _load_raw() -> list[dict]:
    """El archivo tal cual está, SIN filtrar. Solo para la migración."""
    return _load_checked() or []


def _entry_ad_reason(entry) -> str | None:
    if not isinstance(entry, dict):
        return None
    return ad_filter.detect(entry.get("title"), entry.get("artist"), entry.get("player_name"))


def load() -> list[dict]:
    """Nunca falla: si el archivo no existe o está corrupto, devuelve una
    lista vacía en vez de tumbar la app.

    Nunca devuelve anuncios: aunque el archivo todavía los tenga (p. ej. antes
    de la migración), historial, estadísticas y "recién sonaron" quedan limpios."""
    return [e for e in _load_raw() if _entry_ad_reason(e) is None]


def purge_ads_from_history() -> int:
    """Migración: mueve al registro de anuncios (ad_log) los que ya estaban en
    el historial y deja el historial sin ellos. Devuelve cuántos movió.

    - Idempotente: una segunda llamada no encuentra nada que mover.
    - Antes de tocar nada hace UNA copia de seguridad (history.json.bak; no se
      sobreescribe si ya existe).
    - Primero escribe el registro y después el historial: si algo falla en
      medio, lo peor es repetir filas en el registro, nunca perder datos."""
    raw = _load_raw()
    ads, clean = [], []
    for e in raw:
        reason = _entry_ad_reason(e)
        (ads if reason else clean).append((e, reason) if reason else e)
    if not ads:
        return 0
    try:
        path = _history_path()
        bak = path.with_suffix(".json.bak")
        if path.exists() and not bak.exists():
            bak.write_bytes(path.read_bytes())
    except Exception:
        pass
    rows = [ad_log._row(e.get("title"), e.get("artist"), e.get("player_name"),
                        e.get("duration_seconds"), f"migrado:{reason}", e.get("played_at"))
            for e, reason in ads]
    if not ad_log.add_entries(rows):
        return 0          # no se pudo guardar el registro: no se toca el historial
    _save(clean)
    return len(ads)


def _save(entries: list[dict]) -> None:
    """Escritura atómica (ver el mismo comentario en config.py:save) — acá
    el riesgo es peor porque se guarda en CADA canción nueva detectada,
    no solo cada 20s."""
    try:
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(entries[-MAX_ENTRIES:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except Exception:
        pass


def add_entry(title: str, artist: str, player_name: str = "", duration_seconds: int = 0) -> list[dict]:
    """Agrega una entrada al historial (evitando duplicar la misma canción
    dos veces seguidas, por ejemplo si el sondeo detecta el mismo título
    más de una vez) y lo guarda. Retorna la lista completa actualizada."""
    # str(x or "") en vez de asumir que title/artist ya vienen como texto:
    # si alguna vez llega None desde el backend, se guarda como "" en vez
    # de None — un None guardado hacía explotar el filtro de búsqueda del
    # historial más adelante (.lower() sobre None).
    title = str(title or "")
    artist = str(artist or "")
    player_name = str(player_name or "")
    try:
        duration_seconds = max(0, int(duration_seconds or 0))
    except (TypeError, ValueError):
        duration_seconds = 0
    # Red de seguridad: un anuncio NUNCA entra al historial, venga de donde
    # venga la llamada; va al registro aparte.
    reason = ad_filter.detect(title, artist, player_name)
    if reason:
        ad_log.add_entry(title, artist, player_name, duration_seconds, reason)
        return load()
    raw = _load_checked()
    if raw is None:
        # No se pudo leer el historial (archivo bloqueado un instante): NO se
        # escribe nada para no pisar lo que hay. Esta canción no se registra.
        return []
    entries = [e for e in raw if _entry_ad_reason(e) is None]
    if entries and entries[-1].get("title") == title and entries[-1].get("artist") == artist:
        return entries
    entries.append({
        "title": title,
        "artist": artist,
        "player_name": player_name,
        "played_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "duration_seconds": duration_seconds,
    })
    entries = entries[-MAX_ENTRIES:]
    _save(entries)
    return entries


def clear() -> None:
    _save([])


def format_relative_time(iso_string: str) -> str:
    """Convierte un timestamp ISO en algo legible tipo 'hace 5 min', 'ayer'
    o una fecha corta si ya pasó más de una semana."""
    try:
        dt = datetime.datetime.fromisoformat(iso_string)
    except Exception:
        return ""
    delta = datetime.datetime.now() - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "hace un momento"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"hace {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"hace {hours} h"
    if delta.days == 1:
        return "ayer"
    if delta.days < 7:
        return f"hace {delta.days} días"
    return dt.strftime("%d/%m/%Y")
