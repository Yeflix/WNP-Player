"""Diálogos secundarios: puerto, 'Acerca de', errores, dependencias faltantes y teclas."""
import contextlib
import unicodedata

from PyQt6 import sip
from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
    QPlainTextEdit, QApplication, QCheckBox, QScrollArea, QFrame, QSizePolicy, QComboBox, QGridLayout
)

from theme import Palette, FONT_BODY, FONT_MONO
from hotkeys import capture_from_event, combo_to_string, combo_to_display, combo_needs_modifier
from widgets import ElidedLabel, IconButton, HistoryCard, ArrowComboBox, NoWheelSlider, sync_accessible_names


class _DialogBase(QDialog):
    def __init__(self, parent=None, title="", height=None, width=320):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Sin esto, cerrar un diálogo (aceptar, cancelar o la X) solo lo
        # oculta — el objeto de Qt queda vivo para siempre como hijo del
        # padre, porque nada más lo libera. En una sesión larga, abrir
        # Configuración/Historial/Estadísticas varias veces iba
        # acumulando diálogos "fantasma" sin destruir nunca: una fuga de
        # memoria real y creciente. WA_DeleteOnClose hace que Qt programe
        # su destrucción de verdad al cerrarse (self.accept()/reject()/X
        # pasan igual por QDialog.done(), así que cubre los tres casos).
        # La destrucción queda diferida al próximo ciclo del event loop
        # (deleteLater), no es inmediata — leer dlg.result_xxx justo
        # después de exec() sigue siendo seguro.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setModal(True)
        self._inherit_topmost(parent)
        self._title = title
        self._fixed_height = height
        if height:
            self.setFixedHeight(height)
        self.setFixedWidth(width)

    def _inherit_topmost(self, parent):
        """Un diálogo nunca debe quedar DETRÁS de una ventana de YefriPlayer que
        esté "siempre visible" (la ventana principal con esa opción, la compacta
        y el panel lateral siempre lo están). Windows deja la ventana propia por
        encima de su dueña solo dentro del mismo nivel: un diálogo normal cuyo
        dueño es "siempre visible" quedaba tapado por él y parecía que
        Configuración no abría. Si hay una ventana así visible, el diálogo
        también se marca como "siempre visible"."""
        top = Qt.WindowType.WindowStaysOnTopHint
        needs = False
        if parent is not None and bool(parent.window().windowFlags() & top):
            needs = True
        else:
            for w in QApplication.topLevelWidgets():
                if w is not self and w.isVisible() and bool(w.windowFlags() & top):
                    needs = True
                    break
        if needs:
            self.setWindowFlag(top, True)

    def showEvent(self, event):
        self._fit_to_content_and_screen()
        super().showEvent(event)
        if not getattr(self, "_a11y_synced", False):
            self._a11y_synced = True
            sync_accessible_names(self)
        # Primer plano real (no solo "visible"): se hace al terminar de mostrarse.
        QTimer.singleShot(0, self._bring_to_front)

    def _bring_to_front(self):
        try:
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass        # el diálogo ya se cerró

    def _fit_to_content_and_screen(self):
        """Altura del diálogo:
        - Sin altura explícita: la que pide el contenido AL ANCHO del diálogo.
          Antes un QDialog con textos que se ajustan a varias líneas calculaba
          su alto sin conocer el ancho final, y "Acerca de" salía con el texto
          aplastado y cortado, o el de mensajes con un hueco enorme.
        - Con altura explícita: se respeta, pero nunca más alta que la pantalla
          (en pantallas de baja resolución o con mucha escala de Windows,
          Configuración y los asistentes se salían por abajo y los botones
          Guardar/Cancelar quedaban inalcanzables)."""
        lay = self.layout()
        if lay is None:
            return
        if not self._fixed_height:
            w = self.width()
            h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
            h = max(h, lay.minimumSize().height())
            self.setFixedHeight(h)
        screen = (self.screen() or QApplication.primaryScreen())
        if screen is not None:
            limit = screen.availableGeometry().height() - 48
            if self.height() > limit:
                self.setFixedHeight(max(320, limit))

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPainterPath, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()),
                             float(rect.height()), 16, 16)
        painter.fillPath(path, QColor(*Palette.BG_BASE, 255))   # opaco: antes alpha 250 dejaba ver lo de atrás
        painter.setPen(QColor(255, 255, 255, 30))
        painter.drawPath(path)


class PortDialog(_DialogBase):
    """Permite cambiar el puerto en el que escucha el servidor WebNowPlaying."""

    def __init__(self, current_port: int, parent=None):
        super().__init__(parent, title="Puerto de conexión")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel("Puerto de conexión")
        title.setStyleSheet(f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
                             f"font-size: 14px; font-weight: 600; background: transparent;")
        layout.addWidget(title)

        hint = QLabel(
            "Este es el puerto que debe usar la extensión WebNowPlaying "
            "del navegador como 'adaptador personalizado'."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                            f"font-size: 11px; background: transparent;")
        layout.addWidget(hint)

        self.input = QLineEdit(str(current_port))
        self.input.setValidator(_int_validator())
        layout.addWidget(self.input)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("dialogButton")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Guardar")
        ok_btn.setObjectName("dialogButtonAccent")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def selected_port(self) -> int:
        try:
            return int(self.input.text())
        except ValueError:
            return 0


def _int_validator():
    from PyQt6.QtGui import QIntValidator
    return QIntValidator(1, 65535)


from version import APP_VERSION, AUTHOR


class AboutDialog(_DialogBase):
    def __init__(self, port: int, parent=None):
        super().__init__(parent, title="Acerca de")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("YefriPlayer")
        title.setStyleSheet(f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
                             f"font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(title)
        kind = QLabel("Controlador multimedia · no reproduce audio")
        kind.setStyleSheet(f"color: rgb{Palette.ACCENT_A}; font-family:'{FONT_BODY}'; "
                           f"font-size: 10.5px; font-weight: 600; background: transparent;")
        layout.addWidget(kind)

        import version as _v
        body = QLabel(
            f"{_v.APP_DESCRIPTION}\n\n{_v.platforms_text()}\n\n"
            f"Versión {APP_VERSION} · desarrollado por {AUTHOR}.\n"
            f"Servidor escuchando en el puerto {port}.\n\n"
            "Instala la extensión 'WebNowPlaying' en tu navegador y agrega "
            "este puerto como adaptador personalizado para conectarte."
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                            f"font-size: 11px; background: transparent;")
        layout.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton("Cerrar")
        ok_btn.setObjectName("dialogButtonAccent")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)


class MessageDialog(_DialogBase):
    """Diálogo genérico de un solo mensaje (usado para avisos de
    dependencias faltantes, y reutilizable para lo que haga falta)."""

    def __init__(self, title: str, body: str, parent=None,
                 accent_button_text: str = "Entendido"):
        super().__init__(parent, title=title, width=380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 15px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(title_label)

        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_MONO}'; "
            f"font-size: 11px; background: transparent;"
        )
        layout.addWidget(body_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(accent_button_text)
        ok_btn.setObjectName("dialogButtonAccent")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)


class UpdateDialog(_DialogBase):
    """Aviso de versión nueva (updater.py) con tres salidas:
    `result_action` = "update" | "later" | "skip"."""

    def __init__(self, new_version: str, notes: str = "", installed: bool = True, parent=None):
        super().__init__(parent, title="Actualización disponible", width=400)
        self.result_action = "later"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title_label = QLabel(f"YefriPlayer {new_version} está disponible")
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 15px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(title_label)

        import version as _v
        how = ("Se descargará el instalador y se abrirá; cerrará esta copia y conservará tu "
               "configuración." if installed else
               "Se abrirá la página de la versión en el navegador para descargarla.")
        intro = QLabel(f"Tienes la {_v.APP_VERSION}. {how}")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 11px; background: transparent;"
        )
        layout.addWidget(intro)

        if notes:
            box = QPlainTextEdit(notes)
            box.setReadOnly(True)
            box.setFixedHeight(130)
            box.setAccessibleName("Novedades de la versión")
            box.setStyleSheet(
                f"QPlainTextEdit {{ background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,20); "
                f"border-radius: 8px; padding: 6px; color: rgb{Palette.TEXT_DIM}; "
                f"font-family:'{FONT_BODY}'; font-size: 10.5px; }}"
            )
            layout.addWidget(box)

        btn_row = QHBoxLayout()
        skip_btn = QPushButton("Omitir esta versión")
        skip_btn.setObjectName("dialogButton")
        skip_btn.clicked.connect(lambda: self._finish("skip"))
        btn_row.addWidget(skip_btn)
        btn_row.addStretch(1)
        later_btn = QPushButton("Ahora no")
        later_btn.setObjectName("dialogButton")
        later_btn.clicked.connect(lambda: self._finish("later"))
        btn_row.addWidget(later_btn)
        go_btn = QPushButton("Actualizar" if installed else "Abrir descarga")
        go_btn.setObjectName("dialogButtonAccent")
        go_btn.setDefault(True)
        go_btn.clicked.connect(lambda: self._finish("update"))
        btn_row.addWidget(go_btn)
        layout.addLayout(btn_row)

    def _finish(self, action: str):
        self.result_action = action
        self.accept()


class ErrorDialog(_DialogBase):
    """Aviso amigable de error inesperado, con el detalle técnico visible
    (para poder copiarlo y reportarlo) pero sin protagonismo."""

    def __init__(self, details: str, parent=None):
        super().__init__(parent, title="Ha ocurrido un error", width=400)
        self._details = details
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Ha ocurrido un error inesperado")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 15px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(title)

        body = QLabel(
            "Algo salió mal, pero la aplicación sigue funcionando. El "
            "detalle técnico quedó guardado para poder revisarlo después."
        )
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 11px; background: transparent;"
        )
        layout.addWidget(body)

        self.details_box = QPlainTextEdit()
        self.details_box.setReadOnly(True)
        self.details_box.setPlainText(details)
        self.details_box.setFixedHeight(130)
        layout.addWidget(self.details_box)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copiar detalles")
        copy_btn.setObjectName("dialogButton")
        copy_btn.clicked.connect(self._copy)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("dialogButtonAccent")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _copy(self):
        QApplication.clipboard().setText(self._details)


