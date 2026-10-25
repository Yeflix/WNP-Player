"""
Abre Spotify o YouTube cuando se pulsa "reproducir" sin ningún reproductor.

- Spotify: la app de escritorio (protocolo `spotify:`, que registran tanto el
  instalador clásico como la versión de la Microsoft Store). Si no está
  instalada, abre open.spotify.com en el navegador.
- YouTube / YouTube Music: la página en el navegador predeterminado. Para que
  el reproductor la vea hace falta la extensión de WebNowPlaying, igual que
  siempre; esto solo abre la página, no elige qué reproducir.

Las funciones públicas devuelven True si se logró abrir algo. `_open_url` y
`_spotify_protocol_registered` están separadas para poder sustituirlas en tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

SPOTIFY_WEB = "https://open.spotify.com"
YOUTUBE_URL = "https://www.youtube.com"
YOUTUBE_MUSIC_URL = "https://music.youtube.com"

# ACTIONS: las opciones del ajuste "al pulsar Reproducir sin reproductor" y de su
# menú. EXTRA_ACTIONS: reproductores web que solo ofrece el selector de la ventana.
ACTIONS = ("spotify", "youtube", "ytmusic")
EXTRA_ACTIONS = ("soundcloud", "deezer", "applemusic", "tidal")
ALL_ACTIONS = ACTIONS + EXTRA_ACTIONS
LABELS = {
    "spotify": "Abrir Spotify",
    "youtube": "Abrir YouTube",
    "ytmusic": "Abrir YouTube Music",
    "soundcloud": "Abrir SoundCloud",
    "deezer": "Abrir Deezer",
    "applemusic": "Abrir Apple Music",
    "tidal": "Abrir TIDAL",
}
# Nombre corto para el selector (el reproductor activo se marca con una casilla).
SHORT_NAMES = {
    "spotify": "Spotify", "youtube": "YouTube", "ytmusic": "YouTube Music",
    "soundcloud": "SoundCloud", "deezer": "Deezer", "applemusic": "Apple Music", "tidal": "TIDAL",
}
WEB_URLS = {
    "soundcloud": "https://soundcloud.com",
    "deezer": "https://www.deezer.com",
    "applemusic": "https://music.apple.com",
    "tidal": "https://listen.tidal.com",
}


def action_for_player_name(player_name: str) -> str | None:
    """Qué acción corresponde a lo que informa pywnp como `player_name`."""
    n = (player_name or "").lower()
    if "spotify" in n:
        return "spotify"
    if "youtube music" in n or "ytmusic" in n:
        return "ytmusic"
    if "youtube" in n:
        return "youtube"
    if "soundcloud" in n:
        return "soundcloud"
    if "deezer" in n:
        return "deezer"
    if "apple" in n:
        return "applemusic"
    if "tidal" in n:
        return "tidal"
    return None


def _open_url(url: str) -> bool:
    return bool(QDesktopServices.openUrl(QUrl(url)))


def _spotify_protocol_registered() -> bool:
    """En Windows: ¿hay un programa asociado a `spotify:`? Sin esto,
    ShellExecute muestra el diálogo "¿Con qué aplicación abrir este enlace?"
    cuando Spotify de escritorio no está instalado. En otros sistemas se
    asume que sí y se confía en el retorno de openUrl."""
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "spotify"):
            return True
    except OSError:
        return False


def _spotify_exe() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    exe = Path(appdata) / "Spotify" / "Spotify.exe"
    return exe if exe.exists() else None


def launch_spotify() -> bool:
    if _spotify_protocol_registered() and _open_url("spotify:"):
        return True
    exe = _spotify_exe()
    if exe is not None:
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([str(exe)], creationflags=flags, close_fds=True)
            return True
        except OSError:
            pass
    return _open_url(SPOTIFY_WEB)


def launch_youtube(music: bool = False) -> bool:
    return _open_url(YOUTUBE_MUSIC_URL if music else YOUTUBE_URL)


def launch(action: str) -> bool:
    """`action`: cualquiera de ALL_ACTIONS. Otro valor → False."""
    if action == "spotify":
        return launch_spotify()
    if action == "youtube":
        return launch_youtube(False)
    if action == "ytmusic":
        return launch_youtube(True)
    if action in WEB_URLS:
        return _open_url(WEB_URLS[action])
    return False
