"""Botón de "me gusta": OAuth PKCE, clientes de Spotify/YouTube y gestor.

Todo contra servidores locales / funciones de red sustituidas: no toca internet.

    QT_QPA_PLATFORM=offscreen python tests/test_likes.py
"""
import json, os, sys, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="wnp_likes_")
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["LOCALAPPDATA"] = TMP

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

from PyQt6.QtCore import QEventLoop, QThreadPool, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True)
app.setStyleSheet(theme.build_global_qss())

import oauth_pkce, likes
from backend import PlayerState
from config import AppConfig

def run(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

def settle():
    QThreadPool.globalInstance().waitForDone(); run(30); app.processEvents()

# ------------------------------------------------------------------ 1
print("== 1) PKCE")
v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"      # vector del RFC 7636, apéndice B
check("challenge S256 coincide con el vector del RFC",
      oauth_pkce.challenge_for(v) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
ver = oauth_pkce.make_verifier()
check("verifier: 43-128 caracteres y alfabeto permitido",
      43 <= len(ver) <= 128 and all(c.isalnum() or c in "-._~" for c in ver), str(len(ver)))
check("dos verifiers no se repiten", ver != oauth_pkce.make_verifier())
url = oauth_pkce.build_authorize_url("https://x.test/auth", "CID", "http://127.0.0.1:1/callback",
                                     ["a", "b"], "ST", "CH", {"prompt": "consent"})
q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
check("URL de autorización con todos los parámetros",
      q["client_id"] == "CID" and q["scope"] == "a b" and q["code_challenge_method"] == "S256"
      and q["code_challenge"] == "CH" and q["state"] == "ST" and q["prompt"] == "consent"
      and q["redirect_uri"] == "http://127.0.0.1:1/callback", str(q))

# ------------------------------------------------------------------ 2
print("== 2) Flujo completo contra un servidor de tokens falso")
seen = {}
class TokenHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        form = dict(urllib.parse.parse_qsl(body))
        seen["form"] = form
        if form.get("grant_type") == "authorization_code":
            ok = (form.get("code") == "CODE123" and
                  oauth_pkce.challenge_for(form.get("code_verifier", "")) == seen.get("challenge"))
            payload = ({"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600}
                       if ok else {"error": "invalid_grant", "error_description": "verifier no coincide"})
            self.send_response(200 if ok else 400)
        else:
            payload = {"access_token": "AT2", "expires_in": 3600, "refresh_token": "RT2"}
            self.send_response(200)
        data = json.dumps(payload).encode()
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
tok_srv = HTTPServer(("127.0.0.1", 0), TokenHandler)
threading.Thread(target=tok_srv.serve_forever, daemon=True).start()
TOKEN_URL = f"http://127.0.0.1:{tok_srv.server_address[1]}/token"

def fake_browser(code="CODE123", state_override=None, error=None):
    def opener(url):
        p = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        seen["challenge"] = p["code_challenge"]
        params = {"state": state_override or p["state"]}
        params.update({"error": error} if error else {"code": code})
        target = p["redirect_uri"] + "?" + urllib.parse.urlencode(params)
        threading.Thread(target=lambda: urllib.request.urlopen(target, timeout=5).read(), daemon=True).start()
        return True
    return opener

tok = oauth_pkce.authorize("http://x.test/auth", TOKEN_URL, "CID", ["s"], open_browser=fake_browser(), timeout_s=10)
check("devuelve access y refresh token", tok["access_token"] == "AT1" and tok["refresh_token"] == "RT1")
check("el servidor recibió el code_verifier que corresponde al challenge", seen["form"]["code_verifier"])
check("el redirect_uri enviado usa 127.0.0.1", seen["form"]["redirect_uri"].startswith("http://127.0.0.1:"))

def fails(**kw):
    try:
        oauth_pkce.authorize("http://x.test/auth", TOKEN_URL, "CID", ["s"], timeout_s=kw.pop("timeout_s", 5), **kw)
    except oauth_pkce.OAuthError as exc:
        return str(exc)
    return None
msg = fails(open_browser=fake_browser(state_override="OTRO"))
check("state distinto se rechaza (CSRF)", msg and "state" in msg, str(msg))
msg = fails(open_browser=fake_browser(error="access_denied"))
check("el usuario rechaza el permiso", msg and "access_denied" in msg, str(msg))
msg = fails(open_browser=lambda url: True, timeout_s=1)
check("sin respuesta del navegador: se agota el tiempo", msg and "tiempo" in msg, str(msg))
msg = fails(open_browser=lambda url: True, timeout_s=10, cancelled=lambda: True)
check("cancelar interrumpe la espera", msg and "cancel" in msg.lower(), str(msg))
msg = fails(open_browser=lambda url: False)
check("sin navegador: error claro", msg and "navegador" in msg, str(msg))
busy = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
msg = fails(open_browser=lambda url: True, port=busy.server_address[1])
check("puerto de retorno ocupado: error claro", msg and "puerto" in msg, str(msg))
busy.server_close()
try:
    oauth_pkce.authorize("http://x.test/auth", TOKEN_URL, "", ["s"])
    msg = None
except oauth_pkce.OAuthError as exc:
    msg = str(exc)
check("sin Client ID: error claro", msg and "Client ID" in msg, str(msg))
rt = oauth_pkce.refresh_access_token(TOKEN_URL, "CID", "RT1", "SECRET")
check("renovar con refresh_token", rt["access_token"] == "AT2" and seen["form"]["client_secret"] == "SECRET")

# ------------------------------------------------------------------ 3
print("== 3) Clientes: endpoints exactos")
calls = []
routes = {}
def fake_request(method, url, token="", timeout=0):
    calls.append((method, url, token))
    for (m, prefix), resp in routes.items():
        if method == m and url.startswith(prefix):
            if isinstance(resp, Exception):
                raise resp
            return (resp(url) if callable(resp) else resp)
    raise likes.ApiError(404, "sin ruta")
likes._request = fake_request
oauth_pkce.refresh_access_token = lambda *a, **k: {"access_token": "AT", "expires_in": 3600}

def client(cls, token_url="x"):
    saved = []
    t = likes._Tokens(token_url, lambda: ("CID", "", "RT"), saved.append)
    return cls(t), saved

# --- Spotify
sp, _ = client(likes.SpotifyLikes)
snap = {"title": "One More Time (Official Video)", "artist": "Daft Punk - Topic", "duration_seconds": 320}
routes.clear(); calls.clear()
routes[("GET", likes.SPOTIFY_API + "/me/player/currently-playing")] = (200, {"item": {
    "type": "track", "uri": "spotify:track:AAA", "id": "AAA", "name": "One More Time"}})
ident = sp.identify(snap)
check("identifica con lo que suena en la cuenta (título limpio)", ident == {"uri": "spotify:track:AAA", "id": "AAA"}, str(ident))
check("usa el token Bearer", all(c[2] == "AT" for c in calls))

routes.clear(); calls.clear()
routes[("GET", likes.SPOTIFY_API + "/me/player/currently-playing")] = (204, None)
routes[("GET", likes.SPOTIFY_API + "/search")] = (200, {"tracks": {"items": [
    {"uri": "spotify:track:BAD", "id": "BAD", "name": "Otra cosa", "artists": [{"name": "Nadie"}], "duration_ms": 100000},
    {"uri": "spotify:track:OK", "id": "OK", "name": "One More Time", "artists": [{"name": "Daft Punk"}], "duration_ms": 320000}]}})
ident = sp.identify(snap)
check("sin nada sonando: busca y elige la que se parece", ident and ident["id"] == "OK", str(ident))
routes[("GET", likes.SPOTIFY_API + "/search")] = (200, {"tracks": {"items": [
    {"uri": "spotify:track:BAD", "id": "BAD", "name": "Otra cosa", "artists": [{"name": "Nadie"}], "duration_ms": 100000}]}})
check("si nada se parece: None (no guarda una canción equivocada)", sp.identify(snap) is None)

ident = {"uri": "spotify:track:OK", "id": "OK"}
routes.clear(); calls.clear()
routes[("GET", likes.SPOTIFY_API + "/me/library/contains")] = (200, [True])
check("is_liked usa /me/library/contains con el URI", sp.is_liked(ident) is True and
      "uris=spotify%3Atrack%3AOK" in calls[-1][1], calls[-1][1])
routes.clear(); calls.clear()
routes[("PUT", likes.SPOTIFY_API + "/me/library")] = (200, None)
sp.set_liked(ident, True)
check("guardar: PUT /me/library?uris=…", calls[-1][0] == "PUT" and calls[-1][1].endswith("/me/library?uris=spotify%3Atrack%3AOK"), str(calls[-1]))
routes[("DELETE", likes.SPOTIFY_API + "/me/library")] = (200, None)
sp.set_liked(ident, False)
check("quitar: DELETE /me/library?uris=…", calls[-1][0] == "DELETE", str(calls[-1]))
routes.clear(); calls.clear()
routes[("GET", likes.SPOTIFY_API + "/me/library/contains")] = likes.ApiError(404, "no existe")
routes[("GET", likes.SPOTIFY_API + "/me/tracks/contains")] = (200, [False])
check("respaldo a /me/tracks/contains ante 404", sp.is_liked(ident) is False and "ids=OK" in calls[-1][1], calls[-1][1])

# 401 -> renueva y reintenta una vez
routes.clear(); calls.clear()
state401 = {"n": 0}
def once_401(url):
    state401["n"] += 1
    if state401["n"] == 1:
        raise likes.ApiError(401, "token caducado")
    return (200, [True])
routes[("GET", likes.SPOTIFY_API + "/me/library/contains")] = once_401
check("401: renueva el token y reintenta una vez", sp.is_liked(ident) is True and state401["n"] == 2)

# --- YouTube
yt, _ = client(likes.YouTubeLikes)
for cover, vid in (("https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg", "dQw4w9WgXcQ"),
                   ("https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg?x=1", "dQw4w9WgXcQ"),
                   ("https://i.ytimg.com/vi_webp/dQw4w9WgXcQ/hq720.webp", "dQw4w9WgXcQ")):
    got = yt.identify({"cover_url": cover})
    check(f"id del video desde la miniatura ({cover[8:30]}…)", got == {"id": vid}, str(got))
check("carátula sin id (YouTube Music): None",
      yt.identify({"cover_url": "https://lh3.googleusercontent.com/abcdef=w544"}) is None)
routes.clear(); calls.clear()
routes[("GET", likes.YOUTUBE_API + "/videos/getRating")] = (200, {"items": [{"videoId": "X", "rating": "like"}]})
check("getRating 'like' -> True", yt.is_liked({"id": "dQw4w9WgXcQ"}) is True and "id=dQw4w9WgXcQ" in calls[-1][1])
routes[("GET", likes.YOUTUBE_API + "/videos/getRating")] = (200, {"items": [{"videoId": "X", "rating": "none"}]})
check("getRating 'none' -> False", yt.is_liked({"id": "dQw4w9WgXcQ"}) is False)
routes[("POST", likes.YOUTUBE_API + "/videos/rate")] = (204, None)
yt.set_liked({"id": "dQw4w9WgXcQ"}, True)
check("dar me gusta: POST rate rating=like", calls[-1][0] == "POST" and "rating=like" in calls[-1][1], calls[-1][1])
yt.set_liked({"id": "dQw4w9WgXcQ"}, False)
check("quitarlo: rating=none", "rating=none" in calls[-1][1])

# --- mensajes
check("403 de Spotify explica Premium / User Management",
      "Premium" in likes._friendly("spotify", likes.ApiError(403, "")) and "User Management" in likes._friendly("spotify", likes.ApiError(403, "")))
check("403 de YouTube menciona la cuota", "cuota" in likes._friendly("youtube", likes.ApiError(403, "")))
check("sin conexión conserva el mensaje", "Sin conexión" in likes._friendly("spotify", likes.ApiError(0, "Sin conexión con el servicio (x).")))

# ------------------------------------------------------------------ 4
print("== 4) LikeManager")
def playing(player="Spotify", title="One More Time", artist="Daft Punk", cover=""):
    return PlayerState(connected=True, player_name=player, state="PLAYING", title=title, artist=artist,
                       duration_seconds=320, cover_url=cover, can_play_pause=True)

cfg = AppConfig()
mgr = likes.LikeManager(cfg)
infos = []
mgr.changed.connect(infos.append)
setups = []
mgr.setupRequested.connect(setups.append)

mgr.track_changed(None)
check("sin reproducción: el botón se oculta", infos[-1].visible is False)
mgr.track_changed(playing(player="SoundCloud"))
check("otro reproductor: oculto", infos[-1].visible is False)
mgr.track_changed(playing())
check("Spotify sin cuenta conectada: visible pero 'sin configurar'",
      infos[-1].service == "spotify" and infos[-1].configured is False and "conecta" in infos[-1].tooltip)
mgr.toggle()
check("clic sin cuenta: pide abrir el diálogo de conexión", setups == ["spotify"])
cfg.likes_enabled = False
mgr.track_changed(playing())
check("con el ajuste desactivado: oculto", infos[-1].visible is False)
cfg.likes_enabled = True

# conectada
cfg.spotify_client_id, cfg.spotify_refresh_token = "CID", "RT"
state = {"liked": False, "contains": 0}
routes.clear(); calls.clear()
routes[("GET", likes.SPOTIFY_API + "/me/player/currently-playing")] = (200, {"item": {
    "type": "track", "uri": "spotify:track:OK", "id": "OK", "name": "One More Time"}})
routes[("GET", likes.SPOTIFY_API + "/me/library/contains")] = lambda url: (state.__setitem__("contains", state["contains"] + 1) or (200, [state["liked"]]))
def put(url): state["liked"] = True; return (200, None)
def delete(url): state["liked"] = False; return (200, None)
routes[("PUT", likes.SPOTIFY_API + "/me/library")] = put
routes[("DELETE", likes.SPOTIFY_API + "/me/library")] = delete

infos.clear()
mgr.track_changed(playing())
check("al cambiar de canción: pasa por 'comprobando'", infos[0].busy and infos[0].configured and infos[0].liked is None)
settle()
check("termina con el estado real (no le gusta)", infos[-1].liked is False and not infos[-1].busy, str(infos[-1]))
n_before = len(calls)
mgr.toggle()
check("clic: respuesta optimista inmediata", infos[-1].liked is True and infos[-1].busy)
settle()
check("tras la API: le gusta", infos[-1].liked is True and not infos[-1].busy and state["liked"] is True)
check("el segundo clic NO vuelve a identificar la canción (usa la guardada)",
      not any("currently-playing" in c[1] or "/search" in c[1] for c in calls[n_before:]))
mgr.toggle(); settle()
check("otro clic: lo quita", infos[-1].liked is False and state["liked"] is False)

# error al guardar: se revierte y explica
routes[("PUT", likes.SPOTIFY_API + "/me/library")] = likes.ApiError(403, "")
mgr.toggle()
check("optimista aunque vaya a fallar", infos[-1].liked is True)
settle()
check("fallo: se revierte el corazón", infos[-1].liked is False and not infos[-1].busy)
check("fallo: mensaje legible en el tooltip", "Premium" in infos[-1].message and infos[-1].tooltip == infos[-1].message, infos[-1].message)

# la canción cambia mientras la API responde
routes[("PUT", likes.SPOTIFY_API + "/me/library")] = lambda url: (time.sleep(0.3) or put(url))
mgr.toggle()
mgr.track_changed(playing(title="Otra Canción"))
n = len(infos)
QThreadPool.globalInstance().waitForDone(); run(60)
check("respuesta de la canción anterior se ignora", all(i.liked is not True for i in infos[n:]) , str([i.liked for i in infos[n:]]))
settle()

# YouTube
cfg.google_client_id, cfg.google_refresh_token = "G", "GR"
routes.clear(); calls.clear()
routes[("GET", likes.YOUTUBE_API + "/videos/getRating")] = (200, {"items": [{"rating": "like"}]})
mgr.forget_credentials()
mgr.track_changed(playing(player="YouTube", cover="https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"))
settle()
check("YouTube: lee el 'me gusta' del video", infos[-1].service == "youtube" and infos[-1].liked is True, str(infos[-1]))
check("YouTube: tooltip propio", "video" in infos[-1].tooltip)
mgr.track_changed(playing(player="YouTube Music", cover="https://lh3.googleusercontent.com/zzz=w500"))
settle()
check("YouTube Music: explica por qué no se puede (sin falso 'error HTTP')",
      infos[-1].liked is None and "YouTube Music" in infos[-1].message
      and "respondió con un error" not in infos[-1].message, infos[-1].message)

# rotación de refresh_token
oauth_pkce.refresh_access_token = lambda *a, **k: {"access_token": "AT9", "expires_in": 3600, "refresh_token": "NUEVO"}
cfg.spotify_refresh_token = "VIEJO"
mgr.forget_credentials()
routes[("GET", likes.SPOTIFY_API + "/me/player/currently-playing")] = (204, None)
routes[("GET", likes.SPOTIFY_API + "/search")] = (200, {"tracks": {"items": []}})
mgr.track_changed(playing()); settle()
check("si el servicio rota el refresh_token, se guarda el nuevo", cfg.spotify_refresh_token == "NUEVO", cfg.spotify_refresh_token)

# ------------------------------------------------------------------ 5
print("== 5) LikesDialog")
from likes_dialog import LikesDialog
cfg2 = AppConfig()
changed = []
dlg = LikesDialog(cfg2, on_changed=lambda: changed.append(1))
dlg.show(); app.processEvents()
check("al inicio: 'Sin conectar'", dlg.spotify_btn.text() == "Conectar" and "Sin conectar" in dlg.spotify_status.text())
dlg.spotify_btn.click()
check("sin Client ID: avisa y no lanza nada", "Client ID" in dlg.spotify_status.text() and not dlg._busy["spotify"])
dlg.spotify_id_input.setText("MI_CLIENT_ID")
dlg._authorize = lambda service, cid, secret: {"access_token": "a", "refresh_token": "R-SPOT"}
dlg.spotify_btn.click()
check("mientras conecta el botón pasa a 'Cancelar'", dlg._busy["spotify"] and dlg.spotify_btn.text() == "Cancelar")
t0 = time.time()
while dlg._busy["spotify"] and time.time() - t0 < 5:
    app.processEvents(); time.sleep(0.01)
check("conectado: guarda client id y refresh token", cfg2.spotify_client_id == "MI_CLIENT_ID" and cfg2.spotify_refresh_token == "R-SPOT")
check("conectado: el botón pasa a 'Desconectar' y se avisó del cambio", dlg.spotify_btn.text() == "Desconectar" and changed)
dlg.spotify_btn.click()
check("desconectar borra el token (conserva el Client ID)", cfg2.spotify_refresh_token == "" and cfg2.spotify_client_id == "MI_CLIENT_ID")
def boom(service, cid, secret): raise oauth_pkce.OAuthError("El usuario canceló")
dlg._authorize = boom
dlg.spotify_btn.click()
t0 = time.time()
while dlg._busy["spotify"] and time.time() - t0 < 5:
    app.processEvents(); time.sleep(0.01)
check("fallo de conexión: muestra el motivo", "canceló" in dlg.spotify_status.text(), dlg.spotify_status.text())
dlg.google_id_input.setText("GID"); dlg.google_secret_input.setText("GSEC")
dlg._authorize = lambda service, cid, secret: {"refresh_token": "R-GOOG", "_secret": secret}
dlg.youtube_btn.click()
t0 = time.time()
while dlg._busy["youtube"] and time.time() - t0 < 5:
    app.processEvents(); time.sleep(0.01)
check("YouTube: guarda id, secreto y refresh token",
      (cfg2.google_client_id, cfg2.google_client_secret, cfg2.google_refresh_token) == ("GID", "GSEC", "R-GOOG"))
dlg.enabled_check.setChecked(False)
check("desmarcar 'mostrar el botón' se guarda", cfg2.likes_enabled is False)
dlg.close()

print(f"\n{len(PASS)} OK, {len(FAIL)} fallos")
sys.exit(1 if FAIL else 0)
