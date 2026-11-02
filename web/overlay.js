'use strict';
/* mania-overlay page: reads tosu's websocket, draws widgets, hosts the edit UI. */

const DEMO = new URLSearchParams(location.search).has('demo');

// tosu GameState numbers
const ST = { menu: 0, edit: 1, play: 2, selectEdit: 4, selectPlay: 5, selectDrank: 6, results: 7, selectMulti: 13 };
const SELECT_STATES = [ST.selectEdit, ST.selectPlay, ST.selectDrank, ST.selectMulti];

const SHOW_IN = [
  ['always', 'Always'],
  ['playing', 'While playing'],
  ['playing+results', 'Playing + results'],
  ['select', 'Song select'],
  ['notplaying', 'When not playing'],
  ['results', 'Results screen'],
];

let S = null;            // settings from the Python side
let NATIVE_ANALYSER = false;   // the GTK host draws the MSD panel itself
let edit = false;
let selectedId = null;
const live = { connected: false, data: null, hitErrors: [] };

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v, d = 0) => (Number.isFinite(+v) ? (+v).toFixed(d) : '0');
const fmtRate = (r) => (+r).toFixed(2).replace(/0+$/, '').replace(/\.$/, '');

async function api(path, body) {
  const opts = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  return res.json();
}

let saveTimer = null;
function saveSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api('/api/settings', S).catch(() => {}), 300);
}

// ------------------------------------------------------------------ data access
function stateNum(d) { return d?.state?.number ?? -1; }

function hitsOf(src) {
  const h = src?.hits || {};
  return { max: h.geki | 0, 300: h['300'] | 0, 200: h.katu | 0, 100: h['100'] | 0, 50: h['50'] | 0, miss: h['0'] | 0 };
}

function sampleData() {
  return {
    state: { number: ST.play },
    play: {
      hits: { geki: 1532, 300: 214, katu: 31, 100: 6, 50: 2, 0: 3 },
      accuracy: 97.84, combo: { current: 812, max: 1203 }, pp: { current: 412.6, fc: 455.1 },
      unstableRate: 92.4, mods: { name: 'NM', rate: 1 },
    },
    beatmap: {
      artist: 'Artist', title: 'Example Song', version: 'Insane 1.1x', mapper: 'mapper',
      stats: { stars: { total: 5.42 }, od: { original: 8 }, cs: { original: 4 }, bpm: { common: 200 } },
    },
    performance: { accuracy: { 100: 520.3 } },
  };
}

// What a widget should render from: live data, or a sample in edit mode when nothing is live.
function dataFor(showIn) {
  const d = live.data;
  if (edit && (!d || !visibleIn(showIn, stateNum(d)))) return sampleData();
  return d || sampleData();
}

function visibleIn(showIn, st) {
  switch (showIn) {
    case 'always': return true;
    case 'playing': return st === ST.play;
    case 'playing+results': return st === ST.play || st === ST.results;
    case 'select': return SELECT_STATES.includes(st);
    case 'results': return st === ST.results;
    case 'notplaying': return st !== ST.play;
    default: return true;
  }
}

function odWindows(od) {
  // osu!stable mania hit windows (ms, one side)
  return { max: 16, 300: 64 - 3 * od, 200: 97 - 3 * od, 100: 127 - 3 * od, 50: 151 - 3 * od };
}

