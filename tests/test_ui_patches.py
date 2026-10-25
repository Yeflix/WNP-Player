"""Pruebas automáticas (Qt "offscreen") de los parches de UI/UX.

Uso (desde la carpeta del proyecto):
    QT_QPA_PLATFORM=offscreen python tests/test_ui_patches.py
    QT_QPA_PLATFORM=offscreen WNP_REDUCE_MOTION=1 python tests/test_ui_patches.py --reduced

OJO: validan lógica, geometría y pintura sin errores en Qt offscreen; NO
reemplazan una prueba en Windows real (foco, DPI fraccionario, DWM).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QBuffer, QByteArray, QIODevice, QEvent, QPointF
from PyQt6.QtGui import QImage, QColor, QPainter, QLinearGradient, QKeyEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication(sys.argv)
REDUCED = "--reduced" in sys.argv

import theme
from theme import Palette
theme.apply_accessibility(1.0, False)
app.setStyleSheet(theme.build_global_qss())

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  OK   " if cond else "  FALLA"), name, extra)


def make_cover(c1, c2, size=600):
    img = QImage(size, size, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor(*c1))
    g.setColorAt(1, QColor(*c2))
    p.fillRect(img.rect(), g)
    p.end()
    return img


class FakeLyricsLoader(QObject):
    lyricsReady = pyqtSignal(str, object)

    def request(self, *a, **k):
        pass


from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
import widgets
import main_window as mw
import mini_window as mi
import dock_window as dk

backend = WNPBackend()
loader = CoverArtLoader()

if not REDUCED:
    print("== Contraste / paleta")
    check("TEXT_FAINT >= 4.5 sobre BG_PANEL",
          theme.contrast_ratio(Palette.TEXT_FAINT, Palette.BG_PANEL) >= 4.5,
          f"{theme.contrast_ratio(Palette.TEXT_FAINT, Palette.BG_PANEL):.2f}")
    check("TEXT_DIM >= 4.5 sobre BG_PANEL", theme.contrast_ratio(Palette.TEXT_DIM, Palette.BG_PANEL) >= 4.5)
    check("blanco sobre ACCENT_BUTTON >= 4.5", theme.contrast_ratio((255, 255, 255), Palette.ACCENT_BUTTON) >= 4.5)
    check("blanco sobre ACCENT_BUTTON_HOVER >= 4.5", theme.contrast_ratio((255, 255, 255), Palette.ACCENT_BUTTON_HOVER) >= 4.5)
    yellow, lime = (221, 221, 95), (170, 230, 60)
    ic = theme.on_color(yellow, lime)
    check("on_color elige oscuro sobre amarillo/lima", ic != (255, 255, 255),
          f"{ic} ratio={min(theme.contrast_ratio(ic, yellow), theme.contrast_ratio(ic, lime)):.2f}")
    check("on_color mantiene blanco sobre rojo/azul por defecto",
          theme.on_color(Palette.ACCENT_A, Palette.ACCENT_B) == (255, 255, 255))
    blue = (37, 37, 177)
    fixed = theme.ensure_contrast(blue, Palette.BG_BASE, 4.5)
    check("ensure_contrast lleva el azul oscuro a >= 4.5", theme.contrast_ratio(fixed, Palette.BG_BASE) >= 4.5,
          f"{blue}->{fixed}")
    white_cover = make_cover((255, 255, 255), (250, 250, 250))
    dark_cover = make_cover((10, 10, 30), (20, 20, 60))
    a_w = theme.scrim_alpha_for(white_cover, fg=Palette.TEXT_FAINT, scrim=Palette.BG_BASE, lo=195, hi=235)
    a_d = theme.scrim_alpha_for(dark_cover, fg=Palette.TEXT_FAINT, scrim=Palette.BG_BASE, lo=195, hi=235)
    check("velo: portada oscura conserva el alpha original", a_d == 195, str(a_d))
    check("velo: portada blanca sube el alpha", a_w > 195, str(a_w))
    bg = theme.blend_over(Palette.BG_BASE, (255, 255, 255), a_w / 255)
    check("velo: texto TEXT_DIM >= 4.5 sobre portada blanca", theme.contrast_ratio(Palette.TEXT_DIM, bg) >= 4.5,
          f"{theme.contrast_ratio(Palette.TEXT_DIM, bg):.2f}")

    print("== QSS global y alto contraste")
    m = QMenu(); m.ensurePolished()
    check("QMenu escala x1.15 (14px)", m.font().pixelSize() == 14, f"{m.font().pixelSize()}px")
    theme.apply_accessibility(1.0, True)
    check("alto contraste sube TEXT_FAINT", Palette.TEXT_FAINT == (176, 176, 192))
    theme.apply_accessibility(1.0, False)   # (Palette queda en HC: solo se prueba que no falla)

print("== Ventanas: construir / mostrar / estado")
win = mw.MainWindow(backend, loader, FakeLyricsLoader())
mini = mi.MiniWindow(backend, loader)
dock = dk.DockWindow(backend, loader)
for w in (win, mini, dock):
    w.show()
app.processEvents()
check("MainWindow/MiniWindow/DockWindow construyen y muestran", all(w.isVisible() for w in (win, mini)))

st = PlayerState(connected=True, player_name="YouTube", state="PLAYING", title="Tema", artist="Artista",
                 duration="3:20", duration_seconds=200, position="0:10", position_seconds=10,
                 position_percent=5.0, volume=80, can_volume=True, cover_url="x")
win.apply_state(st); mini.apply_state(st); dock.apply_state(st)
app.processEvents()

print("== Ancho mínimo")
win.set_content_width(300)
app.processEvents()
lay_min = win.content_widget.layout().minimumSize().width()
check("ancho de contenido nunca < mínimo del layout", win.content_width() >= lay_min,
      f"content={win.content_width()} min_layout={lay_min}")
check("MIN_WIDTH cubre el layout", mw.MIN_WIDTH >= lay_min)

print("== IconButton")
b = win.shuffle_btn
check("foco solo por Tab (no por clic)", b.focusPolicy() == Qt.FocusPolicy.TabFocus)
check("nombre accesible desde tooltip", b.accessibleName() == "Reproducción aleatoria", b.accessibleName())
check("mini: botones con nombre accesible", mini.prev_btn.accessibleName() == "Anterior")
pb = win.play_btn
pb.set_icon("play")
app.processEvents()
pb.set_icon("pause")
t0 = time.time()
while time.time() - t0 < 0.5:
    app.processEvents()
check("swap de ícono termina y limpia estado", pb._prev_icon is None and pb._swap == 1.0)
pb.setEnabled(False)
img = win.grab()
check("paint con play deshabilitado sin errores", not img.isNull())
pb.setEnabled(True)
win.set_content_width(mw.WIDTH)
from PyQt6.QtGui import QFocusEvent
b.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
check("Tab activa el anillo de foco", b._kbd_focus)
b.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
check("el clic NO activa el anillo de foco", not b._kbd_focus)
b.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
b.setFocus(); b.repaint()
check("pinta con anillo de foco sin errores", not b.grab().isNull())
b.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
check("al perder el foco se apaga el anillo", not b._kbd_focus)

print("== Cambios de carátula: acento, velo, texto")
cover = make_cover((255, 255, 255), (240, 240, 250))
win._current_cover_url = "x"; mini._current_cover_url = "x"; dock._current_cover_url = "x"
for w in (win, mini, dock):
    w._on_cover_ready("x", cover)
win._on_colors_ready("x", (37, 37, 177), (200, 200, 60)); mini._on_colors_ready("x", (37, 37, 177), (200, 200, 60))
t0 = time.time()
while time.time() - t0 < 0.7:
    app.processEvents()
check("main: velo adaptativo con portada blanca", win._scrim_to > 195, str(win._scrim_to))
art = win.artist_label._color
check("main: texto del artista >= 4.5 sobre el fondo real",
      theme.contrast_ratio((art.red(), art.green(), art.blue()), win._text_bg) >= 4.5,
      f"{theme.contrast_ratio((art.red(), art.green(), art.blue()), win._text_bg):.2f}")
check("mini: velo adaptativo", mini._scrim_lo > 120, str(mini._scrim_lo))
art = mini.artist_label._color
check("mini: texto del artista >= 4.5", theme.contrast_ratio((art.red(), art.green(), art.blue()), mini._text_bg) >= 4.5,
      f"{theme.contrast_ratio((art.red(), art.green(), art.blue()), mini._text_bg):.2f}")
check("dock: velo adaptativo", dock._scrim_lo > 150, str(dock._scrim_lo))
for w in (win, mini, dock):
    check(f"{type(w).__name__}.grab() con portada clara", not w.grab().isNull())

print("== SeekBar / VolumeBar")
got = []
sb = widgets.SeekBar(); sb.resize(200, 16); sb.show()
sb.set_duration_seconds(200); sb.set_percent(0); sb.seekRequested.connect(got.append)
sb.setFocus(Qt.FocusReason.TabFocusReason)
QApplication.sendEvent(sb, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
check("flecha derecha = +5 s (2.5 % de 200 s)", got and abs(got[-1] - 2.5) < 1e-6, str(got))
QApplication.sendEvent(sb, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_End, Qt.KeyboardModifier.NoModifier))
check("Fin = 100 %", got[-1] == 100.0)
check("hover text de la barra", sb._hover_text(50.0) == "1:40", sb._hover_text(50.0))
vols = []
vb = widgets.VolumeBar(height=16, bar_height=6); vb.resize(150, 16); vb.show(); vb.set_percent(50)
vb.set_interactive(True); vb.volumeChanged.connect(vols.append)
ev = QWheelEvent(QPointF(10, 8), QPointF(10, 8), QPointF(0, 0).toPoint(), QPointF(0, 120).toPoint(),
                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(vb, ev)
check("rueda sube el volumen 5 %", vols and vols[-1] == 55, str(vols))
vb.set_interactive(False)
vols.clear()
QApplication.sendEvent(vb, ev)
check("volumen no interactivo ignora la rueda", not vols)
win._premute_volume = 0
win.volume_bar.set_interactive(True); win.volume_bar.set_percent(70)
t0 = time.time()
while time.time() - t0 < 0.4:     # deja terminar la animación de la barra (80 -> 70)
    app.processEvents()
sent = []
backend.set_volume = lambda v: sent.append(v)
win._on_mute_clicked()
check("silenciar manda volumen 0 y cambia el ícono", sent[-1:] == [0] and win.volume_icon.icon_name == "speaker_mute", str(sent))
win._on_mute_clicked()
check("segundo clic restaura el volumen previo", sent[-1:] == [70], str(sent))

print("== Marquesina / vinilo (tiempo real)")
ml = widgets.MarqueeLabel("Un titulo bastante largo para forzar el desplazamiento horizontal completo", pixels_per_sec=100.0, pause_ms=50)
ml.resize(120, 20); ml.show(); app.processEvents()
if REDUCED:
    check("reduced motion: la marquesina no se desplaza", not ml._needs_scroll and not ml._timer.isActive())
    check("reduced motion: tooltip con el texto completo", ml.toolTip() == ml.fullText())
else:
    check("marquesina desplaza cuando no cabe", ml._needs_scroll)
    ml._pause_until = 0.0
    ml._last_tick = time.monotonic() - 0.1     # simula 100 ms transcurridos
    off0 = ml._offset
    ml._tick()
    check("avance por tiempo real (100 px/s x 0.1 s ~ 10 px)", 8.0 <= ml._offset - off0 <= 12.0, f"{ml._offset - off0:.1f}px")
v = mini.vinyl
v.set_spinning(True)
if REDUCED:
    check("reduced motion: el vinilo no gira", not v._timer.isActive())
else:
    check("vinilo gira con PreciseTimer", v._timer.isActive() and v._timer.timerType() == Qt.TimerType.PreciseTimer)
    v._angle = 0.0; v._last_spin = time.monotonic() - 0.2
    v._advance()
    check("vinilo: 55 deg/s x 0.2 s ~ 11 deg", 9.0 <= v._angle <= 13.0, f"{v._angle:.1f}")

print("== Letra (lienzo pintado a mano)")
panel = win.lyrics_panel
win.set_lyrics_panel_enabled(True, animate=False)
app.processEvents()
key = "k1"
panel._key = key
synced = [(i * 4.0, f"Línea número {i} de la canción con texto suficiente para envolver en varias líneas dentro del panel") for i in range(120)]
panel._on_ready(key, {"synced": synced, "plain": ""})
app.processEvents()
check("letra sincronizada muestra el lienzo", panel.stack.currentWidget() is panel.canvas)
panel.set_position(41.0)
check("índice por búsqueda binaria (41 s -> línea 10)", panel._current_index == 10, str(panel._current_index))
t0 = time.time()
while time.time() - t0 < 0.7:
    app.processEvents()
c = panel.canvas
check("línea activa centrada tras la animación",
      abs(c._scroll - c._target_for(10)) < 1.0 or c._scroll >= c._max_scroll() - 1,
      f"scroll={c._scroll:.1f} objetivo={c._target_for(10):.1f}")
check("lienzo pinta sin errores", not panel.grab().isNull())
t0 = time.perf_counter()
for w_ in (200, 230, 260, 240):
    c._layout_width = -1
    c.resize(w_, c.height())
    c._ensure_layout()
dt = (time.perf_counter() - t0) / 4 * 1000
check("re-medir 120 líneas envueltas < 25 ms", dt < 25, f"{dt:.1f} ms")
t0 = time.perf_counter()
for i in range(200):
    panel._apply_position(float(i))
dt = (time.perf_counter() - t0) / 200 * 1000
check("_apply_position < 1 ms", dt < 1.0, f"{dt:.3f} ms")
c._manual_until = 0
QApplication.sendEvent(c, QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPointF(0, 0).toPoint(), QPointF(0, -120).toPoint(),
                                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
check("rueda desplaza la letra y pausa el auto-centrado", c._manual_until > time.monotonic())
panel._key = "k2"
panel._on_ready("k2", {"synced": None, "plain": "uno\n\ndos\ntres"})
check("letra sin sincronizar: 4 líneas (vacía = ♪)", c._texts == ["uno", "♪", "dos", "tres"], str(c._texts))
check("letra plana pinta", not panel.grab().isNull())

print("== Fondo ambiente: reutiliza el blur previo")
import widgets as _w
calls = []
_orig_blur = mw.blur_image_hq
def _counting_blur(img, tw, th):
    calls.append((tw, th)); return _orig_blur(img, tw, th)
mw.blur_image_hq = _counting_blur
win.set_content_width(mw.WIDTH); app.processEvents()
imgA = make_cover((200, 30, 60), (30, 60, 200)); imgB = make_cover((30, 200, 90), (250, 220, 40))
win._current_cover_url = "a"; win._on_cover_ready("a", imgA)
calls.clear()
win._current_cover_url = "b"; win._on_cover_ready("b", imgB)
check("cambio de canción = 1 solo blur (antes 2)", len(calls) == 1, f"{len(calls)} blur(s)")
check("la 'anterior' es el blur previo reutilizado", win._ambient_big_from is not None and win._ambient_big_to is not None)
same = win._ambient_big_from.size() == win._ambient_big_to.size()
check("ambos blurs al mismo tamaño", same)
calls.clear()
win._ambient_cache_size = None      # simula cambio de tamaño: no se puede reutilizar
win._regenerate_ambient_bg(shift=True)
check("si cambió el tamaño, se difuminan ambos", len(calls) == 2, f"{len(calls)} blur(s)")
calls.clear()
win._regenerate_ambient_bg()        # resize normal (sin shift)
check("resize (sin shift) difumina ambos", len(calls) == 2)
mw.blur_image_hq = _orig_blur

print("== Halo por reloj real")
win._glow_phase = 0.0; win._glow_last = time.monotonic() - 0.16
win._on_glow_tick()
check("halo: 0.16 s -> 0.156 rad (0.975 rad/s)", 0.14 <= win._glow_phase <= 0.17, f"{win._glow_phase:.3f}")
win._glow_last = time.monotonic() - 5.0
p0 = win._glow_phase; win._on_glow_tick()
check("halo: un salto de 5 s se limita a 0.25 s", win._glow_phase - p0 <= 0.25 * 0.975 + 1e-6, f"{win._glow_phase - p0:.3f}")

print("== Carátulas: reducción antes de cachear")
import cover_loader as cl
big = make_cover((200, 30, 60), (30, 60, 200), size=2000)
ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly); big.save(buf, "PNG"); buf.close()
import base64
url = "data:image/png;base64," + base64.b64encode(bytes(ba)).decode()
out = []
sig = cl._JobSignals(); sig.finished.connect(lambda u, i, a, b: out.append(i))
cl._CoverJob(url, sig).run()
check("carátula 2000 px -> <= 800 px", out and max(out[0].width(), out[0].height()) <= 800,
      f"{out[0].width()}x{out[0].height()}" if out else "sin imagen")

print("== Multi-monitor")
import app_controller as ac
class _Dummy:
    def __init__(self): self.pos = None
    def move(self, x, y): self.pos = (x, y)
d = _Dummy()
ac.AppController._move_within_screen(None, d, 100, 100)
check("_move_within_screen funciona con la pantalla presente", d.pos == (100, 100), str(d.pos))
ac.AppController._move_within_screen(None, d, 10**6, 10**6)
check("posición inexistente se acota a una pantalla real", d.pos[0] < 10**5 and d.pos[1] < 10**5, str(d.pos))

print()
print(f"RESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL:
    print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
