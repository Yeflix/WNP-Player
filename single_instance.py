"""
Evita que se abran dos instancias del programa a la vez.

Usa un socket local (QLocalServer/QLocalSocket) con un nombre fijo: si al
arrancar ya hay alguien escuchando en ese nombre, significa que ya hay una
instancia corriendo. En ese caso le mandamos un mensaje corto para que se
muestre a sí misma, y esta segunda instancia debe salir sin hacer nada
más (sin competir por el mismo puerto de WebNowPlaying, sin abrir una
segunda ventana, etc).
"""
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_SERVER_NAME = "WNPPlayer-single-instance-v1"
_SHOW_MESSAGE = b"show"
_CONNECT_TIMEOUT_MS = 200


class SingleInstanceGuard(QObject):
    """Emite `showRequested` cuando una segunda instancia intenta abrirse
    mientras esta (la primera) sigue corriendo."""

    showRequested = pyqtSignal()

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
        data = bytes(conn.readAll())
        if data == _SHOW_MESSAGE:
            self.showRequested.emit()

    def release(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(_SERVER_NAME)
