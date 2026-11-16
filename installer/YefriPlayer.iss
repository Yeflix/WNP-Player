; =============================================================================
;  YefriPlayer - instalador para Windows (Inno Setup 6.3 o posterior)
;
;  No se compila a mano: usa  tools\construir_instalador.py  (o el doble clic en
;  Construir-Instalador.bat), que compila el programa, lee la versión de
;  version.py y llama a ISCC con estas definiciones:
;
;    /DAppVersion=1.4.0
;    /DSourceDir=<carpeta con YefriPlayer.exe>   (dist-nuitka\YefriPlayer o dist\YefriPlayer)
;    /DOutputDir=<carpeta de salida>              (dist-installer)
;
;  Qué deja registrado en el sistema:
;    - «Aplicaciones instaladas» / «Programas y características» con icono,
;      versión, editor, enlaces y desinstalador.
;    - Accesos directos en Inicio (y en el escritorio si se elige), con el mismo
;      AppUserModelID que usa el programa (main.APP_USER_MODEL_ID) para que la
;      barra de tareas agrupe bien la ventana con el acceso anclado.
;    - «App Paths»: Win+R → «YefriPlayer» abre el programa.
;    - Opcional: la tarea programada de Spicetify AutoFix (solo si Spicetify está).
;
;  Instalación por usuario (sin administrador) por defecto, en
;  %LOCALAPPDATA%\Programs\YefriPlayer; el asistente permite elegir «para todos
;  los usuarios» (Archivos de programa, pide administrador).
; =============================================================================

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist-nuitka\YefriPlayer"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist-installer"
#endif

#define AppName       "YefriPlayer"
#define AppExe        "YefriPlayer.exe"
#define AppPublisher  "YefriDev"
#define AppURL        "https://github.com/Yeflix/yefriplayer"
; Deben coincidir con el código (las pruebas lo comprueban: tests/test_instalador.py)
#define AppMutexName  "YefriPlayerAppMutex"
#define PipeName      "YefriPlayer-single-instance-v1"
#define AppUserModel  "YefriDev.YefriPlayer"
#define RunValueName  "YefriPlayer"

