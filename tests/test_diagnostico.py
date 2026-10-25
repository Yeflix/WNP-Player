"""Script de diagnóstico de anuncios (tools/diagnostico_anuncios.py).

    python tests/test_diagnostico.py
"""
import json, os, socket, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import diagnostico_anuncios as dg

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)


class _Controls:
    def __init__(self, sim, can_seek): self.sim = sim; self.supports_set_position = can_seek
    supports_skip_next = True; supports_skip_previous = True; supports_play_pause = True
    def try_set_position_seconds(self, s): self.sim.on_seek(s)

class _MI:
    def __init__(self, sim, can_seek): self.sim = sim; self.controls = _Controls(sim, can_seek)
    player_name = "YouTube"; state = "PLAYING"; album = ""
    title = property(lambda s: s.sim.title); artist = property(lambda s: s.sim.artist)
    duration_seconds = property(lambda s: s.sim.duration); position_seconds = property(lambda s: int(s.sim.position))
    position_percent = property(lambda s: 100.0 * s.sim.position / max(1, s.sim.duration))

class Sim:
    """Reproductor simulado con reloj propio. `scenario` decide qué hace la orden de posición."""
    def __init__(self, scenario, duration=30, position=5, can_seek=True, natural_end_at=None):
        self.clock = 1000.0; self.scenario = scenario
        self.title, self.artist = "Video de prueba", "Canal"
        self.duration, self.position = duration, position
        self.seeked_at = None; self.natural_end_at = natural_end_at
        self.clients = 1; self.media_info = _MI(self, can_seek)
    def now(self): return self.clock
    def on_seek(self, target):
        self.seeked_at = self.clock
        if self.scenario in ("works", "restart"): self.position = target
    def sleep(self, dt):
        self.clock += dt; self.position += dt
        if self.seeked_at is not None and self.clock - self.seeked_at >= dt:
            if self.scenario == "works" and self.title == "Video de prueba":
                self._become_video()
            elif self.scenario == "restart" and self.clock - self.seeked_at >= 1.0 and self.position >= self.duration - 1.5:
                self.position = 0                       # el anuncio se reinicia (tras ~1 s en el final): mismo medio
        if self.natural_end_at is not None and self.clock >= self.natural_end_at and self.title == "Video de prueba":
            self._become_video()
    def _become_video(self):
        self.title, self.artist, self.duration, self.position = "El video que querías ver", "Otro canal", 600, 0

def probe(sim):
    rec = dg.Recorder(None, echo=lambda *_: None)
    return dg.run_seek_probe(sim, rec, sleep=sim.sleep, now=sim.now), rec

print("== Prueba de salto: cada escenario da su veredicto")
r, _ = probe(Sim("works", duration=30, position=5))
check("el salto funciona (el medio cambia mucho antes del fin natural)", r["verdict"] == dg.V_SALTO_Y_CAMBIO, r["verdict"])
check("la orden fue al penúltimo segundo (duración - 1)", r.get("sent") == 29, str(r.get("sent")))
r, _ = probe(Sim("ignored", duration=30, position=5))
check("orden ignorada -> SIN_EFECTO", r["verdict"] == dg.V_SIN_EFECTO, r["verdict"])
r, _ = probe(Sim("restart", duration=30, position=5))
check("llega al final pero el anuncio se reinicia -> SALTO_SIN_CAMBIO", r["verdict"] == dg.V_SALTO_SIN_CAMBIO, r["verdict"])
r, _ = probe(Sim("ignored", duration=15, position=8, natural_end_at=1000.0 + 7))
check("el anuncio terminaba solo justo en la ventana -> AMBIGUO (no se atribuye a la orden)", r["verdict"] == dg.V_AMBIGUO, r["verdict"])
r, _ = probe(Sim("works", can_seek=False))
check("la fuente no permite cambiar posición -> NO_SOPORTADO", r["verdict"] == dg.V_NO_SOPORTADO, r["verdict"])
sim0 = Sim("ignored", duration=0, position=0); r, _ = probe(sim0)
check("duración 0: no hay a dónde saltar -> SIN_EFECTO con nota", r["verdict"] == dg.V_SIN_EFECTO and "duración" in r.get("note", ""))
class _Boom(Sim):
    def on_seek(self, t): raise RuntimeError("fallo del adaptador")
