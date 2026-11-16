"""Mejoras de interfaz de 1.3.1: búsqueda y secciones en Configuración, tiempo compacto en
Estadísticas, etiqueta de estado adaptable, nombres accesibles, color de enlaces y título en dos
líneas con movimiento reducido."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QCheckBox, QSlider, QWidget
from PyQt6.QtGui import QPalette, QFont, QColor
from PyQt6.QtCore import QObject, pyqtSignal
app = QApplication(sys.argv)
import theme, config, dialogs, stats, widgets
import main_window as mw
from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=False); app.setStyleSheet(theme.build_global_qss())

fails = 0
def check(name, cond, extra=""):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1
def settle(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents()

# --- 1) tiempo compacto ------------------------------------------------------------------------
check("2 h 50 min -> 2 h 50 m", stats.shorten_duration("2 h 50 min") == "2 h 50 m")
check("45 min, 3 h y 'menos de 1 min' no cambian", [stats.shorten_duration(x) for x in ("45 min", "3 h", "menos de 1 min", "0 min")] == ["45 min", "3 h", "menos de 1 min", "0 min"])

# --- 2) Configuración: búsqueda y secciones ---------------------------------------------------------
class Puente(QObject):
    connectionChanged = pyqtSignal(bool); modesChanged = pyqtSignal(list); modeChanged = pyqtSignal(str)
    is_running = True; is_connected = False; last_error = ""; port = 8977
    def mode(self): return ""
    def modes(self): return []
d = dialogs.SettingsDialog(config.AppConfig(), 1234, lambda: None, lambda: None, lambda: None, theme_bridge=Puente())
d.show(); settle(0.3)
names = [n for n, _ in d._nav_anchors]
check("secciones en el orden en que aparecen (Spotify va a mitad)",
      names == ["General", "Teclas", "Visualizador", "Aspecto", "Panel", "Spotify", "Cuentas", "YouTube", "Datos"], str(names))
CUENTAS = names.index("Cuentas")
ys = [w.mapTo(d._nav_inner, widgets.QPoint(0, 0)).y() if hasattr(widgets, "QPoint") else w.mapTo(d._nav_inner, __import__("PyQt6.QtCore", fromlist=["QPoint"]).QPoint(0, 0)).y() for _, w in d._nav_anchors]
check("y su posición vertical crece de arriba abajo", ys == sorted(ys) and len(set(ys)) == len(ys))
check("hay un botón por sección (barra lateral) y el primero está marcado",
      len(d._nav_chips) == len(names) and d._nav_chips[0].isChecked() and d._nav_chips[0].objectName() == "settingsNavItem")
d._goto_section(CUENTAS); settle(0.1)
check("al pulsar «Cuentas» se desplaza hasta esa sección", d._nav_scroll.verticalScrollBar().value() > 0 and d._nav_chips[CUENTAS].isChecked())
d._nav_scroll.verticalScrollBar().setValue(0); settle(0.1)
check("al volver arriba se marca «General»", d._nav_chips[0].isChecked() and not d._nav_chips[CUENTAS].isChecked())
check("sin buscar, una tarjeta por sección", len(d._nav_inner.card_rects()) == len(names))
d._nav_scroll.verticalScrollBar().setValue(d._nav_scroll.verticalScrollBar().maximum()); settle(0.1)
check("al llegar al final se marca la última sección", d._nav_chips[-1].isChecked())

def visibles(): return [g for g in d._search_groups if all(not w.isHidden() for w in g["widgets"])]
base = len(visibles())            # grupos visibles sin filtrar (algunos llevan cuadros ocultos por su propia lógica)
d._search_input.setText("contraste"); settle(0.1)
v = visibles()
check("buscar «contraste» deja solo lo que lo menciona (alto contraste y su sección)", 1 <= len(v) <= 3 and all("contraste" in g["folded"] for g in v))
d._search_input.setText("ACCESIBILIDAD"); settle(0.1)
check("la búsqueda ignora mayúsculas y tildes (accesibilidad = Accesibilidad)", len(visibles()) >= 1 and all("accesibilidad" in g["folded"] for g in visibles()))
d._search_input.setText("visualizador audio"); settle(0.1)
check("varias palabras: deben estar todas", len(visibles()) >= 1
      and all("visualizador" in g["folded"] and "audio" in g["folded"] for g in visibles()))
check("buscando no se dibujan tarjetas", d._nav_inner.card_rects() == [])
d._search_input.setText("letra"); settle(0.1)
check("buscando no hay ninguna sección marcada", not any(c.isChecked() for c in d._nav_chips))
d._search_input.setText("xyzqq"); settle(0.1)
check("sin coincidencias aparece el aviso", len(visibles()) == 0 and not d._no_results.isHidden())
d._search_input.setText(""); settle(0.1)
check("al borrar se vuelve a marcar la sección actual", sum(c.isChecked() for c in d._nav_chips) == 1)
check("al borrar la búsqueda vuelve todo lo que se veía antes", len(visibles()) == base and d._no_results.isHidden())
# lo que estaba oculto por su propia lógica (cuadros de Last.fm/ListenBrainz) NO reaparece al limpiar
check("los cuadros ocultos por su propia lógica siguen ocultos tras buscar y borrar", d.lastfm_box.isHidden() and d.listenbrainz_box.isHidden())
d._search_input.setText("scrobbling"); settle(0.1); d._search_input.setText(""); settle(0.1)
check("(también tras buscar justo ese grupo)", d.lastfm_box.isHidden() and d.listenbrainz_box.isHidden())
d._search_input.setText("pausa"); settle(0.05)
d._goto_section(1); settle(0.1)
check("pulsar una sección limpia la búsqueda", d._search_input.text() == "" and len(visibles()) == base)
check("puerto y opacidad tienen nombre accesible", d.port_input.accessibleName() == "Puerto de conexión" and d.opacity_slider.accessibleName() == "Opacidad de la ventana")
d.close()

# --- 3) etiqueta de estado adaptable ------------------------------------------------------------------
lab = widgets.ElidedLabel("x"); lab.set_variants(["REPRODUCIENDO", "SONANDO"])
f = lab.font(); fm = widgets.QFontMetrics(f)
lab.resize(fm.horizontalAdvance("REPRODUCIENDO") + 10, 20); lab.show(); settle(0.05)
check("con espacio: se muestra la versión larga", lab.text() == "REPRODUCIENDO")
lab.resize(fm.horizontalAdvance("SONANDO") + 10, 20); settle(0.05)
check("con poco espacio: pasa a la corta (palabra completa, sin «…»)", lab.text() == "SONANDO" and "…" not in lab.text())
check("sin tooltip cuando la corta cabe entera... (el texto largo queda en el tooltip)", lab.toolTip() == "REPRODUCIENDO")
lab.resize(15, 20); settle(0.05)
check("si ni la corta cabe, se recorta con «…»", "…" in lab.text())
lab.resize(300, 20); settle(0.05)
check("al volver a haber espacio recupera la larga", lab.text() == "REPRODUCIENDO")
lab.close()

# --- 4) nombres accesibles ---------------------------------------------------------------------------------
host = QWidget(); sl = QSlider(host); sl.setToolTip("Volumen"); chk = QCheckBox("Algo", host); chk.setToolTip("Explicación")
named = QSlider(host); named.setToolTip("Otro"); named.setAccessibleName("Mío")
widgets.sync_accessible_names(host)
check("deslizador sin nombre toma el tooltip", sl.accessibleName() == "Volumen")
check("casilla con texto conserva el suyo (no se pisa)", chk.accessibleName() == "")
check("un nombre puesto a mano se respeta", named.accessibleName() == "Mío")

# --- 5) color de enlaces --------------------------------------------------------------------------------------------
for scheme in ("default", "cosmos"):
    if scheme == "cosmos" and not hasattr(theme, "set_palette_scheme"): continue
link = app.palette().color(QPalette.ColorRole.Link)
check("enlaces: contraste ≥ 4,5:1 contra el panel (antes 4,0:1)", theme.contrast_ratio((link.red(), link.green(), link.blue()), theme.Palette.BG_PANEL) >= 4.5)
check("el enlace visitado usa el mismo color", app.palette().color(QPalette.ColorRole.LinkVisited) == link)

# --- 6) título en dos líneas con movimiento reducido ---------------------------------------------------------------
theme.apply_accessibility(1.0, False, reduced_motion=True)
t = widgets.MarqueeLabel("Una canción con un título bastante largo para probar el reparto en líneas", max_static_lines=2,
                         font=QFont("DejaVu Sans", 14))
t.resize(220, 24); t.show(); settle(0.1)
check("movimiento reducido + texto largo: se reparte en 2 líneas", len(t._wrapped) == 2)
check("el alto pedido crece con las líneas", t.sizeHint().height() > widgets.QFontMetrics(t._font).height() + 4 and t.minimumHeight() > 24)
t.resize(1000, 24); settle(0.1)
check("si cabe en una línea, vuelve a una sola", t._wrapped == [] and t.minimumHeight() == 0)
t.resize(150, 24); t.setText("Palabra " * 40); settle(0.1)
check("demasiado largo: la última línea se recorta con «…» y se avisa en el tooltip", len(t._wrapped) == 2 and t._wrapped[-1].endswith("…") and t.toolTip() != "")
t.resize(260, 24); t.setText("Una canción con un título bastante largo"); settle(0.1)
check("si se ve entero en 2 líneas no hace falta tooltip", len(t._wrapped) == 2 and not t._wrap_elided and t.toolTip() == "")
sn = widgets.MarqueeLabel("Una canción con un título bastante largo para probar el reparto en líneas", font=QFont("DejaVu Sans", 14))
sn.resize(220, 24); sn.show(); settle(0.1)
check("sin max_static_lines (por defecto 1) se comporta como antes: una línea recortada", sn._wrapped == [])
t.close(); sn.close()
theme.apply_accessibility(1.0, False, reduced_motion=False)
t2 = widgets.MarqueeLabel("Una canción con un título bastante largo para probar el reparto en líneas", max_static_lines=2, font=QFont("DejaVu Sans", 14))
t2.resize(220, 24); t2.show(); settle(0.1)
check("con movimiento normal NO se reparte (se desplaza como siempre)", t2._wrapped == [] and t2._needs_scroll)
t2.close()

# la ventana principal ajusta su alto cuando el título pasa a 2 líneas
theme.apply_accessibility(1.0, False, reduced_motion=True)
w = mw.MainWindow(WNPBackend(), CoverArtLoader(), type("L", (QObject,), {"lyricsReady": pyqtSignal(str, object), "request": lambda *a, **k: None})())
w.show(); w.set_content_width(mw.MIN_WIDTH); w.apply_state(PlayerState(connected=True, player_name="YouTube", state="PLAYING", title="Corto", artist="A", duration="3:00", duration_seconds=180, position_percent=1.0, can_play_pause=True)); settle(0.3)
h1 = w.layout().sizeHint().height()                   # alto que pide el layout con un título corto
w.apply_state(PlayerState(connected=True, player_name="YouTube", state="PLAYING", title="Un título larguísimo que seguro no cabe en una sola línea del reproductor", artist="A", duration="3:00", duration_seconds=180, position_percent=1.0, can_play_pause=True)); settle(0.4)
check("ventana principal: al pasar el título a 2 líneas la ventana crece (%d -> %d px)" % (h1, w.height()), w.height() > h1 and abs(w.height() - w.layout().sizeHint().height()) <= 1)
check("y su estado muestra una palabra completa en la cabecera (REPRODUCIENDO o SONANDO)", w.eyebrow_label.text() in ("REPRODUCIENDO", "SONANDO"))
w.apply_state(PlayerState(connected=True, player_name="YouTube", state="PLAYING", title="Corto", artist="A", duration="3:00", duration_seconds=180, position_percent=1.0, can_play_pause=True)); settle(0.4)
check("y vuelve a su alto al ser corto otra vez (%d px)" % h1, abs(w.height() - h1) <= 2)
w.close()
print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
