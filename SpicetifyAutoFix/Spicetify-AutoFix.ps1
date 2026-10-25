<#
.SYNOPSIS
  Reaplica Spicetify solo, cuando Spotify se actualiza o pierde el parche.

.DESCRIPTION
  Pensado para correr cada pocos minutos desde el Programador de tareas
  (lo instala Instalar-AutoFix.ps1). Cada vez que corre, hace una comprobacion
  barata (sin releer los archivos de Spotify si no cambiaron desde la vez anterior) y SOLO si hace falta ejecuta:

      spicetify backup apply

  Cuando hace falta:
    A) La version de Spotify.exe NO coincide con la version guardada en la
       seccion [Backup] de config-xpui.ini  -> Spotify se actualizo.
       (Es el caso de las actualizaciones: la guia oficial de Spicetify manda
       correr "backup apply", NO "apply" a secas, que puede dejar Spotify roto.)
    B) La version coincide pero los archivos de Spotify ya no contienen el
       parche de Spicetify (p. ej. Spotify reparo/reinstalo sus archivos).

  "backup apply" ya incluye el "apply": no hace falta correr "spicetify apply"
  despues.

  Protecciones (para que nunca entre en bucle ni deje Spotify roto):
    - Espera a que Spotify termine de actualizarse (Spotify.exe estable).
    - Una sola instancia a la vez (mutex).
    - Pausa entre intentos y maximo de fallos por version de Spotify
      (pausado, reintenta solo cada 6 horas).
    - Si "backup apply" falla, corre "spicetify restore" para que Spotify
      arranque normal (sin tema) en vez de quedar en blanco.
    - No hace nada si Spicetify nunca se aplico en este equipo.
    - Si la deteccion B se equivoca (el parche sigue sin verse despues de
      aplicar bien), la desactiva sola; lo mismo con la comparacion de
      versiones (A) si la version guardada nunca llega a coincidir.

  Archivos (en %LOCALAPPDATA%\SpicetifyAutoFix):
    autofix.log              eventos importantes (se rota solo)
    ultima-comprobacion.txt  una linea, se sobrescribe en cada corrida
    estado.json              memoria entre corridas

.PARAMETER SoloComprobar
  No ejecuta nada: solo dice que haria.
.PARAMETER Forzar
  Ignora esperas, pausas y limites y aplica ya (si hay motivo).
.PARAMETER EsperarSpotifyCerrado
  No toca nada mientras Spotify este abierto (Spicetify reinicia Spotify al aplicar).
.PARAMETER SinDeteccionDeParche
  Desactiva la deteccion B: solo reaplica cuando Spotify cambia de version.
