"""
Construye una URL de búsqueda razonable para "ir a la canción" al hacer
clic en la carátula o el título.

El protocolo WebNowPlaying NO expone la URL exacta de la canción/pestaña
(ni para sitios del navegador ni, mucho menos, para apps de escritorio
nativas como Spotify de escritorio) — solo título, artista, álbum,
carátula, duración, etc. Por lo tanto, "volver a la página/canción exacta"
no es algo que podamos hacer con la información disponible.

Lo mejor y más honesto que se puede hacer con lo que sí tenemos (título,
artista y el nombre del reproductor) es abrir una búsqueda directa de esa
canción en la plataforma correspondiente, adivinada a partir de
`player_name`. Casi siempre lleva al resultado correcto en un clic.
"""
from urllib.parse import quote_plus

# nombre (en minúsculas, tal como puede aparecer en player_name) -> plantilla de URL
_SEARCH_TEMPLATES = [
    ("youtube music", "https://music.youtube.com/search?q={q}"),
    ("youtube", "https://www.youtube.com/results?search_query={q}"),
    ("spotify", "https://open.spotify.com/search/{q}"),
    ("soundcloud", "https://soundcloud.com/search?q={q}"),
    ("deezer", "https://www.deezer.com/search/{q}"),
    ("tidal", "https://listen.tidal.com/search?q={q}"),
    ("apple music", "https://music.apple.com/search?term={q}"),
    ("twitch", "https://www.twitch.tv/search?term={q}"),
]

_FALLBACK_TEMPLATE = "https://www.google.com/search?q={q}"


def build_search_url(player_name: str, artist: str, title: str) -> str:
    """Arma la URL de búsqueda a partir del reproductor y la canción actual."""
    query = " ".join(part for part in (artist, title) if part).strip()
    if not query:
        return ""
    q = quote_plus(query)

    name = (player_name or "").lower()
    for key, template in _SEARCH_TEMPLATES:
        if key in name:
            return template.format(q=q)
    return _FALLBACK_TEMPLATE.format(q=q)


def is_youtube_player(player_name: str) -> bool:
    """True para YouTube y YouTube Music (esta última contiene "youtube"
    como subcadena, así que un solo chequeo cubre ambas). Lo usa
    youtube_api.py para decidir si vale la pena consultar la API en vez
    de ir directo a la búsqueda genérica de siempre."""
    return "youtube" in (player_name or "").lower()
