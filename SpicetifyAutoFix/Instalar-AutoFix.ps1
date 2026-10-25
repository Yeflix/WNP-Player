<#
.SYNOPSIS
  Instala (o quita) la tarea programada que vigila Spotify y reaplica Spicetify.

.DESCRIPTION
  - Copia Spicetify-AutoFix.ps1 a %LOCALAPPDATA%\SpicetifyAutoFix (asi puedes borrar
    esta carpeta despues).
  - Crea la tarea "Spicetify-AutoFix" de TU usuario: al iniciar sesion (con 1 minuto
    de espera). NO usa privilegios de administrador a proposito: Spicetify se
    niega a funcionar como administrador y Spotify quedaria en negro.
  - Con el lanzador (metodo 1) la tarea deja un vigilante residente que reacciona
    cuando Spotify se ABRE o se CIERRA (ver Lanzador.cs), en vez de revisar cada
    N minutos. La repeticion cada 30 min de la tarea solo sirve de supervisor:
    si el vigilante murio lo vuelve a levantar; si esta vivo no hace nada.
    Con los metodos 2 y 3 (sin lanzador) se mantiene el sondeo cada N minutos.
  - Corre SIN VENTANA. Orden de preferencia (usa el primero que funcione):
      1. Lanzador propio (AutoFixSilencioso.exe, se compila aqui desde Lanzador.cs):
         no tiene consola, asi que no hay ventana, ni parpadeo, ni robo de foco.
         Es el unico que vigila Spotify en vez de sondear.
      2. conhost.exe --headless powershell.exe
      3. powershell.exe -WindowStyle Hidden (la consola se crea y se oculta
         despues: puede parpadear y quitarte el foco)
    Comprueba que la tarea realmente funciona.

.PARAMETER CadaMinutos
  Solo para los metodos sin lanzador (2 y 3): cada cuanto revisa (5 a 120, por
  defecto 10). Con el vigilante no se usa.
.PARAMETER Desinstalar
  Quita la tarea y borra %LOCALAPPDATA%\SpicetifyAutoFix (incluido el registro).
.PARAMETER Estado
  Muestra el estado de la tarea y las ultimas lineas del registro.
.PARAMETER SinLanzador
  No compila ni usa AutoFixSilencioso.exe (pasa a conhost --headless).
.PARAMETER SinConhost
  Usa PowerShell oculto en vez de conhost --headless.
.PARAMETER EsperarSpotifyCerrado
  La tarea no reaplica mientras Spotify este abierto (Spicetify lo reinicia al aplicar).
