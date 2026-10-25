"""Reproducir sin ningún reproductor abierto -> abrir Spotify / YouTube.

    QT_QPA_PLATFORM=offscreen python tests/test_start_player.py
"""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="wnp_start_")
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["LOCALAPPDATA"] = TMP

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

from PyQt6.QtWidgets import QApplication
app = QApplication([])
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True)
app.setStyleSheet(theme.build_global_qss())

import player_launcher
from backend import WNPBackend, PlayerState
from config import AppConfig
from app_controller import AppController

# ------------------------------------------------------------------ 1
print("== 1) player_launcher")
opened = []
player_launcher._open_url = lambda url: opened.append(url) or True
player_launcher._spotify_protocol_registered = lambda: True
check("spotify -> protocolo spotify:", player_launcher.launch("spotify") and opened[-1] == "spotify:", str(opened))
check("youtube -> youtube.com", player_launcher.launch("youtube") and opened[-1] == "https://www.youtube.com")
check("ytmusic -> music.youtube.com", player_launcher.launch("ytmusic") and opened[-1] == "https://music.youtube.com")
check("acción desconocida no abre nada", player_launcher.launch("otra") is False and len(opened) == 3)
player_launcher._spotify_protocol_registered = lambda: False
player_launcher._spotify_exe = lambda: None
opened.clear()
check("sin Spotify instalado cae a open.spotify.com",
      player_launcher.launch("spotify") and opened == [player_launcher.SPOTIFY_WEB], str(opened))
player_launcher._spotify_protocol_registered = lambda: True

# ------------------------------------------------------------------ 2
print("== 2) backend: señal solo si lleva >= 1 s sin reproductor")
b = WNPBackend(port=54501)
got = []
b.noPlayerPlayRequested.connect(lambda: got.append(1))
b._running = True
calls = []
b._safe = lambda fn: calls.append("toggle")
b._no_media_since = time.monotonic()            # acaba de quedarse sin nada
b.toggle_play_pause()
check("recién sin reproductor: aún cuenta como hueco entre canciones", got == [] and calls == ["toggle"])
b._no_media_since = time.monotonic() - 2.0
b.toggle_play_pause()
check("tras el margen: emite la señal y NO manda play", got == [1] and calls == ["toggle"])
b._no_media_since = None                        # suena algo
b.toggle_play_pause()
check("con reproductor: play normal, sin señal", got == [1] and calls == ["toggle", "toggle"])
b._running = False; b._no_media_since = time.monotonic() - 5
b.toggle_play_pause()
check("servidor parado: no hace nada", got == [1])

# _poll mantiene _no_media_since
from pywnp.pywnp import WNPRedux, MediaInfo
b2 = WNPBackend(port=54502); b2._wnp = WNPRedux; b2._running = True
mi = MediaInfo(); mi._id = "x"; WNPRedux.media_info = mi
b2._poll()
check("sin medios: _no_media_since se establece", b2._no_media_since is not None)
mi.player_name = "YouTube"; mi.state = "PLAYING"; mi.title = "Algo"
b2._poll()
check("con medios: se limpia", b2._no_media_since is None)
mi.title = ""; mi.state = "STOPPED"
b2._poll()
check("vuelve a quedarse sin nada: se vuelve a marcar", b2._no_media_since is not None)

# ------------------------------------------------------------------ 3
print("== 3) controlador: acciones")
ctrl = AppController(port=54503)
launched = []
player_launcher.launch = lambda a: launched.append(a) or True
toggles = []
ctrl.backend.toggle_play_pause = lambda: toggles.append(1)

for act, expected in (("spotify", ["spotify"]), ("youtube", ["youtube"]), ("ytmusic", ["ytmusic"])):
    launched.clear(); ctrl._autoplay_until = 0.0
    ctrl.config.empty_play_action = act
    ctrl._on_no_player_play()
    check(f"acción '{act}' abre lo configurado", launched == expected, str(launched))
check("solo Spotify programa el autoplay", ctrl._autoplay_until == 0.0)   # el último fue ytmusic
launched.clear()
ctrl.config.empty_play_action = "none"
ctrl._on_no_player_play()
check("'none' no abre nada", launched == [])
ctrl.config.empty_play_action = "ask"
ctrl._choose_player_from_menu = lambda: "youtube"
ctrl._on_no_player_play()
check("'ask' abre lo que se elija en el menú", launched == ["youtube"])
launched.clear()
ctrl._choose_player_from_menu = lambda: None
ctrl._on_no_player_play()
check("'ask' cerrando el menú sin elegir no abre nada", launched == [])
ctrl.config.empty_play_action = "valor_raro"
ctrl._choose_player_from_menu = lambda: "spotify"
ctrl._on_no_player_play()
check("valor de config desconocido se trata como 'ask'", launched == ["spotify"])

# ------------------------------------------------------------------ 4
print("== 4) autoplay de Spotify (una sola vez, con límites)")
def sp(state="PAUSED", name="Spotify", title="Canción", can=True):
    return PlayerState(connected=True, player_name=name, state=state, title=title, can_play_pause=can)

ctrl.TRACK_SETTLE_MS = 0
ctrl.config.notifications_enabled = False
ctrl.scrobbler.track_changed = lambda *a, **k: None
toggles.clear(); ctrl._start_player("spotify")
check("abrir Spotify programa el autoplay", ctrl._autoplay_until > time.monotonic())
ctrl._on_playback_state_changed(PlayerState())                  # aún sin sesión
check("sin sesión todavía: no toca nada y sigue esperando", toggles == [] and ctrl._autoplay_until)
ctrl._on_playback_state_changed(sp(name="YouTube"))
check("otra app no cuenta", toggles == [] and ctrl._autoplay_until)
ctrl._on_playback_state_changed(sp(can=False))
check("sin controles aún: sigue esperando", toggles == [] and ctrl._autoplay_until)
ctrl._on_playback_state_changed(sp())
check("Spotify en pausa con controles: play UNA vez", toggles == [1] and ctrl._autoplay_until == 0.0)
ctrl._on_playback_state_changed(sp(title="Otra"))
check("no vuelve a darle play", toggles == [1])

