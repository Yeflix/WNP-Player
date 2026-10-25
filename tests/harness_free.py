"""Ayuda de pruebas: altura de la ventana principal más alta, medida de verdad."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def make_main_height() -> int:
    import time
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    import theme
    from backend import WNPBackend
    from cover_loader import CoverArtLoader
    import main_window as mw

    class L(QObject):
        lyricsReady = pyqtSignal(str, object)
        def request(self, *a, **k): pass

    tallest = 0
    for scale in (0.88, 1.0, 1.15, 1.3):
        theme.apply_dark_palette(app); theme.apply_accessibility(scale, False, reduced_motion=True)
        app.setStyleSheet(theme.build_global_qss())
        w = mw.MainWindow(WNPBackend(), CoverArtLoader(), L()); w.show()
        for cw in (mw.MIN_WIDTH, mw.WIDTH, mw.MAX_WIDTH):
            w.set_content_width(cw)
            t0 = time.time()
            while time.time() - t0 < 0.1: app.processEvents()
            tallest = max(tallest, w.height())
        w.hide(); w.deleteLater()
    return tallest