r, _ = probe(_Boom("works"))
check("si la orden lanza error no rompe el script y queda registrado", r["verdict"] == dg.V_SIN_EFECTO and "fallo del adaptador" in r.get("error", ""))

print("== Registro y resumen")
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "x.jsonl")
    sim = Sim("ignored", duration=600, position=100)
    rec = dg.Recorder(path, echo=lambda *_: None)
    rec.sample(dg.snapshot(sim, sim.now)); sim.sleep(1)
    rec.mark("ad_start", sim.now)
    sim.title, sim.artist, sim.duration, sim.position = "Anuncio X", "Anunciante", 15, 2
    rec.sample(dg.snapshot(sim, sim.now)); rec.sample(dg.snapshot(sim, sim.now))
    rec.mark("ad_end", sim.now)
    rec.sample(dg.snapshot(sim, sim.now))
    summary = dg.summarize(rec.rows); rec.log({"type": "summary", **summary}); rec.close()
    lines = [json.loads(l) for l in open(path, encoding="utf-8")]
    check("el .jsonl tiene muestras, marcas y resumen", {l["type"] for l in lines} == {"sample", "marker", "summary"})
    check("las muestras entre 'a' y 'f' quedan marcadas como anuncio", sum(1 for l in lines if l["type"] == "sample" and l["marked_ad"]) == 2)
    check("el resumen separa lo que se reportó durante el anuncio", summary["reportado_durante_anuncio"][0]["title"] == "Anuncio X"
          and summary["reportado_durante_anuncio"][0]["duration_s"] == 15 and summary["muestras_durante_anuncio"] == 2)
    check("el resumen separa lo reportado fuera del anuncio", any(c["title"] == "Video de prueba" for c in summary["reportado_fuera_de_anuncio"]))
    check("registra si se permitía seek / siguiente durante el anuncio", summary["seek_permitido_durante_anuncio"] == [True] and summary["siguiente_permitido_durante_anuncio"] == [True])
check("changed_fields detecta qué cambió", dg.changed_fields({"title": "a", "state": "x"}, {"title": "b", "state": "x"}) == ["title"])
check("la primera muestra cuenta como cambio de todo", dg.changed_fields(None, {}) == list(dg.FIELDS_WATCHED))

print("== Ejecución real del script contra la librería pywnp (sin navegador)")
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); free_port = s.getsockname()[1]
with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "real.jsonl")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "diagnostico_anuncios.py"), "--port", str(free_port), "--out", out],
                       input="a\nf\nq\n", capture_output=True, text=True, timeout=60, cwd=d)
    check("termina bien (código 0)", r.returncode == 0, (r.stderr or "")[-300:])
    check("imprime el resumen y la ruta del archivo", "RESUMEN" in r.stdout and "Archivo completo" in r.stdout)
    rows = [json.loads(l) for l in open(out, encoding="utf-8")] if os.path.exists(out) else []
    check("el archivo tiene muestras reales de pywnp, las 2 marcas y el resumen",
          any(x["type"] == "sample" for x in rows) and [x["label"] for x in rows if x["type"] == "marker"] == ["ad_start", "ad_end"]
          and rows[-1]["type"] == "summary")
with socket.socket() as busy:
    busy.bind(("127.0.0.1", 0)); busy.listen(1); bp = busy.getsockname()[1]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "diagnostico_anuncios.py"), "--port", str(bp)],
                       capture_output=True, text=True, timeout=30)
    check("puerto ocupado: avisa que hay que cerrar la app y sale con código 2", r.returncode == 2 and "Cierra WNP Player" in r.stdout, r.stdout[-120:])

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
