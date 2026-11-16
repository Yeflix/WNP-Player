"""Botones Anterior / Reproducir-Pausar / Siguiente en la miniatura de la barra
de tareas (la vista previa que aparece al pasar el ratón por el icono), como
el Reproductor multimedia de Windows.

Solo tiene sentido si la ventana completa tiene entrada en la barra de tareas,
cosa que YefriPlayer no hace por defecto (vive en la bandeja: sus ventanas son
de tipo Qt.Tool). Por eso va detrás de la opción «Mostrar en la barra de
tareas» (config.taskbar_button), que se aplica al reiniciar.

Funcionamiento (Windows, ITaskbarList3):
- Windows avisa con el mensaje registrado "TaskbarButtonCreated" cuando el
  botón de la ventana ya existe en la barra; solo entonces se pueden añadir
  los botones (ThumbBarAddButtons, una vez por botón creado).
- Al pulsar uno, Windows manda WM_COMMAND con HIWORD(wParam) = THBN_CLICKED y
  LOWORD(wParam) = id del botón. Se capturan con un filtro de eventos nativos
  (igual que las teclas globales de hotkeys.py) y se emite `actionTriggered`
  con los mismos nombres que usan las teclas: "previous", "play_pause", "next".
- Los iconos se dibujan con los mismos trazados que el resto de la app
  (icons.py), en blanco, al tamaño de icono pequeño del sistema.
"""
from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QObject, pyqtSignal

import wincom
from diag import soft
from wincom import GUID, failed, release, vcall

IS_WINDOWS = sys.platform == "win32"

CLSID_TaskbarList = GUID.from_str("56FDF344-FD6D-11D0-958A-006097C9A090")
IID_ITaskbarList3 = GUID.from_str("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")
WM_COMMAND = 0x0111
THBN_CLICKED = 0x1800
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
THBF_ENABLED, THBF_DISABLED = 0x0, 0x1

# id del botón → acción (mismos nombres que las teclas globales)
BUTTONS = ((1, "previous"), (2, "play_pause"), (3, "next"))
_ACTIONS = dict(BUTTONS)


class THUMBBUTTON(ctypes.Structure):
    _fields_ = [("dwMask", ctypes.c_uint32), ("iId", ctypes.c_uint32), ("iBitmap", ctypes.c_uint32),
                ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 260), ("dwFlags", ctypes.c_uint32)]


def action_for_command(wparam: int) -> str | None:
    """Acción de un WM_COMMAND de la barra de tareas, o None si no es nuestro."""
    wparam = int(wparam) & 0xFFFFFFFF
    if (wparam >> 16) & 0xFFFF != THBN_CLICKED:
        return None
    return _ACTIONS.get(wparam & 0xFFFF)


