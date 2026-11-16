"""Hilos de fondo con la biblioteca estándar (sustituye a QThreadPool/QRunnable).

Por qué no QThreadPool: Nuitka avisa de que los hilos propios de Qt no funcionan bien
con PyQt6 cuando el programa se compila con él, y las búsquedas de letras, las
carátulas y los «me gusta» corren en segundo plano. Con hilos de Python funcionan
igual con `python main.py`, con PyInstaller y con Nuitka.

Un trabajo es cualquier objeto con un método `run()`. Para avisar a la interfaz
se emite una señal (`pyqtSignal`) desde `run()`: PyQt la entrega en el hilo de
la interfaz (conexión en cola) aunque se emita desde un hilo de Python.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

DEFAULT_WORKERS = 4


class BackgroundPool:
    """Grupo pequeño de hilos de Python. Misma interfaz que se usaba de QThreadPool
    en este proyecto: `start(job)`."""

    def __init__(self, max_workers: int = DEFAULT_WORKERS, name: str = "yefriplayer"):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
        self._cond = threading.Condition()
        self._pending = 0

    def start(self, job) -> None:
        with self._cond:
            self._pending += 1
        try:
            self._executor.submit(self._run, job)
        except RuntimeError:
            with self._cond:                   # el programa se está cerrando: ya no se aceptan trabajos
                self._pending -= 1
                self._cond.notify_all()

    def _run(self, job) -> None:
        try:
            job.run()
        except Exception:
            import traceback
            try:
                import error_handling
                error_handling._write_log("Error en un trabajo de fondo:\n" + traceback.format_exc())
            except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
                pass
        finally:
            with self._cond:
                self._pending -= 1
                self._cond.notify_all()

    def wait_for_done(self, timeout: float = 10.0) -> bool:
        """Espera a que terminen los trabajos pendientes (lo usan las pruebas).
        Devuelve True si terminaron antes del plazo."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending <= 0, timeout=timeout)

    def shutdown(self) -> None:
        """Al cerrar: no espera a los trabajos en curso (los hilos terminan solos)."""
        self._executor.shutdown(wait=False, cancel_futures=True)


_default: BackgroundPool | None = None
_lock = threading.Lock()


def default_pool() -> BackgroundPool:
    """El grupo compartido de la aplicación (se crea la primera vez que se pide)."""
    global _default  # noqa: PLW0603 — estado de módulo a propósito (lo leen otros módulos o las pruebas)
    with _lock:
        if _default is None:
            _default = BackgroundPool()
        return _default
