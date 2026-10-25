#!/usr/bin/env python3
"""Diagnóstico de anuncios de YouTube para decidir si un botón "Saltar
anuncio" en el reproductor es viable (opción 3).

QUÉ HACE
  Escucha lo mismo que el reproductor (la extensión WebNowPlaying) y registra,
  cada medio segundo, lo que ESTÁ REPORTANDO: reproductor, estado, título,
  artista, duración, posición y qué controles permite. Así se puede ver:
    - si durante un anuncio cambian el título / la duración / la posición,
    - si "ir a otra posición" está permitido mientras suena un anuncio,
    - y, con la prueba de salto, si mandar la posición al final termina el anuncio.

CÓMO USARLO
  1. Cierra WNP Player (usa el mismo puerto; los dos a la vez no caben).
  2. Abre YouTube en el navegador con la extensión WebNowPlaying.
  3. Ejecuta:      python tools/diagnostico_anuncios.py
  4. Reproduce un video hasta que salga un anuncio y usa estas teclas (+ Enter):
        a   "empezó un anuncio"      (marca el inicio en el registro)
        s   PRUEBA DE SALTO: manda la posición al final y observa 10 s
        f   "terminó el anuncio"     (marca el final)
        q   salir y mostrar el resumen
     Conviene repetirlo con anuncios saltables y no saltables, y con y sin
     la prueba 's' (para ver cómo se comporta el anuncio sin tocarlo).
  5. Al salir deja un archivo  diagnostico_anuncios_<fecha>.jsonl  y muestra un
     resumen. Pásame ese resumen (o el archivo) y decidimos.

NO modifica nada de tu cuenta ni de YouTube: solo lee el estado y, si tú pulsas
's', manda UNA orden de posición.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIELDS_WATCHED = ("player", "state", "title", "artist", "album", "duration_s",
                  "can_seek", "can_next", "can_prev", "can_play_pause")
SAMPLE_INTERVAL_S = 0.5
PROBE_WINDOW_S = 10.0

# Veredictos de la prueba de salto
V_NO_SOPORTADO = "NO_SOPORTADO"          # la fuente no permite cambiar la posición
V_SIN_EFECTO = "SIN_EFECTO"              # se mandó la orden y la posición siguió normal
V_SALTO_Y_CAMBIO = "SALTO_Y_CAMBIO"      # llegó al final Y el medio cambió: probable salto logrado
V_SALTO_SIN_CAMBIO = "SALTO_SIN_CAMBIO"  # llegó al final pero el medio sigue igual: ambiguo
V_AMBIGUO = "AMBIGUO_FIN_NATURAL"        # el medio cambió, pero justo cuando el anuncio habría terminado solo


# ------------------------------------------------------------------ lectura
def snapshot(wnp, now=time.time) -> dict:
    """Foto de lo que reporta la extensión en este instante."""
    mi, ctr = wnp.media_info, wnp.media_info.controls
    return {
        "t": round(now(), 3),
        "clients": getattr(wnp, "clients", 0),
        "player": str(mi.player_name or ""),
        "state": str(mi.state or ""),
        "title": str(mi.title or ""),
        "artist": str(mi.artist or ""),
        "album": str(mi.album or ""),
        "duration_s": int(mi.duration_seconds or 0),
        "position_s": int(mi.position_seconds or 0),
        "position_pct": round(float(mi.position_percent or 0.0), 1),
        "can_seek": bool(ctr.supports_set_position),
        "can_next": bool(ctr.supports_skip_next),
        "can_prev": bool(ctr.supports_skip_previous),
        "can_play_pause": bool(ctr.supports_play_pause),
    }


def changed_fields(prev: "dict | None", cur: dict) -> list[str]:
    if prev is None:
        return list(FIELDS_WATCHED)
    return [k for k in FIELDS_WATCHED if prev.get(k) != cur.get(k)]


# ------------------------------------------------------------------ registro
class Recorder:
    """Guarda cada muestra y cada marca en memoria y en un .jsonl."""

    def __init__(self, path: "str | None" = None, echo=print):
        self.rows: list[dict] = []
        self.path = path
        self.echo = echo
        self._fh = open(path, "w", encoding="utf-8") if path else None
        self._last: "dict | None" = None
        self._last_print = 0.0
        self.in_ad = False          # entre las marcas 'a' y 'f'

    def _write(self, row: dict):
        self.rows.append(row)
        if self._fh:
            self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._fh.flush()

    def sample(self, snap: dict):
        row = dict(snap, type="sample", marked_ad=self.in_ad)
        self._write(row)
        diff = changed_fields(self._last, snap)
        if diff or snap["t"] - self._last_print >= 10:
            tag = "CAMBIO " + ",".join(diff) if diff else "latido"
            self.echo(f"[{time.strftime('%H:%M:%S', time.localtime(snap['t']))}] {tag}: {snap['player']!r} {snap['state']} "
                      f"| {snap['title'][:40]!r} / {snap['artist'][:25]!r} | dur={snap['duration_s']}s pos={snap['position_s']}s "
                      f"| seek={'sí' if snap['can_seek'] else 'NO'} sig={'sí' if snap['can_next'] else 'NO'}")
            self._last_print = snap["t"]
        self._last = snap

    def mark(self, label: str, now=time.time):
        if label == "ad_start":
            self.in_ad = True
        elif label == "ad_end":
            self.in_ad = False
        self._write({"type": "marker", "label": label, "t": round(now(), 3)})
        self.echo(f"    >>> marca: {label}")

    def log(self, row: dict):
        self._write(row)

    def close(self):
        if self._fh:
            self._fh.close()


# --------------------------------------------------------------- prueba de salto
def run_seek_probe(wnp, recorder: Recorder, sleep=time.sleep, now=time.time,
                   window_s: float = PROBE_WINDOW_S, interval_s: float = 0.25) -> dict:
    """Manda la posición al final del medio actual y observa qué pasa.

    Veredicto:
      NO_SOPORTADO     la fuente no admite cambiar la posición.
      SIN_EFECTO       la posición nunca se acercó al final.
      SALTO_Y_CAMBIO   el medio cambió (duración o título) ANTES de cuando el
                       anuncio habría terminado solo: lo normal si el salto
                       funcionó y volvió el video.
      AMBIGUO_FIN_NATURAL  cambió, pero justo cuando el anuncio terminaba solo:
                       no se puede atribuir a la orden (repetir con otro anuncio).
      SALTO_SIN_CAMBIO llegó al final mucho antes de lo natural pero el medio
                       sigue siendo el mismo (p. ej. el anuncio se reinició).
    """
    before = snapshot(wnp, now)
    result = {"type": "probe", "t": before["t"], "before": before}
    if not before["can_seek"]:
        result["verdict"] = V_NO_SOPORTADO
        recorder.log(result); recorder.echo("    >>> PRUEBA: la fuente NO permite cambiar la posición.")
        return result
    if before["duration_s"] <= 1:
        result["verdict"] = V_SIN_EFECTO
        result["note"] = "duración desconocida (<= 1 s): no hay a dónde saltar"
        recorder.log(result); recorder.echo("    >>> PRUEBA: la duración reportada es 0; no se puede saltar.")
        return result

    target = max(0, before["duration_s"] - 1)
    recorder.echo(f"    >>> PRUEBA: posición {before['position_s']}s -> {target}s de {before['duration_s']}s "
                  f"(observando {window_s:.0f} s)")
    try:
        wnp.media_info.controls.try_set_position_seconds(target)
        result["sent"] = target
    except Exception as exc:                       # noqa: BLE001
        result["verdict"] = V_SIN_EFECTO
        result["error"] = repr(exc)
        recorder.log(result); recorder.echo(f"    >>> PRUEBA: error al mandar la orden: {exc!r}")
        return result

    # Cuándo habría terminado el anuncio SOLO. Si el medio cambia antes de ese
    # momento, el cambio se debe a nuestra orden; si cambia justo en ese
    # momento, puede ser el fin natural y no se puede afirmar nada.
    natural_eta = max(0, before["duration_s"] - before["position_s"])
    t0 = now()
    reached_end = media_changed = False
    changed_early = None
    after = []
    while now() - t0 < window_s:
        sleep(interval_s)
        s = snapshot(wnp, now)
        recorder.sample(s)
        after.append(s)
        elapsed = now() - t0
        early = elapsed < natural_eta - 2
        same_media = s["duration_s"] == before["duration_s"] and s["title"] == before["title"]
        if same_media and s["duration_s"] > 0 and s["position_s"] >= s["duration_s"] - 2 and early:
            reached_end = True                  # llegó al final MUCHO antes de lo natural
        if (abs(s["duration_s"] - before["duration_s"]) > 5 or s["title"] != before["title"]
                or s["artist"] != before["artist"]):
            media_changed, changed_early = True, early
            break
    result["natural_eta_s"] = natural_eta
    result["after"] = after[-6:]
    if media_changed:
        result["verdict"] = V_SALTO_Y_CAMBIO if (changed_early or reached_end) else V_AMBIGUO
    else:
        result["verdict"] = V_SALTO_SIN_CAMBIO if reached_end else V_SIN_EFECTO
    last = after[-1] if after else before
    recorder.log(result)
    recorder.echo(f"    >>> PRUEBA: veredicto {result['verdict']} | ahora: {last['title'][:40]!r} "
                  f"dur={last['duration_s']}s pos={last['position_s']}s state={last['state']}")
    return result


# ------------------------------------------------------------------- resumen
def summarize(rows: list[dict]) -> dict:
    """Qué reportó la extensión dentro y fuera de las marcas de anuncio."""
    def combos(samples):
        seen = {}
        for s in samples:
            k = (s["player"], s["title"], s["artist"], s["duration_s"])
            seen[k] = seen.get(k, 0) + 1
        return [{"player": k[0], "title": k[1], "artist": k[2], "duration_s": k[3], "muestras": n}
                for k, n in sorted(seen.items(), key=lambda kv: -kv[1])]
    samples = [r for r in rows if r.get("type") == "sample"]
    ad = [s for s in samples if s.get("marked_ad")]
    normal = [s for s in samples if not s.get("marked_ad")]
    probes = [r for r in rows if r.get("type") == "probe"]
    return {
        "muestras_total": len(samples),
        "muestras_durante_anuncio": len(ad),
        "reportado_durante_anuncio": combos(ad),
        "reportado_fuera_de_anuncio": combos(normal)[:5],
        "seek_permitido_durante_anuncio": sorted({s["can_seek"] for s in ad}) if ad else None,
        "siguiente_permitido_durante_anuncio": sorted({s["can_next"] for s in ad}) if ad else None,
        "pruebas_de_salto": [{"veredicto": p.get("verdict"), "antes": {k: p["before"][k] for k in ("title", "duration_s", "position_s", "state")},
                              "orden_enviada_a_s": p.get("sent")} for p in probes],
    }


# --------------------------------------------------------------------- main
def _port_is_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico de anuncios de YouTube (ver la cabecera del archivo).")
    ap.add_argument("--port", type=int, default=None, help="puerto de WebNowPlaying (por defecto, el de tu configuración)")
    ap.add_argument("--out", default=None, help="archivo de salida .jsonl")
    args = ap.parse_args(argv)

    port = args.port
    if port is None:
        try:
            from config import AppConfig
            port = int(getattr(AppConfig.load(), "port", 0) or 0) or 1234
        except Exception:
            port = 1234
    if not _port_is_free(port):
        print(f"El puerto {port} está en uso. Cierra WNP Player (o cualquier otro programa que lo use) y vuelve a intentar.")
        return 2

    out = args.out or f"diagnostico_anuncios_{datetime.datetime.now():%Y%m%d_%H%M%S}.jsonl"
    import pywnp_patch
    pywnp_patch.apply()
    from pywnp import WNPRedux
    WNPRedux.start(port, "diagnostico", lambda level, msg: None)
    rec = Recorder(out)
    print(__doc__.split("CÓMO USARLO")[1].split("NO modifica")[0].rstrip())
    print(f"\nEscuchando en el puerto {port}. Registro: {out}\n")

    stop = threading.Event()
    commands: list[str] = []

    def reader():
        for line in sys.stdin:
            commands.append(line.strip().lower())
            if commands[-1] == "q":
                break
        stop.set()
    threading.Thread(target=reader, daemon=True).start()

    def drain():
        """Ejecuta los comandos pendientes en orden."""
        while commands:
            cmd = commands.pop(0)
            if cmd == "a": rec.mark("ad_start")
            elif cmd == "f": rec.mark("ad_end")
            elif cmd == "s": run_seek_probe(WNPRedux, rec)

    try:
        first = True
        while first or not stop.is_set():          # al menos UNA muestra, aunque la entrada ya esté cerrada
            first = False
            rec.sample(snapshot(WNPRedux))
            drain()
            time.sleep(SAMPLE_INTERVAL_S)
        # El hilo del teclado puede marcar "salir" ANTES de que el bucle haya
        # procesado lo escrito justo antes de la 'q' (p. ej. 'f' y luego 'q'):
        # sin este último vaciado, esas marcas se perdían.
        drain()
    except KeyboardInterrupt:
        pass
    finally:
        summary = summarize(rec.rows)
        rec.log({"type": "summary", **summary})
        rec.close()
        try:
            WNPRedux.stop()
        except Exception:
            pass
        print("\n================ RESUMEN ================")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nArchivo completo: {os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