toggles.clear(); ctrl._start_player("spotify")
ctrl._on_playback_state_changed(sp(state="PLAYING"))
check("si ya suena solo, no se alterna (se pausaría)", toggles == [] and ctrl._autoplay_until == 0.0)

toggles.clear(); ctrl._start_player("spotify")
ctrl._autoplay_until = time.monotonic() - 1
ctrl._on_playback_state_changed(sp(title="Tarde"))
check("pasado el límite no actúa", toggles == [] and ctrl._autoplay_until == 0.0)

# ------------------------------------------------------------------ 5
print("== 5) ajuste en Configuración")
from dialogs import SettingsDialog
check("valor por defecto 'ask'", AppConfig().empty_play_action == "ask")
import dialogs
cfg = AppConfig(); cfg.empty_play_action = "ytmusic"
d = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None)
check("el combo refleja el valor guardado", d.empty_play_combo.currentData() == "ytmusic")
d.empty_play_combo.setCurrentIndex(d.empty_play_combo.findData("none"))
d._save()
check("al guardar, el resultado trae la elección", d.result_empty_play_action == "none", str(d.result_empty_play_action))
cfg2 = AppConfig(); cfg2.empty_play_action = "basura"
d2 = dialogs.SettingsDialog(cfg2, 1234, lambda: None, lambda: None, lambda: None)
check("un valor desconocido cae a 'Preguntar'", d2.empty_play_combo.currentData() == "ask")
check("las 5 opciones están", sorted(d.empty_play_combo.itemData(i) for i in range(d.empty_play_combo.count()))
      == ["ask", "none", "spotify", "youtube", "ytmusic"])

print("== 6) clic real en los botones sin reproductor")
ctrl6 = AppController(port=54506)
ctrl6.config.empty_play_action = "none"   # sin menu modal: aqui solo se mide la señal
sig6 = []
ctrl6.backend.noPlayerPlayRequested.connect(lambda: sig6.append(1))
ctrl6.backend._running = True
ctrl6.backend._no_media_since = time.monotonic() - 3
idle = PlayerState()    # nada reproduciéndose
ctrl6._apply_play_idle_setting()          # config 'none'
for w in (ctrl6.main_window, ctrl6.mini_window, ctrl6.dock_window):
    w.apply_state(idle)
check("con 'No hacer nada' y sin reproductor el play está desactivado (como antes)",
      not ctrl6.main_window.play_btn.isEnabled())
ctrl6.config.empty_play_action = "ask"
ctrl6._apply_play_idle_setting()
check("con acción 'preguntar' el play de la ventana completa está activo", ctrl6.main_window.play_btn.isEnabled())
check("... el del modo compacto", ctrl6.mini_window.play_btn.isEnabled())
check("... y los dos del panel lateral", ctrl6.dock_window.play_btn.isEnabled() and ctrl6.dock_window.bar_play_btn.isEnabled())
check("siguiente/anterior siguen desactivados (no hay a quién mandarlos)",
      not ctrl6.main_window.next_btn.isEnabled() and not ctrl6.mini_window.prev_btn.isEnabled())
ctrl6.config.empty_play_action = "none"
ctrl6._apply_play_idle_setting()
check("al elegir 'No hacer nada' se vuelven a desactivar",
      not ctrl6.main_window.play_btn.isEnabled() and not ctrl6.dock_window.bar_play_btn.isEnabled())
ctrl6.config.empty_play_action = "none"   # sin menu modal en los clics
for w in (ctrl6.main_window, ctrl6.mini_window, ctrl6.dock_window):
    w.set_play_idle_enabled(True)          # el botón debe poder pulsarse para medir la señal
ctrl6.main_window.play_btn.set_icon("play")
ctrl6.main_window.play_btn.click()
check("ventana completa: emite la señal", sig6 == [1])
check("ventana completa: el icono NO pasa a 'pause'", ctrl6.main_window.play_btn.icon_name == "play")
ctrl6.mini_window.play_btn.set_icon("play")
ctrl6.mini_window.play_btn.click()
check("modo compacto: emite la señal", sig6 == [1, 1])
check("modo compacto: el icono NO pasa a 'pause'", ctrl6.mini_window.play_btn.icon_name == "play")
ctrl6.dock_window.play_btn.click()
check("panel lateral: emite la señal", sig6 == [1, 1, 1])
ctrl6.dock_window.bar_play_btn.click()
check("panel lateral (barra): emite la señal", sig6 == [1, 1, 1, 1])
ctrl6.tray_playpause_action.trigger()
check("menú de la bandeja: emite la señal", sig6 == [1, 1, 1, 1, 1])
ctrl6._on_hotkey_triggered("play_pause")
check("atajo global: emite la señal", len(sig6) == 6)
ctrl6.backend._no_media_since = None
ctrl6.main_window.play_btn.set_icon("play")
ctrl6.main_window.play_btn.click()
check("con reproductor el icono sí alterna (sin regresión)", ctrl6.main_window.play_btn.icon_name == "pause" and len(sig6) == 6)

print(f"\n{len(PASS)} OK, {len(FAIL)} fallos")
sys.exit(1 if FAIL else 0)
