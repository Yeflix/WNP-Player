# Spicetify AutoFix

Reaplica Spicetify solo cuando Spotify se actualiza, sin que tengas que abrir
una terminal y escribir `spicetify backup apply`.

## Instalar (1 minuto)

1. Descomprime esta carpeta donde quieras.
2. Doble clic en **`Instalar.bat`** (con tu usuario normal, **no** "como administrador").
3. Debe terminar con `Listo: la tarea funciona.` y la línea
   `Se lanza sin ventana (AutoFixSilencioso.exe).`

Si ya lo tenías instalado, **vuelve a ejecutar `Instalar.bat`**: reemplaza la
tarea por la versión sin ventana. `Estado.bat` te dice con qué método se lanza.

Eso crea la tarea programada **Spicetify-AutoFix** de tu usuario. Al iniciar
sesión deja un **vigilante** sin ventana que reacciona cuando **Spotify se abre o
se cierra**; ya no revisa cada pocos minutos. Cada comprobación casi siempre
termina sin hacer nada y, si los archivos de Spotify no cambiaron desde la vez
anterior, ni siquiera los vuelve a leer.

## Cuándo actúa el vigilante

| Evento | Qué hace |
|---|---|
| **Inicias sesión** | Una comprobación (normalmente Spotify aún no está abierto o está en la bandeja). |
| **Spotify se cierra** | El mejor momento: no hay nada que reiniciar, se aplica **en silencio** y la próxima vez que lo abras ya está listo. Segundo intento a los 2 min por si el instalador de Spotify seguía terminando. |
| **Spotify se abre con ventana** (lo abriste tú) | Comprueba a los 20 s, 110 s y 6 min (por si se estaba actualizando). Si falta el parche, lo aplica: Spotify se reinicia una vez, justo después de abrirlo. |
| **Spotify se abre en la bandeja** (arranque de Windows) | **No lo reinicia delante de ti** (su ventana saltaría al frente). Espera a que lo cierres. |

Sigue existiendo una repetición cada 30 min en la tarea, pero solo es un
supervisor: si el vigilante se cayó lo vuelve a levantar; si está vivo, no hace nada.

## Cómo se mantiene silenciosa

Lanzar `powershell.exe` desde el Programador de tareas crea una consola;
`-WindowStyle Hidden` la oculta *después* de crearla (parpadea y te quita el
foco) y con Windows Terminal como terminal predeterminada puede abrir una
ventana. Por eso el instalador prueba, en este orden, y se queda con el primero
que funcione:

1. **`AutoFixSilencioso.exe`** (se compila en tu equipo desde `Lanzador.cs`, que
   puedes leer entero): no tiene consola, arranca PowerShell con
   `CREATE_NO_WINDOW`. Nunca hay ventana, parpadeo ni robo de foco. Es el único
   método con vigilante; consume prácticamente nada (mira cada 4 s si existe el
   proceso Spotify).
2. `conhost.exe --headless powershell.exe` (sondeo cada `-CadaMinutos`).
3. `powershell.exe -WindowStyle Hidden` (sondeo; el que puede parpadear).

`-SinLanzador` salta el paso 1 (y con él el vigilante). Si tu antivirus bloquea o borra el `.exe`
(un lanzador que arranca PowerShell oculto se parece a lo que hace el malware),
el instalador cae solo al método 2.

Para que **nunca** reinicie Spotify (ni siquiera cuando lo abres tú) y aplique
solo cuando esté cerrado, desde una terminal en esta carpeta:

```
powershell -ExecutionPolicy Bypass -File .\Instalar-AutoFix.ps1 -EsperarSpotifyCerrado
```

`-CadaMinutos` (5 a 120) solo cuenta si el vigilante no se puede usar y se cae al
método de sondeo (ver abajo).

## Qué hace exactamente

Cada revisión mira dos cosas y, solo si alguna falla, ejecuta
`spicetify backup apply`:

| Caso | Cómo lo detecta |
|---|---|
| **A. Spotify se actualizó** | La versión de `Spotify.exe` no coincide con la guardada en la sección `[Backup]` de `config-xpui.ini`. |
| **B. Spotify perdió el parche** | La versión coincide, pero los `.js` de Spotify ya no contienen "Spicetify". |

- `backup apply` **ya incluye** el `apply`; no hace falta correr `spicetify apply` después.
- Nunca corre `spicetify apply` a secas tras una actualización: la guía oficial de Spicetify advierte que puede dejar Spotify roto.
- **Esto es lo único que puede sacarte de lo que estás haciendo:** al aplicar,
  Spotify se reinicia y su ventana aparece al frente. Solo ocurre cuando de
  verdad hace falta reaplicar (tras una actualización de Spotify), no en cada
  revisión. Para evitarlo del todo usa `-EsperarSpotifyCerrado`; ojo: si Spotify
  está configurado para minimizarse a la bandeja al cerrar, el proceso sigue
  vivo y no reaplicará hasta que lo cierres desde la bandeja (Salir).
- **Spotify se reinicia** al aplicar (así funciona Spicetify). Como una actualización ya reinicia Spotify, normalmente lo notas poco; con `-EsperarSpotifyCerrado` solo actúa cuando Spotify está cerrado.
- Tu tema Switch y tu configuración no se tocan: viven en `config-xpui.ini`. Cuando Spotify vuelve a abrirse, `theme.js` se reconecta solo con el reproductor.

## Protecciones (para que no se descontrole)

- Espera a que `Spotify.exe` lleve 90 s sin cambiar y a que no haya un instalador de Spotify en marcha.
- Una sola instancia a la vez, y 30 min de pausa entre intentos.
- Si `backup apply` falla, corre `spicetify restore` para que Spotify abra normal (sin tema) en lugar de quedar en blanco.
- Tras 3 fallos seguidos con la misma versión de Spotify se **pausa** (suele significar que tu Spicetify aún no soporta esa versión: ejecuta `spicetify upgrade`). Mientras tanto reintenta una vez cada 6 horas, por si ya salió la versión nueva.
- Si no encuentra Spicetify, o Spicetify nunca se aplicó en este equipo, no hace nada.
- Si la detección B se equivoca (aplica bien y aun así no ve el parche), se desactiva sola; lo mismo con la comparación de versiones (A).

## Ver qué pasó

- **`Estado.bat`**: estado de la tarea, última comprobación y últimas líneas del registro.
- **`Comprobar-ahora.bat`**: dice qué haría ahora mismo, sin cambiar nada.
- Archivos en `%LOCALAPPDATA%\SpicetifyAutoFix`: `autofix.log` (solo eventos importantes), `ultima-comprobacion.txt` y `estado.json`.

Si el registro está vacío es buena señal: no hizo falta reaplicar nada.

## Desinstalar

Doble clic en **`Desinstalar.bat`** (quita la tarea y borra `%LOCALAPPDATA%\SpicetifyAutoFix`).

## Límites

- Solo Spotify de escritorio (el de spotify.com), no el de Microsoft Store (Spicetify tampoco lo soporta).
- Si Spicetify aún no soporta una versión nueva de Spotify, ningún script puede arreglarlo: el AutoFix lo registra y espera.
- Spicetify no debe correr como administrador; por eso la tarea usa privilegios normales.

## Alternativa oficial

Spicetify trae `spicetify auto` ("hace backup si hace falta, aplica y abre Spotify"). Sirve si siempre abres Spotify desde un acceso directo que lo llame; este AutoFix no depende de eso y también funciona cuando Spotify se abre solo con Windows.
