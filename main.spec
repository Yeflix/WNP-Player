# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all

# Recolectar automáticamente todos los sub-módulos y datos necesarios de PyQt6
pyqt6_submodules = collect_submodules('PyQt6')
pyqt6_data = collect_data_files('PyQt6')

# --- Refuerzo de empaquetado para la detección de reproducción (además del
# parche de pywnp_patch.py): `pywnp` monta su servidor WebSocket sobre
# `aiohttp`, que trae varias extensiones compiladas (p. ej.
# `aiohttp._websocket.mask`, `aiohttp._websocket.reader_c`) y dependencias
# propias (`aiohappyeyeballs`, `aiosignal`, `frozenlist`, `multidict`,
# `propcache`, `yarl`) organizadas en paquetes/sub-paquetes que PyInstaller
# no siempre descubre solo con su análisis estático de imports. Con solo
# los hiddenimports de PyQt6 (como estaba antes), el .exe podía arrancar
# igual (PyQt6 sí se empaqueta bien) pero el servidor WebSocket con el que
# habla la extensión del navegador fallar en tiempo de ejecución al
# faltarle alguna de esas piezas — silenciosamente, porque backend.py
# atrapa la excepción y solo la muestra como aviso genérico. La detección
# de reproductores nativos de Windows (winsdk/SMTC) no depende de aiohttp
# para nada, por eso esa parte puede seguir funcionando mientras los
# navegadores dejan de detectarse — el mismo síntoma reportado.
#
# collect_all() trae hiddenimports + datos + binarios (incluye los .so/.pyd
# compilados) de cada paquete, así no hace falta listar cada submódulo a mano.
_extra_binaries = []
_extra_datas = []
_extra_hiddenimports = []
for _pkg in (
    'pywnp', 'aiohttp', 'aiohappyeyeballs', 'aiosignal', 'attr', 'attrs',
    'frozenlist', 'multidict', 'propcache', 'yarl',
    # Solo existe en Windows (ver requirements.txt), pero es igual de
    # necesario para que la detección de apps de escritorio (Spotify, etc.)
    # no sufra el mismo tipo de falla silenciosa: winsdk también expone
    # sus namespaces vía importación dinámica, que PyInstaller tampoco
    # descubre solo. collect_all() no falla si el paquete no está
    # instalado en la plataforma actual — simplemente no aporta nada.
    'winsdk',
):
    try:
        _b, _d, _h = collect_all(_pkg)
        _extra_binaries += _b
        _extra_datas += _d
        _extra_hiddenimports += _h
    except Exception:
        pass  # paquete no instalado en esta plataforma (p. ej. winsdk fuera de Windows): se ignora

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_extra_binaries,
    datas=pyqt6_data + _extra_datas,  # Añade los recursos necesarios de PyQt6 y de red/pywnp aquí
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip', # Esencial para la gestión de memoria de PyQt6
        # "Iniciar con Windows": autostart.py se importa dentro de funciones y
        # usa winreg (solo Windows); se declaran para que el .exe los incluya.
        'autostart',
        'winreg',
    ] + pyqt6_submodules + _extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,     # <-- ¡RESTAURADO! Es obligatorio para que arranque el script principal
    a.binaries,    # <-- Añadido para empaquetar binarios en el exe
    a.datas,       # <-- Añadido para empaquetar datos en el exe
    [],
    exclude_binaries=False,  # <-- Cambiado a False
    name='Reproductor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Cambia a False si tu app no usa consola (modo ventana)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)