class _CaptureButton(QPushButton):
    """Botón que, al hacer clic, se pone a 'escuchar' la siguiente
    combinación de teclas que el usuario presione (Esc para cancelar)."""

    comboCaptured = pyqtSignal(object)  # (mods:set, key_name:str) | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hotkeyCapture")
        self._listening = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._start_listening)

    def _start_listening(self):
        self._listening = True
        self._repolish("hotkeyCaptureActive")
        self.setText("Presiona una combinación… (Esc cancela)")
        self.setFocus()

    def _stop_listening(self):
        self._listening = False
        self._repolish("hotkeyCapture")

    def _repolish(self, object_name: str):
        self.setObjectName(object_name)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def keyPressEvent(self, event):
        if not self._listening:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Escape:
            self._stop_listening()
            self.comboCaptured.emit(None)
            return
        result = capture_from_event(event)
        if result is None:
            return  # todavía no hay una tecla "real" (p.ej. solo Ctrl solo)
        self._stop_listening()
        self.comboCaptured.emit(result)


class HotkeyDialog(_DialogBase):
    """Deja elegir y grabar la combinación de teclas para cada acción, en
    vez de imponer una fija — en Windows muchas combinaciones ya están
    tomadas por el sistema o por otros programas."""

    ACTIONS = [
        ("play_pause", "Reproducir / Pausar"),
        ("next", "Siguiente"),
        ("previous", "Anterior"),
    ]

    def __init__(self, config, hotkey_manager, parent=None):
        super().__init__(parent, title="Teclas multimedia", width=380)
        self.config = config
        self.manager = hotkey_manager
        self.result_enabled = config.hotkeys_enabled
        self.result_combos = {
            "play_pause": config.hotkey_play_pause,
            "next": config.hotkey_next,
            "previous": config.hotkey_previous,
        }
        self._pending = dict(self.result_combos)
        self._buttons = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Teclas multimedia globales")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 14px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "Funcionan aunque la ventana no tenga el foco. Windows ya usa "
            "muchas combinaciones, así que elige la tuya: haz clic en un "
            "campo y presiona la combinación que quieras usar."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10.5px; background: transparent;"
        )
        layout.addWidget(hint)

        self.enabled_check = QCheckBox("Activar teclas multimedia globales")
        self.enabled_check.setChecked(config.hotkeys_enabled)
        layout.addWidget(self.enabled_check)

        if not hotkey_manager.available:
            note = QLabel("Esta función solo está disponible en Windows.")
            note.setWordWrap(True)
            note.setStyleSheet(
                f"color: rgb{Palette.ERROR}; font-family:'{FONT_BODY}'; "
                f"font-size: 10.5px; background: transparent;"
            )
            layout.addWidget(note)

        for action, label_text in self.ACTIONS:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(label_text)
            label.setFixedWidth(108)
            label.setStyleSheet(
                f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
                f"font-size: 11.5px; font-weight: 600; background: transparent;"
            )
            row.addWidget(label)

            btn = _CaptureButton()
            btn.setText(combo_to_display(self._pending[action]))
            btn.comboCaptured.connect(
                lambda result, a=action, b=btn: self._on_captured(a, b, result)
            )
            row.addWidget(btn, 1)
            self._buttons[action] = btn
            layout.addLayout(row)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            f"color: rgb{Palette.ERROR}; font-family:'{FONT_BODY}'; "
            f"font-size: 10.5px; background: transparent;"
        )
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Quitar todas")
        clear_btn.setObjectName("dialogButton")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("dialogButton")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Guardar")
        save_btn.setObjectName("dialogButtonAccent")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_captured(self, action, button, result):
        if result is None:
            button.setText(combo_to_display(self._pending[action]))
            return
        mods, key_name = result
        combo = combo_to_string(mods, key_name)

        if combo_needs_modifier(combo) and not mods:
            self._warn(
                "Esa tecla necesita al menos un modificador (Ctrl, Alt, "
                "Mayús o Win) para no interferir con el resto del sistema."
            )
            button.setText(combo_to_display(self._pending[action]))
            return

        for other_action, other_combo in self._pending.items():
            if other_action != action and other_combo and other_combo == combo:
                self._warn("Esa combinación ya está asignada a otra acción de aquí mismo.")
                button.setText(combo_to_display(self._pending[action]))
                return

        self.warning_label.hide()
        self._pending[action] = combo
        button.setText(combo_to_display(combo))

    def _warn(self, text: str):
        self.warning_label.setText(text)
        self.warning_label.show()

    def _clear_all(self):
        for action, btn in self._buttons.items():
            self._pending[action] = ""
            btn.setText(combo_to_display(""))
        self.warning_label.hide()

    def _save(self):
        enabled = self.enabled_check.isChecked()

        if enabled and self.manager.available:
            # Intentamos registrar de verdad para detectar si Windows u otro
            # programa ya se adueñaron de alguna combinación — solo en ese
            # momento se sabe con certeza.
            self.manager.unregister_all()
            failed = []
            for action, label_text in self.ACTIONS:
                combo = self._pending[action]
                if not combo:
                    continue
                if not self.manager.register(action, combo):
                    failed.append(label_text)
            if failed:
                self.manager.unregister_all()
                # Restaurar los atajos que ya estaban guardados y funcionando:
                # si luego se pulsa "Cancelar" no deben quedar desregistrados.
                if self.config.hotkeys_enabled:
                    for action, combo in (("play_pause", self.config.hotkey_play_pause),
                                          ("next", self.config.hotkey_next),
                                          ("previous", self.config.hotkey_previous)):
                        if combo:
                            self.manager.register(action, combo)
                self._warn(
                    "No se pudo asignar: " + ", ".join(failed) + ". Es probable que "
                    "Windows u otro programa ya estén usando esa combinación."
                )
                return

        self.result_enabled = enabled
        self.result_combos = dict(self._pending)
        self.accept()


class _StatChip(QFrame):
    """Tarjetita chica con un número grande y una etiqueta abajo — para
    las 2-3 cifras destacadas arriba del panel de estadísticas."""

    def __init__(self, value_text: str, label_text: str, parent=None):
        super().__init__(parent)
        # Antes el selector era "QFrame { ... }" a secas. Un QLabel ES un QFrame,
        # así que la regla también encerraba en cajas (con fondo y borde) al
        # número y a la etiqueta de adentro: cajas dentro de cajas.
        self.setObjectName("statChip")
        self.setStyleSheet(
            "QFrame#statChip { background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,20); "
            "border-radius: 10px; }"
        )
        # Que las tres cifras se repartan el ancho y puedan encogerse en vez de
        # empujar el contenido más allá del área visible.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(2)
        value = QLabel(value_text)
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setWordWrap(True)
        value.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 15px; font-weight: 800; background: transparent;"
        )
        layout.addWidget(value)
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(label)


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
        f"font-size: 11.5px; font-weight: 700; background: transparent; "
        f"margin-top: 6px;"
    )
    return lbl


class StatsDialog(_DialogBase):
    """Panel de estadísticas de escucha: tiempo total, canción actual
    (si hay una sonando), y los tops de canciones/artistas. Todo se
    calcula al vuelo a partir del historial ya guardado (ver stats.py) —
    no hay nada nuevo que trackear en el backend."""

    def __init__(self, entries: list, current_title: str = "", current_artist: str = "",
                 parent=None, initial_scroll_pos: int = 0, totals: dict | None = None):
        """`totals`: estadísticas acumuladas (stats_store.summary()). Sin ellas
        (o si aún no hay), «todo el tiempo» se calcula del historial como antes."""
        super().__init__(parent, title="Estadísticas", width=420, height=560)
        import stats
        self.result_scroll_pos = initial_scroll_pos
        self._initial_scroll_pos = initial_scroll_pos

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        icon = IconButton("chart", size=28, icon_scale=0.5, bg=None)
        icon.setEnabled(False)
        header_row.addWidget(icon)
        title = QLabel("Estadísticas de escucha")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 14px; font-weight: 700; background: transparent;"
        )
        header_row.addWidget(title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        scroll = QScrollArea()
        self.scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.viewport().setStyleSheet("background: transparent;")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 4, 0)
        inner_layout.setSpacing(6)

        all_time = totals or stats.summary(entries, days=None)
        week = stats.summary(entries, days=7)

        # Si hay algo sonando ahora mismo, esto va primero — es lo más
        # "vivo" del panel, tal como se pidió: "has escuchado esta
        # canción X veces".
        if current_title:
            if totals:
                import stats_store
                times = stats_store.play_count(current_title, current_artist)
            else:
                times = stats.play_count(entries, current_title, current_artist)
            if times > 0:
                now_playing = QLabel(
                    f"🎵 Escuchaste <b>“{current_title}”</b> {times} "
                    f"{'vez' if times == 1 else 'veces'}."
                )
                now_playing.setWordWrap(True)
                now_playing.setStyleSheet(
                    f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; font-size: 11.5px; "
                    f"background: {Palette.rgba(Palette.ACCENT_A, 18)}; border-radius: 8px; padding: 10px;"
                )
                inner_layout.addWidget(now_playing)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        chips_row.addWidget(_StatChip(stats.shorten_duration(all_time["total_duration_text"]), "tiempo total"))
        chips_row.addWidget(_StatChip(str(week["plays"]), "canciones esta semana"))
        chips_row.addWidget(_StatChip(str(all_time["unique_songs"]), "canciones distintas"))
        inner_layout.addLayout(chips_row)
        since = self._since_text(all_time.get("since", "")) if totals else ""
        if since:
            since_label = QLabel(since)
            since_label.setStyleSheet(
                f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                f"font-size: 10.5px; background: transparent; padding: 0 2px;"
            )
            inner_layout.addWidget(since_label)

        inner_layout.addWidget(_section_label("Más escuchadas"))
        if all_time["top_songs"]:
            for song_title, song_artist, count in all_time["top_songs"]:
                card = HistoryCard(
                    song_title, song_artist, "",
                    f"{count}×",
                )
                inner_layout.addWidget(card)
        else:
            inner_layout.addWidget(self._empty_label("Todavía no hay suficiente historial."))

        inner_layout.addWidget(_section_label("Artistas top"))
        if all_time["top_artists"]:
            for artist_name, count in all_time["top_artists"]:
                row = ElidedLabel(f"{artist_name}  —  {count} {'canción' if count == 1 else 'canciones'}")
                row.setStyleSheet(
                    f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                    f"font-size: 11px; background: transparent; padding: 3px 2px;"
                )
                inner_layout.addWidget(row)
        else:
            inner_layout.addWidget(self._empty_label("Todavía no hay suficiente historial."))

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("dialogButtonAccent")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self.finished.connect(self._capture_scroll_pos)

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_scroll_pos and not getattr(self, "_scroll_restored", False):
            self._scroll_restored = True
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(self._initial_scroll_pos)
            )

    def _capture_scroll_pos(self):
        self.result_scroll_pos = self.scroll_area.verticalScrollBar().value()

    @staticmethod
    def _since_text(iso: str) -> str:
        import datetime
        try:
            day = datetime.datetime.fromisoformat(iso)
        except (TypeError, ValueError):
            return ""
        return f"Acumulado desde el {day:%d/%m/%Y} (sin el límite de 300 del historial)."

    @staticmethod
    def _empty_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 10.5px; background: transparent; padding: 4px 2px;"
        )
        return lbl


