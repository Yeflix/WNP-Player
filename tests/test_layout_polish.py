"""Pulido de layouts: desbordes, recortes, alturas, rueda en combos, 'Ver letra' eliminado.

    QT_QPA_PLATFORM=offscreen python tests/test_layout_polish.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QPointF, QObject, pyqtSignal, QRect, QSize
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QScrollArea, QLabel, QVBoxLayout, QWidget, QSlider

app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app)
theme.apply_accessibility(1.15, False, reduced_motion=True)
app.setStyleSheet(theme.build_global_qss())

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)
def pump(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents()

import widgets, dialogs, onboarding
from config import AppConfig
from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader

LONG = "Devil May Cry 4: SE ''Shall Never Surrender-HR Edition (Remastered Soundtrack Version)"
entries = [{"title": LONG if i % 2 == 0 else f"Canción {i}", "artist": "Un artista con un nombre bastante largo",
            "player": "YouTube Music", "timestamp": time.time() - i * 5400, "duration": 200 + i} for i in range(12)]

def wheel(w, dy):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPointF(0, 0).toPoint(), QPointF(0, dy).toPoint(),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w, ev); app.processEvents()

print("== ElidedLabel")
host = QWidget(); lay = QVBoxLayout(host); lay.setContentsMargins(0, 0, 0, 0)
el = widgets.ElidedLabel(LONG); lay.addWidget(el)
host.resize(180, 30); host.show(); pump()
check("el contenedor NO se ensancha por el texto", host.width() == 180, str(host.width()))
check("el texto se recorta con '…'", el.text().endswith("…") and el.fullText() == LONG, el.text())
check("tooltip con el texto completo", el.toolTip() == LONG)
check("minimumSizeHint chico (puede comprimirse)", el.minimumSizeHint().width() < 40, str(el.minimumSizeHint()))
check("sizeHint = texto completo", el.sizeHint().width() > 400, str(el.sizeHint().width()))
host.resize(900, 30); pump()
check("al haber espacio vuelve a mostrar el texto completo", el.text() == LONG, el.text()[:30])

print("== Rueda del mouse no cambia valores (bug: el estilo del panel lateral 'se cambiaba solo')")
cfg = AppConfig(); cfg.dock_style = "card"; cfg.dock_edge = "right"; cfg.font_scale = 1.0; cfg.window_opacity = 0.9
d = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None); d.show(); pump()
before = {n: getattr(d, n).currentData() for n in ("dock_style_combo", "dock_edge_combo", "dock_hide_combo", "font_scale_combo", "scrobble_combo")}
for n in before:
    wheel(getattr(d, n), -120); wheel(getattr(d, n), 120)
after = {n: getattr(d, n).currentData() for n in before}
check("ningún combo cambia con la rueda", before == after, f"{before} -> {after}")
v0 = d.opacity_slider.value(); wheel(d.opacity_slider, -120)
check("el deslizador de opacidad tampoco", d.opacity_slider.value() == v0, str(d.opacity_slider.value()))
sa = d.findChildren(QScrollArea)[0]
def _ev(dy):
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPointF(0, 0).toPoint(), QPointF(0, dy).toPoint(),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
# Con la rueda del mouse real, Qt sube los eventos NO aceptados al contenedor (el scroll del
# diálogo). Eso no se puede simular con sendEvent, así que se comprueba la condición:
# el combo y el deslizador dejan el evento sin aceptar, y el área de scroll responde a la rueda.
e1 = _ev(-120); QApplication.sendEvent(d.dock_style_combo, e1)
e2 = _ev(-120); QApplication.sendEvent(d.opacity_slider, e2)
check("combo y deslizador NO aceptan la rueda (Qt la pasa al scroll del diálogo)", not e1.isAccepted() and not e2.isAccepted())
sa.verticalScrollBar().setValue(0); QApplication.sendEvent(sa.viewport(), _ev(-120)); app.processEvents()
check("el área de scroll del diálogo sí responde a la rueda", sa.verticalScrollBar().value() > 0)
sa.verticalScrollBar().setValue(0)
d.dock_style_combo.setCurrentIndex(1)
check("el clic/teclado SÍ cambia el combo", d.dock_style_combo.currentData() == "compact")
d.hide(); d.deleteLater()

print("== Estadísticas / Historial / Recientes: sin desborde")
def hmax(dlg): return max((s.horizontalScrollBar().maximum() for s in dlg.findChildren(QScrollArea)), default=0)
for name, mk in (("Stats", lambda: dialogs.StatsDialog(entries, LONG, "Un artista con un nombre bastante largo")),
                 ("History", lambda: dialogs.HistoryDialog(entries)),
                 ("Recent", lambda: dialogs.RecentlyPlayedDialog(entries, True))):
    dlg = mk(); dlg.show(); pump(0.25)
    check(f"{name}: sin barra horizontal con títulos larguísimos", hmax(dlg) == 0, f"max={hmax(dlg)}")
    dlg.hide(); dlg.deleteLater()
st = dialogs.StatsDialog(entries, LONG, "X"); st.show(); pump(0.2)
chips = st.findChildren(dialogs._StatChip)
check("hay 3 cifras destacadas", len(chips) == 3)
check("cifras: selector por nombre (no alcanza a los QLabel hijos)",
      all(c.objectName() == "statChip" and "QFrame#statChip" in c.styleSheet() for c in chips))
ok_fit = all(c.width() >= 80 for c in chips) and chips[-1].geometry().right() <= chips[0].parentWidget().width()
check("las 3 cifras caben en una fila", ok_fit, str([c.geometry().getRect() for c in chips]))
st.hide(); st.deleteLater()

print("== Diálogos: altura por contenido, acotada a la pantalla, opacos")
ab = dialogs.AboutDialog(1234); ab.show(); pump(0.2)
need = ab.layout().totalHeightForWidth(ab.width())
check("Acerca de: alto suficiente para su texto (antes salía cortado)", ab.height() >= need - 1, f"{ab.height()} >= {need}")
check("Acerca de: no queda un hueco absurdo", ab.height() <= need + 40)
ab.hide(); ab.deleteLater()
msg = dialogs.MessageDialog("Título", "Cuerpo corto."); msg.show(); pump(0.2)
check("Mensaje: sin el hueco enorme entre título y cuerpo", msg.height() <= msg.layout().totalHeightForWidth(msg.width()) + 40, str(msg.height()))
msg.hide(); msg.deleteLater()
class _Tall(dialogs._DialogBase):
    def __init__(self):
        super().__init__(None, title="x", width=300, height=3000)
        QVBoxLayout(self).addWidget(QLabel("hola"))
tall = _Tall(); tall.show(); pump(0.1)
avail = tall.screen().availableGeometry().height()
check("diálogo más alto que la pantalla se acota", tall.height() <= avail - 48 + 1, f"{tall.height()} <= {avail - 48}")
img = ab.__class__(1234); img.show(); pump(0.1)
g = img.grab().toImage(); c = g.pixelColor(g.width() // 2, g.height() // 2)
check("fondo del diálogo totalmente opaco (alpha 255)", c.alpha() == 255, f"alpha={c.alpha()}")
img.hide(); tall.hide()

print("== Ventana principal: horas alineadas")
import main_window as mw
class _FL(QObject):
    lyricsReady = pyqtSignal(str, object)
    def request(self, *a, **k): pass
be = WNPBackend(); loader = CoverArtLoader()
win = mw.MainWindow(be, loader, _FL()); win.show(); pump(0.2)
VC = Qt.AlignmentFlag.AlignVCenter
check("hora izquierda y derecha centradas verticalmente (derecha ya no pegada arriba)",
      bool(win.position_label.alignment() & VC) and bool(win.duration_label.alignment() & VC))
check("la hora derecha sigue alineada a la derecha", bool(win.duration_label.alignment() & Qt.AlignmentFlag.AlignRight))
win.hide(); win.deleteLater()

print("== Barra compacta")
import mini_window as mi
mini = mi.MiniWindow(be, loader); mini.show(); pump(0.2)
st = PlayerState(connected=True, player_name="YouTube", state="PLAYING", title=LONG, artist="By Cem",
                 duration="5:37", duration_seconds=337, position_percent=40.0, can_play_pause=True, can_prev=True, can_next=True, can_seek=True)
mini.apply_state(st); pump(0.2)
t, a = mini.title_label.geometry(), mini.artist_label.geometry()
check("título y artista NO se pisan", not t.intersects(a), f"{t.getRect()} / {a.getRect()}")
check("el título tiene ancho útil (antes 66 px)", t.width() >= 130, str(t.width()))
check("alto de cada línea >= alto de su fuente",
      t.height() >= mini.title_label.text_height() and a.height() >= mini.artist_label.text_height(),
      f"{t.height()}>={mini.title_label.text_height()} {a.height()}>={mini.artist_label.text_height()}")
rest = QRect(mini.prev_btn.pos(), mini.prev_btn.size())
check("el texto no invade los controles", t.right() < rest.left(), f"{t.right()} < {rest.left()}")
mini.hide(); mini.deleteLater()

print("== Panel lateral compacto")
import dock_window as dk
dock = dk.DockWindow(be, loader); dock.set_style("compact"); dock.set_edge("right"); dock.show(); dock._reposition(animate=False); pump(0.1)
dock.apply_state(st); pump(0.2); dock._expand(); pump(0.5)
c = dock._content_zone()
rb = dock.restore_btn.geometry()
check("botón de subir a >= 8 px de los bordes (esquina redondeada)",
      c.right() - rb.right() >= 8 and rb.top() - c.top() >= 8, f"derecha={c.right() - rb.right():.0f} arriba={rb.top() - c.top():.0f}")
others = [dock.prev_btn, dock.play_btn, dock.next_btn]
check("el botón de subir no toca a los controles",
      not any(rb.adjusted(-2, -2, 2, 2).intersects(o.geometry()) for o in others))
tl, al = dock.title_label.geometry(), dock.artist_label.geometry()
check("título/artista del dock no se pisan y tienen ancho útil", not tl.intersects(al) and tl.width() >= 130, f"{tl.width()}")
dock.hide(); dock.deleteLater()

print("== 'Ver letra...' eliminado")
check("LyricsDialog ya no existe", not hasattr(dialogs, "LyricsDialog"))
win2 = mw.MainWindow(be, loader, _FL()); win2.show(); pump(0.1)
check("la ventana principal no tiene señal lyricsDialogRequested", not hasattr(win2, "lyricsDialogRequested"))
texts = [a.text() for a in win2._build_menu().actions()]
check("menú del reproductor sin 'Ver letra...'", not any("Ver letra" in t for t in texts), str(texts))
check("pero conserva 'Letra junto a la carátula'", any("Letra junto a la carátula" in t for t in texts))
win2.hide(); win2.deleteLater()
from app_controller import AppController
ctrl = AppController(port=54329)
tray_texts = [a.text() for a in ctrl.tray.contextMenu().actions()]
check("menú de la bandeja sin 'Ver letra...'", not any("Ver letra" in t for t in tray_texts), str(tray_texts))
check("el controlador ya no tiene _open_lyrics_dialog", not hasattr(ctrl, "_open_lyrics_dialog"))

print("== Asistente de bienvenida")
wz = onboarding.WelcomeWizard(1234); wz.show(); pump(0.2)
texts = [l.text() for l in wz.findChildren(QLabel)]
check("menciona los TRES modos (antes decía 'Dos interfaces')", any("Tres modos" in t for t in texts) and not any("Dos interfaces" in t for t in texts))
wz._page_index = 1; wz._pending_page_index = 1; wz.stack.setCurrentIndex(1); pump(0.3)
ys = []
for title in ("Completo", "Compacto", "Panel lateral"):
    lab = [l for l in wz.findChildren(QLabel) if l.text() == title][0]
    ys.append(lab.mapTo(wz, lab.rect().topLeft()).y())
check("los títulos de las 3 tarjetas están a la misma altura", len(set(ys)) == 1, str(ys))
wz.hide(); wz.deleteLater()

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