[Setup]
; El AppId identifica la instalación para actualizar/desinstalar: NO cambiarlo nunca.
AppId={{8C1B6C55-4E2A-4F7B-9B1E-6E3F2A9D7C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Copyright (C) 2026 {#AppPublisher}. GPL-3.0
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador de {#AppName} (controlador multimedia)

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes

; Por usuario por defecto; el asistente ofrece instalar para todos.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UsedUserAreasWarning=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\assets\yefriplayer.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
WizardStyle=modern
ShowLanguageDialog=auto
SetupLogging=yes

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Si quedara algún archivo del programa en uso, que Windows (Restart Manager)
; cierre lo que lo tenga abierto. El cierre normal de YefriPlayer se hace antes,
; en [Code] (orden «quit» por su canal de instancia única).
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
es.GroupSpicetify=Spotify con Spicetify:
en.GroupSpicetify=Spotify with Spicetify:
es.TaskAutoFix=Instalar Spicetify AutoFix (reaplica Spicetify sola cuando Spotify se actualiza)
en.TaskAutoFix=Install Spicetify AutoFix (re-applies Spicetify when Spotify updates)
es.StatusAutoFix=Configurando Spicetify AutoFix (puede tardar hasta un minuto)...
en.StatusAutoFix=Setting up Spicetify AutoFix (may take up to a minute)...
es.AppRunning=YefriPlayer está abierto. Se cerrará para poder continuar.%n%n¿Continuar?
en.AppRunning=YefriPlayer is running. It will be closed to continue.%n%nContinue?
es.AppStillRunning=No se pudo cerrar YefriPlayer. Ciérralo desde el icono de la bandeja (Salir) y vuelve a intentarlo.
en.AppStillRunning=YefriPlayer could not be closed. Quit it from its tray icon and try again.
es.DeleteUserData=¿Borrar también tu configuración, historial y estadísticas de YefriPlayer?%n%n%1%n%nElige «No» si vas a volver a instalarlo.
en.DeleteUserData=Also delete your YefriPlayer settings, history and statistics?%n%n%1%n%nChoose "No" if you plan to reinstall.
es.DebugShortcut=YefriPlayer (modo depuración)
en.DebugShortcut=YefriPlayer (debug mode)
es.AutoFixStatus=Spicetify AutoFix - estado
en.AutoFixStatus=Spicetify AutoFix - status
es.AutoFixInstall=Spicetify AutoFix - instalar o reparar
en.AutoFixInstall=Spicetify AutoFix - install or repair
es.AppComment=Controlador multimedia: muestra y controla lo que suena en el navegador y en las apps de escritorio
en.AppComment=Media controller: shows and controls what is playing in your browser and desktop apps
es.AutotestShortcut=YefriPlayer - autoprueba
en.AutotestShortcut=YefriPlayer - self-test

[Messages]
es.WelcomeLabel2=Se instalará [name/ver] en tu equipo.%n%nYefriPlayer es un CONTROLADOR MULTIMEDIA, no un reproductor: no reproduce audio, sino que muestra y controla lo que ya suena.%n%n• Navegador (con la extensión WebNowPlaying): YouTube, YouTube Music, Spotify Web, SoundCloud, Deezer, Apple Music, TIDAL y más.%n• Escritorio: Spotify, Apple Music, TIDAL, Deezer, el Reproductor multimedia de Windows y otras apps de los controles multimedia de Windows.%n%nSe recomienda cerrar las demás aplicaciones antes de continuar.
en.WelcomeLabel2=This will install [name/ver] on your computer.%n%nYefriPlayer is a MEDIA CONTROLLER, not a player: it does not play audio, it shows and controls what is already playing.%n%n• Browser (with the WebNowPlaying extension): YouTube, YouTube Music, Spotify Web, SoundCloud, Deezer, Apple Music, TIDAL and more.%n• Desktop: Spotify, Apple Music, TIDAL, Deezer, Windows Media Player and other apps in the Windows media controls.%n%nIt is recommended that you close all other applications before continuing.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autofix"; Description: "{cm:TaskAutoFix}"; GroupDescription: "{cm:GroupSpicetify}"; Check: SpicetifyPresent

[InstallDelete]
; Restos de una versión empaquetada con PyInstaller si ahora se instala la de Nuitka.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\depurar.flag"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "depurar.flag,autotest.txt,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\SpicetifyAutoFix\*"; DestDir: "{app}\SpicetifyAutoFix"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "{cm:AppComment}"; AppUserModelID: "{#AppUserModel}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "{cm:AppComment}"; AppUserModelID: "{#AppUserModel}"; Tasks: desktopicon
Name: "{autoprograms}\{#AppName} - herramientas\{cm:AutotestShortcut}"; Filename: "{app}\{#AppExe}"; Parameters: "--autotest --mostrar"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName} - herramientas\{cm:DebugShortcut}"; Filename: "{app}\{#AppExe}"; Parameters: "--log"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName} - herramientas\{cm:AutoFixStatus}"; Filename: "{app}\SpicetifyAutoFix\Estado.bat"; WorkingDir: "{app}\SpicetifyAutoFix"
Name: "{autoprograms}\{#AppName} - herramientas\{cm:AutoFixInstall}"; Filename: "{app}\SpicetifyAutoFix\Instalar.bat"; WorkingDir: "{app}\SpicetifyAutoFix"
Name: "{autoprograms}\{#AppName} - herramientas\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"

[Registry]
; Win+R → «YefriPlayer». HKA = HKLM si se instala para todos, HKCU si es por usuario.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExe}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"

[Run]
; Spicetify se niega a correr como administrador y la tarea debe quedar para TU
; usuario: por eso runasoriginaluser aunque se instale «para todos».
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\SpicetifyAutoFix\Instalar-AutoFix.ps1"""; WorkingDir: "{app}\SpicetifyAutoFix"; StatusMsg: "{cm:StatusAutoFix}"; Tasks: autofix; Flags: runhidden waituntilterminated runasoriginaluser
; Instalación NUEVA: abre con la bienvenida. Actualización: abre normal (la
; bienvenida solo sale si cambió su contenido, ver onboarding.WELCOME_REVISION).
Filename: "{app}\{#AppExe}"; Parameters: "--bienvenida"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: not WasInstalledBefore
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: WasInstalledBefore

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\SpicetifyAutoFix\Instalar-AutoFix.ps1"" -Desinstalar"; WorkingDir: "{app}\SpicetifyAutoFix"; Tasks: autofix; Flags: runhidden waituntilterminated; RunOnceId: "QuitarSpicetifyAutoFix"

[UninstallDelete]
Type: files; Name: "{app}\depurar.flag"
Type: files; Name: "{app}\autotest.txt"

[Code]
const
  RUN_KEY = 'Software\Microsoft\Windows\CurrentVersion\Run';
  UNINST_KEY = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8C1B6C55-4E2A-4F7B-9B1E-6E3F2A9D7C41}_is1';

var
  InstalledBefore: Boolean;

{ Se mira al arrancar (antes de instalar, después ya existiría siempre). }
function InitializeSetup(): Boolean;
begin
  InstalledBefore := RegKeyExists(HKCU, UNINST_KEY) or RegKeyExists(HKLM, UNINST_KEY);
  Result := True;
end;

function WasInstalledBefore(): Boolean;
begin
  Result := InstalledBefore;
end;

function IsSilent(): Boolean;
begin
  if IsUninstaller() then
    Result := UninstallSilent()
  else
    Result := WizardSilent();
end;

{ ¿Está Spicetify en esta cuenta? Solo entonces se ofrece AutoFix. }
function SpicetifyPresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\spicetify\spicetify.exe'))
         or FileExists(ExpandConstant('{userappdata}\spicetify\config-xpui.ini'));
end;

{ Cualquier copia en marcha, también una antigua sacada de un .zip (que no
  crea el mutex). El mutex lo crea YefriPlayer 1.4+ (single_instance.py). }
function IsAppRunning(): Boolean;
var
  Locator, Service, Procs: Variant;
begin
  Result := CheckForMutexes('{#AppMutexName},Global\{#AppMutexName}');
  if Result then
    Exit;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name=''{#AppExe}''');
    Result := (Procs.Count > 0);
  except
    Result := False;
  end;
end;

function WaitForAppExit(TimeoutMs: Integer): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  while IsAppRunning() and (Waited < TimeoutMs) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  Result := not IsAppRunning();
end;

{ Cierra YefriPlayer: primero de forma ordenada (orden «quit» por su canal de
  instancia única: guarda la configuración y para el servidor), y si es una
  versión antigua que no la entiende o no responde, a la fuerza. }
function CloseRunningApp(): Boolean;
var
  Code: Integer;
begin
  Result := True;
  if not IsAppRunning() then
    Exit;
  if not IsSilent() then
    if MsgBox(CustomMessage('AppRunning'), mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := False;
      Exit;
    end;
  Exec(ExpandConstant('{cmd}'), '/C echo quit>\\.\pipe\{#PipeName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if WaitForAppExit(8000) then
    Exit;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := WaitForAppExit(5000);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CloseRunningApp() then
    Result := CustomMessage('AppStillRunning');
end;

function InitializeUninstall(): Boolean;
begin
  Result := CloseRunningApp();
  if not Result then
    MsgBox(CustomMessage('AppStillRunning'), mbError, MB_OK);
end;

{ «Iniciar con Windows» lo gestiona el propio programa (autostart.py, clave
  HKCU\...\Run). Al desinstalar se quita, solo si apunta a ESTA instalación. }
procedure RemoveAutostartEntry();
var
  Cmd: String;
begin
  if RegQueryStringValue(HKCU, RUN_KEY, '{#RunValueName}', Cmd) then
    if Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Cmd)) > 0 then
      RegDeleteValue(HKCU, RUN_KEY, '{#RunValueName}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    RemoveAutostartEntry();
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#AppName}');
    if DirExists(DataDir) and not UninstallSilent() then
      if MsgBox(FmtMessage(CustomMessage('DeleteUserData'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
