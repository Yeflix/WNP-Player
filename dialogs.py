"""Diálogos secundarios: puerto, 'Acerca de', errores, dependencias faltantes y teclas."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
    QPlainTextEdit, QApplication, QCheckBox, QScrollArea, QFrame, QSizePolicy
)

from theme import Palette, FONT_BODY, FONT_MONO
from hotkeys import capture_from_event, combo_to_string, combo_to_display, combo_needs_modifier
from widgets import ElidedLabel, IconButton, HistoryCard, ArrowComboBox, NoWheelSlider


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
        self._title = title
        self._fixed_height = height
        if height:
            self.setFixedHeight(height)
        self.setFixedWidth(width)

    def showEvent(self, event):
        self._fit_to_content_and_screen()
        super().showEvent(event)

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


class AboutDialog(_DialogBase):
    def __init__(self, port: int, parent=None):
        super().__init__(parent, title="Acerca de")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("WNP Player")
        title.setStyleSheet(f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
                             f"font-size: 16px; font-weight: 700; background: transparent;")
        layout.addWidget(title)

        body = QLabel(
            "Reproductor de escritorio independiente que usa el protocolo "
            "WebNowPlaying para leer y controlar la reproducción de música "
            "desde el navegador (YouTube, Spotify y otros sitios compatibles).\n\n"
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
                 parent=None, initial_scroll_pos: int = 0):
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

        all_time = stats.summary(entries, days=None)
        week = stats.summary(entries, days=7)

        # Si hay algo sonando ahora mismo, esto va primero — es lo más
        # "vivo" del panel, tal como se pidió: "has escuchado esta
        # canción X veces".
        if current_title:
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
        chips_row.addWidget(_StatChip(all_time["total_duration_text"], "tiempo total"))
        chips_row.addWidget(_StatChip(str(week["plays"]), "canciones esta semana"))
        chips_row.addWidget(_StatChip(str(all_time["unique_songs"]), "canciones distintas"))
        inner_layout.addLayout(chips_row)

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
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
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

    def _clear(self):
        import history
        history.clear()
        self._all_entries = []
        self.search_input.clear()  # dispara _on_filter_changed, que reinicia el timer...
        self._filter_timer.stop()  # ...por eso se detiene DESPUÉS, no antes
        self._populate(self._all_entries)


class SettingsDialog(_DialogBase):
    """Panel de configuración: puerto, comportamiento de ventana,
    notificaciones, accesos a teclas multimedia e historial, scrobbling y
    enlaces de YouTube.

    Con scroll interno (antes era un QVBoxLayout directo, ver PROYECTO.md
    sección 12.3/18.2): entre las nuevas secciones de scrobbling y YouTube
    y lo que ya había, el contenido pasó a ser más largo de lo que entra
    cómodo en una ventana fija sin desbordarse — mismo patrón que ya usan
    Historial/Estadísticas (QScrollArea transparente + contenedor interno),
    con los botones Cancelar/Guardar siempre fijos abajo, fuera del scroll."""

    def __init__(self, config, backend_port: int, open_hotkeys_callback,
                 open_history_callback, open_stats_callback, parent=None,
                 theme_bridge=None, theme_enabled: bool = True):
        super().__init__(parent, title="Configuración", width=424, height=560)
        self._theme_bridge = theme_bridge
        self.result_spotify_theme_enabled = theme_enabled
        self.result_spotify_theme_mode = ""
        self.result_port = backend_port
        self.result_always_on_top = config.always_on_top
        self.result_start_minimized = config.start_minimized
        self.result_notifications = config.notifications_enabled
        self.result_empty_play_action = getattr(config, "empty_play_action", "ask")
        self.on_likes_changed = None   # lo fija el controlador
        self.result_bar_waves = getattr(config, "bar_waves_enabled", True)
        self._config_ref = config
        self.result_lyrics_panel_enabled = config.lyrics_panel_enabled
        self.result_window_opacity = config.window_opacity
        self.result_font_scale = config.font_scale
        self.result_ui_scale = config.ui_scale
        self.result_high_contrast = config.high_contrast
        self.result_player_theme = config.player_theme

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 16)
        outer.setSpacing(12)

        title = QLabel("Configuración")
        title.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 16px; font-weight: 700; background: transparent;"
        )
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Antes: setStyleSheet("background: transparent; border: none;") SIN
        # selector. En Qt una regla sin selector se aplica al widget Y A TODOS
        # SUS DESCENDIENTES, y la hoja de un padre gana a la global de la app:
        # todos los controles de este formulario (combos, campos de texto)
        # perdían su fondo y su borde y parecían texto suelto. Ahora las reglas
        # apuntan solo al área, su viewport y el contenedor, por nombre.
        scroll.setObjectName("settingsScroll")
        scroll.viewport().setObjectName("settingsViewport")
        scroll.setStyleSheet(
            "QScrollArea#settingsScroll { background: transparent; border: none; }"
            "QWidget#settingsViewport, QWidget#settingsInner { background: transparent; }"
        )
        inner = QWidget()
        inner.setObjectName("settingsInner")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)

        port_label = QLabel("Puerto de conexión")
        port_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 11.5px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(port_label)

        port_hint = QLabel(
            "El que debe usar la extensión WebNowPlaying del navegador como "
            "adaptador personalizado."
        )
        port_hint.setWordWrap(True)
        port_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(port_hint)

        self.port_input = QLineEdit(str(backend_port))
        self.port_input.setValidator(_int_validator())
        layout.addWidget(self.port_input)

        self.always_on_top_check = QCheckBox("Siempre visible")
        self.always_on_top_check.setChecked(config.always_on_top)
        layout.addWidget(self.always_on_top_check)

        self.start_minimized_check = QCheckBox("Iniciar minimizado a la bandeja")
        self.start_minimized_check.setChecked(config.start_minimized)
        layout.addWidget(self.start_minimized_check)

        self.notifications_check = QCheckBox("Notificar cuando cambia la canción")
        self.notifications_check.setChecked(config.notifications_enabled)
        layout.addWidget(self.notifications_check)

        empty_label = QLabel("Al pulsar Reproducir sin ningún reproductor abierto")
        layout.addWidget(empty_label)
        self.empty_play_combo = ArrowComboBox()
        for label, value in (("Preguntar cada vez", "ask"), ("Abrir Spotify", "spotify"),
                             ("Abrir YouTube", "youtube"), ("Abrir YouTube Music", "ytmusic"),
                             ("No hacer nada", "none")):
            self.empty_play_combo.addItem(label, value)
        idx = self.empty_play_combo.findData(getattr(config, "empty_play_action", "ask"))
        self.empty_play_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self.empty_play_combo)

        likes_row = QHBoxLayout()
        likes_btn = QPushButton("Cuentas para «Me gusta»…")
        likes_btn.setObjectName("dialogButton")
        likes_btn.clicked.connect(self._open_likes_dialog)
        likes_row.addWidget(likes_btn)
        likes_row.addStretch(1)
        layout.addLayout(likes_row)

        self.lyrics_panel_check = QCheckBox("Mostrar letra junto a la carátula")
        self.lyrics_panel_check.setChecked(config.lyrics_panel_enabled)
        layout.addWidget(self.lyrics_panel_check)

        opacity_label = QLabel("Opacidad de la ventana")
        opacity_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 11.5px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(opacity_label)

        opacity_row = QHBoxLayout()
        self.opacity_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setValue(round(config.window_opacity * 100))
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

        layout.addWidget(_section_label("Aspecto del reproductor"))
        theme_hint = QLabel("Cambiar el aspecto pide reiniciar la app.")
        theme_hint.setWordWrap(True)
        theme_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;"
        )
        layout.addWidget(theme_hint)
        self.player_theme_combo = ArrowComboBox()
        self.player_theme_combo.addItem("Predeterminado (rojo y azul neón)", "default")
        self.player_theme_combo.addItem("Cosmos (violeta y celeste, cielo estrellado)", "cosmos")
        self.player_theme_combo.setCurrentIndex(
            max(0, self.player_theme_combo.findData(config.player_theme)))
        self.player_theme_combo.setAccessibleName("Aspecto del reproductor")
        layout.addWidget(self.player_theme_combo)

        access_label = QLabel("Accesibilidad")
        access_label.setStyleSheet(
            f"color: rgb{Palette.TEXT}; font-family:'{FONT_BODY}'; "
            f"font-size: 11.5px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(access_label)

        access_hint = QLabel("El tamaño de letra, la escala de la interfaz y el alto contraste piden reiniciar la app.")
        access_hint.setWordWrap(True)
        access_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_FAINT}; font-family:'{FONT_BODY}'; "
            f"font-size: 9.5px; background: transparent;"
        )
        layout.addWidget(access_hint)

        self.font_scale_combo = ArrowComboBox()
        self.font_scale_combo.addItem("Tamaño de letra: pequeña", 0.88)
        self.font_scale_combo.addItem("Tamaño de letra: normal", 1.0)
        self.font_scale_combo.addItem("Tamaño de letra: grande", 1.15)
        self.font_scale_combo.addItem("Tamaño de letra: muy grande", 1.3)
        current_index = max(0, self.font_scale_combo.findData(round(config.font_scale, 2)))
        # findData puede no encontrar coincidencia exacta si quedó un valor
        # intermedio guardado a mano; en ese caso cae al más cercano.
        if self.font_scale_combo.itemData(current_index) != round(config.font_scale, 2):
            closest = min(
                range(self.font_scale_combo.count()),
                key=lambda i: abs(self.font_scale_combo.itemData(i) - config.font_scale),
            )
            current_index = closest
        self.font_scale_combo.setCurrentIndex(current_index)
        layout.addWidget(self.font_scale_combo)

        # Escala de TODA la interfaz (ventanas, íconos y letra). Automática =
        # según la resolución de la pantalla (ver screen_scale.py).
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

        self.high_contrast_check = QCheckBox("Alto contraste (texto secundario más legible)")
        self.high_contrast_check.setChecked(config.high_contrast)
        layout.addWidget(self.high_contrast_check)

        layout.addWidget(_section_label("Panel lateral"))
        dock_hint = QLabel(
            "Configuración del modo \"Panel lateral\" (menú del reproductor "
            "completo → Panel lateral): una pestaña anclada a un borde de "
            "la pantalla que se despliega al interactuar con ella."
        )
        dock_hint.setWordWrap(True)
        dock_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(dock_hint)

        dock_row = QHBoxLayout()
        self.dock_edge_combo = ArrowComboBox()
        self.dock_edge_combo.addItem("Borde derecho", "right")
        self.dock_edge_combo.addItem("Borde izquierdo", "left")
        self.dock_edge_combo.setCurrentIndex(max(0, self.dock_edge_combo.findData(config.dock_edge)))
        dock_row.addWidget(self.dock_edge_combo, 1)

        self.dock_style_combo = ArrowComboBox()
        self.dock_style_combo.addItem("Estilo tarjeta (carátula grande)", "card")
        self.dock_style_combo.addItem("Estilo compacto (disco de vinilo)", "compact")
        self.dock_style_combo.setCurrentIndex(
            max(0, self.dock_style_combo.findData(config.dock_style))
        )
        dock_row.addWidget(self.dock_style_combo, 1)
        layout.addLayout(dock_row)

        self.dock_hide_combo = ArrowComboBox()
        self.dock_hide_combo.addItem("Se abre y cierra con clic", "click")
        self.dock_hide_combo.addItem("Se abre y cierra solo (al pasar/alejar el mouse)", "hover")
        self.dock_hide_combo.addItem("Ambas formas a la vez", "both")
        self.dock_hide_combo.setCurrentIndex(
            max(0, self.dock_hide_combo.findData(config.dock_hide_mode))
        )
        layout.addWidget(self.dock_hide_combo)

        self.bar_waves_check = QCheckBox("Ondas alrededor de la barra al sonar")
        self.bar_waves_check.setChecked(getattr(config, "bar_waves_enabled", True))
        layout.addWidget(self.bar_waves_check)

        if theme_bridge is not None:
            self._build_spotify_theme_section(layout, theme_bridge, theme_enabled)

        layout.addWidget(_section_label("Scrobbling"))
        scrobble_hint = QLabel(
            "Envía cada canción escuchada a Last.fm o ListenBrainz, además "
            "de guardarla en el historial local de esta app."
        )
        scrobble_hint.setWordWrap(True)
        scrobble_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(scrobble_hint)

        self.scrobble_combo = ArrowComboBox()
        self.scrobble_combo.addItem("Desactivado", "NONE")
        self.scrobble_combo.addItem("Last.fm", "LASTFM")
        self.scrobble_combo.addItem("ListenBrainz", "LISTENBRAINZ")
        idx = max(0, self.scrobble_combo.findData(config.scrobble_service))
        self.scrobble_combo.setCurrentIndex(idx)
        layout.addWidget(self.scrobble_combo)

        # --- Sub-panel Last.fm ---
        self.lastfm_box = QWidget()
        lastfm_layout = QVBoxLayout(self.lastfm_box)
        lastfm_layout.setContentsMargins(0, 4, 0, 0)
        lastfm_layout.setSpacing(6)
        lastfm_hint = QLabel(
            "Necesita una API key + secreto propios (gratis, en "
            "last.fm/api/account/create) y tu usuario/contraseña — la "
            "contraseña se usa una sola vez para obtener una sesión y no "
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

        # Resultado de la sesión de Last.fm (si se conecta durante esta
        # apertura del diálogo); AppController lo vuelca a config al guardar.
        self.result_lastfm_session_key = config.lastfm_session_key
        self.result_lastfm_username = config.lastfm_username

        # --- Sub-panel ListenBrainz ---
        self.listenbrainz_box = QWidget()
        lb_layout = QVBoxLayout(self.listenbrainz_box)
        lb_layout.setContentsMargins(0, 4, 0, 0)
        lb_layout.setSpacing(6)
        lb_hint = QLabel(
            "Pegá tu 'User Token' personal, disponible en tu perfil de "
            "ListenBrainz (listenbrainz.org/settings) — no hace falta "
            "registrar ninguna aplicación aparte."
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

        layout.addWidget(_section_label("Enlace directo a YouTube"))
        yt_hint = QLabel(
            "Con una clave de API de YouTube (Google Cloud, gratis dentro "
            "de la cuota estándar), tocar la carátula/título de una "
            "canción de YouTube o YouTube Music abre el video exacto en "
            "vez de una búsqueda. Sin clave, sigue abriendo una búsqueda "
            "como hasta ahora."
        )
        yt_hint.setWordWrap(True)
        yt_hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(yt_hint)
        self.youtube_key_input = QLineEdit(config.youtube_api_key)
        self.youtube_key_input.setPlaceholderText("Clave de API de YouTube (opcional)")
        self.youtube_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.youtube_key_input)

        extra_row = QHBoxLayout()
        hotkeys_btn = QPushButton("Teclas multimedia...")
        hotkeys_btn.setObjectName("dialogButton")
        hotkeys_btn.clicked.connect(open_hotkeys_callback)
        extra_row.addWidget(hotkeys_btn)
        history_btn = QPushButton("Historial...")
        history_btn.setObjectName("dialogButton")
        history_btn.clicked.connect(open_history_callback)
        extra_row.addWidget(history_btn)
        layout.addLayout(extra_row)

        stats_btn = QPushButton("Estadísticas de escucha...")
        stats_btn.setObjectName("dialogButton")
        stats_btn.clicked.connect(open_stats_callback)
        layout.addWidget(stats_btn)

        layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setObjectName("dialogButton")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Guardar")
        save_btn.setObjectName("dialogButtonAccent")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

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
        layout.addWidget(_section_label("Tema de Spotify (Spicetify)"))
        hint = QLabel(
            "Cambia el modo del tema \"Switch\" de Spotify desde aquí. Se aplica "
            "al guardar (o al abrir Spotify, si estaba cerrado)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: rgb{Palette.TEXT_DIM}; font-family:'{FONT_BODY}'; "
            f"font-size: 10px; background: transparent;"
        )
        layout.addWidget(hint)

        self.theme_enabled_check = QCheckBox("Controlar el tema de Spotify desde aquí")
        self.theme_enabled_check.setChecked(enabled)
        layout.addWidget(self.theme_enabled_check)

        self.theme_combo = ArrowComboBox()
        self.theme_combo.setAccessibleName("Modo del tema de Spotify")
        self._fill_theme_combo()
        layout.addWidget(self.theme_combo)

        self.theme_status_label = QLabel()
        self.theme_status_label.setWordWrap(True)
        layout.addWidget(self.theme_status_label)

        self.theme_enabled_check.toggled.connect(self._refresh_theme_section)
        # Métodos del propio diálogo (no lambdas): PyQt los desconecta solo
        # cuando el diálogo se destruye al cerrarse (WA_DeleteOnClose).
        bridge.connectionChanged.connect(self._refresh_theme_section)
        bridge.modesChanged.connect(self._on_theme_modes_changed)
        bridge.modeChanged.connect(self._on_theme_mode_changed)
        self._refresh_theme_section()

    def _fill_theme_combo(self, keep: str = ""):
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
        self._fill_theme_combo(keep=self.theme_combo.currentData() or "")

    def _on_theme_mode_changed(self, mode_id: str = ""):
        # Spotify cambió de modo por su cuenta (botón del tema o Ctrl+Alt+T):
        # se refleja en el combo. Si el usuario ya tocó el combo, no se lo pisa
        # en cuanto elige: solo se actualiza cuando el combo está en "Sin cambios".
        if not self.theme_combo.currentData():
            self._fill_theme_combo(keep=mode_id)

    def _refresh_theme_section(self, _checked=None):
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
        self.result_start_minimized = self.start_minimized_check.isChecked()
        self.result_notifications = self.notifications_check.isChecked()
        self.result_empty_play_action = self.empty_play_combo.currentData()
        self.result_lyrics_panel_enabled = self.lyrics_panel_check.isChecked()
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
