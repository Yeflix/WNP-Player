#!/usr/bin/env python
"""Construye el instalador de Windows de YefriPlayer (YefriPlayer-<versión>-Setup.exe).

Uso, desde la carpeta del proyecto y con el entorno virtual activado (Windows):

    python tools/construir_instalador.py                   # compila con Nuitka y crea el instalador
    python tools/construir_instalador.py --pyinstaller     # compila con PyInstaller (más rápido de compilar)
    python tools/construir_instalador.py --sin-compilar    # reutiliza la carpeta ya compilada
    python tools/construir_instalador.py --dry-run         # solo muestra lo que haría

(O doble clic en Construir-Instalador.bat, en la raíz del proyecto.)

Pasos:
  1. Compila el programa (tools/compilar_nuitka.py o main.spec), que al terminar
     ejecuta `YefriPlayer.exe --autotest` y avisa de lo que falte.
  2. Llama a Inno Setup (ISCC.exe) con installer/YefriPlayer.iss, pasándole la
     versión de version.py y la carpeta compilada.
  3. Deja el resultado en dist-installer/ y muestra su SHA-256.

Requisitos (una sola vez), además de los de compilar (ver compilar_nuitka.py):
    Inno Setup 6.3 o posterior:  winget install --id JRSoftware.InnoSetup -e
    (o https://jrsoftware.org/isdl.php). Si está en otro sitio: --iscc RUTA o la
    variable de entorno ISCC.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import version as V  # noqa: E402

ISS = ROOT / "installer" / "YefriPlayer.iss"
OUTPUT_DIR = ROOT / "dist-installer"
NUITKA_DIR = ROOT / "dist-nuitka" / V.APP_NAME
PYINSTALLER_DIR = ROOT / "dist" / V.APP_NAME


def iscc_candidates(env: dict | None = None) -> list[Path]:
    """Sitios donde suele estar ISCC.exe (en orden de preferencia)."""
    env = os.environ if env is None else env
    out: list[Path] = []
    if env.get("ISCC"):
        out.append(Path(env["ISCC"]))
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        out.append(Path(found))
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = env.get(var)
        if not base:
            continue
        sub = Path(base) / "Programs" if var == "LOCALAPPDATA" else Path(base)   # winget por usuario
        for name in ("Inno Setup 6", "Inno Setup 7"):
            out.append(sub / name / "ISCC.exe")
    return out


def find_iscc(explicit: str | None = None, env: dict | None = None) -> Path | None:
    cands = [Path(explicit)] if explicit else iscc_candidates(env)
    return next((p for p in cands if p.is_file()), None)


def build_iscc_command(iscc: Path, source_dir: Path, output_dir: Path = OUTPUT_DIR,
                       app_version: str = V.APP_VERSION, iss: Path = ISS) -> list[str]:
    """Línea de comandos de ISCC (función pura, se comprueba en las pruebas)."""
    return [
        str(iscc), "/Qp",                       # salida breve con progreso
        f"/DAppVersion={app_version}",
        f"/DSourceDir={source_dir}",
        f"/DOutputDir={output_dir}",
        str(iss),
    ]


def installer_path(output_dir: Path = OUTPUT_DIR, app_version: str = V.APP_VERSION) -> Path:
    return output_dir / f"{V.APP_NAME}-{app_version}-Setup.exe"


def compiled_dir(pyinstaller: bool) -> Path:
    return PYINSTALLER_DIR if pyinstaller else NUITKA_DIR


def check_compiled(folder: Path) -> list[str]:
    """Problemas de la carpeta compilada que impedirían un instalador válido."""
    problems = []
    exe = folder / f"{V.APP_NAME}.exe"
    if not exe.is_file():
        problems.append(f"No existe {exe}. Compila primero (o quita --sin-compilar).")
    for leftover in ("depurar.flag",):
        if (folder / leftover).exists():
            problems.append(f"{folder / leftover} activa el modo depuración: compila sin --depurar "
                            "(el instalador lo excluye igualmente, pero el .exe sería de depuración).")
    return problems


def compile_app(pyinstaller: bool, extra: list[str]) -> int:
    if pyinstaller:
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "main.spec")]
        print("Compilando con PyInstaller...\n  " + " ".join(cmd))
        code = subprocess.call(cmd, cwd=str(ROOT))
        if code == 0:
            import compilar_nuitka as CN
            exe = PYINSTALLER_DIR / f"{V.APP_NAME}.exe"
            if exe.exists():
                code = CN.autotest(exe)
        return code
    import compilar_nuitka as CN
    return CN.main(["--limpiar", *extra])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Construye el instalador de YefriPlayer (Inno Setup).")
    ap.add_argument("--pyinstaller", action="store_true", help="compilar con PyInstaller en vez de Nuitka")
    ap.add_argument("--sin-compilar", action="store_true", help="usar la carpeta ya compilada")
    ap.add_argument("--iscc", help="ruta de ISCC.exe si no se encuentra solo")
    ap.add_argument("--dry-run", action="store_true", help="solo muestra lo que haría")
    ap.add_argument("--nuitka", action="append", default=[], metavar="OPCION",
                    help="opción para compilar_nuitka.py (se puede repetir), p. ej. --nuitka=--mingw")
    args = ap.parse_args(argv)

    folder = compiled_dir(args.pyinstaller)
    iscc = find_iscc(args.iscc)

    if args.dry_run:
        print(f"Versión: {V.APP_VERSION}\nCarpeta compilada: {folder}")
        print("ISCC:", iscc or "NO ENCONTRADO")
        print(" ".join(build_iscc_command(iscc or Path("ISCC.exe"), folder)))
        print("Instalador:", installer_path())
        return 0

    if sys.platform != "win32":
        print("El instalador solo se puede construir en Windows.")
        return 2
    if iscc is None:
        print("No encuentro Inno Setup (ISCC.exe). Instálalo con:\n"
              "  winget install --id JRSoftware.InnoSetup -e\n"
              "o desde https://jrsoftware.org/isdl.php (versión 6.3 o posterior),\n"
              "y vuelve a ejecutar esto (o indica la ruta con --iscc).")
        return 2

    if not args.sin_compilar:
        code = compile_app(args.pyinstaller, args.nuitka)
        if code != 0:
            print(f"\nLa compilación o su autoprueba falló (código {code}): no se crea el instalador.")
            return code

    problems = check_compiled(folder)
    if any("No existe" in p for p in problems):
        print("\n".join(problems))
        return 2
    for p in problems:
        print("Aviso:", p)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = build_iscc_command(iscc, folder)
    print("\nCreando el instalador con Inno Setup...\n  " + " ".join(cmd))
    code = subprocess.call(cmd, cwd=str(ISS.parent))
    if code != 0:
        print(f"\nInno Setup terminó con error (código {code}).")
        return code
    out = installer_path()
    if not out.is_file():
        print(f"\nInno Setup terminó bien pero no encuentro {out}.")
        return 3
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"\nListo: {out}  ({size_mb:.1f} MB)\nSHA-256: {sha256(out)}")
    print("\nInstalación silenciosa (por ejemplo, para varios equipos):\n"
          f"  {out.name} /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER\n"
          "  (añade /TASKS=\"autofix\" para instalar también Spicetify AutoFix)")
    print(f"\nPara publicarla: sube {out.name} a la carpeta de Google Drive (sin renombrarlo) y crea\n"
          f"en GitHub la release v{V.APP_VERSION} con el enlace y el SHA-256 en sus notas, para que las\n"
          "copias instaladas avisen. Paso a paso en docs/PUBLICAR.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
