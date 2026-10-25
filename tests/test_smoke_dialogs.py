"""Humo: construye y renderiza controlador, diálogos y asistente (Qt offscreen)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import theme
from config import AppConfig
theme.apply_accessibility(1.0, False)
app.setStyleSheet(theme.build_global_qss())
ok, bad = [], []
def step(name, fn):
    try:
        w = fn()
        if w is not None and hasattr(w, "grab"):
            assert not w.grab().isNull()
        ok.append(name); print("  OK  ", name)
    except Exception as e:
        import traceback; traceback.print_exc()
        bad.append(name); print("  FALLA", name, repr(e))
import dialogs, onboarding, weekly_recap
from backend import WNPBackend
cfg = AppConfig()
step("PortDialog", lambda: dialogs.PortDialog(1234))
step("AboutDialog", lambda: dialogs.AboutDialog(1234))
step("MessageDialog", lambda: dialogs.MessageDialog("t", "cuerpo", accent_button_text="Ok"))
step("ErrorDialog", lambda: dialogs.ErrorDialog("detalle"))
entries = [{"title": f"T{i}", "artist": f"A{i}", "player": "YouTube", "timestamp": time.time() - i * 3600, "duration": 200} for i in range(12)]
step("HistoryDialog", lambda: dialogs.HistoryDialog(entries))
step("RecentlyPlayedDialog", lambda: dialogs.RecentlyPlayedDialog(entries, True))
step("StatsDialog", lambda: dialogs.StatsDialog(entries))
step("WelcomeWizard", lambda: onboarding.WelcomeWizard(1234))
from app_controller import AppController
step("AppController (construcción completa)", lambda: AppController(port=54321))
print(f"RESULTADO: {len(ok)} ok, {len(bad)} fallas"); sys.exit(1 if bad else 0)
