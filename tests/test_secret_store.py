"""Protección de secretos en config.json (secret_store) y avisos silenciosos (diag).
DPAPI solo existe en Windows: aquí se prueba la lógica con un cifrador simulado."""
import json, os, stat, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["LOCALAPPDATA"] = tmp
import config, diag, secret_store

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name)
    fails += 0 if cond else 1


class Falso:
    """Cifrador de mentira reversible (XOR) para probar el formato y los casos de error."""
    def encrypt(self, data): return bytes(b ^ 0x5A for b in data)
    def decrypt(self, data): return bytes(b ^ 0x5A for b in data)

class Roto:
    def encrypt(self, data): raise OSError("falla")
    def decrypt(self, data): raise OSError("otro usuario")

logged = []
diag._sink = logged.append

# --- protect / reveal -------------------------------------------------------
secret_store.set_backend(Falso())
tok = "AQD-token_de_prueba/123"
enc = secret_store.protect(tok)
check("se cifra con prefijo y sin dejar el texto a la vista", enc.startswith("dpapi:") and tok not in enc)
check("ida y vuelta", secret_store.reveal(enc) == tok)
check("no se cifra dos veces", secret_store.protect(enc) == enc)
check("vacío se queda vacío", secret_store.protect("") == "" and secret_store.reveal("") == "")
check("valor antiguo en texto plano se acepta", secret_store.reveal("texto-plano") == "texto-plano")
check("tipo raro no revienta", secret_store.protect(None) is None and secret_store.reveal(5) == 5)

# --- la capa ctypes de DPAPI, con una DLL simulada (en Windows real llama a crypt32) ---
import ctypes
class FakeDll:
    """Imita crypt32/kernel32: «cifra» con XOR y devuelve el resultado en memoria propia."""
    def __init__(self, name, use_last_error=False):
        self.freed = []
        self.keep = []
        def _xor(pin, pout, key):
            blob_in, blob_out = pin._obj, pout._obj
            data = ctypes.string_at(blob_in.pbData, blob_in.cbData)
            out = ctypes.create_string_buffer(bytes(b ^ key for b in data), len(data))
            self.keep.append(out)
            blob_out.cbData = len(data)
            blob_out.pbData = ctypes.addressof(out)
            return 1
        def protect(pin, descr, ent, res, prompt, flags, pout):
            assert descr == "YefriPlayer" and flags == 1 and ent is None
            return _xor(pin, pout, 0x33)
        def unprotect(pin, descr, ent, res, prompt, flags, pout):
            assert flags == 1
            return _xor(pin, pout, 0x33)
        self.CryptProtectData, self.CryptUnprotectData = protect, unprotect
        self.LocalFree = lambda ptr: self.freed.append(ptr)
ctypes.WinDLL = FakeDll
real = secret_store._Dpapi()
blob = real.encrypt("token-ñ-€".encode("utf-8"))
check("capa ctypes: cifra y descifra bytes (incluye no ASCII)", real.decrypt(blob).decode("utf-8") == "token-ñ-€" and blob != "token-ñ-€".encode("utf-8"))
check("capa ctypes: libera la memoria que devolvió Windows", len(real._kernel32.freed) == 2)
secret_store.set_backend(real)
check("capa ctypes integrada con protect/reveal", secret_store.reveal(secret_store.protect("abc123")) == "abc123")

# --- fallos -----------------------------------------------------------------
diag.reset(); logged.clear()
secret_store.set_backend(Roto())
check("si cifrar falla, se conserva el valor (no se pierde el token)", secret_store.protect(tok) == tok)
check("si descifrar falla (otro usuario/equipo), queda vacío", secret_store.reveal(enc) == "")
check("los fallos quedan anotados", len(logged) == 2 and "secret_store" in logged[0])
secret_store.set_backend(None)
check("sin cifrador no se rompe nada", secret_store.protect(tok) == tok and secret_store.reveal(enc) == "")
check("base64 corrupto -> vacío", (secret_store.set_backend(Falso()) or True) and secret_store.reveal("dpapi:%%%") == "")

