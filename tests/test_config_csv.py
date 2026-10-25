"""Validación de config.json al cargar e inyección de fórmulas en el CSV de anuncios."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp
os.environ["LOCALAPPDATA"] = tmp
import config, ad_log

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name)
    fails += 0 if cond else 1

p = config._config_path(); p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({"port": 99999, "font_scale": 0, "window_opacity": "x", "dock_style": "raro",
                         "always_on_top": "si", "mini_scale": 9, "main_x": 120, "onboarding_completed": True,
                         "last_mode": "dock", "ui_scale": -3}), encoding="utf-8")
c = config.AppConfig.load()
check("puerto fuera de rango se recorta", c.port == 65535)
check("font_scale 0 se sube al mínimo", c.font_scale == 0.8)
check("tipo incorrecto vuelve al defecto", c.window_opacity == 1.0 and c.always_on_top is False)
check("opción desconocida vuelve al defecto", c.dock_style == "card")
check("mini_scale recortado", c.mini_scale == 3.0)
check("valores válidos se conservan", c.main_x == 120 and c.onboarding_completed is True and c.last_mode == "dock")
check("ui_scale negativo se descarta", c.ui_scale == 0.0)
p.write_text("[1,2]", encoding="utf-8")
check("JSON que no es objeto -> defecto", config.AppConfig.load().port == 1234)

ad_log.add_entry("=HYPERLINK(\"http://x\")", "+cmd", "Spotify", 30, "-r")
ad_log.add_entry("Normal", "Spotify", "Spotify", 30, "regla")
rows = ad_log.load()
check("fórmulas neutralizadas", rows[0]["title"].startswith("'=") and rows[0]["artist"].startswith("'+") and rows[0]["reason"].startswith("'-"))
check("texto normal intacto", rows[1]["title"] == "Normal")
print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
