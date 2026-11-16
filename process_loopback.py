"""Captura del audio de UN proceso (Application Loopback de Windows) para el
visualizador: solo lo que suena en el reproductor, no todo el equipo.

Antes el visualizador abría el *loopback* del dispositivo de salida (la mezcla
final: avisos, Discord, juegos...). Windows permite pedir el audio de un
proceso y sus hijos: ActivateAudioInterfaceAsync sobre el dispositivo virtual
"VAD\\Process_Loopback" con AUDIOCLIENT_ACTIVATION_PARAMS
(PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE). Microsoft lo documenta
desde Windows 10 build 20348 (en la práctica, Windows 11); en algunas
versiones anteriores de Windows 10 también funciona.

A qué proceso se escucha (`resolve_target`):
  1. Al del reproductor si es una app de escritorio con sesión de audio
     (Spotify, VLC...: mismos ejecutables que app_volume.exe_names_for).
  2. Si no (fuente del navegador), al navegador que tenga una sesión de audio
     sonando ahora. Se captura el navegador entero (todas sus pestañas): Windows
     no ve las pestañas como procesos separados.
  Siempre se sube hasta el proceso PRINCIPAL de ese ejecutable (el audio de
  Spotify y de Chrome sale de un proceso hijo, y el árbol completo se incluye).

Si algo falla (Windows antiguo, proceso no encontrado, error de COM), quien lo
usa (audio_levels.AudioLevels) vuelve a la captura de todo el equipo.

Sin dependencias nuevas: ctypes + numpy (que el visualizador ya usa).
"""
from __future__ import annotations

import ctypes
import sys
import threading

import wincom
from diag import soft
from wincom import GUID, check, failed, release, vcall

MIN_BUILD = 19041                 # se intenta desde Windows 10 2004; si falla, se vuelve a todo el equipo
OFFICIAL_BUILD = 20348            # mínimo documentado por Microsoft
RATE = 48000
CHANNELS = 2
BITS = 16
ACTIVATE_TIMEOUT_S = 3.0

VAD_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
IID_IUnknown = GUID.from_str("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = GUID.from_str("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IActivateCompletionHandler = GUID.from_str("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IAudioClient = GUID.from_str("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = GUID.from_str("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
E_NOINTERFACE = -2147467262       # 0x80004002
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
VT_BLOB = 65

BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe",
            "vivaldi.exe", "arc.exe", "zen.exe", "librewolf.exe", "waterfox.exe", "floorp.exe",
            "chromium.exe", "yandex.exe", "thorium.exe")


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def availability() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Solo está disponible en Windows."
    build = windows_build()
    if build < MIN_BUILD:
        return False, (f"Tu Windows (compilación {build}) no permite captar el audio de una sola "
                       "aplicación: se usa todo el audio del equipo.")
    return True, ""


# ---------------------------------------------------------------- a quién escuchar
def root_pid(pid: int, processes: list[tuple[int, int, str]]) -> int:
    """Sube por los padres mientras sigan siendo el mismo ejecutable (Spotify y
    los navegadores reproducen el sonido en un proceso hijo)."""
    by_pid = {p: (parent, exe) for p, parent, exe in processes}
    if pid not in by_pid:
        return pid
    exe = by_pid[pid][1]
    seen = {pid}
    current = pid
    while True:
        parent = by_pid[current][0]
        if parent in seen or parent not in by_pid or by_pid[parent][1] != exe:
            return current
        seen.add(parent)
        current = parent


def choose_target(player_exes: tuple[str, ...], sessions: list[tuple[int, str, bool]],
                  processes: list[tuple[int, int, str]]) -> tuple[int, str] | None:
    """(pid principal, exe) a capturar, o None. `sessions`: [(pid, exe, activa)]
    de app_volume.AppVolume.sessions(). Función pura para poder probarla."""
    wanted = {e.lower() for e in player_exes}

    def pick(candidates):
        # Una sesión que está sonando gana a una que solo existe.
        candidates = sorted(candidates, key=lambda s: not s[2])
        return candidates[0] if candidates else None

    own = pick([s for s in sessions if s[1] in wanted])
    if own is not None and (own[2] or not any(s[2] and s[1] in BROWSERS for s in sessions)):
        return root_pid(own[0], processes), own[1]
    browser = pick([s for s in sessions if s[1] in BROWSERS and s[2]])
    if browser is not None:
        return root_pid(browser[0], processes), browser[1]
    if own is not None:
        return root_pid(own[0], processes), own[1]
    return None


def resolve_target(player_name: str, volume_service=None) -> tuple[int, str] | None:
    """Proceso a escuchar para el reproductor `player_name` (hilo de la interfaz)."""
    import app_volume
    service = volume_service or app_volume.AppVolume()
    try:
        sessions = service.sessions()
    finally:
        if volume_service is None:
            service.close()
    return choose_target(app_volume.exe_names_for(player_name), sessions, wincom.list_processes())


# ------------------------------------------------------------------ estructuras
class _BLOB(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("pBlobData", ctypes.c_void_p)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("blob", _BLOB)]


class _ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_uint32),      # 1 = PROCESS_LOOPBACK
                ("TargetProcessId", ctypes.c_uint32),
                ("ProcessLoopbackMode", ctypes.c_uint32)]  # 0 = incluir el árbol del proceso