#>
[CmdletBinding()]
param(
    [switch]$SoloComprobar,
    [switch]$Forzar,
    [switch]$EsperarSpotifyCerrado,
    [switch]$SinDeteccionDeParche,
    [int]$EstableSegundos = 90,
    [int]$EnfriamientoMinutos = 30,
    [int]$MaxFallos = 3,
    [string]$SpotifyDir = (Join-Path $env:APPDATA 'Spotify'),
    [string]$SpicetifyExe = '',
    [string]$ConfigIni = (Join-Path $env:APPDATA 'spicetify\config-xpui.ini'),
    [string]$DatosDir = (Join-Path $env:LOCALAPPDATA 'SpicetifyAutoFix'),
    # Solo para pruebas
    [string]$VersionSpotify = '',
    [string]$NombreProceso = 'Spotify'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

# ----------------------------------------------------------------- utilidades
$script:LogPath = Join-Path $DatosDir 'autofix.log'
$script:StatePath = Join-Path $DatosDir 'estado.json'
$script:BeatPath = Join-Path $DatosDir 'ultima-comprobacion.txt'

function Write-Log([string]$Message) {
    try {
        if ((Test-Path -LiteralPath $script:LogPath) -and ((Get-Item -LiteralPath $script:LogPath).Length -gt 512KB)) {
            Move-Item -LiteralPath $script:LogPath -Destination ($script:LogPath + '.1') -Force
        }
        $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
        Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
    } catch { }
    if ($SoloComprobar -or $Forzar -or $VerbosePreference -eq 'Continue') { Write-Host $Message }
}

function Set-Heartbeat([string]$Result) {
    try {
        $text = '{0} | {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $Result
        Set-Content -LiteralPath $script:BeatPath -Value $text -Encoding UTF8
    } catch { }
}

function Get-State {
    $default = [ordered]@{
        version          = ''     # version base de Spotify del ultimo intento
        fallos           = 0      # fallos seguidos con esa version
        ultimoIntento    = ''
        ultimoIntentoB   = ''
        ultimoExito      = ''
        deteccionInutil  = $false
        huellaParche     = ''     # tamano+fecha de los archivos de Spotify cuando se comprobo el parche
        parcheResultado  = ''     # 'true'/'false': lo que se encontro (se reutiliza si nada cambio)
        comparacionInutil = $false
        pausaAvisada     = ''
    }
    if (Test-Path -LiteralPath $script:StatePath) {
        try {
            $raw = Get-Content -LiteralPath $script:StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($k in @($default.Keys)) {
                if ($raw.PSObject.Properties.Name -contains $k) { $default[$k] = $raw.$k }
            }
        } catch { Write-Log 'estado.json ilegible; se empieza de cero.' }
    }
    return $default
}

function Save-State($State) {
    try { ($State | ConvertTo-Json) | Set-Content -LiteralPath $script:StatePath -Encoding UTF8 } catch { }
}

function Get-VersionBase([string]$v) {
    if ($v -match '^\s*(\d+)\.(\d+)\.(\d+)\.(\d+)') { return ('{0}.{1}.{2}.{3}' -f $Matches[1], $Matches[2], $Matches[3], $Matches[4]) }
    return $null
}

function Get-IniValue([string]$Path, [string]$Section, [string]$Key) {
    $current = ''
    $pattern = '^' + [regex]::Escape($Key) + '\s*=\s*(.*)$'
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        $t = $line.Trim()
        if ($t -match '^\[(.+)\]$') { $current = $Matches[1]; continue }
        if ($current -eq $Section -and $t -match $pattern) { return $Matches[1].Trim() }
    }
    return $null
}

function Get-SpotifyVersion([string]$ExePath) {
    if ($VersionSpotify) { return $VersionSpotify }
    $info = (Get-Item -LiteralPath $ExePath).VersionInfo
    if ($info.ProductVersion) { return [string]$info.ProductVersion }
    return [string]$info.FileVersion
}

# $true = el parche de Spicetify esta en los archivos de Spotify, $false = no esta,
# $null = no se pudo saber (no se toca nada). El parche deja la palabra "Spicetify"
# dentro de los .js de xpui; el Spotify original no la contiene.
function Test-ParcheAplicado([string]$Dir) {
    $apps = Join-Path $Dir 'Apps'
    $folder = Join-Path $apps 'xpui'
    $spa = Join-Path $apps 'xpui.spa'
    $scanned = $false

    if (Test-Path -LiteralPath $folder -PathType Container) {
        foreach ($f in Get-ChildItem -LiteralPath $folder -Filter '*.js' -File -ErrorAction SilentlyContinue) {
            try {
                $scanned = $true
                if ([System.IO.File]::ReadAllText($f.FullName).Contains('Spicetify')) { return $true }
            } catch { }
        }
    }
    if (Test-Path -LiteralPath $spa -PathType Leaf) {
        try {
            Add-Type -AssemblyName System.IO.Compression
            $fs = [System.IO.File]::Open($spa, 'Open', 'Read', 'ReadWrite')
            try {
                $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Read)
                try {
                    foreach ($entry in $zip.Entries) {
                        if (-not $entry.FullName.EndsWith('.js')) { continue }
                        $scanned = $true
                        $reader = New-Object System.IO.StreamReader($entry.Open())
                        try { if ($reader.ReadToEnd().Contains('Spicetify')) { return $true } } finally { $reader.Dispose() }
                    }
                } finally { $zip.Dispose() }
            } finally { $fs.Dispose() }
        } catch { }
    }
    if ($scanned) { return $false }
    return $null
}