// ------------------------------------------------------------------ widget definitions
const WIDGETS = {
  judgements: {
    label: 'Judgements',
    options: [
      { key: 'layout', type: 'select', label: 'Layout', choices: [['rows', 'Rows'], ['compact', 'One line']] },
      { key: 'showRatios', type: 'bool', label: 'MA / PA ratios' },
      { key: 'showBadge', type: 'bool', label: 'MA / PFC / FC badge' },
    ],
    render(root, cfg, d) {
      const results = stateNum(d) === ST.results && d.resultsScreen;
      const h = hitsOf(results ? d.resultsScreen : d.play);
      const rows = [['max', 'MAX'], ['300', '300'], ['200', '200'], ['100', '100'], ['50', '50'], ['miss', 'MISS']];
      let html = '';
      if (cfg.layout === 'compact') {
        html = `<div class="judge-line">${rows.map(([k]) => `<span class="j-${k}">${h[k]}</span>`).join('<span class="muted">/</span>')}</div>`;
      } else {
        html = `<div class="judge-rows">${rows.map(([k, l]) => `<span class="lbl j-${k}">${l}</span><span class="val j-${k}">${h[k]}</span>`).join('')}</div>`;
      }
      const ratio = (a, b) => (b ? (a / b).toFixed(2) + ':1' : a ? '∞' : '—');
      const total = h.max + h[300] + h[200] + h[100] + h[50] + h.miss;
      let badge = '', cls = '';
      if (total > 0 && h.miss === 0) {
        if (h[300] + h[200] + h[100] + h[50] === 0) { badge = 'MA'; cls = 'ma'; }
        else if (h[200] + h[100] + h[50] === 0) { badge = 'PFC'; cls = 'pfc'; }
        else { badge = 'FC'; cls = 'fc'; }
      }
      if (cfg.showRatios || cfg.showBadge) {
        html += `<div class="judge-foot">${cfg.showRatios ? `<span>MA ${ratio(h.max, h[300])} · PA ${ratio(h[300], h[200])}</span>` : '<span></span>'}` +
          `${cfg.showBadge ? `<span class="badge ${cls}">${badge}</span>` : ''}</div>`;
      }
      root.className = 'card';
      root.innerHTML = html;
    },
  },

  pp: {
    label: 'PP',
    options: [
      { key: 'showFc', type: 'bool', label: 'Show FC / SS pp' },
      { key: 'decimals', type: 'range', label: 'Decimals', min: 0, max: 2, step: 1 },
    ],
    render(root, cfg, d) {
      const st = stateNum(d);
      const dec = cfg.decimals | 0;
      let main, sub = '';
      if (st === ST.results && d.resultsScreen) {
        main = d.resultsScreen.pp?.current;
        if (cfg.showFc) sub = `FC ${num(d.resultsScreen.pp?.fc, dec)}pp`;
      } else if (st === ST.play) {
        main = d.play?.pp?.current;
        if (cfg.showFc) sub = `FC ${num(d.play?.pp?.fc, dec)}pp`;
      } else {
        main = d.performance?.accuracy?.['100'] ?? d.play?.pp?.current;
        sub = 'SS';
      }
      root.className = 'card';
      root.innerHTML = `<div class="pp-main">${num(main, dec)}<small>pp</small></div>${sub ? `<div class="pp-sub">${sub}</div>` : ''}`;
    },
  },

  stats: {
    label: 'Accuracy / combo',
    options: [
      { key: 'showAcc', type: 'bool', label: 'Accuracy' },
      { key: 'showCombo', type: 'bool', label: 'Combo' },
    ],
    render(root, cfg, d) {
      const src = stateNum(d) === ST.results && d.resultsScreen ? d.resultsScreen : d.play || {};
      const combo = src.combo?.current ?? src.maxCombo ?? 0;
      const max = src.combo?.max ?? src.maxCombo ?? 0;
      const parts = [];
      if (cfg.showAcc) parts.push(`<span>${num(src.accuracy, 2)}%</span>`);
      if (cfg.showCombo) parts.push(`<span>${combo}x <span class="muted">/ ${max}x</span></span>`);
      root.className = 'card';
      root.innerHTML = `<div class="stats">${parts.join('')}</div>`;
    },
  },

  ur: {
    label: 'UR / hit error',
    options: [
      { key: 'showBar', type: 'bool', label: 'Hit error bar' },
      { key: 'barWidth', type: 'range', label: 'Bar width', min: 150, max: 900, step: 10 },
      { key: 'barHistory', type: 'range', label: 'Ticks shown', min: 10, max: 120, step: 5 },
    ],
    render(root, cfg, d) {
      const errs = edit && !live.hitErrors.length ? demoErrors() : live.hitErrors;
      let ur = d.play?.unstableRate;
      if (!Number.isFinite(ur) && errs.length > 1) {
        const mean = errs.reduce((a, b) => a + b, 0) / errs.length;
        ur = Math.sqrt(errs.reduce((a, b) => a + (b - mean) ** 2, 0) / errs.length) * 10;
      }
      const w = cfg.barWidth | 0;
      let html = `<div class="ur-num"><span>UR</span>${num(ur, 2)}</div>`;
      if (cfg.showBar) {
        const od = +(d.beatmap?.stats?.od?.converted ?? d.beatmap?.stats?.od?.original ?? 8);
        const win = odWindows(od);
        const range = win[50];
        const x = (ms) => Math.max(0, Math.min(w, w / 2 + (ms / range) * (w / 2)));
        const zones = [[50, 'var(--c-50)'], [100, 'var(--c-100)'], [200, 'var(--c-200)'], [300, 'var(--c-300)'], ['max', 'var(--c-max)']]
          .map(([k, c]) => `<div class="zone" style="left:${x(-win[k])}px;width:${x(win[k]) - x(-win[k])}px;background:${c}"></div>`).join('');
        const recent = errs.slice(-(cfg.barHistory | 0));
        const ticks = recent.map((e, i) => {
          const a = Math.abs(e);
          const c = a <= win.max ? 'var(--c-max)' : a <= win[300] ? 'var(--c-300)' : a <= win[200] ? 'var(--c-200)' : a <= win[100] ? 'var(--c-100)' : 'var(--c-50)';
          return `<div class="tick" style="left:${x(e)}px;background:${c};opacity:${(0.25 + 0.75 * (i + 1) / recent.length).toFixed(2)}"></div>`;
        }).join('');
        const avg = recent.length ? recent.reduce((a, b) => a + b, 0) / recent.length : 0;
        html += `<div class="ur-bar" style="width:${w}px">${zones}<div class="mid"></div>${ticks}<div class="avg" style="left:${x(avg)}px"></div></div>`;
      }
      root.className = 'card';
      root.innerHTML = html;
    },
  },

  mapinfo: {
    label: 'Map info',
    options: [],
    render(root, cfg, d) {
      const b = d.beatmap || {};
      const st = b.stats || {};
      const rate = d.play?.mods?.rate;
      const keys = st.cs?.original;
      root.className = 'card mapinfo';
      root.innerHTML = `<div class="title">${esc(b.artist)} - ${esc(b.title)} <span class="muted">[${esc(b.version)}]</span></div>
        <div class="meta">${keys ? `<span>${keys}K</span>` : ''}<span>★ ${num(st.stars?.total, 2)}</span>
        <span>${num(st.bpm?.common ?? st.bpm?.realtime)} BPM</span>
        ${rate && Math.abs(rate - 1) > 0.001 ? `<span class="rate">${fmtRate(rate)}x</span>` : ''}
        <span class="muted">${esc(b.mapper)}</span></div>`;
    },
  },

  analyser: {
    label: 'MSD / Dan (ManiaMapAnalyser)',
    options: [
      { key: 'width', type: 'range', label: 'Width', min: 300, max: 1000, step: 10 },
      { key: 'height', type: 'range', label: 'Height', min: 200, max: 1200, step: 10 },
    ],
    // The analyser is its own tosu counter. In the overlay app the host draws it
    // with a separate WebView at real zoom (sharp text); this widget is then just
    // a placeholder that tells the host where to put it. In a plain browser
    // preview it falls back to a CSS-scaled iframe.
    // The native view sits above the whole page, so while the editor is open
    // (where it would cover the settings panel) we show an in-page iframe
    // preview instead, and the native view is hidden.
    mount(root) {
      root.className = 'analyser';
      root.innerHTML = '<div class="analyser-slot"><span class="small muted">MSD panel shows here when tosu is connected</span></div>' +
        '<iframe hidden></iframe><div class="shield"></div>';
    },
    render(root, cfg) {
      const src = analyserSrc();
      const slot = root.querySelector('.analyser-slot');
      const frame = root.querySelector('iframe');
      const useFrame = !NATIVE_ANALYSER || edit;
      slot.hidden = useFrame && live.connected;
      frame.hidden = !(useFrame && live.connected);
      for (const e of [slot, frame]) { e.style.width = cfg.width + 'px'; e.style.height = cfg.height + 'px'; }
      slot.classList.toggle('waiting', !live.connected);
      if (!useFrame) {
        // unload the preview so only one copy of the analyser runs
        if (frame.dataset.src) { frame.removeAttribute('src'); delete frame.dataset.src; }
        return;
      }
      if (frame.dataset.src !== src || frame.dataset.gen !== String(connectGen)) {
        frame.dataset.src = src;
        frame.dataset.gen = String(connectGen);
        if (live.connected) frame.src = src;
      }
    },
  },
};

