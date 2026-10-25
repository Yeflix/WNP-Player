"""
Widgets personalizados usados por las interfaces del reproductor.
Todo el dibujo se hace con QPainter para mantener un rendimiento alto
y no depender de recursos gráficos externos (íconos, imágenes de fondo, etc).
"""
import bisect
import math
import time

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QPoint, QSize, QTimer, pyqtSignal, pyqtProperty,
    QPropertyAnimation, QEasingCurve, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QRadialGradient, QPainterPath, QPen,
    QTransform, QFont, QImage, QPixmap, QTextLayout, QTextOption
)
from PyQt6.QtWidgets import (
    QWidget, QAbstractButton, QLabel, QStackedLayout, QHBoxLayout, QVBoxLayout, QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect,
    QToolTip, QComboBox, QSizePolicy, QStyle, QStyleOptionComboBox, QStylePainter, QSlider,
    QPushButton,
)
from PyQt6.QtGui import QBrush, QFontMetrics

from theme import Palette, FONT_BODY
import theme as theme_module
import icons


LIKE_RGB = (255, 94, 125)   # rosa del corazón de "me gusta" (fijo, no depende del acento)


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
        round(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def blur_image(image: QImage, target_w: int, target_h: int, strength: int = 8) -> QImage:
    """Fondo difuminado de la mini-barra, en modo 'cover': la imagen SIEMPRE
    llena por completo el rectángulo destino (nunca deja bandas vacías a
    los lados ni arriba/abajo), recortando parejo lo que sobre por el eje
    que corresponda. No importa perder parte de la carátula: se prioriza
    que rellene por completo sobre mostrarla íntegra.
    """
    if image is None or image.isNull() or target_w <= 0 or target_h <= 0:
        return QImage()

    src_w, src_h = image.width(), image.height()
    if src_w <= 0 or src_h <= 0:
        return QImage()

    # Escala uniforme = la mayor de las dos razones, así la imagen queda
    # siempre AL MENOS tan grande como el destino en ambos ejes (esto es
    # lo que garantiza que nunca queden huecos).
    scale = max(target_w / src_w, target_h / src_h)
    scaled_w = max(1, round(src_w * scale))
    scaled_h = max(1, round(src_h * scale))

    # Downscale agresivo (blur barato) + upscale de vuelta al tamaño ya
    # escalado para "cover" (todavía sin recortar).
    if strength > 1:
        small_w = max(4, scaled_w // strength)
        small_h = max(4, scaled_h // strength)
        small = image.scaled(
            small_w, small_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    else:
        small = image
    scaled = small.scaled(
        scaled_w, scaled_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    # Recorte centrado al tamaño final exacto del destino.
    x0 = max(0, (scaled_w - target_w) // 2)
    y0 = max(0, (scaled_h - target_h) // 2)
    return scaled.copy(x0, y0, min(target_w, scaled_w), min(target_h, scaled_h))


def blur_image_hq(image: QImage, target_w: int, target_h: int) -> QImage:
    """Fondo ambiente de alta calidad para el reproductor completo:
    difuminado GAUSSIANO real (QGraphicsBlurEffect), no solo una miniatura
    minúscula estirada con interpolación (eso es lo que hacía verse
    'con menos calidad' en vez de borroso: reducir demasiado, p. ej. a
    40x40, y agrandar 16x deja bordes de celda visibles, no un blur suave).

    Se mantiene barato así: reduce a un tamaño intermedio MODERADO
    (conserva bastante detalle real) y aplica el blur gaussiano SOBRE esa
    imagen chica (rápido, pocos píxeles), recién ahí escala al tamaño
    final — el resultado es un difuminado suave con la calidad de la
    imagen original detrás, no un mosaico de bloques agrandados.
    """
    if image is None or image.isNull() or target_w <= 0 or target_h <= 0:
        return QImage()

    src_w, src_h = image.width(), image.height()
    if src_w <= 0 or src_h <= 0:
        return QImage()

    # Igual que blur_image(): modo "cover", nunca deja huecos.
    scale = max(target_w / src_w, target_h / src_h)
    scaled_w = max(1, round(src_w * scale))
    scaled_h = max(1, round(src_h * scale))

    # Tamaño intermedio: mucho menos agresivo que el blur "barato" de
    # blur_image (que baja hasta strength=16). Acá bajamos como mucho a la
    # mitad, nunca menos de 220px de lado — sigue siendo chico para que el
    # blur gaussiano sea rápido, pero conserva la calidad de la foto real.
    inter_w = max(220, min(scaled_w, scaled_w // 2 or scaled_w))
    inter_h = max(220, min(scaled_h, scaled_h // 2 or scaled_h))
    inter_w = min(inter_w, scaled_w)
    inter_h = min(inter_h, scaled_h)
    small = image.scaled(
        inter_w, inter_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    # Blur gaussiano real sobre la imagen intermedia (barato: son pocos
    # píxeles). El radio se expresa en píxeles de ESTA imagen chica, así
    # que un radio moderado ya cubre proporcionalmente toda la escena.
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(small))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(inter_w * 0.10)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    blurred_small = QImage(inter_w, inter_h, QImage.Format.Format_ARGB32_Premultiplied)
    blurred_small.fill(Qt.GlobalColor.transparent)
    painter = QPainter(blurred_small)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter)
    painter.end()

    # Recién acá escalamos al tamaño final "cover" (ya difuminado, así que
    # agrandar con interpolación suave no muestra ningún bloque).
    final_scaled = blurred_small.scaled(
        scaled_w, scaled_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x0 = max(0, (scaled_w - target_w) // 2)
    y0 = max(0, (scaled_h - target_h) // 2)
    return final_scaled.copy(x0, y0, min(target_w, scaled_w), min(target_h, scaled_h))


class IconButton(QAbstractButton):
    """Botón circular/plano que dibuja un ícono vectorial (icons.py)."""

    def __init__(self, icon_name, size=38, icon_scale=0.46, bg="circle",
                 gradient_bg=False, parent=None, glyph_on_accent=False):
        super().__init__(parent)
        self.icon_name = icon_name
        # True: el glifo se dibuja con el color "sobre acento" (blanco u oscuro, el
        # que más contraste da con el degradado de acento) en vez de TEXT_DIM.
        # Para botones que se apoyan sobre una zona de acento (flechas de la letra).
        self._glyph_on_accent = glyph_on_accent
        self._icon_scale = icon_scale
        self._bg_mode = bg  # None | "circle"
        self._gradient_bg = gradient_bg
        self._hover = False
        self._active = False
        self._hover_progress = 0.0  # 0 = color normal, 1 = color de hover (animado)
        self._color_override = None  # QColor fijo (p. ej. el rosa del corazón de "me gusta")
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self._on_accent = self._compute_on_accent()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        # Solo Tab da foco (no el clic): con el foco por clic, después de tocar
        # "aleatorio" la barra espaciadora activaba ESE botón en vez de
        # reproducir/pausar. Con foco por teclado se dibuja un anillo visible.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._kbd_focus = False

        # Cambio de ícono (p. ej. play <-> pausa): fundido + pequeño "pop" en
        # vez de un cambio instantáneo.
        self._prev_icon = None
        self._swap = 1.0
        self._swap_anim = QPropertyAnimation(self, b"swapProgress", self)
        self._swap_anim.setDuration(150)
        self._swap_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._swap_anim.finished.connect(self._on_swap_finished)

        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # 1.0 = totalmente visible (comportamiento normal de siempre en
        # cualquier botón existente). Solo se usa en 0..1 cuando alguien
        # llamó a set_reveal_animated (ver MiniWindow en modo vinilo: los
        # controles aparecen/desaparecen con el mouse encima/afuera).
        self._reveal = 1.0
        self._reveal_anim = QPropertyAnimation(self, b"revealProgress", self)
        self._reveal_anim.setDuration(160)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    hoverProgress = pyqtProperty(float, _get_hover_progress, _set_hover_progress)

    def _get_reveal_progress(self) -> float:
        return self._reveal

    def _set_reveal_progress(self, value: float):
        self._reveal = value
        self.update()

    revealProgress = pyqtProperty(float, _get_reveal_progress, _set_reveal_progress)

    def _get_swap_progress(self) -> float:
        return self._swap

    def _set_swap_progress(self, value: float):
        self._swap = value
        self.update()

    swapProgress = pyqtProperty(float, _get_swap_progress, _set_swap_progress)

    def _on_swap_finished(self):
        self._prev_icon = None
        self._swap = 1.0
        self.update()

    def _compute_on_accent(self) -> QColor:
        """Color del ícono sobre el degradado de acento: blanco u oscuro según
        cuál contraste más con AMBOS extremos (ver theme.on_color)."""
        a, b = self._accent_a, self._accent_b
        rgb = theme_module.on_color((a.red(), a.green(), a.blue()),
                                    (b.red(), b.green(), b.blue()))
        return QColor(*rgb)

    def setToolTip(self, text: str):
        super().setToolTip(text)
        # Los botones son íconos pintados a mano: sin nombre accesible un
        # lector de pantalla no tiene nada que leer. Se mantiene sincronizado
        # con el tooltip (p. ej. "Mostrar letra" <-> "Ocultar letra") salvo
        # que alguien haya fijado un nombre propio con setAccessibleName.
        if text:
            name = text.split("\n")[0]
            current = self.accessibleName()
            if not current or current == getattr(self, "_auto_a11y_name", None):
                self.setAccessibleName(name)
                self._auto_a11y_name = name

    def focusInEvent(self, event):
        self._kbd_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._kbd_focus = False
        self.update()
        super().focusOutEvent(event)

    def set_reveal_animated(self, target: float, duration_ms: int = 160):
        self._reveal_anim.stop()
        self._reveal_anim.setDuration(duration_ms)
        self._reveal_anim.setStartValue(self._reveal)
        self._reveal_anim.setEndValue(target)
        self._reveal_anim.start()

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def set_icon(self, icon_name: str):
        if icon_name != self.icon_name:
            if self.isVisible() and not theme_module.REDUCED_MOTION:
                self._prev_icon = self.icon_name
                self.icon_name = icon_name
                self._swap_anim.stop()
                self._swap = 0.0
                self._swap_anim.setStartValue(0.0)
                self._swap_anim.setEndValue(1.0)
                self._swap_anim.start()
            else:
                self.icon_name = icon_name
                self.update()

    def set_color_override(self, rgb):
        """Color fijo del glifo (None = el de siempre)."""
        color = None if rgb is None else QColor(*rgb)
        if color != self._color_override:
            self._color_override = color
            self.update()

    def set_active(self, active: bool):
        if active != self._active:
            self._active = active
            self.update()

    def set_accent(self, rgb_a: tuple, rgb_b: tuple):
        """Solo tiene efecto visible en botones con gradient_bg=True (el de
        play), pero se guarda igual en cualquier IconButton por si algún
        día se usa en otro con fondo degradado."""
        self._accent_a = QColor(*rgb_a)
        self._accent_b = QColor(*rgb_b)
        self._on_accent = self._compute_on_accent()
        self.update()

    def is_active(self) -> bool:
        return self._active

    def enterEvent(self, event):
        self._hover = True
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def setEnabled(self, enabled):
        if enabled == self.isEnabled():
            return
        super().setEnabled(enabled)
        if not enabled and self._hover:
            self._hover = False
            self._hover_anim.stop()
            self._hover_progress = 0.0
        self.update()

    def hitButton(self, pos) -> bool:
        if self._reveal <= 0.05:
            return False
        return super().hitButton(pos)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.update()  # feedback de "squish" inmediato al presionar

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._reveal < 1.0:
            if self._reveal <= 0.0:
                painter.end()
                return
            painter.setOpacity(self._reveal)
        rect = QRectF(0, 0, self.width(), self.height())

        # Pequeño "squish" táctil: todo el botón se encoge un poco mientras
        # está presionado, para que el clic se sienta instantáneo incluso
        # antes de que el backend confirme la acción.
        if self.isDown() and self.isEnabled():
            painter.translate(rect.center())
            painter.scale(0.90, 0.90)
            painter.translate(-rect.center())

        if self._gradient_bg and not self.isEnabled():
            # Antes el play deshabilitado se pintaba idéntico al habilitado.
            painter.setOpacity(painter.opacity() * 0.45)

        if self._bg_mode == "circle":
            painter.setPen(Qt.PenStyle.NoPen)
            if self._gradient_bg:
                grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
                grad.setColorAt(0.0, self._accent_a)
                grad.setColorAt(1.0, self._accent_b)
                painter.setBrush(grad)
            else:
                alpha = round(14 + 16 * self._hover_progress) if self.isEnabled() else 14
                painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(rect)

        size = self.width() * self._icon_scale

        if self._gradient_bg:
            color = self._on_accent
        elif not self.isEnabled():
            color = QColor(*Palette.TEXT_FAINT, 90)
        elif self._color_override is not None:
            color = _lerp_color(self._color_override, self._color_override.lighter(120), self._hover_progress)
        elif self._glyph_on_accent:
            color = self._on_accent
        elif self._active:
            color = self._accent_a
        else:
            # Transición suave entre el color normal y el de hover, en vez
            # de un cambio instantáneo al entrar/salir con el mouse.
            color = _lerp_color(Palette.c(Palette.TEXT_DIM), self._accent_a,
                                 self._hover_progress)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        if self._prev_icon is not None and self._swap < 1.0:
            # Fundido cruzado: el ícono saliente se achica y se desvanece, el
            # entrante crece desde 80% hasta 100%.
            base_opacity = painter.opacity()
            painter.setOpacity(base_opacity * (1.0 - self._swap))
            painter.drawPath(self._icon_mapped(self._prev_icon, rect, size * (1.0 - 0.2 * self._swap)))
            painter.setOpacity(base_opacity * self._swap)
            painter.drawPath(self._icon_mapped(self.icon_name, rect, size * (0.8 + 0.2 * self._swap)))
            painter.setOpacity(base_opacity)
        else:
            painter.drawPath(self._icon_mapped(self.icon_name, rect, size))

        # Anillo de foco de teclado (solo si el foco vino de Tab).
        if self._kbd_focus and self.hasFocus():
            painter.resetTransform()
            ring = QColor(*Palette.TEXT)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ring, 2.0))
            if self._bg_mode == "circle":
                painter.drawEllipse(rect.adjusted(1.0, 1.0, -1.0, -1.0))
            else:
                painter.drawRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), 6, 6)
        painter.end()

    @staticmethod
    def _icon_mapped(name: str, rect: QRectF, size: float) -> QPainterPath:
        transform = QTransform()
        transform.translate(rect.center().x() - size / 2, rect.center().y() - size / 2)
        transform.scale(size / 24, size / 24)
        return transform.map(icons.get_icon_path(name))


class SeekBar(QWidget):
    """Barra de progreso con soporte de arrastre para buscar (seek).
    Las actualizaciones que llegan del backend (`set_percent`) se animan
    suavemente hacia el nuevo valor en vez de saltar de golpe, para que se
    vea como un deslizamiento continuo en vez de "tics" cada pocos ms."""

    seekRequested = pyqtSignal(float)  # porcentaje 0-100
    seekPreview = pyqtSignal(float)

    def __init__(self, parent=None, height=16, bar_height=6):
        super().__init__(parent)
        self._bar_h = bar_height
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self._percent = 0.0
        self._dragging = False
        self._seekable = True
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"animatedPercent", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Hover: la barra se engorda un poco y la perilla crece (feedback de
        # que es interactiva, y más área visual para apuntar).
        self._hover_progress = 0.0
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(120)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._duration_seconds = 0
        self._kbd_focus = False
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName("Progreso de reproducción")

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    hoverProgress = pyqtProperty(float, _get_hover_progress, _set_hover_progress)

    def set_duration_seconds(self, seconds: int):
        """Duración total, solo para mostrar el tiempo al que caería el clic
        mientras se pasa el mouse por encima (tooltip) y para el paso del
        teclado (5 s por flecha)."""
        self._duration_seconds = max(0, int(seconds or 0))

    def _hover_text(self, percent: float) -> str:
        if self._duration_seconds <= 0:
            return ""
        secs = max(0, round(percent / 100.0 * self._duration_seconds))
        m, s = divmod(secs, 60)
        return f"{m}:{s:02d}"

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        if self._seekable:
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        QToolTip.hideText()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._kbd_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._kbd_focus = False
        self.update()
        super().focusOutEvent(event)

    # Teclado: flechas +-5 s (o 2 % si no se conoce la duración), Re/Av Pág
    # +-10 %, Inicio/Fin. Antes la barra no se podía operar sin mouse.
    def _key_step(self) -> float:
        return (5.0 / self._duration_seconds * 100.0) if self._duration_seconds > 0 else 2.0

    def _apply_key_value(self, percent: float):
        self._anim.stop()
        self._percent = percent
        self.seekPreview.emit(percent)
        self.update()
        self.seekRequested.emit(percent)

    def keyPressEvent(self, event):
        if not self._seekable:
            super().keyPressEvent(event)
            return
        key = event.key()
        step = self._key_step()
        K = Qt.Key
        if key in (K.Key_Right, K.Key_Up):
            target = self._percent + step
        elif key in (K.Key_Left, K.Key_Down):
            target = self._percent - step
        elif key == K.Key_PageUp:
            target = self._percent + 10.0
        elif key == K.Key_PageDown:
            target = self._percent - 10.0
        elif key == K.Key_Home:
            target = 0.0
        elif key == K.Key_End:
            target = 100.0
        else:
            super().keyPressEvent(event)
            return
        self._apply_key_value(max(0.0, min(100.0, target)))
        event.accept()

    def _get_animated_percent(self) -> float:
        return self._percent

    def _set_animated_percent(self, value: float):
        self._percent = value
        self.update()

    # Propiedad que anima QPropertyAnimation; distinta del set_percent()
    # público para que no se disparen animaciones anidadas sobre sí mismas.
    animatedPercent = pyqtProperty(float, _get_animated_percent, _set_animated_percent)

    def set_accent(self, rgb_a: tuple, rgb_b: tuple):
        self._accent_a = QColor(*rgb_a)
        self._accent_b = QColor(*rgb_b)
        self.update()

    def set_percent(self, percent: float):
        if self._dragging:
            return
        percent = max(0.0, min(100.0, percent))
        delta = abs(percent - self._percent)
        if delta < 0.05:
            return
        # El backend sondea cada ~150ms, así que esto se llama todo el
        # rato mientras algo está sonando, con incrementos chiquitos
        # (avance normal de la reproducción). Animar ESE caso significa
        # que la barra nunca deja de repintarse mientras hay reproducción
        # activa — un costo de CPU continuo y evitable para un movimiento
        # de apenas un par de píxeles cada vez, prácticamente imperceptible
        # esté animado o no. Reservamos la animación suave para saltos que
        # sí se notan (una búsqueda manual en la barra, por ejemplo);
        # tanto los incrementos mínimos del sondeo normal como los saltos
        # grandes (cambio de canción) van directo, sin animar.
        if delta > 15 or delta < 3:
            self._anim.stop()
            self._percent = percent
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._percent)
        self._anim.setEndValue(percent)
        self._anim.start()

    def set_seekable(self, enabled: bool):
        if enabled == self._seekable:
            return
        self._seekable = enabled
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )

    def is_dragging(self) -> bool:
        return self._dragging

    def mousePressEvent(self, event):
        if not self._seekable:
            return
        self._anim.stop()
        self._dragging = True
        self._update_from_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_x(event.position().x())
        elif self._seekable:
            pct = max(0.0, min(100.0, event.position().x() / max(1, self.width()) * 100))
            text = self._hover_text(pct)
            if text:
                QToolTip.showText(event.globalPosition().toPoint() + QPoint(0, -28), text, self)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.seekRequested.emit(self._percent)

    def _update_from_x(self, x):
        w = max(1, self.width())
        pct = max(0.0, min(100.0, (x / w) * 100))
        self._percent = pct
        self.seekPreview.emit(pct)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._bar_h * (1.0 + 0.5 * self._hover_progress)
        y = (self.height() - h) / 2
        track_rect = QRectF(0, y, self.width(), h)
        track_path = QPainterPath()
        track_path.addRoundedRect(track_rect, h / 2, h / 2)
        painter.fillPath(track_path, QColor(255, 255, 255, 22))

        fill_w = self.width() * (self._percent / 100)
        if fill_w > 1:
            fill_rect = QRectF(0, y, fill_w, h)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill_rect, h / 2, h / 2)
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0, self._accent_a)
            grad.setColorAt(1, self._accent_b)
            painter.fillPath(fill_path, grad)

        # El thumb se dibuja SIEMPRE, no solo cuando hay relleno visible —
        # antes quedaba adentro del "if fill_w > 1" de arriba, así que con
        # el valor muy cerca de 0 (volumen casi al mínimo, por ejemplo)
        # directamente no se pintaba: se sentía como que el botón
        # "desaparecía" al ir demasiado a la izquierda.
        base_h = self._bar_h
        handle_r = base_h * (1.35 if self._dragging else 1.0 + 0.2 * self._hover_progress)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        thumb = QPointF(min(max(fill_w, handle_r), self.width() - handle_r), y + h / 2)
        painter.drawEllipse(thumb, handle_r, handle_r)
        if self._kbd_focus and self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*Palette.TEXT), 1.6))
            painter.drawEllipse(thumb, handle_r + 3.0, handle_r + 3.0)
        painter.end()


class VolumeBar(SeekBar):
    """Barra de volumen con el mismo lenguaje visual e interacción que
    SeekBar (clic directo a la posición + arrastre), en vez del QSlider
    nativo de Qt que se venía usando — que por defecto NO salta a la
    posición exacta donde se hace clic (solo avanza de a "page steps"),
    lo que se sentía como un bug al intentar subir o bajar el volumen.

    A diferencia de SeekBar, acá el valor se aplica EN VIVO mientras se
    arrastra (no solo al soltar el clic). Pero "en vivo" tiene un límite:
    mandar el comando real (que termina viajando hasta el reproductor de
    origen vía pywnp, una llamada que BLOQUEA el hilo principal mientras
    espera) en cada evento de movimiento del mouse —que durante un
    arrastre puede disparar decenas de veces por segundo— hacía que toda
    la interfaz se sintiera trabada ("no actúa de forma inmediata").
    Por eso el comando real se manda con throttle (como mucho cada
    _EMIT_THROTTLE_MS), mientras que el thumb/relleno se sigue pintando
    al instante en cada movimiento (eso es solo dibujo local, gratis)."""

    volumeChanged = pyqtSignal(int)
    _EMIT_THROTTLE_MS = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAccessibleName("Volumen")
        self._pending_emit = False
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(self._EMIT_THROTTLE_MS)
        self._emit_timer.timeout.connect(self._flush_emit)

    def set_interactive(self, enabled: bool):
        self.set_seekable(enabled)

    def _hover_text(self, percent: float) -> str:
        return f"{round(percent)}%"

    def _key_step(self) -> float:
        return 5.0

    def _apply_key_value(self, percent: float):
        self._percent = percent
        self.update()
        self._emit_timer.stop()
        self._pending_emit = False
        self.volumeChanged.emit(round(percent))

    def wheelEvent(self, event):
        """Rueda sobre la barra de volumen = +-5 % por muesca. Si no es
        interactiva se ignora y el evento sube a la ventana (zoom)."""
        steps = event.angleDelta().y() / 120.0
        if not self._seekable or steps == 0:
            event.ignore()
            return
        self._apply_key_value(max(0.0, min(100.0, self._percent + steps * 5.0)))
        event.accept()

    def _flush_emit(self):
        if self._pending_emit:
            self._pending_emit = False
            self.volumeChanged.emit(round(self._percent))

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self._seekable:
            # El primer toque se manda directo, sin esperar el throttle —
            # así el clic inicial se siente inmediato.
            self._emit_timer.stop()
            self._pending_emit = False
            self.volumeChanged.emit(round(self._percent))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._dragging:
            self._pending_emit = True
            if not self._emit_timer.isActive():
                self._emit_timer.start()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Al soltar, asegurarse de mandar el valor FINAL exacto de una,
        # aunque el throttle todavía no haya disparado — nunca debe
        # quedar "pisado" un cambio pendiente.
        self._emit_timer.stop()
        self._flush_emit()


class ElidedLabel(QLabel):
    """QLabel que trunca su texto con '...' si no cabe, mostrando el texto completo en el tooltip."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str):
        text = text or ""
        if text == self._full_text:
            return
        self._full_text = text
        self._apply_elide()

    def fullText(self) -> str:
        return self._full_text

    def resizeEvent(self, event):
        self._apply_elide()
        super().resizeEvent(event)

    def changeEvent(self, event):
        # Si cambia la fuente (p. ej. al aplicarse el stylesheet) hay que volver
        # a medir: el recorte anterior se calculó con la fuente vieja.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._apply_elide()
            self.updateGeometry()
        super().changeEvent(event)

    def sizeHint(self) -> QSize:
        # Tamaño PREFERIDO = el del texto completo (no el del texto ya recortado,
        # que se encogería solo y nunca volvería a crecer al haber espacio).
        sh = super().sizeHint()
        fm = QFontMetrics(self.font())
        # sh.width() = texto mostrado + relleno/márgenes del estilo: se conserva ese extra.
        extra = sh.width() - fm.horizontalAdvance(self.text())
        return QSize(fm.horizontalAdvance(self._full_text) + max(0, extra), sh.height())

    def minimumSizeHint(self) -> QSize:
        # Antes un QLabel sin ajuste de línea devolvía como mínimo el ancho de su
        # texto COMPLETO: el layout jamás lo dejaba encogerse, el contenedor
        # crecía (Estadísticas llegaba a 854 px dentro de un área de 332), y el
        # "…" no se activaba nunca porque la etiqueta nunca quedaba más angosta
        # que su texto. Con un mínimo chico el layout puede comprimirla y el
        # recorte con "…" funciona.
        fm = QFontMetrics(self.font())
        sh = super().sizeHint()
        extra = max(0, sh.width() - fm.horizontalAdvance(self.text()))
        return QSize(fm.horizontalAdvance("…") + extra, super().minimumSizeHint().height())

    def _apply_elide(self):
        metrics = QFontMetrics(self.font())
        # contentsRect() ya descuenta el relleno/borde del stylesheet (padding: 3px 2px...).
        width = self.contentsRect().width()
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, width))
        super().setText(elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")


class MarqueeLabel(QWidget):
    """Label que, si el texto no cabe en el ancho disponible, se desliza de
    lado a lado (estilo "marquesina") en vez de solo cortarlo con "...".
    Si el texto SÍ cabe, se queda quieto y centrado — no vale la pena
    animar algo que ya se ve completo, y así se ahorra CPU y no distrae.

    El deslizamiento es tipo "rebote": se detiene un momento al inicio,
    se desliza hasta revelar el final del texto, se detiene otro momento,
    y vuelve. Nunca se anima mientras la ventana está oculta.
    """

    _TICK_MS = 50          # ~20fps: de sobra para un desplazamiento lento
                           # de texto, y bien por debajo de los 60fps
                           # originales mientras el título/artista no entra
                           # en el ancho disponible — este es de los pocos
                           # timers que quedan corriendo todo el rato
                           # mientras algo suena con un título largo, así
                           # que vale la pena mantenerlo bien bajo (la
                           # velocidad real en píxeles/segundo no cambia:
                           # _step se ajusta solo más abajo según _TICK_MS).
    _GAP_PX = 4             # margen para no recortar la última letra

    def __init__(self, text="", parent=None, font: QFont | None = None,
                 color=None, align=Qt.AlignmentFlag.AlignHCenter,
                 pixels_per_sec: float = 42.0, pause_ms: int = 900):
        super().__init__(parent)
        self._font = font if font is not None else QFont(FONT_BODY, 12)
        self._color = color if color is not None else QColor(255, 255, 255)
        self._align = align

        self._full_text = ""
        self._text_width = 0
        self._needs_scroll = False
        self._offset = 0.0
        self._direction = 1

        # Velocidad por TIEMPO REAL (px/s), no por tick: los QTimer de Qt son
        # "gruesos" (pueden atrasarse ~5 % o más bajo carga) y con un paso fijo
        # por tick la marquesina iba a tirones y a velocidad variable.
        self._pps = pixels_per_sec
        self._pause_s = max(0.05, pause_ms / 1000.0)
        self._pause_until = 0.0
        self._last_tick = None

        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick)

        if text:
            self.setText(text)

    def text_height(self) -> int:
        """Alto de línea de la fuente REAL de la etiqueta. (fontMetrics() de
        QWidget mediría la fuente por defecto de la app: aquí setFont() solo
        guarda la fuente en self._font.)"""
        return QFontMetrics(self._font).height()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font)
        width = max(40, metrics.horizontalAdvance(self._full_text) or 60)
        return QSize(width, metrics.height() + 2)

    def setFont(self, font: QFont):
        super().setFont(font)
        self._font = font
        self._recompute()
        self.updateGeometry()

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def setText(self, text: str):
        text = text or ""
        if text == self._full_text:
            return
        self._full_text = text
        self._recompute()
        self.updateGeometry()

    def fullText(self) -> str:
        return self._full_text

    def resizeEvent(self, event):
        self._recompute()
        super().resizeEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        self._last_tick = None
        super().hideEvent(event)

    def showEvent(self, event):
        if self._needs_scroll:
            self._last_tick = None
            self._timer.start()
        super().showEvent(event)

    def _recompute(self):
        metrics = QFontMetrics(self._font)
        self._text_width = metrics.horizontalAdvance(self._full_text)
        truncated = self.width() > 0 and self._text_width > self.width()
        # Con movimiento reducido el texto largo NO se desplaza: se recorta
        # con "…" (ver paintEvent) y el texto completo queda en el tooltip.
        self._needs_scroll = truncated and not theme_module.REDUCED_MOTION
        self._offset = 0.0
        self._direction = 1
        self._last_tick = None
        self._pause_until = time.monotonic() + self._pause_s if self._needs_scroll else 0.0
        self.setToolTip(self._full_text if truncated else "")

        if self._needs_scroll and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        dt = 0.0 if self._last_tick is None else min(now - self._last_tick, 0.25)
        self._last_tick = now
        if now < self._pause_until:
            return
        max_offset = max(0, self._text_width - self.width() + self._GAP_PX)
        self._offset += self._direction * self._pps * dt
        if self._offset >= max_offset:
            self._offset = max_offset
            self._direction = -1
            self._pause_until = now + self._pause_s
        elif self._offset <= 0:
            self._offset = 0
            self._direction = 1
            self._pause_until = now + self._pause_s
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        painter.setPen(self._color)
        rect = self.rect()
        if self._needs_scroll:
            draw_w = max(rect.width(), self._text_width) + self._GAP_PX
            draw_rect = QRectF(-self._offset, 0, draw_w, rect.height())
            painter.drawText(
                draw_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._full_text,
            )
        else:
            text = self._full_text
            if self._text_width > rect.width() > 0:
                text = QFontMetrics(self._font).elidedText(
                    text, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, self._align | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class CoverArt(QWidget):
    """Carátula redondeada con halo de color y marcador de posición cuando no
    hay imagen. Al cambiar de una carátula a otra, se desvanece suavemente
    en vez de reemplazarse de golpe."""

    def __init__(self, size=190, radius_ratio=0.16, parent=None):
        super().__init__(parent)
        self._img_size = size
        self._radius_ratio = radius_ratio
        self.setFixedSize(size, size)
        self._image: QImage | None = None
        self._prev_image: QImage | None = None
        # Versiones YA escaladas al tamaño del widget, cacheadas: escalar
        # con suavizado es relativamente caro, y sin este cache se estaba
        # recalculando en CADA repintado — antes eso solo pasaba durante
        # el crossfade de 240ms al cambiar de canción, pero ahora que el
        # halo "respira" (ver set_glow_intensity) repinta en bucle
        # mientras suena algo, hacerlo sin cache disparaba el uso de CPU
        # todo el rato que hay reproducción activa. Se recalculan solo
        # cuando cambia la imagen o el tamaño del widget (ver set_image y
        # resizeEvent), nunca en paintEvent.
        self._image_scaled: QImage | None = None
        self._prev_image_scaled: QImage | None = None
        self._fade_progress = 1.0  # 1.0 = solo se ve _image (sin transición en curso)
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)
        self._glow_intensity = 1.0  # animado por MainWindow: "respira" mientras suena algo

        self._fade_anim = QPropertyAnimation(self, b"fadeProgress", self)
        self._fade_anim.setDuration(240)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

    def set_accent(self, rgb_a: tuple, rgb_b: tuple):
        """Color de acento del halo detrás de la carátula. Lo anima quien
        llama (MainWindow), acá solo guardamos el valor ya interpolado de
        este frame y repintamos."""
        self._accent_a = QColor(*rgb_a)
        self._accent_b = QColor(*rgb_b)
        self.update()

    def set_glow_intensity(self, value: float):
        """0..1. MainWindow anima esto para que el halo 'respire' despacio
        mientras hay reproducción activa, y se quede fijo si no."""
        if abs(value - self._glow_intensity) < 0.002:
            return
        self._glow_intensity = value
        self.update()

    def _get_fade_progress(self) -> float:
        return self._fade_progress

    def _set_fade_progress(self, value: float):
        self._fade_progress = value
        self.update()

    fadeProgress = pyqtProperty(float, _get_fade_progress, _set_fade_progress)

    def _on_fade_finished(self):
        self._prev_image = None
        self.update()

    def set_image(self, image):
        if isinstance(image, QPixmap):
            image = image.toImage()
        new_image = image if (image is not None and not image.isNull()) else None

        if new_image is self._image:
            return

        if new_image is not None and self._image is not None:
            # Cambiando de una carátula a otra: crossfade (la vieja se queda
            # de fondo, la nueva se desvanece encima).
            self._fade_anim.stop()
            self._prev_image = self._image
            self._prev_image_scaled = self._image_scaled
            self._image = new_image
            self._image_scaled = self._rescale(new_image)
            self._fade_progress = 0.0
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            # Aparece o desaparece la carátula (nada que mezclar): directo.
            self._fade_anim.stop()
            self._prev_image = None
            self._prev_image_scaled = None
            self._image = new_image
            self._image_scaled = self._rescale(new_image) if new_image is not None else None
            self._fade_progress = 1.0
            self.update()

    def _rescale(self, image: QImage) -> QImage:
        return image.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # El widget cambia de tamaño con el zoom (rueda del mouse); hay que
        # volver a escalar el cache a la nueva medida (barato: solo pasa en
        # los momentos puntuales en que cambia el tamaño, no en cada frame).
        if self._image is not None:
            self._image_scaled = self._rescale(self._image)
        if self._prev_image is not None:
            self._prev_image_scaled = self._rescale(self._prev_image)

    def _draw_scaled(self, painter: QPainter, scaled: QImage):
        x = (scaled.width() - self.width()) / 2
        y = (scaled.height() - self.height()) / 2
        painter.drawImage(QPointF(-x, -y), scaled)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self.width(), self.height())
        radius = self.width() * self._radius_ratio

        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, radius, radius)

        painter.save()
        painter.setClipPath(clip_path)

        if self._image is not None:
            if self._prev_image is not None and self._fade_progress < 0.999:
                painter.setOpacity(1.0)
                self._draw_scaled(painter, self._prev_image_scaled)
                painter.setOpacity(self._fade_progress)
                self._draw_scaled(painter, self._image_scaled)
                painter.setOpacity(1.0)
            else:
                self._draw_scaled(painter, self._image_scaled)
        else:
            base_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            base_grad.setColorAt(0.0, Palette.c(Palette.BG_PANEL, 255))
            base_grad.setColorAt(1.0, QColor(22, 22, 32, 255))
            painter.fillPath(clip_path, base_grad)

            note_path = icons.get_icon_path("note")
            icon_size = self.width() * 0.30
            transform = QTransform()
            transform.translate(
                rect.center().x() - icon_size / 2, rect.center().y() - icon_size / 2
            )
            transform.scale(icon_size / 24, icon_size / 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*Palette.TEXT_FAINT, 200))
            painter.drawPath(transform.map(note_path))

        painter.restore()

        # Borde de acento que "respira" con la reproducción (set_glow_intensity).
        # Antes era un halo exterior de 10 px, pero el widget no tiene margen:
        # Qt lo recortaba y solo se veían manchas rojizas en las 4 esquinas.
        rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
        rim_alpha = round(40 + 90 * max(0.0, min(1.0, self._glow_intensity)))
        rim.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                   self._accent_a.blue(), rim_alpha))
        rim.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                   self._accent_b.blue(), round(rim_alpha * 0.4)))
        painter.setPen(QPen(QBrush(rim), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
        painter.end()


class VinylCover(QWidget):
    """Carátula circular estilo disco de vinilo que 'rompe' el marco de la
    barra compacta. Funciona también como botón (alterna entre la barra
    completa y el modo círculo) y como manija de arrastre de la ventana:
    un click corto alterna el modo, un arrastre mueve la ventana.

    Gira mientras hay reproducción activa; el temporizador de giro se
    detiene por completo cuando no se está reproduciendo o la ventana está
    oculta, para no gastar CPU de fondo sin necesidad."""

    clicked = pyqtSignal()

    _SPIN_INTERVAL_MS = 40
    _SPIN_DEG_PER_SEC = 55.0   # = 2.2 grados cada 40 ms, como antes, pero por tiempo real
    _DRAG_THRESHOLD = 4

    def __init__(self, diameter=76, shadow_margin=9, parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self._shadow_margin = shadow_margin
        self.setFixedSize(diameter + shadow_margin * 2, diameter + shadow_margin * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._label_pixmap: QPixmap | None = None
        self._prev_label_pixmap: QPixmap | None = None
        self._fade_progress = 1.0  # 1.0 = solo se ve _label_pixmap (sin transición en curso)
        self._angle = 0.0
        self._spinning = False
        self._accent_a = Palette.c(Palette.ACCENT_A)
        self._accent_b = Palette.c(Palette.ACCENT_B)

        self._press_global = None
        self._drag_origin = None
        self._moved = False

        self._last_spin = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._SPIN_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

        self._fade_anim = QPropertyAnimation(self, b"fadeProgress", self)
        self._fade_anim.setDuration(240)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

    def _get_fade_progress(self) -> float:
        return self._fade_progress

    def _set_fade_progress(self, value: float):
        self._fade_progress = value
        self.update()

    fadeProgress = pyqtProperty(float, _get_fade_progress, _set_fade_progress)

    def set_accent(self, rgb_a: tuple, rgb_b: tuple):
        self._accent_a = QColor(*rgb_a)
        self._accent_b = QColor(*rgb_b)
        self.update()

    def _on_fade_finished(self):
        self._prev_label_pixmap = None
        self.update()

    # ------------------------------------------------------------ ajustes
    def set_diameter(self, diameter: int):
        if diameter == self._diameter:
            return
        self._diameter = diameter
        self.setFixedSize(diameter + self._shadow_margin * 2, diameter + self._shadow_margin * 2)
        self.update()

    def set_image(self, image):
        if image is None or (hasattr(image, "isNull") and image.isNull()):
            new_pixmap = None
        else:
            if isinstance(image, QPixmap):
                image = image.toImage()
            side = min(image.width(), image.height())
            x0 = (image.width() - side) // 2
            y0 = (image.height() - side) // 2
            cropped = image.copy(x0, y0, side, side)
            new_pixmap = QPixmap.fromImage(
                cropped.scaled(
                    160, 160,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        if new_pixmap is self._label_pixmap:
            return

        if new_pixmap is not None and self._label_pixmap is not None:
            # Cambiando de una carátula a otra: crossfade (la vieja se queda
            # de fondo, la nueva se desvanece encima) — igual que CoverArt.
            self._fade_anim.stop()
            self._prev_label_pixmap = self._label_pixmap
            self._label_pixmap = new_pixmap
            self._fade_progress = 0.0
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            # Aparece o desaparece la carátula (nada que mezclar): directo.
            self._fade_anim.stop()
            self._prev_label_pixmap = None
            self._label_pixmap = new_pixmap
            self._fade_progress = 1.0
            self.update()

    def set_spinning(self, spinning: bool):
        if spinning == self._spinning:
            return
        self._spinning = spinning
        if spinning and self.isVisible() and not theme_module.REDUCED_MOTION:
            self._last_spin = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event):
        if self._spinning and not theme_module.REDUCED_MOTION:
            self._last_spin = time.monotonic()
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self):
        now = time.monotonic()
        dt = 0.0 if self._last_spin is None else min(now - self._last_spin, 0.25)
        self._last_spin = now
        self._angle = (self._angle + self._SPIN_DEG_PER_SEC * dt) % 360.0
        self.update()

    # -------------------------------------------------------------- pintura
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self._diameter
        cx = self.width() / 2
        cy = self.height() / 2

        # sombra propia (el vinilo "flota" sobre la barra)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2 + 3, d, d))

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._angle)

        disc_rect = QRectF(-d / 2, -d / 2, d, d)
        disc_grad = QRadialGradient(QPointF(0, 0), d / 2)
        disc_grad.setColorAt(0.0, QColor(48, 48, 58))
        disc_grad.setColorAt(0.78, QColor(18, 18, 24))
        disc_grad.setColorAt(1.0, QColor(8, 8, 12))
        painter.setBrush(disc_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(disc_rect)

        # surcos del vinilo
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        r = d / 2 - 6
        while r > d * 0.24:
            painter.drawEllipse(QPointF(0, 0), r, r)
            r -= 5

        # brillo que gira, para dar sensación de movimiento
        gloss = QPainterPath()
        gloss.moveTo(0, -d / 2 + 3)
        gloss.arcTo(QRectF(-d / 2 + 3, -d / 2 + 3, d - 6, d - 6), 90, 55)
        gloss.lineTo(0, 0)
        gloss.closeSubpath()
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(gloss)

        # etiqueta central (la carátula real)
        label_r = d * 0.40
        label_rect = QRectF(-label_r, -label_r, label_r * 2, label_r * 2)
        clip = QPainterPath()
        clip.addEllipse(label_rect)
        painter.save()
        painter.setClipPath(clip)
        if self._label_pixmap is not None:
            if self._prev_label_pixmap is not None and self._fade_progress < 0.999:
                painter.setOpacity(1.0)
                painter.drawPixmap(
                    label_rect, self._prev_label_pixmap,
                    QRectF(0, 0, self._prev_label_pixmap.width(), self._prev_label_pixmap.height()),
                )
                painter.setOpacity(self._fade_progress)
                painter.drawPixmap(
                    label_rect, self._label_pixmap,
                    QRectF(0, 0, self._label_pixmap.width(), self._label_pixmap.height()),
                )
                painter.setOpacity(1.0)
            else:
                painter.drawPixmap(
                    label_rect, self._label_pixmap,
                    QRectF(0, 0, self._label_pixmap.width(), self._label_pixmap.height()),
                )
        else:
            base = QLinearGradient(label_rect.topLeft(), label_rect.bottomRight())
            base.setColorAt(0.0, Palette.c(Palette.BG_PANEL))
            base.setColorAt(1.0, QColor(22, 22, 32))
            painter.fillPath(clip, base)
            note_path = icons.get_icon_path("note")
            icon_size = label_r * 1.1
            transform = QTransform()
            transform.translate(-icon_size / 2, -icon_size / 2)
            transform.scale(icon_size / 24, icon_size / 24)
            painter.setBrush(QColor(*Palette.TEXT_FAINT, 200))
            painter.drawPath(transform.map(note_path))
        painter.restore()

        # eje central
        painter.setBrush(QColor(10, 10, 14))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(0, 0), 2.6, 2.6)

        painter.restore()  # deshace translate/rotate

        # borde neón exterior (fijo, para que no "tiemble" al girar)
        ring_grad = QLinearGradient(QPointF(cx - d / 2, cy - d / 2), QPointF(cx + d / 2, cy + d / 2))
        ring_grad.setColorAt(0.0, QColor(self._accent_a.red(), self._accent_a.green(),
                                          self._accent_a.blue(), 210))
        ring_grad.setColorAt(1.0, QColor(self._accent_b.red(), self._accent_b.green(),
                                          self._accent_b.blue(), 210))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring_grad, 1.6))
        painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
        painter.end()

    # -------------------------------------------------------- arrastre/click
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_origin = self.window().frameGeometry().topLeft()
            self._moved = False
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press_global is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if not self._moved and delta.manhattanLength() > self._DRAG_THRESHOLD:
                self._moved = True
            if self._moved:
                self.window().move(self._drag_origin + delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
            if not self._moved:
                self.clicked.emit()
            self._press_global = None
        event.accept()


class HistoryCard(QWidget):
    """Tarjeta visual para una entrada del historial, con resalte animado
    al pasar el mouse (mismo lenguaje visual que los botones de la app).
    Opcionalmente clickeable (ver clickable=True): usado por el panel de
    'Recién sonaron' para reabrir la canción en su sitio."""

    clicked = pyqtSignal()

    def __init__(self, title: str, artist: str, player_name: str,
                 relative_time: str, parent=None, clickable: bool = False):
        super().__init__(parent)
        self._clickable = clickable
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        self.setMouseTracking(True)
        self._hover_progress = 0.0
        self._hover_anim = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(12)

        self.icon = IconButton("note", size=36, icon_scale=0.48, bg="circle")
        self.icon.setEnabled(False)
        layout.addWidget(self.icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = ElidedLabel(title or "Sin título")
        self.title_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 12.5px; font-weight: 700; background: transparent;"
        )
        text_col.addWidget(self.title_label)

        subtitle = artist or "Artista desconocido"
        if player_name:
            subtitle += f"  ·  {player_name}"
        self.artist_label = ElidedLabel(subtitle)
        self.artist_label.setStyleSheet(
            f"color: rgb{Palette.ACCENT_A}; font-family:'{FONT_BODY}'; "
            f"font-size: 10.5px; font-weight: 600; background: transparent;"
        )
        text_col.addWidget(self.artist_label)
        layout.addLayout(text_col, 1)

        self.time_label = QLabel(relative_time)
        self.time_label.setMinimumWidth(66)
        self.time_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 10.5px; background: transparent;"
        )
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.time_label)

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    hoverProgress = pyqtProperty(float, _get_hover_progress, _set_hover_progress)

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._clickable and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        alpha = round(6 + 12 * self._hover_progress)
        painter.fillPath(path, QColor(255, 255, 255, alpha))
        painter.end()


class PulsingDots(QWidget):
    """Tres puntos que laten en secuencia, para el estado 'buscando...'."""

    def __init__(self, parent=None, dot_count=3, dot_radius=4.0, color=None):
        super().__init__(parent)
        self._dot_count = dot_count
        self._radius = dot_radius
        self._color = color if color is not None else Palette.c(Palette.ACCENT_A)
        self._phase = 0.0
        self.setFixedSize(int(dot_count * (dot_radius * 2 + 10)), int(dot_radius * 4))
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps: de sobra para un pulso suave, la mitad de trabajo que antes (62fps)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._phase = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._phase += 0.09
        if self._phase > 2 * math.pi:
            self._phase -= 2 * math.pi
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        spacing = self.width() / self._dot_count
        for i in range(self._dot_count):
            offset = i * (2 * math.pi / 3)
            wave = 0.5 + 0.5 * math.sin(self._phase - offset)
            scale = 0.5 + 0.5 * wave
            cx = spacing * (i + 0.5)
            cy = self.height() / 2
            color = QColor(self._color)
            color.setAlphaF(0.4 + 0.6 * wave)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx, cy), self._radius * scale, self._radius * scale)
        painter.end()


class ArrowComboBox(QComboBox):
    """QComboBox con dos arreglos que el QSS por sí solo no logra:

    - Flecha desplegable dibujada a mano (Qt no dibuja triángulos con el truco
      de bordes de CSS: salía una barrita gris).
    - Ancho acotado: por defecto un combo pide el ancho de su opción MÁS larga
      ("Se abre y cierra solo (al pasar/alejar el mouse)"), y eso ensanchaba
      todo el diálogo de Configuración y sacaba una barra horizontal. Aquí el
      combo se adapta al espacio disponible (el texto largo se recorta con "…")
      y la lista desplegable sí se abre con el ancho necesario para leer todo.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(96)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        # Si el texto actual se recorta con "…", el tooltip lo muestra completo.
        self.currentIndexChanged.connect(lambda _i: self.setToolTip(self.currentText()))
        self.setToolTip(self.currentText())

    def wheelEvent(self, event):
        # Qt cambia el valor de un combo con la rueda del mouse aunque NO tenga
        # el foco. Dentro de un diálogo con scroll (Configuración), pasar el
        # cursor por encima mientras se desplaza el diálogo cambiaba el estilo
        # del panel lateral, el tamaño de letra, el servicio de scrobbling...
        # sin que el usuario lo notara, y se guardaba al aceptar. Ahora el
        # combo ignora la rueda (el evento sube al área de desplazamiento); se
        # cambia con clic o con el teclado.
        event.ignore()

    def showPopup(self):
        # Lista al menos tan ancha como su opción más larga (+ márgenes del QSS).
        view = self.view()
        want = view.sizeHintForColumn(0) + 32
        view.setMinimumWidth(max(self.width(), want))
        super().showPopup()

    def paintEvent(self, event):
        # Marco y fondo los dibuja el estilo (con el QSS); la etiqueta la
        # dibujamos nosotros para poder recortarla con "…" (Qt la corta en seco).
        sp = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""
        sp.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, self)
        if text and field.width() > 8:
            sp.setFont(self.font())
            sp.setPen(QColor(*(Palette.TEXT if self.isEnabled() else Palette.TEXT_FAINT)))
            elided = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, field.width() - 2)
            sp.drawText(field.adjusted(1, 0, -1, 0),
                        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)
        sp.end()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            color = QColor(*Palette.TEXT_FAINT)
        elif self.hasFocus() or self.underMouse():
            color = QColor(*Palette.TEXT)
        else:
            color = QColor(*Palette.TEXT_DIM)
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx = self.width() - 15.0
        cy = self.height() / 2.0
        painter.drawPolyline([QPointF(cx - 4.0, cy - 2.0), QPointF(cx, cy + 2.0), QPointF(cx + 4.0, cy - 2.0)])
        painter.end()


class NoWheelSlider(QSlider):
    """QSlider que ignora la rueda del mouse: igual que los combos, dentro de
    un diálogo con scroll el deslizador cambiaba de valor (la opacidad de la
    ventana) cada vez que el cursor lo cruzaba al desplazar. Arrastrar, hacer
    clic y las flechas del teclado siguen funcionando."""

    def wheelEvent(self, event):
        event.ignore()


class _LyricsCanvas(QWidget):
    """Lienzo de letra pintado a mano (reemplaza a la lista de QLabel + QScrollArea).

    Por qué: antes cada línea era un QLabel al que se le cambiaba el
    setStyleSheet (y el tamaño de letra, 12.5px -> 15px) cada vez que pasaba a
    ser la línea activa. Eso re-pulía el widget, reflujaba el texto envuelto
    (cambiaba el alto de la línea y empujaba todo lo de abajo) y el scroll se
    calculaba ANTES de que el layout se asentara, así que el centrado saltaba.
    Aquí todas las líneas se miden UNA vez con la misma fuente; la línea activa
    solo se dibuja escalada y con más color (transform del painter: cero
    reflujo), y el resaltado + el scroll avanzan con una única animación.
    """

    _MARGIN_X = 18
    _MARGIN_TOP = 36
    _MARGIN_BOTTOM = 46
    _LINE_GAP = 15
    _ACTIVE_SCALE = 0.16      # la línea activa se dibuja 16 % más grande
    _EDGE_FADE_PX = 46        # las líneas cerca del borde se desvanecen
    _MANUAL_HOLD_S = 3.0      # tras usar la rueda, no se re-centra solo durante 3 s

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Letra")
        self._texts: list[str] = []
        self._synced = False
        self._layouts: list = []
        self._heights: list[float] = []
        self._tops: list[float] = []
        self._content_h = 0.0
        self._layout_width = -1

        self._cur = -1
        self._prev = -1
        self._t = 1.0
        self._scroll = 0.0
        self._scroll_from = 0.0
        self._scroll_target = 0.0
        self._manual_until = 0.0

        px = max(10, round(12.5 * theme_module.DEFAULT_FONT_SCALE))
        self._font = QFont(FONT_BODY)
        self._font.setPixelSize(px)
        self._font.setWeight(QFont.Weight.DemiBold)

        self._anim = QPropertyAnimation(self, b"transition", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------ propiedad
    def _get_transition(self) -> float:
        return self._t

    def _set_transition(self, value: float):
        self._t = value
        self._scroll = self._scroll_from + (self._scroll_target - self._scroll_from) * value
        self.update()

    transition = pyqtProperty(float, _get_transition, _set_transition)

    # ------------------------------------------------------------- contenido
    def clear(self):
        self.set_lines([], False)

    def set_lines(self, texts: list, synced: bool):
        self._anim.stop()
        self._texts = list(texts)
        self._synced = synced
        self._cur = self._prev = -1
        self._t = 1.0
        self._scroll = self._scroll_from = self._scroll_target = 0.0
        self._manual_until = 0.0
        self._layout_width = -1          # fuerza re-medir en el próximo paint
        self._layouts, self._heights, self._tops = [], [], []
        self._content_h = 0.0
        self.setAccessibleDescription("")
        self.update()

    def has_lines(self) -> bool:
        return bool(self._texts)

    def _ensure_layout(self):
        w = self.width()
        if w == self._layout_width and self._layouts:
            return
        self._layout_width = w
        wrap = max(40.0, (w - 2 * self._MARGIN_X) / (1.0 + self._ACTIVE_SCALE))
        self._layouts, self._heights, self._tops = [], [], []
        y = float(self._MARGIN_TOP)
        for text in self._texts:
            lay = QTextLayout(text, self._font)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapMode.WordWrap)
            lay.setTextOption(opt)
            lay.beginLayout()
            h = 0.0
            while True:
                line = lay.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(wrap)
                line.setPosition(QPointF(0.0, h))
                h += line.height()
            lay.endLayout()
            self._layouts.append(lay)
            self._heights.append(h)
            self._tops.append(y)
            y += h + self._LINE_GAP
        self._content_h = (y - self._LINE_GAP if self._texts else 0.0) + self._MARGIN_BOTTOM

    def _max_scroll(self) -> float:
        return max(0.0, self._content_h - self.height())

    def _target_for(self, idx: int) -> float:
        if not (0 <= idx < len(self._tops)):
            return self._scroll
        center = self._tops[idx] + self._heights[idx] / 2.0
        return max(0.0, min(center - self.height() / 2.0, self._max_scroll()))

    # ------------------------------------------------------------ resaltado
    def set_current(self, idx: int):
        if idx == self._cur:
            return
        self._ensure_layout()
        self._prev, self._cur = self._cur, idx
        if 0 <= idx < len(self._texts):
            self.setAccessibleDescription(self._texts[idx])
        self._scroll_from = self._scroll
        if time.monotonic() < self._manual_until:
            self._scroll_target = self._scroll      # el usuario está leyendo: no se lo movemos
        else:
            self._scroll_target = self._target_for(idx)
        self._anim.stop()
        self._t = 0.0
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _emphasis(self, i: int) -> float:
        if not self._synced:
            return 0.0
        e = 0.0
        if i == self._cur:
            e += self._t
        if i == self._prev:
            e += 1.0 - self._t
        return min(1.0, e)

    # -------------------------------------------------------------- eventos
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._layouts:
            self._ensure_layout()
            self._scroll = self._scroll_from = self._scroll_target = min(
                self._target_for(self._cur) if self._cur >= 0 else self._scroll,
                self._max_scroll())

    def wheelEvent(self, event):
        self._ensure_layout()
        if self._max_scroll() <= 0:
            event.ignore()          # no hay nada que desplazar: que suba (zoom de la ventana)
            return
        step = event.angleDelta().y() / 120.0 * 60.0
        self._scroll = max(0.0, min(self._scroll - step, self._max_scroll()))
        self._scroll_from = self._scroll_target = self._scroll
        self._manual_until = time.monotonic() + self._MANUAL_HOLD_S
        self.update()
        event.accept()

    # --------------------------------------------------------------- pintura
    def paintEvent(self, event):
        if not self._texts:
            return
        self._ensure_layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        view_h = float(self.height())
        dim = Palette.c(Palette.TEXT_DIM)
        bright = Palette.c(Palette.TEXT)
        plain_color = Palette.c(Palette.TEXT)
        fade_px = float(self._EDGE_FADE_PX)

        for i, lay in enumerate(self._layouts):
            h = self._heights[i]
            top = self._tops[i] - self._scroll
            if top + h * (1.0 + self._ACTIVE_SCALE) < 0 or top > view_h:
                continue
            e = self._emphasis(i)
            color = _lerp_color(dim, bright, e) if self._synced else plain_color
            center = top + h / 2.0
            edge = max(0.0, min(center, view_h - center))
            k = min(1.0, edge / fade_px)
            k = k * k * (3.0 - 2.0 * k)               # smoothstep
            painter.save()
            painter.setOpacity(0.35 + 0.65 * k)
            s = 1.0 + self._ACTIVE_SCALE * e
            painter.translate(self._MARGIN_X, center)
            painter.scale(s, s)
            painter.translate(0.0, -h / 2.0)
            painter.setPen(color)
            lay.draw(painter, QPointF(0.0, 0.0))
            painter.restore()

        # Indicador de scroll fino (solo si la letra es más larga que el panel).
        ms = self._max_scroll()
        if ms > 0:
            track_h = view_h - 16.0
            thumb_h = max(24.0, track_h * view_h / self._content_h)
            thumb_y = 8.0 + (track_h - thumb_h) * (self._scroll / ms)
            painter.setOpacity(1.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 46))
            painter.drawRoundedRect(QRectF(self.width() - 5.0, thumb_y, 3.0, thumb_h), 1.5, 1.5)
        painter.end()


