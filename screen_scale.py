"""Escala de la interfaz según la resolución de la pantalla.

Problema que resuelve: la app se diseñó con tamaños fijos en píxeles. En
pantallas de baja resolución lógica (p. ej. un portátil de 1366x768 con la
escala de Windows al 125 % o 150 %) la ventana principal, de hasta 606 px de
alto, no cabe y los botones quedan fuera de la pantalla.

Estándar (referencia de diseño)
-------------------------------
Full HD, 1920x1080 al 100 %. Se mide siempre en píxeles LÓGICOS (los que ve
Qt: píxeles físicos / escala de Windows) y sobre el área ÚTIL (sin la barra
de tareas):

    alto útil lógico        factor
    ----------------------  -----------------------------------------------
    < 660                   alto_útil / 660        (se reduce para que quepa)
    660  a  1240             1.00                   (estándar: no se toca)
    > 1240                  alto_útil / 1240       (se amplía, tope 1.50)

660 = la ventana más alta de la app (606 px, la principal a su ancho máximo)
+ 48 px de margen. 1240 = la altura útil de un Full HD ampliada un 15 %: hasta
ahí la interfaz ya se ve bien sin tocar nada. El factor se redondea HACIA
ABAJO a pasos de 0.05 (así nunca se pasa de lo que cabe) y se acota a
[0.70, 1.50].

Cómo se aplica: como factor global de Qt (QT_SCALE_FACTOR), que escala por
igual ventanas, íconos y letra. Debe fijarse ANTES de crear la QApplication,
por eso la pantalla se mide con la API de Windows (ctypes) y no con Qt.

Prioridad: variable de entorno QT_SCALE_FACTOR (si ya existe, no se toca) >
WNP_UI_SCALE > ajuste "Escala de la interfaz" de Configuración > automático.
"""
from __future__ import annotations

import math
import os
import sys

STANDARD_REFERENCE = (1920, 1080)   # solo documentación: Full HD al 100 %
FIT_HEIGHT = 660                    # ventana más alta (606) + 48 de margen
GROW_FROM = 1240                    # sobre este alto útil la interfaz se amplía
MIN_SCALE = 0.70
MAX_SCALE = 1.50
STEP = 0.05
TASKBAR_LOGICAL = 40                # solo para estimaciones/pruebas

# Opciones manuales (0.0 = automática). Se muestran en Configuración.
MANUAL_CHOICES = (0.75, 0.90, 1.00, 1.10, 1.25, 1.50)

# Resultado de la última configure(): lo lee Configuración para mostrar
# "Automática (ahora 85 %)".
_applied = {"factor": 1.0, "source": "default", "work_area": None}


def _floor_step(value: float) -> float:
    # +1e-9 para que 0.8 no caiga a 0.75 por error de coma flotante
    return math.floor(value / STEP + 1e-9) * STEP


def auto_scale(work_height_logical: float) -> float:
    """Factor automático para un alto útil lógico dado (ver tabla arriba)."""
    if work_height_logical <= 0:
        return 1.0
    if work_height_logical < FIT_HEIGHT:
        raw = work_height_logical / FIT_HEIGHT
    elif work_height_logical > GROW_FROM:
        raw = work_height_logical / GROW_FROM
    else:
        return 1.0
    return round(max(MIN_SCALE, min(MAX_SCALE, _floor_step(raw))), 2)


def logical_work_area(physical_w: int, physical_h: int, dpi: int) -> tuple[int, int]:
    """Área útil física + DPI efectivo del monitor -> píxeles lógicos de Qt."""
    k = max(1, dpi) / 96.0
    return round(physical_w / k), round(physical_h / k)


# ------------------------------------------------------------------ Windows
def _query_primary_work_area_win32() -> tuple[int, int, int] | None:
    """(ancho útil físico, alto útil físico, DPI) del monitor principal, o None.

    Se consulta con el hilo en modo PerMonitorV2 (el mismo que usa Qt 6) y se
    restaura después: así no se altera la configuración DPI del proceso (Qt
    imprimiría un aviso si el proceso ya la tuviera fijada) y las coordenadas
    salen en píxeles físicos, sea cual sea el manifiesto del ejecutable."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]

    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PER_MONITOR_AWARE_V2
    try:
        hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)           # MONITOR_DEFAULTTOPRIMARY
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        except Exception:
            pass                                                           # sin shcore: 96 DPI
        w = info.rcWork.right - info.rcWork.left
        h = info.rcWork.bottom - info.rcWork.top
        return (w, h, int(dpi_x.value) or 96) if w > 0 and h > 0 else None
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(previous)


def detect_logical_work_area() -> tuple[int, int] | None:
    """Área útil LÓGICA (ancho, alto) del monitor principal, o None si no se
    puede medir (fuera de Windows, o si la API falla)."""
    if sys.platform != "win32":
        return None
    try:
        raw = _query_primary_work_area_win32()
    except Exception:
        return None
    if raw is None:
        return None
    return logical_work_area(*raw)


# ---------------------------------------------------------------- resolución
def _parse(value: str) -> float | None:
    value = (value or "").strip().lower()
    if value in ("", "auto", "automatica", "automática"):
        return None
    try:
        return float(value.replace(",", ".").rstrip("%")) / (100.0 if value.endswith("%") else 1.0)
    except ValueError:
        return None


def resolve(config_value: float = 0.0, detector=detect_logical_work_area) -> tuple[float, str, tuple[int, int] | None]:
    """(factor, origen, área útil lógica medida) según la prioridad documentada.
    `detector` es inyectable para las pruebas."""
    env = _parse(os.environ.get("WNP_UI_SCALE", ""))
    if env is not None and env > 0:
        return round(max(MIN_SCALE, min(MAX_SCALE, env)), 2), "WNP_UI_SCALE", None
    if config_value and config_value > 0:
        return round(max(MIN_SCALE, min(MAX_SCALE, float(config_value))), 2), "manual", None
    area = detector()
    if area is None:
        return 1.0, "sin_medicion", None
    return auto_scale(area[1]), "automatica", area


def configure(config_value: float = 0.0, detector=detect_logical_work_area) -> float:
    """Decide el factor y lo deja en QT_SCALE_FACTOR. LLAMAR ANTES de crear la
    QApplication. Si el usuario ya fijó QT_SCALE_FACTOR a mano, se respeta."""
    if os.environ.get("QT_SCALE_FACTOR"):
        _applied.update(factor=_parse(os.environ["QT_SCALE_FACTOR"]) or 1.0, source="QT_SCALE_FACTOR", work_area=None)
        return _applied["factor"]
    factor, source, area = resolve(config_value, detector)
    if abs(factor - 1.0) > 1e-6:
        os.environ["QT_SCALE_FACTOR"] = f"{factor:.2f}"
    _applied.update(factor=factor, source=source, work_area=area)
    return factor


def applied() -> dict:
    """Qué factor se aplicó en esta ejecución, de dónde salió y el área medida."""
    return dict(_applied)


def describe_auto() -> str:
    """Texto para el combo de Configuración: 'Escala de la interfaz: auto (ahora 85 %)'."""
    a = _applied
    if a["source"] == "automatica":
        return f"Escala de la interfaz: auto (ahora {round(a['factor'] * 100)} %)"
    return "Escala de la interfaz: auto (según tu pantalla)"
