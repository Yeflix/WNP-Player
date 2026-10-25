"""
Paleta de colores y utilidades visuales.
Inspirada en la skin de Rainmeter "NeonTube" (paleta Neon Pulse: rojo -> azul).
"""
import colorsys
import os
import re
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage

# ---------------------------------------------------------------- accesibilidad
# Dos escalas de letra distintas, a pedido:
#   - DEFAULT_FONT_SCALE: fija, "grande", para TODO menos el reproductor
#     completo (diálogos, modo compacto/vinilo, bienvenida, aviso semanal).
#     No es configurable — siempre grande.
#   - FONT_SCALE: la única configurable desde Configuración, y solo afecta
#     al reproductor completo (MainWindow). Se fija UNA sola vez al
#     arrancar (ver apply_accessibility, llamado desde app_controller.py
#     antes de construir cualquier ventana) — cambiarla pide reiniciar la
#     app, no se recalcula en caliente.
#
# Técnica para que el texto escale sin tocar cada lugar que arma su propio
# "font-size: Npx" en un f-string: parchar QWidget.setStyleSheet una sola
# vez para que reescale cualquier "font-size" que pase por ahí. Los pocos
# widgets del reproductor completo que necesitan la escala CONFIGURABLE en
# vez de la fija se marcan con mark_configurable_scale(widget) — ya
# resuelven su propio tamaño con font_px() antes de llamar a
# setStyleSheet, así que el parche los deja pasar tal cual (si no, se
# escalarían dos veces). MarqueeLabel (título/artista) no usa QSS sino
# QFont directo, así que esos puntos piden el tamaño ya escalado
# directamente a font_px().
DEFAULT_FONT_SCALE = 1.15   # "grande" fijo, para todo menos el reproductor
FONT_SCALE = 1.0            # configurable, solo para MainWindow (ver font_px)

_FONT_SIZE_RE = re.compile(r'font-size:\s*([\d.]+)px')


def font_px(base: float) -> int:
    """Tamaño en puntos ya escalado con la escala CONFIGURABLE (solo la
    usa el reproductor completo) — para QFont directo (MarqueeLabel de
    título/artista) o para armar un f-string ya escalado a mano (ver
    mark_configurable_scale)."""
    return max(6, round(base * FONT_SCALE))


def mark_configurable_scale(widget):
    """El reproductor completo arma sus propios tamaños ya escalados con
    font_px() (la escala CONFIGURABLE), en vez de dejar que el parche
    global les aplique la escala fija de todos los demás — sin esto,
    quedarían escalados dos veces. Se llama una vez, justo después de
    crear el widget (antes de la primera vez que alguien le llame
    setStyleSheet)."""
    widget._wnp_configurable_scale = True
    return widget


def _install_font_scale_patch():
    """Se instala una sola vez, la primera vez que se importa este módulo
    (que es casi lo primero que se importa en toda la app). A partir de
    ahí, CUALQUIER widget.setStyleSheet(...) de la aplicación reescala
    automáticamente su 'font-size' con DEFAULT_FONT_SCALE (grande, fijo)
    — salvo los pocos widgets del reproductor marcados con
    mark_configurable_scale(), que ya vienen pre-escalados y se dejan
    pasar tal cual."""
    from PyQt6.QtWidgets import QWidget
    if getattr(QWidget, "_wnp_font_scale_patched", False):
        return
    original = QWidget.setStyleSheet

    def patched(self, css):
        if css and not getattr(self, "_wnp_configurable_scale", False) and DEFAULT_FONT_SCALE != 1.0:
            css = _FONT_SIZE_RE.sub(
                lambda m: f"font-size: {round(float(m.group(1)) * DEFAULT_FONT_SCALE, 1)}px",
                css,
            )
        original(self, css)

    QWidget.setStyleSheet = patched
    QWidget._wnp_font_scale_patched = True


_install_font_scale_patch()


