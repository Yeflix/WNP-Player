// ==UserScript==
// @name         WNP - Saltar anuncios de YouTube automaticamente
// @namespace    wnp-player
// @version      1.0.0
// @description  Pulsa por ti el boton "Saltar anuncio" de YouTube en cuanto aparece. Solo actua con anuncios que YouTube permite saltar.
// @match        https://www.youtube.com/*
// @match        https://m.youtube.com/*
// @match        https://music.youtube.com/*
// @run-at       document-idle
// @noframes
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// ==/UserScript==

/*
 * QUE HACE
 *   Cada 400 ms mira si el reproductor de YouTube esta mostrando un anuncio y,
 *   si el boton "Saltar anuncio" ya esta disponible (visible y habilitado),
 *   lo pulsa. Es exactamente el clic que harias tu.
 *
 * QUE NO HACE (a proposito)
 *   - No toca los anuncios que NO se pueden saltar: no avanza el video ni
 *     manipula el reproductor. Esos se ven completos.
 *   - No pulsa nada fuera del reproductor en modo anuncio (p. ej. el enlace
 *     "Saltar navegacion" de la pagina nunca se toca).
 *   - No hace ninguna peticion de red ni lee nada de la pagina salvo el boton.
 *
 * MENU (icono de Tampermonkey > este script)
 *   - "Alternar auto-salto"        activa / desactiva sin desinstalar.
 *   - "Ver anuncios saltados"      muestra el contador acumulado.
 *   - "Alternar mensajes de depuracion" escribe en la consola (F12) cada clic.
 *
 * Compatible con Tampermonkey y Violentmonkey (Chrome, Edge, Firefox).
 */
(function () {
  'use strict';

  var CHECK_MS = 400;        // cada cuanto se revisa la pagina
  var COOLDOWN_MS = 1500;    // tras un clic, no se vuelve a pulsar durante este tiempo

  // Botones de "Saltar anuncio" conocidos (YouTube los renombra de vez en cuando,
  // por eso hay varios y ademas un respaldo por texto, mas abajo).
  var SKIP_SELECTORS = [
    '.ytp-skip-ad-button',
    '.ytp-ad-skip-button',
    '.ytp-ad-skip-button-modern',
    '.ytp-ad-skip-button-container button',
    '.ytp-skip-ad button',
    '.videoAdUiSkipButton'
  ];
  // Texto de respaldo (es / en / pt / de / fr / it), SOLO dentro del reproductor en modo anuncio.
  // OJO: \b de JavaScript solo entiende letras ASCII (con "Ü" no hay "borde de palabra"),
  // por eso se usa un limite Unicode explicito.
  var SKIP_TEXT = /(?:^|[^\p{L}])(?:skip|saltar|omitir|pular|uberspringen|überspringen|passer|salta)(?![\p{L}])/iu;

  // ---- almacenamiento: GM_* si existe (Tampermonkey), localStorage si no -----
  function load(key, fallback) {
    try {
      if (typeof GM_getValue === 'function') return GM_getValue(key, fallback);
      var raw = window.localStorage.getItem('wnp_autoskip_' + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }
  function save(key, value) {
    try {
      if (typeof GM_setValue === 'function') GM_setValue(key, value);
      else window.localStorage.setItem('wnp_autoskip_' + key, JSON.stringify(value));
    } catch (e) { /* sin almacenamiento: el contador simplemente no persiste */ }
  }

  var enabled = load('enabled', true) !== false;
  var debug = load('debug', false) === true;
  var skipped = Number(load('skipped', 0)) || 0;
  var lastClickAt = 0;

  function log() {
    if (!debug) return;
    var args = ['[WNP auto-salto]'].concat([].slice.call(arguments));
    try { console.log.apply(console, args); } catch (e) { /* nada */ }
  }

  // ---- reglas de seguridad --------------------------------------------------
  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    var rects = el.getClientRects();
    if (!rects || rects.length === 0) return false;           // display:none (propio o de un ancestro)
    var cs = window.getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  }

  function isEnabled(el) {
    if (el.disabled) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;
    return window.getComputedStyle(el).pointerEvents !== 'none';
  }

  function isClickable(el) { return isVisible(el) && isEnabled(el); }

  // El reproductor SOLO esta en modo anuncio cuando YouTube le pone .ad-showing.
  // Camino rapido: el reproductor tiene id "movie_player" y getElementById es una
  // busqueda directa (no recorre la pagina), asi que revisar cada 400 ms sin anuncio
  // casi no cuesta nada. El selector sobre todo el documento queda de respaldo.
  function adPlayer() {
    var p = document.getElementById('movie_player');
    if (p) return p.classList.contains('ad-showing') ? p : null;
    return document.querySelector('.html5-video-player.ad-showing');
  }

  // Si el selector cae en un contenedor (div), se usa el boton que tiene dentro.
  function asButton(el) {
    if (!el) return null;
    if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') return el;
    return el.querySelector('button, [role="button"]');
  }

  function findSkipButton() {
    var player = adPlayer();
    if (!player) return null;                                  // sin anuncio: no se busca NADA

    for (var i = 0; i < SKIP_SELECTORS.length; i++) {
      var nodes = player.querySelectorAll(SKIP_SELECTORS[i]);
      for (var j = 0; j < nodes.length; j++) {
        var btn = asButton(nodes[j]);
        if (btn && isClickable(btn)) return btn;
      }
    }
    // Respaldo por texto, solo botones con texto corto dentro del reproductor.
    var buttons = player.querySelectorAll('button, [role="button"]');
    for (var k = 0; k < buttons.length; k++) {
      var b = buttons[k];
      var text = (b.textContent || '').trim();
      if (text.length > 0 && text.length <= 40 && SKIP_TEXT.test(text) && isClickable(b)) return b;
    }
    return null;
  }

  // ---- bucle principal ------------------------------------------------------
  function tick() {
    if (!enabled) return;
    try {
      var btn = findSkipButton();
      if (!btn) return;
      var now = Date.now();
      if (now - lastClickAt < COOLDOWN_MS) return;
      lastClickAt = now;
      btn.click();
      skipped += 1;
      save('skipped', skipped);
      log('anuncio saltado (total ' + skipped + ')');
    } catch (e) {
      log('error', e);                                         // un fallo aqui nunca debe romper la pagina
    }
  }

  setInterval(tick, CHECK_MS);

  // ---- menu -----------------------------------------------------------------
  if (typeof GM_registerMenuCommand === 'function') {
    GM_registerMenuCommand('Alternar auto-salto de anuncios', function () {
      enabled = !enabled;
      save('enabled', enabled);
      window.alert('Auto-salto de anuncios: ' + (enabled ? 'ACTIVADO' : 'DESACTIVADO'));
    });
    GM_registerMenuCommand('Ver anuncios saltados', function () {
      window.alert('Anuncios saltados automaticamente: ' + skipped);
    });
    GM_registerMenuCommand('Alternar mensajes de depuracion', function () {
      debug = !debug;
      save('debug', debug);
      window.alert('Mensajes de depuracion: ' + (debug ? 'ACTIVADOS (consola, F12)' : 'DESACTIVADOS'));
    });
  }
})();
