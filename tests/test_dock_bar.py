"""Barra vertical del panel lateral (dock): botones, ondas y hover (Qt offscreen).

    QT_QPA_PLATFORM=offscreen python tests/test_dock_bar.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app)
theme.apply_accessibility(1.0, False, reduced_motion=False)
app.setStyleSheet(theme.build_global_qss())

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)
def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents()

from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
import dock_window as dk

be = WNPBackend(); loader = CoverArtLoader()
calls = []
be.toggle_play_pause = lambda: calls.append("play")
be.next = lambda: calls.append("next")
be.previous = lambda: calls.append("prev")

def state(playing=True):
    return PlayerState(connected=True, player_name="Spotify", state="PLAYING" if playing else "PAUSED",
                       title="T", artist="A", duration="3:20", duration_seconds=200, position_percent=20.0,
                       can_play_pause=True, can_prev=True, can_next=True, can_seek=True)

def make(style, edge):
    d = dk.DockWindow(be, loader)
    d.set_style(style); d.set_edge(edge); d.show(); app.processEvents()
    d._reposition(animate=False)        # como la app: colocado en su borde de pantalla
    d.apply_state(state(True)); pump(0.05)
    return d

def bar_widgets(d, style):
    if style == "card":
        return [d.bar_toggle_btn, d.bar_restore_btn, d.bar_prev_btn, d.bar_play_btn, d.bar_next_btn, d.handle_icon]
    return [d.bar_toggle_btn, d.bar_play_btn, d.bar_next_btn]

for style in ("card", "compact"):
    for edge in ("right", "left"):
        tag = f"[{style}/{edge}]"
        d = make(style, edge)
        zone = d._handle_zone().toRect()
        ws = bar_widgets(d, style)
        check(f"{tag} todos los botones de la pestaña visibles", all(w.isVisibleTo(d) for w in ws))
        inside = all(zone.contains(QRect(w.pos(), w.size())) for w in ws)
        check(f"{tag} quedan dentro de la pestaña", inside,
              str([(type(w).__name__, w.geometry().getRect()) for w in ws if not zone.contains(QRect(w.pos(), w.size()))]))
        rects = [QRect(w.pos(), w.size()) for w in ws]
        overlap = any(rects[i].intersects(rects[j]) for i in range(len(rects)) for j in range(i + 1, len(rects)))
        check(f"{tag} sin solaparse entre sí", not overlap)
        btns = [w for w in ws if w is not d.handle_icon]
        check(f"{tag} objetivos de al menos 24 px (WCAG 2.5.8)", all(min(w.width(), w.height()) >= 24 for w in btns),
              str([min(w.width(), w.height()) for w in btns]))
        cxs = {round(w.geometry().center().x()) for w in ws}
        check(f"{tag} centrados en el eje de la pestaña", max(cxs) - min(cxs) <= 1, str(cxs))
        if style == "compact":
            check(f"{tag} SIN círculo de color / volver / anterior",
                  not d.handle_icon.isVisibleTo(d) and not d.bar_restore_btn.isVisibleTo(d) and not d.bar_prev_btn.isVisibleTo(d))
        d.hide(); d.deleteLater()

print("== Clics (tarjeta)")
d = make("card", "right")
calls.clear()
d.bar_play_btn.click(); d.bar_next_btn.click(); d.bar_prev_btn.click()
check("play / siguiente / anterior de la pestaña llaman al backend", calls == ["play", "next", "prev"], str(calls))
got = []
d.restoreMainRequested.connect(lambda: got.append(1))
d.bar_restore_btn.click()
check("'volver al reproductor normal' emite restoreMainRequested", got == [1])
d._collapse(); pump(0.05)
check("pestaña: arranca colapsado y la flecha dice 'Mostrar'", "Mostrar" in d.bar_toggle_btn.accessibleName(), d.bar_toggle_btn.accessibleName())
d.bar_toggle_btn.click(); pump(0.05)
check("la flecha expande el panel", d._collapsed is False)
check("y su nombre cambia a 'Ocultar'", "Ocultar" in d.bar_toggle_btn.accessibleName())
d.bar_toggle_btn.click(); pump(0.05)
check("y vuelve a colapsarlo", d._collapsed is True)
d.hide(); d.deleteLater()

print("== Clics (compacto)")
d = make("compact", "right"); calls.clear()
d.bar_play_btn.click(); d.bar_next_btn.click()
check("compacto: play y siguiente funcionan", calls == ["play", "next"], str(calls))
d.hide(); d.deleteLater()

print("== Estado compartido panel <-> pestaña")
d = make("card", "right")
d.apply_state(state(True)); pump(0.3)
check("sonando: play de la pestaña muestra 'pause'", d.bar_play_btn.icon_name == "pause")
d.apply_state(state(False)); pump(0.3)
check("pausa: muestra 'play'", d.bar_play_btn.icon_name == "play")
s = state(True); s.can_next = False; s.can_prev = False
d.apply_state(s)
check("siguiente/anterior se deshabilitan igual que en el panel",
      not d.bar_next_btn.isEnabled() and not d.bar_prev_btn.isEnabled() and not d.next_btn.isEnabled())
d.apply_state(PlayerState()); pump(0.05)
# Cambio intencional: sin reproductor el play queda ACTIVO para poder abrir
# Spotify/YouTube (ver test_start_player.py); anterior/siguiente siguen apagados.
check("sin reproducción: play de la pestaña activo (abre Spotify/YouTube)", d.bar_play_btn.isEnabled())
check("sin reproducción: anterior/siguiente de la pestaña siguen desactivados",
      not d.bar_prev_btn.isEnabled() and not d.bar_next_btn.isEnabled())
d.set_play_idle_enabled(False)
check("con 'No hacer nada' el play de la pestaña vuelve a desactivarse", not d.bar_play_btn.isEnabled())
d.hide(); d.deleteLater()

print("== Círculo de ondas")
d = make("card", "right"); dot = d.handle_icon
d.apply_state(state(True)); pump(0.1)
check("sonando: la animación corre", dot.is_animating())
f1 = dot.grab().toImage(); pump(0.45); f2 = dot.grab().toImage()
check("sonando: los cuadros cambian (las ondas se mueven)", f1 != f2)
d.apply_state(state(False)); pump(0.1)
check("pausa: la animación se detiene", not dot.is_animating())
g1 = dot.grab().toImage(); pump(0.4); g2 = dot.grab().toImage()
check("pausa: queda ESTÁTICO (cuadros idénticos)", g1 == g2)
check("sonando se ve distinto de pausa", f1 != g1)
d.apply_state(state(True)); pump(0.1)
check("al reanudar vuelve a animarse", dot.is_animating())
d.hide(); pump(0.05)
check("oculto: no gasta CPU (timer detenido)", not dot.is_animating())
d.show(); pump(0.1)
check("al mostrarse de nuevo reanuda", dot.is_animating())
d.set_style("compact"); pump(0.1)
check("compacto: el círculo desaparece y su timer se detiene", not dot.isVisibleTo(d) and not dot.is_animating())
d.set_style("card"); pump(0.1)
check("volver a tarjeta: reaparece y anima", dot.isVisibleTo(d) and dot.is_animating())
# costo por cuadro
t0 = time.perf_counter()
for _ in range(60): dot.repaint()
ms = (time.perf_counter() - t0) / 60 * 1000
check("repintar el círculo < 2 ms/cuadro", ms < 2.0, f"{ms:.2f} ms")
t0 = time.perf_counter()
for _ in range(30): d.repaint()
ms2 = (time.perf_counter() - t0) / 30 * 1000
print(f"       (referencia: repintado completo del dock {ms2:.2f} ms)")
d.hide(); d.deleteLater()

print("== Movimiento reducido")
theme.apply_accessibility(1.0, False, reduced_motion=True)
d = make("card", "right"); dot = d.handle_icon
d.apply_state(state(True)); pump(0.1)
check("movimiento reducido: sin animación aunque suene", not dot.is_animating())
h1 = dot.grab().toImage()
d.apply_state(state(False)); pump(0.1)
h2 = dot.grab().toImage()
check("movimiento reducido: 'sonando' y 'pausa' se distinguen sin moverse", h1 != h2)
d.hide(); d.deleteLater()
theme.apply_accessibility(1.0, False, reduced_motion=False)

print("== Hover: apuntar a un botón NO abre el panel")
class _FakeCursor:
    p = QPoint(-5000, -5000)      # lejos de cualquier ventana
    @staticmethod
    def pos(): return _FakeCursor.p
dk.QCursor = _FakeCursor
for edge in ("right", "left"):
    _FakeCursor.p = QPoint(-5000, -5000)
    d = make("card", edge); d.set_hide_mode("hover"); d._collapse(); pump(0.4)
    d._hover_timer.stop()
    check(f"[{edge}] arranca colapsado antes de apuntar", d._collapsed is True)
    zone_g = d._handle_zone().translated(d.x(), d.y()).toRect()
    play_c = d.bar_play_btn.mapToGlobal(d.bar_play_btn.rect().center())
    check(f"[{edge}] el centro del botón play cae dentro de la zona de la pestaña", zone_g.contains(play_c))
    _FakeCursor.p = play_c; d._poll_hover()
    check(f"[{edge}] cursor sobre el play: el panel sigue colapsado", d._collapsed is True)
    for b, nm in ((d.bar_next_btn, "siguiente"), (d.bar_prev_btn, "anterior"), (d.bar_restore_btn, "volver")):
        _FakeCursor.p = b.mapToGlobal(b.rect().center()); d._poll_hover()
        check(f"[{edge}] cursor sobre {nm}: sigue colapsado", d._collapsed is True)
    _FakeCursor.p = d.bar_toggle_btn.mapToGlobal(d.bar_toggle_btn.rect().center()); d._poll_hover(); pump(0.05)
    check(f"[{edge}] cursor sobre la flecha: SÍ abre el panel", d._collapsed is False)
    d.hide(); d.deleteLater()
_FakeCursor.p = QPoint(-5000, -5000)
d = make("card", "right"); d.set_hide_mode("hover"); d._collapse(); pump(0.4); d._hover_timer.stop()
free = d.bar_toggle_btn.mapToGlobal(QPoint(d.bar_toggle_btn.width() // 2, 0)) + QPoint(0, 120)   # tramo libre entre botones
free = d.mapToGlobal(QPoint(d._handle_zone().toRect().center().x(), int(d.bar_restore_btn.geometry().bottom() + 12)))
check("(el punto 'libre' elegido no toca ningún botón)", not d._cursor_over_action_button(free))
_FakeCursor.p = free; d._poll_hover(); pump(0.05)
check("cursor sobre un tramo libre de la pestaña: abre el panel", d._collapsed is False)
d.hide(); d.deleteLater()

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
