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
import sys
import threading
import time
import traceback
from pathlib import Path

from config import _config_dir

LOG_FILENAME = "error.log"
_MAX_LOG_BYTES = 512 * 1024  # rotar el log si crece demasiado


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


def _write_log(text: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
            path.write_text("", encoding="utf-8")  # rotación simple: reiniciar
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass  # si ni siquiera se puede escribir el log, no hay más que hacer


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
        sys.stderr.write(text)  # también a consola, para quien esté depurando
        global _dialog_open
        signature = (exc_type.__name__, str(exc_value)[:200])
        if not _should_show_dialog(signature):
            return
        _dialog_open = True
        try:
            _show_dialog(text)
        except Exception:
            pass  # mostrar el aviso de error nunca debe generar OTRO error
        finally:
            _dialog_open = False

    def _handle_thread(args):
        text = _format(args.exc_type, args.exc_value, args.exc_traceback,
                        thread_name=args.thread.name if args.thread else None)
        _write_log(text)
        sys.stderr.write(text)

    sys.excepthook = _handle_main_thread
    threading.excepthook = _handle_thread


def _show_dialog(details: str) -> None:
    from PyQt6.QtWidgets import QApplication
    from dialogs import ErrorDialog

    app = QApplication.instance()
    if app is None:
        return
    dlg = ErrorDialog(details)
    dlg.exec()
