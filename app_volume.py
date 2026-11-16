"""Volumen por aplicación (el del «Mezclador de volumen» de Windows).

Las apps de escritorio (Spotify, VLC, foobar2000...) llegan por las sesiones
multimedia de Windows (SMTC), que no tienen volumen: por eso el control estaba
desactivado con ellas. Pero Windows sí deja leer y cambiar el volumen de cada
aplicación (Core Audio: IAudioSessionManager2 → ISimpleAudioVolume). Es el
mismo nivel que se ve en Configuración → Sonido → Mezclador de volumen: NO
mueve la barra de volumen interna de Spotify, sino cuánto suena Spotify en el
equipo; para quien escucha, el efecto es el mismo.

Se recorren todos los dispositivos de salida activos (Spotify puede sonar por
unos auriculares que no son la salida predeterminada) y se actúa sobre las
sesiones cuyo proceso coincide con el reproductor.

Fuera de Windows `available()` es False y nada se usa.
"""
from __future__ import annotations

import ctypes
import time

import wincom
from wincom import GUID, failed, release, vcall

CLSID_MMDeviceEnumerator = GUID.from_str("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID.from_str("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioSessionManager2 = GUID.from_str("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID.from_str("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_ISimpleAudioVolume = GUID.from_str("87CE5498-68D6-44E5-9215-6DA47EF883D8")
E_RENDER = 0
DEVICE_STATE_ACTIVE = 0x1

# Nombre del reproductor (el que muestra la app, ver pywnp_patch._KNOWN_AUMID_NAMES)
# → ejecutables posibles. Para los demás se prueba «<nombre>.exe».
_EXE_NAMES = {
    "spotify": ("spotify.exe",),
    "vlc": ("vlc.exe",),
    "foobar2000": ("foobar2000.exe",),
    "musicbee": ("musicbee.exe",),
    "winamp": ("winamp.exe",),
    "aimp": ("aimp.exe",),
    "itunes": ("itunes.exe",),
    "apple music": ("applemusic.exe", "music.exe"),
    "tidal": ("tidal.exe",),
    "deezer": ("deezer.exe",),
    "groove music": ("music.ui.exe",),
    "windows media player": ("microsoft.media.player.exe", "wmplayer.exe"),
    "telegram": ("telegram.exe",),
    "youtube music": ("youtube music.exe", "youtube-music.exe"),
}


def exe_names_for(player_name: str) -> tuple[str, ...]:
    key = (player_name or "").strip().lower()
    if not key:
        return ()
    if key in _EXE_NAMES:
        return _EXE_NAMES[key]
    return (key.replace(" ", "") + ".exe",)


def available() -> bool:
    return wincom.IS_WINDOWS


class AppVolume:
    """Lee y cambia el volumen de las sesiones de audio de unos ejecutables.
    Llamar siempre desde el MISMO hilo (el de la interfaz)."""

    def __init__(self):
        self._enum = None
        self._names_cache: dict[int, tuple[str, float]] = {}   # pid → (exe, cuándo se miró)

    def _enumerator(self):
        if self._enum is None:
            wincom.co_initialize()
            self._enum = wincom.co_create_instance(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
        return self._enum

    def close(self):
        release(self._enum)
        self._enum = None

    def _exe_of(self, pid: int) -> str:
        now = time.monotonic()
        hit = self._names_cache.get(pid)
        if hit and now - hit[1] < 60:
            return hit[0]
        name = wincom.process_image_name(pid)
        if len(self._names_cache) > 256:
            self._names_cache.clear()
        self._names_cache[pid] = (name, now)
        return name

    def _volumes_for(self, exe_names: tuple[str, ...]) -> list:
        """ISimpleAudioVolume (c_void_p, con referencia propia: hay que liberarlos)
        de todas las sesiones de esos ejecutables, en todas las salidas activas."""
        wanted = {n.lower() for n in exe_names}
        result = []
        enum = self._enumerator()
        coll = ctypes.c_void_p()
        if failed(vcall(enum, 3, (ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                        E_RENDER, DEVICE_STATE_ACTIVE, ctypes.byref(coll))):
            return result
        try:
            count = ctypes.c_uint32()
            vcall(coll, 3, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(count))
            for i in range(count.value):
                device = ctypes.c_void_p()
                if failed(vcall(coll, 4, (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                                i, ctypes.byref(device))):
                    continue
                try:
                    result += self._device_volumes(device, wanted)
                finally:
                    release(device)
        finally:
            release(coll)
        return result

    def sessions(self) -> list[tuple[int, str, bool]]:
        """[(pid, 'exe', activa)] de todas las sesiones de audio de las salidas
        activas. «Activa» = está sonando ahora (AudioSessionStateActive). Lo usa el
        visualizador para saber qué proceso escuchar (process_loopback.py)."""
        found: list[tuple[int, str, bool]] = []
        enum = self._enumerator()
        coll = ctypes.c_void_p()
        if failed(vcall(enum, 3, (ctypes.c_int, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                        E_RENDER, DEVICE_STATE_ACTIVE, ctypes.byref(coll))):
            return found
        try:
            count = ctypes.c_uint32()
            vcall(coll, 3, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(count))
            for i in range(count.value):
                device = ctypes.c_void_p()
                if failed(vcall(coll, 4, (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                                i, ctypes.byref(device))):
                    continue
                try:
                    self._walk_sessions(device, lambda ctl, ctl2, pid, exe: found.append(
                        (pid, exe, self._is_active(ctl))))
                finally:
                    release(device)
        finally:
            release(coll)
        return found

    @staticmethod
    def _is_active(ctl) -> bool:
        state = ctypes.c_int()
        if failed(vcall(ctl, 3, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(state))):
            return False
        return state.value == 1          # AudioSessionStateActive

    def _walk_sessions(self, device, visit) -> None:
        """Llama a visit(control, control2, pid, exe) por cada sesión del dispositivo."""
        mgr = ctypes.c_void_p()
        if failed(vcall(device, 3, (ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p)),
                        ctypes.byref(IID_IAudioSessionManager2), wincom.CLSCTX_ALL, None,
                        ctypes.byref(mgr))):
            return
        try:
            senum = ctypes.c_void_p()
            if failed(vcall(mgr, 5, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(senum))):
                return
            try:
                n = ctypes.c_int()
                vcall(senum, 3, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(n))
                for j in range(n.value):
                    ctl = ctypes.c_void_p()
                    if failed(vcall(senum, 4, (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
                                    j, ctypes.byref(ctl))):
                        continue
                    try:
                        ctl2 = wincom.query_interface(ctl, IID_IAudioSessionControl2)
                        if ctl2 is None:
                            continue
                        try:
                            pid = ctypes.c_uint32()
                            vcall(ctl2, 14, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(pid))
                            visit(ctl, ctl2, pid.value, self._exe_of(pid.value))
                        finally:
                            release(ctl2)
                    finally:
                        release(ctl)
            finally:
                release(senum)
        finally:
            release(mgr)

    def _device_volumes(self, device, wanted: set) -> list:
        out = []

        def visit(ctl, _ctl2, _pid, exe):
            if exe in wanted:
                vol = wincom.query_interface(ctl, IID_ISimpleAudioVolume)
                if vol is not None:
                    out.append(vol)

        self._walk_sessions(device, visit)
        return out

    def get(self, exe_names: tuple[str, ...]) -> float | None:
        """Volumen 0..1 (0 si está silenciada) de la primera sesión encontrada,
        o None si esos ejecutables no tienen ninguna sesión de audio."""
        if not exe_names:
            return None
        vols = self._volumes_for(exe_names)
        try:
            for vol in vols:
                level = ctypes.c_float()
                muted = ctypes.c_int()
                if failed(vcall(vol, 4, (ctypes.POINTER(ctypes.c_float),), ctypes.byref(level))):
                    continue
                vcall(vol, 6, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(muted))
                return 0.0 if muted.value else max(0.0, min(1.0, float(level.value)))
            return None
        finally:
            for vol in vols:
                release(vol)

    def set(self, exe_names: tuple[str, ...], level: float) -> bool:
        """Fija el volumen (0..1) de todas sus sesiones. Si se sube por encima de
        0, quita el silencio (si no, subir el volumen no se oiría)."""
        level = max(0.0, min(1.0, float(level)))
        vols = self._volumes_for(exe_names)
        ok = False
        try:
            for vol in vols:
                hr = vcall(vol, 3, (ctypes.c_float, ctypes.c_void_p), ctypes.c_float(level), None)
                if level > 0:
                    vcall(vol, 5, (ctypes.c_int, ctypes.c_void_p), 0, None)
                ok = ok or not failed(hr)
        finally:
            for vol in vols:
                release(vol)
        return ok
