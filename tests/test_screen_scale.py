"""Escala automática según la resolución (screen_scale.py).

    QT_QPA_PLATFORM=offscreen python tests/test_screen_scale.py
"""
import json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Que el entorno de quien corre las pruebas no interfiera con la lógica de prioridad
for k in ("QT_SCALE_FACTOR", "WNP_UI_SCALE"):
    os.environ.pop(k, None)

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

import screen_scale as ss

print("== Función automática (estándar y escalado)")
check("estándar: 1080 útil lógico (Full HD al 100 %) -> 1.00", ss.auto_scale(1040) == 1.0)
check("el rango estándar [660, 1240] no se toca",
      all(ss.auto_scale(h) == 1.0 for h in range(660, 1241, 20)))
check("poco alto (614) se reduce para caber", ss.auto_scale(614) < 1.0, str(ss.auto_scale(614)))
check("muy poco alto (400) se acota a 0.70", ss.auto_scale(400) == 0.70)
check("pantalla grande (1400) se amplía", ss.auto_scale(1400) > 1.0, str(ss.auto_scale(1400)))
check("pantalla enorme (3000) se acota a 1.50", ss.auto_scale(3000) == 1.50)
check("entrada inválida (0 o negativa) -> 1.0", ss.auto_scale(0) == 1.0 and ss.auto_scale(-5) == 1.0)
vals = [ss.auto_scale(h) for h in range(300, 3000, 10)]
check("monótona: más alto útil nunca da MENOS escala", all(a <= b for a, b in zip(vals, vals[1:])))
check("pasos de 0.05", all(abs(round(v / 0.05) * 0.05 - v) < 1e-9 for v in vals))
check("0.8 exacto no cae a 0.75 por coma flotante", ss.auto_scale(660 * 0.8) == 0.80, str(ss.auto_scale(660 * 0.8)))

print("== La ventana más alta cabe (con la constante FIT_HEIGHT real)")
import theme
from harness_free import make_main_height
tallest = make_main_height()
check("FIT_HEIGHT cubre la ventana principal más alta + 48 px", ss.FIT_HEIGHT >= tallest + 48,
      f"ventana={tallest} FIT_HEIGHT={ss.FIT_HEIGHT}")

SCREENS = [  # (ancho físico, alto físico, % de escala de Windows)
    (1280, 720, 100), (1280, 720, 125), (1366, 768, 100), (1366, 768, 125), (1366, 768, 150),
    (1600, 900, 100), (1600, 900, 125), (1920, 1080, 100), (1920, 1080, 125), (1920, 1080, 150),
    (1920, 1200, 100), (2560, 1440, 100), (2560, 1440, 125), (2560, 1440, 150),
    (3840, 2160, 100), (3840, 2160, 150), (3840, 2160, 200), (2880, 1800, 200), (1440, 900, 100),
]
print("== Simulación de pantallas reales")
all_fit, rows = True, []
for pw, ph, pct in SCREENS:
    dpi = round(96 * pct / 100)
    taskbar_phys = round(ss.TASKBAR_LOGICAL * pct / 100)
    _, work_h = ss.logical_work_area(pw, ph - taskbar_phys, dpi)
    f = ss.auto_scale(work_h)
    avail_after = work_h / f
    fits = avail_after >= tallest + 48 or f == ss.MIN_SCALE
    all_fit &= fits
    rows.append(f"{pw}x{ph}@{pct}%: útil={work_h} -> x{f:.2f} (queda {avail_after:.0f}){'' if fits else '  <-- NO CABE'}")
print("   " + "\n   ".join(rows))
check("en TODAS las pantallas la ventana más alta cabe tras escalar", all_fit)
check("estándar sin cambios: 1920x1080@100 y 1366x768@100 y 1920x1200@100",
      all(ss.auto_scale(ss.logical_work_area(w, h - 40, 96)[1]) == 1.0 for w, h in ((1920, 1080), (1366, 768), (1920, 1200))))
check("el caso crítico 1366x768@150 % se reduce", ss.auto_scale(ss.logical_work_area(1366, 768 - 60, 144)[1]) < 1.0)
check("4K@100 % se amplía hasta el tope", ss.auto_scale(ss.logical_work_area(3840, 2160 - 40, 96)[1]) == 1.5)

