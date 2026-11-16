"""Visualizador de audio: espectro de lo que suena por los altavoces.

Cómo funciona
-------------
En Windows se abre el dispositivo "loopback" de WASAPI (la salida de audio
por defecto, vista como si fuera un micrófono) con PyAudioWPatch. Cada bloque
de sonido se convierte a mono, se pasa por una FFT (numpy) y se reparte en
`N_BANDS` bandas logarítmicas (graves a la izquierda, agudos a la derecha).
Todo se procesa en memoria: no se graba, no se guarda y no sale del equipo.

Es OPCIONAL y se apaga solo para no gastar nada:
  - la captura solo corre si está activado en Configuración, hay música
    sonando (estado PLAYING) y alguna ventana está mostrando el visualizador;
  - si falta PyAudioWPatch o numpy, o no estamos en Windows, la función queda
    "no disponible" con un motivo claro y el resto del programa no se entera;
  - si el dispositivo falla (se desconecta, cambia la salida por defecto...)
    se reintenta con espera creciente, sin ruido ni avisos.

Diseño para poder probarlo sin Windows: la fuente de audio es un objeto con
`start(callback)` / `stop()`; el de verdad es `_WasapiLoopbackSource`, y las
pruebas inyectan uno falso. El análisis (`SpectrumAnalyzer`) es una clase
independiente de Qt.
"""
from __future__ import annotations

import importlib
import math
import sys
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from diag import soft

N_BANDS = 36                 # bandas que se calculan (los widgets las remuestrean)
FFT_SIZE = 4096             # muestras por análisis (~85 ms a 48 kHz): resuelve bien los graves
MIN_HZ, MAX_HZ = 60.0, 16000.0
TILT_DB_PER_OCT = 1.5       # compensación de pendiente (la música cae ~3-6 dB por octava)
RANGE_DB = 45.0             # rango dinámico que se muestra por debajo del pico reciente
GAMMA = 1.35                # >1 realza el contraste: lo flojo queda bajo, lo fuerte destaca
FRAME_RATE = 30             # cuadros por segundo hacia la interfaz
RELEASE_PER_S = 2.2         # caída de las barras (escala completa en ~0,45 s)
SILENCE_RMS = 3e-4          # por debajo (≈ -70 dBFS) se considera silencio
STALE_FIRST_S = 5.0         # sin ningún bloque desde que se abrió: reabrir
STALE_LATER_S = 30.0        # sin bloques tras haberlos tenido (silencio real / cambio de salida)
MAX_RETRY_WAIT_S = 60.0


# ----------------------------------------------------------------- disponibilidad
def _can_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def availability() -> tuple[bool, str]:
    """(disponible, motivo). El motivo, si no está disponible, es un texto
    para mostrar al usuario en Configuración."""
    if sys.platform != "win32":
        return False, "Solo está disponible en Windows."
    if not _can_import("numpy"):
        return False, "Falta instalar numpy:  pip install numpy"
    if not _can_import("pyaudiowpatch"):
        return False, "Falta instalar PyAudioWPatch:  pip install PyAudioWPatch"
    return True, ""


def _numpy():
    # Importación ESTÁTICA a propósito: PyInstaller solo empaqueta lo que ve
    # en el código (importlib.import_module("numpy") le pasaría desapercibido
    # y en el .exe el visualizador diría "falta numpy").
    import numpy
    return numpy


