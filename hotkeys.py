"""
Teclas multimedia globales, configurables por el usuario.

En vez de atarnos a las teclas físicas de multimedia (Play/Pausa/Siguiente/
Anterior) —que ni todos los teclados tienen, y que en Windows muchas
combinaciones ya están tomadas por el sistema o por otros programas—, se
deja que el usuario elija y grabe la combinación que quiera (por ejemplo
Ctrl+Alt+P) desde `HotkeyDialog`.

Se implementa con la API nativa de Windows (`RegisterHotKey` /
`UnregisterHotKey` vía `ctypes`, sin depender de `pywin32`) interceptando
el mensaje `WM_HOTKEY` con un `QAbstractNativeEventFilter`. Fuera de
Windows, `HotkeyManager.available` queda en `False` y todo se vuelve un
no-op seguro (la app sigue funcionando normal, simplemente sin esta
función).
"""
from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QObject, Qt, pyqtSignal

IS_WINDOWS = sys.platform == "win32"

# --- Constantes de la API de Windows (RegisterHotKey) ----------------------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MOD_FLAGS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_MOD_ORDER = ["ctrl", "alt", "shift", "win"]

# Teclas que tiene sentido registrar SIN ningún modificador (las teclas
# físicas dedicadas de multimedia: para eso existen). Cualquier otra tecla
# sin modificador secuestraría esa tecla en todo el sistema, así que el
# diálogo exige al menos un modificador para las demás.
BARE_ALLOWED = {"mediaplaypause", "medianext", "mediaprevious", "mediastop"}


def _build_key_map() -> dict:
    m = {
        Qt.Key.Key_Space: ("Space", 0x20),
        Qt.Key.Key_Up: ("Up", 0x26),
        Qt.Key.Key_Down: ("Down", 0x28),
        Qt.Key.Key_Left: ("Left", 0x25),
        Qt.Key.Key_Right: ("Right", 0x27),
        Qt.Key.Key_Home: ("Home", 0x24),
        Qt.Key.Key_End: ("End", 0x23),
        Qt.Key.Key_Insert: ("Insert", 0x2D),
        Qt.Key.Key_Delete: ("Delete", 0x2E),
        Qt.Key.Key_PageUp: ("PageUp", 0x21),
        Qt.Key.Key_PageDown: ("PageDown", 0x22),
        Qt.Key.Key_MediaTogglePlayPause: ("MediaPlayPause", 0xB3),
        Qt.Key.Key_MediaPlay: ("MediaPlayPause", 0xB3),
        Qt.Key.Key_MediaNext: ("MediaNext", 0xB0),
        Qt.Key.Key_MediaPrevious: ("MediaPrevious", 0xB1),
        Qt.Key.Key_MediaStop: ("MediaStop", 0xB2),
    }
    for i in range(1, 25):
        key_attr = getattr(Qt.Key, f"Key_F{i}", None)
        if key_attr is not None:
            m[key_attr] = (f"F{i}", 0x70 + i - 1)
    for c in "0123456789":
        m[getattr(Qt.Key, f"Key_{c}")] = (c, ord(c))
    for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        m[getattr(Qt.Key, f"Key_{c}")] = (c, ord(c))
    return m


_KEY_MAP = _build_key_map()
_NAME_TO_VK = {name.lower(): vk for (name, vk) in _KEY_MAP.values()}
_MODIFIER_ONLY_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
}


def capture_from_event(event) -> tuple[set, str] | None:
    """A partir de un QKeyEvent, retorna (modificadores, nombre_tecla) si es
    una combinación capturable, o None si todavía no hay una tecla "real"
    presionada (por ejemplo, el usuario solo tiene Ctrl apretado) o si la
    tecla no está soportada."""
    key = event.key()
    if key in _MODIFIER_ONLY_KEYS:
        return None
    entry = _KEY_MAP.get(key)
    if entry is None:
        return None
    display_name, _vk = entry

    mods = set()
    qmods = event.modifiers()
    if qmods & Qt.KeyboardModifier.ControlModifier:
        mods.add("ctrl")
    if qmods & Qt.KeyboardModifier.AltModifier:
        mods.add("alt")
    if qmods & Qt.KeyboardModifier.ShiftModifier:
        mods.add("shift")
    if qmods & Qt.KeyboardModifier.MetaModifier:
        mods.add("win")
    return mods, display_name


