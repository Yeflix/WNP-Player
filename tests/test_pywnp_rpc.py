"""Recuperación de sesiones de Windows muertas (pywnp_patch, Bug #12).

    python tests/test_pywnp_rpc.py

No necesita Windows ni pywnp: simula `pywnp.pywnp` con sesiones falsas que
fallan con `[WinError -2147023174] El servidor RPC no está disponible`.
Comprueba que la orden se reintenta con la sesión renovada, que no hay ruido
si el reproductor se cerró de verdad, que no hay bucles y que
`unregister_sessions` limpia siempre.
"""
import sys, types, asyncio, threading, time
from concurrent.futures import ThreadPoolExecutor
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logs = []
class RpcError(OSError):
    def __init__(self):
        super().__init__("[WinError -2147023174] El servidor RPC no está disponible")
        self.winerror = -2147023174

class FakeSession:
    def __init__(self, name, alive=True, exc=None):
        self.name, self.alive, self.exc, self.calls = name, alive, exc, []
        self.removed = 0
    source_app_user_model_id = property(lambda s: s.name)
    async def try_play_async(self):
        if self.exc: raise self.exc
        if not self.alive: raise RpcError()
        self.calls.append("play")
    async def try_pause_async(self):
        if not self.alive: raise RpcError()
        self.calls.append("pause")
    async def try_skip_next_async(self):
        if not self.alive: raise RpcError()
        self.calls.append("next")
    def _remove(self, tok):
        self.removed += 1
        if not self.alive: raise RpcError()
    remove_media_properties_changed = remove_playback_info_changed = remove_timeline_properties_changed = _remove

class WinSession:
    def __init__(self, session): self.session=session; self.media_properties_changed_token=self.playback_info_changed_token=self.timeline_properties_changed_token=1

class MediaInfo:
    def __init__(self): self._id=""; self.player_name=""; self.repeat_mode="NONE"; self.shuffle_active=False

class WNPRedux:
    media_info = MediaInfo()
    @staticmethod
    def log(t, m): logs.append((t, m))

class HttpServer: 
    @staticmethod
    def update_recipients(): pass

class Native:
    id_prefix = "WNPReduxNativeWindows_"
    win_sessions = {}
    pool = ThreadPoolExecutor()
    manager = types.SimpleNamespace(sessions=[])
    refreshes = 0
    @staticmethod
    def get_media_info(app_id): return WNPRedux.media_info
    @staticmethod
    def unregister_sessions():   # = original de pywnp: UN solo try/except para todo el bucle
        try:
            for ws in Native.win_sessions.values():
                ws.session.remove_media_properties_changed(1)
                ws.session.remove_playback_info_changed(1)
                ws.session.remove_timeline_properties_changed(1)
            Native.win_sessions.clear()
        except: pass
    @staticmethod
    def sessions_changed_native(manager, e):
        Native.refreshes += 1
        Native.unregister_sessions()
        for s in manager.sessions: Native.win_sessions[s.name] = WinSession(s)
    @staticmethod
    def on_message_hook(m): pass
    @staticmethod
    def playback_info_changed_native(s,e): pass
    @staticmethod
    def timeline_properties_changed_native(s,e): pass

impl = types.ModuleType("pywnp.pywnp")
impl.WNPRedux, impl.HttpServer, impl.WNPReduxNative = WNPRedux, HttpServer, Native
impl.time_in_seconds_to_string = lambda n: str(n)
pkg = types.ModuleType("pywnp"); pkg.pywnp = impl
sys.modules["pywnp"] = pkg; sys.modules["pywnp.pywnp"] = impl

import pywnp_patch
pywnp_patch.apply()
hook = Native.on_message_hook
PASS=[]; FAIL=[]
def check(n, c, extra=""): (PASS if c else FAIL).append(n); print(("  OK   " if c else "  FALLA"), n, extra)
def errors(): return [m for t,m in logs if t=="Error"]
def reset(): logs.clear()
def use(app, s): 
    WNPRedux.media_info._id = Native.id_prefix + app
    Native.win_sessions.clear(); Native.win_sessions[app] = WinSession(s)

