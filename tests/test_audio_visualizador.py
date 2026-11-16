"""Visualizador de audio: análisis, ciclo de vida del servicio, widgets e integración."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
import audio_levels as AL
from audio_levels import SpectrumAnalyzer, AudioLevels, N_BANDS

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1
def pump(s=0.2):
    t = time.time()
    while time.time() - t < s: app.processEvents(); time.sleep(0.003)

RATE = 48000
T = np.arange(AL.FFT_SIZE) / RATE
def tone(f, amp=0.5): return (amp * np.sin(2 * np.pi * f * T)).astype(np.float32)
def band_of(f):
    edges = np.geomspace(AL.MIN_HZ, min(AL.MAX_HZ, RATE * 0.45), N_BANDS + 1)
    return int(np.searchsorted(edges, f, "right") - 1)

# ------------------------------------------------------------------ análisis
an = SpectrumAnalyzer(RATE)
for f in (100, 440, 1000, 4000, 12000):
    an.reset(); b = an.feed(tone(f), 0.02)
    check(f"{f} Hz cae en su banda ({band_of(f)})", int(np.argmax(b)) == band_of(f))
an.reset(); check("silencio -> todo en cero", max(an.feed(np.zeros(AL.FFT_SIZE, np.float32), 0.02)) == 0.0)
an.reset(); low = max(an.feed(tone(440, 0.02), 0.02)); an.reset(); high = max(an.feed(tone(440, 0.8), 0.02))
check("volumen bajo y alto se ven igual (ganancia automática)", abs(low - high) < 0.05 and low > 0.9)
an.reset(); b = an.feed(tone(440), 0.02); c = an.decay(0.1)
check("sin sonido nuevo las barras bajan solas", max(c) < max(b))
for _ in range(20): c = an.decay(0.1)
check("y llegan a cero", max(c) == 0.0)
an.reset(); b = an.feed(tone(440)[:300], 0.02)
check("bloques cortos (menos que la FFT) también funcionan", len(b) == N_BANDS and max(b) > 0)
an.reset(); an.feed(np.zeros(0, np.float32), 0.02)
check("un bloque vacío no rompe nada", True)
an44 = SpectrumAnalyzer(44100); check("otra frecuencia de muestreo (44,1 kHz)", len(an44.feed(tone(1000), 0.02)) == N_BANDS)
check("resample_bands conserva el valor si coincide el tamaño", AL.resample_bands([0.1, 0.2], 2) == [0.1, 0.2])
rs = AL.resample_bands(list(np.linspace(0, 1, 32)), 50)
check("resample_bands a más barras: monótono y en [0,1]", len(rs) == 50 and all(rs[i] <= rs[i + 1] + 1e-9 for i in range(49)) and 0 <= min(rs) and max(rs) <= 1)
check("resample_bands con lista vacía", AL.resample_bands([], 5) == [0.0] * 5 and AL.resample_bands([1], 0) == [])
check("bass_level promedia los graves", abs(AL.bass_level([1, 1, 1, 1, 1, 1, 0, 0]) - 1.0) < 1e-9 and AL.bass_level([]) == 0.0)

# ------------------------------------------------------------ disponibilidad
ok, reason = AL.availability()
check("fuera de Windows: no disponible y explica por qué", (not ok) and "Windows" in reason)
real_platform, real_can = sys.platform, AL._can_import
try:
    sys.platform = "win32"
    AL._can_import = lambda n: n != "pyaudiowpatch"
    check("Windows sin PyAudioWPatch: dice qué instalar", "PyAudioWPatch" in AL.availability()[1])
    AL._can_import = lambda n: n != "numpy"
    check("Windows sin numpy: dice qué instalar", "numpy" in AL.availability()[1])
    AL._can_import = lambda n: True
    check("Windows con todo: disponible", AL.availability() == (True, ""))
finally:
    sys.platform, AL._can_import = real_platform, real_can

# ------------------------------------------------------------------- servicio
class FakeSource:
    instances = []; fail = False
    def __init__(self): self.cb = None; self.started = 0; self.stopped = 0; FakeSource.instances.append(self)
    def start(self, cb):
        if FakeSource.fail: raise RuntimeError("sin dispositivo")
        self.cb = cb; self.started += 1
    def stop(self): self.stopped += 1

svc = AudioLevels(source_factory=FakeSource)
got = []; svc.levelsChanged.connect(lambda b: got.append(list(b)))
statuses = []; svc.statusChanged.connect(statuses.append)
svc.set_enabled(True); svc.set_playing(True)
check("activado y sonando pero sin nadie mirando: NO captura", not svc.running and not FakeSource.instances)
viewer = object(); svc.acquire(viewer)
check("al aparecer un visualizador empieza a capturar", svc.running and FakeSource.instances[-1].started == 1)
src = FakeSource.instances[-1]
src.cb(tone(1000), RATE); pump(0.15)
check("se emiten niveles con el pico en la banda correcta", got and int(np.argmax(got[-1])) == band_of(1000) and max(got[-1]) > 0.9)
n_before = len(got); pump(0.3)
check("sin bloques nuevos las barras bajan (se sigue emitiendo)", len(got) > n_before and max(got[-1]) < max(got[n_before - 1]) or max(got[-1]) == 0)
src.cb(object(), RATE)      # basura: no debe romper el hilo
check("un bloque inválido no lanza excepción", True)
svc.set_playing(False)
check("al pausar la música se detiene la captura", not svc.running and src.stopped == 1)
pump(0.6)
check("las barras terminan en cero y el temporizador se apaga", max(got[-1]) == 0.0 and not svc._timer.isActive())
svc.set_playing(True)
check("al volver a sonar reanuda", svc.running and FakeSource.instances[-1] is not src)
svc.set_enabled(False)
check("al desactivar en Configuración se detiene", not svc.running)
svc.set_enabled(True); svc.release(viewer)
check("al ocultarse el último visualizador se detiene", not svc.running)

# ---- fallos del dispositivo: sin ruido y con reintento creciente
FakeSource.fail = True; FakeSource.instances.clear()
svc.acquire(viewer)
check("si el dispositivo falla no hay excepción y se informa el motivo", not svc.running and "sin dispositivo" in svc.status and statuses[-1] == svc.status)
first_wait = svc._next_retry - time.monotonic()
svc._next_retry = 0; svc._sync()
check("reintenta y la espera crece", svc._fails >= 2 and (svc._next_retry - time.monotonic()) > first_wait)
FakeSource.fail = False; svc._next_retry = 0; svc._tick()
check("al volver el dispositivo se recupera y limpia el aviso", svc.running and svc.status == "")
src = FakeSource.instances[-1]; svc._started_at = time.monotonic() - 10
svc._tick()
check("si nunca llega sonido (cambió la salida de audio) se reabre", not svc.running and src.stopped == 1)
svc._next_retry = 0; svc._tick()
check("y arranca de nuevo", svc.running)
svc.shutdown()
check("shutdown suelta el dispositivo", not svc.running)

real_svc = AudioLevels(); real_svc.set_enabled(True); real_svc.set_playing(True); real_svc.acquire(viewer)
check("con la fuente real fuera de Windows: no hay captura, hay motivo", not real_svc.running and "Windows" in real_svc.status)
real_svc.shutdown()

# ------------------------------------------------------------------- widgets
from widgets import SpectrumBars, PlayingIndicator
class Spy:
    def __init__(self): self.acq = 0; self.rel = 0
bars = SpectrumBars(height=44); bars.resize(300, 44)
svc2 = AudioLevels(source_factory=FakeSource); svc2.set_enabled(True); svc2.set_playing(True)
bars.set_source(svc2)
check("conectar el servicio con el widget oculto no captura", not svc2.running)
bars.show(); pump(0.05)
check("al mostrarse pide captura", svc2.running)
bars.hide(); pump(0.05)
check("al ocultarse la suelta", not svc2.running)
bars.show(); pump(0.05)
bars.set_levels([0.0] * 16 + [1.0] * 16); pump(0.05)
img = bars.grab().toImage()
lit = sum(1 for x in range(0, img.width(), 2) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 120)
check("pinta barras", lit > 50)
check("el número de barras se ajusta al ancho", bars._bar_count() == int((300 + 3) // 7))
bars.set_levels([1.0] * 32); bars.set_levels([0.0] * 32)
check("la marca de pico cae despacio", max(bars._peaks) > 0.9)
theme.REDUCED_MOTION = True
bars.hide(); bars.show(); pump(0.05)
check("con 'reducir movimiento' no captura", not svc2.running)
theme.REDUCED_MOTION = False
bars.hide(); bars.set_source(None); svc2.shutdown()

ind = PlayingIndicator(); ind.set_playing(True); ind.show()
ind.set_levels([1.0] * 4 + [0.0] * 28)
check("indicador del encabezado: graves altos, agudos bajos", ind._bar_heights[0] > 0.9 and ind._bar_heights[3] < 0.3)
ind._tick()
check("mientras llega audio real no se pisa con la simulación", ind._bar_heights[0] > 0.9)
ind._live_until = 0; ind._tick()
check("sin audio real vuelve la animación decorativa", ind._bar_heights != [1.0, 0.15, 0.15, 0.15])
ind2 = PlayingIndicator(); ind2.set_levels([1.0] * 32)
check("si no está sonando se ignora", ind2._live_until == 0.0)

# ---------------------------------------------------------- ventana principal
from backend import WNPBackend
from cover_loader import CoverArtLoader
import main_window
mw = main_window.MainWindow(WNPBackend(), CoverArtLoader()); mw.show(); pump(0.2)
svc3 = AudioLevels(source_factory=FakeSource); mw.set_audio_levels(svc3)
h0 = mw.height()
check("el visualizador está oculto por defecto", not mw.spectrum.isVisibleTo(mw))
mw.set_audio_visualizer_visible(True); pump(0.1)
check("al activarlo la ventana crece para alojar las barras", mw.height() >= h0 + 40 and mw.spectrum.isVisible())
mw.set_audio_visualizer_visible(False); pump(0.1)
check("al desactivarlo vuelve a su altura", abs(mw.height() - h0) <= 2 and not mw.spectrum.isVisible())
theme.REDUCED_MOTION = True; mw.set_audio_visualizer_visible(True)
check("con 'reducir movimiento' no se muestra", not mw.spectrum.isVisibleTo(mw))
theme.REDUCED_MOTION = False
mw._glow_playing = True; mw._on_audio_levels([1.0] * 32)
check("el borde de la carátula sigue los graves", mw.cover._glow_intensity > 0.95 and mw._audio_glow_until > time.monotonic())
mw._on_audio_levels([0.0] * 32)
check("y baja con el silencio", mw.cover._glow_intensity < 0.45)

# ------------------------------------------------- configuración y controlador
import config
check("por defecto está activado (desde 1.5)", config.AppConfig().audio_visualizer is True)
c = config.AppConfig(); c.audio_visualizer = True; c.save()
check("la opción se guarda", config.AppConfig.load().audio_visualizer is True)
import dialogs
dlg = dialogs.SettingsDialog(config.AppConfig(audio_visualizer=True), 1234, lambda: None, lambda: None, lambda: None)
check("Configuración: sin soporte la casilla queda desactivada y apagada", not dlg.audio_visualizer_check.isEnabled() and not dlg.audio_visualizer_check.isChecked())
check("y el motivo se ve en el tooltip", "Windows" in dlg.audio_visualizer_check.toolTip())
from app_controller import AppController
ctrl = AppController(port=54339)
ctrl._apply_audio_visualizer(True)
check("controlador: sin soporte se queda desactivado, sin errores", ctrl.config.audio_visualizer is False and not ctrl.main_window.spectrum.isVisibleTo(ctrl.main_window))
AL.availability = lambda: (True, "")
ctrl._apply_audio_visualizer(True)
check("controlador: con soporte se activa y muestra las barras", ctrl.config.audio_visualizer is True and ctrl.main_window.spectrum.isVisibleTo(ctrl.main_window))
ctrl.audio_levels._source_factory = FakeSource
from backend import PlayerState
ctrl._on_playback_state_changed(PlayerState(connected=True, player_name="Spotify", state="PLAYING", title="T", artist="A"))
check("el estado PLAYING le avisa al servicio", ctrl.audio_levels._playing is True)
ctrl._on_playback_state_changed(PlayerState(connected=True, player_name="Spotify", state="PAUSED", title="T", artist="A"))
check("y PAUSED también", ctrl.audio_levels._playing is False)
ctrl.shutdown()
check("al cerrar el programa se suelta la captura", not ctrl.audio_levels.running and not ctrl.audio_levels._enabled)

# ------------------------------------------- barras: caen solas al pausar la música
bars2 = SpectrumBars(height=44); bars2.resize(300, 44); bars2.show(); pump(0.05)
bars2.set_levels([1.0] * N_BANDS); pump(0.05)
check("al llegar niveles el temporizador de caída trabaja", bars2._settle_timer.isActive() and max(bars2._peaks) > 0.9)
pump(1.6)
check("sin niveles nuevos las barras y los picos bajan a cero y el temporizador se apaga",
      not bars2._settle_timer.isActive() and not bars2._levels and not bars2._peaks)
img = bars2.grab().toImage()
row = [img.pixelColor(x, img.height() - 3).alpha() for x in range(20, img.width() - 20, 5)]
check("en reposo se ve una línea tenue continua (no puntos sueltos)", all(a > 20 for a in row))
bars2.hide(); bars2.deleteLater()

# ------------------------------------------------ panel lateral: ondas con audio real
import dock_window as dk
from backend import PlayerState
svc4 = AudioLevels(source_factory=FakeSource)
dock = dk.DockWindow(WNPBackend(), CoverArtLoader()); dock.set_style("card"); dock.set_edge("right")
dock.set_audio_levels(svc4); dock.show(); pump(0.1)
st = PlayerState(connected=True, player_name="Spotify", state="PLAYING", title="T", artist="A", duration_seconds=200, can_play_pause=True)
dock.apply_state(st); pump(0.1)
check("sin la opción activada no pide captura", not svc4._viewers and not dock._audio_waves_live())
dock.set_audio_visualizer_enabled(True); pump(0.1)
check("con la opción activada y música sonando pide captura", id(dock) in svc4._viewers)
check("pero sin datos todavía usa las ondas decorativas de siempre", not dock._audio_waves_live())
bands = [1.0 if i < 6 else 0.2 for i in range(N_BANDS)]
dock._on_audio_levels(bands)
check("con audio real dibuja las ondas del espectro", dock._audio_waves_live())
pill = dock._pill_rect()
path_r = dock._wave_path(pill, bands, 0.0, 12.0)
xs = [path_r.elementAt(i).x for i in range(path_r.elementCount())]
check("panel a la DERECHA: las ondas salen de derecha a izquierda (hacia fuera, x < borde de la píldora)", max(xs) < pill.left() and min(xs) < pill.left() - 8)
dock.set_edge("left"); pump(0.1); pill = dock._pill_rect()
path_l = dock._wave_path(pill, bands, 0.0, 12.0)
xs = [path_l.elementAt(i).x for i in range(path_l.elementCount())]
check("panel a la IZQUIERDA: las ondas salen de izquierda a derecha (x > borde de la píldora)", min(xs) > pill.right() and max(xs) > pill.right() + 8)
mid = path_l.elementAt(path_l.elementCount() // 2).x - pill.right()
edge_pt = path_l.elementAt(1).x - pill.right()
check("los graves (centro) sobresalen más que los extremos", mid > edge_pt)
img = dock.grab().toImage()
check("el panel se dibuja sin errores con las ondas", img.width() > 0)
for _ in range(5): dock._on_audio_levels(bands); time.sleep(0.09)
check("se guardan contornos de eco (con separación mínima)", 2 <= len(dock._contours) <= 10)
dock._live_at = time.monotonic() - 1.0
check("si dejan de llegar niveles vuelve a las ondas decorativas", not dock._audio_waves_live())
dock.set_style("compact"); pump(0.1)
check("estilo compacto: no hay ondas, así que no se captura", id(dock) not in svc4._viewers)
dock.set_style("card"); dock.set_waves_enabled(False); pump(0.1)
check("con las ondas desactivadas en Configuración tampoco se captura", id(dock) not in svc4._viewers)
dock.set_waves_enabled(True); dock.apply_state(PlayerState(connected=True, state="PAUSED", title="T", artist="A")); pump(0.1)
check("en pausa no se captura", id(dock) not in svc4._viewers)
dock.hide(); svc4.shutdown()

print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
