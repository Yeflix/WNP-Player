"""Identidad y versión de YefriPlayer (la leen backend.py, el diálogo Acerca de, los clientes HTTP y los scripts de empaquetado)."""
import os
import sys

APP_NAME = "YefriPlayer"
APP_VERSION = "1.5.6"
AUTHOR = "YefriDev"
# URL pública del repositorio (opcional). Si se rellena, se incluye en el
# User-Agent de las peticiones, como piden APIs como lrclib para identificar apps.
PROJECT_URL = "https://github.com/Yeflix/yefriplayer"


# Qué es (una sola fuente para el Acerca de, la bienvenida, el instalador y el .exe).
# YefriPlayer NO reproduce audio: es un controlador multimedia.
APP_KIND = "Controlador multimedia"
APP_TAGLINE = "Controlador multimedia para Windows"
APP_DESCRIPTION = ("Controlador multimedia para Windows: no reproduce audio, sino que muestra y "
                   "controla lo que ya suena en tu navegador y en las apps de escritorio.")
SUPPORTED_WEB = ("YouTube", "YouTube Music", "Spotify Web", "SoundCloud", "Deezer",
                 "Apple Music", "TIDAL")
SUPPORTED_WEB_NOTE = "y cualquier sitio compatible con la extensión WebNowPlaying"
SUPPORTED_DESKTOP = ("Spotify", "Apple Music", "TIDAL", "Deezer", "Reproductor multimedia de Windows")
SUPPORTED_DESKTOP_NOTE = "y las demás apps que aparecen en los controles multimedia de Windows"


def platforms_text() -> str:
    """Frase con las plataformas compatibles (para textos largos)."""
    return (f"En el navegador: {', '.join(SUPPORTED_WEB)} {SUPPORTED_WEB_NOTE}. "
            f"En el escritorio: {', '.join(SUPPORTED_DESKTOP)} {SUPPORTED_DESKTOP_NOTE}.")


def user_agent() -> str:
    """Cabecera User-Agent honesta: nombre/versión (+ enlace al proyecto si existe)."""
    ua = f"{APP_NAME}/{APP_VERSION}"
    return f"{ua} (+{PROJECT_URL})" if PROJECT_URL else ua


def is_frozen() -> bool:
    """True si el programa corre EMPAQUETADO como ejecutable (PyInstaller o Nuitka)
    y no con `python main.py`.

    PyInstaller marca `sys.frozen`; Nuitka NO lo hace, pero cada módulo compilado
    por Nuitka tiene la variable global `__compiled__`. Se comprueban las dos para
    que «Iniciar con Windows» registre el .exe (y no `pythonw main.py`) con
    cualquiera de los dos empaquetadores."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def executable_path() -> str:
    """Ruta REAL del programa (la que debe registrarse en «Iniciar con Windows»).

    - Código fuente y PyInstaller: `sys.executable`.
    - Nuitka: `sys.executable` NO es fiable. En una prueba con el binario compilado
      apuntaba a `<carpeta>/python3` (un archivo que no existe), y con `--onefile`
      apunta a una copia TEMPORAL que se borra al cerrar. El programa verdadero es
      `sys.argv[0]` (la ruta con la que se lanzó).
    """
    exe = sys.executable
    if "__compiled__" in globals() and sys.argv and sys.argv[0]:
        cand = os.path.abspath(sys.argv[0])
        for path in (cand, cand + ".exe"):
            if os.path.isfile(path):
                return path
    return exe
