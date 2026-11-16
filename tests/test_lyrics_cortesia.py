"""lrclib: una consulta a la vez, 429 respetado, consultas obsoletas abandonadas, caché acotada."""
import os, sys, time, threading, io, email.message, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import lyrics as L

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

class Resp:
    def __init__(self, body=b'{"plainLyrics": "hola"}'): self._b = body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

real_urlopen = L.urllib.request.urlopen
try:
    # --- una sola petición en vuelo
    active = []; peak = [0]; lock = threading.Lock()
    def slow(req, timeout=0):
        with lock:
            active.append(1); peak[0] = max(peak[0], len(active))
        time.sleep(0.05)
        with lock: active.pop()
        return Resp()
    L.urllib.request.urlopen = slow
    ts = [threading.Thread(target=L._http_get_json, args=("https://lrclib.net/api/get?x=%d" % i,)) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    check("6 consultas simultáneas se atienden de una en una", peak[0] == 1)

    # --- 429 con Retry-After
    n = [0]
    def limited(retry_after):
        def f(req, timeout=0):
            n[0] += 1
            h = email.message.Message()
            if retry_after is not None: h["Retry-After"] = retry_after
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", h, io.BytesIO(b""))
        return f
    for header, expect in (("7", 7), ("9999", 120), ("1", 5), ("Wed, 21 Oct 2026 07:28:00 GMT", 30), (None, 30)):
        L._blocked_until = 0.0; n[0] = 0
        L.urllib.request.urlopen = limited(header)
        t0 = time.monotonic(); data, err = L._http_get_json("https://lrclib.net/api/get?q=1")
        waited = L._blocked_until - t0
        check(f"429 con Retry-After={header!r}: espera {expect} s", err == L._RATE_LIMIT_MESSAGE and abs(waited - expect) < 1.0)
    L._blocked_until = 0.0; n[0] = 0
    L.urllib.request.urlopen = limited("30")
    L._RETRY_DELAY_S = 0
    L._http_get_json_retry("https://lrclib.net/api/get?q=2")
    check("un 429 no se reintenta (una sola petición)", n[0] == 1)
    n[0] = 0
    data, err = L._http_get_json("https://lrclib.net/api/get?q=3")
    check("durante la espera no se consulta al servidor", n[0] == 0 and err == L._RATE_LIMIT_MESSAGE)
    L._blocked_until = 0.0

    # --- consulta obsoleta
    n[0] = 0
    L.urllib.request.urlopen = lambda req, timeout=0: (n.__setitem__(0, n[0] + 1) or Resp())
    L._ctx.should_continue = lambda: False
    data, err = L._http_get_json("https://lrclib.net/api/get?q=4")
    check("si el usuario ya cambió de canción no se hace la consulta", n[0] == 0 and err == L._CANCELLED)
    check("_fetch devuelve 'cancelled' (no 'no encontrada' ni error)", L._fetch("Queen", "Bohemian Rhapsody", "", 355) == {"cancelled": True})
    L._ctx.should_continue = None
finally:
    L.urllib.request.urlopen = real_urlopen
    L._ctx.should_continue = None

# --- LyricsLoader: la canción más reciente manda
class FakePool:
    def __init__(self): self.jobs = []
    def start(self, job): self.jobs.append(job)
loader = L.LyricsLoader(); loader._pool = FakePool()
got = []; loader.lyricsReady.connect(lambda k, r: got.append((k, r)))
loader.request("A", "uno"); loader.request("B", "dos")
ja, jb = loader._pool.jobs
check("la consulta de la canción anterior queda obsoleta", ja._should_continue() is False and jb._should_continue() is True)
loader._on_job_finished(ja.cache_key, {"cancelled": True})
check("una consulta cancelada no se guarda, y avisa (sin dejar a nadie esperando) con un error transitorio",
      len(got) == 1 and got[0][0] == ja.cache_key and got[0][1].get("transient") is True
      and ja.cache_key not in loader._cache and ja.cache_key not in loader._pending)
got.clear()
loader._on_job_finished(jb.cache_key, {"plain": "x", "synced": None, "instrumental": False})
check("la consulta vigente sí se entrega", len(got) == 1 and got[0][0] == jb.cache_key and "plain" in got[0][1])
for i in range(L._MAX_CACHE + 25):
    loader._on_job_finished(f"k{i}", {"plain": str(i), "synced": None, "instrumental": False})
check(f"la caché queda acotada a {L._MAX_CACHE} letras", len(loader._cache) <= L._MAX_CACHE and "k0" not in loader._cache)
check("el User-Agent identifica a YefriPlayer", L._HEADERS["User-Agent"].startswith("YefriPlayer/"))
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
