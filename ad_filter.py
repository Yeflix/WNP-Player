"""Detección de anuncios de Spotify.

Los anuncios de Spotify llegan al reproductor como si fueran una canción más
(p. ej. título "Escucha música sin anuncios." con artista "Spotify") y
ensuciaban el historial y las estadísticas. Aquí se decide si lo que suena es
un anuncio; qué se hace con él lo decide quien llama (ver app_controller.py).

Reglas (conservadoras: es preferible dejar pasar un anuncio raro que ocultar
una canción de verdad):
  1. El artista es exactamente "Spotify" (cualquier reproductor). Cubre los
     anuncios propios de Spotify, como el del ejemplo anterior.
  2. El reproductor es Spotify, el artista viene vacío (o es "Spotify") y el
     título es uno de los típicos de un anuncio ("Advertisement", "Anuncio",
     "Publicidad"...).
Las comparaciones ignoran mayúsculas, tildes y espacios sobrantes.

Como es una heurística, se puede ampliar SIN tocar el código con un archivo
`ad_rules.json` en la carpeta de datos de la app (la misma de config.json):

    {"artistas": ["Nombre de un anunciante"], "titulos": ["Título de un anuncio"]}

  - "artistas": cualquier pista con ese artista se considera anuncio.
  - "titulos": con Spotify como reproductor, cualquier pista con ese título.
"""
from __future__ import annotations

import json
import unicodedata

from config import _config_dir

RULES_FILENAME = "ad_rules.json"

DEFAULT_AD_ARTISTS = frozenset({"spotify"})
DEFAULT_AD_TITLES = frozenset({
    "advertisement", "advertising", "ad",
    "anuncio", "anuncios", "publicidad",
    "anuncio de spotify", "spotify",
    "publicite", "werbung", "pubblicita", "anuncio publicitario",
})

_extra_cache: tuple[frozenset, frozenset] | None = None


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


def _load_extra() -> tuple[frozenset, frozenset]:
    """(artistas, títulos) extra del archivo del usuario. Nunca falla: si no
    existe o está mal formado, no hay reglas extra."""
    global _extra_cache
    if _extra_cache is not None:
        return _extra_cache
    artists, titles = frozenset(), frozenset()
    try:
        path = _config_dir() / RULES_FILENAME
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                artists = frozenset(_norm(x) for x in data.get("artistas", []) if _norm(x))
                titles = frozenset(_norm(x) for x in data.get("titulos", []) if _norm(x))
    except Exception:
        pass
    _extra_cache = (artists, titles)
    return _extra_cache


def reload_rules() -> None:
    """Vuelve a leer ad_rules.json (para pruebas, o tras editarlo)."""
    global _extra_cache
    _extra_cache = None


def detect(title, artist, player_name="") -> str | None:
    """Motivo por el que es un anuncio ('artista_spotify', 'titulo_anuncio',
    'regla_usuario_artista', 'regla_usuario_titulo') o None si no lo es."""
    t, a, p = _norm(title), _norm(artist), _norm(player_name)
    extra_artists, extra_titles = _load_extra()
    if a and a in DEFAULT_AD_ARTISTS:
        return "artista_spotify"
    if a and a in extra_artists:
        return "regla_usuario_artista"
    is_spotify_player = "spotify" in p
    if is_spotify_player:
        if a in ("", "spotify") and t in DEFAULT_AD_TITLES:
            return "titulo_anuncio"
        if t and t in extra_titles:
            return "regla_usuario_titulo"
    return None


def is_ad(title, artist, player_name="") -> bool:
    return detect(title, artist, player_name) is not None
