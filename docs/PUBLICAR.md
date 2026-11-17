# Publicar una versión

Cómo sacar una versión nueva para que se pueda descargar y para que **las copias ya instaladas avisen de ella**.

## Dónde va cada cosa

| Qué | Dónde | Para qué |
|---|---|---|
| El instalador `YefriPlayer-<versión>-Setup.exe` | Una **carpeta pública de Google Drive** (siempre la misma) | Es lo que descarga la gente. El botón del README apunta a esa carpeta |
| La *release* `v<versión>` (sin el `.exe`) | **GitHub → Releases** | Es lo que mira el programa para avisar de que hay versión nueva. Sus notas llevan el enlace de descarga y el SHA-256 |
| El código | El repositorio | `.gitignore` ya deja fuera `*.exe`, `dist-installer/` y las carpetas de compilación |

> [!TIP]
> **El instalador sí cabe en GitHub Releases.** El límite de 25 MB (subida por la web) y de 100 MB es para archivos **dentro del repositorio**. Los archivos adjuntos a una *release* pueden pesar hasta **2 GiB** cada uno y no cuentan para el tamaño del repositorio. Si adjuntas ahí el `Setup.exe` con su nombre exacto, el programa **se actualiza solo con un clic** (descarga, comprueba el SHA-256 y ejecuta el instalador). Con Google Drive solo puede avisar y abrir la página de la versión, desde donde la persona descarga a mano. Ver la [opción B](#opción-b-adjuntar-el-instalador-a-la-release).

## Cómo avisa el programa de las versiones nuevas

`updater.py` consulta una vez al día `https://api.github.com/repos/Yeflix/yefriplayer/releases/latest`. Solo lo hace el programa instalado (`.exe`), no el código fuente. Una versión cuenta solo si:

| Requisito | Por qué |
|---|---|
| El repositorio es **público** | La consulta va sin iniciar sesión |
| La *release* está **publicada** y es la más reciente (*Latest*): ni borrador ni *pre-release* | La API `releases/latest` ignora los borradores y las *pre-releases* |
| La etiqueta es **`v` + la versión de `version.py`**, por ejemplo `v1.5.6` | El programa le quita la `v` y compara números: `1.5.10` es más nueva que `1.5.9` |
| La versión es **mayor** que la instalada | Una igual o menor no se ofrece |

Si la *release* no trae el `Setup.exe` adjunto, al pulsar «Actualizar» se abre la página de la *release* en el navegador. Por eso **sus notas tienen que llevar el enlace de Drive**.

## Paso a paso (opción A: instalador en Google Drive)

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

Compila con Nuitka, ejecuta la autoprueba del `.exe` y, si todo va bien, deja **`dist-installer\YefriPlayer-<versión>-Setup.exe`** y muestra su **SHA-256**. Copia esa huella: va en las notas. Si la necesitas otra vez:

```powershell
Get-FileHash dist-installer\YefriPlayer-1.5.6-Setup.exe -Algorithm SHA256
```

Antes de publicarlo, pruébalo en Windows:
- encima de la versión anterior (debe cerrarla, conservar tus datos y abrirse con la versión nueva);
- en una instalación limpia (debe aparecer la bienvenida);
- **Inicio → YefriPlayer - herramientas → YefriPlayer - autoprueba** debe terminar en «todo ok».

### 4. Sube el instalador a Google Drive

**Solo la primera vez:**
1. En Google Drive crea una carpeta, por ejemplo `YefriPlayer`.
2. Clic derecho en la carpeta → **Compartir** → en «Acceso general» elige **Cualquier persona que tenga el vínculo** con rol **Lector** → **Copiar vínculo**.
3. Pega ese vínculo al final del `README.md`, en la línea `[descarga]: …` (es el único sitio donde aparece). Desde entonces el botón «Descargar» sirve para todas las versiones.

**En cada versión:**
1. Sube `YefriPlayer-<versión>-Setup.exe` a esa carpeta **sin renombrarlo**.
2. Opcional: mueve los instaladores viejos a una subcarpeta `anteriores` para que el más nuevo sea el único a la vista.
3. Saca el **vínculo del archivo** (clic derecho → Compartir → Copiar vínculo). Va en las notas de la *release*.

> [!NOTE]
> En archivos grandes Google Drive no puede analizar virus y muestra un aviso antes de descargar («Descargar de todas formas»). Es normal; el README ya lo explica. Si un archivo se descarga demasiadas veces en poco tiempo, Drive puede bloquear las descargas durante unas horas. Si pasa, GitHub Releases no tiene ese límite.

### 5. Sube el código y la etiqueta

```powershell
git add -A
git commit -m "YefriPlayer 1.5.6"
git tag v1.5.6
git push origin main --tags
```

### 6. Publica la *release* (sin el instalador)

1. Abre [`docs/notas/v1.5.6.md`](notas/v1.5.6.md) y sustituye los dos marcadores: el **vínculo del archivo en Drive** y el **SHA-256** del paso 3.
2. En el repositorio: **Releases → Draft a new release**.
   - **Choose a tag:** `v1.5.6`.
   - **Release title:** `YefriPlayer 1.5.6`.
   - **Descripción:** pega el texto de las notas.
   - Deja **sin marcar** «Set as a pre-release» y marcado «Set as the latest release».
   - **Publish release**.

O con la terminal ([GitHub CLI](https://cli.github.com)):

```powershell
gh release create v1.5.6 --title "YefriPlayer 1.5.6" --notes-file docs\notas\v1.5.6.md --latest
```

### 7. Comprueba que se publicó bien

- Abre el botón «Descargar» del README en una ventana de incógnito (sin tu sesión de Google): debe abrir la carpeta y dejar descargar el instalador.
- Abre `https://api.github.com/repos/Yeflix/yefriplayer/releases/latest`: debe mostrar `"tag_name": "v1.5.6"`.
- En un equipo con una versión anterior instalada: **clic derecho en el icono de la bandeja → Buscar actualizaciones…**. Debe ofrecer la versión nueva y, al pulsar «Actualizar», abrir la página de la *release* con el enlace de Drive.

## Opción B: adjuntar el instalador a la *release*

Igual que la opción A, salvo los pasos 4 y 6. En el paso 6 arrastra `dist-installer\YefriPlayer-1.5.6-Setup.exe` a **Attach binaries** **sin renombrarlo**, o desde la terminal:

```powershell
gh release create v1.5.6 "dist-installer\YefriPlayer-1.5.6-Setup.exe" `
  --title "YefriPlayer 1.5.6" --notes-file docs\notas\v1.5.6.md --latest
```

GitHub calcula el SHA-256 del archivo, y el programa lo comprueba antes de ejecutar el instalador. Con esto las copias instaladas se actualizan con un clic. Para que el README descargue desde ahí, cambia la línea `[descarga]: …` por `https://github.com/Yeflix/yefriplayer/releases/latest`. También puedes hacer las dos cosas: adjuntarlo a la *release* y además dejarlo en Drive.

## Errores comunes

| Síntoma | Causa |
|---|---|
| Las copias instaladas no ven la versión nueva | La *release* es borrador o *pre-release*, la etiqueta no coincide con `version.py`, o el repositorio es privado |
| «Actualizar» abre la página pero no hay forma de descargar | Faltó el enlace de Drive en las notas de la *release* |
| Drive pide permiso o dice «Necesitas acceso» | La carpeta o el archivo no está compartido como «Cualquier persona que tenga el vínculo» |
| Drive dice que se superó la cuota de descargas | Demasiadas descargas en poco tiempo. Espera unas horas o usa la opción B |
| Se ofrece una versión vieja | Otra *release* más antigua está marcada como *Latest* |

> [!IMPORTANT]
> No cambies el `AppId` de `installer/YefriPlayer.iss`: es lo que permite que el instalador nuevo actualice y desinstale las versiones anteriores.

## Más adelante: firmar el instalador

Sin firma digital, SmartScreen avisa la primera vez («Windows protegió su PC») hasta que el archivo gana reputación. Para quitar el aviso hace falta firmar el `.exe` y el instalador con un certificado de firma de código, por ejemplo con `signtool` y la directiva `SignTool` de Inno Setup. Es opcional y no afecta a las actualizaciones.
