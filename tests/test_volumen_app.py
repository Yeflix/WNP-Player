"""Volumen por aplicación para apps de escritorio (backend + app_volume), con el
servicio de Windows simulado: la parte COM real solo se puede probar en Windows."""
import os, sys, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import app_volume, backend
from backend import PlayerState

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

check("Spotify → spotify.exe", app_volume.exe_names_for("Spotify") == ("spotify.exe",))
check("nombre desconocido → <nombre>.exe", app_volume.exe_names_for("Mi Player") == ("miplayer.exe",))
check("sin nombre → nada", app_volume.exe_names_for("") == ())

class FakeVol:
    def __init__(self): self.levels = {"spotify.exe": 0.42}; self.gets = 0; self.sets = []
    def get(self, names):
        self.gets += 1
        return next((self.levels[n] for n in names if n in self.levels), None)
    def set(self, names, level):
        self.sets.append((names, level)); self.levels[names[0]] = level; return True
    def close(self): pass

b = backend.WNPBackend()
fake = FakeVol(); b._app_volume = fake
clock = {"t": 100.0}; backend.time.monotonic = lambda: clock["t"]

native = PlayerState(connected=True, player_name="Spotify", title="x", state="PLAYING", can_volume=False, volume=100)
st = b._with_app_volume(native)
check("app de escritorio con sesión de audio → volumen disponible", st.can_volume and st.volume == 42, str(st))
b._with_app_volume(native); b._with_app_volume(native)
check("se consulta como mucho una vez por segundo", fake.gets == 1)
clock["t"] += 1.1; b._with_app_volume(native)
check("…y se refresca pasado el segundo", fake.gets == 2)

b._running = True
b.set_volume(80)
check("set_volume va al volumen de la aplicación", fake.sets[-1] == (("spotify.exe",), 0.8))
check("lo pedido se refleja de inmediato", b._with_app_volume(native).volume == 80)

web = PlayerState(connected=True, player_name="YouTube", title="x", can_volume=True, volume=55)
check("fuente del navegador con volumen propio: no se toca", b._with_app_volume(web) == web)
called = []
b._wnp = types.SimpleNamespace(media_info=types.SimpleNamespace(controls=types.SimpleNamespace(
    try_set_volume=lambda v: called.append(v))))
b.set_volume(30)
check("y su volumen sigue yendo a la extensión", called == [30] and fake.sets[-1][1] == 0.8)

other = PlayerState(connected=True, player_name="Telegram", title="x", can_volume=False)
check("app sin sesión de audio: sigue sin volumen", not b._with_app_volume(other).can_volume)
b._app_volume = None; b._app_volume_failed = True
check("sin servicio (fuera de Windows): sin cambios", b._with_app_volume(native) == native)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
