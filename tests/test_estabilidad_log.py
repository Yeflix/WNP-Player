"""Registro con rotación que conserva lo anterior, crash.log de fallos nativos, stderr=None en el .exe y Python no soportado."""
import os, sys, tempfile, faulthandler, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
import error_handling as EH, startup_checks as SC

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

# --- rotación: lo anterior se conserva
EH._MAX_LOG_BYTES = 200
log = EH.log_path()
EH._write_log("A" * 150 + "\n"); EH._write_log("B" * 150 + "\n")      # pasa del tope
EH._write_log("C" * 50 + "\n")
old = log.with_name(log.name + ".1")
check("al pasar el tope el log se archiva como error.log.1", old.exists())
check("lo anterior NO se pierde", "A" * 150 in old.read_text(encoding="utf-8") or "B" * 150 in old.read_text(encoding="utf-8"))
check("el log nuevo tiene lo último", "C" * 50 in log.read_text(encoding="utf-8"))
EH._MAX_LOG_BYTES = 512 * 1024

# --- .exe sin consola: sys.stderr es None
saved_err, saved_hook, saved_thook = sys.stderr, sys.excepthook, __import__("threading").excepthook
EH._show_dialog = lambda text: None
try:
    sys.stderr = None
    EH.install_native_crash_log = lambda: True          # aquí no interesa faulthandler
    EH.install()
    try:
        sys.excepthook(ValueError, ValueError("falla de prueba"), None)
        raised = False
    except Exception:
        raised = True
    check("sin consola (stderr=None) el manejador de errores no vuelve a fallar", not raised)
    check("y el error queda registrado", "falla de prueba" in log.read_text(encoding="utf-8"))
finally:
    sys.stderr, sys.excepthook = saved_err, saved_hook
    __import__("threading").excepthook = saved_thook

# --- fallos nativos (faulthandler)
import importlib; importlib.reload(EH)
crash = EH.crash_log_path()
crash.write_text('Fatal Python error: Segmentation fault\n\nThread 0x1 (most recent call first):\n  File "x.py", line 1\n', encoding="utf-8")
check("se detecta el fallo nativo de la sesión anterior", EH._report_previous_crash(crash) is True)
check("se copia al registro de errores", "cierre inesperado" in log.read_text(encoding="utf-8") and "Segmentation fault" in log.read_text(encoding="utf-8"))
check("y crash.log se archiva (no se reporta dos veces)", not crash.exists() and crash.with_name("crash.log.1").exists())
check("sin fallo previo no hace nada", EH._report_previous_crash(crash) is False)
check("faulthandler queda activo escribiendo en crash.log", EH.install_native_crash_log() is True and faulthandler.is_enabled())
faulthandler.disable(); EH._crash_file.close()

# --- Python que winsdk no soporta
check("Python 3.12 es compatible", SC.winsdk_supported((3, 12, 4)))
check("Python 3.10 es compatible", SC.winsdk_supported((3, 10, 0)))
check("Python 3.13 NO es compatible", not SC.winsdk_supported((3, 13, 1)))
check("Python 3.14 NO es compatible", not SC.winsdk_supported((3, 14, 0)))
msg = SC._python_message((3, 14, 0))
check("el mensaje explica qué versión instalar", "3.14" in msg and "3.12" in msg and "requirements.txt" in msg)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
