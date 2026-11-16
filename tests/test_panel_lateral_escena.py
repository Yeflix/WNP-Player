"""1.5.6: la escena 3D sustituye a la nota musical de las carátulas sin imagen
(CoverArt, VinylCover) y el panel lateral rediseñado (estado, tiempos, alto que
se adapta a la pantalla). Necesita Qt (offscreen)."""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import theme, widgets, welcome_fx
import dock_window as dk
from backend import PlayerState, WNPBackend
from cover_loader import CoverArtLoader

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1
def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)
def grab(w):
    img = QImage(w.size(), QImage.Format.Format_ARGB32); img.fill(0)
    p = QPainter(img); w.render(p); p.end()
    return img
def cover_img():
    img = QImage(64, 64, QImage.Format.Format_ARGB32); img.fill(QColor("#e76f51"))
    return img

theme.REDUCED_MOTION = False

# --- escena (sin widget) -----------------------------------------------------------
check("detalle reducido en huecos chicos", welcome_fx.SoundScene.detail_for(80, 80) == "mini"
      and welcome_fx.SoundScene.detail_for(200, 200) == "full")
img = QImage(120, 120, QImage.Format.Format_ARGB32); img.fill(0)
p = QPainter(img)
welcome_fx.SoundScene("mini").paint(p, img.rect().toRectF(), 1.0, QColor(255, 71, 87), QColor(41, 121, 255))
p.end()
check("la escena pinta algo", any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 120, 6) for y in range(0, 120, 6)))

# --- CoverArt ----------------------------------------------------------------------
c = widgets.CoverArt(size=190); c.show(); pump(0.15)
check("sin imagen: la escena anima", c.scene_running())
a = grab(c); pump(0.25); b = grab(c)
check("y se mueve (dos fotogramas distintos)", a != b)
c.set_image(cover_img()); pump(0.1)
check("con carátula: la escena se para", not c.scene_running())
c.set_image(None); pump(0.05)
check("sin carátula otra vez: vuelve", c.scene_running())
c.set_scene_paused(True)
check("pausa externa: se para", not c.scene_running())
c.set_scene_paused(False)
c.hide(); pump(0.05)
check("oculta: se para", not c.scene_running())
theme.REDUCED_MOTION = True; c.show(); pump(0.05)
check("reducir movimiento: quieta", not c.scene_running())
theme.REDUCED_MOTION = False; c.hide()

# --- VinylCover (modo compacto) --------------------------------------------------------
v = widgets.VinylCover(diameter=76); v.show(); pump(0.1)
check("vinilo sin carátula: escena en la etiqueta", v.scene_running())
v.set_image(cover_img()); pump(0.05)
check("vinilo con carátula: escena parada", not v.scene_running())
v.hide()

# --- panel lateral ---------------------------------------------------------------------
check("alto de la tarjeta: máximo en pantallas altas", dk.DockWindow.card_height_for(1040) == dk.CARD_HEIGHT)
check("alto de la tarjeta: se adapta en pantallas bajas",
      dk.DockWindow.card_height_for(420) == 420 - 2 * dk.CARD_SCREEN_MARGIN)
check("alto de la tarjeta: nunca por debajo del mínimo", dk.DockWindow.card_height_for(200) == dk.CARD_MIN_HEIGHT)

playing = PlayerState(connected=True, player_name="Spotify", state="PLAYING", title="One More Time", artist="Daft Punk",
                      duration="5:20", duration_seconds=320, position="1:02", position_seconds=62, position_percent=19.0,
                      can_play_pause=True, can_next=True, can_prev=True, can_seek=True)
loader = CoverArtLoader()
for style in ("card", "compact"):
    d = dk.DockWindow(WNPBackend(), loader)
    d.set_style(style); d.set_edge("right"); d.show_on_edge(); pump(0.1)
    tag = f"[{style}]"
    art = d.cover if style == "card" else d.cover_small
    check(f"{tag} recogido: la escena de la carátula en pausa", not art.scene_running())
    d._expand(); pump(0.5)
    check(f"{tag} abierto: la escena anima", art.scene_running())
    check(f"{tag} sin nada: 'En espera' y sin tiempos", d.status_text() == "En espera" and d.time_texts() == ("", ""))
    d.apply_state(playing); pump(0.1)
    check(f"{tag} sonando: estado y tiempos", d.status_text() == "Sonando · Spotify" and d.time_texts() == ("1:02", "5:20"))
    content = d._content_zone().toRect()
    items = [art, d.title_label, d.artist_label, d.seek_bar, d.prev_btn, d.play_btn, d.next_btn]
    if style == "compact":
        items.append(d.restore_btn)
    check(f"{tag} todo dentro de la tarjeta", all(content.contains(w.geometry()) for w in items),
          str([(type(w).__name__, w.geometry().getRect()) for w in items if not content.contains(w.geometry())]))
    rects = [w.geometry() for w in items]
    overlap = [(i, j) for i in range(len(rects)) for j in range(i + 1, len(rects)) if rects[i].intersects(rects[j])]
    check(f"{tag} sin solapes", not overlap, str(overlap))
    times = [r.toRect() for r in d._time_rects]
    check(f"{tag} los tiempos no pisan la barra ni los controles",
          not any(t.intersects(w.geometry()) for t in times for w in (d.seek_bar, d.prev_btn, d.play_btn, d.next_btn)))
    if style == "card":
        check(f"{tag} el estado va arriba, sin pisar la carátula", d._chip_rect.bottom() <= art.y())
        check(f"{tag} carátula entre el mínimo y el máximo", dk.CARD_COVER_MIN <= art.width() <= dk.CARD_COVER_SIZE)
    d._collapse(); pump(0.5)
    check(f"{tag} al recogerse vuelve a pausarse", not art.scene_running())
    d.hide(); d.deleteLater(); pump(0.05)

# pantalla baja: la tarjeta encoge y la carátula también, sin que nada se salga
orig = dk.DockWindow._screen_geometry
dk.DockWindow._screen_geometry = lambda self: QRect(0, 0, 1366, 400)
d = dk.DockWindow(WNPBackend(), loader); d.set_style("card"); d.show_on_edge(); pump(0.1)
check("pantalla baja: alto reducido", d.height() == dk.DockWindow.card_height_for(400), str(d.height()))
check("pantalla baja: carátula más chica", d.cover.width() < dk.CARD_COVER_SIZE, str(d.cover.width()))
check("pantalla baja: controles dentro", d._content_zone().toRect().contains(d.play_btn.geometry()))
d.hide(); d.deleteLater()
dk.DockWindow._screen_geometry = orig

print("RESULTADO:", "todo ok" if not fails else f"{fails} fallas")
sys.exit(1 if fails else 0)
