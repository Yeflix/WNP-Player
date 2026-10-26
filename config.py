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

from backend import DEFAULT_PORT

APP_DIR_NAME = "WNPPlayer"
CONFIG_FILENAME = "config.json"


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def _config_path() -> Path:
    return _config_dir() / CONFIG_FILENAME


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
    start_minimized: bool = False

    hotkeys_enabled: bool = False
    hotkey_play_pause: str = ""   # p.ej. "ctrl+alt+p" (vacío = sin asignar)
    hotkey_next: str = ""
    hotkey_previous: str = ""

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
            raw = json.loads(path.read_text(encoding="utf-8"))
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
            if name in cls._RANGES:
                lo, hi = cls._RANGES[name]
                value = max(lo, min(hi, value))
            if name == "ui_scale" and value != 0 and not (0.5 <= value <= 3.0):
                continue
            if isinstance(default, float):
                value = float(value)
            out[name] = value
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
        try:
            path = _config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)
        except Exception:
            pass
