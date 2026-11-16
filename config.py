"""
Guarda y recupera la configuración de la app entre sesiones: puerto,
último modo usado (completo/compacto), zoom de cada ventana, posición de
ventana y "siempre visible". Se guarda en un pequeño archivo JSON local,
en la carpeta de configuración estándar del sistema operativo.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import contextlib
import secret_store
from diag import soft

# Puerto por defecto del servidor de WebNowPlaying. Vive aquí (y backend.py lo
# reexporta) para que config.py no importe PyQt6: así la configuración se puede
# leer en el arranque, en la autoprueba y en el instalador sin cargar Qt.
DEFAULT_PORT = 1234

APP_DIR_NAME = "YefriPlayer"
# Carpetas de datos de nombres anteriores del programa (antes se llamaba YefriPlayer).
LEGACY_APP_DIR_NAMES = ("WNPPlayer",)
CONFIG_FILENAME = "config.json"

# Teclas globales por defecto (acción → combinación). Las usan AppConfig y la bienvenida.
DEFAULT_HOTKEYS = {
    "play_pause": "ctrl+shift+space",
    "next": "ctrl+shift+c",
    "previous": "ctrl+shift+x",
}

# Preferencias recomendadas que se aplican en la primera ejecución (la bienvenida
# las muestra marcadas así y se pueden cambiar allí mismo).
RECOMMENDED_PREFS = {
    "start_with_windows": True,
    "start_minimized": False,
    "always_on_top": False,
    "notifications_enabled": True,
    "check_updates": True,
    "taskbar_button": False,
    "audio_visualizer": True,
    "visualizer_per_app": True,
    "hotkeys_enabled": True,
}


def _dir_for(name: str) -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / name


_legacy_checked = False


def _migrate_legacy(target: Path) -> bool:
    """Si es la primera vez con el nombre nuevo y existe la carpeta del nombre
    anterior, COPIA su contenido (configuración, historial, estadísticas...).
    No borra nada: la carpeta vieja queda intacta por si se vuelve a una
    versión anterior. Devuelve True si copió algo."""
    import shutil
    with contextlib.suppress(OSError):
        if target.is_dir() and any(target.iterdir()):
            return False
        for name in LEGACY_APP_DIR_NAMES:
            legacy = _dir_for(name)
            if legacy.is_dir() and any(legacy.iterdir()):
                shutil.copytree(legacy, target, dirs_exist_ok=True)
                return True
    return False


def _config_dir() -> Path:
    global _legacy_checked  # noqa: PLW0603 — estado de módulo a propósito (lo leen otros módulos o las pruebas)
    target = _dir_for(APP_DIR_NAME)
    if not _legacy_checked:
        _legacy_checked = True
        _migrate_legacy(target)
    return target


def _config_path() -> Path:
    return _config_dir() / CONFIG_FILENAME


# Último contenido guardado por ruta: (JSON en claro ordenado, (mtime_ns, tamaño)).
# Solo vive en memoria; sirve para no reescribir config.json si nada cambió.
_LAST_SAVED: dict[str, tuple[str, tuple[int, int] | None]] = {}


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _replace_with_retry(src: Path, dst: Path, attempts: int = 5, delay_s: float = 0.05) -> None:
    """os.replace con reintentos cortos. En Windows, un antivirus, el indexador
    o la sincronización de OneDrive pueden tener config.json abierto un instante
    y el reemplazo falla con PermissionError ("acceso denegado"); unos
    milisegundos después funciona. Si sigue fallando, se propaga el error."""
    import time
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay_s * (i + 1))


@dataclass
class AppConfig:
    port: int = DEFAULT_PORT
    last_mode: str = "main"          # "main" | "mini"
    always_on_top: bool = False

    main_width: int | None = None   # ancho de la ventana completa (define su zoom)
    main_x: int | None = None
    main_y: int | None = None

    mini_scale: float = 1.0
    mini_x: int | None = None
    mini_y: int | None = None

    start_with_windows: bool = True      # iniciar junto con Windows (ver autostart.py)
    # Solo al arrancar con Windows (main.py --inicio-windows): abrirlo a mano siempre
    # muestra la ventana. Antes aplicaba a todo arranque y parecía que no abría.
    start_minimized: bool = False
    audio_visualizer: bool = True        # visualizador que reacciona al audio (ver audio_levels.py)
    # Visualizador: captar solo el audio del reproductor (Spotify, el navegador...)
    # en vez de todo el equipo, si Windows lo permite (ver process_loopback.py).
    visualizer_per_app: bool = True
    # Entrada en la barra de tareas con botones en la miniatura (taskbar_buttons.py).
    # Por defecto no: la app vive en la bandeja. Se aplica al reiniciar.
    taskbar_button: bool = False

    # Buscar versiones nuevas en GitHub (updater.py): una vez al día como mucho.
    check_updates: bool = True
    last_update_check: str = ""          # ISO de la última consulta
    skipped_update_version: str = ""     # versión que el usuario pidió no volver a avisar

    # Teclas globales activadas por defecto (DEFAULT_HOTKEYS).
    hotkeys_enabled: bool = True
    hotkey_play_pause: str = "ctrl+shift+space"   # formato "ctrl+alt+p" (vacío = sin asignar)
    hotkey_next: str = "ctrl+shift+c"
    hotkey_previous: str = "ctrl+shift+x"

    notifications_enabled: bool = True
    # Que hacer al pulsar Reproducir sin ningun reproductor abierto:
    # "ask" (preguntar) | "spotify" | "youtube" | "ytmusic" | "none"
    empty_play_action: str = "ask"
    # Botón "me gusta" (Spotify / YouTube). Las credenciales son de TU app de
    # desarrollador (ver likes.py); el refresh_token se guarda al conectar.
    likes_enabled: bool = True
    spotify_client_id: str = ""
    spotify_refresh_token: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    # Ondas alrededor de la barra del panel lateral mientras suena algo.
    bar_waves_enabled: bool = True

    lyrics_panel_enabled: bool = False   # panel de letra junto a la carátula (reproductor completo)
    lyrics_panel_side: str = "right"     # "left" | "right" — de qué lado sale el panel de letra

    # Se pone en True apenas se completa (o se omite) el asistente de
    # bienvenida la primera vez. Mientras sea False, AppController.start()
    # lo muestra antes de abrir cualquier ventana normal.
    onboarding_completed: bool = False
    # Revisión del asistente que ya vio el usuario: si sale una bienvenida nueva
    # (onboarding.WELCOME_REVISION mayor), se muestra una vez más.
    welcome_revision: int = 0

    # Opacidad de ambas ventanas (0.5-1.0), útil sobre todo con "siempre
    # visible" activado para que estorbe menos al superponerse a otras
    # apps. Se aplica en caliente (no pide reiniciar).
    window_opacity: float = 1.0

    # Accesibilidad. A diferencia de window_opacity, estos dos SÍ piden
    # reiniciar la app para aplicarse — ver theme.apply_accessibility()
    # para el motivo (todo el texto se arma una sola vez, al construir
    # cada widget, no hay recálculo de estilos en caliente).
    font_scale: float = 1.0       # 1.0 normal / 1.15 grande / 1.3 muy grande
    ui_scale: float = 0.0         # escala de TODA la interfaz: 0.0 = automática según la
                                  # resolución de la pantalla (ver screen_scale.py); > 0 = fija
    high_contrast: bool = False

    # Aspecto de la app: "default" (rojo -> azul neón, el de siempre) o
    # "cosmos" (índigo + violeta/celeste, inspirado en el modo Cosmos del tema
    # de Spotify). Se aplica al arrancar: pide reiniciar (ver theme.set_player_theme).
    player_theme: str = "default"

    # ISO de la última vez que se mostró el resumen semanal automático
    # (ver stats.should_show_weekly_recap, consultado en AppController.start()).
    last_weekly_recap_shown: str = ""

    # Scrobbling (ítem #2 de las propuestas pendientes): "NONE" | "LASTFM"
    # | "LISTENBRAINZ". La contraseña de Last.fm NUNCA se guarda acá —
    # solo la sesión que devuelve auth.getMobileSession (ver scrobbling.py
    # y SettingsDialog._lastfm_connect).
    scrobble_service: str = "NONE"
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    lastfm_session_key: str = ""
    lastfm_username: str = ""
    listenbrainz_token: str = ""

    # Clave de API de YouTube Data v3 (ítem #3): si está presente, tocar
    # la carátula/título de una canción de YouTube/YouTube Music abre el
    # video exacto en vez de una búsqueda genérica (ver youtube_api.py).
    youtube_api_key: str = ""

    # Posición de scroll de Historial/Estadísticas al cerrarse, para
    # restaurarla la próxima vez que se abran (ítem #10) — en píxeles,
    # tal como los devuelve QScrollArea.verticalScrollBar().value().
    history_scroll_pos: int = 0
    stats_scroll_pos: int = 0

    # Modo "panel lateral" (dock_window.py): de qué borde de pantalla
    # asoma la pestaña, y cómo se abre/cierra. "click": solo con clic en
    # la pestaña. "hover": se abre solo al pasar el mouse por la pestaña
    # y se cierra solo al alejarlo (con un margen de gracia). "both":
    # ambos mecanismos activos a la vez — el clic siempre funciona además
    # como apertura/cierre manual inmediato.
    dock_edge: str = "right"          # "left" | "right"
    dock_hide_mode: str = "both"      # "click" | "hover" | "both"
    dock_style: str = "card"          # "card" | "compact" (disco de vinilo, estilo modo compacto)

    # Tema de Spotify (Spicetify "Switch"): el reproductor abre un servidor
    # WebSocket local (solo 127.0.0.1) al que se conecta theme.js desde
    # Spotify, para cambiar de modo (Cosmos / Cover / YefriDev...) desde acá.
    # Ver spotify_theme.py. spotify_theme_mode guarda el último modo conocido
    # solo para mostrarlo mientras Spotify está cerrado (no se reimpone).
    spotify_theme_enabled: bool = True
    spotify_theme_port: int = 8977
    spotify_theme_mode: str = ""

    @classmethod
    def load(cls) -> AppConfig:
        """Nunca falla: si el archivo no existe, está corrupto, o tiene
        campos de una versión distinta del programa, simplemente devuelve
        la configuración por defecto (ignorando lo que no reconozca)."""
        try:
            path = _config_path()
            if not path.exists():
                return cls()
            raw = secret_store.reveal_fields(json.loads(path.read_text(encoding="utf-8")))
            valid_fields = {f.name for f in dataclasses.fields(cls)}
            filtered = {k: v for k, v in raw.items() if k in valid_fields}
            # Actualización desde 1.0: ese config no conoce "start_with_windows".
            # Quien ya usaba el programa no pidió el inicio automático, así que
            # no se le activa en silencio (en instalaciones nuevas sí es True).
            if "start_with_windows" not in raw and raw.get("onboarding_completed"):
                filtered["start_with_windows"] = False
            return cls(**cls._sanitize(filtered))
        except Exception:
            return cls()

    # Valores permitidos / rangos. Un config.json editado a mano (o de otra
    # versión) con un valor imposible (font_scale 0, puerto 99999, un texto
    # donde va un número...) ya no se acepta: ese campo vuelve a su valor por
    # defecto y el resto de la configuración se conserva.
    _CHOICES = {
        "last_mode": ("main", "mini", "dock"),
        "empty_play_action": ("ask", "spotify", "youtube", "ytmusic", "none"),
        "lyrics_panel_side": ("left", "right"),
        "player_theme": ("default", "cosmos"),
        "scrobble_service": ("NONE", "LASTFM", "LISTENBRAINZ"),
        "dock_edge": ("left", "right"),
        "dock_hide_mode": ("click", "hover", "both"),
        "dock_style": ("card", "compact"),
    }
    _RANGES = {
        "port": (1, 65535),
        "spotify_theme_port": (1, 65535),
        "mini_scale": (0.5, 3.0),
        "window_opacity": (0.5, 1.0),
        "font_scale": (0.8, 1.6),
        "history_scroll_pos": (0, 10_000_000),
        "stats_scroll_pos": (0, 10_000_000),
    }

    @classmethod
    def _sanitize(cls, raw: dict) -> dict:
        defaults = cls()
        out = {}
        for name, value in raw.items():
            default = getattr(defaults, name)
            if name in cls._CHOICES:
                ok = isinstance(value, str) and value in cls._CHOICES[name]
            elif isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            elif isinstance(default, str):
                ok = isinstance(value, str)
            else:   # "int | None" (posiciones y ancho de ventana)
                ok = value is None or (isinstance(value, int) and not isinstance(value, bool))
            if not ok:
                continue   # se queda el valor por defecto
            clean = value
            if name in cls._RANGES:
                lo, hi = cls._RANGES[name]
                clean = max(lo, min(hi, clean))
            if name == "ui_scale" and clean != 0 and not (0.5 <= clean <= 3.0):
                continue
            if isinstance(default, float):
                clean = float(clean)
            out[name] = clean
        return out

    def save(self) -> None:
        """Guardar la configuración nunca debe tumbar la app (por ejemplo,
        si el usuario no tiene permisos de escritura en esa carpeta).
        Escritura ATÓMICA: se escribe primero a un archivo temporal y
        recién se reemplaza el definitivo con os.replace() (una sola
        operación a nivel de sistema de archivos). Sin esto, si el proceso
        se corta a la mitad de path.write_text() (cierre forzado, corte de
        luz, cuelgue) el config.json queda truncado — y como config.load()
        descarta cualquier JSON inválido y vuelve a los valores por
        defecto, eso significa perder TODA la configuración guardada de
        golpe (zoom, posición, teclas, si ya se vio la bienvenida...).
        Como esto se guarda cada ~20s (autoguardado) más al cerrar y al
        cambiar cualquier ajuste, la ventana de riesgo no es solo teórica."""
        with soft("config.AppConfig.save"):
            path = _config_path()
            plain = asdict(self)
            # El autoguardado (cada 20 s) reescribía el archivo y volvía a cifrar los
            # secretos con DPAPI aunque nada hubiera cambiado: escrituras a disco sin
            # motivo, y cada una con riesgo de chocar con el antivirus o el indexador.
            # Si lo que se guardaría es idéntico a lo último guardado Y el archivo sigue
            # tal cual quedó (nadie lo editó ni borró), no se toca.
            key = str(path)
            snapshot = json.dumps(plain, sort_keys=True, ensure_ascii=False)
            last = _LAST_SAVED.get(key)
            if last is not None and last[0] == snapshot and _file_stamp(path) == last[1]:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".json.tmp")
            # Los tokens y claves se guardan protegidos (DPAPI en Windows; ver secret_store.py).
            tmp_path.write_text(
                json.dumps(secret_store.protect_fields(plain), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if sys.platform != "win32":
                with contextlib.suppress(OSError):
                    os.chmod(tmp_path, 0o600)       # fuera de Windows no hay cifrado: al menos, solo tu usuario
            _replace_with_retry(tmp_path, path)
            _LAST_SAVED[key] = (snapshot, _file_stamp(path))
