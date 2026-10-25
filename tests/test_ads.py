"""Anuncios de Spotify: detección, registro aparte, migración y desvío.

    QT_QPA_PLATFORM=offscreen python tests/test_ads.py
"""
import csv, json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp(prefix="wnp_ads_")
os.environ["XDG_CONFIG_HOME"] = TMP           # aislado: no toca datos reales
os.environ["LOCALAPPDATA"] = TMP

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name); print(("  OK   " if cond else "  FALLA"), name, extra)

import ad_filter, ad_log, history, stats
from config import _config_dir
D = _config_dir(); D.mkdir(parents=True, exist_ok=True)

print("== Detección")
check("el caso real: 'Escucha música sin anuncios.' / Spotify", ad_filter.is_ad("Escucha música sin anuncios.", "Spotify", "Spotify"))
check("artista 'Spotify' basta, sin importar el reproductor", ad_filter.is_ad("Lo que sea", "Spotify", "YouTube"))
check("insensible a mayúsculas, tildes y espacios", ad_filter.is_ad("x", "  SPOTIFY ", ""))
check("título típico con artista vacío en Spotify (en/es)",
      ad_filter.is_ad("Advertisement", "", "Spotify") and ad_filter.is_ad("Publicidad", "", "Spotify Web") and ad_filter.is_ad("Anuncio", "Spotify", "Spotify"))
check("'Publicité' con tilde también", ad_filter.is_ad("Publicité", "", "Spotify"))
check("título de anuncio en OTRO reproductor NO cuenta", not ad_filter.is_ad("Advertisement", "", "YouTube"))
check("una canción real no se toca", not ad_filter.is_ad("Fiesta pagana 2.0", "Mägo de Oz", "Spotify"))
check("artista que solo CONTIENE 'Spotify' no cuenta (coincidencia exacta)",
      not ad_filter.is_ad("Cancion", "Spotify Singles", "Spotify") and not ad_filter.is_ad("Cancion", "DJ Spotify Fan", "Spotify"))
check("título 'Anuncio' con un artista real NO cuenta (podría ser una canción)", not ad_filter.is_ad("Anuncio", "Un Artista", "Spotify"))
check("None / vacío no rompe", not ad_filter.is_ad(None, None, None) and not ad_filter.is_ad("", "", ""))
check("devuelve el motivo", ad_filter.detect("x", "Spotify") == "artista_spotify" and ad_filter.detect("Advertisement", "", "Spotify") == "titulo_anuncio")

print("== Reglas del usuario (ad_rules.json)")
(D / "ad_rules.json").write_text(json.dumps({"artistas": ["Coca-Cola"], "titulos": ["Escucha Premium gratis"]}), encoding="utf-8")
ad_filter.reload_rules()
check("artista extra", ad_filter.detect("Algo", "coca-cola", "Spotify") == "regla_usuario_artista")
check("título extra (solo con Spotify)", ad_filter.detect("Escucha Premium gratis", "Otra", "Spotify") == "regla_usuario_titulo"
      and not ad_filter.is_ad("Escucha Premium gratis", "Otra", "YouTube"))
(D / "ad_rules.json").write_text("{esto no es json", encoding="utf-8"); ad_filter.reload_rules()
check("archivo de reglas corrupto: no rompe y no agrega reglas", not ad_filter.is_ad("Algo", "Coca-Cola", "Spotify"))
(D / "ad_rules.json").unlink(); ad_filter.reload_rules()