print("== Prioridades (resolve / configure)")
det = lambda: (1366, 614)
f, src, area = ss.resolve(0.0, det)
check("automática: usa el alto medido", src == "automatica" and f == ss.auto_scale(614) and area == (1366, 614), f"{f} {src}")
check("manual: gana sobre lo medido", ss.resolve(1.25, det)[:2] == (1.25, "manual"))
check("manual fuera de rango se acota", ss.resolve(9.0, det)[0] == 1.5 and ss.resolve(0.1, det)[0] == 0.70)
os.environ["WNP_UI_SCALE"] = "0.9"
check("WNP_UI_SCALE gana sobre todo", ss.resolve(1.25, det)[:2] == (0.9, "WNP_UI_SCALE"))
os.environ["WNP_UI_SCALE"] = "110%"
check("WNP_UI_SCALE acepta porcentaje", ss.resolve(0.0, det)[0] == 1.1)
os.environ["WNP_UI_SCALE"] = "auto"
check("WNP_UI_SCALE=auto no fuerza nada", ss.resolve(0.0, det)[1] == "automatica")
os.environ.pop("WNP_UI_SCALE")
check("sin poder medir -> 1.0 (nunca rompe)", ss.resolve(0.0, lambda: None)[:2] == (1.0, "sin_medicion"))

ss.configure(0.0, det)
check("configure deja QT_SCALE_FACTOR para Qt", os.environ.get("QT_SCALE_FACTOR") == f"{ss.auto_scale(614):.2f}", os.environ.get("QT_SCALE_FACTOR", ""))
os.environ["QT_SCALE_FACTOR"] = "1.7"
ss.configure(0.0, det)
check("si el usuario ya fijó QT_SCALE_FACTOR, se respeta", os.environ["QT_SCALE_FACTOR"] == "1.7" and ss.applied()["source"] == "QT_SCALE_FACTOR")
os.environ.pop("QT_SCALE_FACTOR")
ss.configure(0.0, lambda: (1920, 1040))
check("escala 1.0: no se toca el entorno", "QT_SCALE_FACTOR" not in os.environ)
ss.configure(1.0, det)
check("manual 100 % sobreescribe una pantalla pequeña", "QT_SCALE_FACTOR" not in os.environ)
os.environ.pop("QT_SCALE_FACTOR", None)
ss.configure(0.0, det)
check("describe_auto muestra el porcentaje aplicado y dice qué es",
      ss.describe_auto().startswith("Escala de la interfaz") and "ahora" in ss.describe_auto() and "%" in ss.describe_auto(), ss.describe_auto())
os.environ.pop("QT_SCALE_FACTOR", None)

print("== Medición Windows (lógica; la llamada real a la API solo corre en Windows)")
check("fuera de Windows no mide y no falla", ss.detect_logical_work_area() is None or sys.platform == "win32")
real_platform, real_q = sys.platform, ss._query_primary_work_area_win32
try:
    sys.platform = "win32"
    ss._query_primary_work_area_win32 = lambda: (1366, 720, 144)            # 1366x768@150 %, sin barra de tareas
    check("físico + DPI -> lógico (1366x720 a 144 DPI = 911x480)", ss.detect_logical_work_area() == (911, 480), str(ss.detect_logical_work_area()))
    def boom(): raise OSError("api no disponible")
    ss._query_primary_work_area_win32 = boom
    check("si la API falla -> None (la app arranca igual)", ss.detect_logical_work_area() is None)
    ss._query_primary_work_area_win32 = lambda: None
    check("si no hay monitor -> None", ss.detect_logical_work_area() is None)
finally:
    sys.platform, ss._query_primary_work_area_win32 = real_platform, real_q
check("logical_work_area: 125 % de 1920x1040 -> 1536x832", ss.logical_work_area(1920, 1040, 120) == (1536, 832))

