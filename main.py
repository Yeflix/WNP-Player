#!/usr/bin/env python3
"""
YefriPlayer - Controlador multimedia para Windows (NO reproduce audio).

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
    python main.py --autotest [ARCHIVO]   # comprueba que el .exe trae todo (ver selftest.py)
    python main.py --log [ARCHIVO]        # modo depuración: terminal + registro completo (debug_log.py)
    python main.py --quit                 # cierra la copia abierta (lo usa el instalador)
    python main.py --bienvenida           # muestra el asistente de bienvenida
    python main.py --inicio-windows       # como lo lanza «Iniciar con Windows»
    YefriPlayer.exe --autotest --mostrar  # autoprueba y abre el informe (el .exe no tiene consola)
"""
import argparse
import os
import sys
import traceback


def parse_args():
    parser = argparse.ArgumentParser(
        description="YefriPlayer: controlador multimedia para Windows (no reproduce audio: "
                    "controla lo que suena en el navegador y en las apps de escritorio)")
    parser.add_argument(
        "--port", type=int, default=None,
        help="Puerto en el que escuchará el servidor WebNowPlaying "
             "(si no se indica, se usa el de la última sesión guardada)",
    )
    parser.add_argument(
        "--log", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="Modo depuración: abre una terminal y guarda todo en debug.log "
             "(también con YEFRIPLAYER_DEBUG=1 o un archivo depurar.flag junto al .exe)",
    )
    parser.add_argument(
        "--bienvenida", action="store_true",
        help="Muestra el asistente de bienvenida (lo usa el instalador tras una instalación nueva)",
    )
    parser.add_argument(
        "--inicio-windows", dest="inicio_windows", action="store_true",
        help="Arranque desde «Iniciar con Windows» (solo así se respeta «Iniciar minimizado»)",
    )
    parser.add_argument(
        "--mostrar", action="store_true",
        help="Con --autotest: abre el informe al terminar (el .exe no tiene consola)",
    )
    parser.add_argument(
        "--sin-carga", dest="sin_carga", action="store_true",
        help="Arranca sin la pantalla de carga animada",
    )
    parser.add_argument(
        "--quit", action="store_true",
        help="Cierra la copia de YefriPlayer que esté abierta (la usa el instalador) y sale",
    )
    parser.add_argument(
        "--autotest", nargs="?", const="", default=None, metavar="ARCHIVO",
        help="Comprueba las dependencias y escribe un informe (sin abrir la interfaz)",
    )
    return parser.parse_args()


def _data_dir():
    """Carpeta de datos SIN importar nada del proyecto (se usa cuando el arranque falla)."""
    from pathlib import Path
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "YefriPlayer"


def _report_startup_failure(detail):
    """El .exe no tiene consola: un error al arrancar (una DLL o un módulo que falta)
    era INVISIBLE, el programa simplemente no abría. Aquí se guarda el detalle en
    `startup-error.log` y se muestra un aviso de Windows. Solo usa la biblioteca estándar."""
    where = None
    try:
        import datetime
        folder = _data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        where = folder / "startup-error.log"
        with where.open("a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ---\n{detail}\n")
    except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
        pass
    try:
        if sys.stderr:
            sys.stderr.write(detail)
    except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            texto = ("YefriPlayer no pudo iniciar.\n\n" + detail.strip().splitlines()[-1][:300]
                     + (f"\n\nDetalle completo en:\n{where}" if where else ""))
            ctypes.windll.user32.MessageBoxW(None, texto, "YefriPlayer", 0x10)   # MB_ICONERROR
        except Exception:  # noqa: S110 — no se puede anotar el fallo aquí (es el propio registro/arranque)
            pass


APP_USER_MODEL_ID = "YefriDev.YefriPlayer"   # = AppUserModelID de los accesos directos del instalador