#>
[CmdletBinding()]
param(
    [int]$CadaMinutos = 10,
    [switch]$Desinstalar,
    [switch]$Estado,
    [switch]$SinConhost,
    [switch]$SinLanzador,
    [switch]$EsperarSpotifyCerrado
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Spicetify-AutoFix'
$DatosDir = Join-Path $env:LOCALAPPDATA 'SpicetifyAutoFix'
$Destino = Join-Path $DatosDir 'Spicetify-AutoFix.ps1'
$Latido = Join-Path $DatosDir 'ultima-comprobacion.txt'
$LogPath = Join-Path $DatosDir 'autofix.log'
$LanzadorExe = Join-Path $DatosDir 'AutoFixSilencioso.exe'

function Get-Tarea { Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }

# Detiene el vigilante residente (si esta corriendo): hace falta antes de
# reemplazar su .exe, de cambiar de metodo o de borrar la carpeta.
function Stop-Vigilante {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-Process -Name 'AutoFixSilencioso' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

# Compila Lanzador.cs -> AutoFixSilencioso.exe (aplicacion de Windows, sin consola).
# Devuelve $true si el .exe queda listo. Cualquier fallo (sin compilador, antivirus,
# archivo en uso) devuelve $false y el instalador cae al siguiente metodo.
function Install-Lanzador {
    $fuente = Join-Path $PSScriptRoot 'Lanzador.cs'
    if (-not (Test-Path -LiteralPath $fuente)) { return $false }
    $tmp = Join-Path $DatosDir 'AutoFixSilencioso.nuevo.exe'
    try {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        $codigo = [System.IO.File]::ReadAllText($fuente)
        Add-Type -TypeDefinition $codigo -OutputAssembly $tmp -OutputType WindowsApplication -ErrorAction Stop
        if (-not (Test-Path -LiteralPath $tmp)) { return $false }
        Stop-Vigilante   # el .exe actual no se puede reemplazar mientras corre
        Move-Item -LiteralPath $tmp -Destination $LanzadorExe -Force -ErrorAction Stop
        return $true
    } catch {
        Write-Host ('  (no pude preparar el lanzador sin ventana: {0})' -f $_.Exception.Message) -ForegroundColor Yellow
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        return $false
    }
}

# $Metodo: 'lanzador' | 'conhost' | 'powershell'
function Register-Tarea([string]$Metodo) {
    $psArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $Destino
    if ($EsperarSpotifyCerrado) { $psArgs += ' -EsperarSpotifyCerrado' }
    $vigilante = ($Metodo -eq 'lanzador')
    switch ($Metodo) {
        'lanzador' {
            $argsVig = '--vigilar'
            if ($EsperarSpotifyCerrado) { $argsVig += ' -EsperarSpotifyCerrado' }
            $action = New-ScheduledTaskAction -Execute $LanzadorExe -Argument $argsVig
        }
        'conhost' { $action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument ('--headless powershell.exe ' + $psArgs) }
        default   { $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-WindowStyle Hidden ' + $psArgs) }
    }

    # Vigilante: la repeticion (30 min) es solo un supervisor; con IgnoreNew no lanza
    # una segunda copia si ya esta corriendo. Sin lanzador: sondeo cada $CadaMinutos.
    $intervalo = if ($vigilante) { 30 } else { $CadaMinutos }
    $user = '{0}\{1}' -f $env:USERDOMAIN, $env:USERNAME
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes $intervalo) -RepetitionDuration (New-TimeSpan -Days 3650)
    $logon.Repetition = $repeat.Repetition
    $logon.Delay = 'PT1M'

    if ($vigilante) {
        # Residente: sin limite de tiempo, y que Windows lo relance si se cae.
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    } else {
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    }
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $logon -Settings $settings `
        -Principal $principal -Force `
        -Description 'Reaplica Spicetify (spicetify backup apply) cuando Spotify se actualiza o pierde el parche. Con AutoFixSilencioso.exe vigila la apertura/cierre de Spotify.' | Out-Null
}

function Test-Tarea {
    # Lanza la tarea y espera a que el script deje su "latido" (se sobrescribe en cada corrida)
    $t0 = Get-Date
    Start-ScheduledTask -TaskName $TaskName
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if ((Test-Path -LiteralPath $Latido) -and ((Get-Item -LiteralPath $Latido).LastWriteTime -ge $t0)) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------- estado
if ($Estado) {
    $task = Get-Tarea
    if (-not $task) { Write-Host 'La tarea Spicetify-AutoFix NO esta instalada.' -ForegroundColor Yellow; exit 0 }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host ('Tarea: {0}  (estado: {1})' -f $TaskName, $task.State)
    Write-Host ('Ultima ejecucion: {0}   Resultado: {1}' -f $info.LastRunTime, $info.LastTaskResult)
    Write-Host ('Proxima ejecucion: {0}' -f $info.NextRunTime)
    $accion = @($task.Actions)[0]
    $metodo = if ($accion.Execute -like '*AutoFixSilencioso.exe') { 'vigilante sin ventana (reacciona al abrir/cerrar Spotify)' }
              elseif ($accion.Execute -like '*conhost.exe') { 'conhost --headless' }
              else { 'PowerShell oculto (puede parpadear una ventana)' }
    Write-Host ('Se lanza con: {0}' -f $metodo)
    if ($accion.Execute -like '*AutoFixSilencioso.exe') {
        $vig = @(Get-Process -Name 'AutoFixSilencioso' -ErrorAction SilentlyContinue)
        if ($vig.Count -gt 0) { Write-Host ('Vigilante: ACTIVO (pid {0})' -f $vig[0].Id) }
        else { Write-Host 'Vigilante: no esta corriendo ahora (la tarea lo relanza sola en menos de 30 min, o ejecuta Instalar.bat).' -ForegroundColor Yellow }
    }
    if (Test-Path -LiteralPath $Latido) { Write-Host ('Ultima comprobacion: ' + (Get-Content -LiteralPath $Latido -Raw).Trim()) }
    if (Test-Path -LiteralPath $LogPath) {
        Write-Host "`nUltimas lineas del registro ($LogPath):"
        Get-Content -LiteralPath $LogPath -Tail 15 -Encoding UTF8 | ForEach-Object { Write-Host ('  ' + $_) }
    } else {
        Write-Host "`n(Todavia no hay eventos en el registro: es buena senal, significa que no hizo falta reaplicar nada.)"
    }
    exit 0
}

# ----------------------------------------------------------------- desinstalar
if ($Desinstalar) {
    Stop-Vigilante
    if (Get-Tarea) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Write-Host 'Tarea eliminada.' -ForegroundColor Green }
    else { Write-Host 'La tarea no estaba instalada.' }
    if (Test-Path -LiteralPath $DatosDir) { Remove-Item -LiteralPath $DatosDir -Recurse -Force; Write-Host "Borrado $DatosDir" }
    exit 0
}

# -------------------------------------------------------------------- instalar
if ($CadaMinutos -lt 5 -or $CadaMinutos -gt 120) { Write-Host 'CadaMinutos debe estar entre 5 y 120.' -ForegroundColor Red; exit 1 }

$origen = Join-Path $PSScriptRoot 'Spicetify-AutoFix.ps1'
if (-not (Test-Path -LiteralPath $origen)) { Write-Host "No encuentro Spicetify-AutoFix.ps1 junto a este instalador ($origen)." -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $DatosDir | Out-Null
Copy-Item -LiteralPath $origen -Destination $Destino -Force

$spicetify = Get-Command spicetify -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $spicetify -and -not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'spicetify\spicetify.exe'))) {
    Write-Host 'Aviso: no encuentro spicetify. La tarea se instala igual, pero no hara nada hasta que Spicetify este instalado.' -ForegroundColor Yellow
}

