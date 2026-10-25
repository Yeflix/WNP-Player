"""Interfaz de la ronda 4: selector de reproductor, "me gusta", panel lateral
(sin botón de esquina, micrófono, ondas), indicador de reproducción.

    QT_QPA_PLATFORM=offscreen python tests/test_ui_ronda4.py
"""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="wnp_ui4_")
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["LOCALAPPDATA"] = TMP

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMenu, QPushButton
app = QApplication([])
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=False)
app.setStyleSheet(theme.build_global_qss())
theme.REDUCED_MOTION = False

def run(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

import dock_window, player_launcher
from dock_window import DockWindow, RIPPLE_M, HANDLE_SIZE
from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
from likes import LikeInfo
from widgets import PlatformPickerButton, PlayingIndicator, LIKE_RGB

def st(state="PLAYING", player="Spotify", **kw):
    base = dict(connected=True, player_name=player, state=state, title="One More Time", artist="Daft Punk",
                duration="5:20", duration_seconds=320, can_play_pause=True, can_prev=True, can_next=True, can_seek=True)
    base.update(kw)
    return PlayerState(**base)

class FakeLyrics(QObject):
    lyricsReady = pyqtSignal(str, object)
    def __init__(self): super().__init__(); self.calls = []
    def request(self, artist, title, album="", duration_seconds=0, force=False):
        self.calls.append((artist, title))

cl = CoverArtLoader()

# ------------------------------------------------------------------ 1
print("== 1) Panel lateral: la píldora NO se mueve de sitio")
for edge in ("right", "left"):
    d = DockWindow(WNPBackend(), cl, lyrics_loader=FakeLyrics())
    d.set_edge(edge); d.set_style("card"); d.show_on_edge(); app.processEvents()
    geo = d._screen_geometry()
    pill = d._pill_rect()
    g_left, g_right = d.x() + pill.left(), d.x() + pill.right()
    if edge == "right":
        ok = (round(g_left) == geo.right() - 31 and round(g_right) == geo.right() - 3)
    else:
        ok = (round(g_left) == geo.left() + 3 and round(g_right) == geo.left() + 31)
    check(f"borde {edge}: la píldora queda donde estaba (a 3 px del borde, 28 px de ancho)", ok,
          f"{g_left:.0f}..{g_right:.0f} geo={geo.left()}..{geo.right()}")
    check(f"borde {edge}: la zona de la pestaña incluye el margen de las ondas", d._handle_zone().width() == 34 + RIPPLE_M)
    d.hide()

# ------------------------------------------------------------------ 2
print("== 2) Barra: botones nuevos, sin solaparse, y sin botón en la esquina")
d = DockWindow(WNPBackend(), cl, lyrics_loader=FakeLyrics())
d.set_edge("right"); d.set_style("card"); d.show_on_edge(); d.apply_state(st()); app.processEvents()
d.set_like_info(LikeInfo(service="spotify", configured=True, liked=False)); app.processEvents()
check("tarjeta grande: el botón de la esquina ya no está", not d.restore_btn.isVisibleTo(d))
check("tarjeta grande: la pestaña conserva 'volver al reproductor'", d.bar_restore_btn.isVisibleTo(d))
check("micrófono en la pestaña", d.bar_mic_btn.isVisibleTo(d))
check("corazón en la pestaña (suena Spotify)", d.bar_like_btn.isVisibleTo(d))
pill = d._pill_rect()
seq = [d.bar_toggle_btn, d.bar_restore_btn, d.bar_prev_btn, d.bar_play_btn, d.bar_next_btn,
       d.bar_mic_btn, d.bar_like_btn, d.handle_icon]
rects = [w.geometry() for w in seq]
check("todos centrados en el eje de la píldora",
      all(abs(r.center().x() - pill.center().x()) <= 1.5 for r in rects), str([r.center().x() for r in rects]))
check("de arriba abajo: toggle, volver, ant, play, sig, mic, corazón, círculo",
      all(rects[i].bottom() < rects[i + 1].top() for i in range(len(rects) - 1)), str([(r.top(), r.bottom()) for r in rects]))
check("todo dentro de la altura de la píldora",
      rects[0].top() >= pill.top() and rects[-1].bottom() <= pill.bottom() + 6, f"{rects[0].top()} {rects[-1].bottom()} / {pill.top():.0f}-{pill.bottom():.0f}")
check("mic y corazón cuentan como botones de acción (no despliegan al pasar el mouse)",
      d.bar_mic_btn in d._bar_action_btns and d.bar_like_btn in d._bar_action_btns)

# la esquina sigue existiendo en el compacto (allí no hay otra forma de volver)
d.set_style("compact"); app.processEvents()
check("compacto: el botón de la esquina SÍ está", d.restore_btn.isVisibleTo(d))
check("compacto: sin micrófono ni corazón en la pestaña", not d.bar_mic_btn.isVisibleTo(d) and not d.bar_like_btn.isVisibleTo(d))
d.set_style("card"); app.processEvents()
check("al volver a tarjeta: sin botón de esquina y con mic/corazón otra vez",
      not d.restore_btn.isVisibleTo(d) and d.bar_mic_btn.isVisibleTo(d) and d.bar_like_btn.isVisibleTo(d))
check("el bloque de la tarjeta sigue dentro de la ventana",
      d.seek_bar.geometry().bottom() < d.height() and d.cover.geometry().top() >= 0)

# ------------------------------------------------------------------ 3
print("== 3) Micrófono: la letra sustituye a la carátula")
fl = d.lyrics_loader
check("al inicio la carátula se ve y la letra no", d.cover.isVisibleTo(d) and not d.lyrics_panel.isVisibleTo(d))
d.bar_mic_btn.click(); app.processEvents()
check("modo letra: panel de letra visible", d.is_lyrics_mode() and d.lyrics_panel.isVisibleTo(d))
check("modo letra: carátula y título ocultos", not d.cover.isVisibleTo(d) and not d.title_label.isVisibleTo(d))
check("modo letra: controles y barra de progreso siguen visibles", d.play_btn.isVisibleTo(d) and d.seek_bar.isVisibleTo(d))
check("modo letra: busca la letra de lo que suena", fl.calls and fl.calls[-1] == ("Daft Punk", "One More Time"), str(fl.calls))
check("modo letra: el panel queda entre arriba y los controles",
      d.lyrics_panel.geometry().bottom() < d.play_btn.geometry().top() and d.lyrics_panel.geometry().top() >= 0)
check("el micrófono se marca como activo", d.bar_mic_btn._active is True)
d.bar_mic_btn.click(); app.processEvents()
check("segundo clic: vuelve la carátula", d.cover.isVisibleTo(d) and not d.lyrics_panel.isVisibleTo(d) and not d.is_lyrics_mode())
d._collapsed = True
d.bar_mic_btn.click(); app.processEvents()
check("con el panel recogido, el micrófono lo despliega", d._collapsed is False and d.is_lyrics_mode())
d.set_style("compact"); app.processEvents()
check("al pasar a compacto se sale del modo letra", not d.is_lyrics_mode())
d.set_style("card")
d2 = DockWindow(WNPBackend(), cl)     # sin cargador de letras (letras deshabilitadas)
d2.set_style("card"); app.processEvents()
check("sin cargador de letras no hay micrófono", not d2.bar_mic_btn.isVisibleTo(d2) and d2.lyrics_panel is None)

# ------------------------------------------------------------------ 4
print("== 4) 'Me gusta' en la barra")
d.set_like_info(LikeInfo(service="spotify", configured=True, liked=True)); app.processEvents()
check("le gusta: corazón relleno y rosa", d.bar_like_btn.icon_name == "heart" and d.bar_like_btn._color_override is not None
      and d.bar_like_btn._color_override.getRgb()[:3] == LIKE_RGB)
d.set_like_info(LikeInfo(service="spotify", configured=True, liked=False)); app.processEvents()
check("no le gusta: corazón en contorno y sin color fijo", d.bar_like_btn.icon_name == "heart_outline" and d.bar_like_btn._color_override is None)
d.set_like_info(LikeInfo()); app.processEvents()
check("otro reproductor: corazón oculto", not d.bar_like_btn.isVisibleTo(d))
d.set_like_info(LikeInfo(service="youtube", configured=False)); app.processEvents()
check("sin cuenta: visible, con tooltip de conectar", d.bar_like_btn.isVisibleTo(d) and "conecta" in d.bar_like_btn.toolTip())
got = []
d.likeToggleRequested.connect(lambda: got.append(1))
d.bar_like_btn.click()
check("clic emite likeToggleRequested", got == [1])

# ------------------------------------------------------------------ 5
print("== 5) Ondas alrededor de la barra")
dr = DockWindow(WNPBackend(), cl, lyrics_loader=FakeLyrics())
dr.set_edge("right"); dr.set_style("card"); dr.show_on_edge(); app.processEvents()
dr.apply_state(st("PAUSED")); app.processEvents()
check("en pausa: sin ondas", not dr._ripple_timer.isActive())
dr.apply_state(st("PLAYING")); app.processEvents()
check("sonando (por defecto activadas): hay ondas", dr._ripple_timer.isActive() and dr.waves_enabled())
frame = dr.grab()
check("pintar con ondas no falla", not frame.isNull())
dr.set_waves_enabled(False)
check("desactivadas en Configuración: se apagan", not dr._ripple_timer.isActive())
dr.set_waves_enabled(True)
check("al reactivarlas vuelven", dr._ripple_timer.isActive())
rr = dr._ripple_rect()
check("el rectángulo de repintado cabe en la ventana (no repinta toda la tarjeta)",
      dr.rect().contains(rr) and rr.width() < dr.width() // 2, str(rr))
dr.set_style("compact"); app.processEvents()
check("estilo compacto: sin ondas", not dr._ripple_timer.isActive())
dr.set_style("card"); app.processEvents()
check("de vuelta a tarjeta sonando: otra vez ondas", dr._ripple_timer.isActive())
theme.REDUCED_MOTION = True
dr._sync_ripples()
check("'reducir movimiento': sin ondas", not dr._ripple_timer.isActive())
theme.REDUCED_MOTION = False
dr._sync_ripples()
dr.hide(); app.processEvents()
check("ventana oculta: el timer se detiene", not dr._ripple_timer.isActive())

# el círculo de ondas
dot = dr.handle_icon
dr.show(); dr.apply_state(st("PLAYING")); app.processEvents(); run(100)
check("círculo de ondas: 4 anillos y animando", dot.RINGS == 4 and dot.is_animating())
check("círculo de ondas: pinta sin errores", not dot.grab().isNull())

# ------------------------------------------------------------------ 6
print("== 6) Selector de reproductor (ventana completa)")
opened = []
player_launcher._open_url = lambda url: opened.append(url) or True      # nada de abrir enlaces reales
from app_controller import AppController
ctrl = AppController(port=54801)
ctrl.config.empty_play_action = "none"
mw = ctrl.main_window
check("el pie ahora es un botón con flecha", isinstance(mw.platform_label, PlatformPickerButton))
mw.platform_label.setText("")
check("sin reproductor el botón muestra 'Elegir reproductor' (y text() sigue vacío)",
      mw.platform_label.text() == "" and "Elegir reproductor" in QPushButton.text(mw.platform_label))
mw.platform_label.setText("YouTube")
check("text() devuelve el nombre sin la flecha", mw.platform_label.text() == "YouTube")
check("el texto mostrado lleva la flecha ▾", QPushButton.text(mw.platform_label).endswith("\u25be"))

chosen = []
mw.startPlayerRequested.connect(chosen.append)
seen = {}
def fake_exec(self, *a, **k):
    acts = [x for x in self.actions() if x.data()]
    seen["keys"] = [x.data() for x in acts]
    seen["checked"] = [x.data() for x in acts if x.isChecked()]
    seen["pick"] = next(x for x in acts if x.data() == "deezer")
    return seen["pick"]
QMenu.exec = fake_exec
mw.apply_state(st("PLAYING", player="Spotify"))
mw._show_platform_menu()
check("el menú ofrece todos los reproductores", seen["keys"] == list(player_launcher.ALL_ACTIONS), str(seen["keys"]))
check("marca el que está sonando (Spotify)", seen["checked"] == ["spotify"], str(seen["checked"]))
check("elegir uno emite startPlayerRequested con su clave", chosen == ["deezer"], str(chosen))
mw.apply_state(st("PLAYING", player="YouTube Music", title="Otra"))
mw._show_platform_menu()
check("YouTube Music se distingue de YouTube", seen["checked"] == ["ytmusic"], str(seen["checked"]))
check("action_for_player_name reconoce los nombres de pywnp",
      [player_launcher.action_for_player_name(n) for n in ("Spotify", "YouTube", "YouTube Music", "SoundCloud", "Deezer", "Apple Music", "Tidal", "VLC")]
      == ["spotify", "youtube", "ytmusic", "soundcloud", "deezer", "applemusic", "tidal", None])
ctrl._start_player("deezer")
check("deezer abre su web", opened[-1] == "https://www.deezer.com", str(opened))
ctrl._start_player("applemusic"); ctrl._start_player("tidal"); ctrl._start_player("soundcloud")
check("las demás webs", opened[-3:] == ["https://music.apple.com", "https://listen.tidal.com", "https://soundcloud.com"], str(opened[-3:]))
check("el ajuste de 'sin reproductor' solo ofrece Spotify/YouTube/YT Music", player_launcher.ACTIONS == ("spotify", "youtube", "ytmusic"))

# ------------------------------------------------------------------ 7
print("== 7) 'Me gusta' en la ventana completa")
check("oculto sin reproducción", not mw.like_btn.isVisibleTo(mw))
mw.set_like_info(LikeInfo(service="spotify", configured=True, liked=True))
check("le gusta: visible, relleno, rosa", mw.like_btn.isVisibleTo(mw) and mw.like_btn.icon_name == "heart"
      and mw.like_btn._color_override.getRgb()[:3] == LIKE_RGB)
mw.set_like_info(LikeInfo(service="spotify", configured=True, liked=False, message="Spotify denegó el acceso (403)."))
check("no le gusta: contorno; el tooltip muestra el error si lo hay",
      mw.like_btn.icon_name == "heart_outline" and "403" in mw.like_btn.toolTip())
fired = []
mw.likeToggleRequested.connect(lambda: fired.append(1))
mw.like_btn.click()
check("clic emite likeToggleRequested", fired == [1])
# El corazón va justo a la izquierda del botón de historial, en la misma fila.
mw.show(); app.processEvents(); run(50)
check("el corazón queda al lado del historial (misma fila, justo a su izquierda)",
      mw.like_btn.parentWidget() is mw.recently_played_btn.parentWidget()
      and 0 < mw.recently_played_btn.geometry().left() - mw.like_btn.geometry().right() <= 12
      and abs(mw.like_btn.geometry().center().y() - mw.recently_played_btn.geometry().center().y()) <= 2,
      f"{mw.like_btn.geometry()} {mw.recently_played_btn.geometry()}")

# ------------------------------------------------------------------ 8
print("== 8) Controlador: cableado de 'me gusta' y ajuste de ondas")
calls = []
ctrl.likes.track_changed = lambda s: calls.append(None if s is None else (s.title, s.player_name))
ctrl.TRACK_SETTLE_MS = 0
ctrl.config.notifications_enabled = False
ctrl.scrobbler.track_changed = lambda *a, **k: None
ctrl._on_playback_state_changed(st("PLAYING", title="Canción A"))
check("al registrar una canción estable se consulta 'me gusta'", calls[-1] == ("Canción A", "Spotify"), str(calls))
ctrl._on_playback_state_changed(PlayerState())
check("sin reproducción: se le avisa (oculta el botón)", calls[-1] is None)
ctrl._on_playback_state_changed(st("PLAYING", title="Escucha música sin anuncios", artist="Spotify"))
check("un anuncio no se puede guardar: se oculta", calls[-1] is None, str(calls[-2:]))
sig = []
ctrl.likes.setupRequested.connect(lambda s: sig.append(s))
check("el gestor está conectado a ambas ventanas",
      ctrl.likes.receivers(ctrl.likes.changed) >= 2)
from dialogs import SettingsDialog
from config import AppConfig
cfgx = AppConfig()
dlg = SettingsDialog(cfgx, 1234, lambda: None, lambda: None, lambda: None)
check("ajuste 'ondas' activado por defecto", dlg.bar_waves_check.isChecked() and cfgx.bar_waves_enabled is True)
dlg.bar_waves_check.setChecked(False); dlg._save()
check("al guardar, el resultado trae el ajuste", dlg.result_bar_waves is False)
check("el diálogo tiene el acceso a las cuentas de 'me gusta'", callable(getattr(dlg, "_open_likes_dialog", None)))
ctrl._apply_play_idle_setting()
ctrl.dock_window.set_waves_enabled(cfgx.bar_waves_enabled)
check("el controlador aplica el ajuste al panel lateral", ctrl.dock_window.waves_enabled() is True)

# ------------------------------------------------------------------ 9
print("== 9) Indicador de reproducción")
pi = PlayingIndicator()
pi.show(); app.processEvents()
check("más grande que el de antes (14x11)", pi.width() >= 18 and pi.height() >= 14, f"{pi.width()}x{pi.height()}")
check("parado: sin timer y pinta un punto", not pi._timer.isActive() and not pi.grab().isNull())
pi.set_playing(True); run(150)
check("sonando: anima con PreciseTimer a ~30 fps", pi._timer.isActive() and pi._timer.interval() <= 40
      and pi._timer.timerType().name == "PreciseTimer")
check("4 barras con alturas dentro de rango tras animar",
      len(pi._bar_heights) == 4 and all(0.2 <= h <= 1.0 for h in pi._bar_heights), str(pi._bar_heights))
h1 = list(pi._bar_heights); run(120)
check("las barras se mueven", pi._bar_heights != h1)
check("pinta con barras sin errores", not pi.grab().isNull())
theme.REDUCED_MOTION = True
pi.set_playing(False); pi.set_playing(True)
check("'reducir movimiento': no anima", not pi._timer.isActive())
theme.REDUCED_MOTION = False
pi.hide()
check("oculto: el timer se detiene", not pi._timer.isActive())

print(f"\n{len(PASS)} OK, {len(FAIL)} fallos")
sys.exit(1 if FAIL else 0)
