"""
Verifica que las dependencias necesarias estén instaladas antes de
arrancar. Si falta algo, mejor mostrar un aviso claro (con el comando
exacto para instalarlo) que dejar que el programa truene con un
ImportError críptico apenas se intenta usar.
"""
from __future__ import annotations

import sys

from version import is_frozen

# `winsdk` (lo usa pywnp en Windows) dejó de publicarse en 2023 y solo tiene
# versiones para Python 3.8 a 3.12.
WINSDK_MAX_PYTHON = (3, 12)


def winsdk_supported(version_info=None) -> bool:
    v = tuple((version_info or sys.version_info)[:2])
    return v <= WINSDK_MAX_PYTHON


def _python_message(version_info=None) -> str:
    v = tuple((version_info or sys.version_info)[:2])
    return (
        f"Tu Python es {v[0]}.{v[1]}, pero en Windows YefriPlayer necesita Python "
        "3.10 a 3.12: 'winsdk' (que lee los reproductores de escritorio como "
        "Spotify) no tiene versión para 3.13 o superior.\n\n"
        "Instala Python 3.12 desde python.org y vuelve a ejecutar:\n\n"
        "    pip install -r requirements.txt"
    )


def check_dependencies() -> list[str]:
    """Retorna una lista de problemas encontrados (vacía si todo está bien)."""
    problems: list[str] = []

    try:
        import pywnp  # noqa: F401 — se importa solo para comprobar que existe
    except ImportError:
        problems.append(
            "Falta instalar 'pywnp' (es lo que habla con la extensión del "
            "navegador). En una terminal:\n\n    pip install pywnp"
        )

    try:
        import aiohttp  # noqa: F401 — se importa solo para comprobar que existe
    except ImportError:
        problems.append(
            "Falta instalar 'aiohttp' (lo necesita pywnp para su servidor). "
            "En una terminal:\n\n    pip install aiohttp"
        )

    if sys.platform == "win32" and not is_frozen():
        try:
            import winsdk  # noqa: F401 — se importa solo para comprobar que existe
        except ImportError:
            if not winsdk_supported():
                problems.append(_python_message())      # `pip install winsdk` no serviría aquí
            else:
                problems.append(
                    "Falta instalar 'winsdk' (necesario en Windows para leer "
                    "reproductores de escritorio como Spotify). En una terminal:"
                    "\n\n    pip install winsdk"
                )

    return problems