print("== 1) sesión sana")
reset(); s = FakeSession("Spotify.exe"); use("Spotify.exe", s)
hook("TRY_SET_STATE PLAYING"); check("ejecuta la orden", s.calls == ["play"] and not errors())

print("== 2) sesión muerta, Windows ya tiene la sesión nueva -> se renueva y se reintenta")
reset(); old = FakeSession("Spotify.exe", alive=False); new = FakeSession("Spotify.exe"); use("Spotify.exe", old)
Native.manager.sessions = [new]; Native.refreshes = 0; pywnp_patch._last = None
hook("TRY_SKIP_NEXT")
check("la orden llega a la sesión NUEVA", new.calls == ["next"], str(new.calls))
check("sin errores en el registro", not errors(), str(errors()))
check("se renovaron las sesiones una vez", Native.refreshes == 1)
check("la sesión muerta ya no está", Native.win_sessions["Spotify.exe"].session is new)

print("== 3) sesión muerta y Spotify ya no existe -> se descarta sin ruido")
reset(); dead = FakeSession("Spotify.exe", alive=False); use("Spotify.exe", dead); Native.manager.sessions = []
time.sleep(1.6); hook("TRY_SET_STATE PAUSED")
check("sin error", not errors(), str(errors()))
check("queda registrado a nivel Debug", any("ya no tiene sesión" in m for t,m in logs if t=="Debug"))
check("se limpió la entrada muerta (Bug #12a)", "Spotify.exe" not in Native.win_sessions)

print("== 4) error que NO es RPC -> se registra como Error (comportamiento de siempre)")
reset(); s = FakeSession("Spotify.exe", exc=ValueError("otro problema")); use("Spotify.exe", s); Native.refreshes = 0
hook("TRY_SET_STATE PLAYING")
check("se registra el error", len(errors()) == 1 and "Failed to execute event (parche)" in errors()[0])
check("NO se renuevan sesiones por un error ajeno", Native.refreshes == 0)

print("== 5) la sesión sigue inalcanzable tras renovar (fantasma) -> 1 error, sin bucle")
reset(); ghost = FakeSession("Spotify.exe", alive=False); use("Spotify.exe", ghost); Native.manager.sessions = [ghost]; Native.refreshes = 0
time.sleep(1.6); hook("TRY_SET_STATE PLAYING")
check("un solo Error registrado", len(errors()) == 1, str(len(errors())))
check("solo un reintento (1 renovación)", Native.refreshes == 1)

print("== 6) unregister_sessions corregido (Bug #12a)")
reset(); dead = FakeSession("A", alive=False); live = FakeSession("B")
Native.win_sessions.clear(); Native.win_sessions["A"] = WinSession(dead); Native.win_sessions["B"] = WinSession(live)
Native.unregister_sessions()
check("limpia el diccionario aunque la primera sesión falle", Native.win_sessions == {})
check("da de baja los manejadores de la sesión sana", live.removed == 3, str(live.removed))

print("== 7) varias órdenes a la vez con sesión muerta -> una sola renovación")
reset(); old = FakeSession("Spotify.exe", alive=False); new = FakeSession("Spotify.exe"); use("Spotify.exe", old)
Native.manager.sessions = [new]; Native.refreshes = 0; time.sleep(1.6)
ts = [threading.Thread(target=hook, args=("TRY_SKIP_NEXT",)) for _ in range(3)]
[t.start() for t in ts]; [t.join() for t in ts]
check("una sola renovación", Native.refreshes == 1, str(Native.refreshes))
check("sin errores", not errors(), str(errors()))
print("== 8) detección del código")
check("winerror", pywnp_patch._is_rpc_unavailable(RpcError()))
check("texto con el número", pywnp_patch._is_rpc_unavailable(Exception("[WinError -2147023174] The RPC server is unavailable")))
check("0x800706BA", pywnp_patch._is_rpc_unavailable(Exception("HRESULT 0x800706BA")))
check("otro error no", not pywnp_patch._is_rpc_unavailable(ValueError("x")))
print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas"); sys.exit(1 if FAIL else 0)
