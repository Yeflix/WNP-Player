"""Puente con el tema "Switch" de Spicetify (theme.js).

El reproductor abre un pequeño servidor WebSocket SOLO en 127.0.0.1 y el
theme.js que corre dentro de Spotify se conecta a él (igual que la extensión
WebNowPlaying se conecta al puerto de pywnp). Por ahí viajan mensajes JSON
muy cortos:

    Spotify  -> reproductor   {"type": "hello", "mode": "cosmos", "modes": [{"id", "name", "desc"}, ...]}
    Spotify  -> reproductor   {"type": "mode",  "mode": "cover"}      (el usuario cambió de modo en Spotify)
    reproductor -> Spotify    {"type": "set",   "mode": "yefridev"}   (el usuario eligió un modo aquí)

Así los modos se leen de theme.js (lista MODES): si agregas un modo nuevo allá,
aparece solo en el reproductor, sin tocar Python.

Nada de esto toca el audio ni el puerto de pywnp (1234): es un canal aparte.
"""
from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QHostAddress
from PyQt6.QtWebSockets import QWebSocket, QWebSocketServer

DEFAULT_THEME_PORT = 8977

# Lista de respaldo: se usa mientras Spotify no está conectado (todavía no
# informó sus modos). Cuando Spotify se conecta, la lista real la reemplaza.
FALLBACK_MODES = [
    {"id": "cosmos", "name": "Cosmos", "desc": "Cielo estrellado con estrellas fugaces"},
    {"id": "cover", "name": "Cover", "desc": "La carátula de la canción como fondo"},
    {"id": "yefridev", "name": "YefriDev", "desc": "Cyberpunk: rojo, azul y negro con circuitos"},
]

_MAX_MESSAGE_CHARS = 16_384   # el cliente local nunca manda más que unos cientos de bytes