print("== Qt aplica el factor de verdad (subproceso, antes de crear la QApplication)")
SCRIPT = r'''
import json, os, sys
sys.path.insert(0, %r); os.chdir(%r)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv[:1])
scr = app.primaryScreen()
w = QWidget(); w.setFixedSize(300, 100); w.show(); app.processEvents()
out = {"device_w": w.grab().width(), "logical_w": w.width(), "avail_h": scr.availableGeometry().height(), "dpr": scr.devicePixelRatio()}
import theme; theme.apply_accessibility(1.0, False, reduced_motion=True); app.setStyleSheet(theme.build_global_qss())
from backend import WNPBackend; from cover_loader import CoverArtLoader
import main_window as mw
from PyQt6.QtCore import QObject, pyqtSignal
class L(QObject):
    lyricsReady = pyqtSignal(str, object)
    def request(self, *a, **k): pass
m = mw.MainWindow(WNPBackend(), CoverArtLoader(), L()); m.show(); m.set_content_width(mw.MAX_WIDTH); app.processEvents(); app.processEvents()
out["main_h"] = m.height()
print(json.dumps(out))
''' % (ROOT, ROOT)
def run(env_scale):
    env = dict(os.environ); env.pop("WNP_UI_SCALE", None)
    if env_scale: env["QT_SCALE_FACTOR"] = env_scale
    else: env.pop("QT_SCALE_FACTOR", None)
    r = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=env, timeout=120)
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
base = run(None)
half = run("0.8")
check("sin factor: 300 px lógicos = 300 px de pantalla", base["device_w"] == 300 and base["dpr"] == 1.0, str(base))
check("QT_SCALE_FACTOR=0.8: el mismo widget ocupa 240 px de pantalla", half["device_w"] == 240, str(half))
check("y el área útil lógica crece (más espacio en unidades lógicas)", half["avail_h"] > base["avail_h"], f"{base['avail_h']} -> {half['avail_h']}")

# Caso crítico simulado: Windows al 150 % (factor 1.5 de Qt) en una pantalla física de 800 px de alto útil
crit = run("1.5")
check("SIN escala automática la ventana principal NO cabe (el problema original)",
      crit["avail_h"] < crit["main_h"] + 48, f"útil={crit['avail_h']} ventana={crit['main_h']}")
auto = ss.auto_scale(crit["avail_h"])
fixed = run(f"{1.5 * auto:.2f}")
check("CON la escala automática sí cabe", fixed["avail_h"] >= fixed["main_h"] + 48,
      f"factor={auto} útil={fixed['avail_h']} ventana={fixed['main_h']}")

print("== Configuración")
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True); app.setStyleSheet(theme.build_global_qss())
from config import AppConfig
import dialogs
check("AppConfig.ui_scale por defecto = 0.0 (automática)", AppConfig().ui_scale == 0.0)
check("un config.json viejo sin ui_scale carga sin error",
      AppConfig(**{k: v for k, v in AppConfig().__dict__.items() if k != "ui_scale"}).ui_scale == 0.0)
cfg = AppConfig(); d = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None); d.show(); app.processEvents()
check("combo: automática + 6 manuales", d.ui_scale_combo.count() == 1 + len(ss.MANUAL_CHOICES))
check("combo: arranca en Automática", d.ui_scale_combo.currentData() == 0.0)
d.ui_scale_combo.setCurrentIndex(d.ui_scale_combo.findData(1.25))
check("combo: elegir 125 %", d.ui_scale_combo.currentData() == 1.25)
cfg2 = AppConfig(); cfg2.ui_scale = 1.1
d2 = dialogs.SettingsDialog(cfg2, 1234, lambda: None, lambda: None, lambda: None)
check("combo: refleja el valor guardado (110 %)", d2.ui_scale_combo.currentData() == 1.1)
cfg3 = AppConfig(); cfg3.ui_scale = 1.12
d3 = dialogs.SettingsDialog(cfg3, 1234, lambda: None, lambda: None, lambda: None)
check("combo: un valor intermedio cae al más cercano", d3.ui_scale_combo.currentData() == 1.1)
before = d2.ui_scale_combo.currentData()
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QWheelEvent
ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPointF(0, 0).toPoint(), QPointF(0, -120).toPoint(), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(d2.ui_scale_combo, ev)
check("combo: la rueda del mouse no lo cambia", d2.ui_scale_combo.currentData() == before)

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
