"""Iniciar WNP Player junto con Windows.

Usa la clave de registro por-usuario `HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Run` (no pide permisos de administrador y es la misma que
usan casi todos los programas). Funciona igual con el `.exe` empaquetado
(PyInstaller) que ejecutando `python main.py`:

- `.exe`: el comando es la ruta del propio ejecutable (`sys.executable`).
  Como se vuelve a escribir en cada arranque (`sync`), si el usuario mueve el
  `.exe` a otra carpeta la entrada se corrige sola en la siguiente ejecución.
- Desde código fuente: `pythonw.exe main.py` (sin ventana de consola).

Si el usuario lo desactiva desde el Administrador de tareas (pestaña
"Inicio"), Windows lo recuerda en otra clave (StartupApproved) y se respeta:
aquí solo se gestiona la entrada, no se pelea con esa decisión.

Fuera de Windows no hace nada. Todo acceso al registro está en funciones
pequeñas que usan `_winreg()` para poder sustituirlo en las pruebas.
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WNPPlayer"


def _winreg():
    """El módulo `winreg` (solo existe en Windows) o None."""
    if sys.platform != "win32":
        return None
    import winreg
    return winreg


def is_supported() -> bool:
    return _winreg() is not None


def launch_command() -> str:
    """Comando que Windows ejecutará al iniciar sesión."""
    if getattr(sys, "frozen", False):          # .exe de PyInstaller
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    interpreter = pyw if pyw.exists() else exe
    script = Path(__file__).resolve().with_name("main.py")
    return f'"{interpreter}" "{script}"'


def registered_command() -> str | None:
    """Lo que hay registrado ahora mismo (None si no hay entrada)."""
    reg = _winreg()
    if reg is None:
        return None
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _kind = reg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    return registered_command() is not None


def set_enabled(enabled: bool) -> bool:
    """Crea/actualiza o elimina la entrada. Devuelve True si el registro
    quedó como se pidió (False si no hay Windows o el registro falló)."""
    reg = _winreg()
    if reg is None:
        return False
    try:
        if enabled:
            command = launch_command()
            if registered_command() == command:
                return True
            with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command)
            return True
        if registered_command() is None:
            return True
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            reg.DeleteValue(key, VALUE_NAME)
        return True
    except OSError:
        return False


def sync(enabled: bool) -> bool:
    """Deja el registro igual que la configuración. Se llama en cada arranque
    y al guardar Configuración."""
    return set_enabled(bool(enabled))