# "Huella" barata (sin leer contenido) de los archivos donde se busca el parche:
# si no cambio nada desde la ultima comprobacion, el resultado sigue valiendo y se
# evita descomprimir y leer xpui.spa (decenas de MB) cada pocos minutos.
function Get-HuellaParche([string]$Dir) {
    $apps = Join-Path $Dir 'Apps'
    $partes = @()
    $spa = Join-Path $apps 'xpui.spa'
    if (Test-Path -LiteralPath $spa -PathType Leaf) {
        $i = Get-Item -LiteralPath $spa
        $partes += ('spa:{0}:{1}' -f $i.Length, $i.LastWriteTimeUtc.Ticks)
    }
    $folder = Join-Path $apps 'xpui'
    if (Test-Path -LiteralPath $folder -PathType Container) {
        foreach ($f in @(Get-ChildItem -LiteralPath $folder -Filter '*.js' -File -ErrorAction SilentlyContinue | Sort-Object Name)) {
            $partes += ('{0}:{1}:{2}' -f $f.Name, $f.Length, $f.LastWriteTimeUtc.Ticks)
        }
    }
    if ($partes.Count -eq 0) { return '' }
    return ($partes -join '|')
}

function Get-ParcheCacheado($State) {
    $huella = Get-HuellaParche $SpotifyDir
    if (-not $Forzar -and $huella -and $State.huellaParche -eq $huella -and $State.parcheResultado -in @('true', 'false')) {
        return ($State.parcheResultado -eq 'true')
    }
    $r = Test-ParcheAplicado $SpotifyDir
    if ($huella -and $null -ne $r) {
        $State.huellaParche = $huella
        $State.parcheResultado = if ($r) { 'true' } else { 'false' }
        Save-State $State
    }
    return $r
}

function Invoke-Spicetify([string]$Exe, [string[]]$CommandArgs) {
    $text = ''
    $code = 1
    try {
        $text = (& $Exe @CommandArgs 2>&1 | ForEach-Object { "$_" } | Out-String)
        $code = $LASTEXITCODE
    } catch {
        $text = $_.Exception.Message
        $code = 1
    }
    $text = [regex]::Replace($text, '\x1B\[[0-9;]*[A-Za-z]', '').Trim()
    return [pscustomobject]@{ Code = $code; Output = $text }
}

function Format-Output([string]$Text) {
    if (-not $Text) { return '(sin salida)' }
    $lines = @($Text -split "`r?`n" | Where-Object { $_.Trim() })
    if ($lines.Count -gt 12) { $lines = @('...') + $lines[($lines.Count - 12)..($lines.Count - 1)] }
    return ($lines -join ' / ')
}

# --------------------------------------------------------------------- inicio
try { New-Item -ItemType Directory -Force -Path $DatosDir | Out-Null } catch { }

