"""config.json: el autoguardado no reescribe si nada cambió, pero sí si cambió algo,
si alguien editó o borró el archivo; y el reemplazo atómico reintenta si Windows
lo tiene bloqueado un instante. config.py ya no importa PyQt6 (se comprueba)."""
import os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

check("config.py se importa sin cargar Qt", "PyQt6" not in sys.modules)
c = config.AppConfig(); c.save(); p = config._config_path()
m1 = p.stat().st_mtime_ns; time.sleep(0.02); c.save()
check("sin cambios no se reescribe", p.stat().st_mtime_ns == m1)
c.port = 5678; c.save()
check("con cambios se guarda", config.AppConfig.load().port == 5678)
time.sleep(0.02); p.write_text(p.read_text(encoding="utf-8").replace("5678", "4321"), encoding="utf-8"); c.save()
check("si se editó a mano, el siguiente guardado manda", config.AppConfig.load().port == 5678)
p.unlink(); c.save()
check("si se borró, se vuelve a crear", p.exists())

# Reintento ante PermissionError transitorio
calls = {"n": 0}; real = os.replace
def flaky(a, b):
    calls["n"] += 1
    if calls["n"] < 3:
        raise PermissionError("bloqueado")
    return real(a, b)
os.replace = flaky
try:
    c.port = 1111; c.save()
finally:
    os.replace = real
check("reintenta y guarda tras un bloqueo momentáneo", calls["n"] == 3 and config.AppConfig.load().port == 1111)
check("no queda el temporal", not p.with_suffix(".json.tmp").exists())
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
