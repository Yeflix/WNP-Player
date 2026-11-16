"""Scrobbling: las pausas no cuentan como escuchado, y sin conexión los scrobbles
van a una cola en disco que se reenvía en orden (sin tocar la red: todo simulado)."""
import os, sys, tempfile, types
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pathlib import Path
from PyQt6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import scrobbling as S

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

class SyncPool:
    def submit(self, fn, *a): fn(*a)

cfg = types.SimpleNamespace(scrobble_service="LASTFM", lastfm_api_key="k", lastfm_api_secret="s",
                            lastfm_session_key="sk", listenbrainz_token="")
sent, now_playing, online = [], [], {"v": True}
def fake_scrobble(key, secret, sk, artist, title, ts, album="", dur=0):
    if not online["v"]:
        return S.SendError("No se pudo conectar con Last.fm: sin red", True)
    sent.append((artist, title, ts)); return None
S.lastfm_scrobble = fake_scrobble
S.lastfm_update_now_playing = lambda *a, **k: now_playing.append(a) or None

clock = {"t": 1000.0}
S.time.monotonic = lambda: clock["t"]

q = S.ScrobbleQueue(Path(tmp) / "cola.json")
m = S.ScrobbleManager(lambda: cfg, queue=q); m._pool = SyncPool()

# --- pausas -------------------------------------------------------------------
m.set_playing(True)
m.track_changed("Artista", "Tema", "Disco", 200)        # umbral: 100 s
clock["t"] += 60; m.set_playing(False)                   # 60 s escuchados
clock["t"] += 1000                                       # pausa larga
m._do_scrobble()                                         # aunque el temporizador saltara...
check("una pausa larga no cuenta como escuchado", sent == [] and abs(m.listened_seconds() - 60) < 1e-6)
m.set_playing(True); clock["t"] += 39; m._do_scrobble()
check("a los 99 s escuchados todavía no", sent == [])
clock["t"] += 2; m._do_scrobble()
check("al pasar la mitad (sin pausas) se envía", len(sent) == 1 and sent[0][:2] == ("Artista", "Tema"))
m.track_changed("A", "Muy corta", "", 20)
check("las de menos de 30 s no se programan", m._pending is None)
m.track_changed("A", "Larga", "", 3600); clock["t"] += 240; m._do_scrobble()
check("las largas se envían a los 4 min", sent[-1][1] == "Larga")
m.track_changed("A", "Cortada", "", 300); clock["t"] += 10; m.stop_pending(); clock["t"] += 500; m._do_scrobble()
check("stop_pending cancela", sent[-1][1] == "Larga")

# --- cola sin conexión ------------------------------------------------------------
online["v"] = False
for i in range(3):
    m.track_changed("Sin red", f"T{i}", "", 100); clock["t"] += 60; m._do_scrobble()
check("sin red: 3 a la cola", len(q) == 3 and len(sent) == 2, str(q.items()))
check("la cola se guarda en disco", (Path(tmp) / "cola.json").exists())
q2 = S.ScrobbleQueue(Path(tmp) / "cola.json")
check("y sobrevive a un reinicio", [it["title"] for it in q2.items()] == ["T0", "T1", "T2"])
m._flush_now(cfg)
check("reenvío sin red: no se pierde nada", len(q) == 3)
online["v"] = True
m.track_changed("Con red", "Nueva", "", 100); clock["t"] += 60; m._do_scrobble()
check("al volver la red se envía todo en orden", [t for _, t, _ in sent[-4:]] == ["T0", "T1", "T2", "Nueva"], str(sent))
check("cola vacía y archivo borrado", len(q) == 0 and not (Path(tmp) / "cola.json").exists())

# --- reglas de la cola ------------------------------------------------------------
import time as _t
q3 = S.ScrobbleQueue(Path(tmp) / "c3.json")
q3.add("LASTFM", "a", "vieja", "", 100, int(_t.time()) - 20 * 24 * 3600)
q3.add("LASTFM", "a", "mala", "", 100, int(_t.time()))
q3.add("LASTFM", "a", "buena", "", 100, int(_t.time()))
def send(item):
    return S.SendError("Invalid parameters", False) if item["title"] == "mala" else None
ok, dropped = q3.flush(send)
check("Last.fm: >14 días y errores definitivos se descartan; el resto se envía", (ok, dropped) == (1, 2) and len(q3) == 0)
for i in range(S.QUEUE_MAX_ENTRIES + 5):
    q3.add("LISTENBRAINZ", "a", f"t{i}", "", 100, int(_t.time()))
check("límite de tamaño: se descarta lo más viejo", len(q3) == S.QUEUE_MAX_ENTRIES and q3.items()[0]["title"] == "t5")
check("un archivo de cola dañado no rompe nada", (Path(tmp) / "d.json").write_text("{no json") and len(S.ScrobbleQueue(Path(tmp) / "d.json")) == 0)
check("SendError sigue siendo un texto", isinstance(S.SendError("x", True), str) and S.SendError("x", True) == "x")
cfg.scrobble_service = "NONE"; q4 = S.ScrobbleQueue(Path(tmp) / "c4.json"); q4.add("LASTFM", "a", "b", "", 100, int(_t.time()))
m.queue = q4; m._flush_now(cfg)
check("con el scrobbling apagado la cola se conserva", len(q4) == 1)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
