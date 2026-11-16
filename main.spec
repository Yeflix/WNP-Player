# -*- mode: python ; coding: utf-8 -*-
#
# YefriPlayer: empaquetado en MODO CARPETA (onedir).
#
# Por qué carpeta y no un solo .exe:
#   - Arranque instantáneo: el .exe de un solo archivo se descomprime en una
#     carpeta temporal en CADA arranque (varios segundos, y más aún al iniciar
#     con Windows). En modo carpeta ya está todo desplegado.
#   - Menos falsos positivos de antivirus (el descompresor de un solo archivo
#     y UPX son justo lo que más alerta a Defender), y sin carpetas _MEI sobrantes
#     si el programa se cierra a la fuerza.
#
# Resultado: dist/YefriPlayer/YefriPlayer.exe (+ carpeta _internal). Se
# distribuye comprimiendo TODA la carpeta dist/YefriPlayer en un .zip.
import os
import sys

from PyInstaller.utils.hooks import collect_all

_here = os.path.abspath(SPECPATH)          # SPECPATH lo define PyInstaller
sys.path.insert(0, _here)
import version as _v                       # nombre, versión y autor (una sola fuente)

# --- Dependencias que PyInstaller no descubre solo ----------------------------
# `pywnp` monta su servidor WebSocket sobre `aiohttp`, que trae extensiones
# compiladas y dependencias propias (aiohappyeyeballs, aiosignal, frozenlist,
# multidict, propcache, yarl) en paquetes que el análisis estático no siempre ve.
# Sin ellas el .exe arranca, pero el servidor al que se conecta la extensión del
# navegador falla en silencio (el síntoma típico: los navegadores no se detectan
# aunque las apps de escritorio sí). collect_all() trae módulos + datos +
# binarios de cada paquete. `winsdk` (solo Windows) expone sus espacios de
# nombres por importación dinámica, igual de invisible para el análisis.
_extra_binaries, _extra_datas, _extra_hiddenimports = [], [], []
for _pkg in (
    'pywnp', 'aiohttp', 'aiohappyeyeballs', 'aiosignal', 'attr', 'attrs',
    'frozenlist', 'multidict', 'propcache', 'yarl', 'winsdk',
    # Visualizador de audio (audio_levels.py): captura WASAPI loopback (solo Windows).
    'pyaudiowpatch',
):
    try:
        _b, _d, _h = collect_all(_pkg)
        _extra_binaries += _b
        _extra_datas += _d
        _extra_hiddenimports += _h
    except Exception:
        pass  # no instalado en esta plataforma (p. ej. winsdk fuera de Windows)

# --- Solo los módulos de Qt que el programa usa -------------------------------
# Antes se recolectaba TODO PyQt6 (WebEngine, Multimedia, 3D, QML...): decenas de
# MB de DLL que no se usan, arranque más lento y más superficie para antivirus.
_qt_usados = [
    'PyQt6', 'PyQt6.sip', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'PyQt6.QtNetwork', 'PyQt6.QtWebSockets',
]
_qt_excluidos = [
    'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineQuick',
    'PyQt6.QtWebChannel', 'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuickWidgets',
    'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'PyQt6.Qt3DCore',
    'PyQt6.QtSql', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtBluetooth',
    'PyQt6.QtNfc', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort', 'PyQt6.QtDesigner',
    'PyQt6.QtHelp', 'PyQt6.QtTest', 'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets',
    'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtPositioning',
    'PyQt6.QtRemoteObjects', 'PyQt6.QtDBus', 'PyQt6.QtXml', 'PyQt6.QtStateMachine',
    'tkinter', 'unittest',
]

a = Analysis(
    ['main.py'],
    pathex=[_here],
    binaries=_extra_binaries,
    datas=_extra_datas,
    hiddenimports=_qt_usados + [
        # autostart.py se importa dentro de funciones y usa winreg (solo Windows).
        'autostart', 'winreg',
        # Visualizador de audio: se declaran para que SIEMPRE entren en el paquete.
        'audio_levels', 'numpy', 'pyaudiowpatch',
    ] + _extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_qt_excluidos,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# --- Datos de versión del .exe (Propiedades > Detalles) -----------------------
# Solo tiene sentido (y solo se puede importar) en Windows.
_version_file = None
if sys.platform == 'win32':
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
        VarStruct, VSVersionInfo,
    )
    _partes = [int(x) for x in _v.APP_VERSION.split('.')[:3]] + [0] * 3
    _ver4 = tuple(_partes[:3]) + (0,)
    _ver_txt = '.'.join(str(n) for n in _ver4)
    _version_info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=_ver4, prodvers=_ver4, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable('040904B0', [
                StringStruct('CompanyName', _v.AUTHOR),
                StringStruct('FileDescription', f'{_v.APP_NAME} - {_v.APP_TAGLINE}'),
                StringStruct('FileVersion', _ver_txt),
                StringStruct('InternalName', _v.APP_NAME),
                StringStruct('LegalCopyright', f'Copyright (C) 2026 {_v.AUTHOR}. GPL-3.0'),
                StringStruct('OriginalFilename', f'{_v.APP_NAME}.exe'),
                StringStruct('ProductName', _v.APP_NAME),
                StringStruct('ProductVersion', _v.APP_VERSION),
            ])]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])]),
        ],
    )
    os.makedirs(os.path.join(_here, 'build'), exist_ok=True)
    _version_file = os.path.join(_here, 'build', 'version_info.txt')
    with open(_version_file, 'w', encoding='utf-8') as _f:
        _f.write(str(_version_info))

_icono = os.path.join(_here, 'assets', 'yefriplayer.ico')   # tools/generar_icono.py

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # modo carpeta: los binarios van en COLLECT
    name=_v.APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX no ayuda al arranque y dispara falsos positivos
    console=False,               # aplicación de ventana, sin consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icono if (sys.platform == 'win32' and os.path.exists(_icono)) else None,
    version=_version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=_v.APP_NAME,
)
