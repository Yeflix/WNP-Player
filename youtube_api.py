"""
Integración con la API de YouTube (ítem #3 de las propuestas pendientes):
con una clave de API configurada (Google Cloud, gratis dentro de la cuota
estándar), tocar la carátula/título de una canción de YouTube o YouTube
Music busca el video exacto y abre ESE link, en vez de la búsqueda
genérica que se arma con `links.build_search_url`.

Sin clave configurada, o para cualquier otra plataforma, o si la consulta
falla por lo que sea (sin resultados, cuota agotada, sin red, timeout):
se cae siempre al comportamiento de siempre (búsqueda genérica), nunca se
deja al usuario sin nada. Por eso `find_video_url` nunca lanza — cualquier
problema simplemente devuelve None.

La consulta a la API es de red y no debe congelar la interfaz: se resuelve
en un hilo de fondo (mismo patrón que cover_loader.py/scrobbling.py) y el
resultado se entrega por señal de Qt.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, pyqtSignal

from links import build_search_url, is_youtube_player

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_TIMEOUT_SECONDS = 5

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="youtube-api")


def find_video_url(api_key: str, artist: str, title: str) -> str | None:
    """Primer resultado de video para "artista - título", como URL directa
    de YouTube, o None ante cualquier problema (nunca lanza)."""
    if not api_key or not title:
        return None
    query = f"{artist} - {title}" if artist else title
    params = {
        "part": "snippet",
        "type": "video",
        "maxResults": "1",
        "q": query,
        "key": api_key,
    }
    url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "WNP-Player"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = data.get("items") or []
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        if not video_id:
            return None
        return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:  # noqa: BLE001 — red, timeout, JSON/forma inesperada, cuota, lo que sea
        return None


class VideoLinkResolver(QObject):
    """Punto único para resolver "a qué link me lleva esto": arma el
    fallback (búsqueda genérica) al instante y, si corresponde, además
    intenta el video exacto en un hilo de fondo. `linkResolved` se emite
    UNA sola vez por pedido, siempre con un link válido (nunca vacío si
    había artista/título) — el llamador solo necesita conectarse a esa
    señal y abrirla con QDesktopServices, sin preocuparse de cuál de los
    dos caminos se tomó."""

    linkResolved = pyqtSignal(str)

    def resolve(self, player_name: str, artist: str, title: str, api_key: str):
        fallback_url = build_search_url(player_name, artist, title)
        if not fallback_url:
            return
        if not (api_key and is_youtube_player(player_name)):
            self.linkResolved.emit(fallback_url)
            return

        def _work():
            exact = find_video_url(api_key, artist, title)
            self.linkResolved.emit(exact or fallback_url)

        _pool.submit(_work)
