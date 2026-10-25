"""Letras: limpieza de títulos, elección del resultado correcto, reintento,
recarga forzada, botón de recarga y espera ante metadatos a medias.

    QT_QPA_PLATFORM=offscreen python tests/test_lyrics_robustez.py
"""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="wnp_lyr_")

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

from PyQt6.QtCore import QObject, QThreadPool, pyqtSignal, QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True)
app.setStyleSheet(theme.build_global_qss())

import lyrics as L

def run(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

# ------------------------------------------------------------------ 1
print("== 1) Limpieza de títulos de YouTube")
check("quita (Official Video)", L.clean_title("Song (Official Video)") == "Song")
check("quita [HD] y comillas ''", L.clean_title("SE ''Shall Never Surrender'' [HD]") == "SE Shall Never Surrender",
      L.clean_title("SE ''Shall Never Surrender'' [HD]"))
check("quita - Official Audio al final", L.clean_title("Song - Official Audio") == "Song")
check("NO toca paréntesis que son del título", L.clean_title("Song (Part II)") == "Song (Part II)")
check("artista '- Topic'", L.clean_artist("Daft Punk - Topic") == "Daft Punk")
check("artista 'XVEVO'", L.clean_artist("QueenVEVO") == "Queen")
c = L.query_candidates("ArtistVEVO", "Artist - Song Name (Lyrics) ft. Someone")
check("separa 'Artista - Canción' del título", ("Artist", "Song Name ft. Someone") in c, str(c))
check("y prueba sin 'feat.'", ("Artist", "Song Name") in c, str(c))
check("la primera variante es la original", c[0] == ("ArtistVEVO", "Artist - Song Name (Lyrics) ft. Someone"))

# ------------------------------------------------------------------ 2
print("== 2) Elegir el resultado que de verdad es la canción")
def entry(name, artist, dur, plain="letra", synced=""):
    return {"trackName": name, "artistName": artist, "duration": dur, "plainLyrics": plain,
            "syncedLyrics": synced, "instrumental": False}
data = [entry("Otra Canción Distinta", "Otro Artista", 310, "letra equivocada"),
        entry("One More Time", "Daft Punk", 320, "letra correcta", "[00:01.00]hola")]
best = L._best_entry(data, "Daft Punk", "One More Time", 320)
check("salta el primer resultado si no se parece", best and best["plain"] == "letra correcta", str(best))
check("si nada se parece, devuelve None (antes: letra de otra canción)",
      L._best_entry([entry("Zzzz", "Qqqq", 100, "x")], "Daft Punk", "One More Time", 320) is None)
check("misma canción pero duración muy distinta se descarta",
      L._best_entry([entry("One More Time", "Daft Punk", 600, "x")], "Daft Punk", "One More Time", 320) is None)
check("sin duración conocida igual acepta la que coincide por nombre",
      L._best_entry([entry("One More Time", "Daft Punk", 320, "ok")], "Daft Punk", "One More Time", 0) is not None)
check("prefiere la sincronizada a igualdad",
      L._best_entry([entry("A Song", "X", 200, "p1"), entry("A Song", "X", 200, "p2", "[00:01.00]s")],
                    "X", "A Song", 200)["synced"] is not None)

# ------------------------------------------------------------------ 3
print("== 3) _fetch con la red simulada")
L._RETRY_DELAY_S = 0
calls = []
def fake_http(responses):
    seq = list(responses)
    def f(url):
        calls.append(url)
        return seq.pop(0) if seq else (None, None)
    return f

# a) el 'get' exacto falla (404) y la búsqueda difusa trae la buena entre ruido
L._http_get_json = fake_http([(None, None), (None, None), (data, None)])
calls.clear()
r = L._fetch("Daft Punk - Topic", "One More Time (Official Video)", "", 320)
check("título sucio: acaba encontrando la letra correcta", isinstance(r, dict) and r.get("plain") == "letra correcta", str(r))

# b) fallo puntual y éxito al reintentar
L._http_get_json = fake_http([(None, "timeout"), ({"plainLyrics": "ok", "syncedLyrics": "", "instrumental": False}, None)])
calls.clear()
r = L._fetch("Queen", "Bohemian Rhapsody", "", 355)
check("un fallo puntual se reintenta solo", isinstance(r, dict) and r.get("plain") == "ok" and len(calls) == 2, f"{r} / {len(calls)} llamadas")

# c) caído del todo: error, sin lanzar decenas de peticiones
L._http_get_json = fake_http([(None, "sin conexión")] * 50)
calls.clear()
r = L._fetch("Queen", "Bohemian Rhapsody", "", 355)
check("sin red: devuelve error", isinstance(r, dict) and "error" in r, str(r))
check("sin red: no se queda reintentando indefinidamente", len(calls) <= 6, f"{len(calls)} llamadas")

# d) no existe
L._http_get_json = fake_http([])        # todo 404 / vacío
r = L._fetch("Nadie", "Nada Inventada", "", 100)
check("no existe: None (no error)", r is None, str(r))

# ------------------------------------------------------------------ 4
print("== 4) LyricsLoader: recarga forzada ignora la caché")
fetch_calls = []
def fake_fetch(artist, title, album="", dur=0):
    fetch_calls.append((artist, title))
    return None if len(fetch_calls) == 1 else {"plain": "ya está", "synced": None, "instrumental": False}
L._fetch = fake_fetch
loader = L.LyricsLoader()
got = []
loader.lyricsReady.connect(lambda k, r: got.append(r))
loader.request("A", "T", "", 100)
QThreadPool.globalInstance().waitForDone(); run(50)
check("primera consulta: 'no encontrada' (None)", got == [None], str(got))
loader.request("A", "T", "", 100)
QThreadPool.globalInstance().waitForDone(); run(50)
check("sin force sale de la caché (no vuelve a consultar)", len(fetch_calls) == 1 and got == [None, None])
loader.request("A", "T", "", 100, force=True)
QThreadPool.globalInstance().waitForDone(); run(50)
check("con force=True vuelve a consultar y encuentra", len(fetch_calls) == 2 and got[-1] and got[-1]["plain"] == "ya está", str(got))

# ------------------------------------------------------------------ 5
print("== 5) LyricsPanel: botón de recarga y espera")
from widgets import LyricsPanel
class FakeLoader(QObject):
    lyricsReady = pyqtSignal(str, object)
    def __init__(self): super().__init__(); self.calls = []
    def request(self, artist, title, album="", duration_seconds=0, force=False):
        self.calls.append((artist, title, force))
fl = FakeLoader()
panel = LyricsPanel(fl)
panel.show(); app.processEvents()
panel.set_track("Queen", "Bohemian Rhapsody", "", 355)
key = L._cache_key("Queen", "Bohemian Rhapsody")
panel._on_ready(key, {"error": "No se pudo conectar"})
check("error: aparece el botón de recarga", panel.reload_btn.isVisibleTo(panel))
panel._on_ready(key, None)
check("no encontrada: también", panel.reload_btn.isVisibleTo(panel))
panel.reload_btn.click()
check("clic en recarga: pide de nuevo con force=True", fl.calls[-1] == ("Queen", "Bohemian Rhapsody", True), str(fl.calls))
check("al recargar muestra 'buscando' y oculta el botón", not panel.reload_btn.isVisibleTo(panel))
panel._on_ready(key, {"plain": "letra", "synced": None, "instrumental": False})
check("con letra encontrada no hay botón", not panel.reload_btn.isVisibleTo(panel))

fl.calls.clear()
panel.set_track_debounced("Queen", "Bohemian Rhapsody", "", 355)
check("misma canción ya cargada: no vuelve a pedir", fl.calls == [])
fresh = LyricsPanel(fl)
fresh.set_track_debounced("Primera", "Carga", "", 100)
check("primera carga: inmediata (sin esperar)", fl.calls == [("Primera", "Carga", False)], str(fl.calls))
fl.calls.clear()
panel.set_track_debounced("Artista Viejo", "Canción Nueva", "", 200)    # título nuevo, artista a medias
run(150)
panel.set_track_debounced("Artista Nuevo", "Canción Nueva", "", 200)    # llega el artista real
run(200)
check("durante la espera no se ha buscado nada", fl.calls == [], str(fl.calls))
run(450)
check("pasada la espera se busca UNA vez, con los datos completos",
      fl.calls == [("Artista Nuevo", "Canción Nueva", False)], str(fl.calls))
panel.set_track_debounced("", "", "", 0)
check("vaciar la canción es inmediato", not panel.reload_btn.isVisibleTo(panel) and panel._cur is None)

print(f"\n{len(PASS)} OK, {len(FAIL)} fallos")
sys.exit(1 if FAIL else 0)