class Palette:
    BG_BASE = (12, 13, 20)
    BG_PANEL = (32, 32, 46)
    ACCENT_A = (255, 71, 87)     # rojo neón
    ACCENT_B = (41, 121, 255)    # azul neón
    # Contraste medido (WCAG 2.x) contra BG_BASE / BG_PANEL:
    #   TEXT       16.5 / 13.7      TEXT_DIM   8.5 / 7.0      TEXT_FAINT 5.9 / 4.9
    # Antes TEXT_FAINT era (104,104,124) = 3.6 / 2.9 (no llegaba a AA 4.5:1) y
    # se usaba en texto chico (etiqueta de estado, plataforma, letra inactiva,
    # "hace X min"). Se subió TEXT_DIM en paralelo para conservar la jerarquía.
    TEXT = (236, 236, 242)
    TEXT_DIM = (170, 170, 188)
    TEXT_FAINT = (140, 140, 160)
    # Fondo de los botones "de acento" con texto blanco (dialogButtonAccent):
    # el rojo neón puro daba 3.3:1 con texto blanco; este da 5.3:1.
    ACCENT_BUTTON = (208, 36, 56)
    ACCENT_BUTTON_HOVER = (222, 44, 66)
    OK = (46, 213, 115)
    ERROR = (255, 99, 99)
    # Fondos de menús y tooltips (antes escritos a mano dentro del QSS global)
    MENU_BG = (22, 23, 32)
    TOOLTIP_BG = (24, 25, 34)
    # Valores que toma el modo "alto contraste" (ver apply_accessibility)
    BG_PANEL_HC = (46, 46, 63)
    TEXT_DIM_HC = (204, 204, 216)
    TEXT_FAINT_HC = (176, 176, 192)

    @staticmethod
    def c(rgb, alpha=255):
        r, g, b = rgb
        return QColor(r, g, b, alpha)

    @staticmethod
    def rgba(rgb, alpha: int) -> str:
        """'rgba(r,g,b,a)' para QSS (alpha 0-255) con el color dado."""
        return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha})"


# ------------------------------------------------------------ aspecto (temas)
# El aspecto del reproductor se elige en Configuración y se fija UNA sola vez
# al arrancar (set_player_theme, llamado desde main.py antes de importar el
# resto de la app): los colores se "hornean" en el QSS de cada widget al
# crearlo, igual que el tamaño de letra, así que cambiarlo pide reiniciar.
#   "default": el aspecto de siempre (rojo -> azul neón, equivale al modo
#              YefriDev del tema de Spotify).
#   "cosmos":  el modo Cosmos del tema "Switch" de Spicetify (índigo profundo,
#              violeta #a78bfa y celeste #7dd3fc, cielo estrellado).
# Contrastes medidos (WCAG 2.x), Cosmos: TEXT 18.3/16.3, TEXT_DIM 10.8/9.6,
# TEXT_FAINT 7.5/6.7 contra BG_BASE/BG_PANEL (y >= 4.8 incluso sobre la parte
# más clara de la nebulosa); botón de acento con texto blanco 5.3:1.
PLAYER_THEMES = {
    "default": {},   # se rellena abajo con los valores originales de Palette
    "cosmos": {
        "BG_BASE": (7, 6, 24),
        "BG_PANEL": (21, 18, 58),
        "ACCENT_A": (167, 139, 250),
        "ACCENT_B": (125, 211, 252),
        "TEXT": (246, 243, 255),
        "TEXT_DIM": (190, 187, 220),
        "TEXT_FAINT": (158, 154, 194),
        "ACCENT_BUTTON": (124, 77, 222),
        "ACCENT_BUTTON_HOVER": (134, 88, 228),
        "MENU_BG": (16, 14, 44),
        "TOOLTIP_BG": (21, 18, 58),
        "BG_PANEL_HC": (34, 30, 82),
        "TEXT_DIM_HC": (214, 212, 236),
        "TEXT_FAINT_HC": (186, 183, 214),
    },
}
PLAYER_THEMES["default"] = {k: getattr(Palette, k) for k in PLAYER_THEMES["cosmos"]}
PLAYER_THEME = "default"


def set_player_theme(name: str) -> str:
    """Aplica un aspecto a Palette. Llamar antes de importar app_controller
    (accent.py lee Palette al importarse). Un nombre desconocido deja el
    aspecto predeterminado. Devuelve el aspecto realmente aplicado."""
    global PLAYER_THEME
    name = name if name in PLAYER_THEMES else "default"
    for key, value in PLAYER_THEMES[name].items():
        setattr(Palette, key, value)
    PLAYER_THEME = name
    return name


def is_cosmos() -> bool:
    return PLAYER_THEME == "cosmos"