function analyserSrc() {
  const folder = S.general.analyserCounter.split('/').map(encodeURIComponent).join('/');
  return `http://${S.general.tosuHost}/${folder}/index.html`;
}

// Tell the host where to draw the native analyser view (only when something changed).
let lastAnalyserSpec = '';
let analyserVisible = false;
function syncAnalyser() {
  if (!NATIVE_ANALYSER || !S) return;
  const cfg = S.widgets.analyser;
  const spec = {
    visible: analyserVisible && live.connected && !edit && !menu,
    x: Math.round(cfg.x), y: Math.round(cfg.y),
    width: cfg.width, height: cfg.height, zoom: cfg.scale, opacity: cfg.opacity,
    src: analyserSrc(), gen: connectGen,
  };
  const key = JSON.stringify(spec);
  if (key === lastAnalyserSpec) return;
  lastAnalyserSpec = key;
  api('/api/analyser', spec).catch(() => { lastAnalyserSpec = ''; });
}
let analyserSyncQueued = false;
function syncAnalyserSoon() {
  if (analyserSyncQueued) return;
  analyserSyncQueued = true;
  requestAnimationFrame(() => { analyserSyncQueued = false; syncAnalyser(); });
}

let demoErrCache = null;
function demoErrors() {
  if (!demoErrCache) demoErrCache = Array.from({ length: 60 }, () => Math.round((Math.random() + Math.random() + Math.random() - 1.5) * 22));
  return demoErrCache;
}

// ------------------------------------------------------------------ rendering
const nodes = {};   // id -> { wrap, inner }

function applyTheme() {
  const t = S.theme, r = document.documentElement.style;
  r.setProperty('--font', t.font);
  r.setProperty('--text', t.textColor);
  r.setProperty('--accent', t.accent);
  const hex = t.panelColor.replace('#', '');
  const [pr, pg, pb] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) || 0);
  r.setProperty('--panel', `rgba(${pr},${pg},${pb},${t.panelOpacity})`);
  r.setProperty('--radius', `${t.radius}px`);
  r.setProperty('--shadow', t.textShadow ? '0 1px 3px rgba(0,0,0,0.85)' : 'none');
  for (const [k, v] of Object.entries(t.colors)) r.setProperty(`--c-${k}`, v);
}

function ensureNodes() {
  const stage = $('#stage');
  for (const id of Object.keys(WIDGETS)) {
    if (nodes[id]) continue;
    const wrap = el('div', 'widget');
    wrap.dataset.id = id;
    wrap.dataset.label = WIDGETS[id].label;
    const inner = el('div');
    wrap.appendChild(inner);
    stage.appendChild(wrap);
    WIDGETS[id].mount?.(inner);
    attachDrag(wrap);
    nodes[id] = { wrap, inner };
  }
}

function renderAll() {
  if (!S) return;
  const st = stateNum(live.data);
  const stage = $('#stage');
  const hiddenAll = !edit && !live.connected && S.general.hideWhenDisconnected && !DEMO;
  stage.classList.toggle('hidden-all', hiddenAll);
  for (const [id, def] of Object.entries(WIDGETS)) {
    const cfg = S.widgets[id];
    const { wrap, inner } = nodes[id];
    const shown = cfg.enabled && (edit || visibleIn(cfg.showIn, st));
    if (id === 'analyser') analyserVisible = shown && !hiddenAll;
    wrap.classList.toggle('off', !shown);
    wrap.classList.toggle('selected', edit && selectedId === id);
    wrap.style.left = cfg.x + 'px';
    wrap.style.top = cfg.y + 'px';
    wrap.style.transform = `scale(${cfg.scale})`;
    wrap.style.opacity = cfg.opacity;
    if (shown || (edit && !cfg.enabled)) {
      try { def.render(inner, cfg, dataFor(cfg.showIn)); } catch (e) { console.error(id, e); }
    }
  }
  const conn = $('#conn');
  conn.textContent = live.connected ? `tosu connected (${S.general.tosuHost})` : `tosu not connected (${S.general.tosuHost}) — is tosu running?`;
  conn.classList.toggle('bad', !live.connected);
  syncAnalyser();
}

let frameQueued = false;
function scheduleRender() {
  if (frameQueued) return;
  frameQueued = true;
  requestAnimationFrame(() => { frameQueued = false; renderAll(); });
}

// ------------------------------------------------------------------ tosu websockets
let connectGen = 0;
let sockets = [];

function connectTosu() {
  for (const s of sockets) { s.onclose = null; s.close(); }
  sockets = [];
  if (DEMO) { startDemo(); return; }
  const host = S.general.tosuHost;

  const open = (path, onMessage, isMain) => {
    let ws;
    try { ws = new WebSocket(`ws://${host}${path}`); } catch (e) { return; }
    sockets.push(ws);
    ws.onopen = () => { if (isMain) { live.connected = true; connectGen++; scheduleRender(); } };
    ws.onmessage = (ev) => { try { onMessage(JSON.parse(ev.data)); } catch (e) { /* ignore bad frame */ } };
    ws.onclose = () => {
      if (isMain && live.connected) { live.connected = false; scheduleRender(); }
      sockets = sockets.filter((s) => s !== ws);
      setTimeout(() => { if (S.general.tosuHost === host) open(path, onMessage, isMain); }, 1500);
    };
  };

  open('/websocket/v2', (d) => {
    const prevSt = stateNum(live.data);
    live.data = d;
    if (stateNum(d) !== prevSt && stateNum(d) !== ST.play && stateNum(d) !== ST.results) live.hitErrors = [];
    scheduleRender();
  }, true);
  open('/websocket/v2/precise', (d) => {
    // precise frames arrive very often; only redraw when a new hit came in
    if (Array.isArray(d.hitErrors) && d.hitErrors.length !== live.hitErrors.length) {
      live.hitErrors = d.hitErrors;
      scheduleRender();
    }
  }, false);
}