class _WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16),
                ("nSamplesPerSec", ctypes.c_uint32), ("nAvgBytesPerSec", ctypes.c_uint32),
                ("nBlockAlign", ctypes.c_uint16), ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16)]


# Manejadores cuya activación no terminó a tiempo: Windows podría llamarlos más
# tarde, así que no se pueden liberar nunca (son unos pocos bytes).
_ORPHAN_HANDLERS: list = []

# ------------------------------------------- objeto COM de respuesta (en Python)
_QI = wincom._FUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
_ADDREF = wincom._FUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_COMPLETED = wincom._FUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)


class _HandlerVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI), ("AddRef", _ADDREF), ("Release", _ADDREF),
                ("ActivateCompleted", _COMPLETED)]


class _HandlerObj(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_HandlerVtbl))]


class _CompletionHandler:
    """IActivateAudioInterfaceCompletionHandler + IAgileObject hechos con ctypes.
    Windows llama a ActivateCompleted desde otro hilo; solo se avisa con un Event.
    El objeto Python debe vivir mientras dure la activación (lo guarda la fuente)."""

    def __init__(self):
        self.done = threading.Event()
        self._refs = 1

        def qi(this, riid, ppv):
            iid = bytes(riid.contents)
            if iid in (bytes(IID_IUnknown), bytes(IID_IAgileObject), bytes(IID_IActivateCompletionHandler)):
                ppv[0] = this
                self._refs += 1
                return 0
            ppv[0] = None
            return E_NOINTERFACE

        def addref(this):
            self._refs += 1
            return self._refs

        def rel(this):
            self._refs = max(0, self._refs - 1)
            return self._refs

        def completed(this, op):
            self.done.set()
            return 0

        self._vtbl = _HandlerVtbl(_QI(qi), _ADDREF(addref), _ADDREF(rel), _COMPLETED(completed))
        self._obj = _HandlerObj(ctypes.pointer(self._vtbl))

    @property
    def pointer(self) -> int:
        return ctypes.addressof(self._obj)


