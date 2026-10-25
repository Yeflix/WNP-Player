"""Regresiones de la ronda de revisión 3.

    QT_QPA_PLATFORM=offscreen python tests/test_fixes_ronda3.py
"""
import json, os, socket, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="wnp_r3_")
os.environ["XDG_CONFIG_HOME"] = TMP           # aislado: no toca datos reales
os.environ["LOCALAPPDATA"] = TMP

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True)
app.setStyleSheet(theme.build_global_qss())

def run(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

import history, error_handling, pywnp_patch
from config import AppConfig
from backend import WNPBackend, PlayerState
from app_controller import AppController

def st(title, artist, **kw):
    base = dict(connected=True, player_name="YouTube", state="PLAYING", title=title, artist=artist,
                duration="3:20", duration_seconds=200, can_play_pause=True)
    base.update(kw)
    return PlayerState(**base)

# ------------------------------------------------------------------ 1
print("== 1) Cambio de canción: título y artista llegan en mensajes separados")
ctrl = AppController(port=54401)
sent = []
ctrl.scrobbler.track_changed = lambda *a, **k: sent.append(a)
ctrl.config.notifications_enabled = False
ctrl._on_playback_state_changed(st("Song B", "Artist A"))     # lectura a medias
run(150)
ctrl._on_playback_state_changed(st("Song B", "Artist A", position_seconds=1))  # solo cambia la posición
run(150)
ctrl._on_playback_state_changed(st("Song B", "Artist B"))     # llega el artista real
run(ctrl.TRACK_SETTLE_MS + 300)
titles = [(e["title"], e["artist"]) for e in history.load()]
check("solo se registra la canción completa", titles == [("Song B", "Artist B")], str(titles))
check("a Last.fm solo llega la canción completa", [(s[0], s[1]) for s in sent] == [("Artist B", "Song B")], str(sent))

ctrl._on_playback_state_changed(st("Song C", "Artist C"))
run(100)
ctrl._on_playback_state_changed(st("Song B", "Artist B"))     # vuelve a la ya registrada antes de asentarse
run(ctrl.TRACK_SETTLE_MS + 300)
check("volver a la canción registrada cancela el pendiente",
      [e["title"] for e in history.load()] == ["Song B"], str([e["title"] for e in history.load()]))

# ------------------------------------------------------------------ 2
print("== 2) Historial: un fallo de lectura no borra lo guardado")
history.clear()
for i in range(5):
    history.add_entry(f"Canción {i}", "Artista", "YouTube", 200)
real_read = Path.read_text
state = {"fail": True}
def flaky(self, *a, **k):
    if self.name == "history.json" and state["fail"]:
        state["fail"] = False
        raise PermissionError("bloqueado")
    return real_read(self, *a, **k)
Path.read_text = flaky
history.add_entry("Nueva", "Artista", "YouTube", 200)
Path.read_text = real_read
check("sigue habiendo 5 entradas tras el fallo", len(history.load()) == 5, str(len(history.load())))
history.add_entry("Nueva", "Artista", "YouTube", 200)
check("y la siguiente escritura funciona con normalidad", len(history.load()) == 6)
hp = history._history_path()
hp.write_text("{esto no es json", encoding="utf-8")
history.add_entry("Tras corrupción", "A", "YouTube", 100)
check("JSON corrupto: se empieza de nuevo", [e["title"] for e in history.load()] == ["Tras corrupción"])
check("y se conserva copia del archivo dañado", hp.with_name(hp.name + ".corrupt").exists())

# ------------------------------------------------------------------ 3
print("== 3) Cambio de puerto a uno ocupado")
b = WNPBackend(port=54411)
errs = []
b.serverError.connect(errs.append)
b.start()
check("el servidor arranca", b.is_running)
busy = socket.socket(); busy.bind(("127.0.0.1", 54412)); busy.listen(1)
ok = b.restart_on_port(54412)
check("restart_on_port devuelve False", ok is False)
check("el servidor anterior sigue vivo en su puerto", b.is_running and b.port == 54411)
check("se avisó del puerto ocupado", any("54412" in e for e in errs), str(errs))
busy.close()
ok = b.restart_on_port(54413)
check("a un puerto libre sí se mueve", ok is True and b.port == 54413 and b.is_running)
b.stop()

ctrl2 = AppController(port=54421)
ctrl2.backend.start()
busy = socket.socket(); busy.bind(("127.0.0.1", 54422)); busy.listen(1)
ctrl2._change_port(54422)
check("el puerto ocupado NO se guarda en la config", AppConfig.load().port != 54422, str(AppConfig.load().port))
busy.close()
ctrl2._change_port(54423)
check("el libre sí se guarda", AppConfig.load().port == 54423)
ctrl2.backend.stop()

# ------------------------------------------------------------------ 4
print("== 4) Posiciones de ventanas nunca mostradas")
ctrl3 = AppController(port=54431)
cfg = AppConfig.load(); cfg.main_x = cfg.main_y = cfg.mini_x = cfg.mini_y = None; cfg.save()
ctrl3.config = AppConfig.load()
ctrl3._save_config()
cfg = AppConfig.load()
check("no se guarda (0, 0) de ventanas sin mostrar", (cfg.main_x, cfg.mini_x) == (None, None), str((cfg.main_x, cfg.mini_x)))
cfg.main_x = cfg.main_y = cfg.mini_x = cfg.mini_y = 0; cfg.save()
ctrl4 = AppController(port=54432)
check("un (0, 0) heredado de versiones anteriores se ignora al restaurar",
      not ctrl4._main_positioned and not ctrl4._mini_positioned)

# ------------------------------------------------------------------ 5
print("== 5) Directos / sin duración: la barra no se llena")
from pywnp.pywnp import WNPRedux, MediaInfo
b2 = WNPBackend(); b2._wnp = WNPRedux; b2._running = True
mi = MediaInfo(); mi._id = "x"; WNPRedux.media_info = mi
mi.player_name = "YouTube"; mi.state = "PLAYING"; mi.title = "Directo"
mi.duration_seconds = 0; mi.position_seconds = 3600; mi.position_percent = 100
got = []; b2.stateChanged.connect(got.append); b2._poll()
check("position_percent = 0 sin duración conocida", got[0].position_percent == 0.0, str(got[0].position_percent))
mi.duration_seconds = 200; mi.position_seconds = 100; mi.position_percent = 50
b2._poll()
check("con duración conocida se respeta el valor real", got[-1].position_percent == 50.0, str(got[-1].position_percent))

# ------------------------------------------------------------------ 6
print("== 6) pywnp_patch.apply() no rompe si pywnp cambia")
import pywnp.pywnp as impl
saved = impl.time_in_seconds_to_string
del impl.time_in_seconds_to_string
raised = None
try:
    pywnp_patch._patched = False
    pywnp_patch.apply()
except Exception as exc:
    raised = exc
impl.time_in_seconds_to_string = saved
check("no lanza si falta un helper interno", raised is None, repr(raised))
orig_impl = pywnp_patch._apply_impl
def boom(): raise RuntimeError("estructura interna distinta")
pywnp_patch._apply_impl = boom
pywnp_patch._patched = False
raised = None
try:
    pywnp_patch.apply()
except Exception as exc:
    raised = exc
pywnp_patch._apply_impl = orig_impl
check("ni ante un fallo inesperado dentro del parche", raised is None, repr(raised))
check("y queda marcado como aplicado (no se envuelve dos veces)", pywnp_patch._patched is True)

# ------------------------------------------------------------------ 7
print("== 7) Manejador de errores: sin tormenta de diálogos")
error_handling._last_dialog_at.clear(); error_handling._dialog_open = False
sig = ("RuntimeError", "fallo repetido")
check("el primer error se muestra", error_handling._should_show_dialog(sig, now=100.0))
check("el mismo error enseguida NO", not error_handling._should_show_dialog(sig, now=101.0))
check("otro error distinto sí", error_handling._should_show_dialog(("ValueError", "otro"), now=101.0))
check("el mismo tras el enfriamiento sí", error_handling._should_show_dialog(sig, now=100.0 + error_handling._DIALOG_COOLDOWN_S + 1))
error_handling._dialog_open = True
check("con un diálogo abierto no se apila otro", not error_handling._should_show_dialog(("X", "y"), now=1000.0))
error_handling._dialog_open = False

# ------------------------------------------------------------------ 8
print("== 8) Last.fm por https y cierre idempotente")
import scrobbling
check("API de Last.fm por https", scrobbling._LASTFM_API_URL.startswith("https://"))
ctrl5 = AppController(port=54441)
ctrl5.shutdown(); ctrl5.shutdown()
check("shutdown() se puede llamar dos veces", ctrl5._shut_down is True)

print(f"\n{len(PASS)} OK, {len(FAIL)} fallos")
sys.exit(1 if FAIL else 0)
