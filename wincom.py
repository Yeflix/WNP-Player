"""Ayudas mínimas para llamar a interfaces COM de Windows con `ctypes`.

Se usan para el volumen por aplicación (app_volume.py), los botones de la
miniatura de la barra de tareas (taskbar_buttons.py) y la captura de audio de
un solo proceso (process_loopback.py). No añade dependencias: `comtypes` o
`pycaw` harían lo mismo, pero son más paquetes que empaquetar con Nuitka.

Una interfaz COM es un puntero a un puntero a su tabla de funciones (vtable).
`vcall(obj, i, ...)` llama a la función número `i` de esa tabla; los números
salen del orden de los métodos en los .h del SDK de Windows (los tres primeros
son siempre QueryInterface, AddRef y Release).

Fuera de Windows este módulo se puede importar (las pruebas lo hacen), pero
cualquier llamada real falla con OSError.
"""
from __future__ import annotations

import contextlib
import ctypes
import sys
import uuid

IS_WINDOWS = sys.platform == "win32"
HRESULT = ctypes.c_long
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = -2147417850       # 0x80010106: COM ya iniciado en otro modo (vale igual)
CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
COINIT_MULTITHREADED = 0x0

_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)   # CFUNCTYPE solo para importar fuera de Windows


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, text: str) -> GUID:
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)

    def __str__(self) -> str:
        return str(uuid.UUID(bytes_le=bytes(self)))


class ComError(OSError):
    def __init__(self, where: str, hr: int):
        super().__init__(f"{where} falló (HRESULT 0x{hr & 0xFFFFFFFF:08X})")
        self.hr = hr


def failed(hr: int) -> bool:
    return hr < 0


def check(hr: int, where: str) -> int:
    if hr < 0:
        raise ComError(where, hr)
    return hr


def vcall(obj, index: int, argtypes=(), *args, restype=HRESULT):
    """Llama al método `index` de la vtable del objeto COM `obj` (entero o c_void_p)."""
    if not obj:
        raise ComError(f"vcall({index}) sobre puntero nulo", -1)
    address = obj.value if isinstance(obj, ctypes.c_void_p) else int(obj)
    vtbl = ctypes.cast(address, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = _FUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(address, *args)


def release(obj) -> None:
    """IUnknown::Release (índice 2). Acepta None/0 sin hacer nada."""
    if obj is None:
        return
    address = obj.value if isinstance(obj, ctypes.c_void_p) else obj
    if address:
        with contextlib.suppress(OSError):
            vcall(address, 2, (), restype=ctypes.c_ulong)


def query_interface(obj, iid: GUID):
    out = ctypes.c_void_p()
    hr = vcall(obj, 0, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)),
               ctypes.byref(iid), ctypes.byref(out))
    return out if not failed(hr) and out.value else None


_initialized_threads: set[int] = set()


def co_initialize(apartment: int = COINIT_APARTMENTTHREADED) -> None:
    """Inicia COM en el hilo actual una sola vez (el hilo de la interfaz ya lo
    tiene iniciado por Qt: entonces devuelve S_FALSE o RPC_E_CHANGED_MODE, y
    ambos valen para seguir)."""
    import threading
    tid = threading.get_ident()
    if tid in _initialized_threads:
        return
    hr = ctypes.windll.ole32.CoInitializeEx(None, apartment)
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise ComError("CoInitializeEx", hr)
    _initialized_threads.add(tid)


def co_create_instance(clsid: GUID, iid: GUID):
    out = ctypes.c_void_p()
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.argtypes = (ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
    ole32.CoCreateInstance.restype = HRESULT
    check(ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid),
                                 ctypes.byref(out)), "CoCreateInstance")
    return out


def process_image_name(pid: int) -> str:
    """Nombre del ejecutable de un proceso ('spotify.exe', en minúsculas) o ''."""
    if not pid:
        return ""
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    k32.QueryFullProcessImageNameW.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                                               ctypes.POINTER(ctypes.c_uint32))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = ctypes.c_uint32(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    finally:
        k32.CloseHandle(handle)


def list_processes() -> list[tuple[int, int, str]]:
    """[(pid, pid_padre, 'nombre.exe' en minúsculas)] de todos los procesos
    (instantánea de Toolhelp32; no necesita permisos especiales)."""
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                    ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                    ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
    k32.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
    k32.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W))
    k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return []
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile.lower()))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out
