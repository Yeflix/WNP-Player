"""
Manejador de errores global.

Sin esto, si algo inesperado truena en un lugar que Qt no protege bien
(la app "desaparece" o queda en un estado raro sin ninguna explicación
visible). Con esto: se guarda el detalle técnico en un archivo de registro
(para poder revisarlo después sin tener que reproducir el error) y se
muestra un aviso amigable, sin tumbar el resto de la aplicación.

Nota importante: los widgets de Qt solo pueden crearse/tocarse desde el
hilo principal (GUI). `sys.excepthook` cubre excepciones del hilo
principal (incluyendo las que ocurren dentro de slots conectados a
señales, que es la gran mayoría de los casos reales). Para excepciones en
hilos secundarios (poco frecuentes, ya que los puntos más riesgosos del
proyecto ya atrapan sus propias excepciones) se instala también un
`threading.excepthook` que solo registra en el log, sin intentar mostrar
una ventana desde el hilo equivocado.
"""
from __future__ import annotations

import datetime
import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from config import _config_dir

LOG_FILENAME = "error.log"
_MAX_LOG_BYTES = 512 * 1024  # al pasar de aquí el log pasa a error.log.1 (no se pierde)
CRASH_FILENAME = "crash.log"
_MAX_CRASH_BYTES = 256 * 1024
_crash_file = None           # se mantiene abierto mientras viva el proceso (faulthandler lo necesita)


# Un error que se repite (un timer, un paintEvent) abría un diálogo por cada
# vez. Ahora: solo uno a la vez, y el MISMO error no vuelve a mostrarse
# durante _DIALOG_COOLDOWN_S (sigue yendo siempre al log).
_DIALOG_COOLDOWN_S = 60.0
_dialog_open = False
_last_dialog_at: dict = {}


def _should_show_dialog(signature, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    if _dialog_open:
        return False
    last = _last_dialog_at.get(signature)
    if last is not None and now - last < _DIALOG_COOLDOWN_S:
        return False
    if len(_last_dialog_at) > 200:
        _last_dialog_at.clear()
    _last_dialog_at[signature] = now
    return True


def log_path() -> Path:
    return _config_dir() / LOG_FILENAME


def _rotate(path: Path, max_bytes: int) -> None:
    """Si el archivo pasa del tope, se archiva como `<nombre>.1` (reemplazando
    al archivo anterior). Antes se BORRABA el log entero al rotar: justo tras
    una falla larga se perdía la evidencia que hacía falta para entenderla."""
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        pass


def _write_log(text: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path, _MAX_LOG_BYTES)
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
        pass  # si ni siquiera se puede escribir el log, no hay más que hacer
    dbg = sys.modules.get("debug_log")           # modo depuración: copia la línea a debug.log
    if dbg is not None:
        dbg.forward(text)


def _to_console(text: str) -> None:
    """En el .exe sin consola `sys.stderr` es None: escribir ahí lanzaba
    AttributeError DENTRO del manejador de errores y el aviso nunca aparecía."""
    try:
        if sys.stderr:
            sys.stderr.write(text)
    except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
        pass


def crash_log_path() -> Path:
    return _config_dir() / CRASH_FILENAME


def _report_previous_crash(path: Path) -> bool:
    """Si la sesión anterior terminó con un fallo nativo (Qt o una extensión en
    C), `faulthandler` dejó el detalle en crash.log. Se copia al registro de
    errores y se archiva, para verlo todo en un solo lugar y no repetirlo."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        detail = path.read_text(encoding="utf-8", errors="replace")[-4000:]
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_log(f"--- {stamp} cierre inesperado de la sesión anterior (crash.log) ---\n{detail}\n")
        os.replace(path, path.with_name(path.name + ".1"))
        return True
    except OSError:
        return False


def install_native_crash_log() -> bool:
    """Registra los cierres NATIVOS (segfault en Qt, una DLL...), que
    `sys.excepthook` no ve porque Python ya ni siquiera llega a ejecutarse.
    Con consola `faulthandler` escribiría en stderr; en el .exe es None, así
    que se le da un archivo."""
    global _crash_file  # noqa: PLW0603 — estado de módulo a propósito (lo leen otros módulos o las pruebas)
    try:
        path = crash_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _report_previous_crash(path)
        _rotate(path, _MAX_CRASH_BYTES)
        if _crash_file is None or _crash_file.closed:
            _crash_file = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
        return True
    except Exception:
        return False


def _format(exc_type, exc_value, exc_tb, thread_name: str | None = None) -> str:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"--- {timestamp}" + (f" (hilo: {thread_name})" if thread_name else "") + " ---\n"
    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return header + body + "\n"


def install() -> None:
    """Instala los manejadores globales. Llamar una sola vez, apenas
    arranca la app, después de crear la QApplication."""

    def _handle_main_thread(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = _format(exc_type, exc_value, exc_tb)
        _write_log(text)
        _to_console(text)  # también a consola, para quien esté depurando
        global _dialog_open  # noqa: PLW0603 — estado de módulo a propósito (lo leen otros módulos o las pruebas)
        signature = (exc_type.__name__, str(exc_value)[:200])
        if not _should_show_dialog(signature):
            return
        _dialog_open = True
        try:
            _show_dialog(text)
        except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
            pass  # mostrar el aviso de error nunca debe generar OTRO error
        finally:
            _dialog_open = False

    def _handle_thread(args):
        text = _format(args.exc_type, args.exc_value, args.exc_traceback,
                        thread_name=args.thread.name if args.thread else None)
        _write_log(text)
        _to_console(text)

    sys.excepthook = _handle_main_thread
    threading.excepthook = _handle_thread
    install_native_crash_log()


def _show_dialog(details: str) -> None:
    from PyQt6.QtWidgets import QApplication
    from dialogs import ErrorDialog

    app = QApplication.instance()
    if app is None:
        return
    dlg = ErrorDialog(details)
    dlg.exec()