def combo_to_string(mods: set, key_name: str) -> str:
    parts = [m for m in _MOD_ORDER if m in mods]
    parts.append(key_name.lower())
    return "+".join(parts)


_DISPLAY_NAMES = {
    "mediaplaypause": "Reproducir/Pausar (tecla física)",
    "medianext": "Siguiente (tecla física)",
    "mediaprevious": "Anterior (tecla física)",
    "mediastop": "Detener (tecla física)",
}


def combo_to_display(combo: str) -> str:
    if not combo:
        return "(sin asignar)"
    parts = combo.split("+")
    key_name = parts[-1]
    if key_name in _DISPLAY_NAMES:
        mod_parts = parts[:-1]
        prefix = " + ".join("Win" if p == "win" else p.capitalize() for p in mod_parts)
        label = _DISPLAY_NAMES[key_name]
        return f"{prefix} + {label}" if prefix else label
    out = []
    for p in parts:
        out.append("Win" if p == "win" else p.upper() if len(p) <= 2 else p.capitalize())
    return " + ".join(out)


def combo_needs_modifier(combo: str) -> bool:
    """True si este combo requiere al menos un modificador para ser válido
    (todas las teclas EXCEPTO las de multimedia dedicadas)."""
    if not combo:
        return True
    key_name = combo.split("+")[-1]
    return key_name not in BARE_ALLOWED


def _parse_combo(combo: str):
    parts = [p for p in combo.lower().split("+") if p]
    mods = {p for p in parts if p in _MOD_FLAGS}
    keys = [p for p in parts if p not in _MOD_FLAGS]
    if len(keys) != 1:
        return set(), None
    return mods, _NAME_TO_VK.get(keys[0])


def _mods_to_flags(mods) -> int:
    flags = MOD_NOREPEAT
    for m in mods:
        flags |= _MOD_FLAGS.get(m, 0)
    return flags


# --- Integración con Windows -----------------------------------------------
if IS_WINDOWS:
    import ctypes.wintypes as wintypes
    from PyQt6.QtCore import QAbstractNativeEventFilter

    _user32 = ctypes.windll.user32

    def _win_register(hotkey_id: int, mods: set, vk: int) -> bool:
        return bool(_user32.RegisterHotKey(None, hotkey_id, _mods_to_flags(mods), vk))

    def _win_unregister(hotkey_id: int) -> None:
        _user32.UnregisterHotKey(None, hotkey_id)

    class _NativeFilter(QAbstractNativeEventFilter):
        def __init__(self, manager: HotkeyManager):
            super().__init__()
            self._manager = manager

        def nativeEventFilter(self, event_type, message):
            if event_type == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    self._manager._on_hotkey(msg.wParam)
            return False, 0
else:
    def _win_register(hotkey_id: int, mods: set, vk: int) -> bool:
        return False

    def _win_unregister(hotkey_id: int) -> None:
        pass

    _NativeFilter = None


class HotkeyManager(QObject):
    """Registra combinaciones globales y avisa (`triggered`) cuál acción
    corresponde cuando el usuario la presiona, sin importar qué ventana
    tenga el foco."""

    triggered = pyqtSignal(str)  # "play_pause" | "next" | "previous"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = IS_WINDOWS
        self._ids: dict[str, int] = {}
        self._next_id = 1
        self._filter = None

    def install(self, app) -> None:
        if not self.available:
            return
        self._filter = _NativeFilter(self)
        app.installNativeEventFilter(self._filter)

    def _on_hotkey(self, hotkey_id: int) -> None:
        for action, hid in self._ids.items():
            if hid == hotkey_id:
                self.triggered.emit(action)
                return

    def register(self, action: str, combo: str) -> bool:
        """Registra `combo` (p.ej. "ctrl+alt+p") para `action`, reemplazando
        lo que tuviera antes. Retorna False si el combo ya está en uso por
        Windows/otro programa, es inválido, o no estamos en Windows."""
        self.unregister(action)
        if not self.available or not combo:
            return False
        mods, vk = _parse_combo(combo)
        if vk is None:
            return False
        hotkey_id = self._next_id
        self._next_id += 1
        if _win_register(hotkey_id, mods, vk):
            self._ids[action] = hotkey_id
            return True
        return False

    def unregister(self, action: str) -> None:
        hotkey_id = self._ids.pop(action, None)
        if hotkey_id is not None:
            _win_unregister(hotkey_id)

    def unregister_all(self) -> None:
        for action in list(self._ids.keys()):
            self.unregister(action)
