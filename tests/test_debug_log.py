"""Modo depuración (debug_log): cómo se activa, qué registra y que nunca rompa el arranque."""
import logging, logging.handlers, os, subprocess, sys, tempfile, threading
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import debug_log, error_handling, version

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

# --- cómo se activa -----------------------------------------------------------
vacio = tempfile.mkdtemp()
check("por defecto NO se activa", not debug_log.requested(["main.py"], {}, vacio))
check("--log lo activa", debug_log.requested(["main.py", "--log"], {}, vacio))
check("--log=RUTA lo activa", debug_log.requested(["main.py", "--log=x.log"], {}, vacio))
check("YEFRIPLAYER_DEBUG=1 lo activa", debug_log.requested(["main.py"], {"YEFRIPLAYER_DEBUG": "1"}, vacio))
check("YEFRIPLAYER_DEBUG=0 no", not debug_log.requested(["main.py"], {"YEFRIPLAYER_DEBUG": "0"}, vacio))
open(os.path.join(vacio, "depurar.flag"), "w").close()
check("archivo depurar.flag junto al .exe lo activa", debug_log.requested(["main.py"], {}, vacio))
check("la ruta se toma de --log RUTA y de --log=RUTA", debug_log._explicit_path(["m", "--log", "a.log"]) == "a.log"
      and debug_log._explicit_path(["m", "--log=b.log"]) == "b.log" and debug_log._explicit_path(["m", "--log", "--port"]) is None)

# --- registro -----------------------------------------------------------------
destino = os.path.join(tmp, "mi", "depuracion.log")
orig_out, orig_err = sys.stdout, sys.stderr
ruta = debug_log.start(["main.py", "--log"], path=destino)
check("start devuelve la ruta y crea el archivo (y su carpeta)", str(ruta) == destino and os.path.exists(destino) and debug_log.active())
check("start dos veces no duplica", debug_log.start(["main.py"]) == ruta and len(logging.getLogger().handlers) <= 2)

print("hola desde print")
sys.stderr.write("mensaje de error\n")
logging.getLogger("aiohttp.server").warning("registro de otra biblioteca")
def hilo(): raise RuntimeError("fallo en hilo")
t = threading.Thread(target=hilo, name="Trabajador"); t.start(); t.join()
error_handling._write_log("--- aviso de prueba que va a error.log\n")
import warnings; warnings.warn("advertencia de prueba")
for h in logging.getLogger().handlers: h.flush()
texto = open(destino, encoding="utf-8").read()
debug_log.stop(); sys.stdout, sys.stderr = orig_out, orig_err

check("cabecera: versión, Python y argumentos", f"YefriPlayer {version.APP_VERSION}" in texto and "argumentos: ['--log']" in texto)
check("lo que se imprime con print queda registrado", "INFO    [MainThread] stdout: hola desde print" in texto)
check("stderr queda como WARNING", "WARNING [MainThread] stderr: mensaje de error" in texto)
check("registros de otras bibliotecas (logging)", "aiohttp.server: registro de otra biblioteca" in texto)
check("excepción de un hilo, con el nombre del hilo y el detalle", "en el hilo Trabajador" in texto and "RuntimeError: fallo en hilo" in texto)
check("lo que va a error.log se copia al registro", "error.log: --- " in texto and "aviso de prueba" in texto)
check("las advertencias de Python se registran", "advertencia de prueba" in texto)
check("tras stop() todo vuelve a la normalidad", not debug_log.active() and sys.stdout is orig_out)

# --- rotación -------------------------------------------------------------------
rot = os.path.join(tmp, "rot.log")
debug_log.MAX_BYTES = 2000; debug_log.BACKUPS = 2
debug_log.start(["m"], path=rot)
for h in list(logging.getLogger().handlers):            # sin eco en la terminal (son 400 líneas)
    if not isinstance(h, logging.handlers.RotatingFileHandler): logging.getLogger().removeHandler(h)
for i in range(400): logging.getLogger("x").info("linea %04d " + "z" * 40, i)
debug_log.stop(); debug_log.MAX_BYTES = 2 * 1024 * 1024; debug_log.BACKUPS = 3
check("rota y conserva copias (el disco no se llena)", os.path.exists(rot + ".1") and os.path.exists(rot + ".2") and not os.path.exists(rot + ".3"))

# --- nunca rompe el arranque ---------------------------------------------------
check("ruta imposible: start devuelve None y no lanza", debug_log.start(["m"], path=os.path.join(tmp, "x\0y", "a.log")) is None and not debug_log.active())

# --- de punta a punta: python main.py --log ------------------------------------
env = dict(os.environ, XDG_CONFIG_HOME=tempfile.mkdtemp())
rep = os.path.join(env["XDG_CONFIG_HOME"], "e2e.log")
r = subprocess.run([sys.executable, "-c",
    "import sys; sys.argv=['main.py','--log','%s']; import debug_log; debug_log.start(); import logging; "
    "logging.getLogger('yefriplayer').info('desde otro proceso'); print('salida')" % rep.replace("\\", "/")],
    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
t2 = open(rep, encoding="utf-8").read() if os.path.exists(rep) else ""
check("proceso real: registra y además lo muestra en la terminal",
      "desde otro proceso" in t2 and "proceso terminado" in t2 and "desde otro proceso" in r.stderr)

# --- flag de compilación -------------------------------------------------------
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compilar_nuitka as CN
w1 = CN.build_command(platform="win32", python="python", optional_present=lambda m: True, console=True)
w0 = CN.build_command(platform="win32", python="python", optional_present=lambda m: True, console=False)
check("--depurar/--console compila con terminal; sin ellos, sin consola",
      "--windows-console-mode=force" in w1 and "--windows-console-mode=disable" in w0)
print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
