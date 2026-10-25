"""Lógica del veredicto de tools/diagnostico_sesiones.py (no necesita Windows).

    python tests/test_diagnostico_sesiones.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

import diagnostico_sesiones as d

SP = "Spotify.exe"
win_sp = [{"app": SP, "actual": True, "estado": "PLAYING", "titulo": "t", "artista": "a"}]
win_tg = [{"app": "Telegram.exe", "actual": True, "estado": "PAUSED", "titulo": "", "artista": ""}]
def wnp(entries=(), current=None, ok=True, native_dir=False, error=""):
    return {"ok": ok, "error": error, "native_dir_exists": native_dir, "wnp_path": r"C:\x", "entries": list(entries),
            "current": current}
e_sp = {"id": "WNPReduxNativeWindows_Spotify.exe", "nativo": True, "estado": "PLAYING", "titulo": "t", "artista": "a",
        "player_name": "Spotify"}
cur_sp = {"id": e_sp["id"], "player_name": "Spotify", "estado": "PLAYING", "titulo": "t"}
text = lambda v: " ".join(v)

check("winsdk ausente -> pide instalarlo", "pip install winsdk" in text(d.veredicto(1, False, [], wnp())))
check("carpeta use_native_apis -> lo dice", "DESACTIVADAS" in text(d.veredicto(1, True, win_sp, wnp(native_dir=True))))
check("Spotify cerrado -> lo dice", "no está abierto" in text(d.veredicto(0, True, [], wnp())))
v = text(d.veredicto(1, True, [], wnp()))
check("abierto pero Windows no publica sesión -> Windows NO publica + qué hacer", "Windows NO publica" in v and "REPRODUCIENDO" in v)
check("... y menciona la opción del overlay de teclas multimedia", "Show desktop overlay when using media keys" in v)
v = text(d.veredicto(1, True, win_tg, wnp()))
check("... y nombra las otras apps que Windows sí ve", "Windows NO publica" in v and "Telegram.exe" in v)
check("no se pudo contar procesos (-1): no afirma que esté cerrado",
      "no está abierto" not in text(d.veredicto(-1, True, [], wnp())))
check("Windows ve Spotify pero pywnp falló al arrancar", "pywnp falló" in text(d.veredicto(1, True, win_sp, wnp(ok=False, error="boom"))))
check("Windows lo ve y pywnp no lo lista -> problema del reproductor", "lado del reproductor" in text(d.veredicto(1, True, win_sp, wnp())))
other = {"id": "WNPReduxNativeWindows_Telegram.exe", "player_name": "Telegram", "estado": "PLAYING", "titulo": ""}
check("pywnp elige otra fuente activa -> lo explica", "OTRA fuente" in text(d.veredicto(1, True, win_sp, wnp([e_sp], other))))
check("todo bien -> la detección funciona", "ven a Spotify correctamente" in text(d.veredicto(1, True, win_sp, wnp([e_sp], cur_sp))))
check("Spotify de Microsoft Store (id largo) también se reconoce",
      d.is_spotify_id("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"))
check("el módulo se importa sin Windows y main() lo avisa", d.main() == 1 if sys.platform != "win32" else True)

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
