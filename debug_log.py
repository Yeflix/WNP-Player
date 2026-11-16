"""Modo depuración: terminal visible + registro completo de lo que sucede.

Se activa de cualquiera de estas formas (no hace falta recompilar):

- `YefriPlayer.exe --log`                     (o `--log RUTA` para elegir el archivo)
- variable de entorno `YEFRIPLAYER_DEBUG=1`
- un archivo vacío llamado `depurar.flag` junto al `.exe` (lo crea
  `tools/compilar_nuitka.py --depurar`, que además compila con consola)

Qué hace:
- Abre una **terminal** si el programa no tiene (el `.exe` normal no la tiene).
  Cerrar esa ventana cierra el programa.
- Escribe TODO en `debug.log` (carpeta de datos de YefriPlayer; rota a 2 MB y
  conserva 3 copias): lo que el programa imprime (stdout/stderr), los avisos de
  Qt, los registros de `logging` (aiohttp, asyncio...), las excepciones y cada
  línea que va a `error.log`. Cada sesión empieza con una cabecera con versión,
  Python, ruta del `.exe` y argumentos.
- Nunca lanza una excepción: si algo del registro falla, el programa sigue.
"""
from __future__ import annotations

import atexit
import contextlib
import io
import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback
from pathlib import Path

LOG_NAME = "debug.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 3
FLAG_NAME = "depurar.flag"
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

_active = False
_path: Path | None = None


def active() -> bool:
    return _active


def log_file() -> Path | None:
    return _path


def requested(argv: list[str] | None = None, environ=None, exe_dir: str | None = None) -> bool:
    """¿Se pidió el modo depuración? (argumento --log, variable o archivo depurar.flag)."""
    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    if any(a == "--log" or a.startswith("--log=") for a in argv[1:]):
        return True
    if str(environ.get("YEFRIPLAYER_DEBUG", "")).strip().lower() in ("1", "true", "si", "sí", "yes", "on"):
        return True
    if exe_dir is None:
        try:
            import version
            exe_dir = os.path.dirname(version.executable_path())
        except Exception:
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv else "."))
    return os.path.isfile(os.path.join(exe_dir, FLAG_NAME))


def _explicit_path(argv: list[str]) -> str | None:
    for i, a in enumerate(argv[1:], start=1):
        if a.startswith("--log="):
            return a.split("=", 1)[1] or None
        if a == "--log" and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            return argv[i + 1]
    return None


def _data_dir() -> Path:
    try:
        import config
        return Path(config._config_dir())
    except Exception:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        elif sys.platform == "darwin":
            base = str(Path.home() / "Library" / "Application Support")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "YefriPlayer"


def _open_console():
    """Windows: si el programa no tiene terminal (el .exe va sin consola), abre una y
    devuelve un flujo de texto hacia ella. En el resto de casos devuelve None."""
    if sys.platform != "win32":
        return None
    if sys.stdout is not None and sys.stderr is not None:
        return None
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.AllocConsole()                     # 0 si ya había una: no pasa nada
        kernel32.SetConsoleTitleW("YefriPlayer — registro (cerrar esta ventana cierra el programa)")
        kernel32.SetConsoleOutputCP(65001)          # UTF-8: tildes y ñ
        return open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        return None


class _Tee:
    """Sustituye a sys.stdout / sys.stderr: cada línea impresa pasa al registro (que la
    muestra en la terminal y la guarda en el archivo)."""

    def __init__(self, name: str, level: int) -> None:
        self._log = logging.getLogger(name)
        self._level = level
        self._buf = ""
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, text) -> int:
        try:
            self._buf += str(text)
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._log.log(self._level, line.rstrip())
        except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
            pass
        return len(text) if hasattr(text, "__len__") else 0

    def flush(self) -> None:
        if self._buf.strip():
            with contextlib.suppress(Exception):
                self._log.log(self._level, self._buf.rstrip())
        self._buf = ""

    def reconfigure(self, **_kwargs) -> None:       # algunas bibliotecas lo llaman sobre sys.stdout
        pass

    def fileno(self) -> int:
        raise io.UnsupportedOperation("fileno")     # no es un archivo real (lo esperado por faulthandler & co.)

    closed = False

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


def _install_hooks() -> None:
    log = logging.getLogger("excepciones")

    def main_hook(exc_type, exc, tb):
        log.critical("Excepción sin capturar:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    def thread_hook(args):
        log.critical("Excepción sin capturar en el hilo %s:\n%s",
                     getattr(args.thread, "name", "?"),
                     "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    def unraisable_hook(args):
        log.error("Excepción ignorada en %r: %s", args.object, args.exc_value)

    sys.excepthook = main_hook
    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook


def _install_qt_handler() -> None:
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return
    log = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def handler(kind, context, message):
        try:
            where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
            log.log(levels.get(kind, logging.INFO), "%s%s", message, where)
        except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
            pass

    qInstallMessageHandler(handler)


def start(argv: list[str] | None = None, path: str | Path | None = None) -> Path | None:
    """Activa el modo depuración. Devuelve la ruta del registro (o None si no pudo)."""
    global _active, _path
    if _active:
        return _path
    argv = sys.argv if argv is None else argv
    try:
        target = Path(path or _explicit_path(argv) or (_data_dir() / LOG_NAME))
        target.parent.mkdir(parents=True, exist_ok=True)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for h in list(root.handlers):
            root.removeHandler(h)
        formatter = logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

        file_handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        console = _open_console() or (sys.__stderr__ if sys.__stderr__ is not None else None)
        if console is not None:
            console_handler = logging.StreamHandler(console)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        sys.stdout = _Tee("stdout", logging.INFO)
        sys.stderr = _Tee("stderr", logging.WARNING)
        logging.captureWarnings(True)
        _install_hooks()
        _install_qt_handler()

        log = logging.getLogger("yefriplayer")
        log.info("=" * 70)
        try:
            import version
            log.info("%s %s · Python %s · %s", version.APP_NAME, version.APP_VERSION,
                     platform.python_version(), platform.platform())
            log.info("ejecutable: %s · empaquetado=%s", version.executable_path(), version.is_frozen())
        except Exception as exc:
            log.info("Python %s · %s (version no disponible: %s)", platform.python_version(), platform.platform(), exc)
        log.info("argumentos: %s", argv[1:])
        log.info("registro: %s", target)
        atexit.register(lambda: logging.getLogger("yefriplayer").info("proceso terminado"))
        _active, _path = True, target
        return target
    except Exception:
        return None


def forward(text: str) -> None:
    """Copia al registro de depuración una línea que se escribió en error.log."""
    if _active:
        with contextlib.suppress(Exception):
            logging.getLogger("error.log").error(text.rstrip())


def stop() -> None:
    """Solo para pruebas: deja todo como estaba."""
    global _active, _path
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    logging.captureWarnings(False)
    _active, _path = False, None
