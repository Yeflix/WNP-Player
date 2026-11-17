# Publicar una versión en GitHub

Cómo sacar una versión nueva para que se pueda descargar desde *Releases* y para que **las copias ya instaladas se actualicen solas**.

## Cómo encuentra el programa las versiones nuevas

`updater.py` consulta una vez al día `https://api.github.com/repos/Yeflix/yefriplayer/releases/latest`. Solo lo hace el programa instalado (`.exe`), no el código fuente. Para que una versión cuente, tienen que cumplirse **todas** estas condiciones:

| Requisito | Por qué |
|---|---|
| El repositorio es **público** | La consulta va sin iniciar sesión |
| La *release* está **publicada** y es la más reciente (*Latest*): ni borrador ni *pre-release* | La API `releases/latest` ignora los borradores y las *pre-releases*, y el programa las descarta también |
| La etiqueta es **`v` + la versión de `version.py`**, por ejemplo `v1.5.6` | El programa le quita la `v` y compara números: `1.5.10` es más nueva que `1.5.9` |
| La versión es **mayor** que la instalada | Una igual o menor no se ofrece |
| Lleva adjunto **`YefriPlayer-<versión>-Setup.exe`** con ese nombre exacto | Es el archivo que descarga. Con otro nombre, el aviso solo abre la página de la versión |

GitHub calcula el **SHA-256** de cada archivo adjunto y el programa lo comprueba antes de ejecutar el instalador: si no coincide, no lo ejecuta. No hace falta subir el hash aparte.

## Paso a paso

### 1. Prepara la versión

1. Sube el número en **`version.py`** (`APP_VERSION`). Es la única fuente de la versión: la leen el `.exe`, el instalador y el diálogo «Acerca de».
2. Añade la entrada al principio de **`CHANGELOG.md`**.
3. Si cambió algo visible, actualiza las capturas de `docs/img/`.

### 2. Comprueba que todo está bien

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
Get-ChildItem tests\test_*.py | ForEach-Object { python $_.FullName; if ($LASTEXITCODE) { "FALLA $($_.Name)" } }
python main.py --autotest
```

### 3. Crea el instalador (en Windows)

```powershell
python tools\construir_instalador.py
# o doble clic en Construir-Instalador.bat
```

Compila con Nuitka, ejecuta la autoprueba del `.exe` y, si todo va bien, deja **`dist-installer\YefriPlayer-<versión>-Setup.exe`** y muestra su SHA-256. Si la compilación o la autoprueba fallan, no crea el instalador.

Antes de publicarlo, pruébalo en Windows:
- encima de la versión anterior (debe cerrarla, conservar tus datos y abrirse con la versión nueva);
- en una instalación limpia (debe aparecer la bienvenida);
- **Inicio → YefriPlayer - herramientas → YefriPlayer - autoprueba** debe terminar en «todo ok».

### 4. Sube el código y la etiqueta

```powershell
git add -A
git commit -m "YefriPlayer 1.5.6"
git tag v1.5.6
git push origin main --tags
```

### 5. Publica la *release*

**Desde la web:** en el repositorio, ve a **Releases → Draft a new release**:

1. **Choose a tag:** `v1.5.6`.
2. **Release title:** `YefriPlayer 1.5.6`.
3. **Descripción:** pega el texto de [`docs/notas/v1.5.6.md`](notas/v1.5.6.md) (o la entrada del CHANGELOG, contada para usuarios).
4. **Attach binaries:** arrastra `dist-installer\YefriPlayer-1.5.6-Setup.exe` **sin renombrarlo**.
5. Deja **sin marcar** «Set as a pre-release» y marcado «Set as the latest release».
6. **Publish release**.

**O con la terminal** ([GitHub CLI](https://cli.github.com)):

```powershell
gh release create v1.5.6 "dist-installer\YefriPlayer-1.5.6-Setup.exe" `
  --title "YefriPlayer 1.5.6" --notes-file docs\notas\v1.5.6.md --latest
```

### 6. Comprueba que se publicó bien

- Abre `https://api.github.com/repos/Yeflix/yefriplayer/releases/latest`. Debe mostrar `"tag_name": "v1.5.6"` y, en `assets`, el `Setup.exe` con su `"digest": "sha256:…"`.
- En un equipo con una versión anterior instalada: **clic derecho en el icono de la bandeja → Buscar actualizaciones…**. Debe ofrecer la nueva versión, descargarla e instalarla.
- El botón de descarga del README apunta a `releases/latest`, así que siempre lleva a la versión más reciente sin tocarlo.

## Errores comunes

| Síntoma | Causa |
|---|---|
| Las copias instaladas no ven la versión nueva | La *release* es borrador o *pre-release*, la etiqueta no coincide con `version.py`, o el repositorio es privado |
| El aviso solo abre la página web, no actualiza | El instalador no está adjunto o se renombró |
| «La descarga no coincide» | El archivo se reemplazó después de publicar. Sube de nuevo el instalador correcto (GitHub recalcula su SHA-256) |
| Se ofrece una versión vieja | Otra *release* más antigua está marcada como *Latest* |

> [!IMPORTANT]
> No cambies el `AppId` de `installer/YefriPlayer.iss`: es lo que permite que el instalador nuevo actualice y desinstale las versiones anteriores.

## Más adelante: firmar el instalador

Sin firma digital, SmartScreen avisa la primera vez («Windows protegió su PC») hasta que el archivo gana reputación. Para quitar el aviso hace falta firmar el `.exe` y el instalador con un certificado de firma de código, por ejemplo con `signtool` y la directiva `SignTool` de Inno Setup. Es opcional y no afecta a las actualizaciones.