# --------------------------------------------------------------------- fuente
class ProcessLoopbackSource:
    """Misma interfaz que las fuentes de audio_levels: start(callback) / stop().
    `start` resuelve el proceso (hilo de la interfaz) y lanza un hilo de captura;
    lanza una excepción si no se puede (entonces se usa la captura de todo el
    equipo). `callback(mono_float32, rate)` se llama desde el hilo de captura."""

    def __init__(self, player_name: str, target_resolver=resolve_target):
        self.player_name = player_name
        self._resolver = target_resolver
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self.target: tuple[int, str] | None = None

    def start(self, callback):
        ok, reason = availability()
        if not ok:
            raise OSError(reason)
        target = self._resolver(self.player_name)
        if target is None:
            raise OSError("No encuentro el proceso del reproductor con audio.")
        self.target = target
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, args=(target[0], callback),
                                        name="yefriplayer-process-loopback", daemon=True)
        self._thread.start()
        # Esperar a que la activación termine para poder caer a la otra fuente si falla.
        if not self._ready.wait(ACTIVATE_TIMEOUT_S + 0.5):
            self.stop()
            raise OSError("La captura por aplicación no respondió.")
        if self._error is not None:
            err, self._error = self._error, None
            self.stop()
            raise OSError(str(err))

    def stop(self):
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)

    # ------------------------------------------------------- hilo de captura
    def _run(self, pid: int, callback):
        client = capture = op = None
        event = None
        handler = None
        k32 = ctypes.windll.kernel32
        ole32 = ctypes.windll.ole32
        # COM propio de este hilo (y se cierra al salir: el id de un hilo se reutiliza).
        com_hr = ole32.CoInitializeEx(None, wincom.COINIT_MULTITHREADED)
        try:
            handler = _CompletionHandler()
            params = _ACTIVATION_PARAMS(1, int(pid), 0)
            pv = _PROPVARIANT(vt=VT_BLOB)
            pv.blob.cbSize = ctypes.sizeof(params)
            pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), ctypes.c_void_p)
            mmdev = ctypes.windll.mmdevapi
            mmdev.ActivateAudioInterfaceAsync.restype = ctypes.c_long
            mmdev.ActivateAudioInterfaceAsync.argtypes = (
                ctypes.c_wchar_p, ctypes.POINTER(GUID), ctypes.POINTER(_PROPVARIANT),
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
            op = ctypes.c_void_p()
            check(mmdev.ActivateAudioInterfaceAsync(VAD_PROCESS_LOOPBACK, ctypes.byref(IID_IAudioClient),
                                                    ctypes.byref(pv), handler.pointer, ctypes.byref(op)),
                  "ActivateAudioInterfaceAsync")
            if not handler.done.wait(ACTIVATE_TIMEOUT_S):
                _ORPHAN_HANDLERS.append(handler)      # Windows aún puede llamarlo
                raise OSError("Windows no completó la activación de la captura.")
            hr_activate = ctypes.c_long()
            unknown = ctypes.c_void_p()
            check(vcall(op, 3, (ctypes.POINTER(ctypes.c_long), ctypes.POINTER(ctypes.c_void_p)),
                        ctypes.byref(hr_activate), ctypes.byref(unknown)), "GetActivateResult")
            check(hr_activate.value, "activación de la captura por proceso")
            client = unknown

            fmt = _WAVEFORMATEX(1, CHANNELS, RATE, RATE * CHANNELS * BITS // 8, CHANNELS * BITS // 8, BITS, 0)
            flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                     | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
            check(vcall(client, 3, (ctypes.c_int, ctypes.c_uint32, ctypes.c_longlong, ctypes.c_longlong,
                                    ctypes.POINTER(_WAVEFORMATEX), ctypes.c_void_p),
                        0, flags, 2_000_000, 0, ctypes.byref(fmt), None), "IAudioClient.Initialize")
            k32.CreateEventW.restype = ctypes.c_void_p
            k32.CreateEventW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p)
            k32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            k32.CloseHandle.argtypes = (ctypes.c_void_p,)
            event = k32.CreateEventW(None, False, False, None)
            check(vcall(client, 13, (ctypes.c_void_p,), event), "IAudioClient.SetEventHandle")
            capture = ctypes.c_void_p()
            check(vcall(client, 14, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)),
                        ctypes.byref(IID_IAudioCaptureClient), ctypes.byref(capture)), "GetService")
            check(vcall(client, 10), "IAudioClient.Start")
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            self._cleanup(client, capture, op, event)
            if com_hr >= 0:
                ole32.CoUninitialize()
            return
        self._ready.set()

        import numpy as np
        block = CHANNELS * BITS // 8
        try:
            while not self._stop.is_set():
                k32.WaitForSingleObject(event, 100)
                while not self._stop.is_set():
                    pending = ctypes.c_uint32()
                    if failed(vcall(capture, 5, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(pending))):
                        raise OSError("GetNextPacketSize falló (el proceso se cerró o cambió la salida)")
                    if pending.value == 0:
                        break
                    data = ctypes.c_void_p()
                    frames = ctypes.c_uint32()
                    bflags = ctypes.c_uint32()
                    if failed(vcall(capture, 3, (ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
                                                 ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p),
                                    ctypes.byref(data), ctypes.byref(frames), ctypes.byref(bflags), None, None)):
                        break
                    n = frames.value
                    try:
                        if n:
                            if bflags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data.value:
                                mono = np.zeros(n, dtype=np.float32)
                            else:
                                raw = ctypes.string_at(data.value, n * block)
                                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                                mono = pcm.reshape(-1, CHANNELS).mean(axis=1)
                            with soft("process_loopback.callback"):
                                callback(mono, RATE)
                    finally:
                        vcall(capture, 4, (ctypes.c_uint32,), n)
        except Exception:
            # Sin bloques nuevos, el vigilante de AudioLevels reabrirá la captura.
            import diag
            diag.note("process_loopback._run")
        finally:
            with soft("process_loopback.stop"):
                vcall(client, 11)
            self._cleanup(client, capture, op, event)   # suelta op ANTES que el manejador
            del handler
            if com_hr >= 0:
                ole32.CoUninitialize()

    @staticmethod
    def _cleanup(client, capture, op, event):
        with soft("process_loopback.cleanup"):
            release(capture)
            release(client)
            release(op)
            if event:
                ctypes.windll.kernel32.CloseHandle(event)