function startDemo() {
  live.connected = true;
  const d = sampleData();
  d.play.hits = { geki: 0, 300: 0, katu: 0, 100: 0, 50: 0, 0: 0 };
  d.play.combo = { current: 0, max: 0 };
  live.data = d;
  setInterval(() => {
    const e = Math.round((Math.random() + Math.random() + Math.random() - 1.5) * 24);
    live.hitErrors = [...live.hitErrors.slice(-200), e];
    const a = Math.abs(e), h = d.play.hits;
    if (a <= 16) h.geki++; else if (a <= 40) h['300']++; else if (a <= 73) h.katu++; else if (a <= 103) h['100']++; else h['50']++;
    d.play.combo.current++;
    d.play.combo.max = Math.max(d.play.combo.max, d.play.combo.current);
    d.play.pp.current = Math.min(455, h.geki * 0.25);
    d.play.accuracy = 100 * (h.geki * 305 + h['300'] * 300 + h.katu * 200 + h['100'] * 100 + h['50'] * 50) /
      (305 * (h.geki + h['300'] + h.katu + h['100'] + h['50'] + h['0']));
    d.play.unstableRate = undefined;
    scheduleRender();
  }, 120);
}

// ------------------------------------------------------------------ dragging & resizing
function attachDrag(wrap) {
  wrap.addEventListener('pointerdown', (ev) => {
    if (!edit || ev.button !== 0) return;
    const id = wrap.dataset.id;
    select(id);
    const cfg = S.widgets[id];
    const start = { x: ev.clientX, y: ev.clientY, ox: cfg.x, oy: cfg.y };
    wrap.setPointerCapture(ev.pointerId);
    wrap.classList.add('dragging');
    const grid = Math.max(1, S.general.gridSize | 0);
    const move = (e) => {
      let nx = start.ox + e.clientX - start.x;
      let ny = start.oy + e.clientY - start.y;
      if (!e.shiftKey) { nx = Math.round(nx / grid) * grid; ny = Math.round(ny / grid) * grid; }
      const rect = wrap.getBoundingClientRect();
      cfg.x = Math.max(0, Math.min(window.innerWidth - Math.min(rect.width, 40), nx));
      cfg.y = Math.max(0, Math.min(window.innerHeight - Math.min(rect.height, 40), ny));
      wrap.style.left = cfg.x + 'px';
      wrap.style.top = cfg.y + 'px';
      if (id === 'analyser') syncAnalyserSoon();
    };
    const up = () => {
      wrap.removeEventListener('pointermove', move);
      wrap.removeEventListener('pointerup', up);
      wrap.removeEventListener('pointercancel', up);
      wrap.classList.remove('dragging');
      saveSoon();
      buildWidgetsTab();
    };
    wrap.addEventListener('pointermove', move);
    wrap.addEventListener('pointerup', up);
    wrap.addEventListener('pointercancel', up);
  });
  wrap.addEventListener('wheel', (ev) => {
    if (!edit) return;
    ev.preventDefault();
    const cfg = S.widgets[wrap.dataset.id];
    cfg.scale = Math.round(Math.max(0.3, Math.min(4, cfg.scale + (ev.deltaY < 0 ? 0.05 : -0.05))) * 100) / 100;
    select(wrap.dataset.id);
    scheduleRender();
    saveSoon();
    buildWidgetsTab();
  }, { passive: false });
}

function select(id) {
  selectedId = id;
  openCards.add(id);
  scheduleRender();
  buildWidgetsTab();
}

// ------------------------------------------------------------------ edit mode
function setEditMode(on) {
  edit = !!on;
  document.body.classList.toggle('edit', edit);
  $('#panel').hidden = !edit;
  if (edit) { buildPanel(); refreshRateMap(); }
  scheduleRender();
}

async function leaveEdit() {
  try {
    const r = await api('/api/control', { cmd: 'edit-off' });
    if (r.ok) return;              // the host calls setEditMode(false) for us
  } catch (e) { /* no host (browser preview) */ }
  setEditMode(false);
}

document.addEventListener('keydown', (ev) => {
  if (DEMO && ev.key === 'F3') { setMenuMode(!menu); return; }
  if (menu) { rateMenuKey(ev); return; }
  if (ev.key === 'Escape' && edit) { ev.preventDefault(); leaveEdit(); }
  if (DEMO && ev.key === 'F2') setEditMode(!edit);
  if (edit && selectedId && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(ev.key) &&
      !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
    ev.preventDefault();
    const cfg = S.widgets[selectedId];
    const step = ev.shiftKey ? 10 : 1;
    if (ev.key === 'ArrowUp') cfg.y -= step;
    if (ev.key === 'ArrowDown') cfg.y += step;
    if (ev.key === 'ArrowLeft') cfg.x -= step;
    if (ev.key === 'ArrowRight') cfg.x += step;
    scheduleRender();
    saveSoon();
  }
});

// ------------------------------------------------------------------ settings panel
const openCards = new Set();

function field(label, input, valText) {
  const f = el('label', 'field');
  f.appendChild(el('span', null, esc(label)));
  const g = el('div', 'field-group');
  g.appendChild(input);
  if (valText !== undefined) { const v = el('span', 'val', esc(valText)); g.appendChild(v); input._val = v; }
  f.appendChild(g);
  return f;
}