$mutex = New-Object System.Threading.Mutex($false, 'Local\SpicetifyAutoFix')
$hasMutex = $false
try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) { exit 0 }   # ya hay otra corrida en marcha

    # 1) Que existan Spicetify, su configuracion y Spotify de escritorio
    if (-not $SpicetifyExe) {
        $cmd = Get-Command spicetify -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $SpicetifyExe = $cmd.Source }
        else { $SpicetifyExe = Join-Path $env:LOCALAPPDATA 'spicetify\spicetify.exe' }
    }
    if (-not (Test-Path -LiteralPath $SpicetifyExe)) { Set-Heartbeat 'sin hacer nada: no encuentro spicetify'; Write-Log "No encuentro spicetify ($SpicetifyExe)."; exit 0 }
    if (-not (Test-Path -LiteralPath $ConfigIni)) { Set-Heartbeat 'sin hacer nada: Spicetify sin configurar'; exit 0 }

    $spotifyExe = Join-Path $SpotifyDir 'Spotify.exe'
    if (-not (Test-Path -LiteralPath $spotifyExe)) { Set-Heartbeat 'sin hacer nada: no encuentro Spotify.exe (version de Microsoft Store?)'; exit 0 }

    # 2) Versiones
    $actual = Get-SpotifyVersion $spotifyExe
    $actualBase = Get-VersionBase $actual
    $backupRaw = Get-IniValue $ConfigIni 'Backup' 'version'
    $backupBase = Get-VersionBase $backupRaw

    if (-not $backupBase) {
        # Nunca se hizo "backup apply" en este equipo: Spicetify no se esta usando, no se interviene.
        Set-Heartbeat 'sin hacer nada: Spicetify nunca se aplico aqui'
        exit 0
    }

    $state = Get-State
    $needA = ($actualBase -and ($actualBase -ne $backupBase) -and -not $state.comparacionInutil)
    $patched = $null
    if (-not $SinDeteccionDeParche -and -not $state.deteccionInutil) { $patched = Get-ParcheCacheado $state }
    $needB = (-not $needA) -and ($patched -eq $false)

    if (-not $needA -and -not $needB) {
        $note = 'todo en orden'
        if ($patched -eq $null -and -not $SinDeteccionDeParche) { $note = 'todo en orden (no pude comprobar el parche)' }
        Set-Heartbeat ("{0}; Spotify {1}" -f $note, $actual)
        if ($SoloComprobar) { Write-Host ("Spotify {0}, backup {1}: no hay nada que hacer." -f $actual, $backupRaw) }
        exit 0
    }

    if ($needA) { $reason = "Spotify se actualizo (ahora $actual, el backup de Spicetify es de $backupRaw)" }
    else { $reason = "Spotify $actual ya no tiene el parche de Spicetify" }

    # 3) Esperas y limites (se saltan con -Forzar)
    if (-not $Forzar) {
        $age = (New-TimeSpan -Start (Get-Item -LiteralPath $spotifyExe).LastWriteTime -End (Get-Date)).TotalSeconds
        if ($age -lt $EstableSegundos) { Set-Heartbeat 'esperando: Spotify se esta actualizando'; exit 0 }

        $updating = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^Spotify(Migrator|Setup|Update|FullSetup)' }
        if ($updating) { Set-Heartbeat 'esperando: hay un instalador de Spotify en marcha'; exit 0 }

        if ($EsperarSpotifyCerrado -and (Get-Process -Name $NombreProceso -ErrorAction SilentlyContinue)) {
            Set-Heartbeat 'esperando: Spotify esta abierto (EsperarSpotifyCerrado)'; exit 0
        }

        # Tras varios fallos seguidos con la misma version de Spotify se pausa, pero cada 6 horas
        # se reintenta una vez por si salio una version de Spicetify que ya la soporta.
        $pausado = $false
        if ($state.version -eq $actualBase -and [int]$state.fallos -ge $MaxFallos) {
            $pausado = $true
            if ($state.ultimoIntento) {
                $horas = (New-TimeSpan -Start ([datetime]$state.ultimoIntento) -End (Get-Date)).TotalHours
                if ($horas -ge 6) { $pausado = $false }
            }
        }
        if ($pausado) {
            Set-Heartbeat ("pausado: {0} fallos seguidos con Spotify {1}" -f $state.fallos, $actual)
            if ($state.pausaAvisada -ne $actualBase) {
                Write-Log ("PAUSADO: 'spicetify backup apply' fallo {0} veces seguidas con Spotify {1}. Seguramente tu version de Spicetify aun no soporta esta version de Spotify: ejecuta 'spicetify upgrade' (se reintenta solo cada 6 horas, o ya con -Forzar)." -f $state.fallos, $actual)
                $state.pausaAvisada = $actualBase
                Save-State $state
            }
            exit 0
        }

        if ($state.ultimoIntento) {
            $since = (New-TimeSpan -Start ([datetime]$state.ultimoIntento) -End (Get-Date)).TotalMinutes
            if ($since -lt $EnfriamientoMinutos) { Set-Heartbeat ("esperando: ultimo intento hace {0:N0} min" -f $since); exit 0 }
        }
        if ($needB -and $state.ultimoIntentoB) {
            $sinceB = (New-TimeSpan -Start ([datetime]$state.ultimoIntentoB) -End (Get-Date)).TotalHours
            if ($sinceB -lt 24) { Set-Heartbeat 'esperando: ya se reaplico por falta de parche hoy'; exit 0 }
        }
    }

    if ($SoloComprobar) {
        Write-Host "Haria: spicetify backup apply  -- motivo: $reason"
        Set-Heartbeat 'solo comprobar: hay que reaplicar'
        exit 0
    }

    # 4) Reaplicar
    Write-Log "Reaplicando Spicetify. Motivo: $reason."
    $now = (Get-Date).ToString('s')
    if ($state.version -ne $actualBase) { $state.fallos = 0; $state.pausaAvisada = '' }
    $state.version = $actualBase
    $state.ultimoIntento = $now
    if ($needB) { $state.ultimoIntentoB = $now }

    $result = Invoke-Spicetify $SpicetifyExe @('backup', 'apply')
    $ok = ($result.Code -eq 0)

    if ($ok) {
        $state.fallos = 0
        $state.ultimoExito = (Get-Date).ToString('s')
        Write-Log ("OK: 'spicetify backup apply' termino bien. Salida: {0}" -f (Format-Output $result.Output))
        if ($needB -and -not $SinDeteccionDeParche) {
            Start-Sleep -Seconds 3
            if ((Test-ParcheAplicado $SpotifyDir) -eq $false) {
                $state.deteccionInutil = $true
                Write-Log 'Aviso: aplique bien pero no veo el parche en los archivos; desactivo la deteccion de parche (seguira reaplicando solo cuando Spotify cambie de version).'
            }
        }
        if ($needA) {
            # Si despues de aplicar bien la version guardada sigue sin coincidir, comparar versiones
            # no sirve en este equipo: se deja de usar para no reiniciar Spotify en bucle.
            $after = Get-VersionBase (Get-IniValue $ConfigIni 'Backup' 'version')
            if ($after -ne $actualBase) {
                $state.comparacionInutil = $true
                Write-Log ("Aviso: aplique bien pero la version guardada por Spicetify ({0}) sigue sin coincidir con la de Spotify ({1}); dejo de comparar versiones y solo vigilare el parche." -f $after, $actualBase)
            }
        }
        Set-Heartbeat ("reaplicado OK; Spotify {0}" -f $actual)
    } else {
        $state.fallos = [int]$state.fallos + 1
        Write-Log ("FALLO ({0} de {1}): 'spicetify backup apply' devolvio {2}. Salida: {3}" -f $state.fallos, $MaxFallos, $result.Code, (Format-Output $result.Output))
        # Dejar Spotify funcional (sin tema) en vez de roto
        $restore = Invoke-Spicetify $SpicetifyExe @('restore')
        Write-Log ("'spicetify restore' (para que Spotify abra normal) devolvio {0}. Salida: {1}" -f $restore.Code, (Format-Output $restore.Output))
        Set-Heartbeat ("fallo al reaplicar ({0}/{1})" -f $state.fallos, $MaxFallos)
    }
    Save-State $state
    exit $(if ($ok) { 0 } else { 1 })
}
catch {
    Write-Log ("Error inesperado: {0}" -f $_.Exception.Message)
    Set-Heartbeat 'error inesperado (ver autofix.log)'
    exit 1
}
finally {
    if ($hasMutex) { try { $mutex.ReleaseMutex() } catch { } }
    $mutex.Dispose()
}
