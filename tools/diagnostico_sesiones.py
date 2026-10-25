#!/usr/bin/env python3
"""Diagnóstico: ¿por qué el reproductor no detecta Spotify de escritorio?

QUÉ HACE
  Mira, por separado, las tres capas por las que tiene que pasar Spotify para
  llegar al reproductor, y dice en cuál se corta:

    1. Spotify         ¿está abierto?  ¿qué versión?
    2. Windows         ¿publica una sesión multimedia (SMTC)? Se lee DIRECTO de
                       Windows con winsdk, sin pywnp ni este proyecto.
    3. pywnp + parche  ¿esa sesión llega a pywnp y a pywnp_patch.py?
                       (usa un puerto libre aparte: no choca con el reproductor)

  También muestra si pywnp tiene desactivadas las APIs nativas (carpeta
  `use_native_apis`) y qué hizo por última vez Spicetify AutoFix (por si reinició
  Spotify hace poco).

CÓMO USARLO
  1. Abre Spotify y pon a sonar una canción (la sesión de Windows de Spotify
     aparece cuando reproduce algo; con Spotify recién abierto y sin tocar
     "play" puede no existir todavía).
  2. En la misma consola/entorno donde ejecutas el reproductor:
         python tools/diagnostico_sesiones.py
  3. Dura unos 8 segundos. Deja un archivo  diagnostico_sesiones_<fecha>.txt  y
     termina con un VEREDICTO. Pásame el veredicto (o el archivo entero).

NO modifica nada: solo lee.
"""
from __future__ import annotations

import asyncio
import datetime
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_STATUS = {0: "CLOSED", 1: "OPENED", 2: "CHANGING", 3: "STOPPED", 4: "PLAYING", 5: "PAUSED"}
_LINES: list[str] = []


def out(text: str = "") -> None:
    print(text)
    _LINES.append(text)


def is_spotify_id(app_id: str) -> bool:
    return "spotify" in (app_id or "").lower()


# ----------------------------------------------------------------- capa 1
def spotify_processes() -> int:
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Spotify.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=15)
        return sum(1 for ln in r.stdout.splitlines() if ln.lower().startswith('"spotify.exe"'))
    except Exception:  # noqa: BLE001
        return -1   # no se pudo comprobar


def spotify_version() -> str:
    exe = os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")
    if not os.path.isfile(exe):
        return "(no encuentro %APPDATA%\\Spotify\\Spotify.exe: ¿versión de Microsoft Store?)"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or "(sin dato)"
    except Exception:  # noqa: BLE001
        return "(no se pudo leer)"


# ----------------------------------------------------------------- capa 2
def windows_sessions() -> tuple[bool, list[dict], str]:
    """(winsdk disponible, sesiones que ve Windows, error)."""
    try:
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as SM
    except Exception as exc:  # noqa: BLE001
        return False, [], f"{type(exc).__name__}: {exc}"

    async def _list():
        mgr = await SM.request_async()
        current = mgr.get_current_session()
        current_id = current.source_app_user_model_id if current is not None else None
        res = []
        for s in mgr.get_sessions():
            row = {"app": s.source_app_user_model_id, "actual": s.source_app_user_model_id == current_id,
                   "estado": "?", "titulo": "", "artista": ""}
            try:
                info = s.get_playback_info()
                row["estado"] = _STATUS.get(info.playback_status.value, str(info.playback_status))
            except Exception as exc:  # noqa: BLE001
                row["estado"] = f"error: {exc}"
            try:
                props = await s.try_get_media_properties_async()
                row["titulo"], row["artista"] = props.title, props.artist
            except Exception as exc:  # noqa: BLE001
                row["titulo"] = f"(error: {exc})"
            res.append(row)
        return res

    try:
        return True, asyncio.run(_list()), ""
    except Exception as exc:  # noqa: BLE001
        return True, [], f"{type(exc).__name__}: {exc}"


