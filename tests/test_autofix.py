"""Spicetify AutoFix: comprobaciones estáticas (no hace falta Windows ni PowerShell).

Las reglas que más importan y que un cambio podría romper sin darse cuenta:
- `spicetify backup apply` ABRE Spotify al terminar: si estaba cerrado hay que
  pasar -n (--no-restart), o el vigilante lo reabre justo cuando el usuario lo cerró.
- Spicetify puede preguntar ([Y/n]); la corrida oculta no tiene a nadie que conteste:
  se le pasan respuestas por la entrada estándar.
- Los .ps1 llevan BOM UTF-8 (Windows PowerShell 5.1 lee sin BOM como ANSI) y CRLF.
- Lanzador.cs debe compilar con C# 5 (Add-Type de Windows PowerShell 5.1).
"""
import re, sys
from pathlib import Path
D = Path(__file__).resolve().parent.parent / "SpicetifyAutoFix"

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FALLA"), name); fails += 0 if cond else 1

fix = (D / "Spicetify-AutoFix.ps1").read_bytes()
inst = (D / "Instalar-AutoFix.ps1").read_bytes()
cs = (D / "Lanzador.cs").read_text(encoding="utf-8")
fix_t = fix.decode("utf-8-sig")

for name, raw in (("Spicetify-AutoFix.ps1", fix), ("Instalar-AutoFix.ps1", inst)):
    check(f"{name}: BOM UTF-8", raw.startswith(b"\xef\xbb\xbf"))
    check(f"{name}: saltos CRLF", b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"))
for bat in D.glob("*.bat"):
    raw = bat.read_bytes()
    check(f"{bat.name}: ASCII y CRLF", raw.isascii() and raw.count(b"\n") == raw.count(b"\r\n"))

check("si Spotify está cerrado se pasa -n (no reabrirlo)",
      re.search(r"if \(-not \$spotifyAbierto\) \{ \$flags \+= '-n' \}", fix_t) is not None)
check("backup apply y restore usan las mismas banderas",
      "($flags + @('backup', 'apply'))" in fix_t and "($flags + @('restore'))" in fix_t)
check("se contestan las preguntas de Spicetify por stdin", "@('y', 'y', 'y') | & $Exe" in fix_t)
check("no se usa -q (silenciaría el registro)", not re.search(r"@\('-q'|'--quiet'", fix_t))
check("una sola corrida a la vez (mutex)", "Local\\SpicetifyAutoFix" in fix_t)
check("se espera a que Spotify termine de actualizarse", "$EstableSegundos" in fix_t)

# Llaves y paréntesis equilibrados (ignorando cadenas y comentarios) en el C#
body = re.sub(r'@"(?:[^"]|"")*"|"(?:\\.|[^"\\])*"|//[^\n]*|\'(?:\\.|[^\'\\])\'', "", cs)
check("Lanzador.cs: llaves equilibradas", body.count("{") == body.count("}"))
check("Lanzador.cs: paréntesis equilibrados", body.count("(") == body.count(")"))
check("Lanzador.cs: sin sintaxis posterior a C# 5 (=>, $\"\", ?., nameof, var x is)",
      not re.search(r"=>|\$\"|\?\.|nameof\(|\bis\s+\w+\s+\w+", body))
check("vigilante: detecta reinicio de Spotify (actualización)", "InicioSpotify()" in cs and "reiniciado" in cs)
check("vigilante: reacciona al pasar de la bandeja a ventana", "ventanaAhora && !ventana" in cs)
check("vigilante: comprobación horaria que nunca reinicia Spotify",
      "PeriodicaMs" in cs and 'args.Add("-EsperarSpotifyCerrado")' in cs)
check("el instalador avisa si se ejecuta como administrador", b"IsInRole" in inst)
print("RESULTADO:", "todo ok" if not fails else f"FALLAS {fails}"); sys.exit(1 if fails else 0)