def apply_accessibility(font_scale: float = 1.0, high_contrast: bool = False,
                        reduced_motion: bool | None = None):
    """Llamar UNA sola vez al arrancar, antes de construir cualquier
    ventana (ver app_controller.py). font_scale es la escala CONFIGURABLE
    (solo afecta al reproductor completo — todo lo demás ya usa
    DEFAULT_FONT_SCALE fijo, "grande", sin pasar por acá). Alto contraste
    sube el brillo de los grises secundarios (TEXT_DIM/TEXT_FAINT) y
    aclara un poco los paneles, para que el texto secundario (artista,
    tiempos, subtítulos de diálogos) se lea mejor sin cambiar la paleta de
    acento del tema — este sí aplica a TODA la app, reproductor incluido."""
    global FONT_SCALE, REDUCED_MOTION
    FONT_SCALE = max(0.8, min(1.6, font_scale))
    # Alto contraste: se respeta el ajuste propio de la app Y el de Windows
    # (Configuración > Accesibilidad > Contraste). Movimiento reducido: por
    # defecto se lee de Windows ("Efectos de animación" desactivado) o de la
    # variable de entorno WNP_REDUCE_MOTION=1 (útil para probar fuera de Windows).
    high_contrast = bool(high_contrast) or system_high_contrast()
    REDUCED_MOTION = system_prefers_reduced_motion() if reduced_motion is None else bool(reduced_motion)
    if high_contrast:
        Palette.TEXT_DIM = Palette.TEXT_DIM_HC
        Palette.TEXT_FAINT = Palette.TEXT_FAINT_HC
        Palette.BG_PANEL = Palette.BG_PANEL_HC
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            apply_dark_palette(app)
            app.setStyleSheet(build_global_qss())
    except Exception:
        pass


# ------------------------------------------------------------ movimiento reducido
# Cuando está activo (preferencia del sistema), las animaciones DECORATIVAS se
# apagan: transiciones de propiedad (duración 0, ver parche de
# QPropertyAnimation.setDuration más abajo), halo que "respira", vinilo que
# gira y marquesina (el texto largo se recorta con "…" y queda completo en el
# tooltip). Lo informativo (barra de progreso, letra) sigue funcionando.
REDUCED_MOTION = False


def system_prefers_reduced_motion() -> bool:
    if os.environ.get("WNP_REDUCE_MOTION", "").strip() in ("1", "true", "yes"):
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        SPI_GETCLIENTAREAANIMATION = 0x1042
        flag = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0)
        return bool(ok) and not flag.value
    except Exception:
        return False