# ----------------------------------------------------------------- capa 3
def pywnp_view(wait_seconds: float = 6.0) -> dict:
    info = {"ok": False, "error": "", "native_enabled": None, "wnp_path": "", "native_dir_exists": None,
            "entries": [], "current": None, "logs": [], "version": ""}
    try:
        from importlib.metadata import version
        info["version"] = version("pywnp")
    except Exception:  # noqa: BLE001
        pass
    try:
        import pywnp_patch
        pywnp_patch.apply()
        from pywnp import WNPRedux
        from pywnp.pywnp import get_wnp_path
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    try:
        info["wnp_path"] = get_wnp_path()
        info["native_dir_exists"] = os.path.isdir(os.path.join(info["wnp_path"], "use_native_apis"))
    except Exception:  # noqa: BLE001
        pass

    with socket.socket() as s:      # puerto libre aparte
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    try:
        WNPRedux.start(port, "diagnostico", lambda lvl, msg: info["logs"].append(f"[{lvl}] {msg}"))
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            time.sleep(0.4)
            if any(getattr(m, "is_native", False) and (m.title or m.state != "STOPPED")
                   for m in WNPRedux.media_info_dictionary):
                time.sleep(0.8)
                break
        info["native_enabled"] = bool(WNPRedux.is_using_native_apis)
        for m in list(WNPRedux.media_info_dictionary):
            info["entries"].append({"id": getattr(m, "_id", ""), "nativo": bool(getattr(m, "is_native", False)),
                                    "estado": m.state, "titulo": m.title, "artista": m.artist,
                                    "player_name": m.player_name})
        cur = WNPRedux.media_info
        info["current"] = {"id": getattr(cur, "_id", ""), "player_name": cur.player_name,
                           "estado": cur.state, "titulo": cur.title}
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


# ----------------------------------------------------------------- AutoFix
def autofix_info() -> list[str]:
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "SpicetifyAutoFix")
    res = []
    beat = os.path.join(base, "ultima-comprobacion.txt")
    log = os.path.join(base, "autofix.log")
    try:
        if os.path.isfile(beat):
            res.append("Última comprobación: " + open(beat, encoding="utf-8-sig").read().strip())
        else:
            res.append("Spicetify AutoFix no está instalado (o aún no corrió).")
        if os.path.isfile(log):
            tail = open(log, encoding="utf-8-sig").read().strip().splitlines()[-4:]
            res.append("Últimas líneas del registro:")
            res.extend("  " + ln for ln in tail)
    except Exception as exc:  # noqa: BLE001
        res.append(f"(no se pudo leer: {exc})")
    return res


# --------------------------------------------------------------- veredicto
def veredicto(spotify_procs: int, winsdk_ok: bool, win_rows: list[dict], pywnp: dict) -> list[str]:
    """Lógica pura (se prueba sin Windows). Devuelve las conclusiones, de la más
    importante a la menos."""
    if not winsdk_ok:
        return ["winsdk NO está instalado en este entorno de Python: sin él pywnp no puede leer apps de "
                "escritorio como Spotify. Instálalo con:  pip install winsdk"]
    if pywnp.get("native_dir_exists"):
        return [f"pywnp tiene DESACTIVADAS las APIs nativas: existe la carpeta "
                f"'{os.path.join(pywnp.get('wnp_path', ''), 'use_native_apis')}'. Bórrala o renómbrala y "
                f"reinicia el reproductor."]
    if spotify_procs == 0:
        return ["Spotify no está abierto (no hay proceso Spotify.exe). Ábrelo y reproduce una canción."]

    win_spotify = [r for r in win_rows if is_spotify_id(r["app"])]
    wnp_spotify = [e for e in pywnp.get("entries", []) if is_spotify_id(e["id"]) or
                   is_spotify_id(e.get("player_name", ""))]

    if not win_spotify:
        msg = ["Windows NO publica ninguna sesión multimedia de Spotify: el reproductor no tiene nada que leer."]
        if win_rows:
            msg.append("  (Windows sí ve otras apps: " + ", ".join(r["app"] for r in win_rows) + ")")
        msg += ["  1) Comprueba que Spotify esté REPRODUCIENDO (no solo abierto): su sesión aparece al sonar.",
                "  2) En Spotify → Configuración → 'Show desktop overlay when using media keys' ('Mostrar el",
                "     overlay de escritorio al usar teclas multimedia'): DESACTÍVALA y vuelve a ACTIVARLA. Esa",
                "     opción es la que registra a Spotify en los controles multimedia de Windows, y tras",
                "     actualizar o reiniciar Spotify a veces aparece activada sin estar aplicada.",
                "  3) Cierra Spotify por completo (bandeja del sistema → Salir), ábrelo, reproduce y vuelve a",
                "     ejecutar este diagnóstico.",
                "  Prueba extra: si al pulsar una tecla multimedia Windows tampoco muestra a Spotify en su",
                "  panel de controles, ninguna app externa podrá leerlo: el problema está en Spotify/Windows."]
        return msg
    if not pywnp.get("ok"):
        return [f"Windows sí ve Spotify, pero pywnp falló al arrancar aquí: {pywnp.get('error', '?')}"]
    if not wnp_spotify:
        return ["Windows SÍ ve a Spotify pero pywnp (con pywnp_patch.py) NO lo está listando. Esto sí es un "
                "problema del lado del reproductor: pásame esta salida completa."]
    cur = pywnp.get("current") or {}
    if not is_spotify_id(cur.get("id", "")) and not is_spotify_id(cur.get("player_name", "")):
        return ["Windows y pywnp ven a Spotify, pero pywnp eligió OTRA fuente como activa: "
                f"{cur.get('id') or cur.get('player_name') or '?'} ({cur.get('estado')}). pywnp prefiere la fuente "
                f"que está sonando (o la más reciente): pausa o cierra esa otra (navegador, Telegram, etc.) "
                f"y verás a Spotify."]
    return ["Windows, pywnp y el parche ven a Spotify correctamente: la detección funciona en esta consola. "
            "Si el reproductor sigue mostrando 'esperando', reinícialo y pásame esta salida + el texto exacto "
            "que muestra."]


