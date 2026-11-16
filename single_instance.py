"""
Evita que se abran dos instancias del programa a la vez.

Usa un socket local (QLocalServer/QLocalSocket) con un nombre fijo: si al
arrancar ya hay alguien escuchando en ese nombre, significa que ya hay una
instancia corriendo. En ese caso le mandamos un mensaje corto para que se
muestre a sí misma, y esta segunda instancia debe salir sin hacer nada
más (sin competir por el mismo puerto de WebNowPlaying, sin abrir una
segunda ventana, etc).

También acepta la orden "quit" (`YefriPlayer.exe --quit`): la usa el
instalador para cerrar limpiamente la copia en marcha antes de actualizarla
(guardando la configuración y parando el servidor), en vez de matarla.

Además, en Windows, la instancia principal crea el mutex con nombre
`APP_MUTEX_NAME`: es lo que el instalador (Inno Setup, directiva AppMutex)
mira para saber si el programa sigue abierto.
"""
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_SERVER_NAME = "YefriPlayer-single-instance-v1"
_SHOW_MESSAGE = b"show"
_QUIT_MESSAGE = b"quit"
_CONNECT_TIMEOUT_MS = 200
# Debe coincidir con AppMutex en installer/YefriPlayer.iss.
APP_MUTEX_NAME = "YefriPlayerAppMutex"
_mutex_handles: list = []   # se conservan abiertos mientras viva el proceso


class SingleInstanceGuard(QObject):
    """Emite `showRequested` cuando una segunda instancia intenta abrirse
    mientras esta (la primera) sigue corriendo."""

    showRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """True si esta es la única instancia y debe seguir arrancando
        normal. False si ya había otra instancia corriendo (ya se le avisó
        que se muestre; quien llama debe salir sin hacer nada más)."""
        probe = QLocalSocket()
        probe.connectToServer(_SERVER_NAME)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            probe.write(_SHOW_MESSAGE)
            probe.flush()
            probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            return False

        # Nadie escuchando: seremos el servidor para futuras instancias.
        # Primero limpiamos por si quedó un socket huérfano de un cierre
        # anormal anterior (por ejemplo, el proceso murió sin llegar a
        # cerrar el servidor limpiamente).
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(_SERVER_NAME)
        create_app_mutex()
        return True

    def _on_new_connection(self):
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: self._on_ready_read(conn))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready_read(self, conn):
        data = bytes(conn.readAll()).strip()
        if data == _SHOW_MESSAGE:
            self.showRequested.emit()
        elif data == _QUIT_MESSAGE:
            self.quitRequested.emit()

    def release(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(_SERVER_NAME)


def send_quit(timeout_ms: int = 1500) -> bool:
    """Pide a la instancia en marcha que se cierre. True si había una y recibió
    la orden. Para `--quit`: crea su propia QCoreApplication mínima (sin
    ventanas) porque los sockets de Qt la necesitan."""
    from PyQt6.QtCore import QCoreApplication
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])  # noqa: F841 — debe vivir hasta salir
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(_QUIT_MESSAGE)
    sock.flush()
    ok = sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return bool(ok)


def create_app_mutex() -> None:
    """Crea (y deja abierto) el mutex con nombre que el instalador usa para
    detectar que YefriPlayer está abierto. Fuera de Windows no hace nada.
    Se crean la versión de sesión y la global (Inno Setup recomienda ambas para
    que también se detecte una copia abierta en otra sesión de usuario)."""
    if sys.platform != "win32" or _mutex_handles:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        for name in (APP_MUTEX_NAME, "Global\\" + APP_MUTEX_NAME):
            handle = kernel32.CreateMutexW(None, False, name)
            if handle:
                _mutex_handles.append(handle)
    except Exception:  # noqa: S110 — sin mutex el instalador solo pierde el aviso; la app sigue igual
        pass
