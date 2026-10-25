"""Diálogo para conectar Spotify y/o YouTube (botón "me gusta").

Ambos servicios exigen una app propia (gratuita) en su consola de
desarrolladores: aquí se pega su Client ID, se pulsa Conectar y se autoriza en
el navegador. Solo se guarda un refresh_token en la configuración.
La conexión corre en un hilo (no congela la ventana) y se puede cancelar."""
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox

import likes
import oauth_pkce
from dialogs import _DialogBase, _section_label
from theme import Palette, FONT_BODY


class LikesDialog(_DialogBase):
    _connectFinished = pyqtSignal(str, object, str)   # servicio, token|None, error

    def __init__(self, config, on_changed=None, parent=None):
        super().__init__(parent, title="Cuentas para «Me gusta»", width=460)
        self.config = config
        self._on_changed = on_changed
        self._cancel = {"spotify": False, "youtube": False}
        self._busy = {"spotify": False, "youtube": False}
        self._connectFinished.connect(self._on_connect_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)

        title = QLabel("Cuentas para «Me gusta»")
        title.setStyleSheet(f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
                            f"font-size: 14px; font-weight: 600; background: transparent;")
        layout.addWidget(title)
        intro = QLabel("El botón del corazón guarda la canción en tus favoritas de Spotify, o da «me gusta» "
                       "al video en YouTube. Cada servicio pide una app tuya (gratuita); sigue los pasos.")
        intro.setWordWrap(True)
        intro.setStyleSheet(self._hint_css())
        layout.addWidget(intro)

        self.enabled_check = QCheckBox("Mostrar el botón «me gusta»")
        self.enabled_check.setChecked(getattr(config, "likes_enabled", True))
        self.enabled_check.toggled.connect(self._toggle_enabled)
        layout.addWidget(self.enabled_check)

        # ---- Spotify
        layout.addWidget(_section_label("Spotify"))
        sp_hint = QLabel(
            "1. En <a href='https://developer.spotify.com/dashboard'>developer.spotify.com/dashboard</a> crea "
            "una app (su dueño necesita Spotify Premium).<br>"
            f"2. En <i>Redirect URIs</i> añade exactamente: <b>http://127.0.0.1:{likes.SPOTIFY_REDIRECT_PORT}/callback</b><br>"
            "3. Pega aquí su <i>Client ID</i> y pulsa Conectar.")
        sp_hint.setWordWrap(True)
        sp_hint.setOpenExternalLinks(True)
        sp_hint.setTextFormat(Qt.TextFormat.RichText)
        sp_hint.setStyleSheet(self._hint_css())
        layout.addWidget(sp_hint)
        self.spotify_id_input = QLineEdit(config.spotify_client_id)
        self.spotify_id_input.setPlaceholderText("Client ID de Spotify")
        layout.addWidget(self.spotify_id_input)
        sp_row = QHBoxLayout()
        self.spotify_btn = QPushButton("Conectar")
        self.spotify_btn.setObjectName("dialogButton")
        self.spotify_btn.clicked.connect(lambda: self._connect_clicked("spotify"))
        sp_row.addWidget(self.spotify_btn)
        self.spotify_status = QLabel("")
        self.spotify_status.setWordWrap(True)
        sp_row.addWidget(self.spotify_status, 1)
        layout.addLayout(sp_row)

        # ---- YouTube
        layout.addWidget(_section_label("YouTube"))
        yt_hint = QLabel(
            "1. En <a href='https://console.cloud.google.com'>console.cloud.google.com</a> crea un proyecto y "
            "activa <i>YouTube Data API v3</i>.<br>"
            "2. En la pantalla de consentimiento añade tu cuenta como usuario de prueba y publícala "
            "(<i>En producción</i>); si no, el permiso caduca a los 7 días.<br>"
            "3. Credenciales → ID de cliente de OAuth → <i>Aplicación de escritorio</i>. Pega el ID y el secreto.<br>"
            "<i>Solo identifica videos de youtube.com; en YouTube Music no se puede.</i>")
        yt_hint.setWordWrap(True)
        yt_hint.setOpenExternalLinks(True)
        yt_hint.setTextFormat(Qt.TextFormat.RichText)
        yt_hint.setStyleSheet(self._hint_css())
        layout.addWidget(yt_hint)
        self.google_id_input = QLineEdit(config.google_client_id)
        self.google_id_input.setPlaceholderText("Client ID de Google")
        layout.addWidget(self.google_id_input)
        self.google_secret_input = QLineEdit(config.google_client_secret)
        self.google_secret_input.setPlaceholderText("Client secret de Google")
        self.google_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.google_secret_input)
        yt_row = QHBoxLayout()
        self.youtube_btn = QPushButton("Conectar")
        self.youtube_btn.setObjectName("dialogButton")
        self.youtube_btn.clicked.connect(lambda: self._connect_clicked("youtube"))
        yt_row.addWidget(self.youtube_btn)
        self.youtube_status = QLabel("")
        self.youtube_status.setWordWrap(True)
        yt_row.addWidget(self.youtube_status, 1)
        layout.addLayout(yt_row)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("dialogButtonAccent")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._refresh_ui()

    # ---------------------------------------------------------------- utilidades
    @staticmethod
    def _hint_css() -> str:
        return (f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; font-size: 10px; "
                f"background: transparent;")

    def _connected(self, service: str) -> bool:
        c = self.config
        return bool(c.spotify_refresh_token) if service == "spotify" else bool(c.google_refresh_token)

    def _set_status(self, service: str, text: str, ok: bool = False, error: bool = False):
        label = self.spotify_status if service == "spotify" else self.youtube_status
        color = Palette.TEXT_DIM if ok else (Palette.ERROR if error else Palette.TEXT_FAINT)
        label.setText(text)
        label.setStyleSheet(f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: 10px; background: transparent;")

    def _refresh_ui(self):
        for service, btn in (("spotify", self.spotify_btn), ("youtube", self.youtube_btn)):
            if self._busy[service]:
                btn.setText("Cancelar")
            else:
                btn.setText("Desconectar" if self._connected(service) else "Conectar")
                self._set_status(service, "Conectado" if self._connected(service) else "Sin conectar",
                                 ok=self._connected(service))

    def _notify_changed(self):
        self.config.save()
        if self._on_changed:
            self._on_changed()

    def _toggle_enabled(self, on: bool):
        self.config.likes_enabled = bool(on)
        self._notify_changed()

    # ------------------------------------------------------------------ conexión
    def _connect_clicked(self, service: str):
        if self._busy[service]:
            self._cancel[service] = True
            self._set_status(service, "Cancelando…")
            return
        if self._connected(service):                       # Desconectar
            if service == "spotify":
                self.config.spotify_refresh_token = ""
            else:
                self.config.google_refresh_token = ""
            self._notify_changed()
            self._refresh_ui()
            return
        client_id = (self.spotify_id_input if service == "spotify" else self.google_id_input).text().strip()
        if not client_id:
            self._set_status(service, "Escribe primero el Client ID.", error=True)
            return
        secret = "" if service == "spotify" else self.google_secret_input.text().strip()
        self._busy[service] = True
        self._cancel[service] = False
        self._refresh_ui()
        self._set_status(service, "Esperando la autorización en el navegador…")
        self._start_worker(service, client_id, secret)

    def _authorize(self, service: str, client_id: str, secret: str) -> dict:
        """Separado para poder sustituirlo en los tests (no abre navegador)."""
        if service == "spotify":
            return oauth_pkce.authorize(
                likes.SPOTIFY_AUTH_URL, likes.SPOTIFY_TOKEN_URL, client_id, likes.SPOTIFY_SCOPES,
                port=likes.SPOTIFY_REDIRECT_PORT, cancelled=lambda: self._cancel[service])
        return oauth_pkce.authorize(
            likes.GOOGLE_AUTH_URL, likes.GOOGLE_TOKEN_URL, client_id, likes.YOUTUBE_SCOPES,
            port=0, client_secret=secret, cancelled=lambda: self._cancel[service],
            extra={"access_type": "offline", "prompt": "consent"})

    def _start_worker(self, service: str, client_id: str, secret: str):
        def work():
            try:
                self._connectFinished.emit(service, self._authorize(service, client_id, secret), "")
            except oauth_pkce.OAuthError as exc:
                self._connectFinished.emit(service, None, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._connectFinished.emit(service, None, f"Error inesperado: {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _on_connect_finished(self, service: str, tok, error: str):
        self._busy[service] = False
        if error or not tok:
            self._refresh_ui()
            self._set_status(service, error or "No se pudo conectar.", error=True)
            return
        refresh = tok.get("refresh_token")
        if not refresh:
            self._refresh_ui()
            self._set_status(service, "El servicio no devolvió un permiso duradero. Inténtalo de nuevo.", error=True)
            return
        if service == "spotify":
            self.config.spotify_client_id = self.spotify_id_input.text().strip()
            self.config.spotify_refresh_token = refresh
        else:
            self.config.google_client_id = self.google_id_input.text().strip()
            self.config.google_client_secret = self.google_secret_input.text().strip()
            self.config.google_refresh_token = refresh
        self._notify_changed()
        self._refresh_ui()

    def done(self, result):
        for k in self._cancel:      # cerrar el diálogo cancela una conexión a medias
            self._cancel[k] = True
        super().done(result)