class SpotifyThemeBridge(QObject):
    connectionChanged = pyqtSignal(bool)   # hay al menos un Spotify conectado
    modeChanged = pyqtSignal(str)          # modo activo (informado por Spotify o elegido aquí)
    modesChanged = pyqtSignal(list)        # lista de modos disponibles cambió
    error = pyqtSignal(str)

    def __init__(self, port: int = DEFAULT_THEME_PORT, last_mode: str = "", parent=None):
        super().__init__(parent)
        self.port = port
        self._server: QWebSocketServer | None = None
        self._clients: list[QWebSocket] = []
        self._modes: list[dict] = [dict(m) for m in FALLBACK_MODES]
        self._mode: str = last_mode if self._known(last_mode) else ""
        # Modo elegido en el reproductor mientras Spotify estaba cerrado: se
        # envía apenas Spotify se conecte. (Lo que se eligió en Spotify NO se
        # pisa al conectar: solo se envía lo que el usuario pidió aquí.)
        self._pending: str = ""
        self._last_error: str = ""

    # ------------------------------------------------------------ consulta
    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.isListening()

    @property
    def is_connected(self) -> bool:
        return bool(self._clients)

    @property
    def last_error(self) -> str:
        return self._last_error

    def modes(self) -> list[dict]:
        return [dict(m) for m in self._modes]

    def mode(self) -> str:
        """Último modo conocido ('' si todavía no se sabe)."""
        return self._mode

    def mode_name(self, mode_id: str) -> str:
        for m in self._modes:
            if m["id"] == mode_id:
                return m["name"]
        return mode_id

    def _known(self, mode_id: str) -> bool:
        return any(m["id"] == mode_id for m in getattr(self, "_modes", FALLBACK_MODES))

    # ------------------------------------------------------- ciclo de vida
    def start(self) -> bool:
        if self.is_running:
            return True
        server = QWebSocketServer("WNP Player - tema de Spotify",
                                  QWebSocketServer.SslMode.NonSecureMode, self)
        # Solo la propia PC: nunca otra máquina de la red.
        if not server.listen(QHostAddress("127.0.0.1"), self.port):
            self._last_error = (f"No se pudo abrir el puerto {self.port} para el tema de "
                                f"Spotify: {server.errorString()}")
            server.deleteLater()
            self.error.emit(self._last_error)
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        self._last_error = ""
        return True

    def stop(self):
        had_clients = bool(self._clients)
        clients, self._clients = self._clients, []
        for ws in clients:
            ws.close()
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        if had_clients:
            self.connectionChanged.emit(False)

    def restart_on_port(self, port: int) -> bool:
        self.stop()
        self.port = port
        return self.start()

    # --------------------------------------------------------------- acciones
    def set_mode(self, mode_id: str) -> bool:
        """Pide a Spotify cambiar de modo. Devuelve False si el modo no existe.
        Si Spotify no está conectado, queda pendiente hasta que se conecte."""
        if not self._known(mode_id):
            return False
        self._pending = mode_id if not self._clients else ""
        self._send_all({"type": "set", "mode": mode_id})
        self._update_mode(mode_id)
        return True

    # --------------------------------------------------------------- conexiones
    def _on_new_connection(self):
        server = self._server
        while server is not None and server.hasPendingConnections():
            ws = server.nextPendingConnection()
            if ws is None:
                break
            ws.setParent(self)
            self._clients.append(ws)
            ws.textMessageReceived.connect(lambda text, w=ws: self._on_message(w, text))
            ws.disconnected.connect(lambda w=ws: self._on_disconnected(w))
            if len(self._clients) == 1:
                self.connectionChanged.emit(True)

    def _on_disconnected(self, ws: QWebSocket):
        ws.deleteLater()
        if ws not in self._clients:
            return   # ya lo retiró stop(): nada más que avisar
        self._clients.remove(ws)
        if not self._clients:
            try:
                self.connectionChanged.emit(False)
            except RuntimeError:
                pass   # el puente ya se destruyó (cierre de la app)

    def _on_message(self, ws: QWebSocket, text: str):
        if len(text) > _MAX_MESSAGE_CHARS:
            return
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "hello":
            self._on_hello(ws, msg)
        elif kind == "mode":
            mode_id = msg.get("mode")
            if isinstance(mode_id, str) and self._known(mode_id):
                self._pending = ""
                self._update_mode(mode_id)

    def _on_hello(self, ws: QWebSocket, msg: dict):
        modes = self._parse_modes(msg.get("modes"))
        if modes and modes != self._modes:
            self._modes = modes
            self.modesChanged.emit(self.modes())
        reported = msg.get("mode")
        pending, self._pending = self._pending, ""
        if pending and self._known(pending) and pending != reported:
            # El usuario eligió un modo aquí mientras Spotify estaba cerrado.
            if ws.isValid():
                ws.sendTextMessage(json.dumps({"type": "set", "mode": pending}))
            self._update_mode(pending)
        elif isinstance(reported, str) and self._known(reported):
            self._update_mode(reported)

    @staticmethod
    def _parse_modes(raw) -> list[dict]:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw[:50]:
            if not isinstance(item, dict):
                continue
            mid, name = item.get("id"), item.get("name")
            if not isinstance(mid, str) or not mid.strip() or not isinstance(name, str):
                continue
            desc = item.get("desc")
            out.append({"id": mid, "name": name[:60], "desc": desc[:160] if isinstance(desc, str) else ""})
        return out

    def _update_mode(self, mode_id: str):
        if mode_id != self._mode:
            self._mode = mode_id
            self.modeChanged.emit(mode_id)

    def _send_all(self, payload: dict):
        data = json.dumps(payload)
        for ws in self._clients:
            if ws.isValid():
                ws.sendTextMessage(data)


# ---------------------------------------------------------------- menú (Qt)
def make_theme_menu(title: str, bridge: SpotifyThemeBridge, parent=None):
    """Submenú "Tema de Spotify" con un modo por opción (marca el actual).

    Sirve igual para el menú del engranaje y el de la bandeja: se vuelve a
    llenar cada vez que se despliega (aboutToShow), así siempre refleja los
    modos reales de theme.js y el estado de la conexión. Devuelve el QMenu;
    quien lo llama lo agrega con parent_menu.addMenu(...)."""
    from PyQt6.QtGui import QActionGroup
    from PyQt6.QtWidgets import QMenu

    menu = QMenu(title, parent)

    def populate():
        menu.clear()
        if not bridge.is_running:
            off = menu.addAction("Desactivado (ver Configuración)")
            off.setEnabled(False)
            return
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = bridge.mode()
        for m in bridge.modes():
            act = menu.addAction(m["name"])
            act.setCheckable(True)
            act.setChecked(m["id"] == current)
            act.setData(m["id"])
            if m["desc"]:
                act.setToolTip(m["desc"])
            group.addAction(act)
        menu.addSeparator()
        status = menu.addAction("Spotify conectado" if bridge.is_connected
                                else "Esperando a Spotify...")
        status.setEnabled(False)

    def on_triggered(action):
        mode_id = action.data()
        if isinstance(mode_id, str) and mode_id:
            bridge.set_mode(mode_id)

    menu.aboutToShow.connect(populate)
    menu.triggered.connect(on_triggered)
    populate()
    return menu
