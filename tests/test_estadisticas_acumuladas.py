"""Estadísticas acumuladas (stats_store) y exportación del historial a CSV.
Sin Qt: historial y estadísticas son funciones de archivo."""
import csv, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["LOCALAPPDATA"] = tmp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import history, stats, stats_store

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("ok   " if cond else "FALLA"), name, "" if cond else detail); fails += 0 if cond else 1

check("sin datos todavía: summary() es None (el diálogo usa el historial)", stats_store.summary() is None)

# Historial previo a la actualización: se escribe directamente (como un 1.3.x)
old = [{"title": f"Vieja {i % 3}", "artist": "Grupo A", "player_name": "x",
        "played_at": f"2026-01-0{1 + i % 9}T10:00:00", "duration_seconds": 100} for i in range(9)]
history._save(old)
history.add_entry("Nueva", "Grupo B", "Spotify", 200)
s = stats_store.summary()
check("la primera vez se siembra con el historial existente", s["plays"] == 10 and s["total_seconds"] == 1100, str(s))
check("«desde» = la entrada más antigua del historial", s["since"].startswith("2026-01-01"))
check("top artistas", s["top_artists"][0] == ("Grupo A", 9))

# Superar el límite de 300 del historial
for i in range(400):
    history.add_entry(f"Tema {i % 50}", "Grupo C", "YouTube", 60)
check("el historial sigue limitado a 300", len(history.load()) == history.MAX_ENTRIES)
s = stats_store.summary()
check("las estadísticas acumuladas NO se recortan", s["plays"] == 410, str(s["plays"]))
check("veces por canción acumuladas", stats_store.play_count("Tema 0", "Grupo C") == 8)
check("mismo formato que stats.summary",
      set(stats.summary([], None)).issubset(set(s)) and s["total_duration_text"] == stats.format_duration(s["total_seconds"]))
history.add_entry("Tema 49", "Grupo C", "YouTube", 60)
check("la misma canción seguida no suma (igual que el historial)", stats_store.summary()["plays"] == 410)

# Anuncios: ni historial ni estadísticas
before = stats_store.summary()["plays"]
history.add_entry("Advertisement", "Spotify", "Spotify", 30)
check("un anuncio no cuenta", stats_store.summary()["plays"] == before)

# Archivo dañado → se vuelve a sembrar sin romper nada
stats_store.path().write_text("{roto", encoding="utf-8")
check("archivo dañado: summary None, sin excepción", stats_store.summary() is None)
history.add_entry("Otra", "Grupo D", "x", 10)
check("y el siguiente registro lo rehace desde el historial", stats_store.summary()["plays"] == history.MAX_ENTRIES + 1)

# Límite de canciones distintas
old_max = stats_store.MAX_SONGS; stats_store.MAX_SONGS = 5
for i in range(10):
    stats_store.record(f"Única {i}", "Z", 10, f"2026-02-{10 + i}T00:00:00")
data = stats_store.load()
check("tope de canciones: se quitan las de una escucha más antiguas", len(data["songs"]) == 5)
stats_store.MAX_SONGS = old_max

# Exportar CSV
out = os.path.join(tmp, "export.csv")
history._save([{"title": "=HYPERLINK(\"x\")", "artist": "Ñandú", "player_name": "Spotify",
                "played_at": "2026-11-16T09:00:00", "duration_seconds": 215}])
n = history.export_csv(out)
raw = open(out, "rb").read()
rows = list(csv.reader(open(out, encoding="utf-8-sig", newline=""), delimiter=";"))
check("CSV: BOM para Excel y separador ;", raw.startswith(b"\xef\xbb\xbf") and n == 1 and rows[0][0] == "fecha")
check("CSV: acentos intactos", rows[1][2] == "Ñandú")
check("CSV: fórmulas escapadas", rows[1][1].startswith("'="))
try:
    history.export_csv(os.path.join(tmp, "no", "existe", "x.csv"))
    check("CSV: carpeta inexistente → OSError", False)
except OSError:
    check("CSV: carpeta inexistente → OSError", True)

# Borrar historial borra las estadísticas
history.clear()
check("history.clear() también olvida las estadísticas", stats_store.summary() is None and not stats_store.path().exists())
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
