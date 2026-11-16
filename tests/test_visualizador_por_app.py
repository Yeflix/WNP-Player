"""Visualizador solo con el audio del reproductor (process_loopback + audio_levels).
La captura real (COM de Windows) no se puede probar aquí: se prueban la elección
del proceso y el respaldo automático a «todo el equipo» con fuentes simuladas."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtCore import QCoreApplication
app = QCoreApplication.instance() or QCoreApplication(sys.argv)
import process_loopback as PL, audio_levels as AL

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

# Árbol de procesos: explorer(1) → spotify(10) → spotify(11, audio); explorer → chrome(20) → chrome(21, audio)
procs = [(1, 0, "explorer.exe"), (10, 1, "spotify.exe"), (11, 10, "spotify.exe"),
         (20, 1, "chrome.exe"), (21, 20, "chrome.exe"), (30, 1, "discord.exe")]
check("sube hasta el proceso principal del mismo ejecutable", PL.root_pid(11, procs) == 10)
check("no sube a un padre de otro ejecutable", PL.root_pid(10, procs) == 10)
check("pid desconocido se deja igual", PL.root_pid(99, procs) == 99)
check("un ciclo de padres no se cuelga", PL.root_pid(5, [(5, 6, "a.exe"), (6, 5, "a.exe")]) in (5, 6))

sess = [(11, "spotify.exe", True), (21, "chrome.exe", False), (30, "discord.exe", True)]
check("Spotify de escritorio sonando → Spotify", PL.choose_target(("spotify.exe",), sess, procs) == (10, "spotify.exe"))
sess = [(11, "spotify.exe", False), (21, "chrome.exe", True), (30, "discord.exe", True)]
check("web (Spotify de escritorio callado) → el navegador que suena",
      PL.choose_target(("spotify.exe",), sess, procs) == (20, "chrome.exe"))
check("YouTube en el navegador → el navegador", PL.choose_target(("youtube.exe",), sess, procs) == (20, "chrome.exe"))
check("Discord nunca se elige", PL.choose_target(("youtube.exe",), [(30, "discord.exe", True)], procs) is None)
check("app sin sonar y sin navegador sonando → la app igualmente",
      PL.choose_target(("spotify.exe",), [(11, "spotify.exe", False)], procs) == (10, "spotify.exe"))
ok, why = PL.availability()
check("fuera de Windows no está disponible y lo explica", (not ok and "Windows" in why) if sys.platform != "win32" else True)

# --- respaldo en AudioLevels ----------------------------------------------------
log = []
class Fake:
    def __init__(self, kind, fail=False): self.kind, self.fail = kind, fail
    def start(self, cb):
        log.append(("start", self.kind))
        if self.fail: raise OSError("no se puede")
    def stop(self): log.append(("stop", self.kind))
per_app_fail = {"v": False}
lv = AL.AudioLevels(source_factory=lambda: Fake("equipo"),
                    per_app_factory=lambda name: Fake(f"app:{name}", per_app_fail["v"]))
lv.set_enabled(True); lv.set_playing(True); lv.acquire(object()); lv._viewers.add(1)
lv.set_target("Spotify")
lv._stop_source(); log.clear(); lv._start_source()
check("con reproductor: se usa la captura por aplicación", log == [("start", "app:Spotify")] and lv.using_per_app, str(log))
log.clear(); lv.set_target("YouTube")
check("cambiar de reproductor reabre la captura sobre el nuevo",
      ("stop", "app:Spotify") in log and ("start", "app:YouTube") in log, str(log))
per_app_fail["v"] = True; lv._stop_source(); log.clear(); lv._start_source()
check("si falla, se cae a todo el equipo en el acto",
      log[:3] == [("start", "app:YouTube"), ("stop", "app:YouTube"), ("start", "equipo")] and not lv.using_per_app, str(log))
lv._stop_source(); log.clear(); lv._start_source()
check("y no se reintenta enseguida con ese reproductor", log == [("start", "equipo")], str(log))
lv.set_target(""); lv._stop_source(); log.clear(); lv._start_source()
check("sin reproductor (o la opción apagada) → todo el equipo", log == [("start", "equipo")])
lv2 = AL.AudioLevels(source_factory=lambda: Fake("equipo"))
lv2.set_target("Spotify"); lv2._start_source()
check("sin fábrica por aplicación (Windows antiguo): como antes", not lv2.using_per_app)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
