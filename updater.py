"""Buscar versiones nuevas de YefriPlayer (GitHub Releases) y actualizar.

- Consulta `releases/latest` del repositorio (version.PROJECT_URL) como mucho
  una vez al día (config.check_updates / last_update_check), en segundo plano.
- Si hay una versión mayor que la actual y el usuario no pidió saltarla, se
  avisa (bandeja + diálogo) con tres opciones: actualizar, ahora no, omitir
  esta versión.
- «Actualizar»: si el programa se instaló con el instalador, se descarga el
  `YefriPlayer-<versión>-Setup.exe` publicado en la versión, se comprueba
  (SHA-256 si GitHub lo publica, si no el tamaño) y se ejecuta; el instalador
  cierra esta copia de forma ordenada y actualiza encima. Si no está instalado
  (código fuente o .zip), se abre la página de la versión en el navegador.
- Solo biblioteca estándar (`urllib`), sin enviar nada del usuario: es una
  petición GET anónima con el User-Agent de siempre.

La parte de red y de decisión son funciones puras/simples, probadas sin Qt.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass

import version

CHECK_INTERVAL_H = 24
_TIMEOUT_S = 10
_ASSET_RE = re.compile(r"^YefriPlayer-[\w.\-]+-Setup\.exe$", re.IGNORECASE)


def api_url(project_url: str = version.PROJECT_URL) -> str:
    """https://github.com/dueño/repo → URL de la API de la última versión."""
    m = re.match(r"^https?://github\.com/([^/]+)/([^/#?]+)", (project_url or "").strip())
    if not m:
        return ""
    repo = m.group(2).removesuffix(".git")
    return f"https://api.github.com/repos/{m.group(1)}/{repo}/releases/latest"


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v1.4.0' / '1.4' / '1.4.0-beta' → (1, 4, 0); None si no es una versión.
    Lo que va tras un guion (beta, rc...) cuenta como «anterior» a la final."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+){0,3})(-[0-9A-Za-z.\-]+)?\s*$", text or "")
    if not m:
        return None
    nums = [int(x) for x in m.group(1).split(".")]
    nums += [0] * (4 - len(nums))          # 1.4 == 1.4.0 == 1.4.0.0
    return tuple(nums) + ((-1,) if m.group(2) else (0,))


def is_newer(remote: str, current: str = version.APP_VERSION) -> bool:
    r, c = parse_version(remote), parse_version(current)
    return bool(r and c and r > c)


def should_check(last_iso: str, now: datetime.datetime | None = None) -> bool:
    now = now or datetime.datetime.now()
    try:
        last = datetime.datetime.fromisoformat(last_iso)
    except (TypeError, ValueError):
        return True
    return (now - last).total_seconds() >= CHECK_INTERVAL_H * 3600 or last > now


@dataclass
class UpdateInfo:
    version: str              # sin la «v»
    page_url: str             # página de la versión en GitHub
    notes: str = ""           # notas (recortadas)
    asset_url: str = ""       # Setup.exe publicado ('' si no hay)
    asset_name: str = ""
    asset_size: int = 0
    asset_sha256: str = ""    # '' si GitHub no publica el resumen


