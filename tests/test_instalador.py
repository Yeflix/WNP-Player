"""Instalador de Windows (installer/YefriPlayer.iss + tools/construir_instalador.py).

No necesita Qt ni Windows: comprueba que el script de Inno Setup y el código
hablan de lo mismo (mutex, canal de instancia única, AppUserModelID, entrada de
«Iniciar con Windows»), que los archivos que empaqueta existen y que el comando
de ISCC se arma bien. La compilación real del instalador se prueba en Windows."""
import re, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import version, autostart
import construir_instalador as CI

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, detail if not cond else ""); fails += 0 if cond else 1

iss = (ROOT / "installer" / "YefriPlayer.iss").read_text(encoding="utf-8")
def define(name):
    m = re.search(r'#define\s+%s\s+"([^"]*)"' % name, iss)
    return m.group(1) if m else None

single = (ROOT / "single_instance.py").read_text(encoding="utf-8")
main_src = (ROOT / "main.py").read_text(encoding="utf-8")

check("mutex del instalador = el que crea la app",
      define("AppMutexName") == re.search(r'APP_MUTEX_NAME = "([^"]+)"', single).group(1))
check("canal «quit» del instalador = servidor de instancia única",
      define("PipeName") == re.search(r'_SERVER_NAME = "([^"]+)"', single).group(1))
check("la app entiende la orden quit", '_QUIT_MESSAGE = b"quit"' in single and "quitRequested" in single)
check("main.py conecta quitRequested y acepta --quit",
      "guard.quitRequested.connect" in main_src and '"--quit"' in main_src)
check("AppUserModelID igual en accesos directos y en la app",
      define("AppUserModel") == re.search(r'APP_USER_MODEL_ID = "([^"]+)"', main_src).group(1))
check("entrada de inicio que se limpia al desinstalar = la de autostart.py",
      define("RunValueName") == autostart.VALUE_NAME)
check("nombre y ejecutable coinciden con version.py",
      define("AppName") == version.APP_NAME and define("AppExe") == version.APP_NAME + ".exe")
check("AppId fijo presente (no cambiar nunca)", re.search(r"^AppId=\{\{[0-9A-F-]{36}\}", iss, re.M) is not None)
check("instalación por usuario con opción para todos",
      "PrivilegesRequired=lowest" in iss and "PrivilegesRequiredOverridesAllowed=commandline dialog" in iss)
check("Spicetify AutoFix corre con el usuario original (Spicetify rechaza admin)",
      re.search(r"Instalar-AutoFix\.ps1.*runasoriginaluser", iss) is not None)
check("al desinstalar se quita la tarea de AutoFix si se instaló",
      re.search(r"\[UninstallRun\][\s\S]*-Desinstalar[^\n]*Tasks: autofix", iss) is not None)
check("datos del usuario: solo se borran si lo confirma (No por defecto)", "MB_DEFBUTTON2" in iss)

# Archivos referenciados por el .iss (rutas relativas a installer/)
for rel in ("..\\assets\\yefriplayer.ico", "..\\LICENSE"):
    check(f"existe {rel}", (ROOT / "installer" / rel.replace("\\", "/")).resolve().exists())
for name in ("Instalar-AutoFix.ps1", "Spicetify-AutoFix.ps1", "Lanzador.cs", "Instalar.bat", "Estado.bat"):
    check(f"existe SpicetifyAutoFix/{name}", (ROOT / "SpicetifyAutoFix" / name).exists())

# Comando de ISCC
cmd = CI.build_iscc_command(Path("C:/IS/ISCC.exe"), Path("C:/p/dist-nuitka/YefriPlayer"),
                            Path("C:/p/out"), "9.8.7")
check("ISCC recibe versión, carpeta compilada y salida",
      "/DAppVersion=9.8.7" in cmd and any(a.startswith("/DSourceDir=") for a in cmd)
      and any(a.startswith("/DOutputDir=") for a in cmd) and cmd[-1].endswith("YefriPlayer.iss"))
check("nombre del instalador", CI.installer_path(Path("o"), "9.8.7").name == "YefriPlayer-9.8.7-Setup.exe")
check("OutputBaseFilename del .iss produce ese mismo nombre",
      "OutputBaseFilename={#AppName}-{#AppVersion}-Setup" in iss)

# Búsqueda de ISCC
with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp) / "Programs" / "Inno Setup 6" / "ISCC.exe"
    fake.parent.mkdir(parents=True); fake.write_text("")
    env = {"LOCALAPPDATA": tmp, "PATH": ""}
    check("encuentra ISCC instalado por usuario (winget)", CI.find_iscc(env=env) == fake)
    check("respeta la variable ISCC", CI.iscc_candidates({"ISCC": "X:/a/ISCC.exe"})[0] == Path("X:/a/ISCC.exe"))
    check("--iscc inexistente → None", CI.find_iscc(str(Path(tmp) / "no.exe")) is None)
    d = Path(tmp) / "comp"; d.mkdir()
    check("sin .exe compilado → problema", any("No existe" in p for p in CI.check_compiled(d)))
    (d / "YefriPlayer.exe").write_text(""); (d / "depurar.flag").write_text("")
    probs = CI.check_compiled(d)
    check("con .exe → solo aviso de depurar.flag", len(probs) == 1 and "depurar.flag" in probs[0])

check("dry-run no falla", CI.main(["--dry-run"]) == 0)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
