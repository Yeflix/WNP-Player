#!/usr/bin/env python3
"""
WNP Player - Reproductor de música independiente basado en WebNowPlaying.

Compatible con YouTube, Spotify (web) y cualquier otro sitio soportado por la
extensión de navegador "WebNowPlaying" (https://wnp.keifufu.dev), además de
reproductores de escritorio en Windows a través de las sesiones multimedia
nativas del sistema.

Recuerda el puerto, el modo (completo/compacto), el zoom y la posición de
ventana entre sesiones (ver config.py), evita que se abran dos instancias a
la vez (ver single_instance.py), verifica que las dependencias necesarias
estén instaladas antes de arrancar (ver startup_checks.py), y muestra un
aviso amigable en vez de un traceback si algo inesperado truena (ver
error_handling.py).

Uso:
    python main.py [--port PUERTO]
"""
import argparse
import sys

from PyQt6.QtWidgets import QApplication

from theme import build_global_qss, apply_dark_palette


def parse_args():
    parser = argparse.ArgumentParser(description="WNP Player")
    parser.add_argument(
        "--port", type=int, default=None,
        help="Puerto en el que escuchará el servidor WebNowPlaying "
             "(si no se indica, se usa el de la última sesión guardada)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Escala de la interfaz según la resolución. Tiene que fijarse ANTES de
    # crear la QApplication (QT_SCALE_FACTOR solo se lee al arrancar Qt).
    import screen_scale
    from config import AppConfig
    saved_config = AppConfig.load()
    screen_scale.configure(saved_config.ui_scale)

    # Aspecto (paleta de colores). Tiene que aplicarse ANTES de construir
    # cualquier ventana e incluso antes de importar app_controller: varios
    # módulos leen Palette al importarse (p. ej. accent.py).
    import theme
    theme.set_player_theme(saved_config.player_theme)

    QApplication.setQuitOnLastWindowClosed(False)
    app = QApplication(sys.argv)
    app.setApplicationName("WNP Player")
    apply_dark_palette(app)
    app.setStyleSheet(build_global_qss())

    import error_handling
    error_handling.install()

    from startup_checks import check_dependencies
    problems = check_dependencies()
    if problems:
        from dialogs import MessageDialog
        body = "No se puede iniciar porque falta lo siguiente:\n\n" + "\n\n".join(problems)
        MessageDialog("Faltan dependencias", body, accent_button_text="Salir").exec()
        sys.exit(1)

    from app_controller import AppController
    from single_instance import SingleInstanceGuard

    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        # Ya había una instancia corriendo: ya se le avisó que se muestre
        # (ver SingleInstanceGuard.try_acquire). Esta segunda instancia no
        # debe seguir arrancando (no debe competir por el mismo puerto).
        return

    controller = AppController(port=args.port)
    # Cierre por el sistema (apagado/cierre de sesión) o app.quit() desde otro
    # sitio: sin esto no se guardaba la config ni se paraban los hilos de pywnp.
    app.aboutToQuit.connect(controller.shutdown)
    guard.showRequested.connect(controller.show_current)
    controller.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