class RecentlyPlayedDialog(_DialogBase):
    """'Recién sonaron': el botón de 'listado' del reproductor completo
    (Fase 5). No es una cola real de lo que sigue —WebNowPlaying no
    expone eso, ver links.py para el porqué— así que se muestra lo único
    honesto que sí tenemos: lo último que sonó. Si en ese momento no hay
    nada reproduciéndose, tocar una entrada abre una búsqueda de esa
    canción en su plataforma (mismo mecanismo que tocar la carátula/
    título en la ventana principal)."""

    def __init__(self, entries: list, can_open: bool, parent=None, youtube_api_key: str = ""):
        super().__init__(parent, title="Recién sonaron", width=380, height=500)
        self.can_open = can_open
        self._youtube_api_key = youtube_api_key
        from youtube_api import VideoLinkResolver
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        self._video_resolver = VideoLinkResolver()
        self._video_resolver.linkResolved.connect(
            lambda url: QDesktopServices.openUrl(QUrl(url)) if url else None
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        icon = IconButton("clock", size=26, icon_scale=0.55, bg=None)
        icon.setEnabled(False)
        header_row.addWidget(icon)
        title = QLabel("Recién sonaron")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 14px; font-weight: 700; background: transparent;"
        )
        header_row.addWidget(title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        hint_text = (
            "Tocá una canción para reabrirla en su sitio."
            if can_open else
            "Hay algo sonando ahora — para no interrumpirlo, tocar la lista "
            "no hace nada mientras tanto."
        )
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;"
        )
        layout.addWidget(hint)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(list_widget)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(4)
        self.scroll_area.setWidget(list_widget)
        layout.addWidget(self.scroll_area, 1)

        self._populate(entries)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("dialogButtonAccent")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def _populate(self, entries: list):
        import history
        if not entries:
            empty = QLabel("Todavía no sonó nada en esta instalación.")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                f"font-size: 11.5px; background: transparent; padding: 40px 10px;"
            )
            self.list_layout.addWidget(empty)
            return

        # Más reciente primero, sin repetir la misma canción dos veces
        # seguidas visualmente (add_entry ya evita duplicar la inmediata
        # anterior al guardar, pero por las dudas con historiales viejos).
        for entry in reversed(entries[-40:]):
            card = HistoryCard(
                str(entry.get("title") or ""),
                str(entry.get("artist") or ""),
                str(entry.get("player_name") or ""),
                history.format_relative_time(str(entry.get("played_at") or "")),
                clickable=self.can_open,
            )
            if self.can_open:
                card.clicked.connect(lambda e=entry: self._open_entry(e))
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def _open_entry(self, entry: dict):
        self._video_resolver.resolve(
            str(entry.get("player_name") or ""),
            str(entry.get("artist") or ""),
            str(entry.get("title") or ""),
            self._youtube_api_key,
        )


class HistoryDialog(_DialogBase):
    """Lista de las últimas canciones reproducidas, como tarjetas."""

    def __init__(self, entries: list, parent=None, initial_scroll_pos: int = 0):
        super().__init__(parent, title="Historial", width=380, height=500)
        self.result_scroll_pos = initial_scroll_pos
        self._initial_scroll_pos = initial_scroll_pos
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        icon = IconButton("clock", size=28, icon_scale=0.55, bg=None)
        icon.setEnabled(False)
        header_row.addWidget(icon)
        title = QLabel("Historial de reproducción")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 14px; font-weight: 700; background: transparent;"
        )
        header_row.addWidget(title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar por título o artista...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(
            f"QLineEdit {{ background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,25); "
            f"border-radius: 8px; padding: 7px 10px; color: rgb{Palette.TEXT}; "
            f"font-family:'{FONT_BODY}'; font-size: 11.5px; }}"
        )
        self.search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.search_input)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(4)
        self.scroll_area.setWidget(self.list_container)
        layout.addWidget(self.scroll_area, 1)

        self._all_entries = entries
        self._populate(entries)

        # Debounce del filtro: reconstruir hasta 150 tarjetas en CADA
        # tecla presionada (con el historial lleno) se sentía como
        # tirones al escribir — medido en ~70-75ms por letra, muy por
        # encima de los 16ms de un frame. En vez de reconstruir de
        # inmediato, se espera a que el usuario deje de escribir por
        # 200ms; mientras tanto no se reconstruye nada. Es la misma
        # técnica que ya usa VolumeBar para no saturar de comandos de
        # red durante un arrastre — acá el "comando caro" es reconstruir
        # la lista en vez de un pedido de red.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_pending_filter)
        self._pending_filter_text = ""

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Borrar historial")
        clear_btn.setObjectName("dialogButton")
        clear_btn.setToolTip("Borra el historial y las estadísticas acumuladas (pide confirmación)")
        clear_btn.clicked.connect(self._clear_clicked)
        self.clear_btn = clear_btn
        btn_row.addWidget(clear_btn)
        export_btn = QPushButton("Exportar CSV…")
        export_btn.setObjectName("dialogButton")
        export_btn.setToolTip("Guarda el historial en un archivo CSV (se abre con Excel)")
        export_btn.clicked.connect(self._export_csv)
        self.export_btn = export_btn
        btn_row.addWidget(export_btn)
        btn_row.addStretch(1)
        # Borrar ahora también reinicia las estadísticas acumuladas: se pide un
        # segundo clic (en 4 s) en vez de borrar al primero.
        self._clear_armed = False
        self._clear_disarm_timer = QTimer(self)
        self._clear_disarm_timer.setSingleShot(True)
        self._clear_disarm_timer.setInterval(4000)
        self._clear_disarm_timer.timeout.connect(self._disarm_clear)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("dialogButtonAccent")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # Persistir posición de scroll (ítem #10): se restaura una vez que
        # el diálogo ya está mostrado y con su layout resuelto (ver
        # showEvent — restaurarla antes, en __init__, no "pega" porque el
        # QScrollArea todavía no conoce su rango real de scroll), y se
        # captura al cerrarse sin importar cómo (aceptar/cancelar/X).
        self.finished.connect(self._capture_scroll_pos)

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_scroll_pos and not getattr(self, "_scroll_restored", False):
            self._scroll_restored = True
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(self._initial_scroll_pos)
            )

    def _capture_scroll_pos(self):
        self.result_scroll_pos = self.scroll_area.verticalScrollBar().value()

    def _on_filter_changed(self, text: str):
        self._pending_filter_text = text
        self._filter_timer.start()  # reinicia el temporizador si ya estaba corriendo

    def _apply_pending_filter(self):
        self._populate(self._all_entries, filter_text=self._pending_filter_text)

    def _populate(self, entries: list, filter_text: str = ""):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # str(x or "") en vez de e.get("title", ""): si algún registro
        # viejo quedó guardado con un campo en None (en vez de faltante o
        # ""), .get(...) con default NO lo cubre —solo cubre la clave
        # ausente, no un valor None explícito— y un .lower() sobre None
        # tira la excepción que cerraba el diálogo (y con él la app).
        query = filter_text.strip().lower()
        if query:
            entries = [
                e for e in entries
                if query in str(e.get("title") or "").lower()
                or query in str(e.get("artist") or "").lower()
            ]

        if not entries:
            msg = (
                "No hay resultados para esa búsqueda."
                if query else "Sin canciones registradas todavía."
            )
            empty = QLabel(msg)
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                f"font-size: 11.5px; background: transparent; padding: 40px 10px;"
            )
            self.list_layout.addWidget(empty)
            return

        import history
        for entry in reversed(entries[-150:]):
            card = HistoryCard(
                str(entry.get("title") or ""),
                str(entry.get("artist") or ""),
                str(entry.get("player_name") or ""),
                history.format_relative_time(str(entry.get("played_at") or "")),
            )
            self.list_layout.addWidget(card)
        self.list_layout.addStretch(1)

    def _clear_clicked(self):
        if not self._clear_armed:
            self._clear_armed = True
            self.clear_btn.setText("¿Seguro? Pulsa otra vez")
            self._clear_disarm_timer.start()
            return
        self._disarm_clear()
        self._clear()

    def _disarm_clear(self):
        self._clear_armed = False
        self._clear_disarm_timer.stop()
        self.clear_btn.setText("Borrar historial")

    @staticmethod
    def default_export_path() -> str:
        import datetime
        from pathlib import Path
        home = Path.home()
        folder = next((d for d in (home / "Documents", home / "Documentos") if d.is_dir()), home)
        return str(folder / f"historial-yefriplayer-{datetime.date.today():%Y%m%d}.csv")

    def _export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        import history
        target, _ = QFileDialog.getSaveFileName(
            self, "Exportar historial", self.default_export_path(), "CSV (*.csv)")
        if not target:
            return
        if not target.lower().endswith(".csv"):
            target += ".csv"
        try:
            count = history.export_csv(target, self._all_entries)
        except OSError as exc:
            MessageDialog("No se pudo exportar", f"{target}\n\n{exc}", parent=self).exec()
            return
        MessageDialog("Historial exportado",
                      f"{count} {'canción' if count == 1 else 'canciones'} en:\n{target}",
                      parent=self).exec()

    def _clear(self):
        import history
        history.clear()
        self._all_entries = []
        self.search_input.clear()  # dispara _on_filter_changed, que reinicia el timer...
        self._filter_timer.stop()  # ...por eso se detiene DESPUÉS, no antes
        self._populate(self._all_entries)


