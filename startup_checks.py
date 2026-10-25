"""
Verifica que las dependencias necesarias estén instaladas antes de
arrancar. Si falta algo, mejor mostrar un aviso claro (con el comando
exacto para instalarlo) que dejar que el programa truene con un
ImportError críptico apenas se intenta usar.
"""
from __future__ import annotations

import sys


def check_dependencies() -> list[str]:
    """Retorna una lista de problemas encontrados (vacía si todo está bien)."""
    problems: list[str] = []

    try:
        import pywnp  # noqa: F401
    except ImportError:
        problems.append(
            "Falta instalar 'pywnp' (es lo que habla con la extensión del "
            "navegador). En una terminal:\n\n    pip install pywnp"
        )

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        problems.append(
            "Falta instalar 'aiohttp' (lo necesita pywnp para su servidor). "
            "En una terminal:\n\n    pip install aiohttp"
        )

    if sys.platform == "win32":
        try:
            import winsdk  # noqa: F401
        except ImportError:
            problems.append(
                "Falta instalar 'winsdk' (necesario en Windows para leer "
                "reproductores de escritorio como Spotify). En una terminal:"
                "\n\n    pip install winsdk"
            )

    return problems
