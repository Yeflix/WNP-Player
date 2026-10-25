"""
Descarga las carátulas en un hilo aparte para no bloquear la interfaz,
y las cachea por URL para evitar descargas repetidas. También calcula (en
ese mismo hilo, sin costo extra para la interfaz) un par de colores de
acento a partir de la imagen, para poder teñir el resto de la app con
colores que combinen con lo que se está reproduciendo (ver accent.py).
"""
from __future__ import annotations

import base64
import http.client
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

from accent import extract_accent_pair

_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (WNP-Player)"}
_MAX_CACHE_ITEMS = 24
# Lado máximo (px) al que se reducen las carátulas ANTES de cachearlas. Algunos
# servicios entregan portadas de 1200-3000 px: cada QImage cacheada pesaba
# 6-36 MB (x40 entradas = cientos de MB) para dibujar como mucho 260 px lógicos
# (~780 px físicos a 300 % de escala). 800 px sobra y el caché queda en ~60 MB.
_MAX_COVER_SIDE = 800
_TIMEOUT_SECONDS = 4
_MAX_REDIRECTS = 5
_RETRY_QUEUE_DELAY_MS = 2500  # pausa antes del reintento extra si la descarga falló del todo

# Pool chico de conexiones HTTP(S) reutilizables por (scheme, host, port),
# para no pagar el handshake TCP/TLS de nuevo en cada carátula cuando
# varias vienen seguidas del mismo servidor (típico al saltar canciones en
# una playlist del mismo sitio). http.client no sigue redirecciones solo
# (a diferencia de urllib.request), así que _http_get() las sigue a mano.
_connection_pools: dict[tuple, list] = {}
_pool_lock = threading.Lock()


def _borrow_connection(scheme: str, host: str, port: int):
    key = (scheme, host, port)
    with _pool_lock:
        pool = _connection_pools.setdefault(key, [])
        if pool:
            return pool.pop()
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=_TIMEOUT_SECONDS)
    return http.client.HTTPConnection(host, port, timeout=_TIMEOUT_SECONDS)


def _return_connection(scheme: str, host: str, port: int, conn, reusable: bool):
    if not reusable:
        try:
            conn.close()
        except Exception:
            pass
        return
    key = (scheme, host, port)
    with _pool_lock:
        pool = _connection_pools.setdefault(key, [])
        if len(pool) < 4:
            pool.append(conn)
            return
    conn.close()


def _http_get(url: str) -> bytes:
    """GET simple con conexiones reutilizables y redirecciones manuales
    (301/302/303/307/308), acotado a _MAX_REDIRECTS para nunca colgarse en
    un bucle. Lanza si falla; el llamador ya está en un try/except."""
    for _ in range(_MAX_REDIRECTS):
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn = _borrow_connection(parts.scheme, parts.hostname, port)
        ok = False
        try:
            conn.request("GET", path, headers=_REQUEST_HEADERS)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                resp.read()  # drenar antes de reusar/cerrar la conexión
                ok = True
                if not location:
                    raise ValueError("Redirección sin Location")
                url = urllib.parse.urljoin(url, location)
                continue
            raw = resp.read()
            ok = True
            if not (200 <= resp.status < 300):
                raise ValueError(f"HTTP {resp.status}")
            return raw
        finally:
            _return_connection(parts.scheme, parts.hostname, port, conn, ok)
    raise ValueError("Demasiadas redirecciones")


_MAX_DOWNLOAD_ATTEMPTS = 3       # intento inicial + 2 reintentos
_RETRY_DELAY_SECONDS = 0.5       # entre intentos — corre en el hilo de fondo, no bloquea la interfaz


class _JobSignals(QObject):
    finished = pyqtSignal(str, QImage, tuple, tuple)


