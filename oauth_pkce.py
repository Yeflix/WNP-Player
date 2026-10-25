"""
OAuth 2.0 con PKCE para aplicaciones de escritorio (RFC 7636 + RFC 8252).

Flujo: se abre el navegador en la pantalla de permisos del servicio; al aceptar,
el servicio redirige a http://127.0.0.1:<puerto>/callback, donde este módulo
tiene un servidor local de un solo uso que recoge el `code`; se canjea por un
`access_token` + `refresh_token`. Solo se guarda el refresh_token (en la
configuración, igual que las claves de Last.fm); el access_token dura ~1 h y se
renueva solo.

Sin dependencias externas (urllib + http.server). Todo lo que toca la red está
en funciones pequeñas para poder sustituirlas en los tests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections.abc import Callable

CALLBACK_PATH = "/callback"
_TIMEOUT_S = 15

_PAGE_OK = ("<html><head><meta charset='utf-8'><title>Listo</title></head>"
            "<body style='font-family:Segoe UI,sans-serif;background:#12121a;color:#eee;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
            "<div style='text-align:center'><h2>✔ Cuenta conectada</h2>"
            "<p>Ya puedes cerrar esta pestaña y volver al reproductor.</p></div></body></html>")
_PAGE_ERR = ("<html><head><meta charset='utf-8'><title>Error</title></head>"
             "<body style='font-family:Segoe UI,sans-serif;background:#12121a;color:#eee;"
             "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
             "<div style='text-align:center'><h2>No se pudo conectar</h2><p>%s</p></div></body></html>")


class OAuthError(Exception):
    """Fallo legible para mostrar al usuario."""


# ------------------------------------------------------------------- PKCE
def make_verifier(nbytes: int = 48) -> str:
    """43–128 caracteres [A-Za-z0-9-._~] (RFC 7636 §4.1)."""
    return secrets.token_urlsafe(nbytes)[:128]


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def redirect_uri(port: int) -> str:
    # 127.0.0.1 y no "localhost": Spotify (y las guías de Google) lo exigen así.
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def build_authorize_url(auth_url: str, client_id: str, redirect: str, scopes: list[str],
                        state: str, challenge: str, extra: dict | None = None) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if extra:
        params.update(extra)
    return auth_url + ("&" if "?" in auth_url else "?") + urllib.parse.urlencode(params)


# --------------------------------------------------------- servidor de retorno
class CallbackServer:
    """Servidor local de un solo uso. Se crea ANTES de abrir el navegador para
    conocer el puerto real (con puerto 0 lo elige el sistema)."""

    def __init__(self, port: int = 0):
        self._result: dict | None = None
        self._event = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self.send_response(404)
                    self.end_headers()
                    return
                q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                outer._result = q
                ok = "code" in q and "error" not in q
                body = (_PAGE_OK if ok else _PAGE_ERR % (q.get("error_description") or q.get("error") or "")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer._event.set()

            def log_message(self, *args):  # silencio: nada de ruido en consola
                pass

        try:
            self._server = HTTPServer(("127.0.0.1", port), Handler)
        except OSError as exc:
            raise OAuthError(
                f"No se pudo abrir el puerto {port} para recibir la respuesta del navegador "
                f"({exc}). Ciérralo o usa otro."
            ) from exc
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def wait(self, expected_state: str, timeout_s: float = 180.0,
             cancelled: Callable[[], bool] | None = None) -> str:
        """Espera el redireccionamiento y devuelve el `code`."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._event.wait(0.25):
                break
            if cancelled is not None and cancelled():
                raise OAuthError("Conexión cancelada.")
        else:
            raise OAuthError("Se agotó el tiempo esperando la autorización en el navegador.")
        res = self._result or {}
        if res.get("error"):
            raise OAuthError(f"El servicio rechazó la autorización: {res.get('error_description') or res['error']}")
        if res.get("state") != expected_state:
            raise OAuthError("La respuesta no coincide con la solicitud (state distinto). Inténtalo de nuevo.")
        code = res.get("code")
        if not code:
            raise OAuthError("El servicio no devolvió ningún código de autorización.")
        return code

    def close(self):
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------- tokens
def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode({k: v for k, v in data.items() if v not in (None, "")}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            detail = payload.get("error_description") or payload.get("error") or ""
        except Exception:  # noqa: BLE001
            pass
        raise OAuthError(f"El servicio respondió {exc.code}. {detail}".strip()) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OAuthError(f"No se pudo conectar con el servicio: {getattr(exc, 'reason', exc)}") from exc


def exchange_code(token_url: str, client_id: str, code: str, redirect: str, verifier: str,
                  client_secret: str = "") -> dict:
    tok = _post_form(token_url, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": client_id, "code_verifier": verifier, "client_secret": client_secret})
    if not tok.get("access_token"):
        raise OAuthError("El servicio no devolvió un token de acceso.")
    tok["obtained_at"] = time.time()
    return tok


def refresh_access_token(token_url: str, client_id: str, refresh_token: str,
                         client_secret: str = "") -> dict:
    tok = _post_form(token_url, {
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": client_id, "client_secret": client_secret})
    if not tok.get("access_token"):
        raise OAuthError("El servicio no devolvió un token de acceso al renovar.")
    tok["obtained_at"] = time.time()
    return tok


def authorize(auth_url: str, token_url: str, client_id: str, scopes: list[str],
              port: int = 0, client_secret: str = "", extra: dict | None = None,
              open_browser: Callable[[str], object] = webbrowser.open,
              timeout_s: float = 180.0, cancelled: Callable[[], bool] | None = None,
              on_waiting: Callable[[str], None] | None = None) -> dict:
    """Flujo completo. Devuelve el JSON del token (con `refresh_token`).
    Bloquea: llamar desde un hilo, nunca desde el de la interfaz."""
    if not client_id:
        raise OAuthError("Falta el Client ID.")
    server = CallbackServer(port)
    try:
        redirect = redirect_uri(server.port)
        verifier = make_verifier()
        state = secrets.token_urlsafe(16)
        url = build_authorize_url(auth_url, client_id, redirect, scopes, state, challenge_for(verifier), extra)
        if on_waiting:
            on_waiting(url)
        if not open_browser(url):
            raise OAuthError("No se pudo abrir el navegador.")
        code = server.wait(state, timeout_s, cancelled)
        return exchange_code(token_url, client_id, code, redirect, verifier, client_secret)
    finally:
        server.close()
