# WNP Player — Documentación del proyecto

> Reproductor de música de escritorio (Windows) hecho con **PyQt6**, que muestra y controla lo que suena en tu navegador (YouTube, Spotify Web, SoundCloud…) y en las apps de escritorio de Windows (Spotify, etc.), usando la librería **pywnp** y la extensión **WebNowPlaying**.
>
> Estado documentado: versión 1.0 (octubre de 2026). Todo lo que aquí se describe sale de leer el código; las partes que dependen de Windows y de servicios externos reales (Spotify, YouTube, Last.fm) no se han podido ejecutar fuera de pruebas con servidores simulados, y se indica donde corresponde.

---

## Índice

1. [Qué es y qué hace](#1-qué-es-y-qué-hace)
2. [Requisitos, instalación y ejecución](#2-requisitos-instalación-y-ejecución)
3. [Arquitectura general](#3-arquitectura-general)
4. [Estructura de archivos](#4-estructura-de-archivos)
5. [Arranque de la aplicación](#5-arranque-de-la-aplicación)
6. [Backend y comunicación con los reproductores](#6-backend-y-comunicación-con-los-reproductores)
7. [El parche de pywnp (12 errores corregidos)](#7-el-parche-de-pywnp-12-errores-corregidos)
8. [El controlador (`AppController`)](#8-el-controlador-appcontroller)
9. [Interfaz gráfica](#9-interfaz-gráfica)
10. [Funciones](#10-funciones)
11. [Configuración y archivos de datos](#11-configuración-y-archivos-de-datos)
12. [Spicetify AutoFix](#12-spicetify-autofix)
13. [Herramientas auxiliares](#13-herramientas-auxiliares)
14. [Pruebas](#14-pruebas)
15. [Empaquetado](#15-empaquetado)
16. [Seguridad y privacidad](#16-seguridad-y-privacidad)
17. [Limitaciones conocidas](#17-limitaciones-conocidas)
18. [Solución de problemas](#18-solución-de-problemas)
19. [Historial de revisiones](#19-historial-de-revisiones)

---

## 1. Qué es y qué hace

WNP Player no reproduce audio por sí mismo: **lee el estado** de lo que ya suena en otro sitio (título, artista, carátula, posición, volumen…) y **le manda órdenes** (play/pausa, siguiente, anterior, buscar posición, aleatorio, repetir, volumen).

Fuentes que puede controlar:

| Fuente | Cómo llega la información |
|---|---|
| Sitios web (YouTube, YouTube Music, Spotify Web, SoundCloud, Deezer…) | La extensión del navegador **WebNowPlaying** se conecta por WebSocket al servidor local de `pywnp` |
| Apps de escritorio de Windows (Spotify, etc.) | Las sesiones multimedia nativas de Windows (SMTC), leídas con `winsdk` a través de `pywnp` |

### Resumen de funciones

**Reproducción**
- Tres modos de ventana: **completa**, **compacta** (barra flotante con vinilo) y **panel lateral** (pestaña anclada a un borde de la pantalla, con estilo *tarjeta* o *compacto*).
- Carátula, título (con marquesina si no cabe), artista, barra de progreso con *seek*, volumen con silenciar, aleatorio y repetir.
- Icono en la bandeja del sistema con menú, notificaciones al cambiar de canción y teclas globales configurables.
- Si no hay ningún reproductor abierto, **pulsar play abre Spotify o YouTube** (configurable).
- Un selector (el nombre del reproductor, abajo a la izquierda) para **abrir otro reproductor**: Spotify, YouTube, YouTube Music, SoundCloud, Deezer, Apple Music, TIDAL.

**Extras**
- **Letras** sincronizadas (LRC) o en texto plano desde *lrclib.net*, con limpieza de títulos de YouTube, ranking de resultados, reintento y botón de recarga.
- **Botón "me gusta"** para Spotify (guardar en tus canciones favoritas) y YouTube (me gusta del vídeo).
- **Historial** local, **estadísticas** y un **resumen semanal** automático.
- **Filtro de anuncios de Spotify** (no ensucian historial ni estadísticas) con registro aparte en CSV.
- **Scrobbling** a Last.fm o ListenBrainz.
- Enlace "ir a la canción" (búsqueda, o el vídeo exacto si hay clave de API de YouTube).
- Dos aspectos visuales (**predeterminado** rojo→azul neón y **Cosmos**), accesibilidad (tamaño de letra, alto contraste, reducir movimiento), escala automática según la resolución.
- Puente con el tema **Switch** de Spicetify para cambiar de modo desde el reproductor.
- **Spicetify AutoFix**: tarea programada que reaplica Spicetify cuando Spotify se actualiza, sin ventanas.

---

## 2. Requisitos, instalación y ejecución

### Requisitos
| Componente | Versión / nota |
|---|---|
| Python | 3.10 o superior (se probó con 3.12) |
| PyQt6 | `>=6.11,<7` |
| pywnp | `>=2.0.2,<2.1` (el parche `pywnp_patch.py` está escrito contra 2.0.2; el límite superior evita que una versión nueva lo rompa sin avisar) |
| aiohttp | `>=3.14.5` (dependencia de pywnp; se lista para que el empaquetado la fije) |
| winsdk | `>=1.0.0b10`, **solo Windows** (apps de escritorio vía SMTC). En PyPI solo hay versiones beta |
| Extensión | **WebNowPlaying** en el navegador, con el *adaptador personalizado* apuntando a `localhost:<puerto>` (por defecto **1234**) |

### Instalación
```bash
pip install -r requirements.txt
python main.py                 # usa el puerto de la última sesión (por defecto 1234)
python main.py --port 5678     # fija el puerto
```

En Linux/macOS la app arranca, pero sin `winsdk` ni `RegisterHotKey`: no ve apps de escritorio y las teclas globales quedan desactivadas (el resto funciona).

### Primera ejecución
Se muestra el **asistente de bienvenida** (4 pasos: bienvenida con la firma del desarrollador, modos de ventana, instalar la extensión, fin con la casilla «Iniciar junto con Windows»). Se guarda `onboarding_completed` y no vuelve a aparecer.

---

## 3. Arquitectura general

```
   Navegador                         Windows
 ┌───────────────┐              ┌──────────────────┐
 │ WebNowPlaying │              │ SMTC (Spotify,   │
 │  (extensión)  │              │ apps de escrit.) │
 └───────┬───────┘              └────────┬─────────┘
         │ WebSocket 127.0.0.1:1234      │ winsdk
         └──────────────┬────────────────┘
                        ▼
              ┌───────────────────┐
              │ pywnp (+ parche)  │  servidor aiohttp en hilos propios
              └─────────┬─────────┘
                        │ WNPRedux.media_info  (se lee, no se empuja)
                        ▼
              ┌───────────────────┐   QTimer 150 ms (700 ms en reposo)
              │   WNPBackend      │──► PlayerState (dataclass)
              └─────────┬─────────┘    señales Qt: stateChanged, connectionChanged,
                        │              serverError, started, stopped, noPlayerPlayRequested
                        ▼
              ┌───────────────────┐
              │  AppController    │  coordina todo (ver §8)
              └───┬───┬───┬───┬───┘
        ┌─────────┘   │   │   └──────────┐
        ▼             ▼   ▼              ▼
   MainWindow    MiniWindow DockWindow   Servicios: Historial · Estadísticas · Anuncios ·
   (completa)    (compacta) (panel)      Scrobbling · Letras · Carátulas · "Me gusta" ·
                                         Hotkeys · Tema de Spotify · Bandeja
```

Ideas de diseño que se repiten por todo el código:

- **El backend no empuja datos**: la interfaz recibe un `PlayerState` inmutable por señal, y solo cuando cambia (si el estado nuevo es igual al anterior no se emite nada).
- **Todo lo lento va a hilos** (`QThreadPool` / `ThreadPoolExecutor`): descarga de carátulas, letras, scrobbling, "me gusta", conexión OAuth. La interfaz solo recibe resultados por señales.
- **Sin dependencias extra para la red**: se usa `urllib` de la biblioteca estándar (no `requests`).
- **Los textos y estilos se construyen una vez** al crear cada widget; por eso el aspecto, el tamaño de letra y el contraste piden reiniciar la app.
- **Las animaciones usan reloj real** (`time.monotonic`), no "N píxeles por tick", y se detienen cuando el widget no es visible o con "reducir movimiento".

---

## 4. Estructura de archivos

### Núcleo
| Archivo | Líneas | Responsabilidad |
|---|---:|---|
| `main.py` | 92 | Punto de entrada: escala, tema, `QApplication`, comprobaciones, instancia única, arranque |
| `app_controller.py` | 832 | Coordina backend, ventanas, bandeja, servicios y configuración |
| `backend.py` | 310 | `WNPBackend` y `PlayerState`: conexión con pywnp y sondeo |
| `pywnp_patch.py` | 629 | Parches en caliente de 12 errores de pywnp 2.0.2 |
| `config.py` | 183 | `AppConfig` (dataclass) guardada como JSON |
| `startup_checks.py` | 42 | Comprueba dependencias antes de arrancar |
| `single_instance.py` | 69 | Evita dos instancias (socket local) |
| `error_handling.py` | 119 | Manejador global de errores y registro |

### Interfaz
| Archivo | Líneas | Responsabilidad |
|---|---:|---|
| `main_window.py` | 1418 | Ventana completa |
| `mini_window.py` | 708 | Ventana compacta (barra + vinilo) |
| `dock_window.py` | 1110 | Panel lateral (tarjeta / compacto), ondas, letra |
| `widgets.py` | 2288 | Botones, barras, carátula, vinilo, panel de letra, indicador… |
| `dialogs.py` | 1499 | Puerto, Acerca de, errores, teclas, estadísticas, historial, configuración |
| `likes_dialog.py` | 218 | Conectar cuentas para "me gusta" |
| `onboarding.py` | ~650 | Asistente de bienvenida |
| `autostart.py` | ~100 | Inicio con Windows (registro `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) |
| `weekly_recap.py` | 179 | Aviso semanal no modal |
| `theme.py` | 714 | Paleta, aspectos, accesibilidad, QSS global |
| `accent.py` | 172 | Colores de acento extraídos de la carátula |
| `cosmos_sky.py` | 241 | Fondo animado del aspecto Cosmos |
| `icons.py` | 353 | Iconos dibujados por código (`QPainterPath`, lienzo 24×24) |
| `app_icon.py` | 36 | Icono de la aplicación dibujado por código |
| `screen_scale.py` | 184 | Escala de la interfaz según la resolución |

### Funciones
| Archivo | Líneas | Responsabilidad |
|---|---:|---|
| `lyrics.py` | 360 | Búsqueda de letras en lrclib |
| `likes.py` | 432 | Clientes de Spotify/YouTube y `LikeManager` |
| `oauth_pkce.py` | 214 | Flujo OAuth 2.0 con PKCE |
| `player_launcher.py` | 132 | Abre Spotify/YouTube y otros reproductores |
| `history.py` | 192 | Historial local |
| `stats.py` | 123 | Estadísticas (funciones puras) |
| `ad_filter.py` / `ad_log.py` | 96 / 79 | Detección y registro de anuncios |
| `scrobbling.py` | 292 | Last.fm y ListenBrainz |
| `cover_loader.py` | 247 | Descarga de carátulas |
| `links.py` / `youtube_api.py` | 52 / 89 | "Ir a la canción" |
| `hotkeys.py` | 247 | Teclas globales (Windows) |
| `spotify_theme.py` | 261 | Puente WebSocket con el tema Switch de Spicetify |

### Otros directorios
```
SpicetifyAutoFix/   Tarea programada que reaplica Spicetify (ver §12)
tools/              Diagnósticos y script de YouTube (ver §13)
tests/              Pruebas (ver §14)
main.spec           Receta de PyInstaller (ver §15)
requirements.txt
```

---

## 5. Arranque de la aplicación

Orden de `main.py` (el orden importa y está comentado en el código):

1. Lee los argumentos (`--port`).
2. Carga la configuración y fija la **escala** (`screen_scale.configure`) *antes* de crear `QApplication`, porque `QT_SCALE_FACTOR` solo se lee al iniciar Qt.
3. Aplica el **aspecto** (`theme.set_player_theme`) *antes* de importar `app_controller`: varios módulos leen `Palette` al importarse.
4. Crea `QApplication` con `setQuitOnLastWindowClosed(False)` (la app vive en la bandeja), paleta oscura y QSS global.
5. Instala el manejador global de errores.
6. `check_dependencies()`: si falta algo, muestra un diálogo y sale.
7. `SingleInstanceGuard`: si ya hay otra instancia, le pide que se muestre y esta termina.
8. Crea `AppController`, conecta `aboutToQuit → shutdown` (cierre por el sistema) y `showRequested → show_current`.
9. `controller.start()` (asistente la primera vez, si no la ventana del último modo, o solo bandeja si `start_minimized`) y `app.exec()`.

---

## 6. Backend y comunicación con los reproductores

### `PlayerState`
Dataclass con todo lo que la interfaz necesita:

`connected, clients, player_name, state ("STOPPED"|"PLAYING"|"PAUSED"), title, artist, album, cover_url, duration, duration_seconds, position, position_seconds, position_percent, volume, shuffle_active, repeat_mode ("NONE"|"ONE"|"ALL"), can_play_pause, can_prev, can_next, can_seek, can_volume, can_shuffle, can_repeat`

Propiedades útiles: `has_media` (hay título o el estado no es STOPPED) y `controls_available`.

### `WNPBackend`
- **Sondeo**: un `QTimer` lee `WNPRedux.media_info` cada **150 ms** (cada **700 ms** cuando ninguna ventana es visible). Si el `PlayerState` resultante es igual al anterior, no emite.
- **Señales**: `stateChanged(PlayerState)`, `connectionChanged(bool)`, `serverError(str)`, `started(int)`, `stopped()`, `noPlayerPlayRequested()`.
- **Control**: `toggle_play_pause`, `next`, `previous`, `set_position_percent`, `set_volume`, `toggle_shuffle`, `cycle_repeat`.
- **Puerto**: antes de arrancar pywnp comprueba que `127.0.0.1:<puerto>` esté libre (pywnp reintenta el bind en silencio cada 5 s sin avisar; ver parche #6) y emite un error claro si no.
- **`restart_on_port(port) -> bool`**: cambia el puerto. Si el nuevo está ocupado **no toca el servidor actual** y devuelve `False`; si el arranque falla, vuelve al puerto anterior. Solo devuelve `True` si quedó escuchando en el nuevo.
- **"Sin reproductor"**: `has_no_player()` es verdadero si lleva ≥ 1 s sin nada reproducible (el margen evita confundir el hueco entre dos canciones de YouTube). Con eso, `toggle_play_pause()` emite `noPlayerPlayRequested` en vez de no hacer nada.
- **Directos / sin duración**: si `duration_seconds <= 0`, `position_percent` se fuerza a 0 (pywnp reportaba 100 % y la barra se veía llena).

---

## 7. El parche de pywnp (12 errores corregidos)

`pywnp_patch.py` sustituye funciones de `pywnp` 2.0.2 en memoria (no modifica la librería instalada). `apply()` es un envoltorio seguro: si pywnp cambia algo interno y un parche falla, avisa por *stderr* y **la app sigue arrancando** (antes la excepción impedía iniciar el servidor).

| # | Dónde | Problema | Efecto |
|---|---|---|---|
| 1 | `WNPReduxNative.on_message_hook` | `str.replace()` con un solo argumento → `TypeError` silenciado | Ninguna orden llegaba a apps nativas |
| 2 | ídem | Llamadas asíncronas de Windows sin `await` ni loop | Las órdenes nunca se ejecutaban |
| 3 | repetir/aleatorio nativos | La API de Windows exige el valor destino; pywnp no lo pasaba | "Invalid parameter count" |
| 4 | `playback_info_changed_native` | Nunca copiaba `is_shuffle_active` | El botón aleatorio no reflejaba el estado |
| 5 | `MediaControls.from_json` | Intercambiaba `supports_skip_previous/next` | Anterior/siguiente mal habilitados |
| 6 | `HttpServer.start` | Puerto ocupado: reintento infinito y silencioso | Conexión que nunca llega (la app ahora lo comprueba antes) |
| 7 | Proactor en Windows | Tracebacks ruidosos al cerrar clientes de golpe | Consola sucia |
| 8 | `web_websocket_handler` | `update_media_info()` casi nunca se llamaba | Pestaña activa mal elegida |
| 9 | `get_media_info` | Pisaba `player_name` con "Windows Media Session" | Imposible saber si era Spotify, VLC… |
| 10 | `timeline_properties_changed_native` | `position_percent = 100` si la duración es 0 | Barra llena en apps sin duración |
| 11 | timeline / playback_info | Sin `try/except` al leer la sesión | Excepciones sueltas |
| 12 | `win_sessions` | Guardaba la sesión vieja al reiniciarse el reproductor | Órdenes que fallaban hasta reiniciar |

Pendiente conocido (no parcheado, solo Windows): al reiniciar el servidor, pywnp puede dejar un segundo hilo de posición "optimista", y la barra avanzaría al doble hasta el siguiente evento de tiempo.

---

## 8. El controlador (`AppController`)

Es el centro de la aplicación. Crea y conecta todo:

- **Ventanas**: `MainWindow`, `MiniWindow`, `DockWindow`; recuerda el último modo, posiciones y zoom; gestiona fundidos entre modos.
- **Bandeja**: menú con *Reproducir/Pausar, Anterior, Siguiente, Mostrar reproductor, Modo compacto, Configuración…, Registro de anuncios (CSV)…, Salir*. Un clic alterna mostrar/ocultar.
- **Cambio de canción con espera (debounce)**: una canción solo se registra cuando `(título, artista)` lleva **500 ms estable** (`TRACK_SETTLE_MS`). La extensión manda título, artista y duración en mensajes separados y el sondeo puede caer entre ellos; sin esta espera se guardaban entradas mezcladas en el historial y se enviaban a Last.fm.
- **Al registrar una canción**: filtra anuncios → consulta "me gusta" → añade al historial → notificación → scrobble → mantiene el icono de la bandeja.
- **"Reproducir" sin reproductor**: según `empty_play_action` abre Spotify/YouTube/YouTube Music, pregunta en un menú, o no hace nada. Si abre Spotify, cuando aparece su sesión (hasta **40 s**) le da play **una sola vez** (no si ya suena, ni con otro reproductor).
- **Autoguardado** de la configuración cada **20 s** y al salir. Solo guarda la posición de una ventana si alguna vez se mostró (antes se guardaba (0, 0) y aparecía en la esquina).
- **Cambio de puerto**: solo guarda el puerto si el servidor quedó escuchando en él.
- **Cierre**: `shutdown()` es idempotente y se llama tanto desde "Salir" como desde `aboutToQuit`.
- **Resumen semanal**: al arrancar, si pasaron ≥ 7 días, muestra el aviso.

---

## 9. Interfaz gráfica

### 9.1 Ventana completa (`main_window.py`)
- Ancho **356 px** (rango 320–460, se cambia con la rueda del ratón) y carátula de 150–260 px.
- Cabecera con indicador "REPRODUCIENDO", ajustes, minimizar/compactar, cerrar.
- Carátula con colores de acento extraídos de la imagen; título con marquesina; artista.
- Barra de progreso con *seek*, tiempos, controles (aleatorio, anterior, play/pausa, siguiente, repetir) y volumen.
- **Pie**: a la izquierda el **selector de reproductor** (nombre + ▾, menú para abrir otro); a la derecha el **corazón de "me gusta"** y el botón de **historial reciente**.
- **Panel de letra** lateral (240 px, a izquierda o derecha).
- Los botones play/pausa están activos aunque no haya reproductor (abren Spotify/YouTube); anterior/siguiente no.

### 9.2 Ventana compacta (`mini_window.py`)
Barra horizontal flotante de **380 × 74** (escala 0,75–1,6) con el vinilo girando a la izquierda (el vinilo gira solo mientras suena y se detiene con "reducir movimiento"). Tiene modo barra y modo disco.

### 9.3 Panel lateral (`dock_window.py`)
Una **pestaña anclada a un borde** (`dock_edge`: izquierdo/derecho) que se despliega. Apertura por clic, por hover o ambos (`dock_hide_mode`).

Dos estilos (`dock_style`):

| Estilo | Tamaño | Contenido |
|---|---|---|
| **Tarjeta** | 248 × 408 (carátula 148) | Carátula grande, título, artista, controles, progreso |
| **Compacto** | 380 × 96 | Disco de vinilo estilo ventana compacta |

**La pestaña (barra)** de estilo tarjeta, de arriba abajo: flecha de desplegar, *volver al reproductor completo*, anterior / play / siguiente, **micrófono (letra)**, **corazón (me gusta)** y el **círculo de ondas**.

- **Sin botón de esquina**: en la tarjeta grande ya no hay botón para volver al modo completo en la esquina (la pestaña lo tiene); en el compacto sí, porque allí no hay otro.
- **Modo letra**: el micrófono sustituye la carátula y el título por la letra de la canción (línea actual resaltada), manteniendo controles y progreso debajo. Si el panel está recogido, lo despliega.
- **Ondas alrededor de la barra**: mientras suena algo (y la opción está activada, no se usa "reducir movimiento", el estilo es tarjeta y la ventana es visible) salen ondas con degradado del acento y resplandor. La zona de la pestaña tiene un margen transparente de **12 px** (`RIPPLE_M`) que no mueve la píldora de su sitio (verificado por test: sigue a 3 px del borde y 28 px de ancho). Se repinta solo la franja de la pestaña, a 25 fps.
- **Círculo de ondas** (`_WaveDot`): 4 anillos, halo que "respira" y núcleo que late; estático en pausa.

### 9.4 Widgets (`widgets.py`)
`IconButton` (con color fijo opcional, usado por el corazón), `SeekBar`, `VolumeBar`, `ElidedLabel`, `MarqueeLabel`, `CoverArt`, `VinylCover`, `HistoryCard`, `PulsingDots`, `ArrowComboBox`, `NoWheelSlider`, `_LyricsCanvas`/`LyricsPanel`, `PlatformPickerButton` y `PlayingIndicator` (4 barras de 20×16 con degradado y movimiento orgánico, a ~30 fps).

### 9.5 Aspecto, accesibilidad y escala
- **Aspectos** (`player_theme`): `default` (rojo → azul neón) y `cosmos` (índigo + violeta/celeste, con cielo animado). Cambiarlo pide reiniciar.
- **Accesibilidad**: `font_scale` (1,0 / 1,15 / 1,3), `high_contrast`, y "reducir movimiento" (se toma de la preferencia del sistema). Piden reiniciar.
- **Opacidad** de ventana (0,5–1,0), en caliente.
- **Escala automática** (`screen_scale.py`): factor según la altura útil lógica de la pantalla (referencia Full HD): por debajo de 660 px se reduce, entre 660 y 1240 es 1,00, por encima se amplía hasta 1,50; redondeado hacia abajo a pasos de 0,05 y acotado a [0,70 – 1,50]. `ui_scale > 0` fija un valor manual; la variable `QT_SCALE_FACTOR` tiene prioridad.
- **Iconos** dibujados por código (`icons.py`), incluidos `heart`, `heart_outline` y `refresh`.

---

## 10. Funciones

### 10.1 Letras (`lyrics.py`)
- Fuente: **lrclib.net**, endpoints `/api/get` (coincidencia exacta) y `/api/search` (difusa). Devuelve letra sincronizada (formato LRC, que se analiza a pares `(segundos, texto)`) o texto plano, o marca la canción como instrumental.
- **Limpieza de títulos de YouTube**: quita `(Official Video)`, `[HD]`, `- Topic`, `VEVO`, comillas decorativas…, separa "Artista - Canción", y prueba varias variantes (`query_candidates`).
- **Elección del resultado**: puntúa título, artista y duración y descarta lo que no se parece (antes tomaba el primer resultado sin comprobar). Una duración que difiere más de 25 s se descarta.
- **Reintento** automático de un fallo transitorio; un 404 no se reintenta.
- **Resultados posibles**: encontrada, `{"error": …}` (fallo real), o `None` (no existe). Los errores no se cachean; "no existe" sí, pero el botón de recarga (`request(..., force=True)`) lo ignora.
- **Panel** (`LyricsPanel`): botón de recarga en errores y "no encontrada"; **espera de 450 ms** ante cambios de canción para no buscar con metadatos a medias (la primera carga es inmediata).

### 10.2 "Me gusta" (`likes.py`, `oauth_pkce.py`, `likes_dialog.py`)

**Qué hace**: el corazón aparece solo cuando suena **Spotify** o **YouTube** (incluye YouTube Music, que no es identificable; ver límites). Relleno y rosa = te gusta; contorno = no. Al pulsarlo cambia al instante y se revierte con un mensaje si la API falla.

**Spotify** (Web API tras la migración de febrero de 2026):
- Identifica la canción con `GET /me/player/currently-playing` si coincide con el título mostrado; si no, busca con `GET /search` y puntúa.
- `GET /me/library/contains?uris=…`, `PUT /me/library?uris=…`, `DELETE /me/library?uris=…`. Los endpoints antiguos `/me/tracks` solo se usan de respaldo ante 400/404/410.
- Alcances: `user-library-read user-library-modify user-read-currently-playing`.
- **Requisitos**: una app propia en developer.spotify.com (su dueño con **Premium**), añadir `http://127.0.0.1:8898/callback` como *Redirect URI* y pegar el *Client ID*.

**YouTube** (Data API v3, alcance `youtube.force-ssl`):
- El id del vídeo se saca de la **miniatura** (`…/vi/<id>/…`). En YouTube Music la carátula no lo trae: el botón explica por qué no puede.
- `GET /videos/getRating` (1 unidad de cuota), `POST /videos/rate?rating=like|none` (50 unidades; cuota diaria 10 000).
- **Requisitos**: proyecto de Google Cloud con YouTube Data API v3 activada, cliente OAuth de tipo "Aplicación de escritorio" (ID + secreto) y pantalla de consentimiento **publicada** (en modo prueba el permiso caduca a los 7 días).

**OAuth** (`oauth_pkce.py`): PKCE (S256, verificado con el vector del RFC 7636), servidor local de un solo uso en `127.0.0.1`, comprobación de `state`, cancelable, con tiempo límite. Se guarda solo el *refresh token*; el *access token* vive en memoria y se renueva (con un reintento ante 401). Si el servicio rota el refresh token, se guarda el nuevo.

**Gestor** (`LikeManager`): consulta en segundo plano; ignora respuestas de una canción anterior; reutiliza la identificación entre clics; emite `LikeInfo(service, configured, liked, busy, message)` y un tooltip legible (por ejemplo, el 403 de Spotify explica Premium y *User Management*).

Se configura en **Configuración → Cuentas para «Me gusta»…**

### 10.3 Abrir un reproductor (`player_launcher.py`)
- **Spotify**: protocolo `spotify:` (instalador clásico y Microsoft Store); en Windows primero comprueba en el registro que esté registrado (si no, cae a `%APPDATA%\Spotify\Spotify.exe` y, por último, a open.spotify.com).
- **YouTube / YouTube Music / SoundCloud / Deezer / Apple Music / TIDAL**: abre su web en el navegador predeterminado.
- Ajuste `empty_play_action`: `ask` (menú junto al cursor) · `spotify` · `youtube` · `ytmusic` · `none`.

### 10.4 Historial (`history.py`)
- `history.json`, hasta **300 entradas**, con título, artista, reproductor, fecha y duración. No duplica la entrada inmediatamente anterior.
- **Seguridad de datos**: si la lectura falla por un error de E/S (antivirus, OneDrive…) **no se escribe**, para no pisar el historial. Si el JSON está corrupto, conserva una copia en `history.json.corrupt` y empieza de nuevo.
- Los anuncios no se guardan (se purgan al migrar con copia `.bak`).

### 10.5 Estadísticas y resumen semanal (`stats.py`, `weekly_recap.py`)
- Funciones puras sobre el historial: total de tiempo, canciones únicas, top canciones, top artistas, conteos, por periodo.
- **Aproximaciones conscientes**: "veces escuchada" cuenta entradas (un bucle de una canción cuenta una vez) y el tiempo suma la duración completa de cada canción iniciada, aunque se salte antes.
- **Resumen semanal**: aviso no modal de esquina, 2–4 datos con fundido cruzado, como máximo una vez por semana (`last_weekly_recap_shown`).

### 10.6 Anuncios de Spotify (`ad_filter.py`, `ad_log.py`)
Reglas conservadoras: (1) el artista es exactamente "Spotify"; (2) el reproductor es Spotify, el artista viene vacío (o es "Spotify") y el título es típico de anuncio (*Advertisement, Anuncio, Publicidad…*). Se amplía sin tocar código con `ad_rules.json`:
```json
{"artistas": ["Nombre de un anunciante"], "titulos": ["Título de un anuncio"]}
```
Los anuncios van a `anuncios.csv` (accesible desde la bandeja) y no al historial, estadísticas ni scrobbling.

### 10.7 Scrobbling (`scrobbling.py`)
- **Last.fm** (`https://ws.audioscrobbler.com/2.0/`; firma MD5 exigida por su API) y **ListenBrainz**. La contraseña de Last.fm nunca se guarda: solo la sesión de `auth.getMobileSession`.
- "Ahora suena" inmediato; el scrobble se envía a partir de **la mitad de la duración o 4 min** (lo primero) y solo si la canción dura **más de 30 s**. Todo en un hilo de fondo; los errores se devuelven como texto, nunca interrumpen la reproducción.

### 10.8 "Ir a la canción" (`links.py`, `youtube_api.py`)
Tocar la carátula/título abre una **búsqueda** en el reproductor correspondiente. Con una clave de la **YouTube Data API v3** (`youtube_api_key`), abre el **vídeo exacto**.

### 10.9 Carátulas (`cover_loader.py`)
Descarga en hilo aparte con caché de **24** carátulas y reutilización de conexiones; reintento si falla; soporta `data:` y la URL local que sirve pywnp para apps nativas.

### 10.10 Teclas globales (`hotkeys.py`)
Solo Windows (`RegisterHotKey` vía `ctypes`, sin `pywin32`). Combinaciones configurables para reproducir/pausar, siguiente y anterior (`HotkeyDialog` las graba). Exige al menos un modificador, salvo para las teclas multimedia dedicadas. Si el registro falla, se restauran los atajos que ya funcionaban.

### 10.11 Tema de Spotify (`spotify_theme.py`)
Servidor WebSocket **solo en 127.0.0.1:8977** al que se conecta el `theme.js` del tema *Switch* de Spicetify. Mensajes JSON:
```
Spotify → reproductor   {"type":"hello","mode":"cosmos","modes":[{"id","name","desc"},…]}
Spotify → reproductor   {"type":"mode","mode":"cover"}
reproductor → Spotify   {"type":"set","mode":"yefridev"}
```
Los modos se leen del propio `theme.js`, así que añadir uno allí lo hace aparecer aquí sin tocar Python. Es un canal aparte: no toca el audio ni el puerto 1234.

### 10.12 Instancia única, errores y comprobaciones
- **Instancia única**: socket local (`QLocalServer`, nombre `WNPPlayer-single-instance-v1`); una segunda ejecución pide a la primera que se muestre.
- **Errores** (`error_handling.py`): `sys.excepthook` global; muestra un diálogo amigable (un solo diálogo a la vez y el **mismo error no se repite durante 60 s**) y escribe siempre en `error.log` (se rota pasados 512 KB).
- **Dependencias** (`startup_checks.py`): avisa antes de arrancar si falta algo.

---

## 11. Configuración y archivos de datos

Carpeta de datos (`WNPPlayer`): Windows `%LOCALAPPDATA%\WNPPlayer` · macOS `~/Library/Application Support/WNPPlayer` · Linux `$XDG_CONFIG_HOME/WNPPlayer` (o `~/.config/WNPPlayer`).

| Archivo | Contenido |
|---|---|
| `config.json` | Configuración (tabla siguiente). Escritura atómica |
| `history.json` | Historial (máx. 300). Copias `.bak` / `.corrupt` si procede |
| `anuncios.csv` | Registro de anuncios de Spotify |
| `ad_rules.json` | Reglas extra de anuncios (opcional, lo creas tú) |
| `error.log` | Errores no controlados (rotación a 512 KB) |

### Campos de `config.json`

| Campo | Defecto | Descripción |
|---|---|---|
| `port` | `1234` | Puerto del servidor de pywnp |
| `last_mode` | `"main"` | Último modo (`main`/`mini`) |
| `always_on_top` | `false` | Siempre visible |
| `main_width`, `main_x`, `main_y` | `null` | Ancho (zoom) y posición de la ventana completa |
| `mini_scale`, `mini_x`, `mini_y` | `1.0`, `null` | Escala y posición de la compacta |
| `start_with_windows` | `true` | Iniciar junto con Windows (clave `HKCU\...\Run`, ver `autostart.py`) |
| `start_minimized` | `false` | Arrancar solo en la bandeja |
| `hotkeys_enabled`, `hotkey_play_pause`, `hotkey_next`, `hotkey_previous` | `false`, `""` | Teclas globales |
| `notifications_enabled` | `true` | Notificar al cambiar de canción |
| `empty_play_action` | `"ask"` | Qué hacer al pulsar play sin reproductor |
| `likes_enabled` | `true` | Mostrar el botón "me gusta" |
| `spotify_client_id`, `spotify_refresh_token` | `""` | Cuenta de Spotify |
| `google_client_id`, `google_client_secret`, `google_refresh_token` | `""` | Cuenta de Google/YouTube |
| `bar_waves_enabled` | `true` | Ondas alrededor de la barra del panel lateral |
| `lyrics_panel_enabled`, `lyrics_panel_side` | `false`, `"right"` | Panel de letra de la ventana completa |
| `onboarding_completed` | `false` | Asistente ya mostrado |
| `window_opacity` | `1.0` | Opacidad (0,5–1,0) |
| `font_scale`, `ui_scale`, `high_contrast` | `1.0`, `0.0`, `false` | Accesibilidad (piden reiniciar) |
| `player_theme` | `"default"` | `default` o `cosmos` (pide reiniciar) |
| `last_weekly_recap_shown` | `""` | ISO de la última vez |
| `scrobble_service` | `"NONE"` | `NONE`/`LASTFM`/`LISTENBRAINZ` |
| `lastfm_api_key`, `lastfm_api_secret`, `lastfm_session_key`, `lastfm_username` | `""` | Last.fm |
| `listenbrainz_token` | `""` | ListenBrainz |
| `youtube_api_key` | `""` | Para abrir el vídeo exacto |
| `history_scroll_pos`, `stats_scroll_pos` | `0` | Posición de scroll de esos diálogos |
| `dock_edge`, `dock_hide_mode`, `dock_style` | `"right"`, `"both"`, `"card"` | Panel lateral |
| `spotify_theme_enabled`, `spotify_theme_port`, `spotify_theme_mode` | `true`, `8977`, `""` | Puente con el tema de Spotify |

> **Validación al cargar** (ronda 5): `AppConfig._sanitize` descarta los valores de tipo incorrecto o con opción desconocida (vuelven a su valor por defecto) y recorta los rangos numéricos (puerto 1–65535, `font_scale` 0,8–1,6, `window_opacity` 0,5–1,0, `mini_scale` 0,5–3,0…). El resto de la configuración se conserva.

---

## 12. Spicetify AutoFix

Carpeta `SpicetifyAutoFix/`. Resuelve un problema concreto: cada vez que Spotify se actualiza, **Spicetify deja de estar aplicado** y hay que ejecutar `spicetify backup apply` a mano. Esta herramienta lo hace sola, **sin ventanas**.

### Archivos
| Archivo | Para qué |
|---|---|
| `Instalar.bat` | Instala la tarea (llama a `Instalar-AutoFix.ps1`) |
| `Instalar-AutoFix.ps1` | Instalador: copia archivos, compila el lanzador, crea la tarea y la prueba |
| `Spicetify-AutoFix.ps1` | La lógica de comprobación y reaplicación |
| `Lanzador.cs` | Código fuente de `AutoFixSilencioso.exe` (se compila en tu equipo) |
| `Comprobar-ahora.bat`, `Estado.bat`, `Desinstalar.bat` | Utilidades |
| `LEEME.md` | Guía de uso |

Datos en `%LOCALAPPDATA%\SpicetifyAutoFix`: `estado.json`, `autofix.log`, `ultima-comprobacion.txt`.

### Qué comprueba (`Spicetify-AutoFix.ps1`)
- **Caso A**: la versión de `Spotify.exe` difiere de la guardada en `[Backup] version` de `config-xpui.ini` → Spotify se actualizó.
- **Caso B**: las versiones coinciden pero los `.js` de `xpui` ya no contienen "Spicetify" → perdió el parche. (Se guarda una "huella" de tamaño y fecha de los archivos para no releer decenas de MB en cada revisión.)
- **Antes de actuar**: espera a que `Spotify.exe` lleve 90 s estable y a que no haya un instalador de Spotify en marcha; respeta un enfriamiento de 30 min entre intentos (24 h para el caso B); un mutex evita ejecuciones simultáneas.
- **Acción**: `spicetify backup apply`. Si falla, `spicetify restore` para que Spotify no quede en blanco; tras 3 fallos con la misma versión se pausa y reintenta cada 6 h. Si aplica bien pero no ve el parche, desactiva esa detección para no entrar en bucle.

### Cómo se lanza, sin ventanas
`powershell.exe -WindowStyle Hidden` crea la consola y la oculta *después* (parpadea y roba el foco). El instalador prueba, en este orden, y usa el primero que funcione:

1. **`AutoFixSilencioso.exe`** — aplicación de Windows sin consola que arranca PowerShell con `CREATE_NO_WINDOW`. En este modo es además un **vigilante**: queda residente (mira cada 4 s si existe el proceso Spotify) y comprueba **solo cuando Spotify se abre o se cierra**:

   | Evento | Qué hace |
   |---|---|
   | Inicio de sesión | Una comprobación |
   | Spotify se cierra | Aplica en silencio (nada que reiniciar); segundo intento a los 2 min |
   | Spotify se abre con ventana | Comprueba a los 20 s, 110 s y 6 min; si falta el parche lo aplica (Spotify se reinicia una vez) |
   | Spotify se abre en la bandeja | No lo reinicia delante del usuario; espera a que lo cierres |

   La tarea tiene además una repetición cada 30 min que solo sirve de supervisor (relanza el vigilante si murió).
2. `conhost.exe --headless powershell.exe` (sondeo cada `-CadaMinutos`).
3. `powershell.exe -WindowStyle Hidden` (sondeo; el que puede parpadear).

Parámetros del instalador: `-EsperarSpotifyCerrado` (nunca reiniciar Spotify, ni siquiera con ventana), `-CadaMinutos` (solo métodos 2 y 3), `-SinLanzador`, `-SinConhost`.

**Avisos**: un `.exe` que arranca PowerShell oculto puede asustar a un antivirus (si lo bloquea, se cae al método 2). Si Spotify se minimiza a la bandeja al cerrar, el proceso no termina y no hay evento de cierre. La parte de Windows (compilación con `Add-Type`, Programador de tareas, detección de ventana) **no se pudo probar fuera de Windows**; la lógica se validó con PowerShell 7 y con un Spotify/PowerShell simulados.

---

## 13. Herramientas auxiliares

Carpeta `tools/`:

| Herramienta | Qué hace |
|---|---|
| `youtube_saltar_anuncios.user.js` | Userscript (Tampermonkey/Violentmonkey) que pulsa "Saltar anuncio" en cuanto aparece. Solo actúa con anuncios saltables; sin peticiones de red. Menú: alternar, contador, depuración. Funciona en `youtube.com`, `m.youtube.com` y `music.youtube.com`. En Chrome reciente hay que activar "Permitir secuencias de comandos de usuario" en la extensión |
| `diagnostico_anuncios.py` | Registra lo que WebNowPlaying reporta durante un anuncio y permite probar si "ir al final" lo termina. Hay que cerrar WNP Player antes (comparten puerto) |
| `diagnostico_sesiones.py` | Cuando no se detecta Spotify de escritorio: revisa las tres capas (Spotify abierto → sesión de Windows → pywnp y el parche) y emite un VEREDICTO; guarda `diagnostico_sesiones_<fecha>.txt` |

---

## 14. Pruebas

Son **scripts independientes** (no usan pytest; cada uno hace `sys.exit` al final), pensados para ejecutarse en modo sin pantalla:

```bash
QT_QPA_PLATFORM=offscreen python tests/test_ads.py
# todos:
for t in tests/test_*.py; do QT_QPA_PLATFORM=offscreen python $t || echo "FALLA $t"; done
```

| Script | Cubre |
|---|---|
| `test_ads.py` | Detección de anuncios, registro y migración del historial |
| `test_cosmos.py` | Aspecto Cosmos y cielo animado |
| `test_diagnostico*.py` | Herramientas de diagnóstico |
| `test_dock_bar.py` | Pestaña del panel lateral |
| `test_layout_polish.py` | Maquetación y desbordes |
| `test_pywnp_rpc.py` | Órdenes a apps nativas (parche de pywnp) |
| `test_screen_scale.py` | Escala según resolución |
| `test_settings_dialog.py`, `test_smoke_dialogs.py` | Diálogos y ajustes |
| `test_ui_patches.py` | Correcciones de interfaz (volumen, marquesina, lienzo de letra…) |
| `test_fixes_ronda3.py` | 28 comprobaciones: debounce de canción, historial, puerto, posiciones, directos, parche seguro, errores |
| `test_start_player.py` | 48: reproducir sin reproductor, autoplay, botones activos |
| `test_lyrics_robustez.py` | 32: limpieza, ranking, reintento, recarga, espera |
| `test_likes.py` | 63: PKCE, flujo OAuth contra servidor falso, clientes, gestor, diálogo |
| `test_ui_ronda4.py` | 77: pestaña, letra, ondas, selector, "me gusta", indicador |

**Qué no cubren**: nada que dependa de Windows real (SMTC, `RegisterHotKey`, Programador de tareas), de un navegador con la extensión, ni de Spotify/YouTube/Last.fm reales: la red se simula con servidores locales o funciones sustituidas.

---

## 15. Empaquetado

`main.spec` (PyInstaller) recoge todos los submódulos y datos de PyQt6 y, con `collect_all`, `pywnp`, `aiohttp` y sus dependencias (`aiohappyeyeballs`, `aiosignal`, `attrs`, `frozenlist`, `multidict`, `propcache`, `yarl`) y `winsdk` (que expone sus espacios de nombres por importación dinámica). Los módulos nuevos (`likes`, `oauth_pkce`, `likes_dialog`, `player_launcher`) se importan de forma estática o dentro de funciones, que PyInstaller detecta.

---

## 16. Seguridad y privacidad

- **Red local**: el servidor de pywnp y el puente del tema de Spotify escuchan **solo en 127.0.0.1**. El puente WebSocket (8977) no comprueba el origen de la conexión: cualquier página local podría conectarse y cambiar el modo del tema (impacto bajo).
- **Credenciales**: `config.json` guarda **en texto plano** las claves de API, el secreto de Google, y los *refresh tokens* de Spotify/Google/Last.fm. Es un archivo local de tu usuario; no lo compartas ni lo subas a un repositorio. La contraseña de Last.fm no se guarda.
- **Qué sale de tu equipo y adónde**:
  - lrclib.net: artista, título, álbum y duración (para la letra).
  - Last.fm / ListenBrainz: lo que escuchas (si activas el scrobbling).
  - Spotify / Google: solo si conectas la cuenta para "me gusta"; la autorización se hace en el navegador y la app nunca ve tu contraseña.
  - YouTube Data API: solo con tu clave, para abrir el vídeo exacto.
  - Servidores de carátulas: la URL que entregue el reproductor.
- **Anuncios CSV**: los textos que empiezan por `=`, `+`, `-`, `@`, tab o CR se guardan con un apóstrofo delante para que Excel no los interprete como fórmula (ronda 5).

---

## 17. Limitaciones conocidas

- **"Me gusta" en YouTube Music**: no se puede identificar el vídeo (su carátula no incluye el id). En YouTube depende de que la extensión entregue la miniatura con el id (no verificado con una instalación real).
- **Spotify "sin canción cargada"** se interpreta como "sin reproductor": pulsar play vuelve a lanzar Spotify.
- **Estadísticas aproximadas** (ver §10.5) y limitadas a las últimas 300 reproducciones.
- **La letra puede seguir fallando** si lrclib no tiene la canción; ahora el botón de recarga permite reintentarlo y el mensaje lo dice.
- **Windows**: reiniciar el servidor puede dejar dos hilos de posición hasta el siguiente evento (ver §7); `HttpServer.stop()` de pywnp bloquea la interfaz ~0,5 s.
- **El scrobble no descuenta pausas** (solo se cancela al detenerse) y no hay cola de reintento sin conexión.
- **Spicetify AutoFix**: sin evento de cierre si Spotify se minimiza a la bandeja; la parte de Windows no se probó fuera de Windows.
- Las pruebas no son de `pytest` (los `sys.exit` a nivel de módulo impiden `pytest tests/`).

---

## 18. Solución de problemas

| Síntoma | Qué mirar |
|---|---|
| "Esperando una reproducción" y nada más | Que la extensión WebNowPlaying apunte a `localhost:<puerto>` y el puerto coincida. Para Spotify de escritorio, ejecuta `tools/diagnostico_sesiones.py` |
| "El puerto N ya está en uso" | Otro programa lo usa (¿otra instancia? ¿`diagnostico_anuncios.py` abierto?). Cambia el puerto en Configuración; si está ocupado, se conserva el anterior |
| La letra no sale o es de otra canción | Pulsa el botón de recarga. Si el título es muy "sucio", prueba desde la fuente original |
| El corazón no aparece | Solo sale con Spotify o YouTube. Si sale gris/sin color, falta conectar la cuenta (Configuración → Cuentas para «Me gusta») |
| 403 de Spotify al dar "me gusta" | Tu cuenta debe estar en *User Management* de la app y el dueño de la app necesita Premium |
| Spotify sin tema tras actualizar | Mira `Estado.bat` y `autofix.log`; recuerda que si Spotify está en la bandeja el AutoFix espera a que lo cierres (Salir) |
| Una ventana (0, 0) tras una versión antigua | Ya se ignora un `(0, 0)` guardado; reubica la ventana |
| Errores inesperados | `error.log` en la carpeta de datos |
| El historial se ve vacío | Mira `history.json.corrupt` en la carpeta de datos |

---

## 19. Historial de revisiones

**Ronda 1 – Revisión de código.** 368 comprobaciones existentes en verde; análisis con pylint/pyflakes/vulture/bandit; 7 errores confirmados con pruebas y 10 más por lectura.

**Ronda 2 – Parches.** Debounce de cambio de canción; historial que ya no se pisa ante un fallo de lectura; cambio a puerto ocupado; posiciones (0,0); barra de directos; parche de pywnp con degradación segura; manejador de errores sin tormenta de diálogos; Last.fm por HTTPS; cierre ordenado; atajos que se restauran al cancelar.

**Ronda 3 – Spicetify AutoFix y "reproducir sin reproductor".** Lanzador sin ventana y vigilante de apertura/cierre de Spotify; caché de la comprobación del parche; play activo en reposo con apertura de Spotify/YouTube y autoplay de Spotify.

**Ronda 5 – Librerías y limpieza.** Verificadas las últimas versiones en PyPI (PyQt6 6.11.0, PyQt6-Qt6 6.11.2, PyQt6-sip 13.13.0, pywnp 2.0.2, aiohttp 3.14.5, winsdk 1.0.0b10); 600+ comprobaciones en verde sin avisos de obsolescencia; validación de `config.json`; CSV a prueba de fórmulas; MD5 de Last.fm marcado `usedforsecurity=False`; 58 anotaciones modernizadas (`X | None`) y 20 importaciones/variables sin uso eliminadas. Interfaz: los íconos (altavoz, silencio, corazón, nota…) se rellenan por devanado y ya no tienen huecos donde se cruzan trazos; la carátula ya no muestra manchas rojizas en las esquinas (el halo exterior quedaba recortado por el widget) y ahora tiene un borde de acento que "respira" con la reproducción.

**Versión 1.1.0.** `version.py` es la única fuente de la versión. Al actualizar desde 1.0, `AppConfig.load` deja `start_with_windows` en `false` si el config ya existía sin esa clave.

**Ronda 6 – Ajustes finales.** «Iniciar con Windows» en Configuración y en el asistente, activado por defecto: la entrada del registro se alinea con la configuración en cada arranque, así que un `.exe` movido de carpeta corrige solo su ruta. Panel lateral compacto: ya se muestran título y artista (se ocultaban por un error en `_sync_lyrics`). Asistente de bienvenida rehecho: sin menciones obsoletas, español neutro, firma del desarrollador (YefriDev) y aclaración de que las apps de escritorio no necesitan la extensión.

**Ronda 4 – Funciones nuevas.** Selector de reproductor; letras más robustas con botón de recarga; botón "me gusta" (Spotify y YouTube, con OAuth PKCE); panel lateral con micrófono, corazón y sin botón de esquina; indicador de reproducción y círculo de ondas más llamativos; ondas alrededor de la barra, opcionales.

---

*Documento generado a partir del código del proyecto. Si algo cambia (puertos, endpoints de Spotify/YouTube, estructura interna de pywnp), conviene revisar las secciones 6, 7 y 10.2, que son las más expuestas a cambios externos.*
