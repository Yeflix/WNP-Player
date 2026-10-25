// Lanzador / vigilante sin ventana para Spicetify-AutoFix.
//
// Por que existe: lanzar "powershell.exe" desde el Programador de tareas crea
// una consola. -WindowStyle Hidden la oculta DESPUES de crearla (parpadea y
// roba el foco), y con Windows Terminal como terminal predeterminada puede
// incluso abrir una ventana. Este programa es de tipo "aplicacion de Windows"
// (sin consola propia) y arranca PowerShell con CREATE_NO_WINDOW: la consola
// nunca llega a existir, asi que no hay ventana, ni parpadeo, ni robo de foco.
//
// Dos modos:
//
//   AutoFixSilencioso.exe [opciones]
//       Una comprobacion: ejecuta Spicetify-AutoFix.ps1 oculto, espera a que
//       termine y devuelve su codigo de salida.
//
//   AutoFixSilencioso.exe --vigilar [opciones]
//       Se queda residente (consume ~nada: mira cada pocos segundos si existe
//       el proceso Spotify) y lanza la comprobacion SOLO cuando Spotify se abre
//       o se cierra, en vez de cada N minutos:
//         - al cerrarse Spotify: es el mejor momento, no hay nada que reiniciar,
//           se aplica en silencio y la proxima vez que lo abras ya esta listo;
//         - al abrirse: si lo abriste tu (tiene ventana visible) se puede aplicar
//           ya; si arranco solo en la bandeja (inicio de Windows) NO se reinicia
//           delante de ti: se espera a que lo cierres.
//
// No abre red, no escribe archivos propios, solo ejecuta el .ps1 que tiene al lado.
// Se compila en tu equipo con Instalar-AutoFix.ps1 (Add-Type). Codigo compatible
// con C# 5 (el compilador de Windows PowerShell 5.1).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

static class Lanzador
{
    // Maximo que se le deja correr a UNA comprobacion; la tarea programada puede
    // matar este proceso y el powershell hijo quedaria vivo.
    const int LimiteMs = 14 * 60 * 1000;
    const int SondeoMs = 4000;
    const string NombreSpotify = "Spotify";

    static int Main(string[] args)
    {
        try
        {
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(dir, "Spicetify-AutoFix.ps1");
            if (!File.Exists(script)) return 2;

            bool vigilar = false;
            List<string> extra = new List<string>();
            foreach (string a in args)
            {
                if (a == "--vigilar") vigilar = true;
                // Solo opciones simples (-Forzar, -EstableSegundos 60...); el resto se ignora.
                else if (Regex.IsMatch(a, @"^-?[A-Za-z0-9]{1,40}$")) extra.Add(a);
            }
            return vigilar ? Vigilar(dir, script, extra) : Ejecutar(dir, script, extra);
        }
        catch
        {
            return 1;
        }
    }

    // ------------------------------------------------------------ una comprobacion
    static int Ejecutar(string dir, string script, List<string> extra)
    {
        try
        {
            StringBuilder sb = new StringBuilder();
            sb.Append("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"")
              .Append(script).Append('"');
            foreach (string a in extra) sb.Append(' ').Append(a);

            ProcessStartInfo psi = new ProcessStartInfo("powershell.exe", sb.ToString());
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;                 // CREATE_NO_WINDOW
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.WorkingDirectory = dir;

            using (Process p = Process.Start(psi))
            {
                try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch { }
                if (!p.WaitForExit(LimiteMs))
                {
                    try { p.Kill(); } catch { }
                    return 3;
                }
                return p.ExitCode;
            }
        }
        catch
        {
            return 1;
        }
    }

    // --------------------------------------------------------------- vigilante
    static int Vigilar(string dir, string script, List<string> extra)
    {
        bool esLaUnica;
        // Una sola copia vigilando; otra igual saldria sin hacer nada.
        using (Mutex mutex = new Mutex(true, @"Local\AutoFixSilenciosoVigilante", out esLaUnica))
        {
            if (!esLaUnica) return 0;

            // Comprobacion inicial (al iniciar sesion): normalmente Spotify aun no esta
            // abierto o esta en la bandeja, y asi se arregla en silencio.
            Comprobar(dir, script, extra);
            bool corriendo = SpotifyCorriendo();
            List<DateTime> seguimientos = new List<DateTime>();

            while (true)
            {
                Thread.Sleep(SondeoMs);
                DateTime ahora = DateTime.UtcNow;
                bool hay = SpotifyCorriendo();

                if (hay != corriendo)
                {
                    corriendo = hay;
                    seguimientos.Clear();
                    if (hay)
                    {
                        // Se abrio: dejar que termine de arrancar y, si se esta
                        // actualizando (Spotify.exe recien cambiado), volver a mirar.
                        seguimientos.Add(ahora.AddSeconds(20));
                        seguimientos.Add(ahora.AddSeconds(110));
                        seguimientos.Add(ahora.AddMinutes(6));
                    }
                    else
                    {
                        // Se cerro: aplicar en silencio; segundo intento por si
                        // el instalador de Spotify aun estaba terminando.
                        seguimientos.Add(ahora.AddSeconds(3));
                        seguimientos.Add(ahora.AddMinutes(2));
                    }
                }

                if (seguimientos.Count > 0 && ahora >= seguimientos[0])
                {
                    seguimientos.RemoveAt(0);
                    Comprobar(dir, script, extra);
                    // Si la comprobacion reinicio Spotify, no contarlo como un evento nuevo.
                    corriendo = SpotifyCorriendo();
                }
            }
        }
    }

    // Decide con que opciones lanzar la comprobacion segun el estado de Spotify.
    static void Comprobar(string dir, string script, List<string> extra)
    {
        List<string> args = new List<string>(extra);
        bool yaEsperaCerrado = extra.Contains("-EsperarSpotifyCerrado");
        // Spotify abierto pero sin ventana = en la bandeja: no se reinicia delante del
        // usuario (la ventana saltaria al frente); se espera a que lo cierre.
        if (!yaEsperaCerrado && SpotifyCorriendo() && !SpotifyTieneVentana())
            args.Add("-EsperarSpotifyCerrado");
        Ejecutar(dir, script, args);
    }

    static bool SpotifyCorriendo()
    {
        Process[] ps = null;
        try
        {
            ps = Process.GetProcessesByName(NombreSpotify);
            return ps.Length > 0;
        }
        catch
        {
            return false;
        }
        finally
        {
            if (ps != null) foreach (Process p in ps) p.Dispose();
        }
    }

    // MainWindowHandle solo cuenta ventanas visibles: Spotify minimizado a la
    // bandeja no tiene ninguna.
    static bool SpotifyTieneVentana()
    {
        Process[] ps = null;
        try
        {
            ps = Process.GetProcessesByName(NombreSpotify);
            foreach (Process p in ps)
            {
                try
                {
                    p.Refresh();
                    if (p.MainWindowHandle != IntPtr.Zero) return true;
                }
                catch { }
            }
            return false;
        }
        catch
        {
            return false;
        }
        finally
        {
            if (ps != null) foreach (Process p in ps) p.Dispose();
        }
    }
}
