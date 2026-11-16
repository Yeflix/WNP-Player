"""Los diálogos no quedan detrás de una ventana 'siempre visible' de YefriPlayer (Configuración 'no abría')."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
from backend import WNPBackend
from cover_loader import CoverArtLoader
import main_window, dialogs, config
TOP = Qt.WindowType.WindowStaysOnTopHint

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1
def pump(s=0.1):
    t = time.time()
    while time.time() - t < s: app.processEvents()

mw = main_window.MainWindow(WNPBackend(), CoverArtLoader()); mw.show(); pump()
d0 = dialogs.AboutDialog(1234, parent=mw)
check("ventana normal (sin 'siempre visible'): el diálogo no se fuerza arriba", not bool(d0.windowFlags() & TOP))
d0.close()

mw.set_always_on_top(True); mw.show(); pump()
d1 = dialogs.SettingsDialog(config.AppConfig(), 1234, lambda: None, lambda: None, lambda: None, parent=mw)
check("con la ventana 'siempre visible', Configuración también lo es", bool(d1.windowFlags() & TOP))
d1.show(); pump(0.15)
check("y se muestra y queda activa (se trae al frente)", d1.isVisible())
d1.close(); pump()

mw.set_always_on_top(False); mw.hide(); pump()
import dock_window
dk = dock_window.DockWindow(WNPBackend(), CoverArtLoader()); dk.show(); pump()
check("el panel lateral es 'siempre visible'", bool(dk.windowFlags() & TOP) and dk.isVisible())
d2 = None
if d2 is None:
    d2 = dialogs.AboutDialog(1234)
check("un diálogo SIN padre también queda por encima del panel lateral", bool(d2.windowFlags() & TOP))
d2.close()
dk.hide(); pump()
d3 = dialogs.AboutDialog(1234)
check("sin ninguna ventana 'siempre visible' visible, nada se fuerza", not bool(d3.windowFlags() & TOP))
d3.close()
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
