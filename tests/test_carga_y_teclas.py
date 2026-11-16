"""Pantalla de carga 3D (splash.py) y aviso de teclas rápidas ocupadas
(hotkeys.HotkeyManager.failures). Necesita Qt (offscreen)."""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import theme, splash, hotkeys

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1
def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)

# --- teclas ocupadas --------------------------------------------------------------
mgr = hotkeys.HotkeyManager(); mgr.available = True
real = hotkeys._win_register
def fake(hid, mods, vk):
    ok = vk != ord("X")
    hotkeys._LAST_ERROR[0] = 0 if ok else hotkeys.ERROR_HOTKEY_ALREADY_REGISTERED
    return ok
hotkeys._win_register = fake
hotkeys._win_unregister = lambda hid: None
try:
    check("Ctrl+Shift+C se activa", mgr.register("next", "ctrl+shift+c") and "next" not in mgr.failures)
    check("Ctrl+Shift+X ocupada: se recuerda y se dice por qué",
          not mgr.register("previous", "ctrl+shift+x")
          and mgr.failures.get("previous") == ("ctrl+shift+x", "otro programa ya usa esta combinación"))
    check("al cambiarla por otra libre, el aviso desaparece",
          mgr.register("previous", "ctrl+shift+z") and "previous" not in mgr.failures)
    mgr.register("previous", "ctrl+shift+x"); mgr.unregister_all()
    check("desactivar todas limpia los avisos", mgr.failures == {})
finally:
    hotkeys._win_register = real
check("texto del motivo", "otro programa" in hotkeys.failure_reason(1409) and "error 5" in hotkeys.failure_reason(5))

# --- pantalla de carga ----------------------------------------------------------------
theme.REDUCED_MOTION = False
s = splash.Splash(); s.show(); pump(0.2)
check("la escena anima mientras carga", s.stage._clock.isActive())
mod = os.path.join(tmp, "modulo_lento.py")
open(mod, "w").write("import time\ntime.sleep(0.4)\nVALOR = 1\n")
sys.path.insert(0, tmp)
paints = []
real_update = s.stage.update
s.stage.update = lambda *a: (paints.append(1), real_update(*a))
t0 = time.time(); splash.import_with_splash("modulo_lento", s)
check("importa en segundo plano y la escena sigue repintándose", len(paints) >= 5 and time.time() - t0 >= 0.35,
      f"{len(paints)} repintados")
s.morph_into(QRect(200, 120, 356, 520)); pump(0.05)
check("al transformarse la escena deja de animarse (imagen congelada)", not s.stage._clock.isActive())
pump(splash.MORPH_MS / 1000 + 0.3)
check("la transformación termina y la pantalla de carga desaparece", s.finished and not s.isVisible())
s2 = splash.Splash(); s2.show(); pump(0.1); s2.morph_into(None); pump(splash.MORPH_MS / 1000 + 0.3)
check("sin ventana (arranque en la bandeja): se encoge y se va", s2.finished)
theme.REDUCED_MOTION = True
s3 = splash.Splash(); s3.show(); pump(0.1); s3.morph_into(QRect(0, 0, 100, 100))
check("reducir movimiento: se cierra sin animación", s3.finished)
theme.REDUCED_MOTION = False
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main.py"), encoding="utf-8").read()
check("main.py: instancia única ANTES de la pantalla de carga",
      src.index("guard.try_acquire()") < src.index("Splash()"))
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