def parse_release(data: dict) -> UpdateInfo | None:
    """Datos de la API → UpdateInfo, o None si no es una versión utilizable."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        return None
    info = UpdateInfo(version=tag.lstrip("vV").strip(), page_url=str(data.get("html_url") or ""),
                      notes=str(data.get("body") or "").strip()[:800])
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if _ASSET_RE.match(name) and asset.get("browser_download_url"):
            info.asset_name = name
            info.asset_url = str(asset["browser_download_url"])
            info.asset_size = int(asset.get("size") or 0)
            digest = str(asset.get("digest") or "")
            if digest.lower().startswith("sha256:"):
                info.asset_sha256 = digest.split(":", 1)[1].strip().lower()
            break
    return info


def fetch_latest(url: str | None = None, opener=urllib.request.urlopen) -> UpdateInfo | None:
    """Consulta la API (lanza OSError/ValueError si no hay red o la respuesta es rara)."""
    url = url or api_url()
    if not url:
        return None
    req = urllib.request.Request(url, headers={
        "User-Agent": version.user_agent(), "Accept": "application/vnd.github+json"})
    with opener(req, timeout=_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return parse_release(data)


def is_installed() -> bool:
    """True si esta copia vino del instalador (junto al .exe está el desinstalador
    de Inno Setup). Solo entonces tiene sentido descargar y ejecutar el Setup."""
    if not version.is_frozen():
        return False
    folder = os.path.dirname(version.executable_path())
    return any(os.path.isfile(os.path.join(folder, f"unins00{i}.exe")) for i in range(10))


def download(info: UpdateInfo, dest_dir: str | None = None, opener=urllib.request.urlopen,
             chunk: int = 1 << 16) -> str:
    """Descarga el Setup.exe a una carpeta temporal y lo verifica. Devuelve la
    ruta. Lanza OSError/ValueError si falla (y no deja el archivo a medias)."""
    if not info.asset_url or not _ASSET_RE.match(info.asset_name):
        raise ValueError("Esta versión no publica un instalador.")
    dest_dir = dest_dir or os.path.join(tempfile.gettempdir(), "YefriPlayer-actualizacion")
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, info.asset_name)
    part = final + ".part"
    h = hashlib.sha256()
    size = 0
    req = urllib.request.Request(info.asset_url, headers={"User-Agent": version.user_agent()})
    try:
        with opener(req, timeout=60) as resp, open(part, "wb") as f:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                f.write(block)
                h.update(block)
                size += len(block)
        if info.asset_sha256 and h.hexdigest() != info.asset_sha256:
            raise ValueError("La descarga no coincide con la huella SHA-256 publicada.")
        if not info.asset_sha256 and info.asset_size and size != info.asset_size:
            raise ValueError(f"Descarga incompleta ({size} de {info.asset_size} bytes).")
        if size < 1024:
            raise ValueError("La descarga está vacía.")
        os.replace(part, final)
        return final
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(part)
        raise


def run_installer(path: str) -> None:
    """Abre el instalador (con su asistente; pide administrador solo si se
    instaló para todos). /SP- omite la pregunta inicial «¿Desea instalar?»."""
    import subprocess
    import sys
    if sys.platform != "win32":
        raise OSError("El instalador solo funciona en Windows.")
    # ShellExecute (no CreateProcess) para que Windows muestre UAC si hace falta.
    import ctypes
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", path, "/SP-", None, 1)
    if rc <= 32:
        subprocess.Popen([path, "/SP-"])   # último recurso


# --------------------------------------------------------------- parte Qt
try:
    from PyQt6.QtCore import QObject, pyqtSignal
except ImportError:          # pruebas sin Qt: solo se usan las funciones de arriba
    QObject = object         # type: ignore[assignment,misc]
    pyqtSignal = None        # type: ignore[assignment]

if pyqtSignal is not None:
    class UpdateChecker(QObject):
        """Hace la consulta y la descarga en hilos de fondo (workers.py) y
        devuelve los resultados por señal al hilo de la interfaz."""

        checked = pyqtSignal(object, str, bool)    # UpdateInfo|None, error, manual
        downloaded = pyqtSignal(str, str)          # ruta, error

        def check(self, manual: bool = False) -> None:
            checker = self

            class _Job:
                def run(self):
                    try:
                        info = fetch_latest()
                        checker.checked.emit(info, "", manual)
                    except Exception as exc:
                        checker.checked.emit(None, f"No se pudo consultar GitHub: {exc}", manual)

            import workers
            workers.default_pool().start(_Job())

        def download(self, info: UpdateInfo) -> None:
            checker = self

            class _Job:
                def run(self):
                    try:
                        checker.downloaded.emit(download(info), "")
                    except Exception as exc:
                        checker.downloaded.emit("", str(exc))

            import workers
            workers.default_pool().start(_Job())