class LyricsPanel(QWidget):
    """Panel de letra reutilizable (se usa tanto en el diálogo emergente
    como incrustado junto a la carátula en el reproductor completo).

    Estados: cargando (puntos animados), error, no encontrada,
    instrumental, y letra (con resaltado + scroll animado de la línea
    actual si la letra viene sincronizada). La letra se pinta en un
    _LyricsCanvas (ver arriba); el resto de la API pública es la de siempre.
    """

    def __init__(self, lyrics_loader, parent=None):
        super().__init__(parent)
        self._loader = lyrics_loader
        self._loader.lyricsReady.connect(self._on_ready)
        self._key = None
        self._synced = None
        self._times: list[float] = []
        self._plain_text = ""
        self._current_index = -1
        # Última canción pedida (para el botón de recarga) y espera para no
        # buscar con metadatos a medias al cambiar de canción: la extensión
        # manda título y artista en mensajes separados.
        self._cur = None
        self._pending = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_pending_track)

        # --- Interpolación local de la posición ---
        # `set_position()` solo se llama cuando llega un nuevo dato "real"
        # desde el backend (en la práctica el reproductor/extensión suele
        # mandar la posición redondeada al segundo). Entre una actualización
        # real y la siguiente se estima la posición con el reloj, igual que
        # hacen Spotify/Musixmatch; cada dato real vuelve a anclar la
        # estimación, así que nunca se acumula desvío.
        self._last_real_position = 0.0
        self._last_real_time = None      # time.monotonic() del último dato real
        self._is_playing = False
        self._interp_timer = QTimer(self)
        self._interp_timer.setInterval(100)  # 10fps: de sobra para texto, barato en CPU
        self._interp_timer.timeout.connect(self._on_interp_tick)

        self._build_ui()
        self._show_message("mic", "Reproduce algo para ver la letra aquí.")

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedLayout()
        outer.addLayout(self.stack)

        # --- página de mensaje (cargando / error / vacío / instrumental) ---
        self.message_page = QWidget()
        self.message_page.setStyleSheet("background: transparent;")
        mlayout = QVBoxLayout(self.message_page)
        mlayout.setContentsMargins(18, 16, 18, 16)
        mlayout.addStretch(1)

        dots_row = QHBoxLayout()
        self.dots = PulsingDots(self.message_page)
        dots_row.addStretch(1)
        dots_row.addWidget(self.dots)
        dots_row.addStretch(1)
        mlayout.addLayout(dots_row)

        icon_row = QHBoxLayout()
        self.message_icon = IconButton("mic", size=42, icon_scale=0.5, bg=None)
        self.message_icon.setEnabled(False)  # puramente decorativo
        icon_row.addStretch(1)
        icon_row.addWidget(self.message_icon)
        icon_row.addStretch(1)
        mlayout.addLayout(icon_row)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 11px; background: transparent;"
        )
        mlayout.addWidget(self.message_label)

        # Reintentar: solo en los estados de error / "no encontrada".
        reload_row = QHBoxLayout()
        self.reload_btn = IconButton("refresh", size=36, icon_scale=0.55)
        self.reload_btn.setToolTip("Buscar la letra de nuevo")
        self.reload_btn.clicked.connect(self.reload)
        self.reload_btn.setVisible(False)
        reload_row.addStretch(1)
        reload_row.addWidget(self.reload_btn)
        reload_row.addStretch(1)
        mlayout.addSpacing(6)
        mlayout.addLayout(reload_row)
        mlayout.addStretch(1)
        self.stack.addWidget(self.message_page)

        # --- página de letra ---
        self.canvas = _LyricsCanvas()
        self.stack.addWidget(self.canvas)

    # --------------------------------------------------------------- estado
    def _show_message(self, icon_name: str, text: str, loading: bool = False, retry: bool = False):
        self.reload_btn.setVisible(bool(retry) and self._cur is not None)
        self.message_icon.set_icon(icon_name)
        self.message_icon.setVisible(not loading)
        self.dots.setVisible(loading)
        if loading:
            self.dots.start()
        else:
            self.dots.stop()
        self.message_label.setText(text)
        self.stack.setCurrentWidget(self.message_page)

    def _show_lyrics_page(self):
        self.dots.stop()
        self.stack.setCurrentWidget(self.canvas)

    def set_track(self, artist: str, title: str, album: str = "", duration_seconds: int = 0):
        import lyrics as lyrics_module

        self._synced = None
        self._times = []
        self._plain_text = ""
        self._current_index = -1
        self._last_real_position = 0.0
        self._last_real_time = None
        self.canvas.clear()
        self._sync_interp_timer()  # sin letra sincronizada todavía: no hay nada que interpolar

        self._debounce.stop()
        self._pending = None
        if not artist or not title:
            self._cur = None
            self._key = None
            self._show_message("mic", "Reproduce algo para ver la letra aquí.")
            return

        self._cur = (artist, title, album, duration_seconds)
        self._key = lyrics_module._cache_key(artist, title)
        self._show_message("mic", "Buscando letra…", loading=True)
        self._loader.request(artist, title, album, duration_seconds)

    def set_track_debounced(self, artist: str, title: str, album: str = "",
                            duration_seconds: int = 0, delay_ms: int = 450):
        """Como set_track, pero espera `delay_ms` sin más cambios antes de
        buscar. Vaciar la canción es inmediato."""
        if not artist or not title:
            self.set_track(artist, title, album, duration_seconds)
            return
        if self._cur and self._cur[:2] == (artist, title):
            self._debounce.stop()      # volvió a la que ya está cargada
            self._pending = None
            return
        if self._cur is None and self._pending is None:
            # Primera carga (panel recién abierto o app recién iniciada): no hay una
            # canción anterior con metadatos a medias, así que no hay nada que esperar.
            self.set_track(artist, title, album, duration_seconds)
            return
        self._pending = (artist, title, album, duration_seconds)
        self._debounce.start(delay_ms)  # reinicia la espera con cada cambio

    def _apply_pending_track(self):
        args, self._pending = self._pending, None
        if args:
            self.set_track(*args)

    def reload(self):
        """Botón de recarga: vuelve a buscar la letra de la canción actual,
        saltándose la caché (incluida una respuesta previa de 'no encontrada')."""
        if self._cur is None:
            return
        import lyrics as lyrics_module
        artist, title, album, duration_seconds = self._cur
        self._key = lyrics_module._cache_key(artist, title)
        self._show_message("mic", "Buscando letra…", loading=True)
        self._loader.request(artist, title, album, duration_seconds, force=True)

    def _on_ready(self, key: str, result):
        if key != self._key:
            return
        if result is None:
            self._show_message("note", "No se encontró letra para esta canción.", retry=True)
        elif "error" in result:
            self._show_message("alert", str(result.get("error") or "No se pudo buscar la letra."),
                               retry=True)
        elif result.get("instrumental"):
            self._show_message("mic", "Instrumental — esta canción no tiene letra.")
        else:
            self._plain_text = result.get("plain") or ""
            self._synced = result.get("synced")
            if not self._plain_text and not self._synced:
                self._show_message("note", "No se encontró letra para esta canción.", retry=True)
                return
            self._populate_lines()
            self._show_lyrics_page()
            self._sync_interp_timer()  # ahora sí puede haber letra sincronizada para interpolar
            if self._last_real_time is not None:
                # Ya teníamos una posición real (llegó antes que la letra);
                # aplicamos el resaltado de inmediato en vez de esperar al
                # próximo tick de interpolación.
                self._apply_position(self._last_real_position)

    def _populate_lines(self):
        if self._synced:
            texts = [text for _, text in self._synced]
            self._times = [float(t) for t, _ in self._synced]
        else:
            texts = [line for line in self._plain_text.splitlines()]
            self._times = []
        if not texts:
            texts = [self._plain_text or ""]
        texts = [t.strip() if t.strip() else "♪" for t in texts]
        self._current_index = -1
        self.canvas.set_lines(texts, bool(self._synced))

    # ------------------------------------------------------ sincronización
    def set_position(self, seconds: float):
        """Punto de entrada 'autoritativo': se llama cuando llega una
        posición REAL desde el backend. Ancla la estimación local (para
        que la interpolación entre ticks nunca acumule desvío) y aplica el
        resaltado de inmediato."""
        self._last_real_position = seconds
        self._last_real_time = time.monotonic()
        self._apply_position(seconds)

    def set_playing(self, is_playing: bool):
        """Arranca/detiene la interpolación local entre actualizaciones
        reales de posición. Se re-ancla SIEMPRE al cambiar de estado para que,
        al reanudar, la interpolación arranque desde la última posición real
        conocida y no desde donde se había quedado extrapolando."""
        if is_playing == self._is_playing:
            return
        self._is_playing = is_playing
        self._last_real_time = time.monotonic()
        self._sync_interp_timer()

    def _sync_interp_timer(self):
        should_run = self._is_playing and bool(self._synced) and self.isVisible()
        if should_run and not self._interp_timer.isActive():
            self._interp_timer.start()
        elif not should_run and self._interp_timer.isActive():
            self._interp_timer.stop()

    def hideEvent(self, event):
        # Defensivo, además de set_playing(False): sea cual sea el motivo
        # por el que este panel queda oculto, ningún timer interno debería
        # seguir gastando CPU sin que nadie lo esté viendo.
        self._interp_timer.stop()
        self.dots.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        self._sync_interp_timer()
        if self.stack.currentWidget() is self.message_page and self.dots.isVisible():
            self.dots.start()
        super().showEvent(event)

    def _on_interp_tick(self):
        if self._last_real_time is None:
            return
        elapsed = time.monotonic() - self._last_real_time
        # Tope de seguridad: si dejan de llegar posiciones reales (red lenta,
        # backend caído, máquina suspendida...) la estimación no se aleja sin
        # límite del último dato real conocido.
        elapsed = min(elapsed, 5.0)
        self._apply_position(self._last_real_position + elapsed)

    def _apply_position(self, seconds: float):
        if not self._synced or not self._times or not self.canvas.has_lines():
            return
        # Búsqueda binaria (antes: recorrido lineal de toda la letra en cada
        # tick de 100 ms y en cada dato real del backend).
        idx = bisect.bisect_right(self._times, seconds) - 1
        if idx == self._current_index:
            return
        self._current_index = idx
        self.canvas.set_current(idx)