def settings_size(avail_w: int, avail_h: int) -> tuple[int, int]:
    """Tamaño de Configuración para la pantalla disponible (px lógicos): grande en
    escritorio, y siempre dentro de la pantalla en portátiles con escala alta.
    Función pura (se prueba sin Qt)."""
    w = min(760, max(500, avail_w - 60))
    h = min(700, max(440, avail_h - 60))
    return min(w, max(320, avail_w - 16)), min(h, max(320, avail_h - 16))


class _ClickLabel(QLabel):
    """Texto de una casilla que, como el de una QCheckBox normal, la marca al pulsarlo."""

    def __init__(self, text: str, target, parent=None):
        super().__init__(text, parent)
        self._target = target
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self._target.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self._target.click()


class _RowCheckBox(QCheckBox):
    """Casilla sin texto propio (lo pone _CheckRow en una etiqueta que SÍ se
    ajusta al ancho). Al habilitarla o no, su etiqueta se atenúa igual."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title_label: QLabel | None = None
        self._title = title
        self.setAccessibleName(title)

    def label_text(self) -> str:
        return self._title

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        if self._title_label is not None:
            self._title_label.setEnabled(enabled)
            self._title_label.setStyleSheet(_CheckRow.title_style(enabled))


class _CheckRow(QWidget):
    """Casilla + título que se parte en varias líneas si no cabe + explicación
    debajo, alineada con el título. Una QCheckBox normal no parte su texto: con
    la ventana estrecha imponía su ancho y el formulario se cortaba por la
    derecha. Es UN solo elemento de la lista (la búsqueda lo oculta entero)."""

    @staticmethod
    def title_style(enabled: bool = True) -> str:
        color = Palette.TEXT if enabled else Palette.TEXT_FAINT
        return (f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: 11.5px; "
                f"background: transparent;")

    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("searchGroupStart", True)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(1)
        self.check = _RowCheckBox(title)
        grid.addWidget(self.check, 0, 0, Qt.AlignmentFlag.AlignTop)
        self.title_label = _ClickLabel(title, self.check)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(self.title_style())
        self.check._title_label = self.title_label
        grid.addWidget(self.title_label, 0, 1)
        self.hint_label = None
        if description:
            self.hint_label = QLabel(description)
            self.hint_label.setWordWrap(True)
            self.hint_label.setStyleSheet(
                f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
                f"font-size: 9.5px; background: transparent;")
            grid.addWidget(self.hint_label, 1, 1)
        grid.setColumnStretch(1, 1)


class _SettingsInner(QWidget):
    """Contenedor del formulario de Configuración que dibuja, DETRÁS de los
    ajustes, una tarjeta por sección (de su cabecera a la siguiente). Así cada
    ajuste sigue siendo un elemento suelto de la lista (la búsqueda los oculta
    uno a uno) y aun así se ven agrupados. Mientras se busca, no hay tarjetas."""

    PAD_X = 14          # sangría del contenido dentro de la tarjeta
    GAP = 12            # separación vertical entre tarjetas

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: list[QWidget] = []

    def set_sections(self, headers: list[QWidget]):
        self._sections = list(headers)
        self.update()

    PAD = 10            # aire de la tarjeta por encima de la cabecera y bajo el último ajuste

    def card_rects(self):
        """Una tarjeta por sección: desde su cabecera hasta el FINAL REAL del
        último ajuste visible de la sección (antes se cortaba en la cabecera
        siguiente y los últimos campos quedaban medio fuera de la tarjeta)."""
        from PyQt6.QtCore import QRectF
        heads = [h for h in self._sections if not sip.isdeleted(h)]
        if not heads or any(h.isHidden() for h in heads):
            return []
        lay = self.layout()
        if lay is None:
            return []
        head_ids = {id(h): n for n, h in enumerate(heads)}
        bottoms = [None] * len(heads)
        section = -1
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget()
            if w is not None and id(w) in head_ids:
                section = head_ids[id(w)]
            if section < 0:
                continue
            if w is None and item.layout() is None:
                continue                                  # separadores y el resorte final
            if w is not None and w.isHidden():
                continue
            g = item.geometry()
            if g.height() <= 0:
                continue
            bottoms[section] = g.bottom() if bottoms[section] is None else max(bottoms[section], g.bottom())
        rects = []
        for n, head in enumerate(heads):
            top = head.y() - self.PAD
            bottom = (bottoms[n] if bottoms[n] is not None else head.y() + head.height()) + self.PAD
            if bottom > top:
                rects.append(QRectF(2, top, self.width() - 12, bottom - top))
        return rects

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor
        rects = self.card_rects()
        if not rects:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(255, 255, 255, 18))
        painter.setBrush(QColor(255, 255, 255, 9))
        for r in rects:
            painter.drawRoundedRect(r, 12, 12)
        painter.end()


class SettingsDialog(_DialogBase):
    """Panel de configuración: puerto, comportamiento de ventana,
    notificaciones, accesos a teclas multimedia e historial, scrobbling y
    enlaces de YouTube.

    Con scroll interno (antes era un QVBoxLayout directo; ver README.md,
    sección 7): entre las nuevas secciones de scrobbling y YouTube
    y lo que ya había, el contenido pasó a ser más largo de lo que entra
    cómodo en una ventana fija sin desbordarse — mismo patrón que ya usan
    Historial/Estadísticas (QScrollArea transparente + contenedor interno),
    con los botones Cancelar/Guardar siempre fijos abajo, fuera del scroll."""

    def __init__(self, config, backend_port: int, open_hotkeys_callback,
                 open_history_callback, open_stats_callback, parent=None,
                 theme_bridge=None, theme_enabled: bool = True, hotkey_failures=None):
        # hotkey_failures: función que devuelve {acción: (combinación, motivo)} de las
        # teclas que Windows no dejó activar (ver HotkeyManager.failures).
        self._hotkey_failures = hotkey_failures or (lambda: {})
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry().height() if screen is not None else 700
        # Con la búsqueda y las secciones arriba hace falta algo más de alto; en pantallas bajas
        # (portátiles a 125-150 %) se acota para que el diálogo nunca se salga de la pantalla.
        avail_w = screen.availableGeometry().width() if screen is not None else 1000
        width, height = settings_size(avail_w, avail)
        super().__init__(parent, title="Configuración", width=width, height=height)
        self._narrow = width < 620          # barra lateral más estrecha
        self._compact = height < 560        # menos aire entre elementos
        self._theme_bridge = theme_bridge
        self.result_spotify_theme_enabled = theme_enabled
        self.result_spotify_theme_mode = ""
        self.result_port = backend_port
        self.result_always_on_top = config.always_on_top
        self.result_start_with_windows = getattr(config, "start_with_windows", True)
        self.result_start_minimized = config.start_minimized
        self.result_notifications = config.notifications_enabled
        self.result_empty_play_action = getattr(config, "empty_play_action", "ask")
        self.on_likes_changed = None   # lo fija el controlador
        self.result_bar_waves = getattr(config, "bar_waves_enabled", True)
        self._config_ref = config
        self.result_lyrics_panel_enabled = config.lyrics_panel_enabled
        self.result_audio_visualizer = bool(getattr(config, "audio_visualizer", False))
        self.result_visualizer_per_app = bool(getattr(config, "visualizer_per_app", True))
        self.result_taskbar_button = bool(getattr(config, "taskbar_button", False))
        self.result_check_updates = bool(getattr(config, "check_updates", True))
        self.result_window_opacity = config.window_opacity
        self.result_font_scale = config.font_scale
        self.result_ui_scale = config.ui_scale
        self.result_high_contrast = config.high_contrast
        self.result_player_theme = config.player_theme

        # ------------------------------------------------------------ esqueleto
        # Remasterizado (1.5): barra lateral (identidad, búsqueda y secciones) +
        # contenido en tarjetas, una por sección (las dibuja _SettingsInner por
        # detrás, así cada ajuste sigue siendo un elemento suelto de la lista y
        # la búsqueda funciona igual que antes).
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)
        body = QHBoxLayout()
        body.setSpacing(10 if self._narrow else 16)
        root.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(150 if self._narrow else 184)
        sidebar.setStyleSheet(
            "QFrame#settingsSidebar { background: rgba(255,255,255,0.035); "
            "border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; }")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 14, 12, 12)
        side.setSpacing(6)
        title = QLabel("Configuración")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 16px; font-weight: 700; background: transparent;"
        )
        side.addWidget(title)
        import version as _v
        kind = QLabel(f"{_v.APP_NAME} · {_v.APP_KIND.lower()}")
        kind.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;")
        side.addWidget(kind)
        side.addSpacing(6)
        self._sidebar_layout = side
        body.addWidget(sidebar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Las reglas apuntan solo al área, su viewport y el contenedor, por nombre: una
        # regla sin selector se heredaría a todos los controles y perderían su estilo.
        scroll.setObjectName("settingsScroll")
        scroll.viewport().setObjectName("settingsViewport")
        scroll.setStyleSheet(
            "QScrollArea#settingsScroll { background: transparent; border: none; }"
            "QWidget#settingsViewport, QWidget#settingsInner { background: transparent; }"
        )
        inner = _SettingsInner()
        inner.setObjectName("settingsInner")
        layout = QVBoxLayout(inner)
        # Margen interior: el contenido queda DENTRO de las tarjetas que se dibujan detrás.
        layout.setContentsMargins(_SettingsInner.PAD_X, 12, _SettingsInner.PAD_X + 8, 14)
        layout.setSpacing(8)
        self._nav_anchors: list[tuple[str, QWidget]] = []

        # ============================================================ General
        self._header(layout, "General", "General",
                     "Conexión con el navegador, cómo arranca y cómo avisa.")
        self._field_label(layout, "Puerto de conexión")
        self._hint(layout, "El que debe usar la extensión WebNowPlaying del navegador como "
                           "adaptador personalizado (por defecto 1234).")
        self.port_input = QLineEdit(str(backend_port))
        self.port_input.setValidator(_int_validator())
        self.port_input.setAccessibleName("Puerto de conexión")
        layout.addWidget(self.port_input)

        self.start_with_windows_check = self._check(
            layout, "Iniciar con Windows", getattr(config, "start_with_windows", True),
            "Se abre solo al iniciar sesión en Windows.")
        self.start_minimized_check = self._check(
            layout, "Iniciar minimizado", config.start_minimized,
            "Solo cuando arranca con Windows: se queda en la bandeja. Abrirlo a mano siempre "
            "muestra la ventana.")
        self.always_on_top_check = self._check(
            layout, "Siempre visible", config.always_on_top,
            "La ventana queda por encima de las demás.")
        self.notifications_check = self._check(
            layout, "Notificar cuando cambia la canción", config.notifications_enabled,
            "Aviso de Windows con el título, el artista y la carátula.")
        self.check_updates_check = self._check(
            layout, "Buscar actualizaciones automáticamente", bool(getattr(config, "check_updates", True)),
            "Una vez al día consulta en GitHub si hay versión nueva y avisa en la bandeja. "
            "No envía ningún dato tuyo.")
        import sys as _sys
        self.taskbar_button_check = self._check(
            layout, "Mostrar en la barra de tareas", bool(getattr(config, "taskbar_button", False)),
            "La ventana completa tendrá botón en la barra de tareas con Anterior / Reproducir / "
            "Siguiente en su miniatura. Se aplica al reiniciar."
            if _sys.platform == "win32" else "Solo está disponible en Windows.")
        self.taskbar_button_check.setEnabled(_sys.platform == "win32")

        self._field_label(layout, "Al pulsar Reproducir sin ningún reproductor abierto")
        self.empty_play_combo = ArrowComboBox()
        for label, value in (("Preguntar cada vez", "ask"), ("Abrir Spotify", "spotify"),
                             ("Abrir YouTube", "youtube"), ("Abrir YouTube Music", "ytmusic"),
                             ("No hacer nada", "none")):
            self.empty_play_combo.addItem(label, value)
        idx = self.empty_play_combo.findData(getattr(config, "empty_play_action", "ask"))
        self.empty_play_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self.empty_play_combo)

        # ============================================================= Teclas
        self._header(layout, "Teclas", "Teclas rápidas",
                     "Funcionan desde cualquier programa, aunque YefriPlayer esté en la bandeja.")
        self._hotkey_value_labels: dict[str, QLabel] = {}
        for action, name in (("play_pause", "Reproducir / pausar"), ("next", "Siguiente"),
                             ("previous", "Anterior")):
            row = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setWordWrap(True)
            name_label.setProperty("searchGroupStart", True)
            name_label.setStyleSheet(
                f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; font-size: 11.5px; "
                f"background: transparent;")
            row.addWidget(name_label)
            row.addStretch(1)
            value = QLabel()
            value.setStyleSheet(
                f"color: rgb{Palette.TEXT}; font-family:'{FONT_MONO}'; font-size: 10.5px; "
                f"background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.16); "
                f"border-radius: 5px; padding: 2px 8px;")
            row.addWidget(value)
            layout.addLayout(row)
            self._hotkey_value_labels[action] = value
        hotkeys_row = QHBoxLayout()
        hotkeys_btn = QPushButton("Cambiar teclas…")
        hotkeys_btn.setObjectName("dialogButton")
        hotkeys_btn.clicked.connect(lambda: (open_hotkeys_callback(), self._refresh_hotkey_labels()))
        hotkeys_row.addWidget(hotkeys_btn)
        hotkeys_row.addStretch(1)
        layout.addLayout(hotkeys_row)
        self._hint(layout, "Por defecto: Ctrl+Shift+Espacio, Ctrl+Shift+C y Ctrl+Shift+X. Mientras "
                           "YefriPlayer esté abierto esas combinaciones son suyas en todo el sistema "
                           "(Ctrl+Shift+C es «inspeccionar» en los navegadores).")
        self._refresh_hotkey_labels()

        # ======================================================= Visualizador
        self._header(layout, "Visualizador", "Letra y visualizador",
                     "Lo que acompaña a la carátula en la ventana completa y el panel lateral.")
        self.lyrics_panel_check = self._check(
            layout, "Mostrar letra junto a la carátula", config.lyrics_panel_enabled,
            "Letra sincronizada (o en texto) de lrclib.net, en un panel al lado.")
        import audio_levels
        _viz_ok, _viz_reason = audio_levels.availability()
        self.audio_visualizer_check = self._check(
            layout, "Visualizador de audio", bool(getattr(config, "audio_visualizer", True)) and _viz_ok,
            "Barras de espectro y brillo de la carátula que se mueven con el sonido real. Se "
            "analiza en memoria (no se graba ni sale del equipo) y solo mientras suena música "
            "y hay una ventana a la vista." if _viz_ok else _viz_reason)
        self.audio_visualizer_check.setEnabled(_viz_ok)
        self.audio_visualizer_check.setToolTip(
            "Muestra barras de espectro con el sonido real del equipo." if _viz_ok else _viz_reason)
        import process_loopback
        _pl_ok, _pl_reason = process_loopback.availability()
        self.visualizer_per_app_check = self._check(
            layout, "Solo el audio del reproductor", bool(getattr(config, "visualizer_per_app", True)),
            "Activado: el visualizador escucha SOLO al programa que está sonando (Spotify de "
            "escritorio, o el navegador si la música viene de YouTube, Spotify Web, etc.), así que "
            "no reacciona a avisos de Windows, Discord, juegos ni llamadas. Con el navegador "
            "escucha todas sus pestañas: Windows no las separa.\n"
            "Desactivado: escucha todo lo que sale por los altavoces.\n"
            "Funciona en Windows 11 (y en muchos Windows 10); si tu Windows no lo permite, usa "
            "todo el audio sin avisar." if _pl_ok else _pl_reason)
        self.visualizer_per_app_check.setEnabled(_viz_ok and _pl_ok)
        self.visualizer_per_app_check.setToolTip(
            "Escucha solo a Spotify o al navegador, no avisos, juegos o llamadas." if _pl_ok else _pl_reason)
        self.audio_visualizer_check.toggled.connect(
            lambda on: self.visualizer_per_app_check.setEnabled(bool(on) and _viz_ok and _pl_ok))

        # ============================================================ Aspecto
        self._header(layout, "Aspecto", "Aspecto y accesibilidad",
                     "El aspecto, la letra, la escala y el contraste se aplican al reiniciar.")
        self._field_label(layout, "Opacidad de la ventana")
        opacity_row = QHBoxLayout()
        self.opacity_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setValue(round(config.window_opacity * 100))
        self.opacity_slider.setAccessibleName("Opacidad de la ventana")
        opacity_row.addWidget(self.opacity_slider, 1)
        self.opacity_value_label = QLabel(f"{round(config.window_opacity * 100)}%")
        self.opacity_value_label.setFixedWidth(38)
        self.opacity_value_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_MONO}'; font-size: 10.5px; "
            f"background: transparent;"
        )
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_value_label.setText(f"{v}%")
        )
        opacity_row.addWidget(self.opacity_value_label)
        layout.addLayout(opacity_row)

        self._field_label(layout, "Aspecto del reproductor")
        self.player_theme_combo = ArrowComboBox()
        self.player_theme_combo.addItem("Predeterminado (rojo y azul neón)", "default")
        self.player_theme_combo.addItem("Cosmos (violeta y celeste, cielo estrellado)", "cosmos")
        self.player_theme_combo.setCurrentIndex(
            max(0, self.player_theme_combo.findData(config.player_theme)))
        self.player_theme_combo.setAccessibleName("Aspecto del reproductor")
        layout.addWidget(self.player_theme_combo)

        self._field_label(layout, "Accesibilidad")
        self.font_scale_combo = ArrowComboBox()
        self.font_scale_combo.addItem("Tamaño de letra: pequeña", 0.88)
        self.font_scale_combo.addItem("Tamaño de letra: normal", 1.0)
        self.font_scale_combo.addItem("Tamaño de letra: grande", 1.15)
        self.font_scale_combo.addItem("Tamaño de letra: muy grande", 1.3)
        current_index = max(0, self.font_scale_combo.findData(round(config.font_scale, 2)))
        # Un valor intermedio guardado a mano cae al más cercano.
        if self.font_scale_combo.itemData(current_index) != round(config.font_scale, 2):
            current_index = min(
                range(self.font_scale_combo.count()),
                key=lambda i: abs(self.font_scale_combo.itemData(i) - config.font_scale),
            )
        self.font_scale_combo.setCurrentIndex(current_index)
        layout.addWidget(self.font_scale_combo)

        # Escala de TODA la interfaz. Automática = según la resolución (screen_scale.py).
        import screen_scale
        self.ui_scale_combo = ArrowComboBox()
        self.ui_scale_combo.addItem(screen_scale.describe_auto(), 0.0)
        for value in screen_scale.MANUAL_CHOICES:
            self.ui_scale_combo.addItem(f"Escala de la interfaz: {round(value * 100)} %", value)
        idx = 0
        if config.ui_scale > 0:
            idx = min(range(1, self.ui_scale_combo.count()),
                      key=lambda i: abs(self.ui_scale_combo.itemData(i) - config.ui_scale))
        self.ui_scale_combo.setCurrentIndex(idx)
        self.ui_scale_combo.setAccessibleName("Escala de la interfaz")
        layout.addWidget(self.ui_scale_combo)

        self.high_contrast_check = self._check(
            layout, "Alto contraste", config.high_contrast,
            "Texto secundario más legible sobre cualquier fondo.")

        # ====================================================== Panel lateral
        self._header(layout, "Panel", "Panel lateral",
                     "Una pestaña anclada a un borde de la pantalla que se despliega al usarla "
                     "(menú de la ventana completa → Panel lateral).")
        dock_row = QVBoxLayout()
        dock_row.setSpacing(8)
        self.dock_edge_combo = ArrowComboBox()
        self.dock_edge_combo.addItem("Borde derecho", "right")
        self.dock_edge_combo.addItem("Borde izquierdo", "left")
        self.dock_edge_combo.setCurrentIndex(max(0, self.dock_edge_combo.findData(config.dock_edge)))
        dock_row.addWidget(self.dock_edge_combo)
        self.dock_style_combo = ArrowComboBox()
        self.dock_style_combo.addItem("Estilo tarjeta (carátula grande)", "card")
        self.dock_style_combo.addItem("Estilo compacto (disco de vinilo)", "compact")
        self.dock_style_combo.setCurrentIndex(max(0, self.dock_style_combo.findData(config.dock_style)))
        dock_row.addWidget(self.dock_style_combo)
        layout.addLayout(dock_row)
        self.dock_hide_combo = ArrowComboBox()
        self.dock_hide_combo.addItem("Se abre y cierra con clic", "click")
        self.dock_hide_combo.addItem("Se abre y cierra solo (al pasar/alejar el mouse)", "hover")
        self.dock_hide_combo.addItem("Ambas formas a la vez", "both")
        self.dock_hide_combo.setCurrentIndex(max(0, self.dock_hide_combo.findData(config.dock_hide_mode)))
        layout.addWidget(self.dock_hide_combo)
        self.bar_waves_check = self._check(
            layout, "Ondas alrededor de la barra al sonar", getattr(config, "bar_waves_enabled", True))

        # ==================================================== Tema de Spotify
        if theme_bridge is not None:
            self._build_spotify_theme_section(layout, theme_bridge, theme_enabled)

        # ============================================================ Cuentas
        self._header(layout, "Cuentas", "Cuentas y scrobbling",
                     "«Me gusta» en Spotify / YouTube y envío de lo que escuchas a Last.fm o "
                     "ListenBrainz. Todo opcional.")
        likes_row = QHBoxLayout()
        likes_btn = QPushButton("Cuentas para «Me gusta»…")
        likes_btn.setObjectName("dialogButton")
        likes_btn.clicked.connect(self._open_likes_dialog)
        likes_row.addWidget(likes_btn)
        likes_row.addStretch(1)
        layout.addLayout(likes_row)

        self._field_label(layout, "Scrobbling")
        self._hint(layout, "Envía cada canción escuchada (sin contar pausas) a Last.fm o "
                           "ListenBrainz; sin conexión, espera y la envía después.")
        self.scrobble_combo = ArrowComboBox()
        self.scrobble_combo.addItem("Desactivado", "NONE")
        self.scrobble_combo.addItem("Last.fm", "LASTFM")
        self.scrobble_combo.addItem("ListenBrainz", "LISTENBRAINZ")
        self.scrobble_combo.setCurrentIndex(max(0, self.scrobble_combo.findData(config.scrobble_service)))
        layout.addWidget(self.scrobble_combo)

        # --- Sub-panel Last.fm ---
        self.lastfm_box = QWidget()
        lastfm_layout = QVBoxLayout(self.lastfm_box)
        lastfm_layout.setContentsMargins(0, 4, 0, 0)
        lastfm_layout.setSpacing(6)
        lastfm_hint = QLabel(
            "Necesita una API key + secreto propios (gratis, en last.fm/api/account/create) y tu "
            "usuario/contraseña — la contraseña se usa una sola vez para obtener una sesión y no "
            "se guarda; solo queda guardada la sesión resultante."
        )
        lastfm_hint.setWordWrap(True)
        lastfm_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;"
        )
        lastfm_layout.addWidget(lastfm_hint)
        self.lastfm_key_input = QLineEdit(config.lastfm_api_key)
        self.lastfm_key_input.setPlaceholderText("API key")
        lastfm_layout.addWidget(self.lastfm_key_input)
        self.lastfm_secret_input = QLineEdit(config.lastfm_api_secret)
        self.lastfm_secret_input.setPlaceholderText("Secreto compartido")
        self.lastfm_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        lastfm_layout.addWidget(self.lastfm_secret_input)
        lastfm_login_row = QHBoxLayout()
        self.lastfm_user_input = QLineEdit()
        self.lastfm_user_input.setPlaceholderText("Usuario")
        lastfm_login_row.addWidget(self.lastfm_user_input)
        self.lastfm_pass_input = QLineEdit()
        self.lastfm_pass_input.setPlaceholderText("Contraseña")
        self.lastfm_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        lastfm_login_row.addWidget(self.lastfm_pass_input)
        lastfm_layout.addLayout(lastfm_login_row)
        lastfm_action_row = QHBoxLayout()
        self.lastfm_connect_btn = QPushButton("Conectar")
        self.lastfm_connect_btn.setObjectName("dialogButton")
        self.lastfm_connect_btn.clicked.connect(self._lastfm_connect)
        lastfm_action_row.addWidget(self.lastfm_connect_btn)
        self.lastfm_status_label = QLabel(
            f"Sesión activa como {config.lastfm_username}" if config.lastfm_session_key
            else "Sin conectar"
        )
        self.lastfm_status_label.setWordWrap(True)
        self.lastfm_status_label.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM if config.lastfm_session_key else Palette.TEXT_FAINT}; "
            f"font-family:'{FONT_BODY}'; font-size: 10px; background: transparent;"
        )
        lastfm_action_row.addWidget(self.lastfm_status_label, 1)
        lastfm_layout.addLayout(lastfm_action_row)
        layout.addWidget(self.lastfm_box)
        # Sesión de Last.fm conseguida en esta apertura; AppController la vuelca al guardar.
        self.result_lastfm_session_key = config.lastfm_session_key
        self.result_lastfm_username = config.lastfm_username

        # --- Sub-panel ListenBrainz ---
        self.listenbrainz_box = QWidget()
        lb_layout = QVBoxLayout(self.listenbrainz_box)
        lb_layout.setContentsMargins(0, 4, 0, 0)
        lb_layout.setSpacing(6)
        lb_hint = QLabel(
            "Pega tu «User Token» personal, disponible en tu perfil de ListenBrainz "
            "(listenbrainz.org/settings) — no hace falta registrar ninguna aplicación aparte."
        )
        lb_hint.setWordWrap(True)
        lb_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;"
        )
        lb_layout.addWidget(lb_hint)
        self.listenbrainz_token_input = QLineEdit(config.listenbrainz_token)
        self.listenbrainz_token_input.setPlaceholderText("User token")
        self.listenbrainz_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        lb_layout.addWidget(self.listenbrainz_token_input)
        layout.addWidget(self.listenbrainz_box)
        self.scrobble_combo.currentIndexChanged.connect(self._update_scrobble_visibility)
        self._update_scrobble_visibility()

        # ============================================================ YouTube
        self._header(layout, "YouTube", "Enlace directo a YouTube",
                     "Con una clave de API de YouTube (Google Cloud, gratis dentro de la cuota), "
                     "tocar la carátula o el título abre el vídeo exacto en vez de una búsqueda.")
        self.youtube_key_input = QLineEdit(config.youtube_api_key)
        self.youtube_key_input.setPlaceholderText("Clave de API de YouTube (opcional)")
        self.youtube_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.youtube_key_input)

        # ============================================================== Datos
        self._header(layout, "Datos", "Historial y estadísticas",
                     "Todo se guarda solo en este equipo.")
        extra_row = QHBoxLayout()
        history_btn = QPushButton("Historial…")
        history_btn.setObjectName("dialogButton")
        history_btn.clicked.connect(open_history_callback)
        extra_row.addWidget(history_btn)
        stats_btn = QPushButton("Estadísticas…")
        stats_btn.setObjectName("dialogButton")
        stats_btn.clicked.connect(open_stats_callback)
        extra_row.addWidget(stats_btn)
        extra_row.addStretch(1)
        layout.addLayout(extra_row)
        about = QLabel(f"{_v.APP_NAME} {_v.APP_VERSION} · {_v.APP_DESCRIPTION}")
        about.setWordWrap(True)
        about.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;")
        layout.addWidget(about)

        layout.addStretch(1)
        scroll.setWidget(inner)
        inner.set_sections([w for _n, w in self._nav_anchors])
        body.addWidget(scroll, 1)
        self._setup_navigation(side, scroll, inner, layout)

        self._make_responsive(inner)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("dialogButton")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Guardar")
        save_btn.setObjectName("dialogButtonAccent")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _make_responsive(self, inner: QWidget):
        """Que nada imponga un ancho mayor que el disponible: los combos se pueden
        estrechar (el texto largo se recorta en el cuadro, pero la lista
        desplegable se abre a su ancho completo) y, en pantallas bajas, la barra
        lateral usa entradas más juntas."""
        for combo in inner.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            with contextlib.suppress(Exception):
                view = combo.view()
                view.setMinimumWidth(view.sizeHintForColumn(0) + 28)
        for edit in inner.findChildren(QLineEdit):
            edit.setMinimumWidth(60)
        if self._compact:
            for chip in getattr(self, "_nav_chips", []):
                chip.setProperty("compact", True)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    # ------------------------------------------------- piezas del formulario
    def _header(self, layout, nav_name: str, title: str, description: str = ""):
        """Cabecera de sección: abre una tarjeta y un grupo de búsqueda, y es el
        destino del botón de la barra lateral."""
        if self._nav_anchors:
            # Hueco entre tarjetas: aire inferior de la anterior + separación + aire
            # superior de esta (menos el espaciado normal de la lista).
            layout.addSpacing(_SettingsInner.PAD * 2 + _SettingsInner.GAP - layout.spacing())
        head = QWidget()
        head.setProperty("searchGroupStart", True)
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 4)
        head_layout.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 13.5px; font-weight: 700; background: transparent;")
        head_layout.addWidget(t)
        if description:
            d = QLabel(description)
            d.setWordWrap(True)
            d.setStyleSheet(
                f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
                f"font-size: 10px; background: transparent;")
            head_layout.addWidget(d)
        layout.addWidget(head)
        self._nav_anchors.append((nav_name, head))
        return head

    @staticmethod
    def _field_label(layout, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)                       # textos largos: varias líneas, no cortados
        lbl.setProperty("searchGroupStart", True)
        lbl.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 11.5px; font-weight: 600; background: transparent; margin-top: 4px;")
        layout.addWidget(lbl)
        return lbl

    @staticmethod
    def _hint(layout, text: str, indent: int = 0) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;")
        if indent:
            lbl.setContentsMargins(indent, 0, 0, 2)
        layout.addWidget(lbl)
        return lbl

    def _check(self, layout, text: str, checked: bool, description: str = "") -> QCheckBox:
        """Casilla + su explicación debajo (ver _CheckRow). Devuelve la casilla."""
        row = _CheckRow(text, description)
        row.check.setChecked(bool(checked))
        layout.addWidget(row)
        return row.check

    def _refresh_hotkey_labels(self):
        from hotkeys import combo_to_display
        cfg = self._config_ref
        enabled = bool(getattr(cfg, "hotkeys_enabled", True))
        try:
            failures = dict(self._hotkey_failures() or {})
        except Exception:
            failures = {}
        for action, label in self._hotkey_value_labels.items():
            if sip.isdeleted(label):
                return
            combo = getattr(cfg, f"hotkey_{action}", "")
            text = combo_to_display(combo).replace("Space", "Espacio") if combo else "(sin asignar)"
            busy = enabled and action in failures
            label.setText(f"{text} · no funciona" if busy else (text if enabled else f"{text} · desactivadas"))
            label.setToolTip(f"No se pudo activar: {failures[action][1]}. Pulsa «Cambiar teclas…» y elige "
                             "otra combinación." if busy else "")
            border = f"rgb{Palette.ERROR}" if busy else "rgba(255,255,255,0.16)"
            label.setStyleSheet(
                f"color: rgb{Palette.ERROR if busy else Palette.TEXT}; font-family:'{FONT_MONO}'; "
                f"font-size: 10.5px; background: rgba(255,255,255,0.07); border: 1px solid {border}; "
                f"border-radius: 5px; padding: 2px 8px;")

    # ------------------------------------------------- secciones y búsqueda
    @staticmethod
    def _fold(text: str) -> str:
        """Minúsculas y sin tildes: «accesibilidad» encuentra «Accesibilidad» y «visualizador» a «Visualizador»."""
        return unicodedata.normalize("NFD", text or "").encode("ascii", "ignore").decode("ascii").lower()

    def _setup_navigation(self, side, scroll, inner, layout):
        """Busca un ajuste y salta a una sección: en la barra lateral van un cuadro de
        búsqueda (filtra los ajustes) y un botón por sección (lleva hasta ella y se marca
        según por dónde vas)."""
        self._nav_scroll, self._nav_inner, self._nav_layout = scroll, inner, layout

        # orden de las secciones = orden real en la pantalla (el tema de Spotify se crea a mitad)
        def position(widget):
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is widget:
                    return i
                sub = item.layout()
                if sub is not None and any(sub.itemAt(j).widget() is widget for j in range(sub.count())):
                    return i
            return 10_000
        self._nav_anchors.sort(key=lambda pair: position(pair[1]))

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Buscar un ajuste…")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setAccessibleName("Buscar un ajuste")
        self._search_input.textChanged.connect(self._apply_search)

        side.addWidget(self._search_input)
        side.addSpacing(6)
        self._nav_chips: list[QPushButton] = []
        for index, (name, _widget) in enumerate(self._nav_anchors):
            chip = QPushButton(name)
            chip.setObjectName("settingsNavItem")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setAccessibleName(f"Ir a la sección {name}")
            chip.clicked.connect(lambda _checked=False, i=index: self._goto_section(i))
            side.addWidget(chip)
            self._nav_chips.append(chip)
        if self._nav_chips:
            self._nav_chips[0].setChecked(True)
        side.addStretch(1)
        scroll.verticalScrollBar().valueChanged.connect(self._sync_nav_chips)

        self._no_results = QLabel("Ningún ajuste coincide con la búsqueda.")
        self._no_results.setWordWrap(True)
        self._no_results.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; font-size: 11px; background: transparent;")
        self._no_results.hide()
        layout.insertWidget(0, self._no_results)
        self._search_groups = self._build_search_groups(layout)
        self._search_hidden: dict[QWidget, bool] = {}       # widget -> ¿estaba oculto antes del filtro?

    def _goto_section(self, index: int):
        if self._search_input.text():
            self._search_input.clear()                      # ver las secciones completas
        widget = self._nav_anchors[index][1]
        y = widget.mapTo(self._nav_inner, QPoint(0, 0)).y()
        self._nav_scroll.verticalScrollBar().setValue(max(0, y - 14))
        self._mark_chip(index)

    def _mark_chip(self, index: int):
        for i, chip in enumerate(self._nav_chips):
            chip.setChecked(i == index)

    def _sync_nav_chips(self, value: int):
        """Marca la sección que se está viendo (la última cuyo inicio ya pasó)."""
        if self._search_input.text():
            return
        current = 0
        for i, (_name, widget) in enumerate(self._nav_anchors):
            if widget.isVisibleTo(self._nav_inner) and widget.mapTo(self._nav_inner, QPoint(0, 0)).y() <= value + 40:
                current = i
        scrollbar = self._nav_scroll.verticalScrollBar()
        if scrollbar.maximum() and value >= scrollbar.maximum() - 2:
            current = len(self._nav_chips) - 1              # al final del todo: la última
        self._mark_chip(current)

    def _build_search_groups(self, layout) -> list[dict]:
        """Agrupa lo que hay en la lista por ajuste: un título o una casilla abren grupo; las
        explicaciones (texto largo) y los controles se pegan al grupo anterior."""
        groups: list[dict] = []

        def widgets_of(item):
            if item.widget() is not None:
                return [item.widget()]
            sub = item.layout()
            return [] if sub is None else [sub.itemAt(j).widget() for j in range(sub.count())
                                           if sub.itemAt(j).widget() is not None]

        def text_of(widget) -> str:
            parts = []
            for getter in ("text", "toolTip", "placeholderText"):
                value = getattr(widget, getter, None)
                if callable(value):
                    with contextlib.suppress(Exception):
                        result = value()
                        if isinstance(result, str):
                            parts.append(result)
            if isinstance(widget, QComboBox):
                parts += [widget.itemText(i) for i in range(widget.count())]
            for child in widget.findChildren(QWidget):
                if child is not widget and isinstance(child, (QLabel, QCheckBox, QPushButton, QLineEdit, QComboBox)):
                    parts.append(text_of(child))
            return " ".join(p for p in parts if p)

        for i in range(layout.count()):
            item = layout.itemAt(i)
            found = [w for w in widgets_of(item) if w is not self._no_results]
            if not found:
                continue
            first = found[0]
            starts = (bool(first.property("searchGroupStart")) or isinstance(first, QCheckBox)
                      or (isinstance(first, QLabel) and not first.wordWrap()))
            if starts or not groups:
                groups.append({"widgets": [], "text": ""})
            for w in found:
                groups[-1]["widgets"].append(w)
                groups[-1]["text"] += " " + text_of(w)
        for g in groups:
            g["folded"] = self._fold(g["text"])
        return groups

    def _apply_search(self, text: str):
        query = self._fold(text).strip()
        shown = 0
        for group in self._search_groups:
            match = (not query) or all(word in group["folded"] for word in query.split())
            shown += 1 if match else 0
            for w in group["widgets"]:
                if match:
                    if w in self._search_hidden:                     # restaura lo que había antes del filtro
                        w.setVisible(not self._search_hidden.pop(w))
                else:
                    if w not in self._search_hidden:
                        self._search_hidden[w] = w.isHidden()
                    w.hide()
        self._no_results.setVisible(bool(query) and shown == 0)
        self._nav_inner.update()            # las tarjetas se quitan/vuelven con la búsqueda
        # Buscando no se está «en» ninguna sección: se desmarcan; al borrar se vuelve a marcar la actual.
        if query:
            for chip in self._nav_chips:
                chip.setChecked(False)
        else:
            self._sync_nav_chips(self._nav_scroll.verticalScrollBar().value())

    def _update_scrobble_visibility(self):
        service = self.scrobble_combo.currentData()
        self.lastfm_box.setVisible(service == "LASTFM")
        self.listenbrainz_box.setVisible(service == "LISTENBRAINZ")

    def _lastfm_connect(self):
        """Pide una sesión de Last.fm con usuario/contraseña (método
        'mobile session' de su API: no abre navegador ni necesita un
        servidor de callback, ideal para una app de escritorio). La
        contraseña viaja una sola vez a la API oficial de Last.fm para
        este pedido puntual y no se guarda en ningún lado — solo la
        sesión que devuelven, que es lo que se usa de ahí en más."""
        import scrobbling
        api_key = self.lastfm_key_input.text().strip()
        api_secret = self.lastfm_secret_input.text().strip()
        username = self.lastfm_user_input.text().strip()
        password = self.lastfm_pass_input.text()
        if not (api_key and api_secret and username and password):
            self._set_lastfm_status("Completá API key, secreto, usuario y contraseña.", ok=False)
            return
        self.lastfm_connect_btn.setEnabled(False)
        self.lastfm_connect_btn.setText("Conectando...")
        QApplication.processEvents()
        session_key, display_name, error = scrobbling.lastfm_get_mobile_session(
            username, password, api_key, api_secret
        )
        self.lastfm_connect_btn.setEnabled(True)
        self.lastfm_connect_btn.setText("Conectar")
        if error:
            self._set_lastfm_status(error, ok=False)
            return
        self.result_lastfm_session_key = session_key
        self.result_lastfm_username = display_name
        self.lastfm_pass_input.clear()
        self._set_lastfm_status(f"Sesión activa como {display_name}", ok=True)

    def _build_spotify_theme_section(self, layout, bridge, enabled: bool):
        """Cambiar el modo del tema "Switch" de Spicetify (Cosmos, Cover,
        YefriDev...) desde el reproductor. La lista de modos la informa el
        propio theme.js al conectarse (ver spotify_theme.py)."""
        self._header(layout, "Spotify", "Tema de Spotify (Spicetify)",
                     "Cambia el modo del tema «Switch» de Spotify desde aquí. Se aplica al "
                     "guardar (o al abrir Spotify, si estaba cerrado).")

        self.theme_enabled_check = self._check(layout, "Controlar el tema de Spotify desde aquí", enabled)

        self.theme_combo = ArrowComboBox()
        self.theme_combo.setAccessibleName("Modo del tema de Spotify")
        self._fill_theme_combo()
        layout.addWidget(self.theme_combo)

        self.theme_status_label = QLabel()
        self.theme_status_label.setWordWrap(True)
        layout.addWidget(self.theme_status_label)

        self.theme_enabled_check.toggled.connect(self._refresh_theme_section)
        # El puente vive más que este diálogo. PyQt desconecta solo los métodos de un
        # QObject destruido en Python normal, pero NO en el .exe compilado con Nuitka
        # (no reconoce al receptor): la señal llegaba a un diálogo ya borrado y fallaba
        # con «wrapped C/C++ object of type QCheckBox has been deleted». Por eso se
        # desconecta de forma explícita al cerrar.
        bridge.connectionChanged.connect(self._refresh_theme_section)
        bridge.modesChanged.connect(self._on_theme_modes_changed)
        bridge.modeChanged.connect(self._on_theme_mode_changed)
        self.finished.connect(self._disconnect_theme_bridge)
        self._refresh_theme_section()

    def _disconnect_theme_bridge(self, _result=0):
        bridge = self._theme_bridge
        if bridge is None:
            return
        for signal, slot in ((bridge.connectionChanged, self._refresh_theme_section),
                             (bridge.modesChanged, self._on_theme_modes_changed),
                             (bridge.modeChanged, self._on_theme_mode_changed)):
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)

    def _theme_widgets_alive(self) -> bool:
        """False si el diálogo (o sus widgets) ya fueron destruidos por Qt."""
        if sip.isdeleted(self):
            return False
        for name in ("theme_enabled_check", "theme_combo", "theme_status_label"):
            widget = getattr(self, name, None)       # durante la construcción aún no existen todos
            if widget is not None and sip.isdeleted(widget):
                return False
        return True

    def _fill_theme_combo(self, keep: str = ""):
        if not self._theme_widgets_alive():
            return
        bridge = self._theme_bridge
        wanted = keep or bridge.mode()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        known = {m["id"] for m in bridge.modes()}
        if wanted not in known:
            # Todavía no se sabe qué modo tiene Spotify: no se cambia nada al guardar.
            self.theme_combo.addItem("Sin cambios", "")
        for m in bridge.modes():
            self.theme_combo.addItem(m["name"], m["id"])
            if m["desc"]:
                self.theme_combo.setItemData(self.theme_combo.count() - 1, m["desc"],
                                             Qt.ItemDataRole.ToolTipRole)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(wanted)))
        self.theme_combo.blockSignals(False)

    def _on_theme_modes_changed(self, _modes=None):
        if not self._theme_widgets_alive():
            return
        self._fill_theme_combo(keep=self.theme_combo.currentData() or "")

    def _on_theme_mode_changed(self, mode_id: str = ""):
        # Spotify cambió de modo por su cuenta (botón del tema o Ctrl+Alt+T):
        # se refleja en el combo. Si el usuario ya tocó el combo, no se lo pisa
        # en cuanto elige: solo se actualiza cuando el combo está en "Sin cambios".
        if self._theme_widgets_alive() and not self.theme_combo.currentData():
            self._fill_theme_combo(keep=mode_id)

    def _refresh_theme_section(self, _checked=None):
        if not self._theme_widgets_alive():
            return
        on = self.theme_enabled_check.isChecked()
        self.theme_combo.setEnabled(on)
        bridge = self._theme_bridge
        if not on:
            text, color = "Desactivado: el reproductor no abre ningún puerto para el tema.", Palette.TEXT_DIM
        elif bridge.is_running and bridge.is_connected:
            text, color = "Conectado a Spotify.", Palette.OK
        elif bridge.last_error:
            text, color = bridge.last_error, Palette.ERROR
        else:
            text = (f"Esperando a Spotify (puerto {bridge.port}). Se conecta solo cuando "
                    f"abres Spotify con el tema Switch actualizado.")
            color = Palette.TEXT_DIM
        self.theme_status_label.setText(text)
        self.theme_status_label.setStyleSheet(
            f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: 10px; "
            f"background: transparent;"
        )

    def _set_lastfm_status(self, text: str, ok: bool):
        self.lastfm_status_label.setText(text)
        color = Palette.TEXT_DIM if ok else Palette.ERROR
        self.lastfm_status_label.setStyleSheet(
            f"color: rgb{color}; font-family:'{FONT_BODY}'; font-size: 10px; "
            f"background: transparent;"
        )

    def _open_likes_dialog(self):
        from likes_dialog import LikesDialog
        LikesDialog(self._config_ref, on_changed=lambda: self.on_likes_changed and self.on_likes_changed(),
                    parent=self).exec()

    def _save(self):
        try:
            port = int(self.port_input.text())
        except ValueError:
            port = self.result_port
        self.result_port = port
        self.result_always_on_top = self.always_on_top_check.isChecked()
        self.result_start_with_windows = self.start_with_windows_check.isChecked()
        self.result_start_minimized = self.start_minimized_check.isChecked()
        self.result_notifications = self.notifications_check.isChecked()
        self.result_empty_play_action = self.empty_play_combo.currentData()
        self.result_lyrics_panel_enabled = self.lyrics_panel_check.isChecked()
        self.result_audio_visualizer = self.audio_visualizer_check.isChecked()
        self.result_visualizer_per_app = self.visualizer_per_app_check.isChecked()
        self.result_taskbar_button = self.taskbar_button_check.isChecked()
        self.result_check_updates = self.check_updates_check.isChecked()
        self.result_window_opacity = self.opacity_slider.value() / 100.0
        self.result_font_scale = self.font_scale_combo.currentData()
        self.result_ui_scale = self.ui_scale_combo.currentData()
        self.result_high_contrast = self.high_contrast_check.isChecked()
        self.result_player_theme = self.player_theme_combo.currentData()
        self.result_dock_edge = self.dock_edge_combo.currentData()
        self.result_dock_hide_mode = self.dock_hide_combo.currentData()
        self.result_dock_style = self.dock_style_combo.currentData()
        self.result_bar_waves = self.bar_waves_check.isChecked()
        if self._theme_bridge is not None:
            self.result_spotify_theme_enabled = self.theme_enabled_check.isChecked()
            self.result_spotify_theme_mode = (
                self.theme_combo.currentData() if self.theme_enabled_check.isChecked() else "")
        self.result_scrobble_service = self.scrobble_combo.currentData()
        self.result_lastfm_api_key = self.lastfm_key_input.text().strip()
        self.result_lastfm_api_secret = self.lastfm_secret_input.text().strip()
        self.result_listenbrainz_token = self.listenbrainz_token_input.text().strip()
        self.result_youtube_api_key = self.youtube_key_input.text().strip()
        self.accept()
