"""Bienvenida simple y animada (welcome_fx + onboarding): la escena 3D se ajusta
al espacio y solo anima mientras se ve, el giro entre pasos deja la página
correcta, el paso final celebra y «reducir movimiento» lo deja todo quieto.
Necesita Qt (se ejecuta sin pantalla, offscreen)."""
import math, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import theme, onboarding, welcome_fx

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1
def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)
FLIP = welcome_fx.PageFlip.DURATION_MS / 1000 + 0.25

# --- escena: cabe entera con cualquier giro de cámara y tamaño
stage = welcome_fx.SoundStage()
for w, h in ((520, 220), (360, 110), (700, 300)):
    scale, cx, cy = stage.fit(w, h)
    ys, xs = [], []
    for yaw in (-18, 0, 18):
        for pitch in (stage.PITCH - 4, stage.PITCH + 4):
            cam = welcome_fx.Camera(cx, cy, scale * stage.DISTANCE, stage.DISTANCE, yaw, pitch)
            for a in range(0, 360, 10):
                for r, y in ((stage.WAVE_MAX, 0), (1.45, stage.BAR_MAX), (1.6, stage.NOTE_TOP)):
                    x2, y2, _ = cam.project(r * math.cos(math.radians(a)), y, r * math.sin(math.radians(a)))
                    xs.append(x2); ys.append(y2)
    check(f"la escena cabe en {w}×{h}", min(xs) >= -1 and max(xs) <= w + 1 and min(ys) >= -1 and max(ys) <= h + 1,
          f"x {min(xs):.0f}..{max(xs):.0f} y {min(ys):.0f}..{max(ys):.0f}")
lv = welcome_fx.beat_levels(0.0, 30)
check("ecualizador: 30 niveles entre 0 y 1", len(lv) == 30 and all(0 < v <= 1 for v in lv))
check("ecualizador: late (en el golpe sube más que a mitad de compás)",
      sum(welcome_fx.beat_levels(0.0, 30)) > sum(welcome_fx.beat_levels(0.4, 30)))

theme.REDUCED_MOTION = False
w = onboarding.WelcomeWizard(1234); w.show(); pump(0.3)
check("la escena anima con la ventana visible", w.stage._clock.isActive())
w._go_next(); pump(0.05)
check("al avanzar gira la página y la real queda oculta", w._flip.isVisible() and w._page_opacity.isEnabled())
pump(FLIP)
check("tras el giro: paso 2 visible y sin efecto de opacidad",
      w.stack.currentIndex() == 1 and not w._flip.isVisible() and not w._page_opacity.isEnabled())
w._go_next(); pump(FLIP)
check("paso final: las teclas se pulsan solas y la escena se anima más",
      w._key_timer.isActive() and w.stage._energy_target > 1.0)
check("paso final: confeti", w._confetti.isVisible())
pump(welcome_fx.Confetti.DURATION_S + 0.3)
check("el confeti se apaga solo", not w._confetti.isVisible() and not w._confetti._clock.isActive())
w._go_back(); pump(FLIP)
check("al volver atrás dejan de pulsarse", not w._key_timer.isActive())
w.hide(); pump(0.1)
check("oculta: nada anima", not w.stage._clock.isActive() and not w._key_timer.isActive())
w.close()

# --- comprobación en vivo de la extensión (paso 2) -----------------------------
class FakeBackend:
    def __init__(self):
        self.info = {"running": True, "port": 1234, "browsers": 0, "has_media": False,
                     "title": "", "artist": "", "player": ""}
    def connection_info(self): return dict(self.info)
fb = FakeBackend()
w3 = onboarding.WelcomeWizard(1234, backend=fb); w3.show(); pump(0.2)
w3._go_next(); pump(FLIP)
check("paso 2: se comprueba la extensión mientras se ve", w3._status_timer.isActive() and w3.status_pill.isVisible())
check("sin conexión: «esperando»", w3.status_pill.kind == "waiting")
fb.info["browsers"] = 1; pump(0.7)
check("extensión conectada: «conectada»", w3.status_pill.kind == "connected")
fb.info.update(has_media=True, title="Canción", artist="Artista"); pump(0.7)
check("con música del navegador: «¡funciona!» y la escena lo celebra",
      w3.status_pill.kind == "ok" and "Canción" in w3.status_pill.text.text() and w3.stage._energy_target > 1.0)
w3._go_next(); pump(FLIP)
check("al salir del paso deja de comprobar", not w3._status_timer.isActive())
w3.close()
_w4 = onboarding.WelcomeWizard(1234)
check("sin backend no hay indicador ni botón de prueba", _w4.status_pill.isHidden() and _w4.test_btn.isHidden())
_w4.close()
check("puerto ocupado → aviso claro", onboarding.extension_status({"running": False, "port": 1234})[0] == "error")
check("Spotify de escritorio → detectado aunque falte el navegador",
      onboarding.extension_status({"running": True, "port": 1234, "browsers": 0, "has_media": True,
                                   "title": "T", "artist": "", "player": "Spotify"})[0] == "desktop")

theme.REDUCED_MOTION = True
w2 = onboarding.WelcomeWizard(1234); w2.show(); pump(0.2)
check("reducir movimiento: la escena no anima", not w2.stage._clock.isActive())
w2._go_next(); pump(0.05)
check("reducir movimiento: cambio de paso inmediato", w2.stack.currentIndex() == 1 and not w2._flip.isVisible())
w2._confetti.burst()
check("reducir movimiento: sin confeti", not w2._confetti.isVisible())
w2.close()
theme.REDUCED_MOTION = False
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