def main() -> int:
    out("=== Diagnóstico de sesiones (Spotify → Windows → pywnp → reproductor) ===")
    out(datetime.datetime.now().strftime("Fecha: %Y-%m-%d %H:%M:%S") + f"   Python {sys.version.split()[0]}   "
        f"{sys.platform}")
    if sys.platform != "win32":
        out("Este diagnóstico es para Windows (usa las sesiones multimedia de Windows).")
        return 1

    out("\n[1] Spotify")
    procs = spotify_processes()
    out("  Procesos Spotify.exe: " + ("no se pudo comprobar" if procs < 0 else str(procs)))
    out("  Versión: " + spotify_version())

    out("\n[2] Lo que Windows publica (leído directo, sin pywnp)")
    winsdk_ok, rows, werr = windows_sessions()
    if not winsdk_ok:
        out(f"  winsdk no se puede importar: {werr}")
    elif werr:
        out(f"  Error al leer las sesiones: {werr}")
    elif not rows:
        out("  (ninguna sesión multimedia)")
    for r in rows:
        mark = "  ← sesión actual de Windows" if r["actual"] else ""
        out(f"  • {r['app']}  [{r['estado']}]  {r['titulo']} — {r['artista']}{mark}")

    out("\n[3] Lo que ve pywnp + pywnp_patch.py (puerto aparte, ~6 s)")
    wnp = pywnp_view()
    out(f"  pywnp {wnp['version'] or '?'}   carpeta de datos: {wnp['wnp_path'] or '?'}")
    out(f"  APIs nativas activadas: {wnp['native_enabled']}   carpeta 'use_native_apis' existe: {wnp['native_dir_exists']}")
    if wnp["error"]:
        out(f"  Error: {wnp['error']}")
    for e in wnp["entries"]:
        out(f"  • {e['id']}  nativo={e['nativo']}  [{e['estado']}]  {e['titulo']} — {e['artista']}  (player_name={e['player_name']!r})")
    if wnp["ok"] and not wnp["entries"]:
        out("  (pywnp no listó ninguna fuente)")
    if wnp["current"]:
        c = wnp["current"]
        out(f"  Fuente activa elegida: {c['id'] or '(ninguna)'}  [{c['estado']}]  {c['titulo']}")
    for ln in wnp["logs"][:10]:
        out("  log pywnp: " + ln)

    out("\n[4] Spicetify AutoFix")
    for ln in autofix_info():
        out("  " + ln)

    out("\n================ VEREDICTO ================")
    for ln in veredicto(procs, winsdk_ok, rows, wnp):
        out(ln)
    out("===========================================")

    fname = datetime.datetime.now().strftime("diagnostico_sesiones_%Y%m%d_%H%M%S.txt")
    try:
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_LINES) + "\n")
        print(f"\nGuardado en {os.path.abspath(fname)}")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)   # pywnp deja hilos de servidor: se sale sin esperarlos
