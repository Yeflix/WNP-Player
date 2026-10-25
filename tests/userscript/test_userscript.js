// Pruebas de tools/youtube_saltar_anuncios.user.js contra una página YouTube SIMULADA (jsdom).
//   cd tests/userscript && npm install && npm test
const { JSDOM, VirtualConsole } = require('jsdom');
const fs = require('fs');
const path = require('path');

const SCRIPT = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'youtube_saltar_anuncios.user.js'), 'utf8');
const results = [];
function check(name, cond, extra) {
  results.push(!!cond);
  console.log((cond ? '  OK   ' : '  FALLA') + ' ' + name + (extra ? ' ' + extra : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// jsdom no calcula layout: se simula "visible" = ni él ni sus ancestros tienen display:none / visibility:hidden.
function hiddenByStyle(el, w) {
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const cs = w.getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden') return true;
  }
  return false;
}

function makeEnv(bodyHtml, opts = {}) {
  const dom = new JSDOM('<!doctype html><html><body>' + bodyHtml + '</body></html>',
    { runScripts: 'outside-only', pretendToBeVisual: true, url: 'https://www.youtube.com/watch?v=abc', virtualConsole: new VirtualConsole() });
  const w = dom.window;
  w.HTMLElement.prototype.getClientRects = function () { return hiddenByStyle(this, w) ? [] : [{ width: 90, height: 28 }]; };
  const store = Object.assign({ enabled: true, skipped: 0 }, opts.store || {});
  const menu = [], alerts = [];
  if (!opts.noGM) {
    w.GM_getValue = (k, d) => (k in store ? store[k] : d);
    w.GM_setValue = (k, v) => { store[k] = v; };
    w.GM_registerMenuCommand = (name, fn) => menu.push({ name, fn });
  }
  w.alert = (m) => alerts.push(m);
  w.eval(SCRIPT);
  return { w, doc: w.document, store, menu, alerts, close: () => w.close() };
}

// Cuenta clics reales sobre un elemento.
function spy(el) { const c = { n: 0 }; el.addEventListener('click', () => { c.n++; }); return c; }
const AD_PLAYER = (inner) => '<div id="movie_player" class="html5-video-player ad-showing">' + inner + '</div>';
const NO_AD_PLAYER = (inner) => '<div id="movie_player" class="html5-video-player">' + inner + '</div>';

(async () => {
  console.log('== Casos que SÍ debe saltar');
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip">Saltar anuncio</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('anuncio saltable con el botón actual (.ytp-skip-ad-button) -> 1 clic', c.n === 1, 'clics=' + c.n);
    check('el contador persiste (GM_setValue)', e.store.skipped === 1, String(e.store.skipped));
    await sleep(2200);
    check('sigue siendo UN solo clic mientras el botón siga ahí (cooldown), no ametralla', spy(e.doc.getElementById('skip')).n === 0 && c.n <= 2, 'clics=' + c.n);
    e.close();
  }
  for (const [label, html] of [
    ['clase antigua .ytp-ad-skip-button', '<button class="ytp-ad-skip-button" id="skip">Skip</button>'],
    ['clase moderna .ytp-ad-skip-button-modern', '<button class="ytp-ad-skip-button-modern" id="skip">Skip</button>'],
    ['contenedor con el botón dentro (.ytp-skip-ad > button)', '<div class="ytp-skip-ad"><button id="skip">Skip</button></div>'],
    ['contenedor .ytp-ad-skip-button-container', '<div class="ytp-ad-skip-button-container"><button id="skip">Skip</button></div>'],
  ]) {
    const e = makeEnv(AD_PLAYER(html)); const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check(label + ' -> 1 clic', c.n === 1, 'clics=' + c.n); e.close();
  }
  for (const text of ['Saltar anuncio', 'Skip ads', 'Omitir anuncios', 'Pular anúncio', 'Überspringen', 'Passer']) {
    const e = makeEnv(AD_PLAYER('<button class="clase-nueva-desconocida" id="skip">' + text + '</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('respaldo por texto "' + text + '" (clase desconocida) -> 1 clic', c.n === 1, 'clics=' + c.n); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<div class="ytp-ad-preview-container">Podrás saltar en 5</div>'));
    await sleep(500);
    const late = e.doc.createElement('button'); late.className = 'ytp-skip-ad-button'; late.textContent = 'Saltar anuncio';
    const c = spy(late); e.doc.getElementById('movie_player').appendChild(late); await sleep(900);
    check('el botón aparece DESPUÉS de la cuenta atrás -> se pulsa al aparecer', c.n === 1, 'clics=' + c.n); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<div class="ytp-ad-skip-button-slot" style="display:none"><button class="ytp-skip-ad-button" id="skip">Skip</button></div>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('botón en el DOM pero oculto (display:none en el contenedor) -> NO se pulsa todavía', c.n === 0, 'clics=' + c.n);
    e.doc.querySelector('.ytp-ad-skip-button-slot').style.display = ''; await sleep(900);
    check('...y se pulsa cuando el contenedor se muestra', c.n === 1, 'clics=' + c.n); e.close();
  }

  console.log('== Casos que NO debe tocar (seguridad)');
  {
    const e = makeEnv(NO_AD_PLAYER('<button class="ytp-skip-ad-button" id="skip">Saltar anuncio</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('SIN anuncio (el reproductor no tiene .ad-showing) no pulsa nada, aunque haya un botón así', c.n === 0, 'clics=' + c.n); e.close();
  }
  {
    const e = makeEnv('<a id="skip-navigation" href="#">Saltar navegación</a><button id="otro">Skip intro</button>' +
      AD_PLAYER('<div class="ytp-ad-preview-container">El anuncio terminará pronto</div>'));
    const a = spy(e.doc.getElementById('skip-navigation')), b = spy(e.doc.getElementById('otro')); await sleep(900);
    check('anuncio SIN botón de saltar (no saltable): no pulsa nada y no rompe', a.n === 0 && b.n === 0);
    check('enlaces "Saltar navegación" / "Skip intro" FUERA del reproductor jamás se tocan', a.n === 0 && b.n === 0); e.close();
  }
  {
    const e = makeEnv('<button id="fuera" class="ytp-skip-ad-button">Skip</button>' + AD_PLAYER('<span>anuncio</span>'));
    const c = spy(e.doc.getElementById('fuera')); await sleep(900);
    check('un botón con clase de salto pero FUERA del reproductor en modo anuncio no se pulsa', c.n === 0); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip" disabled>Saltar anuncio</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('botón con atributo disabled -> no se pulsa', c.n === 0); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip" aria-disabled="true">Saltar anuncio</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('botón con aria-disabled="true" -> no se pulsa', c.n === 0); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip" style="visibility:hidden">Saltar anuncio</button>'));
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('botón con visibility:hidden -> no se pulsa', c.n === 0); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button id="x">Saltar a la parte favorita del video con un texto larguísimo que supera con creces el límite</button>'));
    const c = spy(e.doc.getElementById('x')); await sleep(900);
    check('respaldo por texto ignora textos largos (no es un botón de saltar)', c.n === 0); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button id="x">Reproducir</button><button id="y">Más información</button>'));
    const a = spy(e.doc.getElementById('x')), b = spy(e.doc.getElementById('y')); await sleep(900);
    check('otros botones del anuncio (Reproducir, Más información) no se tocan', a.n === 0 && b.n === 0); e.close();
  }

  console.log('== Interruptor y menú');
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip">Saltar anuncio</button>'), { store: { enabled: false } });
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('arranca desactivado si así quedó guardado -> no pulsa', c.n === 0); 
    e.menu.find((m) => /Alternar auto-salto/.test(m.name)).fn(); await sleep(900);
    check('el menú lo activa -> pulsa', c.n === 1, 'clics=' + c.n);
    check('y avisa del estado', e.alerts.some((a) => /ACTIVADO/.test(a)), JSON.stringify(e.alerts));
    check('y guarda el estado', e.store.enabled === true); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<span>anuncio</span>'), { store: { skipped: 7 } });
    e.menu.find((m) => /Ver anuncios saltados/.test(m.name)).fn();
    check('el menú muestra el contador acumulado', e.alerts.some((a) => /7/.test(a)), JSON.stringify(e.alerts));
    check('registra los 3 comandos de menú', e.menu.length === 3, String(e.menu.map((m) => m.name))); e.close();
  }

  console.log('== Robustez');
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip">Saltar</button>'), { noGM: true });
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('sin APIs GM_* (otro gestor de scripts) funciona con localStorage', c.n === 1 && e.w.localStorage.getItem('wnp_autoskip_skipped') === '1',
      'clics=' + c.n + ' ls=' + e.w.localStorage.getItem('wnp_autoskip_skipped')); e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<button class="ytp-skip-ad-button" id="skip">Saltar</button>'));
    const el = e.doc.getElementById('skip'); el.addEventListener('click', () => { throw new Error('boom'); });
    const c = spy(el); await sleep(2300);
    check('si un manejador de la página lanza error, el script sigue vivo (no se rompe el bucle)', c.n >= 1);
    e.close();
  }
  {
    const e = makeEnv(AD_PLAYER('<span id="vacio">anuncio</span>'));
    await sleep(500);
    const b = e.doc.createElement('button'); b.className = 'ytp-skip-ad-button'; b.textContent = 'Skip'; const c = spy(b);
    e.doc.getElementById('movie_player').appendChild(b); await sleep(900);
    check('un anuncio posterior en la misma página (YouTube es una SPA) también se salta', c.n === 1); e.close();
  }
  {
    // Rendimiento: en vez de medir tiempos en jsdom (mucho más lento que un navegador, no significa nada),
    // se comprueba de forma determinista que SIN anuncio la revisión no recorre el documento.
    const many = Array.from({ length: 20000 }, (_, i) => '<div class="x' + (i % 50) + '"><span>n' + i + '</span></div>').join('');
    const dom = new JSDOM('<!doctype html><body>' + many + NO_AD_PLAYER('<span>video</span>') + '</body>',
      { runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: new VirtualConsole() });
    const w = dom.window; let scans = 0;
    for (const m of ['querySelector', 'querySelectorAll']) {
      const orig = w.document[m].bind(w.document);
      w.document[m] = function () { scans++; return orig.apply(null, arguments); };
    }
    w.GM_getValue = (k, d) => d; w.GM_setValue = () => {}; w.alert = () => {};
    w.eval(SCRIPT); await sleep(1300);                                  // ~3 revisiones
    check('SIN anuncio la revisión usa solo getElementById: 0 búsquedas sobre el documento (20.000 nodos)', scans === 0, 'búsquedas=' + scans);
    w.close();
  }
  {
    // Si por algún motivo no existe #movie_player, el respaldo sigue encontrando el anuncio.
    const e = makeEnv('<div class="html5-video-player ad-showing"><button class="ytp-skip-ad-button" id="skip">Skip</button></div>');
    const c = spy(e.doc.getElementById('skip')); await sleep(900);
    check('respaldo: sin #movie_player, el selector por clase sigue encontrando el anuncio', c.n === 1, 'clics=' + c.n); e.close();
  }

  const ok = results.filter(Boolean).length, bad = results.length - ok;
  console.log('\nRESULTADO: ' + ok + ' ok, ' + bad + ' fallas');
  process.exit(bad ? 1 : 0);
})();