$metodos = @()
if (-not $SinLanzador -and (Install-Lanzador)) { $metodos += 'lanzador' }
if (-not $SinConhost) { $metodos += 'conhost' }
$metodos += 'powershell'

$ok = $false
$usado = ''
foreach ($m in $metodos) {
    Stop-Vigilante
    Register-Tarea $m
    if ($m -eq 'lanzador') { Write-Host 'Tarea creada con el vigilante sin ventana (reacciona al abrir/cerrar Spotify). Probandola...' }
    else { Write-Host ('Tarea creada con metodo "{0}" (revisa cada {1} minutos y al iniciar sesion). Probandola...' -f $m, $CadaMinutos) }
    if (Test-Tarea) { $ok = $true; $usado = $m; break }
    Write-Host ('Con "{0}" no respondio; pruebo el siguiente metodo...' -f $m) -ForegroundColor Yellow
}

if ($ok) {
    Write-Host 'Listo: la tarea funciona.' -ForegroundColor Green
    if ($usado -eq 'lanzador') { Write-Host '  Vigilante sin ventana activo (AutoFixSilencioso.exe): actua al abrir/cerrar Spotify, no cada N minutos.' }
    else { Write-Host ('  Se lanza con "{0}": si ves parpadear una ventana, vuelve a instalar sin -SinLanzador.' -f $usado) -ForegroundColor Yellow }
    Write-Host ('  Ultima comprobacion: ' + (Get-Content -LiteralPath $Latido -Raw).Trim())
    Write-Host "  Para ver el estado en cualquier momento: Estado.bat   |   Para quitarla: Desinstalar.bat"
} else {
    Write-Host 'La tarea quedo creada pero no pude confirmar que se ejecute. Abre el Programador de tareas, busca "Spicetify-AutoFix" y mira el "Resultado de la ultima ejecucion".' -ForegroundColor Red
    exit 1
}