# --------------------------------------------------------------------- análisis
class SpectrumAnalyzer:
    """Convierte bloques de audio mono en `n_bands` niveles de 0 a 1.

    - Ventana de Hann + FFT de 4096 muestras; bandas logarítmicas de 60 Hz a 16 kHz.
    - **Potencia media por banda** (no el máximo): las bandas agudas abarcan muchos
      más bins que las graves y con el máximo se inflaban, dejando todas las barras
      casi parejas.
    - Compensación de pendiente SUAVE (+1,5 dB por octava). Con +3 dB se "blanquea"
      la música (que cae ~3 dB por octava) y todas las barras quedaban al mismo nivel.
    - Ganancia automática: los niveles son relativos al pico reciente (45 dB de rango),
      así que se ve igual con volumen alto o bajo; una curva (gamma) realza el contraste.
    - Subida instantánea, caída suave.
    """

    def __init__(self, rate: int, n_bands: int = N_BANDS, fft_size: int = FFT_SIZE):
        np = _numpy()
        self.rate = int(rate)
        self.n_bands = n_bands
        self.fft_size = fft_size
        self._window = np.hanning(fft_size).astype(np.float32)
        freqs = np.fft.rfftfreq(fft_size, 1.0 / self.rate)
        top = min(MAX_HZ, self.rate * 0.45)
        edges = np.geomspace(MIN_HZ, top, n_bands + 1)
        lo = np.searchsorted(freqs, edges[:-1], "left").astype(np.int64)
        hi = np.searchsorted(freqs, edges[1:], "left").astype(np.int64)
        hi = np.maximum(hi, lo + 1)                      # al menos un bin por banda
        self._lo = lo
        self._hi = np.minimum(hi, len(freqs))
        self._lo = np.minimum(self._lo, self._hi - 1)
        self._count = (self._hi - self._lo).astype(np.float32)
        centers = np.sqrt(edges[:-1] * edges[1:])
        self._tilt_db = (TILT_DB_PER_OCT * np.log2(centers / 1000.0)).astype(np.float32)
        self._buffer = np.zeros(fft_size, dtype=np.float32)
        self._levels = np.zeros(n_bands, dtype=np.float32)
        self._ref_db: float | None = None     # pico de referencia (se fija con el primer sonido)

    def reset(self):
        self._buffer[:] = 0.0
        self._levels[:] = 0.0
        self._ref_db = None

    def feed(self, mono, dt: float) -> list[float]:
        """Procesa un bloque de muestras (float32 en [-1, 1]) y devuelve las bandas."""
        np = _numpy()
        mono = np.asarray(mono, dtype=np.float32)
        n = len(mono)
        if n == 0:
            return self.decay(dt)
        if n >= self.fft_size:
            self._buffer = mono[-self.fft_size:].copy()
        else:
            self._buffer = np.concatenate((self._buffer[n:], mono))
        rms = float(np.sqrt(np.mean(self._buffer[-min(n, self.fft_size):] ** 2)))
        if rms < SILENCE_RMS:                    # silencio real: sin esto el ruido de fondo "sube"
            return self.decay(dt)
        spectrum = np.abs(np.fft.rfft(self._buffer * self._window)) / (self.fft_size / 4.0)
        csum = np.concatenate(([0.0], np.cumsum(spectrum.astype(np.float64) ** 2)))
        band_power = (csum[self._hi] - csum[self._lo]) / self._count      # potencia media por bin
        db = 10.0 * np.log10(band_power + 1e-12) + self._tilt_db
        peak = float(db.max())
        # Ganancia automática: sube al instante con el pico y baja despacio. Con el
        # primer sonido (o tras un silencio) se ajusta a él de inmediato, así una
        # canción baja de volumen se ve completa desde el primer cuadro.
        ref = peak if self._ref_db is None else max(peak, self._ref_db - 10.0 * dt)
        self._ref_db = max(ref, -50.0)
        level = np.clip((db - (self._ref_db - RANGE_DB)) / RANGE_DB, 0.0, 1.0) ** GAMMA
        self._levels = np.maximum(level.astype(np.float32), self._levels - RELEASE_PER_S * dt)
        return self._levels.tolist()

    def decay(self, dt: float) -> list[float]:
        """Sin sonido nuevo: las barras bajan solas."""
        np = _numpy()
        self._levels = np.maximum(self._levels - RELEASE_PER_S * dt, 0.0)
        if not float(self._levels.max(initial=0.0)) > 0.0:
            self._ref_db = None            # silencio: la próxima canción se normaliza desde cero
        return self._levels.tolist()


def resample_bands(bands, n: int) -> list[float]:
    """Reparte `bands` en `n` valores (interpolación lineal). Puro Python:
    lo usan los widgets sin tener que importar numpy."""
    if n <= 0:
        return []
    m = len(bands)
    if m == 0:
        return [0.0] * n
    if m == n:
        return [float(v) for v in bands]
    out = []
    for i in range(n):
        pos = (i + 0.5) * m / n - 0.5
        lo = max(0, min(m - 1, int(math.floor(pos))))
        hi = min(m - 1, lo + 1)
        frac = max(0.0, min(1.0, pos - lo))
        out.append(float(bands[lo]) * (1 - frac) + float(bands[hi]) * frac)
    return out


def bass_level(bands, count: int = 6) -> float:
    """Energía de los graves (0 a 1): mueve el brillo de la carátula."""
    if not bands:
        return 0.0
    part = bands[:count]
    return max(0.0, min(1.0, sum(part) / len(part)))


