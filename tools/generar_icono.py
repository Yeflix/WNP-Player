"""Genera assets/yefriplayer.ico a partir del ícono que el programa dibuja en código (app_icon.py).

Uso (desde la carpeta del proyecto):
    python tools/generar_icono.py

El .ico lleva varios tamaños (16 a 256 px) como PNG, que es lo que usa el
Explorador de Windows y la barra de tareas. Solo hace falta volver a ejecutarlo
si cambias el diseño del ícono; el resultado se guarda en el repositorio y lo
usa main.spec para el .exe.
"""
from __future__ import annotations

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png_bytes(pixmap) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return bytes(data)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, payload = b"", b""
    for size, png in images:
        w = 0 if size >= 256 else size           # 0 significa 256 en el formato ICO
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def main() -> str:
    _app = QApplication.instance() or QApplication(sys.argv)
    from app_icon import build_app_icon
    icon = build_app_icon(256)
    images = [(s, _png_bytes(icon.pixmap(s, s))) for s in SIZES]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "yefriplayer.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(build_ico(images))
    return os.path.normpath(out)


if __name__ == "__main__":
    print("Ícono generado:", main())
