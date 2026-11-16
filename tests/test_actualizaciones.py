"""Buscar actualizaciones (updater.py): versiones, cada cuánto, lectura de la API de
GitHub y descarga verificada. Sin red: la API y la descarga se simulan."""
import datetime, hashlib, io, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import updater as U, version

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

check("URL de la API desde PROJECT_URL",
      U.api_url("https://github.com/Yeflix/yefriplayer") == "https://api.github.com/repos/Yeflix/yefriplayer/releases/latest")
check("URL con .git y barra final", U.api_url("https://github.com/a/b.git/") == "https://api.github.com/repos/a/b/releases/latest")
check("sin repositorio de GitHub → sin URL", U.api_url("") == "" and U.api_url("https://example.com/x") == "")
check("v1.4 == 1.4.0", U.parse_version("v1.4") == U.parse_version("1.4.0"))
check("versión mayor", U.is_newer("1.10.0", "1.9.9") and U.is_newer("v2.0", "1.99"))
check("igual o menor no es nueva", not U.is_newer("1.4.0", "1.4.0") and not U.is_newer("1.3.9", "1.4.0"))
check("beta < final", U.is_newer("1.5.0", "1.5.0-beta") and not U.is_newer("1.5.0-beta", "1.5.0"))
check("basura no es versión", U.parse_version("latest") is None and not U.is_newer("latest"))

now = datetime.datetime(2026, 11, 16, 12, 0)
check("nunca consultado → consultar", U.should_check("", now))
check("hace 3 h → no", not U.should_check("2026-11-16T09:00:00", now))
check("hace 25 h → sí", U.should_check("2026-11-15T11:00:00", now))
check("fecha en el futuro (reloj cambiado) → sí", U.should_check("2027-01-01T00:00:00", now))

payload = b"MZ" + b"\x00" * 5000
digest = hashlib.sha256(payload).hexdigest()
release = {"tag_name": "v9.9.9", "html_url": "https://github.com/Yeflix/yefriplayer/releases/tag/v9.9.9",
           "body": "Novedades", "draft": False, "prerelease": False,
           "assets": [{"name": "notas.txt", "browser_download_url": "https://x/notas.txt"},
                      {"name": "YefriPlayer-9.9.9-Setup.exe", "size": len(payload),
                       "digest": "sha256:" + digest,
                       "browser_download_url": "https://github.com/x/YefriPlayer-9.9.9-Setup.exe"}]}
info = U.parse_release(release)
check("lee versión, página y el Setup.exe (con SHA-256)",
      info.version == "9.9.9" and info.asset_name.endswith("-Setup.exe") and info.asset_sha256 == digest)
check("borradores y prereleases se ignoran",
      U.parse_release(dict(release, draft=True)) is None and U.parse_release(dict(release, prerelease=True)) is None)
check("sin instalador publicado → sin asset", U.parse_release(dict(release, assets=[])).asset_url == "")

class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
seen = {}
def opener(req, timeout=0):
    seen["ua"] = req.get_header("User-agent"); seen["url"] = req.full_url
    return Resp(json.dumps(release).encode()) if "api.github.com" in req.full_url else Resp(payload)
got = U.fetch_latest(opener=opener)
check("consulta la API con el User-Agent del programa",
      got.version == "9.9.9" and seen["ua"] == version.user_agent() and seen["url"] == U.api_url())

tmp = tempfile.mkdtemp()
path = U.download(info, tmp, opener=opener)
check("descarga verificada por SHA-256", os.path.basename(path) == info.asset_name and open(path, "rb").read() == payload)
bad = U.UpdateInfo(**{**info.__dict__, "asset_sha256": "0" * 64})
try:
    U.download(bad, tmp, opener=opener); check("huella distinta → error", False)
except ValueError:
    check("huella distinta → error y sin archivo a medias",
          not any(f.endswith(".part") for f in os.listdir(tmp)))
short = U.UpdateInfo(**{**info.__dict__, "asset_sha256": "", "asset_size": len(payload) + 10})
try:
    U.download(short, tempfile.mkdtemp(), opener=opener); check("tamaño distinto → error", False)
except ValueError:
    check("sin huella: se comprueba el tamaño", True)
try:
    U.download(U.UpdateInfo("1.0", "x", asset_url="https://evil/x.exe", asset_name="otro.exe"), tmp, opener=opener)
    check("nombre de archivo inesperado → no se descarga", False)
except ValueError:
    check("nombre de archivo inesperado → no se descarga", True)
check("desde código fuente no cuenta como instalado", U.is_installed() is False)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
