"""Palomita de las casillas marcadas: se genera en la carpeta de datos, sin recursos empaquetados."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import theme, config

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

folder = config._config_dir()
check("importar el módulo no crea archivos (sin QApplication)", not folder.exists() or not list(folder.glob("casilla-*")))
check("sin QApplication la hoja de estilo no lleva imagen", "casilla-" not in theme.build_global_qss())

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
app = QApplication(sys.argv)

def tick_color(path):
    img = QImage(str(path)); best = None
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 200: best = c
    return best

theme.set_player_theme("default")
qss = theme.build_global_qss()
check("aspecto predeterminado: la regla de imagen está en la hoja", 'image: url("' in qss and "casilla-blanca-v1.png" in qss)
check("se generan la versión normal y la @2x", (folder / "casilla-blanca-v1.png").exists() and (folder / "casilla-blanca-v1@2x.png").exists())
c = tick_color(folder / "casilla-blanca-v1.png")
check("la palomita es blanca sobre el acento rojo", c is not None and c.red() > 240 and c.green() > 240)
check("el tamaño es 12 px (24 px en @2x)", QImage(str(folder / "casilla-blanca-v1.png")).width() == 12 and QImage(str(folder / "casilla-blanca-v1@2x.png")).width() == 24)

theme.set_player_theme("cosmos")
qss2 = theme.build_global_qss()
check("Cosmos: usa la palomita oscura (contraste)", "casilla-oscura-v1.png" in qss2)
c2 = tick_color(folder / "casilla-oscura-v1.png")
check("la palomita oscura es oscura", c2 is not None and c2.red() < 60)
theme.set_player_theme("default")
check("volver al predeterminado reutiliza el archivo", theme.build_global_qss() == qss)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
