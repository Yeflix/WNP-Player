"""
Extrae un par de colores de acento (vibrante + complementario) a partir de
la carátula del tema que suena, al estilo de lo que hacen Spotify/Apple
Music/YouTube Music con su "color extraction". Se usa para teñir el borde
de la ventana, el halo de la carátula, la barra de progreso y el botón de
play con colores que combinan con lo que se está reproduciendo, en vez de
un rojo/azul fijo siempre igual.

Pensado para correr en un hilo aparte (es trabajo de CPU, aunque liviano:
se reduce la imagen a un puñado de píxeles antes de analizarla).
"""
from __future__ import annotations

import colorsys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

from theme import Palette

# Si la imagen no aporta un color suficientemente "vivo" (p. ej. carátulas
# en blanco y negro, o muy oscuras/muy claras), usamos estos como base en
# vez de forzar un color soso o directamente negro/blanco.
_FALLBACK = (Palette.ACCENT_A, Palette.ACCENT_B)

# Tamaño al que reducimos la imagen antes de analizarla: de sobra para
# capturar los colores dominantes, y lo bastante chico para que analizar
# cada píxel sea instantáneo (max. 24x24 = 576 píxeles).
_SAMPLE_SIZE = 24


def extract_accent_pair(image: QImage | None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Devuelve (color_primario, color_secundario) como tuplas RGB 0-255.

    Estrategia (simplificada de los "swatches" tipo Android Palette):
    1. Reducir la imagen a una miniatura y recorrer sus píxeles.
    2. Convertir cada uno a HSL y quedarnos solo con los que tienen algo
       de saturación y no son casi-negros ni casi-blancos (esos no sirven
       como acento: no se leerían bien ni destacarían).
    3. Agrupar por "cubos" de tono (hue) para no dejar que un solo color
       que ocupa medio póster domine todo, y puntuar cada cubo por
       saturación y qué tan cerca está de una luminosidad "vibrante"
       (ni muy oscuro ni lavado).
    4. El cubo con mejor puntaje es el color primario. El secundario es
       el segundo mejor cubo cuyo tono esté razonablemente lejos del
       primero (para que el degradado se note, no dos tonos casi iguales).
    5. Si no hay suficientes píxeles "vivos" con los umbrales normales, se
       repite el análisis con umbrales bastante más permisivos antes de
       rendirse (ver _scan_buckets/Bug de robustez más abajo) — cubre
       carátulas oscuras/minimalistas con un tinte de color sutil, un
       estilo MUY común (portadas casi negras con solo un dejo de color)
       que antes caía directo al color por defecto sin intentar nada más.
       Si ni así aparece ningún cubo (carátula realmente plana: negro,
       blanco o gris puro, sin tono alguno), ahí sí devolvemos la pareja
       de acento fija de siempre — no hay tono que extraer.
    """
    if image is None or image.isNull():
        return _FALLBACK

    small = image.scaled(
        _SAMPLE_SIZE, _SAMPLE_SIZE,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    small = small.convertToFormat(QImage.Format.Format_RGB32)

    # Primer intento: umbrales normales (colores claramente "vivos").
    result = _scan_buckets(small, light_min=0.08, light_max=0.92, sat_min=0.18)
    if result is not None:
        return result

    # Segundo intento, bastante más permisivo: cubre carátulas oscuras o
    # minimalistas donde TODA la imagen queda por debajo del umbral de
    # luminosidad normal, pero todavía tiene algún tinte de color real
    # (no es gris/negro/blanco puro) — antes esto se descartaba entero y
    # cualquier carátula así de oscura terminaba siempre en el color por
    # defecto, sin importar qué tan distinta fuera una de otra.
    result = _scan_buckets(small, light_min=0.015, light_max=0.985, sat_min=0.08)
    if result is not None:
        return result

    # Ni con umbrales permisivos apareció un solo píxel con algo de tono:
    # la carátula es realmente plana (negro/blanco/gris puro, sin color
    # que extraer). Ahí sí, el color por defecto es lo correcto, no un
    # fallback por falta de intentos.
    return _FALLBACK


def _scan_buckets(small: QImage, light_min: float, light_max: float, sat_min: float):
    """Un pase de extracción con los umbrales dados. Devuelve el par de
    colores encontrado, o None si ningún píxel calificó (para que
    extract_accent_pair pueda reintentar con umbrales más permisivos)."""
    # 24 cubos de tono (15° cada uno) — suficiente resolución para separar
    # colores distintos sin fragmentar demasiado un mismo tono dominante.
    BUCKETS = 24
    bucket_score = [0.0] * BUCKETS
    bucket_rgb_sum = [[0, 0, 0] for _ in range(BUCKETS)]
    bucket_count = [0] * BUCKETS

    w, h = small.width(), small.height()
    for y in range(h):
        for x in range(w):
            pixel = small.pixel(x, y)
            r = (pixel >> 16) & 0xFF
            g = (pixel >> 8) & 0xFF
            b = pixel & 0xFF
            hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            # Descartamos casi-negros, casi-blancos y colores lavados: no
            # sirven como acento (no se leerían bien contra el fondo oscuro
            # de la app, o directamente no aportan tono).
            if light < light_min or light > light_max or sat < sat_min:
                continue
            bucket = min(BUCKETS - 1, int(hue * BUCKETS))
            # Preferimos colores saturados y de luminosidad media (ni
            # apagados ni quemados de blanco) — puntaje más alto para los
            # que se acercan a ese punto dulce.
            vibrance = sat * (1.0 - abs(light - 0.55))
            bucket_score[bucket] += vibrance
            bucket_rgb_sum[bucket][0] += r
            bucket_rgb_sum[bucket][1] += g
            bucket_rgb_sum[bucket][2] += b
            bucket_count[bucket] += 1

    ranked = sorted(range(BUCKETS), key=lambda i: bucket_score[i], reverse=True)
    ranked = [i for i in ranked if bucket_count[i] > 0]

    if not ranked:
        return None

    def _bucket_avg_rgb(i: int) -> tuple[int, int, int]:
        n = bucket_count[i]
        s = bucket_rgb_sum[i]
        return (round(s[0] / n), round(s[1] / n), round(s[2] / n))

    primary_bucket = ranked[0]
    primary = _bucket_avg_rgb(primary_bucket)
    primary = _boost(primary)

    # Buscamos un segundo color con el tono razonablemente separado del
    # primero (al menos ~4 cubos = 60°), para que el degradado se note en
    # vez de ser casi un solo color. Si no hay ninguno así de lejos,
    # usamos el complementario del primario calculado a mano.
    secondary = None
    for i in ranked[1:]:
        hue_distance = min(abs(i - primary_bucket), BUCKETS - abs(i - primary_bucket))
        if hue_distance >= 4:
            secondary = _boost(_bucket_avg_rgb(i))
            break
    if secondary is None:
        secondary = _complementary(primary)

    return primary, secondary


def _boost(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Sube saturación/luminosidad a un punto dulce 'neón' consistente con
    el resto de la paleta de la app, sin importar qué tan apagado viniera
    el color original de la carátula."""
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    s = max(s, 0.65)
    l = min(max(l, 0.42), 0.62)
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def _complementary(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    h = (h + 0.5) % 1.0
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))