// Build an input bound to obj[key]; onChange runs after each edit.
function input(obj, key, spec, onChange) {
  let inp;
  if (spec.type === 'bool') {
    inp = el('input'); inp.type = 'checkbox'; inp.checked = !!obj[key];
    inp.onchange = () => { obj[key] = inp.checked; onChange(); };
  } else if (spec.type === 'select') {
    inp = el('select');
    for (const [v, l] of spec.choices) { const o = el('option', null, esc(l)); o.value = v; inp.appendChild(o); }
    inp.value = obj[key];
    inp.onchange = () => { obj[key] = inp.value; onChange(); };
  } else if (spec.type === 'range') {
    inp = el('input'); inp.type = 'range';
    Object.assign(inp, { min: spec.min, max: spec.max, step: spec.step });
    inp.value = obj[key];
    inp.oninput = () => { obj[key] = +inp.value; if (inp._val) inp._val.textContent = inp.value; onChange(); };
  } else if (spec.type === 'color') {
    inp = el('input'); inp.type = 'color'; inp.value = obj[key];
    inp.oninput = () => { obj[key] = inp.value; onChange(); };
  } else {
    inp = el('input'); inp.type = 'text'; inp.value = obj[key] ?? '';
    inp.onchange = () => { obj[key] = inp.value.trim(); onChange(); };
  }
  return spec.type === 'bool' ? field(spec.label, inp) : field(spec.label, inp, spec.type === 'range' ? obj[key] : undefined);
}

const changed = () => { scheduleRender(); saveSoon(); };

function buildPanel() {
  buildWidgetsTab();
  buildLookTab();
  buildGeneralTab();
  buildRateTab();
}

function buildWidgetsTab() {
  if (!edit) return;
  const tab = $('#tab-widgets');
  const scroll = tab.scrollTop;
  tab.innerHTML = '';
  for (const [id, def] of Object.entries(WIDGETS)) {
    const cfg = S.widgets[id];
    const card = el('div', 'wcard' + (openCards.has(id) ? ' open' : '') + (selectedId === id ? ' selected' : ''));
    const head = el('header');
    const en = el('input'); en.type = 'checkbox'; en.checked = cfg.enabled; en.title = 'Enabled';
    en.onclick = (e) => e.stopPropagation();
    en.onchange = () => { cfg.enabled = en.checked; changed(); };
    head.appendChild(en);
    head.appendChild(el('span', 'name', esc(def.label)));
    head.appendChild(el('span', 'muted small', `${Math.round(cfg.x)}, ${Math.round(cfg.y)} · ${Math.round(cfg.scale * 100)}%`));
    head.onclick = () => { openCards.has(id) ? openCards.delete(id) : openCards.add(id); selectedId = id; buildWidgetsTab(); scheduleRender(); };
    card.appendChild(head);
    const body = el('div', 'body');
    body.appendChild(input(cfg, 'showIn', { type: 'select', label: 'Show', choices: SHOW_IN }, changed));
    body.appendChild(input(cfg, 'scale', { type: 'range', label: 'Size', min: 0.3, max: 4, step: 0.05 }, changed));
    body.appendChild(input(cfg, 'opacity', { type: 'range', label: 'Opacity', min: 0.1, max: 1, step: 0.05 }, changed));
    for (const opt of def.options) body.appendChild(input(cfg, opt.key, opt, changed));
    card.appendChild(body);
    tab.appendChild(card);
  }
  tab.scrollTop = scroll;
}

function buildLookTab() {
  const tab = $('#tab-look');
  const t = S.theme;
  const reTheme = () => { applyTheme(); changed(); };
  tab.innerHTML = '';
  tab.appendChild(el('h4', null, 'Text'));
  tab.appendChild(input(t, 'font', { type: 'text', label: 'Font' }, reTheme));
  tab.appendChild(input(t, 'textColor', { type: 'color', label: 'Text colour' }, reTheme));
  tab.appendChild(input(t, 'textShadow', { type: 'bool', label: 'Text shadow' }, reTheme));
  tab.appendChild(input(t, 'accent', { type: 'color', label: 'Accent' }, reTheme));
  tab.appendChild(el('h4', null, 'Panels'));
  tab.appendChild(input(t, 'panelColor', { type: 'color', label: 'Background' }, reTheme));
  tab.appendChild(input(t, 'panelOpacity', { type: 'range', label: 'Background opacity', min: 0, max: 1, step: 0.05 }, reTheme));
  tab.appendChild(input(t, 'radius', { type: 'range', label: 'Corner radius', min: 0, max: 24, step: 1 }, reTheme));
  tab.appendChild(el('h4', null, 'Judgement colours'));
  for (const [k, l] of [['max', 'MAX'], ['300', '300'], ['200', '200'], ['100', '100'], ['50', '50'], ['miss', 'Miss']]) {
    tab.appendChild(input(t.colors, k, { type: 'color', label: l }, reTheme));
  }
}

function buildGeneralTab() {
  const tab = $('#tab-general');
  const g = S.general;
  tab.innerHTML = '';
  tab.appendChild(el('h4', null, 'Connections'));
  tab.appendChild(input(g, 'tosuHost', { type: 'text', label: 'tosu address' }, () => { changed(); connectTosu(); }));
  tab.appendChild(input(g, 'analyserCounter', { type: 'text', label: 'Analyser counter folder' }, changed));
  tab.appendChild(input(g, 'songsFolder', { type: 'text', label: 'Songs folder (optional)' }, changed));
  tab.appendChild(input(g, 'winePrefix', { type: 'text', label: 'Wine prefix (optional)' }, changed));
  const monSlot = el('div');
  tab.appendChild(monSlot);
  buildMonitorField(monSlot);
  tab.appendChild(el('h4', null, 'Behaviour'));
  tab.appendChild(input(g, 'hideWhenDisconnected', { type: 'bool', label: 'Hide everything when tosu is off' }, changed));
  tab.appendChild(input(g, 'gridSize', { type: 'range', label: 'Snap grid (px)', min: 1, max: 32, step: 1 }, changed));
  tab.appendChild(el('h4', null, 'Shortcuts'));
  tab.appendChild(el('div', 'keys small',
    '<code>Meta+Alt+O</code> this editor · <code>Meta+Alt+R</code> rate picker · <code>Meta+Alt+H</code> show / hide<br>' +
    'The installer sets these up. Change them in KDE System Settings → Keyboard → Shortcuts → mania-overlay, ' +
    'or in <code>~/.config/niri/mania-overlay.kdl</code> on niri.<br>' +
    'Commands: <code>mania-overlay edit</code> · <code>rate-menu</code> · <code>toggle</code> · <code>rate 1.1 --od 8</code><br>' +
    'In the editor: drag to move, scroll to resize, arrows to nudge, Esc to finish.'));
  tab.appendChild(el('h4', null, 'Reset'));
  const row = el('div', 'row');
  const resetLayout = el('button', null, 'Reset layout');
  resetLayout.onclick = async () => {
    const def = (await api('/api/settings/reset', {}));
    const theme = S.theme, general = S.general, rate = S.rate;
    S = def; S.theme = theme; S.general = general; S.rate = rate;
    await api('/api/settings', S);
    buildPanel(); changed();
  };
  const resetAll = el('button', null, 'Reset everything');
  resetAll.onclick = async () => {
    if (!confirm('Reset all settings to defaults?')) return;
    S = await api('/api/settings/reset', {});
    applyTheme(); buildPanel(); changed(); connectTosu();
  };
  row.append(resetLayout, resetAll);
  tab.appendChild(row);
}

