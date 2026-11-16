"""El controlador alinea el registro con la configuración (registro simulado)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import autostart
from app_controller import AppController

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

state = {"on": False, "fail": False}
autostart.is_supported = lambda: True
autostart.is_enabled = lambda: state["on"]
def _sync(enabled):
    if state["fail"]:
        return False
    state["on"] = bool(enabled); return True
autostart.sync = _sync

ctrl = AppController(port=54331)
ctrl._apply_start_with_windows(True)
check("activar: registro y configuración activados", state["on"] and ctrl.config.start_with_windows is True)
ctrl._apply_start_with_windows(False)
check("desactivar: registro y configuración desactivados", not state["on"] and ctrl.config.start_with_windows is False)
state["fail"] = True
ctrl._apply_start_with_windows(True)
check("si el registro falla, la configuración no miente", ctrl.config.start_with_windows is False)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
