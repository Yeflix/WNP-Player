"""
Estadísticas de escucha, calculadas a partir del historial que ya guarda
`history.py` (title, artist, player_name, played_at, duration_seconds).
No hay ningún tracker nuevo corriendo en el backend: todo se deriva del
mismo archivo que ya alimenta al diálogo de Historial, así que estas
funciones son puras (entran entradas, salen números) y fáciles de probar
sin necesitar la app corriendo.

"Veces escuchada" cuenta ENTRADAS del historial, no reproducciones reales:
si la misma canción se repite muchas veces SEGUIDAS (bucle), el propio
`history.add_entry` ya evita duplicar la entrada inmediatamente anterior
(para no ensuciar el historial con ruido del sondeo), así que un bucle
largo de una sola canción cuenta como una sola "vez" acá también. Es una
aproximación consciente, no un bug: privilegia el uso normal (escuchar
cosas distintas) sobre el caso de dejar una sola canción en bucle.
"""
from __future__ import annotations

import datetime
from collections import Counter

WEEK_SECONDS = 7 * 24 * 3600


def _key(entry: dict) -> tuple:
    return (str(entry.get("title") or ""), str(entry.get("artist") or ""))


def _played_at(entry: dict) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(entry.get("played_at") or ""))
    except Exception:
        return None


def entries_since(entries: list[dict], days: int) -> list[dict]:
    """Entradas de los últimos N días (según played_at). Si una entrada no
    tiene fecha válida, se descarta en vez de arriesgar contarla de más."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    result = []
    for e in entries:
        dt = _played_at(e)
        if dt is not None and dt >= cutoff:
            result.append(e)
    return result


def total_seconds(entries: list[dict]) -> int:
    total = 0
    for e in entries:
        try:
            total += max(0, int(e.get("duration_seconds") or 0))
        except (TypeError, ValueError):
            pass
    return total


def format_duration(seconds: int) -> str:
    """'2 h 15 min', '45 min', '3 h' — nunca 'segundos' sueltos, no aporta
    nada a esta escala y hace más ruido que otra cosa."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    if minutes:
        return f"{minutes} min"
    return "menos de 1 min" if seconds > 0 else "0 min"


def play_count(entries: list[dict], title: str, artist: str) -> int:
    target = (str(title or ""), str(artist or ""))
    return sum(1 for e in entries if _key(e) == target)


def top_songs(entries: list[dict], n: int = 5) -> list[tuple[str, str, int]]:
    """[(título, artista, veces)], de más a menos escuchada. Ignora
    entradas sin título (no hay nada útil que mostrar de esas)."""
    counter = Counter(_key(e) for e in entries if str(e.get("title") or "").strip())
    return [(title, artist, count) for (title, artist), count in counter.most_common(n)]


def top_artists(entries: list[dict], n: int = 5) -> list[tuple[str, int]]:
    counter = Counter(str(e.get("artist") or "").strip() for e in entries)
    counter.pop("", None)
    return counter.most_common(n)


def unique_songs_count(entries: list[dict]) -> int:
    return len({_key(e) for e in entries if str(e.get("title") or "").strip()})


def summary(entries: list[dict], days: int | None = None) -> dict:
    """Resumen completo para el panel de estadísticas. days=None = todo
    el historial guardado (hasta 300 canciones); days=7 = solo la última
    semana (lo que usa el recordatorio semanal)."""
    scope = entries_since(entries, days) if days is not None else list(entries)
    top = top_songs(scope, n=5)
    return {
        "plays": len(scope),
        "unique_songs": unique_songs_count(scope),
        "total_seconds": total_seconds(scope),
        "total_duration_text": format_duration(total_seconds(scope)),
        "top_songs": top,
        "top_artists": top_artists(scope, n=5),
        "most_played": top[0] if top else None,  # (título, artista, veces)
    }


def should_show_weekly_recap(last_shown_iso: str) -> bool:
    """True si pasaron 7+ días desde la última vez que se mostró el
    resumen semanal (o si nunca se mostró). No exige que haya datos —eso
    lo decide quien llama, así puede mostrar un mensaje distinto si la
    semana estuvo vacía en vez de directamente no mostrar nada—."""
    if not last_shown_iso:
        return True
    try:
        last = datetime.datetime.fromisoformat(last_shown_iso)
    except Exception:
        return True
    return (datetime.datetime.now() - last).total_seconds() >= WEEK_SECONDS