// Monitor picker: a dropdown of the outputs GTK sees, or a text box in the browser preview.
async function buildMonitorField(slot) {
  const g = S.general;
  let list = [];
  try { list = (await api('/api/monitors')).monitors || []; } catch (e) { /* preview */ }
  slot.innerHTML = '';
  if (!list.length) {
    slot.appendChild(input(g, 'monitor', { type: 'text', label: 'Monitor, e.g. DP-1' }, changed));
    return;
  }
  const choices = [['', 'Automatic (compositor decides)']];
  for (const m of list) {
    const size = m.width && m.height ? ` ${m.width}×${m.height}` : '';
    choices.push([m.connector, `${m.connector}${m.name ? ' — ' + m.name : ''}${size}`]);
  }
  if (g.monitor && !list.some((m) => m.connector === g.monitor)) choices.push([g.monitor, `${g.monitor} (not connected)`]);
  slot.appendChild(input(g, 'monitor', { type: 'select', label: 'Monitor', choices }, changed));
}

// ------------------------------------------------------------------ rate changer tab
const chosenRates = new Set();

function buildRateTab() {
  const r = S.rate;
  const quick = $('#rate-quick');
  quick.innerHTML = '';
  for (const q of r.quickRates) {
    const b = el('button', chosenRates.has(q) ? 'on' : '', fmtRate(q) + 'x');
    b.onclick = () => { chosenRates.has(q) ? chosenRates.delete(q) : chosenRates.add(q); buildRateTab(); };
    quick.appendChild(b);
  }
  $('#rate-pitch').checked = !!r.pitch;
  $('#rate-overwrite').checked = !!r.overwrite;
  $('#rate-format').value = r.audioFormat;
}

function rateLog(line) {
  const log = $('#rate-log');
  log.textContent += (log.textContent ? '\n' : '') + line;
  log.scrollTop = log.scrollHeight;
}

async function refreshRateMap() {
  const b = live.data?.beatmap;
  $('#rate-map').textContent = b?.title ? `${b.artist} - ${b.title} [${b.version}]` : '—';
  try {
    const res = await api('/api/current-map');
    if (!res.path) $('#rate-map').textContent += '  (file not found: set the Songs folder under General)';
  } catch (e) { /* preview without backend */ }
}

// OD typed in the editor's Rate tab; null = keep the map's OD
function editorOd() {
  const raw = String($('#rate-od').value).trim().replace(',', '.');
  if (!raw) return { od: null, ok: true };
  const v = parseFloat(raw);
  if (!Number.isFinite(v) || v < OD_MIN || v > OD_MAX) return { od: null, ok: false };
  return { od: Math.round(v * 10) / 10, ok: true };
}

const describeRate = (rate, od) =>
  [Math.abs(rate - 1) > 1e-6 ? fmtRate(rate) + 'x' : '', od != null ? 'OD' + fmtOd(od) : ''].filter(Boolean).join(' ') || '1x';

async function createRates(rates) {
  if (!rates.length) { rateLog('Pick at least one rate.'); return; }
  const { od, ok } = editorOd();
  if (!ok) { rateLog(`OD must be a number from ${OD_MIN} to ${OD_MAX}, or empty to keep it.`); return; }
  rateLog(`Creating ${rates.map((r) => describeRate(r, od)).join(', ')}…`);
  for (const id of ['rate-one', 'rate-many']) $('#' + id).disabled = true;
  try {
    const res = await api('/api/rate', { rates, pitch: S.rate.pitch, overwrite: S.rate.overwrite, od });
    for (const x of res.results || []) rateLog(`${x.skipped ? 'exists ' : 'created'}  ${describeRate(x.rate, x.od)}  →  ${x.osu.split('/').pop()}`);
    for (const e of res.errors || []) rateLog('error  ' + e);
    if (res.error) rateLog('error  ' + res.error);
  } catch (e) {
    rateLog('error  ' + e);
  } finally {
    for (const id of ['rate-one', 'rate-many']) $('#' + id).disabled = false;
  }
}

// ------------------------------------------------------------------ rate picker popup
const RM_MIN = 0.5, RM_MAX = 2.0;
const OD_MIN = 0, OD_MAX = 10;
let menu = false;
let rmBusy = false;
let rmCloseTimer = null;
let mapOd = null;      // OD of the selected map, from tosu

const clampRate = (r) => Math.round(Math.min(RM_MAX, Math.max(RM_MIN, r)) * 100) / 100;
const clampOd = (o) => Math.round(Math.min(OD_MAX, Math.max(OD_MIN, o)) * 10) / 10;
const fmtOd = (o) => (+o).toFixed(1).replace(/\.0$/, '');
const cleanDecimal = (s) => s.replace(',', '.').replace(/[^0-9.]/g, '').replace(/(\..*)\./g, '$1');

// Read the typed value; null when it isn't a usable rate.
function rmValue() {
  const v = parseFloat(String($('#rm-input').value).replace(',', '.'));
  if (!Number.isFinite(v) || v < RM_MIN || v > RM_MAX) return null;
  return Math.round(v * 100) / 100;
}

const odOn = () => $('#rm-od-on').checked;

// Typed OD; null when invalid.
function odValue() {
  const v = parseFloat(String($('#rm-od').value).replace(',', '.'));
  if (!Number.isFinite(v) || v < OD_MIN || v > OD_MAX) return null;
  return Math.round(v * 10) / 10;
}

