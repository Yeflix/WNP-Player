"""Controles: play/pausa, volumen, silenciar, posición, aleatorio/repetir, teclas y validación del backend."""
import os, sys, time, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEvent, QPointF, QPoint
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
import main_window, mini_window, dock_window

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

calls = []
be = WNPBackend(); loader = CoverArtLoader()
be.set_playing = lambda p: calls.append(("play", p))
be.toggle_play_pause = lambda: calls.append(("toggle",))
be.toggle_shuffle = lambda: calls.append(("shuffle",))
be.toggle_repeat = lambda: calls.append(("repeat",))
be.set_volume = lambda v: calls.append(("vol", v))
be.seek_percent = lambda p: calls.append(("seek", p))
be.next = lambda: calls.append(("next",))
be.previous = lambda: calls.append(("prev",))
be.has_no_player = lambda: False

def st(**kw):
    base = dict(connected=True, player_name="YouTube", state="PAUSED", title="Tema", artist="Artista",
                duration="3:20", duration_seconds=200, position_percent=10.0, volume=70,
                can_play_pause=True, can_prev=True, can_next=True, can_seek=True, can_volume=True,
                can_shuffle=True, can_repeat=True)
    base.update(kw); return PlayerState(**base)

def expire(hold):
    hold._until = time.monotonic() - 1.0

w = main_window.MainWindow(be, loader); w.show(); w.apply_state(st())
app.processEvents()

# ---- play / pausa
w._on_play_clicked()
check("play: el ícono cambia al instante a pausa", w.play_btn.icon_name == "pause")
check("play: manda orden EXPLÍCITA de reproducir", calls[-1] == ("play", True))
w.apply_state(st(state="PAUSED", position_percent=11.0))       # sondeo aún con el estado viejo
check("play: el sondeo viejo NO hace rebotar el ícono", w.play_btn.icon_name == "pause")
w.apply_state(st(state="PLAYING", position_percent=12.0))
check("play: al confirmarse queda en pausa (suena)", w.play_btn.icon_name == "pause" and not w._play_hold.active)
w.apply_state(st(state="PAUSED", position_percent=12.0))
check("play: un cambio real posterior sí se refleja", w.play_btn.icon_name == "play")

calls.clear()
w._on_play_clicked(); w._on_play_clicked()
check("doble clic: dos órdenes explícitas distintas (play y pausa), no dos iguales", calls == [("play", True), ("play", False)])

w.apply_state(st(state="PAUSED", position_percent=13.0)); expire(w._play_hold); w._resync_controls()
w._on_play_clicked(); expire(w._play_hold); w._resync_controls()
check("orden ignorada por el reproductor: el ícono vuelve a la realidad", w.play_btn.icon_name == "play")

# ---- aleatorio / repetir
w.apply_state(st(shuffle_active=False, repeat_mode="NONE", position_percent=14.0))
w._on_shuffle_clicked()
w.apply_state(st(shuffle_active=False, repeat_mode="NONE", position_percent=15.0))
check("aleatorio: el sondeo viejo no lo apaga", w.shuffle_btn.is_active())
w.apply_state(st(shuffle_active=True, repeat_mode="NONE", position_percent=16.0))
check("aleatorio: se confirma", w.shuffle_btn.is_active() and not w._shuffle_hold.active)
w._on_repeat_clicked()
w.apply_state(st(shuffle_active=True, repeat_mode="NONE", position_percent=17.0))
check("repetir: el sondeo viejo no revierte el modo", w.repeat_btn.is_active())
expire(w._repeat_hold); w._resync_controls()
check("repetir: si nunca se confirma, vuelve a la realidad", not w.repeat_btn.is_active())

