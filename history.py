"""
Historial local de reproducción: guarda las últimas canciones reproducidas
(título, artista, reproductor, cuándo) en un archivo aparte de la
configuración principal, para no mezclar datos que crecen sin límite claro
con la configuración (que es pequeña y de tamaño fijo).
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import ad_filter
import ad_log
from config import _config_dir, _replace_with_retry
from diag import soft

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
        with soft("history._load_checked"):
            backup = path.with_name(path.name + ".corrupt")
            if not backup.exists():
                backup.write_text(text, encoding="utf-8")
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
    with soft("history.purge_ads_from_history"):
        path = _history_path()
        bak = path.with_suffix(".json.bak")
        if path.exists() and not bak.exists():
            bak.write_bytes(path.read_bytes())
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
    with soft("history._save"):
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(entries[-MAX_ENTRIES:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _replace_with_retry(tmp_path, path)   # reintenta si el antivirus lo tiene abierto un instante


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
    before = list(entries)
    played_at = datetime.datetime.now().isoformat(timespec="seconds")
    entries.append({
        "title": title,
        "artist": artist,
        "player_name": player_name,
        "played_at": played_at,
        "duration_seconds": duration_seconds,
    })
    entries = entries[-MAX_ENTRIES:]
    _save(entries)
    # Estadísticas acumuladas (sin el límite de 300): ver stats_store.py.
    with soft("history.add_entry.stats_store"):
        import stats_store
        stats_store.record(title, artist, duration_seconds, played_at, history_before=before)
    return entries


def clear() -> None:
    """Borra el historial y, con él, las estadísticas acumuladas (quien borra
    lo que escuchó espera que se olvide también en Estadísticas)."""
    _save([])
    with soft("history.clear.stats_store"):
        import stats_store
        stats_store.clear()


CSV_COLUMNS = ("fecha", "titulo", "artista", "reproductor", "duracion_segundos")


def export_csv(path, entries: list[dict] | None = None) -> int:
    """Guarda el historial en un CSV (UTF-8 con BOM, para que Excel muestre bien
    los acentos). Devuelve cuántas filas escribió. Lanza OSError si no se puede
    escribir (quien llama lo muestra al usuario)."""
    import csv
    rows = load() if entries is None else entries
    count = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")    # ; = lo que espera Excel en español
        writer.writerow(CSV_COLUMNS)
        for e in rows:
            writer.writerow([
                str(e.get("played_at") or ""),
                ad_log._safe_cell(str(e.get("title") or "")),    # mismo escape de fórmulas que anuncios.csv
                ad_log._safe_cell(str(e.get("artist") or "")),
                ad_log._safe_cell(str(e.get("player_name") or "")),
                str(e.get("duration_seconds") or 0),
            ])
            count += 1
    return count


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