function rmStatus(text, kind = '', validation = false) {
  const s = $('#rm-status');
  s.textContent = text;
  s.className = 'small ' + kind;
  s.dataset.validation = validation ? '1' : '';
}

// What would be created right now, or an error message.
function rmPlan() {
  const rate = rmValue();
  if (rate === null) return { error: `Pick a rate from ${RM_MIN}x to ${RM_MAX}x.` };
  let od = null;
  if (odOn()) {
    od = odValue();
    if (od === null) return { error: `OD must be from ${OD_MIN} to ${OD_MAX}.`, rate };
  }
  const sameOd = od !== null && mapOd !== null && Math.abs(od - mapOd) < 1e-6;
  if (rate === 1 && (od === null || sameOd)) {
    return { error: od === null ? '1.0x is the original map. Change the rate or turn on Change OD.' : `This map is already OD${fmtOd(od)}.`, rate };
  }
  return { rate, od: sameOd ? null : od };
}

// Refresh everything that depends on the current values. fromTyping keeps the
// typed text as-is so "1.0" can become "1.05" without being rewritten midway.
function rmSync(fromTyping = false) {
  const v = rmValue();
  const inp = $('#rm-input');
  const plan = rmPlan();
  inp.classList.toggle('bad', v === null || (!!plan.error && !odOn()));
  if (v !== null) $('#rm-slider').value = v;
  for (const b of document.querySelectorAll('#rm-chips button')) b.classList.toggle('on', v !== null && +b.dataset.rate === v);
  if (!fromTyping && v !== null) inp.value = v.toFixed(2);

  $('#rm-od-box').classList.toggle('on', odOn());
  const o = odValue();
  $('#rm-od').classList.toggle('bad', odOn() && o === null);
  if (o !== null) $('#rm-od-slider').value = o;
  $('#rm-od-orig').textContent = mapOd !== null ? `(map is OD${fmtOd(mapOd)})` : '';

  const btn = $('#rm-create');
  btn.disabled = rmBusy || !!plan.error;
  btn.textContent = rmBusy ? 'Creating…' : plan.error ? 'Create' : `Create ${describeRate(plan.rate, plan.od)}`;
  if (!rmBusy) {
    // only touch messages that came from validation; keep server results and warnings
    if (plan.error) rmStatus(plan.error, 'error', true);
    else if ($('#rm-status').dataset.validation) rmStatus('');
  }
}

function rmSet(v) {
  $('#rm-input').value = clampRate(v).toFixed(2);
  rmSync();
}

function rmStep(delta) {
  const cur = rmValue() ?? clampRate(parseFloat($('#rm-input').value) || S.rate.lastRate || 1.1);
  rmSet(Math.round((cur + delta) * 100) / 100);
}

function odSet(o) {
  $('#rm-od').value = fmtOd(clampOd(o));
  rmSync();
}

function odStep(delta) {
  if (!odOn()) { $('#rm-od-on').checked = true; }
  const cur = odValue() ?? mapOd ?? 8;
  odSet(Math.round((cur + delta) * 10) / 10);
}

function buildRateMenu() {
  const chips = $('#rm-chips');
  chips.innerHTML = '';
  for (const q of S.rate.quickRates.filter((q) => q >= RM_MIN && q <= RM_MAX)) {
    const b = el('button', '', fmtRate(q) + 'x');
    b.type = 'button';
    b.dataset.rate = q;
    b.onclick = () => { rmSet(q); $('#rm-input').focus(); };
    chips.appendChild(b);
  }
  $('#rm-pitch').checked = !!S.rate.pitch;
  const b = live.data?.beatmap;
  $('#rm-map').textContent = b?.title ? `${b.artist} - ${b.title} [${b.version}]` : 'No map selected';
  $('#rm-map').title = $('#rm-map').textContent;
  const od = +(b?.stats?.od?.original);
  mapOd = Number.isFinite(od) && b?.title ? Math.round(od * 10) / 10 : null;
}

function setMenuMode(on) {
  menu = !!on;
  clearTimeout(rmCloseTimer);
  $('#ratemenu').hidden = !menu;
  syncAnalyser();   // the native MSD panel would cover the popup
  if (menu) {
    if (edit) setEditMode(false);
    buildRateMenu();
    rmBusy = false;
    rmStatus('');
    $('#rm-od-on').checked = false;            // OD change is opt-in each time
    $('#rm-od').value = fmtOd(S.rate.lastOd ?? mapOd ?? 8);
    rmSet(S.rate.lastRate ?? 1.1);
    const focus = () => { const i = $('#rm-input'); i.focus(); i.select(); };
    focus();
    setTimeout(focus, 60);   // the window may only get keyboard focus a moment later
    api('/api/current-map').then((res) => {
      if (menu && !res.path) rmStatus("Can't find this map's .osu file. Set the Songs folder in the editor's General tab.", 'error');
    }).catch(() => {});
  }
}

async function leaveMenu() {
  try {
    const r = await api('/api/control', { cmd: 'rate-menu-off' });
    if (r.ok) return;              // the host calls setMenuMode(false) for us
  } catch (e) { /* no host (browser preview) */ }
  setMenuMode(false);
}

async function rmCreate() {
  const plan = rmPlan();
  if (rmBusy || plan.error) { rmSync(); return; }
  const { rate, od } = plan;
  const label = describeRate(rate, od);
  rmBusy = true;
  if (rate !== 1) S.rate.lastRate = rate;   // an OD-only copy shouldn't make the picker open at 1.00x
  if (od !== null) S.rate.lastOd = od;
  saveSoon();
  rmSync();
  rmStatus(`Creating ${label}…`);
  let ok = false;
  try {
    const res = await api('/api/rate', { rates: [rate], pitch: S.rate.pitch, overwrite: S.rate.overwrite, od });
    const made = res.results?.[0];
    if (res.error || res.errors?.length) {
      rmStatus((res.error || res.errors.join('\n')), 'error');
    } else if (made?.skipped) {
      rmStatus(`${label} already exists. Turn on "Overwrite existing rates" in the editor to remake it.`, '');
    } else {
      rmStatus(`Created ${label}. Press F5 in song select if it doesn't show up.`, 'ok');
      ok = true;
    }
  } catch (e) {
    rmStatus('error: ' + e, 'error');
  } finally {
    rmBusy = false;
    rmSync();
  }
  if (ok) rmCloseTimer = setTimeout(() => { if (menu) leaveMenu(); }, 1400);
}

