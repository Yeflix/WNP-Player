"""Configuración legible + botón play del dock (Qt offscreen).

    QT_QPA_PLATFORM=offscreen python tests/test_settings_dialog.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QScrollArea
from PyQt6.QtGui import QPalette, QColor

app = QApplication(sys.argv)
PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

# Tema hostil del sistema: texto y fondo oscuros (lo que producía letras invisibles).
hostile = QPalette()
for r in (QPalette.ColorRole.Base, QPalette.ColorRole.Window, QPalette.ColorRole.Button, QPalette.ColorRole.AlternateBase):
    hostile.setColor(r, QColor(8, 8, 8))
for r in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
    hostile.setColor(r, QColor(20, 20, 20))
app.setPalette(hostile)

import theme
from theme import Palette
theme.apply_dark_palette(app)
theme.apply_accessibility(1.3, True)
app.setStyleSheet(theme.build_global_qss())

print("== Paleta")
pal = app.palette()
for role, name in ((QPalette.ColorRole.Text, "Text"), (QPalette.ColorRole.WindowText, "WindowText"), (QPalette.ColorRole.ButtonText, "ButtonText")):
    c = pal.color(role)
    ratio = theme.contrast_ratio((c.red(), c.green(), c.blue()), Palette.BG_PANEL)
    check(f"paleta oscura: {name} legible sobre el panel", ratio >= 4.5, f"{ratio:.1f}")

print("== Configuración")
from config import AppConfig
import dialogs, widgets
cfg = AppConfig(); cfg.high_contrast = True; cfg.font_scale = 1.3
d = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None)
d.show(); app.processEvents()
sa = d.findChildren(QScrollArea)[0]
check("sin desborde horizontal", sa.horizontalScrollBar().maximum() == 0, f"max={sa.horizontalScrollBar().maximum()}")
check("todos los combos son ArrowComboBox", all(isinstance(c, widgets.ArrowComboBox) for c in
      (d.font_scale_combo, d.dock_edge_combo, d.dock_style_combo, d.dock_hide_combo, d.scrobble_combo)))

def rawpx(img, x, y):
    """Color del píxel REAL (x, y) de la imagen, sin conversión de escala."""
    c = img.pixelColor(x, y); return (c.red(), c.green(), c.blue())

def px(img, x, y):
    # Las coordenadas son LÓGICAS; la captura tiene devicePixelRatio píxeles por
    # unidad lógica (distinto de 1 bajo QT_SCALE_FACTOR), así que se convierten.
    k = img.devicePixelRatio()
    c = img.pixelColor(min(img.width() - 1, int(x * k)), min(img.height() - 1, int(y * k)))
    return (c.red(), c.green(), c.blue())

sa.ensureWidgetVisible(d.dock_edge_combo, 10, 60); app.processEvents()
img = d.grab().toImage()
combo = d.dock_edge_combo
top_left = combo.mapTo(d, combo.rect().topLeft())
inside = px(img, top_left.x() + 6, top_left.y() + combo.height() // 2)
outside = px(img, top_left.x() - 8, top_left.y() + combo.height() // 2)
check("el combo tiene fondo/borde propio (antes 'background: transparent' lo borraba)",
      inside != outside, f"dentro={inside} fuera={outside}")

# Texto del combo: debe haber píxeles claros (texto) sobre el fondo oscuro.
def brightest(img, x0, y0, w, h):
    return max(sum(px(img, x, y)) / 3 for x in range(x0, x0 + w) for y in range(y0, y0 + h))
b = brightest(img, top_left.x() + 8, top_left.y() + 4, combo.width() - 40, combo.height() - 8)
check("texto del combo claro sobre fondo oscuro", b >= 180, f"brillo máx {b:.0f}")

print("== Lista desplegable")
combo.showPopup(); app.processEvents()
view = combo.view()
pimg = view.window().grab().toImage()
lum = [sum(rawpx(pimg, x, y)) / 3 for y in range(pimg.height()) for x in range(pimg.width())]
bg_lum = sorted(lum)[len(lum) // 2]
light_px = sum(1 for v in lum if v >= 180)
check("lista: hay texto claro sobre fondo oscuro", bg_lum < 80 and light_px > 40, f"fondo={bg_lum:.0f} px claros={light_px}")
# Cada fila (no solo la resaltada) debe tener texto visible.
rows_ok, detail = True, []
h = pimg.height() // max(1, combo.count())
for i in range(combo.count()):
    row_b = max(sum(rawpx(pimg, x, y)) / 3 for x in range(8, pimg.width() - 8) for y in range(i * h + 4, min(pimg.height(), (i + 1) * h - 2)))
    rows_ok &= row_b >= 160
    detail.append(round(row_b))
check("lista: TODAS las opciones se leen (antes solo la resaltada)", rows_ok, f"brillo por fila={detail} imagen={pimg.width()}x{pimg.height()} dpr={pimg.devicePixelRatio()}")
combo.hidePopup()

print("== ArrowComboBox: texto largo")
long_combo = widgets.ArrowComboBox()
long_combo.addItem("Se abre y cierra solo (al pasar/alejar el mouse)", "x")
long_combo.resize(140, 34); long_combo.show(); app.processEvents()
check("combo con texto largo pinta sin errores", not long_combo.grab().isNull())
check("el ancho pedido no depende del texto más largo", long_combo.sizeHint().width() < 300, str(long_combo.sizeHint().width()))
check("tooltip con el texto completo", long_combo.toolTip().startswith("Se abre y cierra solo"))

print("== Dock: botón play/pausa")
from backend import WNPBackend
from cover_loader import CoverArtLoader
import dock_window as dk
be = WNPBackend(); calls = []
be.toggle_play_pause = lambda: calls.append("toggle")
dock = dk.DockWindow(be, CoverArtLoader()); dock.show(); app.processEvents()
try:
    dock._on_play_clicked()
    ok = calls == ["toggle"]; err = ""
except Exception as e:     # antes: AttributeError 'WNPBackend' object has no attribute 'pause'
    ok = False; err = repr(e)
check("clic en play del dock llama a toggle_play_pause (sin AttributeError)", ok, err)
# Cambio intencional: sin canción el play queda activo (abre Spotify/YouTube); con
# el ajuste "No hacer nada" vuelve a desactivarse.
check("sin canción el play del dock está activo (abre Spotify/YouTube)", dock.play_btn.isEnabled())
dock.set_play_idle_enabled(False)
check("con 'No hacer nada' el play del dock está deshabilitado", not dock.play_btn.isEnabled())
dock.play_btn.setEnabled(True); dock.play_btn.click(); app.processEvents()
check("el botón conectado también lo dispara", calls == ["toggle", "toggle"], str(calls))
check("el backend no necesita pause()/play()", not hasattr(be, "pause") and not hasattr(be, "play"))

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
