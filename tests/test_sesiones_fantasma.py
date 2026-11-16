"""Sesiones nativas de Windows ya cerradas: se limpian solas (reproductor 'pegado' en la última canción)."""
import os, sys, time, types, concurrent.futures
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pywnp_patch as PP

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

PREFIX = "NativeWinMedia:"
class MI:
    def __init__(self, sid, state="PLAYING", title="x", ts=0):
        self._id = PREFIX + sid; self.state = state; self.title = title; self.timestamp = ts; self.is_native = True
class Session:
    def __init__(self, sid, dead=False): self.source_app_user_model_id = sid; self.dead = dead; self.removed = []
    def _remove(self, name):
        def f(token):
            if self.dead: raise OSError("sesión muerta")
            self.removed.append(name)
        return f
    def __getattr__(self, n):
        if n.startswith("remove_"): return self._remove(n)
        raise AttributeError(n)
class WS:
    def __init__(self, session): self.session = session; self.media_properties_changed_token = 1; self.playback_info_changed_token = 2; self.timeline_properties_changed_token = 3

def fake_impl(entries, live, with_sessions=True):
    logs = []; recipients = []
    class WNPRedux:
        media_info_dictionary = list(entries); media_info = entries[0] if entries else None
        @staticmethod
        def update_media_info():
            d = WNPRedux.media_info_dictionary
            WNPRedux.media_info = d[0] if d else None
        @staticmethod
        def log(level, msg): logs.append((level, msg))
    class Native:
        id_prefix = PREFIX
        win_sessions = {mi._id[len(PREFIX):]: WS(Session(mi._id[len(PREFIX):], dead=mi._id[len(PREFIX):] not in live)) for mi in entries} if with_sessions else {}
        manager = types.SimpleNamespace(get_sessions=lambda: [Session(s) for s in live])
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    class Http:
        @staticmethod
        def update_recipients(): recipients.append(1)
    impl = types.SimpleNamespace(WNPRedux=WNPRedux, WNPReduxNative=Native, HttpServer=Http)
    return impl, logs, recipients

# --- Spotify cerrado sin aviso: su entrada fantasma se quita
ghost, other = MI("Spotify.exe", "PLAYING", "Vivamos el Momento", 5), MI("VLC", "PAUSED", "otra", 3)
impl, logs, rec = fake_impl([ghost, other], live={"VLC"})
check("antes: el fantasma gana (está PLAYING y es el primero)", impl.WNPRedux.media_info is ghost)
removed = PP.reconcile_native_sessions(impl)
check("se quita solo la sesión que ya no existe", removed == ["Spotify.exe"] and impl.WNPRedux.media_info_dictionary == [other])
check("el reproductor activo pasa a ser el que sigue vivo", impl.WNPRedux.media_info is other)
check("se da de baja su registro de eventos sin romperse (sesión muerta)", "Spotify.exe" not in impl.WNPReduxNative.win_sessions)
check("se avisa a los clientes y se deja constancia en el registro", rec and any("Spotify.exe" in m for _l, m in logs) and logs[0][0] == "Warning")

# --- ninguna sesión viva: no queda nada
impl, logs, rec = fake_impl([MI("Spotify.exe")], live=set())
PP.reconcile_native_sessions(impl)
check("sin sesiones vivas la interfaz queda sin reproductor", impl.WNPRedux.media_info is None and not impl.WNPRedux.media_info_dictionary)

# --- todo en orden: no toca nada
impl, logs, rec = fake_impl([MI("Spotify.exe")], live={"Spotify.exe"})
check("si la sesión sigue viva no se toca", PP.reconcile_native_sessions(impl) == [] and len(impl.WNPRedux.media_info_dictionary) == 1 and not logs)

# --- entradas que no son nativas (navegador) nunca se tocan
web = types.SimpleNamespace(_id="ws-client-1", state="PLAYING")
impl, logs, rec = fake_impl([MI("Spotify.exe")], live=set()); impl.WNPRedux.media_info_dictionary.append(web)
PP.reconcile_native_sessions(impl)
check("las entradas del navegador se conservan", web in impl.WNPRedux.media_info_dictionary)

# --- casos raros: nunca lanza
impl, logs, rec = fake_impl([MI("X")], live={"X"}); impl.WNPReduxNative.manager = None
check("sin gestor de sesiones: no hace nada", PP.reconcile_native_sessions(impl) == [])
def boom(): raise OSError("RPC no disponible")
impl, logs, rec = fake_impl([MI("X")], live={"X"}); impl.WNPReduxNative.manager = types.SimpleNamespace(get_sessions=boom)
check("si Windows no responde: no lanza y no borra nada", PP.reconcile_native_sessions(impl) == [] and len(impl.WNPRedux.media_info_dictionary) == 1)
check("sin pywnp/nativo (Linux): lista vacía", PP.reconcile_native_sessions(types.SimpleNamespace()) == [])

# --- programación: no bloquea y se limita
impl, logs, rec = fake_impl([MI("Spotify.exe")], live=set())
sys.modules["pywnp.pywnp"] = impl
PP._last_reconcile_at[0] = 0.0
check("se programa la primera vez", PP.schedule_reconcile() is True)
impl.WNPReduxNative.pool.shutdown(wait=True)
check("el trabajo limpió la sesión fantasma en segundo plano", not impl.WNPRedux.media_info_dictionary)
check("el candado queda libre", PP._reconcile_lock.acquire(blocking=False)); PP._reconcile_lock.release()
check("dentro del intervalo no vuelve a programarse", PP.schedule_reconcile() is False)
PP._last_reconcile_at[0] = 0.0
check("sin entradas nativas no hace nada", PP.schedule_reconcile() is False)
sys.modules.pop("pywnp.pywnp", None)
check("sin pywnp cargado no hace nada", PP.schedule_reconcile() is False)

# --- el sondeo del backend lo pide
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from backend import WNPBackend
be = WNPBackend(); asked = []
PP.schedule_reconcile = lambda *a, **k: asked.append(1)
import backend as B; B.pywnp_patch = PP
be._wnp = types.SimpleNamespace(clients=0, media_info=types.SimpleNamespace(
    controls=types.SimpleNamespace(supports_play_pause=False, supports_skip_previous=False, supports_skip_next=False,
        supports_set_position=False, supports_set_volume=False, supports_toggle_shuffle_active=False, supports_toggle_repeat_mode=False),
    player_name="", state="STOPPED", title="", artist="", album="", cover_url="", duration="", duration_seconds=0,
    position="", position_seconds=0, position_percent=0, volume=100, shuffle_active=False, repeat_mode="NONE"))
be._poll()
check("cada sondeo pide la reconciliación (es barata)", asked == [1])
PP.schedule_reconcile = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla"))
be._poll()
check("si la reconciliación fallara, el sondeo sigue", True)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
