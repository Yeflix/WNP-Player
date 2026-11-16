"""--autotest, aviso de errores de arranque y ruta real del .exe (onefile de Nuitka)."""
import os, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
env = dict(os.environ, XDG_CONFIG_HOME=tmp, LOCALAPPDATA=tmp, QT_QPA_PLATFORM="offscreen")
fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

rep = os.path.join(tmp, "informe.txt")
r = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--autotest", rep], env=env, capture_output=True, text=True, timeout=120)
text = open(rep, encoding="utf-8").read() if os.path.exists(rep) else ""
check("--autotest sale con 0 y escribe el informe", r.returncode == 0 and "RESULTADO: todo ok" in text)
check("el informe revisa módulos de terceros y del programa", "PyQt6.QtWebSockets" in text and "OK     secret_store" in text and "OK     main_window" in text)
check("no abre la interfaz ni crea config.json", not os.path.exists(os.path.join(tmp, "YefriPlayer", "config.json")))

# un módulo del programa roto -> FALLA y código 1
bad = os.path.join(tmp, "proj"); os.makedirs(bad)
import shutil
for f in os.listdir(ROOT):
    if f.endswith(".py"): shutil.copy(os.path.join(ROOT, f), bad)
open(os.path.join(bad, "stats.py"), "w").write("import modulo_que_no_existe\n")
rep2 = os.path.join(tmp, "informe2.txt")
r2 = subprocess.run([sys.executable, os.path.join(bad, "main.py"), "--autotest", rep2], env=env, capture_output=True, text=True, timeout=120)
t2 = open(rep2, encoding="utf-8").read()
check("un módulo que falla -> FALLA con la causa y código 1", r2.returncode == 1 and "FALLA  stats" in t2 and "modulo_que_no_existe" in t2)

import glob, selftest
modulos = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROOT, "*.py")))
falta = [m for m in modulos if m not in ("main", "selftest") and m not in selftest.APP]
check("la autoprueba revisa TODOS los módulos del programa (falta: %s)" % falta, not falta)

# error de arranque: queda en startup-error.log (en vez de ser invisible)
open(os.path.join(bad, "theme.py"), "w").write("raise RuntimeError('boom de arranque')\n")
r3 = subprocess.run([sys.executable, os.path.join(bad, "main.py")], env=env, capture_output=True, text=True, timeout=60)
log = os.path.join(tmp, "YefriPlayer", "startup-error.log")
check("un fallo al arrancar termina con 1 y deja startup-error.log",
      r3.returncode == 1 and os.path.exists(log) and "boom de arranque" in open(log, encoding="utf-8").read())

# ruta real del programa
import version as V
check("código fuente: executable_path = sys.executable", V.executable_path() == sys.executable)
exe = os.path.join(tmp, "YefriPlayer.exe"); open(exe, "w").close()
old_argv = sys.argv; sys.argv = [exe]
check("fuera de Nuitka se ignora argv[0]", V.executable_path() == sys.executable)
V.executable_path.__globals__["__compiled__"] = object()
check("Nuitka: devuelve el .exe real (sys.argv[0]), no sys.executable", V.executable_path() == os.path.abspath(exe))
sys.argv = [os.path.join(tmp, "YefriPlayer")]
check("Nuitka: argv[0] sin extensión .exe también se resuelve", V.executable_path() == os.path.abspath(exe))
sys.argv = [os.path.join(tmp, "no_existe")]
check("Nuitka: si argv[0] no existe, cae a sys.executable", V.executable_path() == sys.executable)
del V.executable_path.__globals__["__compiled__"]; sys.argv = old_argv
print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