def _icon_image(name: str, size: int):
    """QImage ARGB32 con el icono `name` de icons.py en blanco."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage, QPainter, QTransform
    import icons
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / 24.0
    path = QTransform().scale(scale, scale).map(icons.get_icon_path(name))
    p.fillPath(path, QColor(255, 255, 255))
    p.end()
    return img


def _hicon_from_image(img) -> int:
    """HICON (con transparencia) a partir de una QImage ARGB32. 0 si falla."""
    w, h = img.width(), img.height()

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", ctypes.c_int), ("xHotspot", ctypes.c_uint32), ("yHotspot", ctypes.c_uint32),
                    ("hbmMask", ctypes.c_void_p), ("hbmColor", ctypes.c_void_p)]

    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint32)
    gdi32.CreateBitmap.restype = ctypes.c_void_p
    gdi32.CreateBitmap.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
    user32.CreateIconIndirect.restype = ctypes.c_void_p
    user32.CreateIconIndirect.argtypes = (ctypes.POINTER(ICONINFO),)

    bih = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,  # de arriba abajo
                           biPlanes=1, biBitCount=32, biCompression=0)
    bits = ctypes.c_void_p()
    color = gdi32.CreateDIBSection(None, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
    if not color or not bits.value:
        return 0
    mask = gdi32.CreateBitmap(w, h, 1, 1, None)
    try:
        # ARGB32 de Qt en memoria (little-endian) = BGRA, lo mismo que un DIB de 32 bits.
        data = img.constBits().asstring(img.sizeInBytes())
        stride = img.bytesPerLine()
        for y in range(h):
            ctypes.memmove(bits.value + y * w * 4, data[y * stride:y * stride + w * 4], w * 4)
        info = ICONINFO(fIcon=1, hbmMask=mask, hbmColor=color)
        return user32.CreateIconIndirect(ctypes.byref(info)) or 0
    finally:
        gdi32.DeleteObject(color)
        if mask:
            gdi32.DeleteObject(mask)


class ThumbBar(QObject):
    """Botones de control en la miniatura de la barra de tareas de `window`."""

    actionTriggered = pyqtSignal(str)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._taskbar = None
        self._added_for_hwnd = 0
        self._icons: dict[str, int] = {}
        self._playing = False
        self._has_media = False
        self._tooltip = ""
        self._filter = None
        self._msg_created = 0

    # ------------------------------------------------------------- instalación
    def install(self, app) -> bool:
        if not IS_WINDOWS:
            return False
        from PyQt6.QtCore import QAbstractNativeEventFilter
        import ctypes.wintypes as wintypes
        user32 = ctypes.windll.user32
        user32.RegisterWindowMessageW.restype = ctypes.c_uint32
        self._msg_created = user32.RegisterWindowMessageW("TaskbarButtonCreated")
        bar = self

        class _Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if event_type == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == bar._msg_created or msg.message == WM_COMMAND:
                        bar._on_native(int(msg.hWnd or 0), msg.message, msg.wParam)
                return False, 0

        self._filter = _Filter()
        app.installNativeEventFilter(self._filter)
        return True

    def _hwnd(self) -> int:
        try:
            return int(self._window.winId())
        except Exception:
            return 0

    def _on_native(self, hwnd: int, message: int, wparam) -> None:
        if not hwnd or hwnd != self._hwnd():
            return
        if message == self._msg_created:
            with soft("taskbar_buttons.add"):
                self._add_buttons(hwnd)
        elif message == WM_COMMAND:
            action = action_for_command(wparam)
            if action:
                self.actionTriggered.emit(action)

    # ------------------------------------------------------------------ COM
    def _bar(self):
        if self._taskbar is None:
            wincom.co_initialize()
            bar = wincom.co_create_instance(CLSID_TaskbarList, IID_ITaskbarList3)
            if failed(vcall(bar, 3)):                       # HrInit
                release(bar)
                return None
            self._taskbar = bar
        return self._taskbar

    def _icon(self, name: str) -> int:
        if name not in self._icons:
            size = max(16, ctypes.windll.user32.GetSystemMetrics(49))   # SM_CXSMICON
            self._icons[name] = _hicon_from_image(_icon_image(name, size))
        return self._icons[name]

    def _buttons(self):
        arr = (THUMBBUTTON * 3)()
        play_icon, play_tip = ("pause", "Pausar") if self._playing else ("play", "Reproducir")
        specs = ((1, "prev", "Anterior"), (2, play_icon, play_tip), (3, "next", "Siguiente"))
        for i, (bid, icon, tip) in enumerate(specs):
            b = arr[i]
            b.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
            b.iId = bid
            b.hIcon = self._icon(icon)
            b.szTip = tip
            b.dwFlags = THBF_ENABLED if self._has_media else THBF_DISABLED
        return arr

    def _add_buttons(self, hwnd: int) -> None:
        bar = self._bar()
        if bar is None:
            return
        arr = self._buttons()
        hr = vcall(bar, 15, (ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(THUMBBUTTON)),
                   hwnd, 3, arr)
        if not failed(hr):
            self._added_for_hwnd = hwnd
            self._push_tooltip(hwnd)

    def _push_tooltip(self, hwnd: int) -> None:
        bar = self._bar()
        if bar is not None:
            vcall(bar, 19, (ctypes.c_void_p, ctypes.c_wchar_p), hwnd, self._tooltip or "YefriPlayer")

    # --------------------------------------------------------------- estado
    def set_state(self, playing: bool, has_media: bool, tooltip: str = "") -> None:
        """Lo llama el controlador con cada estado; solo toca Windows si cambió algo."""
        changed = (bool(playing), bool(has_media)) != (self._playing, self._has_media)
        tip_changed = tooltip != self._tooltip
        self._playing, self._has_media, self._tooltip = bool(playing), bool(has_media), tooltip
        hwnd = self._added_for_hwnd
        if not hwnd or hwnd != self._hwnd():
            return
        with soft("taskbar_buttons.update"):
            if changed:
                bar = self._bar()
                if bar is not None:
                    vcall(bar, 16, (ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(THUMBBUTTON)),
                          hwnd, 3, self._buttons())
            if tip_changed:
                self._push_tooltip(hwnd)

    def close(self) -> None:
        if not IS_WINDOWS:
            return
        with soft("taskbar_buttons.close"):
            for handle in self._icons.values():
                if handle:
                    ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(handle))
            self._icons.clear()
            release(self._taskbar)
            self._taskbar = None
