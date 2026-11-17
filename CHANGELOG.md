# Historial de versiones

Todos los cambios de YefriPlayer, de la versión más reciente a la más antigua. Las descargas de cada versión están en [Releases](https://github.com/Yeflix/yefriplayer/releases).

## 1.5.6 · 2026-11

**Carátulas sin imagen**: la nota musical se sustituye por la escena 3D de sonido (ventana completa, panel lateral y etiqueta del vinilo del modo compacto). Se pinta dentro de la propia carátula (respeta sus esquinas y su borde), a 25 fps, con menos detalle en huecos chicos, y solo mientras se ve: se para con carátula, ventana oculta o minimizada, panel lateral recogido o «reducir movimiento». **Panel lateral rediseñado**: tarjeta más ancha con estado arriba («Sonando · Spotify» / «En pausa» / «En espera»), título y artista con jerarquía (antes iguales), tiempos bajo la barra, controles más grandes y un resplandor del color de acento cuando no hay carátula; su alto se adapta a la pantalla (la carátula encoge en pantallas bajas). La pestaña separa sus botones en tres grupos. El compacto usa una carátula de 76 px, el botón de subir pasa a la fila de controles y la barra de progreso lleva los tiempos a los lados (antes pegada al borde). Pruebas nuevas: `test_panel_lateral_escena.py`.

## 1.5.5 · 2026-11

**Pantalla de carga** con la escena 3D de sonido mientras arranca: los módulos de la interfaz se importan en un hilo para que la escena siga moviéndose, y al terminar la tarjeta **se transforma** (se mueve, se redimensiona y se funde) en la ventana del modo que uses; luego se destruye, sin dejar temporizadores. No aparece al arrancar minimizado con Windows; `--sin-carga` la desactiva. **Teclas rápidas:** si Windows no deja activar una combinación (otro programa ya la usa, error 1409) ya no falla en silencio: aviso en la bandeja y en Configuración → Teclas la combinación sale en rojo con «no funciona» y el motivo.

## 1.5.4 · 2026-11

**Bienvenida:** el paso «Conecta tu música» explica la extensión WebNowPlaying en tres pasos y **comprueba en vivo** si funciona (esperando → extensión conectada → «¡Funciona! Sonando…», o la app de escritorio detectada; avisa si el puerto está ocupado); botón «Probar con YouTube» y la escena celebra cuando llega la primera canción. **Configuración:** las tarjetas de sección cubren hasta el último ajuste de cada sección (antes los últimos campos —el estado del tema de Spotify, el desplegable de scrobbling, la clave de YouTube— quedaban medio fuera) y hay separación real entre tarjetas.

## 1.5.3 · 2026-11

**Bienvenida simplificada**: 3 pasos cortos (qué es, conectar, listo) sobre una **escena 3D de sonido** (vinilo con brazo girando en su plato, anillo de barras de ecualizador que late a 120 BPM, ondas por el suelo y notas que suben; la cámara oscila alrededor) que se encaja sola al espacio disponible. **Responsive**: la bienvenida y Configuración calculan su tamaño con la pantalla (caben en portátiles al 125–150 %); en Configuración las casillas parten su texto en varias líneas, los desplegables pueden estrecharse sin cortar su lista, los ajustes del panel lateral van apilados y la barra lateral se estrecha/compacta en ventanas pequeñas. Pruebas nuevas: `test_responsive.py`.

## 1.5.2 · 2026-11

**Bienvenida animada en 3D**: fondo vivo (orbes de color y suelo de rejilla en perspectiva que avanza), icono que gira en 3D en el riel y una vuelta completa en el paso final, cambio de paso como una tarjeta que gira con profundidad y sombra, píldora que se desliza en la lista de pasos, vistas previas de los modos que se inclinan hacia el ratón, teclas rápidas que se «pulsan» solas y confeti en 3D al terminar. Sin OpenGL (QPainter con perspectiva), con un solo reloj para el fondo y los iconos, parado al ocultarse; con «reducir movimiento» de Windows todo queda quieto.

## 1.5.1 · 2026-11

**Bienvenida remasterizada** (riel de pasos, 6 pasos: plataformas, modo, extensión, teclas rápidas, preferencias recomendadas, resumen); se muestra tras una instalación nueva (`--bienvenida`) y una vez a quien ya la había visto (`WELCOME_REVISION`). **Configuración remasterizada**: barra lateral con búsqueda y secciones, una tarjeta por sección, explicación debajo de cada opción, sección «Teclas» con las combinaciones actuales y explicación detallada de «Solo el audio del reproductor». **Predeterminados** nuevos (visualizador activo, teclas `Ctrl+Shift+Espacio/C/X` activas). **«Iniciar minimizado»** solo al arrancar con Windows (`--inicio-windows`); abrirlo a mano siempre muestra la ventana. Descripción en todo el programa: **controlador multimedia** y plataformas compatibles. `--autotest --mostrar` y acceso directo «autoprueba».

## 1.5.0 · 2026-11

**Actualizaciones** desde GitHub (aviso diario, «Omitir esta versión», descarga verificada por SHA-256 y apertura del instalador). **Scrobbling** con tiempo realmente escuchado (las pausas no cuentan) y **cola sin conexión** persistente. **Canción actual** en el icono de la bandeja. **Estadísticas acumuladas** sin el límite de 300 y **exportar el historial a CSV**; «Borrar historial» pide confirmación. **Volumen** de las apps de escritorio (por aplicación). **Botones en la miniatura** de la barra de tareas (opcional). **Visualizador solo del reproductor** (Application Loopback) con respaldo automático. La autoprueba (`--autotest`) hace llamadas reales a Windows para estas funciones.

## 1.4.0 · 2026-11

**Instalador de Windows** (Inno Setup): por usuario sin administrador o para todos, registro en Aplicaciones instaladas, accesos en Inicio/escritorio, App Paths, cierre ordenado de la copia abierta (`--quit`, mutex), Spicetify AutoFix opcional, desinstalación que limpia el inicio con Windows y pregunta por los datos; `tools/construir_instalador.py` y `Construir-Instalador.bat`. **Spicetify AutoFix:** ya no reabre Spotify al aplicar con Spotify cerrado (`-n`), contesta solo a las preguntas de Spicetify (antes la corrida oculta podía quedarse esperando), detecta que Spotify se reinició al actualizarse, actúa al abrir la ventana desde la bandeja y hace una comprobación horaria sin reiniciar; aviso si se instala como administrador. **Robustez y rendimiento:** `config.json` no se reescribe cada 20 s si nada cambió y reintenta si Windows lo tiene bloqueado; un fallo persistente al leer el estado ya no se emite en cada sondeo (~7/s); `config.py` sin dependencia de Qt; AppUserModelID propio en la barra de tareas.

## 1.3.1 · 2026-11

**Empaquetado:** compilación con Nuitka revisada, autoprueba `--autotest`, aviso de errores de arranque, modo depuración (`--log`, `--depurar`), ruta real del `.exe`. **Seguridad:** tokens cifrados con DPAPI; los errores silenciados ahora dejan rastro (`diag.soft`). **Interfaz:** estados deshabilitados visibles, Configuración con búsqueda y secciones, tiempo compacto en Estadísticas, cabecera y título adaptables, enlaces con contraste AA, nombres accesibles, icono en todas las ventanas. **Rendimiento:** animaciones cacheadas (dock 8,2 % → 2,8 % de un núcleo medido por software), indicador sin temporizador con la ventana oculta. **Corregido:** `QCheckBox has been deleted` al cerrar Configuración en el `.exe`.

## 1.3.0 · 2026-10-29

Visualizador más preciso y panel lateral con el espectro hacia afuera; Configuración que «no abría» (quedaba detrás de ventanas «siempre visibles»); reproducción «pegada» con Spotify (sesiones fantasma); letras que no aparecían; primera compilación con Nuitka; hilos de Python en lugar de `QThreadPool`.

## 1.2.0 · 2026-10-28

Nombre nuevo **YefriPlayer** (antes WNP Player; migración automática de datos); visualizador de audio; registro de fallos nativos; revisión completa de controles (sin parpadeos al pulsar, barras que no rebotan, clic derecho ignorado); letras más corteses con lrclib; `.exe` en modo carpeta.

## 1.1.0 · 2026-10-26

«Iniciar con Windows»; «Acerca de»; validación de `config.json`; casillas con palomita; asistente de bienvenida rehecho; correcciones de seguridad (escape de HTML en OAuth, fórmulas en el CSV).

## 1.0.0

Primera versión pública.