# --- integración con AppConfig ---------------------------------------------
secret_store.set_backend(Falso())
c = config.AppConfig()
c.spotify_client_id = "id-publico"
c.spotify_refresh_token = "REFRESH-SPOTIFY"
c.google_client_secret = "SECRETO-GOOGLE"
c.listenbrainz_token = "LB-TOKEN"
c.port = 4321
c.save()
text = config._config_path().read_text(encoding="utf-8")
data = json.loads(text)
check("en disco no aparece ningún secreto en claro",
      all(v not in text for v in ("REFRESH-SPOTIFY", "SECRETO-GOOGLE", "LB-TOKEN")))
check("los secretos van con prefijo", all(data[k].startswith("dpapi:") for k in
      ("spotify_refresh_token", "google_client_secret", "listenbrainz_token")))
check("lo que no es secreto sigue legible", data["spotify_client_id"] == "id-publico" and data["port"] == 4321)
check("campos secretos vacíos siguen vacíos", data["lastfm_session_key"] == "")
back = config.AppConfig.load()
check("al cargar se descifra todo", back.spotify_refresh_token == "REFRESH-SPOTIFY"
      and back.google_client_secret == "SECRETO-GOOGLE" and back.listenbrainz_token == "LB-TOKEN" and back.port == 4321)
check("el objeto en memoria no se toca al guardar", c.spotify_refresh_token == "REFRESH-SPOTIFY")

# config.json de una versión anterior (texto plano): se lee y, al guardar, se protege
raw = dict(data, spotify_refresh_token="VIEJO-EN-CLARO", youtube_api_key="AIza-clave")
config._config_path().write_text(json.dumps(raw), encoding="utf-8")
old = config.AppConfig.load()
check("un config.json antiguo en texto plano se sigue leyendo", old.spotify_refresh_token == "VIEJO-EN-CLARO" and old.youtube_api_key == "AIza-clave")
old.save()
text2 = config._config_path().read_text(encoding="utf-8")
check("y se protege en el siguiente guardado", "VIEJO-EN-CLARO" not in text2 and "AIza-clave" not in text2)

# config.json copiado de otro equipo: los secretos no se pueden leer, el resto sí
secret_store.set_backend(Roto())
other = config.AppConfig.load()
check("de otro equipo: secretos vacíos (hay que reconectar) y el resto se conserva",
      other.spotify_refresh_token == "" and other.port == 4321)

if sys.platform != "win32":
    mode = stat.S_IMODE(os.stat(config._config_path()).st_mode)
    check("fuera de Windows el archivo queda solo para tu usuario (600)", mode == 0o600)

# --- diag --------------------------------------------------------------------
diag.reset(); logged.clear()
with diag.soft("prueba.a"):
    raise ValueError("boom")
with diag.soft("prueba.a"):
    raise ValueError("boom otra vez")
with diag.soft("prueba.b"):
    pass
check("soft atrapa Exception, anota una vez por contexto", len(logged) == 1 and "prueba.a" in logged[0] and "ValueError: boom" in logged[0])
try:
    with diag.soft("prueba.c"):
        raise KeyboardInterrupt
    interrumpido = False
except KeyboardInterrupt:
    interrumpido = True
check("soft NO atrapa KeyboardInterrupt", interrumpido)
def sink_roto(text): raise RuntimeError("disco lleno")
diag._sink = sink_roto
check("note nunca lanza aunque el registro falle", diag.note("prueba.d", ValueError("x")) is False)
diag._sink = logged.append
diag.reset(); logged.clear()
for i in range(diag.MAX_CONTEXTS + 20):
    diag.note(f"ctx{i}")
check("tope de contextos distintos (no llena el disco)", len(logged) == diag.MAX_CONTEXTS)
diag._sink = diag._default_sink
diag.reset()
diag.note("prueba.real", OSError("de verdad"))
import error_handling
check("por defecto escribe en error.log", "prueba.real" in error_handling.log_path().read_text(encoding="utf-8"))

print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
