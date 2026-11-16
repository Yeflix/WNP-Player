"""Empaquetado: detección de ejecutable (PyInstaller/Nuitka), comando de Nuitka y pool de hilos de Python."""
import os, sys, time, tempfile, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
import version as V, workers
import compilar_nuitka as CN

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

# ---------------------------------------------------------------- is_frozen
check("con `python main.py` no se considera empaquetado", V.is_frozen() is False)
sys.frozen = True
check("PyInstaller (sys.frozen) se detecta", V.is_frozen() is True)
del sys.frozen
V.is_frozen.__globals__["__compiled__"] = object()
check("Nuitka (__compiled__ en el módulo) se detecta aunque NO ponga sys.frozen", V.is_frozen() is True and not hasattr(sys, "frozen"))
del V.is_frozen.__globals__["__compiled__"]
check("y vuelve a False al quitarlo", V.is_frozen() is False)

# ------------------------------------------------------- comando de Nuitka
win = CN.build_command(platform="win32", python="python", optional_present=lambda m: True)
def has(cmd, prefix): return any(c.startswith(prefix) for c in cmd)
check("modo carpeta por defecto", "--mode=standalone" in win and "--mode=onefile" not in win)
check("plugin de PyQt6 activado", "--enable-plugins=pyqt6" in win)
check("el ejecutable se llama YefriPlayer", f"--output-filename={V.APP_NAME}" in win)
check("Windows: sin consola", "--windows-console-mode=disable" in win)
check("Windows: ícono", has(win, "--windows-icon-from-ico=") and win[[i for i, c in enumerate(win) if c.startswith("--windows-icon")][0]].endswith("yefriplayer.ico"))
check("Windows: datos de versión del .exe", f"--product-name={V.APP_NAME}" in win and f"--company-name={V.AUTHOR}" in win
      and any(c == f"--file-version={V.APP_VERSION}.0" for c in win) and f"--product-version={V.APP_VERSION}" in win)
check("pywnp y aiohttp (importación dinámica) se piden explícitamente", "--include-package=pywnp" in win and "--include-package=aiohttp" in win)
check("winsdk: solo los módulos necesarios", "--include-module=winsdk.windows.media.control" in win and "--include-package=winsdk" not in win)
check("numpy NO se fuerza entero (arrastraba sus pruebas y pytest); se sigue por importación estática", "--include-package=numpy" not in win and "--include-package=pyaudiowpatch" not in win)
check("unittest/test/pydoc ya no se excluyen (algo podría importarlos en el .exe)", not any(c in ("--nofollow-import-to=unittest", "--nofollow-import-to=test", "--nofollow-import-to=pydoc") for c in win))
check("pruebas de numpy y aiohttp excluidas", "--nofollow-import-to=numpy.testing" in win and "--nofollow-import-to=aiohttp.test_utils" in win)
check("módulos de Qt sin uso excluidos", "--nofollow-import-to=PyQt6.QtWebEngineCore" in win and "--nofollow-import-to=tkinter" in win)
check("licencia y léeme viajan con el ejecutable", has(win, "--include-data-files=") and any(c.endswith("=LICENSE") for c in win))
check("el último argumento es main.py", win[-1].endswith("main.py"))
check("sin LTO por defecto (compila mucho más rápido)", "--lto=no" in win)
full = CN.build_command(platform="win32", winsdk_completo=True, onefile=True, console=True, msvc=True, asumir_si=True, jobs=4, lto=True)
check("--winsdk-completo / --onefile / --console / --msvc / --jobs / --lto / --asumir-si", "--include-package=winsdk" in full and "--mode=onefile" in full
      and "--windows-console-mode=force" in full and "--msvc=latest" in full and "--jobs=4" in full and "--lto=yes" in full and "--assume-yes-for-downloads" in full)
check("--mingw", "--mingw64" in CN.build_command(platform="win32", mingw=True))
lin = CN.build_command(platform="linux", optional_present=lambda m: False)
check("fuera de Windows no se pasan opciones exclusivas de Windows", not has(lin, "--windows-") and not has(lin, "--company-name") and not has(lin, "--include-module=winsdk"))
check("paquetes no instalados se omiten (sin romper Nuitka)", "--include-package=pywnp" not in lin and "--include-package=yarl" not in lin)

# ------------------------------------------------------ comprobación de entorno
real_installed, real_version = CN._installed, sys.version_info
try:
    CN._installed = lambda m: m != "nuitka"
    check("sin Nuitka lo dice y explica cómo instalarlo", any("pip install nuitka" in p for p in CN.check_environment("win32")))
    CN._installed = lambda m: m != "winsdk"
    check("sin winsdk en Windows lo avisa", any("winsdk" in p for p in CN.check_environment("win32")))
    CN._installed = lambda m: True
    sys.version_info = (3, 14, 0, "final", 0)
    check("Windows con Python 3.14: avisa que hace falta 3.12", any("3.12" in p for p in CN.check_environment("win32")))
    sys.version_info = (3, 12, 3, "final", 0)
    check("Windows con Python 3.12 y todo instalado: sin problemas", CN.check_environment("win32") == [])
finally:
    CN._installed, sys.version_info = real_installed, real_version
check("--dry-run no compila ni falla", CN.main(["--dry-run"]) == 0)

# --------------------------------------------------- pool de hilos de Python
pool = workers.BackgroundPool(max_workers=3)
seen = []; lock = threading.Lock()
class Job:
    def __init__(self, i): self.i = i
    def run(self):
        time.sleep(0.02)
        with lock: seen.append((self.i, threading.current_thread().name))
for i in range(8): pool.start(Job(i))
check("espera a que terminen los trabajos", pool.wait_for_done(5.0) is True)
check("se ejecutaron todos, en hilos de Python distintos al principal", sorted(i for i, _ in seen) == list(range(8)) and all(n != threading.main_thread().name for _, n in seen))
class Bad:
    def run(self): raise RuntimeError("falla de prueba")
pool.start(Bad()); pool.start(Job(99))
check("un trabajo que falla no mata al hilo ni a los demás", pool.wait_for_done(5.0) and (99, ) == tuple(x for x in [s for s in seen if s[0] == 99][0][:1]))
check("el grupo compartido es único", workers.default_pool() is workers.default_pool())
pool.shutdown(); pool.start(Job(1))
check("tras cerrar no acepta trabajos y no lanza excepción", pool.wait_for_done(1.0) is True)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
