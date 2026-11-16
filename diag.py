"""Avisos silenciosos: en vez de tragarse un error en un `try/except: pass`, se
deja UNA línea en `error.log` y el programa sigue como si nada.

Pensado para los sitios donde un fallo no debe molestar al usuario (guardar una
copia de seguridad, cerrar un recurso, una letra que no llegó...) pero donde,
si algo falla de verdad, conviene poder verlo después en el registro.

Uso:

    from diag import soft

    with soft("history.guardar"):
        escribir_archivo()          # si lanza una excepción, se anota y se sigue

    diag.note("contexto", exc)      # anotar a mano

Reglas:
- Nunca lanza una excepción (un registro que falla no puede romper nada).
- Cada contexto se anota una sola vez por sesión (un temporizador que falla 30
  veces por segundo no llena el disco), con tope de contextos distintos.
- Solo atrapa `Exception` (no `KeyboardInterrupt` ni `SystemExit`).
- No importa nada pesado al cargarse: `error_handling` se carga al anotar, así
  que cualquier módulo (incluido `config`) puede usar este sin ciclos.
"""
from __future__ import annotations

import contextlib
import datetime
import threading

MAX_CONTEXTS = 100                 # contextos distintos que se anotan por sesión
_seen: dict[str, int] = {}
_lock = threading.Lock()


def _default_sink(text: str) -> None:
    import error_handling           # lazy: error_handling importa config
    error_handling._write_log(text)


_sink = _default_sink               # las pruebas lo sustituyen


def note(context: str, exc: BaseException | None = None) -> bool:
    """Anota `context` (y la excepción, si hay) en error.log. Devuelve True si se
    escribió y False si ya estaba anotado o no se pudo. Nunca lanza."""
    try:
        with _lock:
            if context in _seen or len(_seen) >= MAX_CONTEXTS:
                _seen[context] = _seen.get(context, 0) + 1
                return False
            _seen[context] = 1
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detail = f"{type(exc).__name__}: {exc}" if exc is not None else ""
        _sink(f"--- {stamp} aviso [{context}] {detail}".rstrip() + "\n")
        return True
    except Exception:
        return False


@contextlib.contextmanager
def soft(context: str):
    """Bloque que no debe tumbar nada: si falla, se anota una vez y se continúa."""
    try:
        yield
    except Exception as exc:
        note(context, exc)


def reset() -> None:
    """Olvida lo anotado (solo para pruebas)."""
    with _lock:
        _seen.clear()