def system_high_contrast() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        class HIGHCONTRASTW(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                        ("lpszDefaultScheme", ctypes.c_wchar_p)]

        SPI_GETHIGHCONTRAST, HCF_HIGHCONTRASTON = 0x0042, 0x1
        hc = HIGHCONTRASTW()
        hc.cbSize = ctypes.sizeof(HIGHCONTRASTW)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0)
        return bool(ok) and bool(hc.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        return False


def _install_reduced_motion_patch():
    """Mismo patrón que _install_font_scale_patch: un único parche global en
    vez de tocar cada QPropertyAnimation. Con movimiento reducido toda
    animación de propiedad dura 0 ms (llega al valor final al instante y sigue
    emitiendo finished, así que la lógica que depende de eso no se rompe)."""
    from PyQt6.QtCore import QPropertyAnimation, QVariantAnimation
    if getattr(QPropertyAnimation, "_wnp_motion_patched", False):
        return

    def patched(self, msecs):
        QVariantAnimation.setDuration(self, 0 if REDUCED_MOTION else msecs)

    QPropertyAnimation.setDuration = patched
    QPropertyAnimation._wnp_motion_patched = True


_install_reduced_motion_patch()


def scale_font_sizes(css: str, scale: float | None = None) -> str:
    """Aplica la misma escala de letra que el parche de setStyleSheet a una
    hoja de estilo suelta. Necesario para GLOBAL_QSS: QApplication.setStyleSheet
    NO pasa por QWidget.setStyleSheet, así que menús, tooltips, casillas y
    campos de texto se quedaban en 11-12px mientras todo lo demás iba a x1.15."""
    scale = DEFAULT_FONT_SCALE if scale is None else scale
    if scale == 1.0:
        return css
    return _FONT_SIZE_RE.sub(
        lambda m: f"font-size: {round(float(m.group(1)) * scale, 1)}px", css)


# ------------------------------------------------------------------- contraste
def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a, b) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def blend_over(fg, bg, alpha: float) -> tuple:
    """Color resultante de pintar fg con opacidad alpha (0..1) sobre bg."""
    return tuple(round(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def ensure_contrast(fg, bg, minimum: float = 4.5) -> tuple:
    """Devuelve fg, o el color más cercano a fg (mismo tono) que alcance el
    contraste mínimo contra bg. Aclara si bg es oscuro y oscurece si es claro.
    Sirve para usar el color de acento dinámico como TEXTO: el acento sale de
    la carátula y en el peor caso (azul oscuro) daba 1.8:1 contra el fondo."""
    fg = tuple(int(x) for x in fg[:3])
    if contrast_ratio(fg, bg) >= minimum:
        return fg
    h, l, s = colorsys.rgb_to_hls(fg[0] / 255, fg[1] / 255, fg[2] / 255)
    lighten = relative_luminance(bg) < 0.5
    step = 0.02 if lighten else -0.02
    best = fg
    for _ in range(50):
        l = min(1.0, max(0.0, l + step))
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        best = (round(r * 255), round(g * 255), round(b * 255))
        if contrast_ratio(best, bg) >= minimum or l in (0.0, 1.0):
            break
    return best


def on_color(*backgrounds, light=(255, 255, 255), dark=(12, 13, 20)) -> tuple:
    """Blanco u oscuro, el que se lea mejor sobre TODOS los fondos dados (se
    compara el peor caso). Para el ícono del botón de play, que se pinta sobre
    un degradado de acento: con acentos amarillos/lima el blanco fijo daba
    1.4:1 y el ícono prácticamente desaparecía."""
    worst_light = min(contrast_ratio(light, bg) for bg in backgrounds)
    worst_dark = min(contrast_ratio(dark, bg) for bg in backgrounds)
    # Un ícono es un componente gráfico: WCAG 1.4.11 pide 3:1, no 4.5:1. Se
    # conserva el blanco (identidad visual de la app, y lo esperado sobre el
    # degradado rojo->azul por defecto: 3.3:1 / 4.0:1) mientras llegue a 3:1;
    # solo se pasa a oscuro cuando el blanco deja de verse (amarillos, limas).
    if worst_light >= 3.0:
        return light
    return light if worst_light >= worst_dark else dark


def brightest_cell_rgb(image: QImage, grid: int = 6) -> tuple:
    """Color de la zona más luminosa de la imagen (promedio por celda en una
    grilla grid x grid). Se usa para dimensionar el velo oscuro que se pone
    encima de una carátula: hay que garantizar el texto sobre la parte MÁS
    clara, no sobre el promedio."""
    small = image.scaled(grid, grid, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_RGB32)
    best, best_l = (0, 0, 0), -1.0
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            rgb = (c.red(), c.green(), c.blue())
            lum = relative_luminance(rgb)
            if lum > best_l:
                best, best_l = rgb, lum
    return best


def scrim_alpha_for(image, fg=None, scrim=(8, 8, 14), minimum: float = 4.5,
                    lo: int = 120, hi: int = 235) -> int:
    """Alpha (0-255) MÍNIMO del velo oscuro para que el texto fg alcance el
    contraste mínimo sobre la parte más clara de la carátula. Carátulas
    oscuras conservan el velo original (lo); las muy claras reciben más."""
    if image is None or image.isNull():
        return lo
    fg = Palette.TEXT_DIM if fg is None else fg
    cell = brightest_cell_rgb(image)
    for a in range(lo, hi + 1, 5):
        if contrast_ratio(fg, blend_over(scrim, cell, a / 255.0)) >= minimum:
            return a
    return hi


def font(family="Segoe UI", size=10, bold=False, weight=None):
    f = QFont(family, size)
    if weight is not None:
        f.setWeight(weight)
    f.setBold(bold)
    return f


# Fuentes reutilizables
FONT_DISPLAY = "Segoe UI Semibold"
FONT_BODY = "Segoe UI"
FONT_MONO = "Consolas"
FONT_FALLBACK = "Segoe UI"

# Hoja de estilo global (QSS) para widgets estándar de Qt (sliders, tooltips, menús...)
def _global_qss_source() -> str:
    return f"""
QToolTip {{
    background-color: rgb{Palette.TOOLTIP_BG};
    color: rgb{Palette.TEXT};
    border: 1px solid rgba(255,255,255,30);
    padding: 4px 8px;
    border-radius: 6px;
    font-family: '{FONT_BODY}';
    font-size: 11px;
}}

QMenu {{
    background-color: rgb{Palette.MENU_BG};
    color: rgb{Palette.TEXT};
    border: 1px solid rgba(255,255,255,25);
    border-radius: 10px;
    padding: 6px;
    font-family: '{FONT_BODY}';
    font-size: 12px;
}}
QMenu::item {{
    padding: 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {Palette.rgba(Palette.ACCENT_A, 45)};
}}
QMenu::separator {{
    height: 1px;
    background: rgba(255,255,255,20);
    margin: 6px 4px;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(255,255,255,25);
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgb{Palette.ACCENT_A}, stop:1 rgb{Palette.ACCENT_B});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: rgb{Palette.TEXT};
    width: 11px;
    height: 11px;
    margin: -4px 0;
    border-radius: 5px;
}}
QSlider::groove:horizontal:disabled {{
    background: rgba(255,255,255,12);
}}
QSlider::sub-page:horizontal:disabled {{
    background: rgba(255,255,255,30);
}}
QSlider::handle:horizontal:disabled {{
    background: rgba(255,255,255,70);
}}

QLineEdit {{
    background-color: rgba(255,255,255,12);
    color: rgb{Palette.TEXT};
    border: 1px solid rgba(255,255,255,30);
    border-radius: 8px;
    padding: 6px 10px;
    font-family: '{FONT_MONO}';
    font-size: 12px;
}}
QLineEdit:focus {{
    border: 1px solid rgb{Palette.ACCENT_A};
}}

/* Listas desplegables. Antes NO tenían estilo: el texto y, sobre todo, la
   lista emergente heredaban los colores del tema de Windows (claro/oscuro)
   y quedaban negro sobre negro, con solo la opción resaltada legible. */
QComboBox {{
    background-color: rgba(255,255,255,14);
    color: rgb{Palette.TEXT};
    border: 1px solid rgba(255,255,255,40);
    border-radius: 8px;
    padding: 6px 8px 6px 10px;   /* el área de la flecha (26px) se descuenta aparte */
    min-height: 20px;
    font-family: '{FONT_BODY}';
    font-size: 12px;
}}
QComboBox:hover {{
    border: 1px solid rgba(255,255,255,80);
    background-color: rgba(255,255,255,20);
}}
QComboBox:focus, QComboBox:on {{
    border: 1px solid rgb{Palette.TEXT};
}}
QComboBox:disabled {{
    color: rgb{Palette.TEXT_FAINT};
    border: 1px solid rgba(255,255,255,20);
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: none;   /* la flecha la dibuja widgets.ArrowComboBox */
    width: 0px;
    height: 0px;
}}
QComboBox QAbstractItemView {{
    background-color: rgb{Palette.BG_PANEL};
    color: rgb{Palette.TEXT};
    border: 1px solid rgba(255,255,255,45);
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: rgb{Palette.ACCENT_BUTTON};
    selection-color: white;
    font-family: '{FONT_BODY}';
    font-size: 12px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 26px;
    padding: 2px 8px;
    border-radius: 6px;
    color: rgb{Palette.TEXT};
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: rgba(255,255,255,26);
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: rgb{Palette.ACCENT_BUTTON};
    color: white;
}}

QPlainTextEdit {{
    background-color: rgba(255,255,255,8);
    color: rgb{Palette.TEXT_DIM};
    border: 1px solid rgba(255,255,255,25);
    border-radius: 8px;
    padding: 8px;
    font-family: '{FONT_MONO}';
    font-size: 10.5px;
    selection-background-color: {Palette.rgba(Palette.ACCENT_A, 90)};
}}

QCheckBox {{
    color: rgb{Palette.TEXT};
    font-family: '{FONT_BODY}';
    font-size: 12px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,50);
    background-color: rgba(255,255,255,10);
}}
QCheckBox::indicator:checked {{
    background-color: rgb{Palette.ACCENT_A};
    border: 1px solid rgb{Palette.ACCENT_A};
}}

QPushButton#hotkeyCapture {{
    background-color: rgba(255,255,255,10);
    color: rgb{Palette.TEXT_DIM};
    border: 1px dashed rgba(255,255,255,45);
    border-radius: 8px;
    padding: 8px 12px;
    font-family: '{FONT_MONO}';
    font-size: 12px;
    text-align: left;
}}
QPushButton#hotkeyCapture:hover {{
    border: 1px dashed rgb{Palette.ACCENT_A};
    color: rgb{Palette.TEXT};
}}
QPushButton#hotkeyCaptureActive {{
    background-color: {Palette.rgba(Palette.ACCENT_A, 25)};
    color: rgb{Palette.TEXT};
    border: 1px solid rgb{Palette.ACCENT_A};
    border-radius: 8px;
    padding: 8px 12px;
    font-family: '{FONT_MONO}';
    font-size: 12px;
    text-align: left;
}}

QPushButton#dialogButton {{
    background-color: rgba(255,255,255,14);
    color: rgb{Palette.TEXT};
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-family: '{FONT_BODY}';
    font-weight: 600;
}}
QPushButton#dialogButton:hover {{
    background-color: rgba(255,255,255,24);
}}
QPushButton#dialogButtonAccent {{
    background-color: rgb{Palette.ACCENT_BUTTON};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-family: '{FONT_BODY}';
    font-weight: 600;
}}
QPushButton#dialogButtonAccent:hover {{
    background-color: rgb{Palette.ACCENT_BUTTON_HOVER};
}}
/* Anillo de foco visible para teclado en botones estándar de Qt. */
QPushButton:focus {{
    border: 2px solid rgb{Palette.TEXT};
}}
QCheckBox:focus {{
    color: white;
}}
QCheckBox::indicator:focus {{
    border: 2px solid rgb{Palette.TEXT};
}}

/* Scrollbar delgada y flotante (estilo moderno tipo macOS/apps actuales)
   en vez de la barra gris con flechas por defecto de Qt. Se usa en todos
   los QScrollArea de la app (historial, letra...). */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 1px 4px 0px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,40);
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255,255,255,70);
}}
QScrollBar::handle:vertical:pressed {{
    background: rgb{Palette.ACCENT_A};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
    border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px 4px 1px 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,40);
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(255,255,255,70);
}}
QScrollBar::handle:horizontal:pressed {{
    background: rgb{Palette.ACCENT_A};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    background: none;
    border: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""


def apply_dark_palette(app) -> None:
    """Paleta oscura explícita para TODA la app. El QSS cubre los widgets que
    la app estiliza, pero cualquier widget sin regla propia (listas emergentes,
    menús contextuales de los campos de texto, diálogos nativos) toma sus
    colores del tema de Windows: con Windows en modo claro u oscuro eso daba
    texto oscuro sobre fondo oscuro. Con una paleta fija, la app se ve igual
    sin importar el tema del sistema."""
    from PyQt6.QtGui import QPalette
    from PyQt6.QtCore import Qt as _Qt
    try:  # Qt >= 6.8: además le decimos al estilo nativo que use su variante oscura
        app.styleHints().setColorScheme(_Qt.ColorScheme.Dark)
    except Exception:
        pass
    C = QColor
    pal = QPalette()
    R = QPalette.ColorRole
    G = QPalette.ColorGroup
    roles = {
        R.Window: Palette.BG_BASE, R.WindowText: Palette.TEXT,
        R.Base: Palette.BG_PANEL, R.AlternateBase: Palette.BG_BASE,
        R.Text: Palette.TEXT, R.Button: Palette.BG_PANEL, R.ButtonText: Palette.TEXT,
        R.ToolTipBase: Palette.BG_PANEL, R.ToolTipText: Palette.TEXT,
        R.Highlight: Palette.ACCENT_BUTTON, R.HighlightedText: (255, 255, 255),
        R.Link: Palette.ACCENT_B, R.BrightText: (255, 255, 255),
        R.PlaceholderText: Palette.TEXT_FAINT,
    }
    for role, rgb in roles.items():
        pal.setColor(role, C(*rgb))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(G.Disabled, role, C(*Palette.TEXT_FAINT))
    app.setPalette(pal)


def build_global_qss() -> str:
    """Hoja de estilo global ya con la escala de letra fija aplicada. Se
    reconstruye desde apply_accessibility() para que el alto contraste (que
    cambia Palette DESPUÉS de importar este módulo) llegue también a los
    widgets estándar; antes GLOBAL_QSS se armaba una sola vez al importar."""
    return scale_font_sizes(_global_qss_source())


GLOBAL_QSS = build_global_qss()  # compatibilidad con main.py original
