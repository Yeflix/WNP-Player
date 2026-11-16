"""El diálogo de Ajustes no debe fallar si el puente del tema emite señales DESPUÉS de cerrarse
(en el .exe de Nuitka PyQt no desconectaba solo: «QCheckBox has been deleted»)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from PyQt6 import sip
app = QApplication.instance() or QApplication([])
import dialogs, config

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

class Puente(QObject):
    connectionChanged = pyqtSignal(bool); modesChanged = pyqtSignal(list); modeChanged = pyqtSignal(str)
    is_running = True; is_connected = False; last_error = ""; port = 8977
    def mode(self): return ""
    def modes(self): return [{"id": "a", "name": "A", "desc": ""}]

def nuevo(puente):
    return dialogs.SettingsDialog(config.AppConfig(), 1234, lambda: None, lambda: None, lambda: None, theme_bridge=puente)

b = Puente()
d = nuevo(b)
d.show(); app.processEvents()
b.connectionChanged.emit(True)
check("abierto: la señal del puente actualiza el estado", d.theme_status_label.text() != "")
d.close(); app.processEvents()
check("al cerrar se desconecta de verdad (receivers == 0)", b.receivers(b.connectionChanged) == 0 and b.receivers(b.modesChanged) == 0 and b.receivers(b.modeChanged) == 0)
app.processEvents()
errors = []
old = sys.excepthook; sys.excepthook = lambda *a: errors.append(a)
b.connectionChanged.emit(False); b.modesChanged.emit([]); b.modeChanged.emit("x"); app.processEvents()
sys.excepthook = old
check("emitir tras cerrar no lanza errores", not errors)

# y aunque la señal SIGA conectada (como en Nuitka), el guardián evita el fallo
d2 = nuevo(b)
d2.finished.disconnect(d2._disconnect_theme_bridge)
d2.show(); app.processEvents(); d2.close(); app.processEvents()
check("el diálogo se destruyó", sip.isdeleted(d2) or not d2._theme_widgets_alive())
try:
    d2._refresh_theme_section(); d2._on_theme_modes_changed([]); d2._on_theme_mode_changed("x"); ok = True
except RuntimeError:
    ok = False
check("con widgets destruidos los manejadores no hacen nada (sin RuntimeError)", ok)
print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