# ------------------------------------------------------------------------ fuentes
class _WasapiLoopbackSource:
    """Captura lo que suena por la salida de audio por defecto (solo Windows).

    Usa el modo con callback: WASAPI en loopback NO entrega bloques durante el
    silencio, y una lectura bloqueante se quedaría colgada para siempre sin
    poder detenerse."""

    def __init__(self):
        self._pa = None
        self._stream = None

    def start(self, callback):
        np = _numpy()
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            device = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if not device.get("isLoopbackDevice"):
                for candidate in pa.get_loopback_device_info_generator():
                    if device["name"] in candidate["name"]:
                        device = candidate
                        break
                else:
                    raise RuntimeError("La salida de audio actual no admite captura.")
            channels = max(1, int(device["maxInputChannels"]))
            rate = int(device["defaultSampleRate"])

            def on_data(in_data, frame_count, time_info, status):
                with soft("audio_levels._WasapiLoopbackSource.start.on_data"):  # nunca dejar que una excepción cruce a PortAudio
                    data = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                    if channels > 1:
                        data = data[: (len(data) // channels) * channels].reshape(-1, channels).mean(axis=1)
                    callback(data, rate)
                return (None, pyaudio.paContinue)

            self._stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                                   frames_per_buffer=1024, input=True,
                                   input_device_index=device["index"], stream_callback=on_data)
            self._pa = pa
            self._stream.start_stream()
        except Exception:
            with soft("audio_levels._WasapiLoopbackSource.start"):
                pa.terminate()
            raise

    def stop(self):
        stream, pa = self._stream, self._pa
        self._stream = self._pa = None
        with soft("audio_levels._WasapiLoopbackSource.stop"):
            if stream is not None:
                stream.stop_stream()
                stream.close()
        with soft("audio_levels._WasapiLoopbackSource.stop"):
            if pa is not None:
                pa.terminate()


# ----------------------------------------------------------------------- servicio
class AudioLevels(QObject):
    """Servicio único de niveles de audio. Emite `levelsChanged(list[float])`
    unas 30 veces por segundo mientras la captura está activa, y la deja
    apagada (sin hilos ni dispositivo abierto) el resto del tiempo."""

    levelsChanged = pyqtSignal(object)
    statusChanged = pyqtSignal(str)      # "" = bien; si no, motivo por el que no funciona

    # Tras fallar la captura por aplicación con un reproductor, no se reintenta
    # con ese mismo reproductor hasta pasado este tiempo (se usa todo el equipo).
    PER_APP_RETRY_S = 600.0

    def __init__(self, parent=None, source_factory=None, per_app_factory=None):
        super().__init__(parent)
        self._source_factory = source_factory or _WasapiLoopbackSource
        # Captura solo del reproductor (process_loopback.py). None = desactivada.
        self._per_app_factory = per_app_factory
        self._target = ""                   # nombre del reproductor a escuchar ('' = todo el equipo)
        self._per_app_failed: dict[str, float] = {}
        self.using_per_app = False
        self._enabled = False
        self._playing = False
        self._viewers: set[int] = set()
        self._source = None
        self._analyzer: SpectrumAnalyzer | None = None
        self._lock = threading.Lock()
        self._latest: list[float] = [0.0] * N_BANDS
        self._last_frame_t = 0.0
        self._last_frame_wall = 0.0
        self._started_at = 0.0
        self._ever_frame = False
        self._fails = 0
        self._next_retry = 0.0
        self._status = ""
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FRAME_RATE))
        self._timer.timeout.connect(self._tick)

    # ---- control desde la interfaz
    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._sync()

    def set_playing(self, playing: bool):
        self._playing = bool(playing)
        self._sync()

    def acquire(self, owner) -> None:
        self._viewers.add(id(owner))
        self._sync()

    def release(self, owner) -> None:
        self._viewers.discard(id(owner))
        self._sync()

    def set_target(self, player_name: str):
        """Reproductor cuyo audio se quiere escuchar ('' = todo el equipo). Si
        cambia mientras se captura, se reabre la captura sobre el nuevo."""
        player_name = player_name or ""
        if player_name == self._target:
            return
        self._target = player_name
        if self._source is not None:
            self._stop_source()
            self._next_retry = 0.0
        self._sync()

    def _make_per_app_source(self):
        """Fuente por aplicación si procede, o None para usar la de todo el equipo."""
        if self._per_app_factory is None or not self._target:
            return None
        failed_at = self._per_app_failed.get(self._target)
        if failed_at is not None and time.monotonic() - failed_at < self.PER_APP_RETRY_S:
            return None
        return self._per_app_factory(self._target)

    def shutdown(self):
        """Al cerrar el programa: suelta el dispositivo de audio."""
        self._enabled = False
        self._viewers.clear()
        self._sync()

    @property
    def running(self) -> bool:
        return self._source is not None

    @property
    def status(self) -> str:
        return self._status

    @property
    def bands(self) -> list[float]:
        with self._lock:
            return list(self._latest)

    # ---- estado
    def _want_running(self) -> bool:
        return self._enabled and self._playing and bool(self._viewers)

    def _set_status(self, text: str):
        if text != self._status:
            self._status = text
            self.statusChanged.emit(text)

    def _sync(self):
        if self._want_running():
            if not self._timer.isActive():
                self._last_tick = time.monotonic()
                self._timer.start()
            if self._source is None and time.monotonic() >= self._next_retry:
                self._start_source()
        else:
            if self._source is not None:
                self._stop_source()
            # El temporizador sigue unos cuadros para que las barras bajen a cero.

    def _start_source(self):
        ok, reason = availability() if self._source_factory is _WasapiLoopbackSource else (True, "")
        if not ok:
            self._set_status(reason)
            self._next_retry = time.monotonic() + MAX_RETRY_WAIT_S
            return
        source = None
        per_app = None
        with soft("audio_levels.AudioLevels._start_source.per_app"):
            per_app = self._make_per_app_source()
        if per_app is not None:
            try:
                self._analyzer = None
                self._ever_frame = False
                self._started_at = time.monotonic()
                self._source = per_app
                per_app.start(self._on_frames)
                self.using_per_app = True
                self._fails = 0
                self._set_status("")
                return
            except Exception:
                # Windows sin la API, proceso no encontrado, error de COM...: se usa
                # todo el equipo, como antes, y no se insiste durante un rato.
                self._source = None
                self._per_app_failed[self._target] = time.monotonic()
                with soft("audio_levels.AudioLevels._start_source.per_app_stop"):
                    per_app.stop()
        self.using_per_app = False
        try:
            source = self._source_factory()
            self._analyzer = None
            self._ever_frame = False
            self._started_at = time.monotonic()
            self._source = source
            source.start(self._on_frames)
            self._fails = 0
            self._set_status("")
        except Exception as exc:
            self._source = None
            self._fails += 1
            wait = min(MAX_RETRY_WAIT_S, 2.0 * (2 ** min(self._fails, 5)))
            self._next_retry = time.monotonic() + wait
            self._set_status(f"No se pudo abrir la captura de audio: {exc}")
            with soft("audio_levels.AudioLevels._start_source"):
                if source is not None:
                    source.stop()

    def _stop_source(self):
        source, self._source = self._source, None
        if source is not None:
            with soft("audio_levels.AudioLevels._stop_source"):
                source.stop()

    # ---- hilo de captura (NO toca widgets: solo guarda el último resultado)
    def _on_frames(self, mono, rate: int):
        with soft("audio_levels.AudioLevels._on_frames"):
            now = time.monotonic()
            with self._lock:
                if self._analyzer is None or self._analyzer.rate != rate:
                    self._analyzer = SpectrumAnalyzer(rate)
                dt = min(0.2, max(0.001, now - self._last_frame_t)) if self._last_frame_t else 0.02
                self._latest = self._analyzer.feed(mono, dt)
                self._last_frame_t = now
                self._ever_frame = True

    # ---- hilo de la interfaz
    def _tick(self):
        now = time.monotonic()
        dt = max(0.001, min(0.2, now - self._last_tick))
        self._last_tick = now
        with self._lock:
            fresh = self._ever_frame and (now - self._last_frame_t) < 0.15
            if not fresh and self._analyzer is not None:
                self._latest = self._analyzer.decay(dt)         # sin bloques nuevos: bajan solas
            elif not fresh:
                self._latest = [max(0.0, v - RELEASE_PER_S * dt) for v in self._latest]
            bands = list(self._latest)
        if self._want_running():
            self._watchdog(now)
        elif max(bands, default=0.0) <= 0.0:
            self._timer.stop()                                    # ya está todo en cero
        self.levelsChanged.emit(bands)

    def _watchdog(self, now: float):
        """Reabre la captura si el dispositivo dejó de entregar sonido (cambió
        la salida de audio, se desconectaron los auriculares...) o si nunca
        arrancó."""
        if self._source is None:
            if now >= self._next_retry:
                self._start_source()
            return
        if self._ever_frame:
            idle = now - self._last_frame_t
            limit = STALE_LATER_S
        else:
            idle = now - self._started_at
            limit = STALE_FIRST_S
        if idle > limit:
            self._stop_source()
            self._next_retry = now + 2.0