function wireRateMenu() {
  const inp = $('#rm-input');
  const odInp = $('#rm-od');
  // digits and one decimal mark only; a comma (Norwegian numpad) counts as the decimal point
  inp.addEventListener('input', () => {
    const clean = cleanDecimal(inp.value);
    if (clean !== inp.value) inp.value = clean;
    rmSync(true);
  });
  inp.addEventListener('blur', () => { if (menu && rmValue() !== null) rmSync(); });
  odInp.addEventListener('input', () => {
    const clean = cleanDecimal(odInp.value);
    if (clean !== odInp.value) odInp.value = clean;
    rmSync(true);
  });
  odInp.addEventListener('focus', () => { if (!odOn()) { $('#rm-od-on').checked = true; rmSync(); } });
  $('#rm-slider').addEventListener('input', (e) => rmSet(+e.target.value));
  $('#rm-od-slider').addEventListener('input', (e) => odSet(+e.target.value));
  $('#rm-minus').onclick = () => { rmStep(-0.05); inp.focus(); };
  $('#rm-plus').onclick = () => { rmStep(0.05); inp.focus(); };
  $('#rm-od-minus').onclick = () => { odStep(-0.5); odInp.focus(); };
  $('#rm-od-plus').onclick = () => { odStep(0.5); odInp.focus(); };
  $('#rm-od-on').onchange = () => { rmSync(); if (odOn()) { odInp.focus(); odInp.select(); } else inp.focus(); };
  $('#rm-create').onclick = rmCreate;
  $('#rm-cancel').onclick = leaveMenu;
  $('#rm-pitch').onchange = (e) => { S.rate.pitch = e.target.checked; saveSoon(); inp.focus(); };
  // click on the dimmed area outside the box closes it
  $('#ratemenu').addEventListener('pointerdown', (e) => { if (e.target.id === 'ratemenu') leaveMenu(); });
}

function rateMenuKey(ev) {
  if (ev.key === 'Escape') { ev.preventDefault(); leaveMenu(); return; }
  if (ev.key === 'Enter') { ev.preventDefault(); rmCreate(); return; }
  const id = document.activeElement?.id || '';
  const onOd = id.startsWith('rm-od');
  const textField = id === 'rm-input' || id === 'rm-od';
  const up = ev.key === 'ArrowUp' || (ev.key === 'ArrowRight' && !textField);
  const down = ev.key === 'ArrowDown' || (ev.key === 'ArrowLeft' && !textField);
  if (!up && !down) return;
  ev.preventDefault();
  if (onOd) odStep((up ? 1 : -1) * (ev.shiftKey ? 0.1 : 0.5));
  else rmStep((up ? 1 : -1) * (ev.shiftKey ? 0.01 : 0.05));
}

function wireStaticPanel() {
  for (const b of document.querySelectorAll('#tabs button')) {
    b.onclick = () => {
      for (const o of document.querySelectorAll('#tabs button')) o.classList.toggle('on', o === b);
      for (const t of document.querySelectorAll('.tab')) t.hidden = t.id !== 'tab-' + b.dataset.tab;
      if (b.dataset.tab === 'rate') refreshRateMap();
    };
  }
  $('#done').onclick = leaveEdit;
  $('#rate-one').onclick = () => createRates([+$('#rate-input').value]);
  $('#rate-many').onclick = () => createRates([...chosenRates].sort((a, b) => a - b));
  $('#rate-clear').onclick = () => { chosenRates.clear(); buildRateTab(); };
  $('#rate-pitch').onchange = (e) => { S.rate.pitch = e.target.checked; saveSoon(); };
  $('#rate-overwrite').onchange = (e) => { S.rate.overwrite = e.target.checked; saveSoon(); };
  $('#rate-format').onchange = (e) => { S.rate.audioFormat = e.target.value; saveSoon(); };

  // drag the panel by its header
  const panel = $('#panel'), head = $('#panel-head');
  head.addEventListener('pointerdown', (ev) => {
    if (ev.target.closest('button')) return;
    const r = panel.getBoundingClientRect();
    const off = { x: ev.clientX - r.left, y: ev.clientY - r.top };
    head.setPointerCapture(ev.pointerId);
    const move = (e) => {
      panel.style.left = Math.max(0, Math.min(window.innerWidth - 100, e.clientX - off.x)) + 'px';
      panel.style.top = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - off.y)) + 'px';
      panel.style.right = 'auto';
    };
    const up = () => { head.removeEventListener('pointermove', move); head.removeEventListener('pointerup', up); };
    head.addEventListener('pointermove', move);
    head.addEventListener('pointerup', up);
  });
}

// ------------------------------------------------------------------ toasts
function toast(message, kind = 'info') {
  const t = el('div', 'toast ' + kind, esc(message));
  $('#toasts').appendChild(t);
  if (edit && $('#rate-log')) rateLog(message);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 450); }, kind === 'error' ? 7000 : 4000);
}

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    S = await api('/api/settings');
  } catch (e) {
    console.error('could not load settings', e);
    return;
  }
  let startMenu = false;
  try {
    const st = await api('/api/status');
    edit = !!st.edit;
    startMenu = !!st.menu;
    NATIVE_ANALYSER = !!st.nativeAnalyser;
  } catch (e) { /* ignore */ }
  applyTheme();
  ensureNodes();
  wireStaticPanel();
  wireRateMenu();
  connectTosu();
  setEditMode(edit || (DEMO && new URLSearchParams(location.search).has('edit')));
  if (startMenu || (DEMO && new URLSearchParams(location.search).has('menu'))) setMenuMode(true);
}

window.overlay = { setEditMode, setMenuMode, toast, reloadSettings: async () => { S = await api('/api/settings'); applyTheme(); buildPanel(); scheduleRender(); } };
boot();
