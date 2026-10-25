"""Aspecto Cosmos del reproductor (Qt offscreen).

    QT_QPA_PLATFORM=offscreen python tests/test_cosmos.py

Comprueba: cambio de aspecto sin efectos secundarios, contrastes de la paleta
(incluida la parte más clara de la nebulosa), que el aspecto predeterminado no
cambia, el fondo estrellado, las estrellas fugaces (cuándo se permiten) y el
selector de Configuración.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

import theme
from theme import Palette
from PyQt6.QtCore import QObject, pyqtSignal


class _Lyrics(QObject):
    lyricsReady = pyqtSignal(str, object)
    def request(self, *a, **k): pass


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)


def make_window():
    from backend import WNPBackend, PlayerState
    from cover_loader import CoverArtLoader
    import main_window as mw
    w = mw.MainWindow(WNPBackend(), CoverArtLoader(), _Lyrics())
    w.show()
    w.apply_state(PlayerState(connected=True, state="PLAYING", title="t", artist="a", duration_seconds=100,
                              position_seconds=10, position_percent=10.0, can_play_pause=True))
    pump(0.15)
    return w


print("== Cambio de aspecto")
default_values = {k: getattr(Palette, k) for k in theme.PLAYER_THEMES["cosmos"]}
check("arranca en el aspecto predeterminado", theme.PLAYER_THEME == "default" and not theme.is_cosmos())
check("rojo -> azul neón de siempre", Palette.ACCENT_A == (255, 71, 87) and Palette.ACCENT_B == (41, 121, 255))
qss_default = theme.build_global_qss()
check("QSS predeterminado conserva menús/tooltips de siempre",
      "rgb(22, 23, 32)" in qss_default and "rgb(24, 25, 34)" in qss_default and "rgba(255,71,87,45)" in qss_default)
check("nombre desconocido -> predeterminado", theme.set_player_theme("no-existe") == "default" and not theme.is_cosmos())
check("cosmos se aplica", theme.set_player_theme("cosmos") == "cosmos" and theme.is_cosmos()
      and Palette.ACCENT_A == (167, 139, 250) and Palette.ACCENT_B == (125, 211, 252))
qss_cosmos = theme.build_global_qss()
check("QSS Cosmos no deja rojo suelto", "255,71,87" not in qss_cosmos and "255, 71, 87" not in qss_cosmos)
check("volver al predeterminado restaura TODOS los valores",
      theme.set_player_theme("default") == "default"
      and all(getattr(Palette, k) == v for k, v in default_values.items())
      and theme.build_global_qss() == qss_default)

print("== Contraste de la paleta Cosmos (WCAG)")
theme.set_player_theme("cosmos")
cr = theme.contrast_ratio
nebula = theme.blend_over(Palette.ACCENT_A, Palette.BG_BASE, 0.20)   # parte más clara del cielo
nebula_panel = theme.blend_over(Palette.ACCENT_A, Palette.BG_PANEL, 0.20)
for label, fg in (("TEXT", Palette.TEXT), ("TEXT_DIM", Palette.TEXT_DIM), ("TEXT_FAINT", Palette.TEXT_FAINT)):
    worst = min(cr(fg, bg) for bg in (Palette.BG_BASE, Palette.BG_PANEL, nebula, nebula_panel))
    check(f"{label} >= 4.5 sobre fondo, panel y nebulosa", worst >= 4.5, f"peor caso {worst:.2f}")
check("blanco sobre ACCENT_BUTTON >= 4.5", cr((255, 255, 255), Palette.ACCENT_BUTTON) >= 4.5,
      f"{cr((255, 255, 255), Palette.ACCENT_BUTTON):.2f}")
check("blanco sobre ACCENT_BUTTON_HOVER >= 4.5", cr((255, 255, 255), Palette.ACCENT_BUTTON_HOVER) >= 4.5,
      f"{cr((255, 255, 255), Palette.ACCENT_BUTTON_HOVER):.2f}")
ic = theme.on_color(Palette.ACCENT_A, Palette.ACCENT_B)
check("icono sobre el degradado violeta->celeste >= 4.5",
      min(cr(ic, Palette.ACCENT_A), cr(ic, Palette.ACCENT_B)) >= 4.5, f"{ic}")
theme.apply_accessibility(1.0, True)
check("alto contraste: TEXT_DIM/FAINT suben y el panel se aclara",
      Palette.TEXT_DIM == Palette.TEXT_DIM_HC and Palette.TEXT_FAINT == Palette.TEXT_FAINT_HC
      and Palette.BG_PANEL == Palette.BG_PANEL_HC)
check("alto contraste: TEXT_FAINT >= 4.5 sobre su panel", cr(Palette.TEXT_FAINT, Palette.BG_PANEL) >= 4.5,
      f"{cr(Palette.TEXT_FAINT, Palette.BG_PANEL):.2f}")
theme.apply_accessibility(1.0, False)
theme.set_player_theme("default")
theme.apply_accessibility(1.0, True)
check("alto contraste en el predeterminado sigue igual (176,176,192)", Palette.TEXT_FAINT == (176, 176, 192))
theme.apply_accessibility(1.0, False)

print("== Ventana principal")
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
w = make_window()
check("predeterminado: sin cielo ni estrellas", w._sky is None and w._stars is None)
check("predeterminado: flechas de letra con el color de siempre", not w.lyrics_left_arrow._glyph_on_accent)
img_default = w.grab().toImage()
w.hide(); w.deleteLater()

theme.set_player_theme("cosmos")
theme.apply_dark_palette(app); app.setStyleSheet(theme.build_global_qss())
import cosmos_sky
w = make_window()
check("cosmos: tiene cielo y estrellas fugaces", w._sky is not None and w._stars is not None)
check("cosmos: flechas de letra usan el color sobre acento", w.lyrics_left_arrow._glyph_on_accent)
arrow_color = w.lyrics_left_arrow._on_accent
check("cosmos: flecha de letra legible sobre la montañita (>= 4.5)",
      min(cr((arrow_color.red(), arrow_color.green(), arrow_color.blue()), Palette.ACCENT_A),
          cr((arrow_color.red(), arrow_color.green(), arrow_color.blue()), Palette.ACCENT_B)) >= 4.5)
base = w.grab().toImage()
check("el cielo se pinta (la ventana cambia respecto al predeterminado)", base != img_default)

# cielo cacheado: se rehace solo si cambia el tamaño
key1 = w._sky._key; w.update(); pump(0.05)
check("el cielo se cachea entre repintados", w._sky._key == key1)

# estrella fugaz dibujada a mitad de vuelo, en una zona libre del encabezado (los widgets
# se pintan ENCIMA del fondo, así que sobre la carátula no se vería: es lo esperado)
w._stars._star = (QPointF(225.0, 44.0), QPointF(130.0, 24.0), 1.0, (255, 255, 255))
w.update(); pump(0.05)
with_star = w.grab().toImage()
diff = sum(1 for x in range(120, 240) for y in range(15, 55)
           if with_star.pixelColor(x, y).lightness() > base.pixelColor(x, y).lightness() + 25)
check("la estrella fugaz se dibuja (detrás de los widgets, sobre el cielo)", diff > 40, f"{diff} píxeles más claros")
w._stars._star = None

print("== Cuándo se permiten las estrellas fugaces")
stars = w._stars
stars._timer.stop()
cosmos_sky.on_ac_power = lambda: True
theme.REDUCED_MOTION = False
stars._launch()
check("sonando + visible + corriente: se anima", stars._anim.state() == cosmos_sky.QVariantAnimation.State.Running)
stars._anim.stop(); stars._timer.stop()

from backend import PlayerState
w.apply_state(PlayerState(connected=True, state="PAUSED", title="t", artist="a", can_play_pause=True)); pump(0.1)
stars._launch()
check("en pausa: no se anima", stars._anim.state() != cosmos_sky.QVariantAnimation.State.Running)
w.apply_state(PlayerState(connected=True, state="PLAYING", title="t", artist="a", can_play_pause=True)); pump(0.1)

cosmos_sky.on_ac_power = lambda: False
stars._timer.stop(); stars._launch()
check("con batería (o sin saberlo): no se anima", stars._anim.state() != cosmos_sky.QVariantAnimation.State.Running)
cosmos_sky.on_ac_power = lambda: True
theme.REDUCED_MOTION = True
stars._timer.stop(); stars._launch()
check("movimiento reducido: no se anima", stars._anim.state() != cosmos_sky.QVariantAnimation.State.Running)
check("sin animar, el reintento queda programado (sin bucle activo)", stars._timer.isActive())
theme.REDUCED_MOTION = False
w.hide(); w.deleteLater()

print("== Configuración")
from config import AppConfig
import dialogs
cfg = AppConfig()
check("AppConfig.player_theme por defecto = default", cfg.player_theme == "default")
cfg.player_theme = "cosmos"
dlg = dialogs.SettingsDialog(cfg, 1234, lambda: None, lambda: None, lambda: None)
dlg.show(); pump(0.05)
check("selector de aspecto con 2 opciones", dlg.player_theme_combo.count() == 2
      and [dlg.player_theme_combo.itemData(i) for i in range(2)] == ["default", "cosmos"])
check("el selector arranca en el aspecto guardado", dlg.player_theme_combo.currentData() == "cosmos")
dlg.player_theme_combo.setCurrentIndex(0)
dlg._save()
check("Guardar entrega el aspecto elegido", dlg.result_player_theme == "default")

theme.set_player_theme("default")
print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL:
    print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