print("== Registro aparte (CSV)")
check("antes de registrar nada no existe", not ad_log.path().exists() and ad_log.load() == [])
ad_log.add_entry('Título, con "comillas" y\nsalto', "Spotify", "Spotify", 30, "artista_spotify")
ad_log.add_entry("Segundo ñandú — áéíóú", "Spotify", "Spotify", "45", "artista_spotify")
rows = ad_log.load()
check("2 filas, con encabezado una sola vez", len(rows) == 2 and open(ad_log.path(), encoding="utf-8-sig").read().count("played_at,title") == 1)
check("comas, comillas y saltos de línea sobreviven", rows[0]["title"] == 'Título, con "comillas" y\nsalto')
check("tildes y ñ sobreviven", rows[1]["title"] == "Segundo ñandú — áéíóú")
check("el BOM va una sola vez (Excel abre bien las tildes)", open(ad_log.path(), "rb").read().count(b"\xef\xbb\xbf") == 1)
check("columnas esperadas", list(rows[0].keys()) == ad_log.FIELDS)
check("duración como texto numérico y motivo guardado", rows[1]["duration_seconds"] == "45" and rows[1]["reason"] == "artista_spotify")
check("el registro NO se recorta a 300 entradas", ad_log.add_entries([ad_log._row(f"a{i}", "Spotify", "Spotify", 20, "x", None) for i in range(500)]) and len(ad_log.load()) == 502)
ad_log.path().unlink()

print("== Historial: los anuncios no entran")
history._save([])
history.add_entry("Canción A", "Artista A", "Spotify", 200)
res = history.add_entry("Escucha música sin anuncios.", "Spotify", "Spotify", 30)
check("add_entry de un anuncio NO lo agrega al historial", [e["title"] for e in res] == ["Canción A"], str([e["title"] for e in res]))
check("pero lo manda al registro aparte", len(ad_log.load()) == 1 and ad_log.load()[0]["title"] == "Escucha música sin anuncios.")
history.add_entry("Canción B", "Artista B", "Spotify", 180)
check("las canciones siguen entrando normal", [e["title"] for e in history.load()] == ["Canción A", "Canción B"])

print("== Migración de lo que ya estaba en el historial")
ad_log.path().unlink()
old = [
    {"title": "Canción 1", "artist": "X", "player_name": "YouTube", "played_at": "2026-10-01T10:00:00", "duration_seconds": 200},
    {"title": "Escucha música sin anuncios.", "artist": "Spotify", "player_name": "Spotify", "played_at": "2026-10-01T10:04:00", "duration_seconds": 30},
    {"title": "Canción 2", "artist": "Y", "player_name": "Spotify", "played_at": "2026-10-01T10:05:00", "duration_seconds": 210},
    {"title": "Advertisement", "artist": "", "player_name": "Spotify", "played_at": "2026-10-01T10:09:00", "duration_seconds": 15},
]
hp = history._history_path(); hp.write_text(json.dumps(old), encoding="utf-8")
check("antes de migrar, load() ya los oculta", [e["title"] for e in history.load()] == ["Canción 1", "Canción 2"])
check("pero el archivo todavía los tiene", len(history._load_raw()) == 4)
n = history.purge_ads_from_history()
check("migra 2 anuncios", n == 2, str(n))
check("el archivo de historial queda limpio", [e["title"] for e in history._load_raw()] == ["Canción 1", "Canción 2"])
rows = ad_log.load()
check("los 2 anuncios están en el registro con su fecha ORIGINAL", [r["played_at"] for r in rows] == ["2026-10-01T10:04:00", "2026-10-01T10:09:00"], str([r["played_at"] for r in rows]))
check("motivo marcado como migrado", all(r["reason"].startswith("migrado:") for r in rows))
bak = hp.with_suffix(".json.bak")
check("copia de seguridad con el contenido ORIGINAL", bak.exists() and len(json.loads(bak.read_text(encoding="utf-8"))) == 4)
check("idempotente: segunda vez no mueve nada ni duplica", history.purge_ads_from_history() == 0 and len(ad_log.load()) == 2)
bak_mtime = bak.stat().st_mtime
hp.write_text(json.dumps(old + [{"title": "X", "artist": "Spotify", "player_name": "Spotify", "played_at": "2026-10-02T09:00:00", "duration_seconds": 5}]), encoding="utf-8")
history.purge_ads_from_history()
check("la copia de seguridad NO se sobreescribe", bak.stat().st_mtime == bak_mtime and len(json.loads(bak.read_text(encoding="utf-8"))) == 4)
hp.write_text("esto no es json", encoding="utf-8")
check("historial corrupto: no rompe", history.purge_ads_from_history() == 0 and history.load() == [])

