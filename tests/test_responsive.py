"""Bienvenida y Configuración caben en pantallas pequeñas (portátil con escala
alta) sin cortarse ni desbordarse. Necesita Qt (offscreen)."""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget
app = QApplication.instance() or QApplication(sys.argv)
import config, dialogs, onboarding

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1
def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)

# Tamaños calculados
check("bienvenida: tamaño normal en escritorio", onboarding.fit_size(1920, 1040) == (onboarding.WIDTH, onboarding.HEIGHT))
w, h = onboarding.fit_size(1280 // 1.5, 680 // 1.5)          # 1280×720 al 150 %
check("bienvenida: cabe en un portátil al 150 %", w <= 1280 // 1.5 and h <= 680 // 1.5, f"{w}×{h}")
check("configuración: grande en escritorio", dialogs.settings_size(1920, 1040) == (760, 700))
w, h = dialogs.settings_size(1366 // 1.5, 728 // 1.5)
check("configuración: cabe en un portátil al 150 %", w <= 1366 // 1.5 and h <= 728 // 1.5, f"{w}×{h}")

def inside(widget, top):
    r = widget.rect()
    br = widget.mapTo(top, r.bottomRight())
    tl = widget.mapTo(top, r.topLeft())
    return tl.x() >= 0 and tl.y() >= 0 and br.x() <= top.width() and br.y() <= top.height()

for (sw, sh) in ((520, 450), (760, 700)):
    real = dialogs.settings_size
    dialogs.settings_size = lambda aw, ah, sw=sw, sh=sh: (sw, sh)
    try:
        cfg = config.AppConfig(); cfg.font_scale = 1.3
        d = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None)
        d.show(); pump(0.3)
        sa = d.findChildren(QScrollArea)[0]
        check(f"configuración {sw}×{sh}: sin desborde horizontal", sa.horizontalScrollBar().maximum() == 0,
              f"max={sa.horizontalScrollBar().maximum()}")
        inner = sa.widget()
        wide = [c for c in inner.findChildren(QWidget) if c.isVisibleTo(inner) and c.width() > sa.viewport().width()]
        check(f"configuración {sw}×{sh}: ningún control más ancho que el área", not wide,
              str([type(c).__name__ for c in wide][:5]))
        check(f"configuración {sw}×{sh}: secciones de la barra lateral visibles",
              all(inside(c, d) for c in d._nav_chips))
        # Cada ajuste queda DENTRO de la tarjeta de su sección (antes los últimos
        # campos de una sección se salían por abajo: captura del usuario, 1.5.3).
        rects = inner.card_rects()
        lay = inner.layout()
        outside = []
        for i in range(lay.count()):
            item = lay.itemAt(i)
            wdg = item.widget()
            if (wdg is None and item.layout() is None) or (wdg is not None and wdg.isHidden()):
                continue
            g = item.geometry()
            if g.height() <= 0 or wdg is d._no_results:
                continue
            if not any(r.top() <= g.top() and g.bottom() <= r.bottom() for r in rects):
                outside.append((type(wdg).__name__ if wdg else "fila", g.top(), g.bottom()))
        check(f"configuración {sw}×{sh}: ningún ajuste se sale de su tarjeta", not outside, str(outside[:4]))
        check(f"configuración {sw}×{sh}: las tarjetas no se pisan",
              all(rects[k].bottom() < rects[k + 1].top() for k in range(len(rects) - 1)))
        d.close()
    finally:
        dialogs.settings_size = real

for (ww, wh) in ((360, 420), (540, 600)):
    real = onboarding.fit_size
    onboarding.fit_size = lambda aw, ah, ww=ww, wh=wh: (ww, wh)
    try:
        wz = onboarding.WelcomeWizard(1234); wz.show(); pump(0.2)
        for i in range(wz.stack.count()):
            wz.stack.setCurrentIndex(i); wz.layout().activate(); pump(0.05)
            check(f"bienvenida {ww}×{wh}, paso {i + 1}: botones y textos dentro",
                  inside(wz.next_btn, wz) and inside(wz.stack, wz) and wz.stage.height() >= 100,
                  f"stage={wz.stage.height()} stack={wz.stack.geometry().getRect()}")
        wz.close()
    finally:
        onboarding.fit_size = real
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
