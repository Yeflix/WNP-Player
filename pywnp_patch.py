"""
Corrige un bug real de la librería `pywnp` 2.0.2 (confirmado leyendo su
código fuente) que impide controlar reproductores nativos de Windows
(por ejemplo, la app de escritorio de Spotify, rastreada vía SMTC) desde
los botones de esta app. No afecta a sitios abiertos en el navegador
(esos ya funcionaban).

Bug #1 - `pywnp/pywnp.py`, dentro de `WNPReduxNative.on_message_hook`:

    media_info = WNPReduxNative.get_media_info(
        WNPRedux.media_info._id.replace(WNPReduxNative.id_prefix)
    )

`str.replace()` necesita dos argumentos (viejo, nuevo) y aquí solo recibe
uno -> lanza TypeError. La excepción se atrapa internamente y solo se
registra en el log, así que el comando (play/pause, siguiente, buscar
posición, aleatorio, repetir...) nunca llega a ejecutarse, sin avisar
del error de forma visible.

Bug #2 - en la misma función, las llamadas a la API nativa de Windows
(`session.try_play_async()`, etc.) se hacen sin `await` y fuera de un
loop de asyncio, así que la operación asíncrona nunca se corre de verdad
(a diferencia del resto del archivo, que sí usa `asyncio.run(...)` para
este tipo de llamadas).

Bug #3 - `try_change_auto_repeat_mode_async()` y `try_change_shuffle_active_async()`
no son simples "toggles" en la API de Windows: cada una EXIGE un parámetro
con el valor exacto al que se debe cambiar (no existe una versión sin
argumentos). La `pywnp` original los llama sin ningún argumento, lo que
Windows rechaza con "Invalid parameter count". Aquí calculamos nosotros
el siguiente valor (repetir: NONE -> ALL -> ONE -> NONE, aleatorio:
invertir el valor actual) y se lo pasamos explícitamente.

Bug #4 - `WNPReduxNative.playback_info_changed_native` (la función que lee el
estado de una sesión nativa cada vez que cambia) nunca copia el valor real
de `info.is_shuffle_active` hacia `media_info.shuffle_active`. Ese campo
solo se actualiza en el camino del navegador (mensaje `SHUFFLE_ACTIVE` por
WebSocket), así que para sesiones nativas se queda para siempre en su
valor por defecto (`False`). Como nuestro toggle calcula "lo contrario de
lo que hay guardado", si siempre lee `False` siempre pide activar
aleatorio, nunca desactivarlo, y la app tampoco puede mostrar el estado
real del botón. Aquí re-implementamos esa función copiando también
`is_shuffle_active`.

Bug #5 - `MediaControls.from_json()` (usado tanto por mensajes `PLAYER_CONTROLS`
del navegador como, originalmente, por `playback_info_changed_native`)
intercambia por error los valores de `supports_skip_previous` y
`supports_skip_next` al construir el objeto final (los pasa en el orden
equivocado al constructor). Con canciones normales no se nota (casi
siempre ambos son `True`), pero en casos como la primera canción de una
cola o una emisora en vivo, el botón "anterior" aparecería habilitado
cuando no debería y viceversa. Nuestra versión nativa ya no llama a esta
función (construye `MediaControls` directo), pero el navegador sí sigue
pasando por ella cuando un sitio manda `PLAYER_CONTROLS` explícitamente
— por eso aquí también parcheamos `from_json` en sí, para cubrir ambos
caminos.

Bug #6 - `HttpServer.start()` nunca informa si el puerto elegido ya está
en uso: si falla el bind, atrapa el error en silencio y reintenta cada 5
segundos para siempre, sin lanzar excepción ni escribir en el log. Esto
lo verificamos aparte (ver `backend.py`): nuestra app ahora comprueba el
puerto por su cuenta antes de arrancar pywnp, para poder avisar de
inmediato en vez de quedarse esperando una conexión que nunca va a
llegar.

Bug #7 - En Windows, `asyncio` usa por defecto `ProactorEventLoop`, que tiene
un problema muy conocido (reportado en decenas de proyectos que usan
`aiohttp`/`asyncio` en Windows, incluyendo discusiones oficiales de
`uvicorn`): cuando un cliente se desconecta de golpe (por ejemplo, cierras
la pestaña del navegador, o el navegador se pone a dormir), el código de
limpieza de Proactor intenta cerrar un socket que el otro lado ya tumbó,
y eso genera tracebacks ruidosos en la consola tipo
`ConnectionResetError: [WinError 10054]` o incluso un `AssertionError` en
`_start_serving`. No son errores nuestros ni truenan la app (`asyncio` los
atrapa y sigue funcionando), pero ensucian la consola sin necesidad. El
arreglo estándar y documentado es usar `WindowsSelectorEventLoopPolicy` en
vez de la política por defecto — es la misma política que ya se usa en
cualquier otro sistema operativo, donde este problema no existe.

Nota sobre el volumen: `TRY_SET_VOLUME` se ignora a propósito (igual que
en la pywnp original) porque `GlobalSystemMediaTransportControlsSession`
—la API de Windows para sesiones nativas— no expone ningún control de
volumen por aplicación. No es un bug que se pueda parchear: es una
limitación real de la API. Por eso esta app deshabilita el control de
volumen automáticamente cuando el reproductor activo es una app de
escritorio (funciona normalmente con sitios del navegador).

Bug #8 - `HttpServer.web_websocket_handler` (usado por TODOS los mensajes
del navegador vía WebSocket) solo llama a `WNPRedux.update_media_info()`
—la función que decide cuál pestaña/reproductor es el "activo" a
mostrar— cuando el mensaje no es de posición Y el título de ESA conexión
ya no está vacío. En la práctica esa comparación de tipo nunca se cumple
como debería (compara contra el string `'POSITION'`, pero el mensaje real
que manda la extensión es `'POSITION_SECONDS'`), así que la condición se
reduce solo a "el título de este cliente ya no está vacío". Esto significa
que, en una conexión nueva, todo lo que llega ANTES del primer mensaje
`TITLE` (player, controles, estado, álbum, duración...) nunca dispara el
recálculo del medio activo — y con reconexiones frecuentes del lado del
navegador (cambiar de pestaña, recargar el sitio, sitios que reinician su
propio reproductor al navegar) esto se percibe como que la app "ya no
detecta" lo que suena. Parcheamos `HttpServer.update_recipients` para que
siempre recalcule el medio activo antes de enviar el estado, sin depender
de esa condición frágil. A diferencia de los bugs #1-#5, este es del lado
del NAVEGADOR (no de sesiones nativas de Windows), así que el parche se
aplica siempre, en cualquier plataforma — no solo en Windows.

Bug #9 - `WNPReduxNative.get_media_info` pisa SIEMPRE `player_name` con el
string genérico literal `'Windows Media Session'`, sin importar qué app
nativa sea en realidad (Spotify, Apple Music, Groove Music, VLC...) —
descarta por completo el AUMID (`source_app_user_model_id`) que Windows
sí le pasa como argumento. Esto rompe, entre otras cosas, el enlace de
"reabrir esta canción" de nuestra app (ver links.py): al no reconocer
"Spotify" en el nombre del reproductor, siempre caía en una búsqueda
genérica de Google en vez de abrir Spotify directamente. Como este método
se llama desde TRES manejadores de eventos distintos de Windows (cambios
de metadata, de posición y de estado — de los cuales solo el de estado
está parcheado más arriba, por el bug #4), parchear cada uno por separado
sería frágil y quedaría desactualizado si pywnp cambia alguno. En cambio,
se envuelve `get_media_info` una sola vez: después de llamar a la versión
original, se reemplaza `player_name` por un nombre legible derivado del
AUMID (con una lista de apps conocidas — Spotify, Apple Music, Groove
Music, iTunes, VLC, foobar2000, MusicBee, Winamp, AIMP, Windows Media
Player — y una extracción genérica razonable para cualquier otra). Así
cubre los tres caminos de una sola vez, sin importar cuál dispare el
cambio.

Bug #10 - `WNPReduxNative.timeline_properties_changed_native` (dispara al
registrarse una sesión nativa y cada vez que Windows informa su línea de
tiempo) calcula `position_percent = 100` cuando `duration_seconds <= 0` en
vez de `0`. Para reproductores normales esto no se nota (siempre informan
una duración real), pero varias apps de escritorio (Telegram es el caso
reportado: sus llamadas/notas de voz registran una sesión SMTC mínima,
solo con botones de reproducir/pausar/siguiente/anterior, sin metadata NI
línea de tiempo real) terminan con `duration_seconds = 0` para siempre. El
resultado visible: nuestra barra de progreso se dibujaba COMPLETAMENTE
LLENA (100%) y quedaba habilitada para arrastrar, como si la canción ya
hubiese terminado, en vez de verse vacía/deshabilitada. Que no haya
carátula ni título no es un bug nuestro ni de `pywnp` -- Windows nunca le
entrega esos datos a una sesión SMTC que no los publica, así que no hay
forma de fabricarlos de este lado (se puede confirmar independientemente
abriendo el panel "Reproduciendo ahora" propio de Windows con Telegram
sonando: se ve exactamente igual de vacío ahí también) -- pero la barra
llena SÍ es corregible: aquí se reimplementa la función calculando `0` en
vez de `100` para ese caso. `backend.py` agrega además `PlayerState.
duration_known`, que `main_window.py`/`mini_window.py` usan para no
ofrecer arrastre y mostrar "--:--" en vez de "0:00" cuando la duración es
realmente desconocida (distinto de "0:00 real, recién empezó").

Bug #11 - Ni `timeline_properties_changed_native` ni `playback_info_
changed_native` (el original de pywnp tampoco) protegen sus llamadas
`session.get_timeline_properties()` / `session.get_playback_info()` con
try/except, a diferencia de `media_properties_changed_native`, que sí
envuelve la suya. Son llamadas COM/WinRT contra el proceso dueño de la
sesión, y confirmado en un caso real (log de un usuario, sesión de
Telegram) que pueden fallar con `[WinError -2147023174] El servidor RPC
no está disponible` (RPC_S_SERVER_UNAVAILABLE) si la sesión queda
momentáneamente inalcanzable. Sin protección, esa excepción se escapa
desde un callback disparado por el propio runtime de WinRT — justo el
tipo de excepción no capturada que puede tirar abajo la app entera. Ambas
funciones quedan con su cuerpo envuelto en try/except, registrando el
error con `WNPRedux.log` (mismo patrón que ya usa `on_message_hook`) en
vez de propagarlo.

Bug #12 - Si el reproductor dueño de la sesión se cierra o se reinicia (por
ejemplo Spotify al aplicar Spicetify o al actualizarse), pywnp sigue
guardando el objeto de la sesión vieja en `win_sessions`. Cualquier orden
(play/pausa, siguiente, buscar...) contra esa sesión falla entonces con
`[WinError -2147023174] El servidor RPC no está disponible`, y como
`on_message_hook` solo lo registraba, los botones del reproductor
"dejaban de funcionar" hasta reiniciar la app. Dos causas, dos arreglos:
  a) `unregister_sessions` envuelve TODO el bucle en un solo try/except: al
     primer `remove_*` que falla con la sesión muerta aborta, y se salta el
     `win_sessions.clear()`, así que la sesión muerta queda en el diccionario
     para siempre. Se reimplementa dando de baja cada manejador por separado
     y limpiando siempre.
  b) Cuando una orden falla con ese error, se vuelven a enumerar las sesiones
     de Windows (`sessions_changed_native`) y se REINTENTA una vez con la
     sesión nueva. Si el reproductor ya no tiene sesión (se cerró de verdad),
     la orden se descarta sin ruido: es lo esperado.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time

_patched = False

# HRESULT 0x800706BA (RPC_S_SERVER_UNAVAILABLE) tal como lo muestra Python.
_RPC_UNAVAILABLE = -2147023174


def _is_rpc_unavailable(ex: BaseException) -> bool:
    """True si la excepción es "El servidor RPC no está disponible". Se mira el
    código (no el texto, que depende del idioma de Windows)."""
    codes = {_RPC_UNAVAILABLE, 0x800706BA}
    if getattr(ex, "winerror", None) in codes:
        return True
    if any(isinstance(a, int) and a in codes for a in getattr(ex, "args", ())):
        return True
    text = str(ex).lower()
    return "-2147023174" in text or "0x800706ba" in text


def _use_selector_event_loop_on_windows():
    """Corrige el bug #7: cambia a `WindowsSelectorEventLoopPolicy` para
    evitar los tracebacks ruidosos de `ProactorEventLoop` al desconectarse
    un cliente de golpe. Debe llamarse ANTES de que pywnp arranque su hilo
    con el servidor (que es cuando se crea el event loop real), para que
    ese hilo recoja esta política — la política de asyncio es global al
    proceso, no específica de un hilo, así que esto funciona aunque el
    servidor corra en otro hilo."""
    if sys.platform != "win32":
        return
    try:
        policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            asyncio.set_event_loop_policy(policy_cls())
    except Exception:
        pass  # si esto falla, seguimos con la política por defecto (con el ruido, pero sin romper nada)


# AUMID (Application User Model ID) -> nombre legible. Cubre las apps
# nativas más comunes; para cualquier otra, _friendly_player_name intenta
# extraer algo razonable del propio AUMID en vez de resignarse directo al
# genérico 'Windows Media Session' que devuelve pywnp original.
_KNOWN_AUMID_NAMES = {
    "spotify": "Spotify",
    "zunemusic": "Groove Music",
    "applemusic": "Apple Music",
    "itunes": "iTunes",
    "vlc": "VLC",
    "foobar2000": "foobar2000",
    "musicbee": "MusicBee",
    "winamp": "Winamp",
    "aimp": "AIMP",
    "wmplayer": "Windows Media Player",
    "tidal": "Tidal",
    "deezer": "Deezer",
    "soundcloud": "SoundCloud",
    "youtubemusic": "YouTube Music",
    "telegram": "Telegram",
}


def _friendly_player_name(app_user_model_id: str) -> str:
    """Ver Bug #9 en la cabecera del archivo. app_user_model_id suele ser
    algo como 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' (apps de la
    Store) o simplemente 'algo.exe' (apps de escritorio clásicas)."""
    raw = (app_user_model_id or "").lower()
    for key, friendly in _KNOWN_AUMID_NAMES.items():
        if key in raw:
            return friendly

    # Fallback genérico para apps no listadas: mejor intentar sacar algo
    # legible del AUMID que resignarse directo al string genérico.
    name = app_user_model_id or ""
    if "!" in name:
        name = name.split("!")[-1]          # después del '!' suele ser el nombre corto
    elif "_" in name:
        name = name.split("_")[0]           # antes del hash de instalación
    if name.lower().endswith(".exe"):
        name = name[:-4]                    # 'spotify.exe' -> 'spotify' (ANTES de mirar puntos)
    elif "." in name:
        name = name.rsplit(".", 1)[-1]      # 'Publisher.AppName' -> 'AppName'
    name = name.strip()
    return name or "Windows Media Session"


def _load_repeat_mode_enum():
    """`MediaPlaybackAutoRepeatMode` vive en el namespace Windows.Media (no en
    Windows.Media.Control). Se importa aparte y de forma perezosa porque solo
    existe en Windows."""
    from winsdk.windows.media import MediaPlaybackAutoRepeatMode
    return MediaPlaybackAutoRepeatMode


def _patch_media_controls_from_json(MediaControls):
    """Corrige el bug #5: reconstruye el objeto con los argumentos por
    nombre (orden correcto) en vez del `__init__(...)` posicional que
    trae la pywnp original con supports_skip_previous/next cambiados."""
    import json as _json

    @staticmethod
    def _fixed_from_json(data):
        try:
            payload = _json.loads(data) if isinstance(data, str) else dict(data)
        except Exception:
            payload = {}
        return MediaControls(
            supports_play_pause=payload.get("supports_play_pause", False),
            supports_skip_previous=payload.get("supports_skip_previous", False),
            supports_skip_next=payload.get("supports_skip_next", False),
            supports_set_position=payload.get("supports_set_position", False),
            supports_set_volume=payload.get("supports_set_volume", False),
            supports_toggle_repeat_mode=payload.get("supports_toggle_repeat_mode", False),
            supports_toggle_shuffle_active=payload.get("supports_toggle_shuffle_active", False),
            supports_set_rating=payload.get("supports_set_rating", False),
            rating_system=payload.get("rating_system", "NONE"),
        )

    MediaControls.from_json = _fixed_from_json


def _patch_httpserver_update_recipients(WNPRedux, HttpServer):
    """Corrige un bug real de detección en el navegador: `pywnp` original
    solo recalcula cuál es el medio "activo" (`WNPRedux.update_media_info()`)
    cuando el mensaje que acaba de llegar no es de posición Y el título de
    ESE cliente ya no está vacío (`type != 'POSITION' and len(media_info.title) > 0`
    en `web_websocket_handler`). Como el tipo real que manda la extensión es
    'POSITION_SECONDS' (no 'POSITION'), esa comparación siempre es cierta y
    en la práctica la condición se reduce solo a "título no vacío" — así
    que en cualquier conexión nueva, todos los mensajes que llegan ANTES del
    primer TITLE (player_name, controles, estado, álbum, duración...) nunca
    disparan el recálculo, y el estado mostrado se queda parado hasta que
    llega un mensaje más después del título. Con reconexiones frecuentes
    (cambiar de pestaña, recargar el sitio, que el sitio reinicie su propio
    reproductor) esto se nota como "no detecta lo que se está reproduciendo".
    Aquí forzamos el recálculo en cada `update_recipients()`, sin condición,
    así el estado nunca se queda desincronizado esperando el próximo mensaje."""
    original_update_recipients = HttpServer.update_recipients

    def _fixed_update_recipients() -> None:
        try:
            WNPRedux.update_media_info()
        except Exception:
            pass
        original_update_recipients()

    HttpServer.update_recipients = _fixed_update_recipients


def _apply_impl():
    """Aplica el parche. Es seguro llamarlo varias veces (no hace nada la
    segunda vez) y no falla si no estamos en Windows o si pywnp cambió su
    estructura interna en una versión más nueva."""
    global _patched
    if _patched:
        return

    # Esto va primero e incondicional: corrige el ruido de ProactorEventLoop
    # (bug #7) sin importar si el resto del parche logra aplicarse o no.
    _use_selector_event_loop_on_windows()

    try:
        import pywnp.pywnp as impl  # módulo interno real de la librería
    except Exception:
        return

    MediaControls = getattr(impl, "MediaControls", None)
    if MediaControls is not None:
        _patch_media_controls_from_json(MediaControls)

    WNPRedux = getattr(impl, "WNPRedux", None)
    HttpServer = getattr(impl, "HttpServer", None)
    if WNPRedux is not None and HttpServer is not None:
        # Este parche es del lado del NAVEGADOR (WebSocket), no de las
        # sesiones nativas de Windows: debe aplicarse SIEMPRE, en cualquier
        # plataforma. Por eso va aquí arriba, antes del check de
        # `WNPReduxNative` (que sí es exclusivo de Windows) — dejarlo
        # después de ese `return` temprano lo dejaría sin aplicar en
        # Mac/Linux, que es justo donde no hay ruta alternativa (SMTC) para
        # detectar nada, así que este parche es aún MÁS importante ahí.
        _patch_httpserver_update_recipients(WNPRedux, HttpServer)

    _time_in_seconds_to_string = getattr(impl, "time_in_seconds_to_string", None)
    if _time_in_seconds_to_string is None:
        # pywnp renombró/quitó el helper: se usa uno propio equivalente.
        def _time_in_seconds_to_string(seconds):
            seconds = max(0, int(seconds or 0))
            h, rem = divmod(seconds, 3600)
            m, sec = divmod(rem, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    native = getattr(impl, "WNPReduxNative", None)
    if native is None:
        # No estamos en Windows (la clase solo existe ahí) o la librería
        # cambió de estructura: no hay más que parchear (lo del navegador
        # ya quedó corregido arriba, y funciona en cualquier plataforma).
        _patched = True
        return

    # Bug #9: se envuelve UNA sola vez, antes que cualquier otro parche
    # nativo — así los tres manejadores de eventos (metadata, posición y
    # estado) quedan cubiertos sin tener que reimplementar los dos que no
    # tocamos explícitamente (solo el de estado se reemplaza más abajo).
    _original_get_media_info = native.get_media_info

    @staticmethod
    def _patched_get_media_info(app_id: str):
        media_info = _original_get_media_info(app_id)
        media_info.player_name = _friendly_player_name(app_id)
        return media_info

    native.get_media_info = _patched_get_media_info

    try:
        RepeatMode = _load_repeat_mode_enum()
    except Exception:
        RepeatMode = None

    def _next_repeat_mode(current: str):
        # Ciclo: apagado -> repetir todo -> repetir una -> apagado
        # (mismo orden que usa Spotify en su propia interfaz).
        order = {"NONE": "ALL", "ALL": "ONE", "ONE": "NONE"}
        target = order.get(current, "ALL")
        if RepeatMode is None:
            return None
        mapping = {"NONE": RepeatMode.NONE, "ONE": RepeatMode.TRACK, "ALL": RepeatMode.LIST}
        return mapping.get(target)

    @staticmethod
    def _fixed_timeline_properties_changed_native(session, e) -> None:
        """Corrige el bug #10: cuando la sesión nunca informó una duración
        real (`duration_seconds <= 0`, típico de Telegram y otras apps con
        una integración SMTC mínima), deja `position_percent` en 0 en vez
        del 100 que calcula la pywnp original -- así la barra de progreso
        no se dibuja engañosamente llena/"terminada".

        Bug #11 (agregado tras un reporte real en Windows): `session.
        get_timeline_properties()` es una llamada COM/WinRT contra el
        proceso dueño de la sesión, y esa llamada puede fallar con
        `[WinError -2147023174] El servidor RPC no está disponible`
        (RPC_S_SERVER_UNAVAILABLE) si la sesión quedó momentáneamente
        inalcanzable -- confirmado que pasa de verdad con sesiones nativas
        poco convencionales como la de Telegram. La pywnp original NUNCA
        protege esta llamada (se revisó su código fuente: ni acá ni en
        `playback_info_changed_native` hay try/except, a diferencia de
        `media_properties_changed_native`, que sí envuelve la suya). Sin
        protección, una excepción acá se escapa desde un callback disparado
        por el propio runtime de WinRT -- exactamente el tipo de excepción
        no capturada que puede tirar abajo la app. Se envuelve todo el
        cuerpo y, si falla, se deja media_info como estaba (no se pisa con
        datos a medio construir) en vez de propagar el error."""
        try:
            info = session.get_timeline_properties()
            media_info = native.get_media_info(session.source_app_user_model_id)

            media_info.duration_seconds = int(info.end_time.total_seconds())
            media_info.duration = _time_in_seconds_to_string(media_info.duration_seconds)

            native.last_position_seconds = int(info.position.total_seconds())
            media_info.position_seconds = native.last_position_seconds
            media_info.position = _time_in_seconds_to_string(media_info.position_seconds)

            if media_info.duration_seconds > 0:
                media_info.position_percent = (media_info.position_seconds / media_info.duration_seconds) * 100
            else:
                # --- la corrección del bug #10: 0, no 100 ---
                media_info.position_percent = 0

            WNPRedux.update_media_info()
            HttpServer.update_recipients()
        except Exception as ex:  # noqa: BLE001 — ver Bug #11 arriba
            WNPRedux.log("Error", "WNPReduxNative - Failed to read timeline properties (parche)")
            WNPRedux.log("Debug", f"WNPReduxNative - Error Trace: {ex}")

    @staticmethod
    def _fixed_playback_info_changed_native(session, e) -> None:
        """Ver Bug #11 en _fixed_timeline_properties_changed_native: la
        misma protección hacía falta acá, `session.get_playback_info()` es
        la misma clase de llamada COM/WinRT y puede fallar exactamente
        igual (RPC_S_SERVER_UNAVAILABLE) con una sesión inalcanzable."""
        try:
            info = session.get_playback_info()
            media_info = native.get_media_info(session.source_app_user_model_id)

            # Construimos MediaControls directamente (con argumentos por
            # nombre) en vez de pasar por MediaControls.from_json(), que
            # intercambia supports_skip_previous <-> supports_skip_next
            # (ver bug #5 arriba).
            media_info.controls = MediaControls(
                supports_play_pause=info.controls.is_play_pause_toggle_enabled,
                supports_skip_previous=info.controls.is_previous_enabled,
                supports_skip_next=info.controls.is_next_enabled,
                supports_set_position=info.controls.is_playback_position_enabled,
                supports_set_volume=False,
                supports_toggle_repeat_mode=info.controls.is_repeat_enabled,
                supports_toggle_shuffle_active=info.controls.is_shuffle_enabled,
                supports_set_rating=False,
                rating_system="NONE",
            )

            repeat_mode = "NONE"
            if info.auto_repeat_mode is not None:
                if info.auto_repeat_mode.value == 1:
                    repeat_mode = "ONE"
                elif info.auto_repeat_mode.value == 2:
                    repeat_mode = "ALL"

            state = "STOPPED"
            if info.playback_status is not None:
                state = "PLAYING" if info.playback_status.value == 4 else "PAUSED"

            media_info.state = state
            media_info.repeat_mode = repeat_mode
            # --- la corrección: pywnp original nunca hace esta asignación ---
            media_info.shuffle_active = bool(info.is_shuffle_active or False)
            WNPRedux.update_media_info()
            HttpServer.update_recipients()
        except Exception as ex:  # noqa: BLE001 — ver Bug #11 arriba
            WNPRedux.log("Error", "WNPReduxNative - Failed to read playback info (parche)")
            WNPRedux.log("Debug", f"WNPReduxNative - Error Trace: {ex}")

    _refresh_lock = threading.Lock()
    _last_refresh = [0.0]

    def _refresh_native_sessions() -> bool:
        """Vuelve a enumerar las sesiones de Windows (lo que pywnp solo hace
        cuando Windows avisa de un cambio). Varios hilos pueden pedirlo a la
        vez: el segundo reutiliza el resultado del primero (ventana de 1.5 s)."""
        with _refresh_lock:
            if time.monotonic() - _last_refresh[0] < 1.5:
                return True
            _last_refresh[0] = time.monotonic()
            manager = native.manager
            if manager is None:
                return False
            try:
                native.pool.submit(native.sessions_changed_native, manager, None).result(timeout=5)
                return True
            except Exception as ex:  # noqa: BLE001
                WNPRedux.log("Debug", f"WNPNativeWindows - No se pudieron renovar las sesiones: {ex}")
                return False

    async def _execute(session, msg_type: str, data: str) -> None:
        if msg_type == "TRY_SET_STATE":
            if data == "PLAYING":
                await session.try_play_async()
            else:
                await session.try_pause_async()
        elif msg_type == "TRY_SKIP_PREVIOUS":
            await session.try_skip_previous_async()
        elif msg_type == "TRY_SKIP_NEXT":
            await session.try_skip_next_async()
        elif msg_type == "TRY_SET_POSITION":
            position_100ns = int(data.split(":")[0]) * 10_000_000
            await session.try_change_playback_position_async(position_100ns)
        elif msg_type == "TRY_TOGGLE_REPEAT_MODE":
            next_mode = _next_repeat_mode(WNPRedux.media_info.repeat_mode)
            if next_mode is not None:
                await session.try_change_auto_repeat_mode_async(next_mode)
        elif msg_type == "TRY_TOGGLE_SHUFFLE_ACTIVE":
            new_value = not WNPRedux.media_info.shuffle_active
            await session.try_change_shuffle_active_async(new_value)
        # TRY_SET_VOLUME / TRY_SET_RATING: la API nativa de Windows
        # no los soporta (igual que en el original de pywnp).

    @staticmethod
    def _fixed_unregister_sessions() -> None:
        # Bug #12a: cada baja por separado y limpiar SIEMPRE (el original aborta
        # en la primera sesión muerta y deja `win_sessions` con entradas viejas).
        for win_session in list(native.win_sessions.values()):
            for name, token in (
                ("remove_media_properties_changed", win_session.media_properties_changed_token),
                ("remove_playback_info_changed", win_session.playback_info_changed_token),
                ("remove_timeline_properties_changed", win_session.timeline_properties_changed_token),
            ):
                try:
                    getattr(win_session.session, name)(token)
                except Exception:  # noqa: BLE001 — sesión muerta: ya no hay nada que dar de baja
                    pass
        native.win_sessions.clear()

    @staticmethod
    def _fixed_on_message_hook(message: str) -> None:
        if not WNPRedux.media_info._id.startswith(native.id_prefix):
            return
        try:
            app_id = WNPRedux.media_info._id.replace(native.id_prefix, "")
            native.get_media_info(app_id)
            if app_id not in native.win_sessions:
                return

            try:
                msg_type = message[: message.index(" ")].upper()
                data = message[message.index(" ") + 1 :]
            except ValueError:
                msg_type = message.upper()
                data = ""

            def _submit(session) -> None:
                native.pool.submit(asyncio.run, _execute(session, msg_type, data)).result(timeout=5)

            try:
                _submit(native.win_sessions[app_id].session)
            except Exception as ex:  # noqa: BLE001
                if not _is_rpc_unavailable(ex):
                    raise
                # Bug #12b: la sesión guardada ya no responde (el reproductor se
                # cerró o se reinició). Se renuevan las sesiones y se reintenta UNA vez.
                WNPRedux.log("Debug", "WNPNativeWindows - Sesión inalcanzable; renovando sesiones y reintentando (parche)")
                _refresh_native_sessions()
                fresh = native.win_sessions.get(app_id)
                if fresh is None:
                    WNPRedux.log("Debug", f"WNPNativeWindows - {app_id} ya no tiene sesión (¿se cerró?); orden descartada (parche)")
                    return
                _submit(fresh.session)
        except Exception as ex:  # noqa: BLE001
            WNPRedux.log("Error", "WNPNativeWindows - Failed to execute event (parche)")
            WNPRedux.log("Debug", f"WNPNativeWindows - Error Trace: {ex}")

    # Reemplazamos los métodos en la clase ANTES de que WNPRedux.start() los
    # use: `on_message_hook` se copia hacia HttpServer.on_message_hook, y
    # `playback_info_changed_native` se registra como listener por cada
    # sesión dentro de sessions_changed_native(). En ambos casos el orden
    # importa: este parche debe aplicarse antes de start().
    native.on_message_hook = _fixed_on_message_hook
    native.unregister_sessions = _fixed_unregister_sessions
    native.playback_info_changed_native = _fixed_playback_info_changed_native
    native.timeline_properties_changed_native = _fixed_timeline_properties_changed_native
    _patched = True


def apply():
    """Envoltorio seguro de `_apply_impl`: si pywnp cambió algo interno y un
    parche falla, se registra el aviso y la app SIGUE arrancando (los parches
    ya aplicados quedan; antes la excepción impedía iniciar el servidor)."""
    global _patched
    if _patched:
        return
    try:
        _apply_impl()
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[pywnp_patch] parche parcial: {type(exc).__name__}: {exc}", file=sys.stderr)
        _patched = True   # evita volver a envolver las mismas funciones dos veces
