"""Primera ejecución: valores predeterminados, teclas por defecto y bienvenida
(revisión, --bienvenida, --inicio-windows). Sin Qt: lógica y textos."""
import os, re, sys, tempfile
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import config, version, autostart

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

c = config.AppConfig()
check("predeterminados pedidos",
      c.start_with_windows and not c.always_on_top and not c.start_minimized and c.notifications_enabled
      and c.check_updates and not c.taskbar_button and c.audio_visualizer and c.visualizer_per_app)
check("teclas por defecto activas", c.hotkeys_enabled and c.hotkey_next == "ctrl+shift+c"
      and c.hotkey_previous == "ctrl+shift+x" and c.hotkey_play_pause == "ctrl+shift+space")
check("DEFAULT_HOTKEYS = las del config", config.DEFAULT_HOTKEYS == {
    "play_pause": c.hotkey_play_pause, "next": c.hotkey_next, "previous": c.hotkey_previous})
check("RECOMMENDED_PREFS = los predeterminados del config",
      all(getattr(c, k) == v for k, v in config.RECOMMENDED_PREFS.items()))
src = open(os.path.join(ROOT, "hotkeys.py"), encoding="utf-8").read()
check("«space» es una tecla registrable", '("Space", 0x20)' in src)

# Bienvenida: revisión y argumentos
ob = open(os.path.join(ROOT, "onboarding.py"), encoding="utf-8").read()
rev = int(re.search(r"^WELCOME_REVISION = (\d+)", ob, re.M).group(1))
check("la revisión de la bienvenida es mayor que la de un config viejo", rev > config.AppConfig().welcome_revision)
ac = open(os.path.join(ROOT, "app_controller.py"), encoding="utf-8").read()
check("se muestra si no se completó, si es de otra revisión o si se pide",
      "show_welcome or not self.config.onboarding_completed" in ac and "welcome_revision < onboarding.WELCOME_REVISION" in ac)
check("«Iniciar minimizado» solo al arrancar con Windows", "self.config.start_minimized and from_autostart" in ac)
mp = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
check("main.py acepta --bienvenida, --inicio-windows y --mostrar",
      all(a in mp for a in ('"--bienvenida"', '"--inicio-windows"', '"--mostrar"')))
check("«Iniciar con Windows» lanza con --inicio-windows", autostart.launch_command().endswith("--inicio-windows"))
iss = open(os.path.join(ROOT, "installer", "YefriPlayer.iss"), encoding="utf-8-sig").read()
check("instalación nueva: abre con la bienvenida", re.search(r'Parameters: "--bienvenida".*Check: not WasInstalledBefore', iss) is not None)
appid = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}", iss, re.M).group(1)
check("la clave de desinstalación que mira el instalador es la de su AppId", f"Uninstall\\{{{appid}}}_is1" in iss)
check("acceso directo de autoprueba", "--autotest --mostrar" in iss)

# Descripción
check("descripción única: controlador multimedia, no reproductor",
      "no reproduce audio" in version.APP_DESCRIPTION and version.APP_KIND == "Controlador multimedia")
check("plataformas: web y escritorio", "YouTube" in version.platforms_text() and "Spotify" in version.platforms_text()
      and "WebNowPlaying" in version.platforms_text())
check("el instalador lo explica en su bienvenida", "CONTROLADOR MULTIMEDIA" in iss)
check("el .exe lo dice en sus propiedades", "APP_TAGLINE" in open(os.path.join(ROOT, "main.spec"), encoding="utf-8").read())
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