print("== Estadísticas sin anuncios")
ents = [{"title": "Escucha música sin anuncios.", "artist": "Spotify", "player_name": "Spotify", "played_at": datetime_iso if (datetime_iso := time.strftime("%Y-%m-%dT%H:%M:%S")) else "", "duration_seconds": 30}] * 4 + \
       [{"title": "Canción real", "artist": "Real", "player_name": "Spotify", "played_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "duration_seconds": 200}]
hp.write_text(json.dumps(ents), encoding="utf-8")
ad_log.path().unlink(missing_ok=True)
summary = stats.summary(history.load(), days=7)
check("el resumen cuenta solo la canción real", summary["plays"] == 1, str(summary))
check("lo más escuchado no incluye el anuncio", [t for t, _, _ in stats.top_songs(history.load())] == ["Canción real"])
check("y los artistas top tampoco", "Spotify" not in [a for a, _ in stats.top_artists(history.load())])

print("== Controlador: desvío completo")
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import theme
theme.apply_dark_palette(app); theme.apply_accessibility(1.0, False, reduced_motion=True); app.setStyleSheet(theme.build_global_qss())
hp.write_text(json.dumps(old), encoding="utf-8"); ad_log.path().unlink(missing_ok=True)
from app_controller import AppController
from backend import PlayerState
ctrl = AppController(port=54331)
ctrl.TRACK_SETTLE_MS = 0   # estos tests comprueban la lógica de anuncios, no el debounce (ver test_fixes_ronda3)
check("al arrancar migra los anuncios del historial", ctrl._migrated_ads == 2 and len(ad_log.load()) == 2, str(ctrl._migrated_ads))
calls = {"scrobble": [], "stop": 0, "notify": []}
ctrl.scrobbler.track_changed = lambda *a, **k: calls["scrobble"].append(a)
real_stop = ctrl.scrobbler.stop_pending
ctrl.scrobbler.stop_pending = lambda: calls.__setitem__("stop", calls["stop"] + 1)
ctrl.config.notifications_enabled = True
ctrl._show_track_notification = lambda s: calls["notify"].append(s.title)
def st(title, artist, player="Spotify", state="PLAYING"):
    return PlayerState(connected=True, player_name=player, state=state, title=title, artist=artist, album="", duration="0:30",
                       duration_seconds=30, can_play_pause=True)
n_hist, n_ads = len(history.load()), len(ad_log.load())
ctrl._on_playback_state_changed(st("Escucha música sin anuncios.", "Spotify"))
check("anuncio: NO entra al historial", len(history.load()) == n_hist)
check("anuncio: SÍ va al registro aparte", len(ad_log.load()) == n_ads + 1 and ad_log.load()[-1]["title"] == "Escucha música sin anuncios.")
check("anuncio: NO se scrobblea", calls["scrobble"] == [])
check("anuncio: se cancela el scrobble pendiente", calls["stop"] == 1)
check("anuncio: NO dispara la notificación de nueva canción", calls["notify"] == [])
ctrl._on_playback_state_changed(st("Escucha música sin anuncios.", "Spotify"))
check("el mismo anuncio repetido sin cambio no se duplica", len(ad_log.load()) == n_ads + 1)
ctrl._on_playback_state_changed(st("Canción nueva", "Alguien"))
check("la canción siguiente sí entra al historial", history.load()[-1]["title"] == "Canción nueva")
check("la canción siguiente sí se scrobblea", len(calls["scrobble"]) == 1)
check("la canción siguiente sí notifica", calls["notify"] == ["Canción nueva"])
texts = [a.text() for a in ctrl.tray.contextMenu().actions()]
check("la bandeja tiene 'Registro de anuncios (CSV)...'", any("Registro de anuncios" in t for t in texts), str(texts))
shown = []
ctrl.tray.showMessage = lambda *a, **k: shown.append(a[1] if len(a) > 1 else "")
ad_log.path().unlink()
ctrl._open_ad_log()
check("sin registro todavía: avisa en vez de fallar", len(shown) == 1 and "ningún anuncio" in shown[0], str(shown))

print(f"\nRESULTADO: {len(PASS)} ok, {len(FAIL)} fallas")
for f in FAIL: print("  FALLA:", f)
sys.exit(1 if FAIL else 0)
