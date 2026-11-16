"""Revisión de interfaz de 1.3.1: estados deshabilitados visibles, indicador sin despertar al
procesador con la ventana oculta, e icono de aplicación para todas las ventanas."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QPushButton
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); qss = theme.build_global_qss(); app.setStyleSheet(qss)

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1
def settle(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents()

# --- 1) estados deshabilitados en la hoja de estilos ---------------------------------
for sel in ("QPushButton#dialogButton:disabled", "QPushButton#dialogButtonAccent:disabled",
            "QCheckBox:disabled", "QCheckBox::indicator:disabled", "QLineEdit:disabled"):
    check(f"QSS define {sel}", sel in qss)
check(":disabled va DESPUÉS de :hover (si no, el botón deshabilitado reacciona al ratón)",
      qss.index("QPushButton#dialogButton:disabled") > qss.index("QPushButton#dialogButton:hover")
      and qss.index("QPushButton#dialogButtonAccent:disabled") > qss.index("QPushButton#dialogButtonAccent:hover"))

# --- 2) en pantalla un botón deshabilitado SE VE distinto --------------------------------
import onboarding
wiz = onboarding.WelcomeWizard(1234); wiz.show(); settle()
check("asistente, paso 1: «Atrás» está deshabilitado", not wiz.back_btn.isEnabled())
dis = wiz.back_btn.grab().toImage()
wiz.back_btn.setEnabled(True); settle(); en = wiz.back_btn.grab().toImage()
check("«Atrás» deshabilitado se dibuja distinto al habilitado", dis != en)
wiz.close()

# --- 3) el indicador de «sonando» no despierta al procesador si está oculto -------------------
import widgets
theme.apply_accessibility(1.0, False, reduced_motion=False)
host = QPushButton(); ind = widgets.PlayingIndicator(host)       # ventana oculta
ind.set_playing(True)
check("oculto + empieza a sonar: el temporizador NO corre", not ind._timer.isActive())
host.show(); settle()
check("al mostrarse arranca", ind._timer.isActive())
host.hide(); settle()
check("al ocultarse se detiene", not ind._timer.isActive())
host.show(); settle(); ind.set_playing(False)
check("pausado: se detiene", not ind._timer.isActive())
host.hide()

# --- 4) icono de aplicación para todas las ventanas -------------------------------------------
import autostart
autostart.is_supported = lambda: False
from app_controller import AppController
ctrl = AppController(port=54371)
check("QApplication tiene icono (mini, dock y diálogos lo heredan)", not QApplication.windowIcon().isNull())
check("el icono de la ventana principal también", not ctrl.main_window.windowIcon().isNull())

print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
