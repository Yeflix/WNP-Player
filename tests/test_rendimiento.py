"""Optimizaciones de rendimiento de 1.3.1: lo cacheado se ve IGUAL que lo dibujado directamente,
las cachés se invalidan cuando toca y los relojes de animación del dock están alineados."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(); os.environ["LOCALAPPDATA"] = os.environ["XDG_CONFIG_HOME"]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap, QFont
from PyQt6.QtCore import QPointF, QRectF, Qt
app = QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
theme.apply_accessibility(1.0, False, reduced_motion=False)
import widgets, dock_window as dw
from theme import Palette

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1
def settle(sec=0.15):
    t0 = time.time()
    while time.time() - t0 < sec: app.processEvents()
def diff(a: QImage, b: QImage) -> float:
    """Diferencia media por canal (0..255) entre dos imágenes del mismo tamaño."""
    a = a.convertToFormat(QImage.Format.Format_ARGB32); b = b.convertToFormat(QImage.Format.Format_ARGB32)
    assert a.size() == b.size(), (a.size(), b.size())
    pa, pb = a.constBits().asstring(a.sizeInBytes()), b.constBits().asstring(b.sizeInBytes())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)
def render(fn, w, h) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32); img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing); fn(p); p.end(); return img
def cover_img(c1="#2a6f97", c2="#e76f51"):
    img = QImage(300, 300, QImage.Format.Format_ARGB32); img.fill(QColor(c1))
    p = QPainter(img); p.setBrush(QColor(c2)); p.drawEllipse(40, 40, 220, 220); p.end(); return img

# --- Marquesina ------------------------------------------------------------------------
m = widgets.MarqueeLabel("Una canción con un título larguísimo que no cabe en el ancho disponible"); m.resize(120, 24); m.show(); settle()
check("la marquesina necesita desplazarse (prueba válida)", m._needs_scroll)
pix = m._text_pixmap(24)
ref = render(lambda p: (p.setFont(m._font), p.setPen(m._color),
                        p.drawText(QRectF(0, 0, m._text_width + m._GAP_PX, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, m._full_text)),
             int(m._text_width + m._GAP_PX), 24)
check("texto cacheado = dibujado directo (dif. media < 1)", diff(pix.toImage(), ref) < 1.0)
check("misma imagen en pasos sucesivos (no se rehace en cada fotograma)", m._text_pixmap(24) is pix)
m.set_color(QColor("#ff0000")); check("cambiar el color invalida la caché", m._text_pixmap(24) is not pix)
pix = m._text_pixmap(24); m.setText("Otro título distinto y también bastante largo para desplazarse sí o sí"); settle()
check("cambiar el texto invalida la caché", m._text_pixmap(24) is not pix)
pix = m._text_pixmap(24); m.setFont(QFont("DejaVu Sans", 14))
check("cambiar la fuente invalida la caché", m._text_pixmap(24) is not pix)
m.hide()

# --- Disco de vinilo -------------------------------------------------------------------
v = widgets.VinylCover(diameter=76); v.show(); settle()
d = 76; side = d + 4
direct = render(lambda p: (p.translate(side / 2, side / 2), v._paint_disc_content(p, d)), side, side)
cached_img = render(lambda p: (p.translate(side / 2, side / 2), v._draw_cached_disc(p, d)), side, side)
check("disco sin carátula: caché = directo (dif. media < 1)", diff(direct, cached_img) < 1.0)
pm = QPixmap.fromImage(cover_img()); v.set_label_pixmap(pm) if hasattr(v, "set_label_pixmap") else None
key1 = v._disc_key
v._label_pixmap = pm; v._prev_label_pixmap = None; v._fade_progress = 1.0
direct = render(lambda p: (p.translate(side / 2, side / 2), v._paint_disc_content(p, d)), side, side)
cached_img = render(lambda p: (p.translate(side / 2, side / 2), v._draw_cached_disc(p, d)), side, side)
check("disco con carátula: caché = directo (dif. media < 1)", diff(direct, cached_img) < 1.0)
check("al cambiar la carátula se rehace el disco", v._disc_key != key1)
cache = v._disc_cache; render(lambda p: (p.translate(side / 2, side / 2), v._draw_cached_disc(p, d)), side, side)
check("sin cambios, el disco se reutiliza", v._disc_cache is cache)
v._prev_label_pixmap = pm; v._fade_progress = 0.5
_img = QImage(4, 4, QImage.Format.Format_ARGB32); _p = QPainter(_img); _res = v._draw_cached_disc(_p, d); _p.end()
check("durante el fundido NO se usa la caché (se dibuja normal)", _res is False)
v._prev_label_pixmap = None; v._fade_progress = 1.0
v.set_diameter(90); settle(); render(lambda p: (p.translate(50, 50), v._draw_cached_disc(p, 90)), 100, 100)
check("al cambiar el diámetro se rehace", v._disc_key[0] == 90)
v.hide()

# --- Carátula -----------------------------------------------------------------------------
c = widgets.CoverArt(size=190); c.set_image(cover_img()); c.show(); settle(0.4)
rect = QRectF(0, 0, 190, 190)
from PyQt6.QtGui import QPainterPath
clip = QPainterPath(); clip.addRoundedRect(rect, 190 * c._radius_ratio, 190 * c._radius_ratio)
direct = render(lambda p: (p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform), c._paint_content(p, rect, clip)), 190, 190)
cache = c._content_cache(rect, clip)
check("carátula: caché = directo (dif. media < 1)", cache is not None and diff(cache.toImage(), direct) < 1.0)
check("la carátula cacheada se reutiliza", c._content_cache(rect, clip) is cache)
c.set_image(cover_img("#264653", "#e9c46a")); settle(0.5)
check("al cambiar la imagen se rehace", c._content_cache(rect, clip) is not cache)
# el borde que «respira» solo repinta cuando cambia su transparencia entera
c._glow_alpha = -1; c.set_glow_intensity(0.5); settle(0.1)
paints = []
orig = c.paintEvent
def contar(ev):
    paints.append(1); orig(ev)
c.paintEvent = contar
base = c._glow_intensity
for i in range(1, 9): c.set_glow_intensity(base + i * 0.0021); settle(0.02)       # 8 variaciones diminutas
check("variaciones que no cambian el borde NO repintan (8 cambios -> ≤ 2 pinturas)", len(paints) <= 2)
paints.clear(); c.set_glow_intensity(0.95); settle(0.1)
check("un cambio visible sí repinta", len(paints) >= 1)
c.hide()

# --- Dock: círculo de la pestaña y ondas ----------------------------------------------------
check("la animación del círculo se repite exactamente cada 3,3 s (ondas y latido son múltiplos de 0,55)",
      abs(dw._WaveDot.PERIOD_S * 2 - dw._WaveDot.LOOP_S) < 1e-9 and abs(dw._WaveDot.BREATH_S * 3 - dw._WaveDot.LOOP_S) < 1e-9)
from backend import WNPBackend, PlayerState
from cover_loader import CoverArtLoader
from PyQt6.QtCore import QObject, pyqtSignal
class L(QObject):
    lyricsReady = pyqtSignal(str, object)
    def request(self, *a, **k): pass
dock = dw.DockWindow(WNPBackend(), CoverArtLoader(), lyrics_loader=L())
dock.show(); dock.apply_state(PlayerState(connected=True, player_name="YouTube", state="PLAYING", title="T", artist="A", duration="3:00",
                                           duration_seconds=180, position_percent=10.0, can_play_pause=True)); settle(0.5)
dot = dock.handle_icon
check("círculo y ondas corren a la vez y con el mismo intervalo (se repintan juntos)",
      dot._timer.isActive() and dock._ripple_timer.isActive() and dot._timer.interval() == dock._ripple_timer.interval() == 33)
now = 1.3
cached = dot._frames.get(int(now / dot.LOOP_S * dot.FRAMES)) or dot._frame()
idx = [i for i, p in dot._frames.items()][0]
direct = render(lambda p: dot._paint_frame(p, idx * dot.LOOP_S / dot.FRAMES), dot.width(), dot.height())
check("fotograma del círculo cacheado = dibujado directo (dif. media < 1)", diff(dot._frames[idx].toImage(), direct) < 1.0)
n = len(dot._frames); dot._frame(); dot._frame()
check("la caché del círculo está acotada a 99 fotogramas", len(dot._frames) <= dot.FRAMES)
dot.set_accent(QColor("#00ff88"), QColor("#8800ff")); dot._frame()
check("cambiar los colores descarta los fotogramas viejos", len(dot._frames) <= 2)
rect = dock._ripple_rect()
dock._ripple_frames.clear(); dock._ripple_key = None
pix_img = render(lambda p: dock._paint_ripples(p), dock.width(), dock.height())
idx = next(iter(dock._ripple_frames))
direct = render(lambda p: dock._paint_ripples_at(p, idx / dock.RIPPLE_FRAMES), dock.width(), dock.height())
check("ondas cacheadas = dibujadas directamente (dif. media < 1)", diff(dock._ripple_frames[idx].toImage(), render(lambda p: (p.translate(-rect.x(), -rect.y()), dock._paint_ripples_at(p, idx / dock.RIPPLE_FRAMES)), rect.width(), rect.height())) < 1.0)
dock.hide(); settle(0.1)
check("con la ventana oculta no corre ningún temporizador de animación", not dot._timer.isActive() and not dock._ripple_timer.isActive())

print(f"RESULTADO: {fails and 'FALLAS ' + str(fails) or 'todo ok'}")
sys.exit(1 if fails else 0)