# ---- barra de posición
bar = w.seek_bar; bar.set_seekable(True); bar.set_duration_seconds(200); bar.set_percent(20.0)
def mouse(widget, kind, button, x):
    ev = QMouseEvent(kind, QPointF(x, 5), widget.mapToGlobal(QPointF(x, 5)), button,
                     button if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    (widget.mousePressEvent if kind == QEvent.Type.MouseButtonPress else widget.mouseReleaseEvent)(ev)
calls.clear(); before = bar._percent
mouse(bar, QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton, 10)
check("posición: el clic derecho ya no mueve la barra", not bar.is_dragging() and bar._percent == before)
mouse(bar, QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, bar.width() - 1)
mouse(bar, QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, bar.width() - 1)
sent = [c for c in calls if c[0] == "seek"]
check("posición: soltar al final deja 1 s (no salta a la siguiente)", sent and sent[-1][1] <= 99.5 + 1e-6)
shown = bar._percent
bar.set_percent(20.0)
check("posición: el sondeo viejo tras soltar no hace rebotar la barra", bar._percent > 90.0)
bar.set_percent(sent[-1][1])
check("posición: al confirmarse se suelta la protección", not bar._hold.active)
bar._hold.set(50.0); expire(bar._hold); bar.set_percent(30.0)
check("posición: vencido el plazo la barra sigue al reproductor", abs(bar._percent - 30.0) < 0.2)
bar._dragging = True; bar.set_percent(40.0)
_t = time.time()
while time.time() - _t < 0.5: app.processEvents()
check("posición: un 'soltar' perdido ya no congela la barra", not bar.is_dragging() and abs(bar._percent - 40.0) < 0.5)

# ---- volumen / silenciar
vol = w.volume_bar; vol.set_interactive(True); vol.set_percent(70.0); calls.clear()
ev = QWheelEvent(QPointF(5, 5), vol.mapToGlobal(QPointF(5, 5)), QPoint(0, 0), QPoint(0, 120),
                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
vol.wheelEvent(ev)
check("volumen: la rueda sube 5 puntos y lo manda", ("vol", 75) in calls and round(vol._percent) == 75)
w.apply_state(st(volume=70, position_percent=18.0))
check("volumen: el sondeo viejo no hace rebotar la barra", round(vol._percent) == 75)
w.apply_state(st(volume=75, position_percent=19.0))
check("volumen: al confirmarse se suelta", not vol._hold.active)
calls.clear(); w._on_mute_clicked()
check("silenciar: manda 0 y la barra queda en 0", ("vol", 0) in calls and round(vol._percent) == 0)
w.apply_state(st(volume=75, position_percent=20.0))
check("silenciar: el sondeo viejo no restaura el volumen ni el ícono", round(vol._percent) == 0 and w.volume_icon.icon_name == "speaker_mute")
calls.clear(); w._on_mute_clicked()
check("silenciar: al reactivar vuelve al volumen anterior (75)", ("vol", 75) in calls)
mouse(vol, QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton, 10)
check("volumen: el clic derecho no cambia el volumen", not vol.is_dragging())

# ---- teclado: mantener pulsada la tecla cuenta una sola vez
def key(k, auto):
    return QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier, "", auto, 1)
w.apply_state(st(state="PAUSED", position_percent=21.0)); expire(w._play_hold); calls.clear()
w.keyPressEvent(key(Qt.Key.Key_Space, False)); w.keyPressEvent(key(Qt.Key.Key_Space, True)); w.keyPressEvent(key(Qt.Key.Key_Space, True))
check("Espacio: la repetición automática no alterna play/pausa", [c for c in calls if c[0] == "play"] == [("play", True)])
calls.clear(); w.keyPressEvent(key(Qt.Key.Key_Right, False)); w.keyPressEvent(key(Qt.Key.Key_Right, True))
check("Flecha derecha: mantenerla pulsada salta una sola canción", calls.count(("next",)) == 1)

# ---- ventana compacta y panel lateral
mi = mini_window.MiniWindow(be, loader); mi.show(); mi.apply_state(st(state="PAUSED"))
calls.clear(); mi._on_play_clicked()
mi.apply_state(st(state="PAUSED", position_percent=30.0))
check("compacta: ícono optimista + orden explícita + sin rebote", mi.play_btn.icon_name == "pause" and calls == [("play", True)])
expire(mi._play_hold); mi._resync_play()
check("compacta: orden ignorada, vuelve a la realidad", mi.play_btn.icon_name == "play")

dk = dock_window.DockWindow(be, loader); dk.show(); dk.apply_state(st(state="PAUSED"))
calls.clear(); dk._on_play_clicked()
check("panel lateral: ahora el ícono cambia al instante (en panel y pestaña)",
      dk.play_btn.icon_name == "pause" and dk.bar_play_btn.icon_name == "pause" and calls == [("play", True)])
dk.apply_state(st(state="PAUSED", position_percent=40.0))
check("panel lateral: sin rebote con el estado viejo", dk.play_btn.icon_name == "pause")
expire(dk._play_hold); dk._resync_play()
check("panel lateral: orden ignorada, vuelve a la realidad", dk.play_btn.icon_name == "play")

# ---- backend: validación y orden explícita
real = WNPBackend(); got = []
ctrl = types.SimpleNamespace(try_set_volume=lambda v: got.append(("vol", v)),
                             try_set_position_percent=lambda p: got.append(("seek", p)),
                             try_play=lambda: got.append("play"), try_pause=lambda: got.append("pause"))
real._running = True; real._controls = lambda: ctrl
real.set_volume(150); real.set_volume(-20); real.set_volume(float("nan")); real.set_volume("x"); real.set_volume(33.6)
check("backend: volumen acotado a 0-100 y valores inválidos descartados", got == [("vol", 100), ("vol", 0), ("vol", 34)])
got.clear(); real.seek_percent(130); real.seek_percent(-1); real.seek_percent(float("inf")); real.seek_percent(42.5)
check("backend: posición acotada y valores inválidos descartados", got == [("seek", 100.0), ("seek", 0.0), ("seek", 42.5)])
got.clear(); real.has_no_player = lambda: False; real.set_playing(True); real.set_playing(False)
check("backend: set_playing manda reproducir y pausar de forma explícita", got == ["play", "pause"])
asked = []; real.noPlayerPlayRequested.connect(lambda: asked.append(1)); real.has_no_player = lambda: True
got.clear(); real.set_playing(True); real.set_playing(False)
check("backend: sin reproductor, 'play' ofrece abrir uno en vez de mandar la orden", asked == [1] and "play" not in got)

print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