class _CoverJob(QRunnable):
    def __init__(self, url: str, signals: _JobSignals):
        super().__init__()
        self.url = url
        self._signals = signals

    def run(self):
        image = QImage()
        try:
            if self.url.startswith("data:"):
                # Nunca vale la pena reintentar esto: no depende de la red,
                # si falla es porque los datos están mal (van a seguir mal).
                _, _, b64data = self.url.partition(",")
                raw = base64.b64decode(b64data)
                image.loadFromData(raw)
            elif self.url.startswith(("http://", "https://")):
                image = self._download_with_retry()
        except Exception:
            image = QImage()

        if not image.isNull() and max(image.width(), image.height()) > _MAX_COVER_SIDE:
            from PyQt6.QtCore import Qt
            image = image.scaled(_MAX_COVER_SIDE, _MAX_COVER_SIDE,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)

        # Calculado acá (hilo de fondo) a propósito: es el mismo hilo que ya
        # hace la descarga, así que no le cuesta nada extra a la interfaz.
        try:
            accent_a, accent_b = extract_accent_pair(image if not image.isNull() else None)
        except Exception:
            from theme import Palette
            accent_a, accent_b = Palette.ACCENT_A, Palette.ACCENT_B

        try:
            self._signals.finished.emit(self.url, image, accent_a, accent_b)
        except RuntimeError:
            pass  # app cerrándose: el QObject de señales ya no existe

    def _download_with_retry(self) -> QImage:
        """Hasta _MAX_DOWNLOAD_ATTEMPTS intentos, con una pausa corta entre
        cada uno. Cubre el caso típico de por qué esto podía fallar sin
        que en realidad haya nada mal: una conexión reutilizada del pool
        (ver _http_get) que murió del lado del servidor justo antes de
        reusarse, o un corte de red de medio segundo. Corre en el hilo de
        fondo del QThreadPool, así que la pausa entre intentos no bloquea
        la interfaz para nada — como mucho retrasa un poco esa carátula
        puntual."""
        for attempt in range(_MAX_DOWNLOAD_ATTEMPTS):
            try:
                raw = _http_get(self.url)
                image = QImage()
                image.loadFromData(raw)
                if not image.isNull():
                    return image
            except Exception:
                pass
            if attempt < _MAX_DOWNLOAD_ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
        return QImage()


class CoverArtLoader(QObject):
    """Punto único para pedir carátulas; emite coverReady(url, QImage) cuando
    están listas, y colorsReady(url, accent_a, accent_b) con el par de
    colores de acento extraído de esa misma imagen.

    Robustez de la descarga/color: `_CoverJob` ya reintenta la descarga en
    sí hasta 3 veces (ver `_download_with_retry`). Si aun así las 3
    fallan (host caído un momento, corte de red breve), antes esto se
    daba por perdido para siempre: como la URL fallida no queda en caché,
    solo se reintentaba si alguien volvía a pedir exactamente esa misma
    URL más tarde — algo que en la práctica casi nunca pasa (la canción ya
    cambió), así que la ventana se quedaba mostrando los colores previos
    (o los por defecto) durante el resto de esa reproducción. Ahora, si el
    trabajo termina sin imagen, se reintenta UNA vez más automáticamente
    tras una pausa corta (ver `_RETRY_QUEUE_DELAY_MS`) antes de resignarse
    del todo — cubre justo esa falla transitoria sin machacar el host con
    reintentos infinitos."""

    coverReady = pyqtSignal(str, QImage)
    colorsReady = pyqtSignal(str, tuple, tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._cache: dict[str, QImage] = {}
        self._color_cache: dict[str, tuple] = {}
        self._pending: set[str] = set()
        self._requeued: set[str] = set()  # URLs que ya tuvieron su reintento extra (no de nuevo)
        self._signals = _JobSignals()
        self._signals.finished.connect(self._on_job_finished)

    def request(self, url: str):
        if not url:
            return
        cached = self._cache.get(url)
        if cached is not None:
            self.coverReady.emit(url, cached)
            colors = self._color_cache.get(url)
            if colors is not None:
                self.colorsReady.emit(url, *colors)
            return
        if url in self._pending:
            return
        self._pending.add(url)
        self._pool.start(_CoverJob(url, self._signals))

    def _on_job_finished(self, url: str, image: QImage, accent_a: tuple, accent_b: tuple):
        self._pending.discard(url)
        if not image.isNull():
            if len(self._cache) >= _MAX_CACHE_ITEMS:
                oldest = next(iter(self._cache))
                self._cache.pop(oldest)
                self._color_cache.pop(oldest, None)
            self._cache[url] = image
            self._color_cache[url] = (accent_a, accent_b)
            self._requeued.discard(url)  # si venía de un reintento, ya no hace falta recordarlo
        elif url not in self._requeued:
            # Falló la descarga (las 3 veces internas de _CoverJob). En vez
            # de resignarnos para siempre, un único reintento extra tras
            # una pausa corta: si fue un corte de red momentáneo, esto lo
            # recupera solo; si el host sigue mal, el segundo intento
            # también falla y ahí sí no se insiste más (self._requeued ya
            # tiene la URL marcada, así que no entra de nuevo a este ramal).
            self._requeued.add(url)
            QTimer.singleShot(_RETRY_QUEUE_DELAY_MS, lambda: self._retry(url))
            return  # no emitir todavía con la imagen vacía: se reintenta primero
        self.coverReady.emit(url, image)
        self.colorsReady.emit(url, accent_a, accent_b)

    def _retry(self, url: str):
        # Puede que mientras esperaba el reintento alguien ya haya vuelto
        # a pedir esta URL por su cuenta (quedó en _pending) — no duplicar.
        if url in self._pending:
            return
        self._pending.add(url)
        self._pool.start(_CoverJob(url, self._signals))
