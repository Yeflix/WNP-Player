"""Autoprueba del programa EMPAQUETADO: `YefriPlayer.exe --autotest [archivo]`.

Sirve para saber, sin abrir la interfaz, si el `.exe` (PyInstaller o Nuitka) trae
todo lo necesario: módulos de Qt, aiohttp y sus extensiones, pywnp, winsdk (con una
llamada real a las sesiones multimedia de Windows), numpy, PyAudioWPatch, el cifrado
de DPAPI y la carpeta de datos. El `.exe` no tiene consola, así que el informe se
escribe en un archivo (por defecto `autotest.txt` en la carpeta de datos).

Código de salida: 0 si todo lo imprescindible está bien, 1 si algo falla.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import sys
import traceback

# (módulo, imprescindible, solo_windows)
MODULOS = [
    ("PyQt6.QtCore", True, False), ("PyQt6.QtGui", True, False), ("PyQt6.QtWidgets", True, False),
    ("PyQt6.QtNetwork", True, False), ("PyQt6.QtWebSockets", True, False),
    ("pywnp", True, False), ("aiohttp", True, False), ("aiohttp.web", True, False),
    ("aiohappyeyeballs", True, False), ("aiosignal", True, False), ("attr", True, False),
    ("frozenlist", True, False), ("multidict", True, False), ("propcache", True, False),
    ("yarl", True, False),
    ("winreg", True, True),
    ("winsdk.system", True, True), ("winsdk.windows.foundation", True, True),
    ("winsdk.windows.foundation.collections", True, True), ("winsdk.windows.media", True, True),
    ("winsdk.windows.media.control", True, True), ("winsdk.windows.storage.streams", True, True),
    ("numpy", False, False), ("pyaudiowpatch", False, True),
]
APP = ["accent", "ad_filter", "ad_log", "app_controller", "app_icon", "app_volume", "audio_levels", "autostart",
       "backend", "config", "cosmos_sky", "cover_loader", "debug_log", "diag", "dialogs", "dock_window",
       "error_handling", "history", "hotkeys", "icons", "likes", "likes_dialog", "links", "lyrics",
       "main_window", "mini_window", "oauth_pkce", "onboarding", "player_launcher", "process_loopback",
       "pywnp_patch", "screen_scale", "scrobbling", "secret_store", "single_instance", "splash", "spotify_theme",
       "startup_checks", "stats", "stats_store", "taskbar_buttons", "theme", "updater", "version",
       "weekly_recap", "welcome_fx", "widgets", "wincom", "workers", "youtube_api"]


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failures = 0

    def ok(self, text: str) -> None:
        self.lines.append(f"OK     {text}")

    def info(self, text: str) -> None:
        self.lines.append(f"       {text}")

    def warn(self, text: str) -> None:
        self.lines.append(f"AVISO  {text}")

    def fail(self, text: str, exc: BaseException | None = None) -> None:
        self.failures += 1
        self.lines.append(f"FALLA  {text}")
        if exc is not None:
            tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.lines.append(f"       -> {tb}")


def _check(rep: Report, label: str, fn, *, required: bool = True) -> None:
    try:
        detail = fn()
        rep.ok(label + (f"  [{detail}]" if detail else ""))
    except Exception as exc:
        (rep.fail if required else lambda t, e=None: rep.warn(f"{t} (opcional): {type(e).__name__}: {e}"))(label, exc)


def run(path: str | None = None) -> int:
    import version
    rep = Report()
    win = sys.platform == "win32"
    rep.info(f"{version.APP_NAME} {version.APP_VERSION} · Python {sys.version.split()[0]} · {sys.platform}")
    rep.info(f"ejecutable: {sys.executable}")
    rep.info(f"empaquetado: {version.is_frozen()} (compilado con Nuitka: {'__compiled__' in globals()})")
    rep.info(f"ruta real del programa: {version.executable_path()}")

    rep.lines.append("-- Módulos de terceros")
    for name, required, only_win in MODULOS:
        if only_win and not win:
            continue
        _check(rep, name, lambda n=name: importlib.import_module(n) and "", required=required)

    rep.lines.append("-- Módulos del programa")
    for name in APP:
        _check(rep, name, lambda n=name: importlib.import_module(n) and "")

    rep.lines.append("-- Funcionamiento")

    def aiohttp_ext():
        from aiohttp import http_parser
        impl = http_parser.HttpRequestParser.__module__
        return f"analizador HTTP: {impl}"
    _check(rep, "aiohttp (extensión C o Python)", aiohttp_ext)

    def datos():
        import config
        d = config._config_dir()
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".autotest.tmp"
        t.write_text("ok", encoding="utf-8")
        assert t.read_text(encoding="utf-8") == "ok"
        t.unlink()
        return str(d)
    _check(rep, "carpeta de datos escribible", datos)

    def parche():
        import pywnp_patch
        pywnp_patch.apply()
        return "parche de pywnp aplicado"
    _check(rep, "pywnp + parche", parche)

    def cifrado():
        import secret_store
        enc = secret_store.protect("prueba-ñ")
        if win and not enc.startswith(secret_store.PREFIX):
            raise RuntimeError("DPAPI no está disponible: los tokens se guardarían en claro")
        assert secret_store.reveal(enc) == "prueba-ñ"
        return "DPAPI" if enc.startswith(secret_store.PREFIX) else "sin cifrado (no es Windows)"
    _check(rep, "cifrado de tokens", cifrado, required=win)

    def qt():
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv[:1])
        img = QImage(8, 8, QImage.Format.Format_ARGB32)
        assert not img.isNull()
        return f"plataforma Qt: {app.platformName()}"
    _check(rep, "Qt arranca", qt)

    def sesiones():
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

        async def pedir():
            mgr = await asyncio.wait_for(M.request_async(), 15)
            return len(list(mgr.get_sessions()))
        return f"{asyncio.run(pedir())} sesión(es) multimedia abiertas"
    if win:
        _check(rep, "sesiones multimedia de Windows (winsdk, llamada real)", sesiones)

    def audio():
        import audio_levels
        okay, why = audio_levels.availability()
        if not okay:
            raise RuntimeError(why)
        return "visualizador disponible"
    _check(rep, "visualizador de audio", audio, required=False)

    # Llamadas REALES a Windows de las funciones nuevas de 1.5 (no se pueden probar
    # fuera de Windows): si algo de ctypes/COM está mal, aparece aquí y no en uso.
    def volumen_app():
        import app_volume
        svc = app_volume.AppVolume()
        try:
            sessions = svc.sessions()
        finally:
            svc.close()
        activas = sum(1 for _p, _e, a in sessions if a)
        return f"{len(sessions)} sesión(es) de audio, {activas} sonando"
    if win:
        _check(rep, "volumen por aplicación (Core Audio, llamada real)", volumen_app, required=False)

    def captura_por_app():
        import process_loopback as PL
        ok, why = PL.availability()
        if not ok:
            raise RuntimeError(why)
        src = PL.ProcessLoopbackSource("autotest", target_resolver=lambda _n: (os.getpid(), "propio"))
        src.start(lambda *_a: None)          # activa la captura sobre este mismo proceso
        src.stop()
        oficial = "" if PL.windows_build() >= PL.OFFICIAL_BUILD else " (Windows anterior al mínimo oficial: funciona)"
        return "Application Loopback activado y cerrado" + oficial
    if win:
        _check(rep, "visualizador: captura solo del reproductor (llamada real)", captura_por_app, required=False)

    def icono_barra():
        import taskbar_buttons as TB
        h = TB._hicon_from_image(TB._icon_image("play", 16))
        if not h:
            raise RuntimeError("CreateIconIndirect devolvió 0")
        import ctypes
        ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(h))
        return "iconos de la miniatura de la barra de tareas"
    if win:
        _check(rep, "barra de tareas: iconos (llamada real)", icono_barra, required=False)

    def autoarranque():
        import autostart
        cmd = autostart.launch_command()
        return cmd
    _check(rep, "comando de «Iniciar con Windows»", autoarranque)

    rep.lines.append("")
    rep.lines.append("RESULTADO: todo ok" if not rep.failures else f"RESULTADO: {rep.failures} FALLA(S)")
    if rep.failures and win:
        rep.lines.append("Si falla algún módulo de winsdk: compila con  python tools/compilar_nuitka.py --winsdk-completo")
    text = "\n".join(rep.lines) + "\n"
    if path is None:
        try:
            import config
            path = str(config._config_dir() / "autotest.txt")
        except Exception:
            path = os.path.join(os.path.expanduser("~"), "yefriplayer-autotest.txt")
    with contextlib.suppress(OSError), open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if sys.stdout:
        with contextlib.suppress(Exception):
            print(text)
    return 1 if rep.failures else 0


def report_path(path: str | None = None) -> str:
    if path:
        return path
    try:
        import config
        return str(config._config_dir() / "autotest.txt")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "yefriplayer-autotest.txt")


def show_report(path: str | None = None) -> None:
    """Abre el informe con el programa predeterminado (Bloc de notas). El .exe
    no tiene consola: sin esto, `--autotest` no mostraba nada en pantalla."""
    target = report_path(path)
    if not os.path.isfile(target):
        return
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606 — abrir el informe que acabamos de escribir
        else:
            import subprocess
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", target])  # noqa: S603,S607

