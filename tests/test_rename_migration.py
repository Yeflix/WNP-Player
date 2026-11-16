"""Cambio de nombre a YefriPlayer: los datos de WNP Player se copian solos, sin borrar nada."""
import os, sys, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
import config, version

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

check("el nombre de la carpeta es YefriPlayer", config.APP_DIR_NAME == "YefriPlayer" and version.APP_NAME == "YefriPlayer")
legacy = config._dir_for("WNPPlayer"); legacy.mkdir(parents=True)
(legacy / "config.json").write_text(json.dumps({"port": 4321, "onboarding_completed": True}), encoding="utf-8")
(legacy / "history.json").write_text("[]", encoding="utf-8")
(legacy / "sub").mkdir(); (legacy / "sub" / "x.txt").write_text("hola", encoding="utf-8")

target = config._dir_for(config.APP_DIR_NAME)
check("antes de migrar no existe la carpeta nueva", not target.exists())
check("la primera vez copia los datos anteriores", config._migrate_legacy(target) is True)
check("config e historial copiados", (target / "config.json").exists() and (target / "history.json").exists() and (target / "sub" / "x.txt").exists())
check("la carpeta vieja queda intacta (se puede volver atrás)", (legacy / "config.json").exists())
check("la configuración migrada se carga", config.AppConfig.load().port == 4321)
(target / "config.json").write_text(json.dumps({"port": 5555}), encoding="utf-8")
check("no vuelve a copiar encima de datos nuevos", config._migrate_legacy(target) is False and config.AppConfig.load().port == 5555)
other = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = other; os.environ["LOCALAPPDATA"] = other
check("sin carpeta anterior no hace nada", config._migrate_legacy(config._dir_for("YefriPlayer")) is False)

check("User-Agent con nombre y versión", version.user_agent().startswith(f"YefriPlayer/{version.APP_VERSION}"))
version.PROJECT_URL = "https://example.org/yefriplayer"
check("User-Agent incluye el enlace si está configurado", "(+https://example.org/yefriplayer)" in version.user_agent())
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
