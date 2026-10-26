"""Iniciar con Windows: registro simulado (no toca ningún registro real)."""
import os, sys, types, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
import autostart, config

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

class _Key:
    def __init__(s, store): s.store = store
    def __enter__(s): return s
    def __exit__(s, *a): return False
store = {}
fake = types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_READ=1, KEY_SET_VALUE=2, REG_SZ=1)
def _open(root, path, res=0, access=0):
    if path != autostart.RUN_KEY: raise OSError("clave")
    return _Key(store)
def _query(key, name):
    if name not in store: raise FileNotFoundError(name)
    return store[name], 1
def _set(key, name, res, kind, value): store[name] = value
def _del(key, name):
    if name not in store: raise FileNotFoundError(name)
    del store[name]
fake.OpenKey = _open; fake.CreateKey = lambda root, path: _Key(store)
fake.QueryValueEx = _query; fake.SetValueEx = _set; fake.DeleteValue = _del
autostart._winreg = lambda: fake

check("por defecto está activado", config.AppConfig().start_with_windows is True)
check("config sin la clave -> activado", config.AppConfig._sanitize({}) == {} and config.AppConfig().start_with_windows)
check("sin entrada al inicio", autostart.is_enabled() is False)
check("activar crea la entrada", autostart.sync(True) and autostart.is_enabled())
check("el comando entre comillas", store["WNPPlayer"].startswith('"'))
store["WNPPlayer"] = '"C:\\viejo\\WNP.exe"'
autostart.sync(True)
check("se corrige una ruta vieja", store["WNPPlayer"] == autostart.launch_command())
check("desactivar elimina la entrada", autostart.sync(False) and not autostart.is_enabled())
check("desactivar sin entrada no falla", autostart.sync(False) is True)

# .exe empaquetado: el comando es el propio ejecutable
sys.frozen = True; real = sys.executable; sys.executable = "C:\\Apps\\WNP Player\\WNP Player.exe"
check(".exe: comando = ruta del ejecutable entre comillas", autostart.launch_command() == '"C:\\Apps\\WNP Player\\WNP Player.exe"')
del sys.frozen; sys.executable = real
check("código fuente: usa main.py", autostart.launch_command().endswith('main.py"'))

# registro con error -> False, sin excepción
fake.CreateKey = lambda *a: (_ for _ in ()).throw(OSError("denegado"))
check("error de registro -> False", autostart.set_enabled(True) is False)

# Fuera de Windows no hace nada
autostart._winreg = lambda: None
check("sin Windows: no soportado y sin efecto", not autostart.is_supported() and autostart.sync(True) is False)

# Configuración: se guarda y se recupera
c = config.AppConfig(); c.start_with_windows = False; c.save()
check("la opción se guarda", config.AppConfig.load().start_with_windows is False)
# Actualizar desde 1.0: no se activa solo; instalación nueva: sí
import json
p = config._config_path(); p.write_text(json.dumps({"onboarding_completed": True, "port": 1234}), encoding="utf-8")
check("actualizando desde 1.0: queda desactivado", config.AppConfig.load().start_with_windows is False)
p.write_text(json.dumps({"onboarding_completed": True, "start_with_windows": True}), encoding="utf-8")
check("si ya lo había elegido, se respeta", config.AppConfig.load().start_with_windows is True)
p.unlink()
check("instalación nueva (sin config): activado", config.AppConfig.load().start_with_windows is True)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