class PlatformPickerButton(QPushButton):
    """Texto plano con una flechita que abre un menú: en el pie de la ventana
    completa muestra el reproductor actual y permite abrir otro. Se estiliza
    por QSS igual que la etiqueta que reemplaza; `text()` devuelve el texto
    sin la flecha."""

    CARET = " \u25be"   # ▾

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._label = ""
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setText(text)

    def setText(self, text: str):
        self._label = text or ""
        shown = self._label or "Elegir reproductor"
        super().setText(shown + self.CARET)
        self.setAccessibleName(f"Reproductor: {shown}. Cambiar")

    def text(self) -> str:
        return self._label


class PlayingIndicator(QWidget):
    """Indicador de "sonando": cuatro barras tipo ecualizador, más grandes que las
    tres de antes (14x11 px casi no se veían), con degradado del acento y
    movimiento más orgánico (dos senos por barra, no uno). En cualquier otro
    estado (pausado, sin conexión...) vuelve a ser un punto estático. Con "reducir
    movimiento" no anima: muestra las barras quietas a media altura.
    Es puramente decorativo; no mide audio real."""

    _TICK_MS = 33             # ~30 fps: el movimiento se ve fluido, no a saltos
    _BAR_COUNT = 4
    _SIZE = (20, 16)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(*self._SIZE)
        self._color = QColor(*Palette.TEXT_FAINT)       # color de las barras animadas (acento dinámico)
        self._idle_color = QColor(*Palette.TEXT_FAINT)  # color del punto estático (semántico: conectado/pausado)
        self._playing = False
        self._t0 = time.monotonic()
        self._bar_heights = [0.45, 0.8, 0.6, 0.35]

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick)

    def set_color(self, rgb: tuple):
        c = QColor(*rgb)
        if c != self._color:
            self._color = c
            self.update()

    def set_idle_color(self, rgb: tuple):
        c = QColor(*rgb)
        if c != self._idle_color:
            self._idle_color = c
            self.update()

    def _animate(self) -> bool:
        import theme as _theme
        return self._playing and not _theme.REDUCED_MOTION

    def set_playing(self, playing: bool):
        if playing == self._playing:
            return
        self._playing = playing
        if self._animate():
            self._t0 = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()
            self._bar_heights = [0.45, 0.8, 0.6, 0.35]
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._animate() and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()      # oculta no hay quien la vea: sin repintados
        super().hideEvent(event)

    def _tick(self):
        t = time.monotonic() - self._t0     # reloj real: no se atrasa si Qt va justo
        for i in range(self._BAR_COUNT):
            # Dos senos de frecuencia distinta y fase propia por barra: no suben y
            # bajan a la vez ni con un patrón evidente (se ve más como un ecualizador real).
            a = math.sin(t * (4.6 + 0.9 * i) + i * 1.9)
            b = math.sin(t * (7.7 - 0.6 * i) + i * 0.7)
            self._bar_heights[i] = 0.2 + 0.8 * ((0.65 * a + 0.35 * b) * 0.5 + 0.5)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        if not self._playing:
            # Estado simple: un punto (color semántico: gris = sin conexión, azul = pausado...).
            painter.setBrush(self._idle_color)
            d = 7
            painter.drawEllipse(QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d))
            painter.end()
            return

        bar_w = 3.0
        gap = 1.9
        total_w = self._BAR_COUNT * bar_w + (self._BAR_COUNT - 1) * gap
        x = (self.width() - total_w) / 2
        base = self.height() - 1.0
        top_color = self._color.lighter(150)
        for h_ratio in self._bar_heights:
            bar_h = max(2.5, (self.height() - 2) * h_ratio)
            rect = QRectF(x, base - bar_h, bar_w, bar_h)
            # Resplandor tenue detrás de cada barra + degradado del acento a un tono más claro.
            glow = QColor(self._color)
            glow.setAlpha(60)
            painter.setBrush(glow)
            painter.drawRoundedRect(rect.adjusted(-1.2, -1.2, 1.2, 0.4), 2.0, 2.0)
            grad = QLinearGradient(rect.bottomLeft(), rect.topLeft())
            grad.setColorAt(0.0, self._color)
            grad.setColorAt(1.0, top_color)
            painter.setBrush(grad)
            painter.drawRoundedRect(rect, 1.4, 1.4)
            x += bar_w + gap
        painter.end()