def _set_app_user_model_id():
    """Windows agrupa la barra de tareas y anclaje por este identificador. Sin él,
    ejecutando desde código fuente el programa aparecía como «Python» y con su
    icono; y el acceso directo del instalador no se asociaba a la ventana abierta."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: S110 — solo afecta a cómo se agrupa en la barra de tareas
        pass


def main():
    args = parse_args()
    if args.quit:
        from single_instance import send_quit
        sys.exit(0 if send_quit() else 1)
    if args.autotest is None:
        import debug_log
        if debug_log.requested():
            debug_log.start()
    if args.autotest is not None:
        import selftest
        code = selftest.run(args.autotest or None)
        if args.mostrar:
            selftest.show_report(args.autotest or None)
        sys.exit(code)

    # Estas importaciones van AQUÍ (no arriba del archivo) para que un fallo al
    # cargarlas lo capture el aviso de arranque de `__main__` y no sea silencioso.
    from PyQt6.QtWidgets import QApplication
    from theme import build_global_qss, apply_dark_palette

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

    _set_app_user_model_id()
    QApplication.setQuitOnLastWindowClosed(False)
    # Qt escribe «qt.gui.icc: fromIccProfile: Failed to parse description» cuando
    # el perfil de color del monitor tiene una descripción que no sabe leer. Es
    # inofensivo (solo afecta a la gestión de color de ese monitor) y ensucia la
    # consola en cada arranque. Se silencia ESA categoría, respetando cualquier
    # regla que el usuario ya tuviera en QT_LOGGING_RULES.
    _rules = os.environ.get("QT_LOGGING_RULES", "")
    if "qt.gui.icc" not in _rules:
        os.environ["QT_LOGGING_RULES"] = (_rules + ";" if _rules else "") + "qt.gui.icc=false"
    app = QApplication(sys.argv)
    app.setApplicationName("YefriPlayer")
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

    from single_instance import SingleInstanceGuard

    # La instancia única se comprueba ANTES de cargar la interfaz: una segunda
    # copia no debe mostrar la pantalla de carga ni importar nada pesado.
    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        # Ya había una instancia corriendo: ya se le avisó que se muestre
        # (ver SingleInstanceGuard.try_acquire). Esta segunda instancia no
        # debe seguir arrancando (no debe competir por el mismo puerto).
        return

    # Pantalla de carga (escena 3D) mientras se importa la interfaz; no se muestra
    # si arranca con Windows minimizado (nadie espera ver nada).
    splash = None
    if not (args.inicio_windows and saved_config.start_minimized) and not args.sin_carga:
        try:
            from splash import Splash
            splash = Splash()
            splash.show()
            app.processEvents()
        except Exception:
            splash = None                     # sin pantalla de carga, el arranque sigue igual
    from splash import import_with_splash
    import_with_splash("app_controller", splash)
    from app_controller import AppController

    import logging
    log = logging.getLogger("yefriplayer")
    log.info("arranque: puerto=%s, escala=%s, tema=%s", args.port or saved_config.port,
             saved_config.ui_scale, saved_config.player_theme)
    if splash is not None:
        splash.set_caption("Preparando la ventana…")
        app.processEvents()
    controller = AppController(port=args.port)
    # Cierre por el sistema (apagado/cierre de sesión) o app.quit() desde otro
    # sitio: sin esto no se guardaba la config ni se paraban los hilos de pywnp.
    app.aboutToQuit.connect(controller.shutdown)
    guard.showRequested.connect(controller.show_current)
    # `--quit` (instalador/desinstalador): mismo cierre que «Salir» de la bandeja.
    guard.quitRequested.connect(controller._quit)
    if splash is not None:
        controller.on_before_welcome = splash.dismiss       # la bienvenida tiene su propia escena
    controller.start(show_welcome=args.bienvenida, from_autostart=args.inicio_windows)
    if splash is not None:
        window = controller.visible_window()
        splash.morph_into(window.frameGeometry() if window is not None else None)
    log.info("interfaz lista")

    code = app.exec()
    log.info("cierre normal (código %s)", code)
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _report_startup_failure(traceback.format_exc())
        sys.exit(1)
