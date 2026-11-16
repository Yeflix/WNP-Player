#!/usr/bin/env python
"""Compila YefriPlayer con Nuitka (alternativa a PyInstaller / main.spec).

Uso, desde la carpeta del proyecto y con el entorno virtual activado:

    python tools/compilar_nuitka.py                 # carpeta con YefriPlayer.exe (recomendado)
    python tools/compilar_nuitka.py --onefile       # un solo .exe (arranca más lento)
    python tools/compilar_nuitka.py --dry-run       # solo muestra el comando, no compila

Resultado: dist-nuitka/main.dist/ → renombrada a dist-nuitka/YefriPlayer/ con
YefriPlayer.exe dentro. Para repartirlo, comprime esa carpeta en un .zip.

Requisitos (una sola vez):
    pip install nuitka ordered-set zstandard
    - Un compilador de C. En Windows, lo más fácil: instala "Build Tools for Visual
      Studio" (carga de trabajo "Desarrollo para el escritorio con C++") o deja que
      Nuitka descargue MinGW64 (pregunta una vez; --asumir-si lo acepta solo).
    - Python 3.10 a 3.12 en Windows (winsdk no existe para 3.13+).

Qué hace distinto a PyInstaller: Nuitka traduce el código Python a C y lo compila.
El arranque es más rápido y el resultado es más difícil de confundir con un
empaquetador genérico, a cambio de una compilación MUCHO más lenta (de minutos a
decenas de minutos la primera vez; las siguientes reutilizan lo ya compilado).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import version as V

# Paquetes que se cargan por importación dinámica o traen extensiones: se piden
# explícitamente para que no falte nada en el ejecutable.
PACKAGES = [
    "pywnp",                                        # puente con WebNowPlaying / Windows
    "aiohttp", "aiohappyeyeballs", "aiosignal",     # servidor WebSocket de pywnp
    "attr", "attrs", "frozenlist", "multidict", "propcache", "yarl",
]
# Módulos de winsdk que usa pywnp (solo Windows). `winsdk.windows.media` entero
# arrastra más de 300 módulos sin uso: se piden solo los necesarios. Si al ejecutar
# falta alguno, usa --winsdk-completo.
WINSDK_MODULES = [
    "winsdk.system",
    "winsdk.windows.foundation",
    "winsdk.windows.foundation.collections",
    "winsdk.windows.media",
    "winsdk.windows.media.control",
    "winsdk.windows.storage.streams",
]
# numpy y PyAudioWPatch (visualizador de audio) NO se piden con --include-package: los
# importa audio_levels.py de forma estática y Nuitka los sigue solo. Forzar
# `numpy` entero arrastraba sus pruebas, pytest y cientos de módulos sin uso
# (la compilación se volvía enorme y lenta).
# Módulos que el programa no usa. OJO: NO se excluyen `unittest`, `test` ni `pydoc`: alguna
# biblioteca puede importarlos y, excluidos, el .exe fallaría al ejecutarse.
NOFOLLOW = [
    "tkinter", "setuptools", "pip",
    "numpy.testing", "numpy.f2py", "numpy.distutils", "numpy.conftest",
    "aiohttp.pytest_plugin", "aiohttp.test_utils", "aiohttp.worker",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick",
    "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtQuickWidgets", "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets", "PyQt6.Qt3DCore", "PyQt6.QtSql", "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets", "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtSensors",
    "PyQt6.QtSerialPort", "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtTest",
    "PyQt6.QtSvg", "PyQt6.QtSvgWidgets", "PyQt6.QtOpenGL", "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtPositioning", "PyQt6.QtRemoteObjects", "PyQt6.QtXml",
    "PyQt6.QtStateMachine",
]


def _installed(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def build_command(
    *,
    platform: str | None = None,
    python: str | None = None,
    root: Path = ROOT,
    onefile: bool = False,
    console: bool = False,
    jobs: int | None = None,
    lto: bool = False,
    msvc: bool = False,
    mingw: bool = False,
    asumir_si: bool = False,
    winsdk_completo: bool = False,
    output_dir: str = "dist-nuitka",
    optional_present=_installed,
) -> list[str]:
    """Arma la línea de comandos de Nuitka. Es una función pura (no ejecuta nada)
    para poder comprobarla en las pruebas."""
    platform = platform or sys.platform
    win = platform == "win32"
    ver = [int(x) for x in V.APP_VERSION.split(".")[:3]] + [0, 0, 0]
    ver4 = ".".join(str(n) for n in ver[:3] + [0])
    cmd = [python or sys.executable, "-m", "nuitka"]
    cmd.append("--mode=onefile" if onefile else "--mode=standalone")
    cmd.append("--enable-plugins=pyqt6")
    cmd += [f"--output-dir={output_dir}", f"--output-filename={V.APP_NAME}"]
    cmd += [f"--include-package={p}" for p in PACKAGES if optional_present(p)]   # los no instalados se omiten
    if win:
        if winsdk_completo:
            cmd.append("--include-package=winsdk")
        else:
            cmd += [f"--include-module={m}" for m in WINSDK_MODULES]
    cmd += [f"--nofollow-import-to={m}" for m in NOFOLLOW]
    # Licencia y léeme junto al ejecutable (la GPL exige acompañar el texto de la licencia).
    for name in ("LICENSE", "README.md"):
        if (root / name).exists():
            cmd.append(f"--include-data-files={root / name}={name}")
    if win:
        cmd.append("--windows-console-mode=" + ("force" if console else "disable"))
        icon = root / "assets" / "yefriplayer.ico"
        if icon.exists():
            cmd.append(f"--windows-icon-from-ico={icon}")
        cmd += [
            f"--company-name={V.AUTHOR}",
            f"--product-name={V.APP_NAME}",
            f"--file-description={V.APP_NAME} - {V.APP_TAGLINE}",
            f"--file-version={ver4}",
            f"--product-version={V.APP_VERSION}",
            f"--copyright=Copyright (C) 2026 {V.AUTHOR}. GPL-3.0",
        ]
        if msvc:
            cmd.append("--msvc=latest")
        elif mingw:
            cmd.append("--mingw64")
    if jobs:
        cmd.append(f"--jobs={jobs}")
    cmd.append("--lto=yes" if lto else "--lto=no")     # LTO ahorra poco y alarga mucho la compilación
    if asumir_si:
        cmd.append("--assume-yes-for-downloads")
    cmd.append(str(root / "main.py"))
    return cmd


def check_environment(platform: str | None = None) -> list[str]:
    """Problemas que impedirían compilar bien (lista de textos; vacía = todo bien)."""
    platform = platform or sys.platform
    problems = []
    if not _installed("nuitka"):
        problems.append("Falta Nuitka:  pip install nuitka ordered-set zstandard")
    if not _installed("PyQt6"):
        problems.append("Falta PyQt6:  pip install -r requirements.txt")
    if platform == "win32":
        if sys.version_info >= (3, 13):
            problems.append(
                f"Python {sys.version_info[0]}.{sys.version_info[1]}: winsdk solo existe para "
                "Python 3.10 a 3.12. Crea el entorno con Python 3.12.")
        if not _installed("winsdk"):
            problems.append("Falta winsdk (lee Spotify y otras apps):  pip install -r requirements.txt")
    elif platform.startswith("linux") and shutil.which("patchelf") is None:
        problems.append("En Linux Nuitka necesita patchelf:  pip install patchelf")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compila YefriPlayer con Nuitka.")
    ap.add_argument("--onefile", action="store_true", help="un solo .exe en vez de una carpeta")
    ap.add_argument("--console", action="store_true", help="deja visible la consola (para depurar)")
    ap.add_argument("--depurar", action="store_true",
                    help="compila con terminal visible Y deja junto al .exe un archivo depurar.flag, "
                         "que activa el registro completo en debug.log (ver debug_log.py)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="compilaciones en paralelo")
    ap.add_argument("--lto", action="store_true", help="optimización en el enlazado (más lento)")
    ap.add_argument("--msvc", action="store_true", help="usar Visual Studio Build Tools")
    ap.add_argument("--mingw", action="store_true", help="usar MinGW64 (Nuitka lo descarga si falta)")
    ap.add_argument("--asumir-si", action="store_true",
                    help="aceptar sin preguntar las descargas que Nuitka necesite (MinGW, etc.)")
    ap.add_argument("--winsdk-completo", action="store_true",
                    help="incluir TODO winsdk (si falta un módulo al ejecutar; compila mucho más lento)")
    ap.add_argument("--limpiar", action="store_true", help="borra dist-nuitka antes de compilar")
    ap.add_argument("--dry-run", action="store_true", help="solo muestra el comando")
    ap.add_argument("--sin-autotest", action="store_true",
                    help="no ejecutar la autoprueba del .exe al terminar")
    ap.add_argument("--extra", action="append", default=[], metavar="OPCION",
                    help="opción adicional para Nuitka (se puede repetir), p. ej. --extra=--nofollow-import-to=numpy")
    args = ap.parse_args(argv)

    cmd = build_command(onefile=args.onefile, console=args.console or args.depurar, jobs=args.jobs, lto=args.lto,
                        msvc=args.msvc, mingw=args.mingw, asumir_si=args.asumir_si,
                        winsdk_completo=args.winsdk_completo)
    cmd[-1:-1] = args.extra          # antes de main.py
    if args.dry_run:
        print(" \\\n  ".join(cmd))
        return 0
    problems = check_environment()
    if problems:
        print("No se puede compilar todavía:\n")
        for p in problems:
            print(" -", p)
        return 2
    out = ROOT / "dist-nuitka"
    if args.limpiar and out.exists():
        shutil.rmtree(out)
    print(f"Compilando {V.APP_NAME} {V.APP_VERSION} con Nuitka ({'un solo archivo' if args.onefile else 'carpeta'})...")
    print("La primera compilación tarda bastante; las siguientes son mucho más rápidas.\n")
    code = subprocess.call(cmd, cwd=str(ROOT))
    if code != 0:
        print(f"\nNuitka terminó con error (código {code}).")
        return code
    if not args.onefile:
        built = out / "main.dist"
        final = out / V.APP_NAME
        if built.exists():
            if final.exists():
                shutil.rmtree(final)
            built.rename(final)
        exe = final / (V.APP_NAME + (".exe" if sys.platform == "win32" else ""))
        flag_dir = final
        print(f"\nListo: {final}\nComprime esa carpeta en un .zip para repartirla.")
    else:
        exe = out / (V.APP_NAME + (".exe" if sys.platform == "win32" else ""))
        flag_dir = out
        print(f"\nListo: {out}")
    if args.depurar:
        (flag_dir / "depurar.flag").write_text("Este archivo activa el modo depuración (terminal + debug.log). "
                                               "Bórralo para volver al modo normal.\n", encoding="utf-8")
        print("\nModo depuración: al abrir el .exe aparecerá una terminal y todo se guardará en\n"
              "  %LOCALAPPDATA%\\YefriPlayer\\debug.log\n"
              "Para volver al modo normal, borra depurar.flag (y compila sin --depurar).")
    if args.sin_autotest or not exe.exists():
        return 0
    return autotest(exe)


def autotest(exe: Path) -> int:
    """Ejecuta `<exe> --autotest` y muestra el informe: así se sabe AL MOMENTO si el
    .exe trae todo (un .exe sin consola que falla no dice nada)."""
    report = exe.parent / "autotest.txt"
    if report.exists():
        report.unlink()
    print(f"\nComprobando el ejecutable ({exe.name} --autotest)...")
    try:
        code = subprocess.call([str(exe), "--autotest", str(report)], timeout=180)
    except subprocess.TimeoutExpired:
        print("La autoprueba no terminó en 3 minutos: el ejecutable se cuelga al arrancar.")
        return 3
    except OSError as exc:
        print(f"No se pudo ejecutar el .exe: {exc}")
        return 3
    if report.exists():
        text = report.read_text(encoding="utf-8", errors="replace")
        bad = [ln for ln in text.splitlines() if ln.startswith(("FALLA", "AVISO", "RESULTADO", "       ->"))]
        print("\n".join(bad) or text)
        print(f"\nInforme completo: {report}")
    else:
        print(f"El .exe terminó con código {code} y NO escribió informe: arranca mal. "
              f"Mira startup-error.log en la carpeta de datos de YefriPlayer, o compila con --depurar (terminal + debug.log).")
    return code


if __name__ == "__main__":
    sys.exit(main())
