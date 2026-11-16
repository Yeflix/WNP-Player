"""Letras que se recuperan solas: metadatos tardíos, no-encontrada con caducidad, reintentos, vigilante."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
import lyrics as L
from widgets import LyricsPanel

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

# ---------------------------------------------------------- primer artista
check("'A, B' -> 'A'", L.first_artist("Artista A, Artista B") == "Artista A")
check("'A & B' -> 'A'", L.first_artist("Soda Stereo & Otro") == "Soda Stereo")
check("'A feat. B' -> 'A'", L.first_artist("Daddy Yankee feat. Snow") == "Daddy Yankee")
check("un nombre simple no cambia", L.first_artist("Airbag") == "Airbag")
check("vacío -> vacío", L.first_artist("") == "")

# ---------------------------------------- pasada sin duración (duración equivocada)
calls = []
orig_get, orig_search = L._fetch_get, L._fetch_search
FOUND = {"plain": "la letra", "synced": None, "instrumental": False}
def fake_get(a, t, album, dur): return None, None
def fake_search(a, t, dur=0, q=""):
    calls.append(dur); return (FOUND if dur == 0 else None), None
L._fetch_get, L._fetch_search = fake_get, fake_search
try:
    r = L._fetch("Airbag", "Vivamos el Momento", "Album", 999)     # duración de OTRA canción
    check("con duración equivocada la letra se encuentra sin ella", r == FOUND and 0 in calls)
    calls.clear(); r = L._fetch("Airbag", "Tema Inexistente", "", 0)
    check("sin duración conocida no repite la pasada de relleno", r == FOUND and all(c == 0 for c in calls))
    L._fetch_search = lambda a, t, dur=0, q="": (None, None)
    check("si de verdad no existe, sigue devolviendo None", L._fetch("X", "Y", "", 200) is None)
finally:
    L._fetch_get, L._fetch_search = orig_get, orig_search

# ------------------------------------------------------------------- cargador
class FakePool:
    def __init__(self): self.jobs = []
    def start(self, job): self.jobs.append(job)
loader = L.LyricsLoader(); loader._pool = FakePool()
got = []; loader.lyricsReady.connect(lambda k, r: got.append((k, r)))
loader.request("A", "uno"); key = L._cache_key("A", "uno")
loader._on_job_finished(key, None)
check("'no encontrada' se entrega pero NO queda guardada para siempre", got[-1] == (key, None) and key not in loader._cache)
n = len(loader._pool.jobs); loader.request("A", "uno")
check("dentro de su caducidad no se vuelve a consultar", len(loader._pool.jobs) == n and got[-1] == (key, None))
loader._negative_until[key] = 0.0; loader.request("A", "uno")
check("vencida la caducidad se consulta de nuevo", len(loader._pool.jobs) == n + 1)
loader._on_job_finished(key, None); loader.request("A", "uno", force=True)
check("recargar ignora el 'no encontrada' reciente", len(loader._pool.jobs) == n + 2)
loader._pending[key] = time.monotonic() - 100
loader.request("A", "uno")
check("una consulta colgada (>25 s) no bloquea las nuevas", len(loader._pool.jobs) == n + 3)
loader._on_job_finished(key, {"error": "sin red"})
check("los errores nunca se cachean", key not in loader._cache and key not in loader._negative_until)

# ---------------------------------------------------------------------- panel
class FakeLoader(QObject):
    lyricsReady = pyqtSignal(str, object)
    def __init__(self): super().__init__(); self.reqs = []
    def request(self, artist, title, album="", duration_seconds=0, force=False):
        self.reqs.append((artist, title, album, duration_seconds, force))

def make():
    ld = FakeLoader(); p = LyricsPanel(ld); return ld, p
KEY = L._cache_key("Airbag", "Vivamos el Momento")

ld, p = make()
p.set_track("Airbag", "Vivamos el Momento", "", 0)
check("la primera búsqueda sale con lo que haya", ld.reqs == [("Airbag", "Vivamos el Momento", "", 0, False)])
p.update_metadata("Mentira", 284)
check("durante la búsqueda no se lanza otra (se anota)", len(ld.reqs) == 1 and p._refresh_after_ready)
ld.lyricsReady.emit(KEY, None)
check("al fallar, repite enseguida con los metadatos nuevos", ld.reqs[-1] == ("Airbag", "Vivamos el Momento", "Mentira", 284, True))
ld.lyricsReady.emit(KEY, {"plain": "la letra", "synced": None, "instrumental": False})
check("al encontrarla queda en 'found'", p._state == "found")
n = len(ld.reqs); p.update_metadata("Otro álbum", 300)
check("con letra ya mostrada los metadatos no la tocan", len(ld.reqs) == n)

ld, p = make(); p.set_track("Airbag", "Vivamos el Momento", "", 0)
ld.lyricsReady.emit(KEY, None)
check("no encontrada: se programa UN reintento automático", p._retry_timer.isActive() and p._auto_retried_key == KEY)
p._retry_timer.stop(); p._auto_retry()
check("el reintento recarga saltándose la caché", ld.reqs[-1][4] is True and p._state == "loading")
ld.lyricsReady.emit(KEY, None)
check("si vuelve a fallar no entra en un bucle de reintentos", not p._retry_timer.isActive())
p.update_metadata("", 284)
check("pero si mejoran los metadatos, sí busca de nuevo", ld.reqs[-1] == ("Airbag", "Vivamos el Momento", "", 284, True) and p._state == "loading")
p.reload()
check("recargar usa los metadatos más recientes (duración 284)", ld.reqs[-1][3] == 284)

ld, p = make(); p.set_track("Airbag", "Vivamos el Momento", "Mentira", 284)
for i in range(3):
    ld.lyricsReady.emit(KEY, {"error": "La búsqueda se interrumpió. Se reintentará.", "transient": True})
    check(f"cancelación transitoria #{i + 1}: se reintenta sola", p._retry_timer.isActive())
    p._retry_timer.stop(); p._auto_retry()
ld.lyricsReady.emit(KEY, {"error": "La búsqueda se interrumpió. Se reintentará.", "transient": True})
check("tras 3 cancelaciones deja de insistir (queda el botón)", not p._retry_timer.isActive() and p.reload_btn.isVisibleTo(p) is True or p._state == "error")

ld, p = make(); p.set_track("Airbag", "Vivamos el Momento", "Mentira", 284)
real_remaining = L.rate_limit_remaining; L.rate_limit_remaining = lambda: 10.0
try:
    ld.lyricsReady.emit(KEY, {"error": L._RATE_LIMIT_MESSAGE})
    check("ante el límite de lrclib espera su tiempo (~11,5 s)", p._retry_timer.isActive() and 11000 <= p._retry_timer.interval() <= 12000)
finally:
    L.rate_limit_remaining = real_remaining

ld, p = make(); p.set_track("Airbag", "Vivamos el Momento", "Mentira", 284)
p._on_watchdog()
check("el vigilante convierte un 'Buscando…' eterno en error con reintento", p._state == "error" and p._retry_timer.isActive())
p._retry_timer.stop(); p._auto_retry()
ld.lyricsReady.emit(KEY, {"plain": "x", "synced": None, "instrumental": False})
check("y si la letra llega después, se muestra", p._state == "found")

ld, p = make(); p.set_track("Airbag", "Vivamos el Momento", "", 0)
ld.lyricsReady.emit(KEY, {"plain": "x", "synced": None, "instrumental": False})
ld.lyricsReady.emit("otra::cancion", None)
check("resultados de otra canción se ignoran", p._state == "found")
p.set_track_debounced("Airbag", "Vivamos el Momento", "Mentira", 284)
check("set_track_debounced con la misma canción solo actualiza metadatos", p._cur[2:] == ("Mentira", 284) and len(ld.reqs) == 1)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
