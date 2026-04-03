/* ==========================================================
   FoE Battle Automation – Frontend
   ========================================================== */

'use strict';

// ---- Server metadata ------------------------------------------------
const SERVERS = [
  { id: 'cz1', label: 'CZ1' },
  { id: 'cz2', label: 'CZ2' },
  { id: 'cz3', label: 'CZ3' },
  { id: 'cz4', label: 'CZ4' },
  { id: 'cz5', label: 'CZ5' },
  { id: 'cz6', label: 'CZ6' },
  { id: 'cz7', label: 'CZ7' },
  { id: 'cz8', label: 'CZ8' },
];

const REGION_DEFS = [
  { key: 'sector_list',   label: 'Oblast sektorů' },
  { key: 'fight_counter', label: 'Počítadlo bitev' },
  { key: 'oslabeni',      label: 'Oslabení' },
  { key: 'attack_button', label: 'Tlačítko útok' },
  { key: 'click_target',  label: 'Cíl klikání' },
];

const REGION_COLORS = {
  sector_list:   'rgba(88,166,255,0.5)',
  fight_counter: 'rgba(63,185,80,0.5)',
  oslabeni:      'rgba(210,153,34,0.5)',
  attack_button: 'rgba(188,140,255,0.5)',
  click_target:  'rgba(248,81,73,0.5)',
};

// ---- State ----------------------------------------------------------
let socket;
let serverConfig = {};
let calibState   = {};

// ---- Init -----------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  buildGrid();
  connectSocket();
  document.getElementById('btn-start-all').addEventListener('click', () => socket.emit('start_all', {}));
  document.getElementById('btn-stop-all').addEventListener('click',  () => socket.emit('stop_all',  {}));
});

// ---- Build server cards ---------------------------------------------
function buildGrid() {
  const grid = document.getElementById('server-grid');
  grid.innerHTML = '';
  for (const srv of SERVERS) {
    grid.appendChild(buildCard(srv));
    calibState[srv.id] = {
      activeRegion: null,
      regions: {},
      dragging: false,
      dragStart: null,
    };
  }
}

function buildCard(srv) {
  const card = document.createElement('div');
  card.className = 'server-card';
  card.dataset.server = srv.id;

  card.innerHTML = `
    <!-- Header -->
    <div class="card-header">
      <span class="server-name">${srv.label}</span>
      <label class="toggle-wrap">
        <input type="checkbox" class="enable-toggle" title="Zapnout server">
        <span>Aktivní</span>
      </label>
      <span class="status-badge state-stopped">stopped</span>
    </div>

    <!-- Stats -->
    <div class="card-stats">
      <div class="stats-row">
        <div class="stat-item">Oslabení: <span class="v-oslabeni">–</span></div>
        <div class="stat-item">Bitvy: <span class="v-fights">–/–</span></div>
        <div class="stat-item">Sektor: <span class="v-sector">–</span></div>
      </div>
      <div class="error-msg" style="display:none"></div>
    </div>

    <!-- Config -->
    <div class="card-config">
      <div class="config-grid">
        <label>
          Max oslabení
          <input type="number" class="cfg-max-oslabeni" min="0" max="999" value="100">
        </label>
        <label class="cfg-checkbox-wrap">
          <input type="checkbox" class="cfg-attack-60">
          Útočit i na 60%
        </label>
        <label>
          Interval klikání (ms)
          <input type="number" class="cfg-click-interval" min="10" max="500" value="50">
        </label>
        <label>
          R klávesa každých N kliků
          <input type="number" class="cfg-r-every" min="1" max="50" value="5">
        </label>
      </div>
      <div class="card-btn-row">
        <button class="btn primary btn-save-cfg">💾 Uložit</button>
        <button class="btn success btn-start">▶ Start</button>
        <button class="btn danger  btn-stop">■ Stop</button>
      </div>
    </div>

    <!-- Calibration -->
    <div class="card-calibration">
      <div class="calib-title">Kalibrace oblastí</div>

      <!-- Tab URL -->
      <div class="win-title-row">
        <label class="win-title-label">
          URL tabu
          <input type="text" class="win-title-input" placeholder="např. cz1.forgeofempires">
        </label>
        <button class="btn btn-find-windows" title="Zobrazit otevřené taby">🔍</button>
        <button class="btn btn-save-win-title">💾</button>
      </div>
      <div class="windows-list" style="display:none"></div>

      <div class="card-btn-row" style="margin-top:6px;margin-bottom:8px">
        <button class="btn btn-screenshot">📷 Screenshot</button>
      </div>

      <!-- Calibration panel (hidden until screenshot) -->
      <div class="calib-panel">
        <div class="region-btns">
          ${REGION_DEFS.map(r => `
            <button class="region-btn" data-region="${r.key}">${r.label}</button>
          `).join('')}
        </div>
        <div class="calib-canvas-wrap">
          <canvas class="calib-canvas"></canvas>
          <svg class="overlay" xmlns="http://www.w3.org/2000/svg"></svg>
        </div>
        <div class="card-btn-row">
          <button class="btn primary btn-save-regions" disabled>💾 Uložit oblasti</button>
          <button class="btn btn-clear-regions">🗑 Vymazat</button>
        </div>
      </div>
    </div>
  `;

  bindCardEvents(card, srv.id);
  return card;
}

// ---- Card event binding ---------------------------------------------
function bindCardEvents(card, sid) {
  const $ = sel => card.querySelector(sel);

  $('.enable-toggle').addEventListener('change', e => saveCfg(sid, card, e.target.checked));
  $('.btn-save-cfg').addEventListener('click', () => saveCfg(sid, card));
  $('.btn-start').addEventListener('click', () => socket.emit('start_server', { server: sid }));
  $('.btn-stop').addEventListener('click',  () => socket.emit('stop_server',  { server: sid }));

  // Save tab URL
  $('.btn-save-win-title').addEventListener('click', () => {
    const url = $('.win-title-input').value.trim();
    socket.emit('save_tab_url', { server: sid, tab_url: url });
  });

  // List open tabs from CDP
  $('.btn-find-windows').addEventListener('click', () => {
    const listEl = $('.windows-list');
    listEl.innerHTML = '<em>Načítám taby z Chrome…</em>';
    listEl.style.display = '';
    socket.emit('list_tabs', {});

    socket.once('tabs_list', (data) => {
      if (data.error) {
        listEl.innerHTML = `<span class="err">${data.error}<br>Spusť Chrome s: --remote-debugging-port=9222</span>`;
        return;
      }
      if (!data.tabs.length) {
        listEl.innerHTML = '<em>Žádné taby nenalezeny. Spusť Chrome s --remote-debugging-port=9222</em>';
        return;
      }
      listEl.innerHTML = data.tabs.map(t =>
        `<div class="win-item" data-url="${escHtml(t.url)}">
          <span class="tab-title">${escHtml(t.title)}</span>
          <span class="tab-url">${escHtml(t.url)}</span>
        </div>`
      ).join('');
      listEl.querySelectorAll('.win-item').forEach(item => {
        item.addEventListener('click', () => {
          $('.win-title-input').value = item.dataset.url;
          listEl.style.display = 'none';
        });
      });
    });
  });

  // Screenshot
  $('.btn-screenshot').addEventListener('click', () => {
    socket.emit('request_screenshot', { server: sid });
  });

  // Region buttons
  card.querySelectorAll('.region-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      card.querySelectorAll('.region-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      calibState[sid].activeRegion = btn.dataset.region;
    });
  });

  // Canvas drawing
  const canvasWrap = $('.calib-canvas-wrap');
  const canvas     = $('.calib-canvas');
  const overlay    = $('.overlay');

  canvasWrap.addEventListener('mousedown',  e => startDrag(e, sid, canvas));
  canvasWrap.addEventListener('mousemove',  e => duringDrag(e, sid, canvas, overlay));
  canvasWrap.addEventListener('mouseup',    e => endDrag(e, sid, canvas, overlay, card));
  canvasWrap.addEventListener('mouseleave', () => { calibState[sid].dragging = false; });

  canvasWrap.addEventListener('touchstart',  e => { e.preventDefault(); startDrag(e.touches[0], sid, canvas); });
  canvasWrap.addEventListener('touchmove',   e => { e.preventDefault(); duringDrag(e.touches[0], sid, canvas, overlay); });
  canvasWrap.addEventListener('touchend',    e => { e.preventDefault(); endDrag(e.changedTouches[0], sid, canvas, overlay, card); });

  $('.btn-save-regions').addEventListener('click', () => saveRegions(sid, card));

  $('.btn-clear-regions').addEventListener('click', () => {
    calibState[sid].regions = {};
    redrawOverlay(sid, overlay, canvas);
    card.querySelectorAll('.region-btn').forEach(b => b.classList.remove('set', 'active'));
    calibState[sid].activeRegion = null;
    $('.btn-save-regions').disabled = true;
  });
}

// ---- Config save ----------------------------------------------------
function saveCfg(sid, card, enabledOverride) {
  const $ = sel => card.querySelector(sel);
  const enabled = enabledOverride !== undefined ? enabledOverride : $('.enable-toggle').checked;
  socket.emit('save_config', {
    server:               sid,
    enabled,
    max_oslabeni:         parseInt($('.cfg-max-oslabeni').value)  || 100,
    attack_60_percent:    $('.cfg-attack-60').checked,
    click_interval_ms:    parseInt($('.cfg-click-interval').value) || 50,
    r_key_every_n_clicks: parseInt($('.cfg-r-every').value)       || 5,
  });
}

// ---- Region save — coords are relative to window client area --------
function saveRegions(sid, card) {
  const cs      = calibState[sid];
  const canvas  = card.querySelector('.calib-canvas');
  const payload = {};

  for (const [key, rect] of Object.entries(cs.regions)) {
    // rect is in canvas display pixels; convert to actual image pixels
    const scaleX = canvas.width  / canvas.getBoundingClientRect().width;
    const scaleY = canvas.height / canvas.getBoundingClientRect().height;
    payload[key] = {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      w: Math.round(Math.abs(rect.w)),
      h: Math.round(Math.abs(rect.h)),
    };
  }
  socket.emit('save_regions', { server: sid, regions: payload });
}

// ---- Canvas drag drawing --------------------------------------------
function canvasPos(evt, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (evt.clientX - rect.left) * (canvas.width  / rect.width),
    y: (evt.clientY - rect.top)  * (canvas.height / rect.height),
  };
}

function startDrag(evt, sid, canvas) {
  const cs = calibState[sid];
  if (!cs.activeRegion) return;
  cs.dragging   = true;
  cs.dragStart  = canvasPos(evt, canvas);
}

function duringDrag(evt, sid, canvas, overlay) {
  const cs = calibState[sid];
  if (!cs.dragging || !cs.dragStart) return;
  const cur = canvasPos(evt, canvas);
  const x = Math.min(cs.dragStart.x, cur.x);
  const y = Math.min(cs.dragStart.y, cur.y);
  const w = Math.abs(cur.x - cs.dragStart.x);
  const h = Math.abs(cur.y - cs.dragStart.y);
  let preview = overlay.querySelector('.preview-rect');
  if (!preview) {
    preview = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    preview.classList.add('preview-rect');
    preview.setAttribute('fill', 'rgba(255,255,255,0.15)');
    preview.setAttribute('stroke', '#fff');
    preview.setAttribute('stroke-width', '1');
    preview.setAttribute('stroke-dasharray', '4');
    overlay.appendChild(preview);
  }
  preview.setAttribute('x',      x / canvas.width  * 100 + '%');
  preview.setAttribute('y',      y / canvas.height * 100 + '%');
  preview.setAttribute('width',  w / canvas.width  * 100 + '%');
  preview.setAttribute('height', h / canvas.height * 100 + '%');
}

function endDrag(evt, sid, canvas, overlay, card) {
  const cs = calibState[sid];
  if (!cs.dragging || !cs.dragStart) return;
  cs.dragging = false;

  const cur = canvasPos(evt, canvas);
  const x = Math.min(cs.dragStart.x, cur.x);
  const y = Math.min(cs.dragStart.y, cur.y);
  const w = Math.abs(cur.x - cs.dragStart.x);
  const h = Math.abs(cur.y - cs.dragStart.y);

  overlay.querySelector('.preview-rect')?.remove();
  if (w < 3 || h < 3) return;

  cs.regions[cs.activeRegion] = { x, y, w, h };

  card.querySelectorAll('.region-btn').forEach(b => {
    if (b.dataset.region === cs.activeRegion) {
      b.classList.remove('active');
      b.classList.add('set');
    }
  });
  cs.activeRegion = null;

  if (cs.regions.click_target) {
    card.querySelector('.btn-save-regions').disabled = false;
  }
  redrawOverlay(sid, overlay, canvas);
}

function redrawOverlay(sid, overlay, canvas) {
  overlay.querySelectorAll('rect:not(.preview-rect), text').forEach(el => el.remove());
  const cs = calibState[sid];
  for (const [key, rect] of Object.entries(cs.regions)) {
    const color = REGION_COLORS[key] || 'rgba(200,200,200,0.4)';
    const label = REGION_DEFS.find(r => r.key === key)?.label || key;

    const svgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    svgRect.setAttribute('x',      rect.x / canvas.width  * 100 + '%');
    svgRect.setAttribute('y',      rect.y / canvas.height * 100 + '%');
    svgRect.setAttribute('width',  rect.w / canvas.width  * 100 + '%');
    svgRect.setAttribute('height', rect.h / canvas.height * 100 + '%');
    svgRect.setAttribute('fill',   color);
    svgRect.setAttribute('stroke', color.replace(/[\d.]+\)$/, '1)'));
    svgRect.setAttribute('stroke-width', '1.5');
    overlay.appendChild(svgRect);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x',           (rect.x + 4) / canvas.width  * 100 + '%');
    text.setAttribute('y',           (rect.y + 13) / canvas.height * 100 + '%');
    text.setAttribute('fill',        '#fff');
    text.setAttribute('font-size',   '10');
    text.setAttribute('font-family', 'sans-serif');
    text.textContent = label;
    overlay.appendChild(text);
  }
}

// ---- Socket.IO ------------------------------------------------------
function connectSocket() {
  socket = io('http://localhost:9000', { transports: ['websocket', 'polling'] });
  socket.on('connect',    () => setConnStatus(true));
  socket.on('disconnect', () => setConnStatus(false));

  socket.on('full_config', cfg => {
    serverConfig = cfg;
    applyFullConfig(cfg);
  });

  socket.on('status_update',  data => updateCard(data));
  socket.on('config_saved',   data => { if (data.ok) flashSaved(data.server); });
  socket.on('calibration_screenshot', data => showCalibScreenshot(data));

  socket.on('error', data => {
    console.error(`[${data.server || 'global'}] ${data.message}`);
    if (data.server) showCardError(data.server, data.message);
  });
}

function setConnStatus(ok) {
  document.getElementById('conn-dot').className   = 'conn-dot' + (ok ? ' ok' : '');
  document.getElementById('conn-label').textContent = ok ? 'Připojeno' : 'Odpojeno';
}

// ---- Apply full config to all cards ---------------------------------
function applyFullConfig(cfg) {
  if (!cfg?.servers) return;
  for (const [sid, srv] of Object.entries(cfg.servers)) {
    const card = document.querySelector(`[data-server="${sid}"]`);
    if (!card) continue;
    const $ = sel => card.querySelector(sel);
    $('.enable-toggle').checked       = !!srv.enabled;
    $('.cfg-max-oslabeni').value       = srv.max_oslabeni        ?? 100;
    $('.cfg-attack-60').checked        = !!srv.attack_60_percent;
    $('.cfg-click-interval').value     = srv.click_interval_ms   ?? 50;
    $('.cfg-r-every').value            = srv.r_key_every_n_clicks ?? 5;
    $('.win-title-input').value        = srv.tab_url               ?? '';
  }
}

// ---- Update card stats ----------------------------------------------
function updateCard(data) {
  const { server: sid, state, oslabeni, fight_current, fight_total, sector_found, last_error } = data;
  const card = document.querySelector(`[data-server="${sid}"]`);
  if (!card) return;

  card.className = `server-card state-${state}`;

  const badge = card.querySelector('.status-badge');
  badge.className   = `status-badge state-${state}`;
  const LABELS = { stopped: 'Stopped', scanning: 'Skenuje', fighting: 'Bojuje!', error: 'Chyba' };
  badge.textContent = LABELS[state] || state;

  const cfg    = serverConfig?.servers?.[sid] || {};
  const maxOsl = cfg.max_oslabeni ?? 100;

  const vOsl = card.querySelector('.v-oslabeni');
  if (oslabeni != null) {
    vOsl.textContent = oslabeni;
    vOsl.className   = oslabeni >= maxOsl ? 'danger' : oslabeni >= maxOsl * 0.9 ? 'warn' : '';
  } else {
    vOsl.textContent = '–';
    vOsl.className   = '';
  }

  const vFights = card.querySelector('.v-fights');
  if (fight_current != null && fight_total != null) {
    vFights.textContent = `${fight_current}/${fight_total}`;
    vFights.className   = (fight_total - fight_current) <= 5 ? 'warn' : '';
  } else {
    vFights.textContent = '–/–';
    vFights.className   = '';
  }

  const vSector = card.querySelector('.v-sector');
  vSector.textContent = sector_found ? '✓ Nalezen' : '–';

  const errEl = card.querySelector('.error-msg');
  if (last_error) {
    errEl.textContent  = last_error;
    errEl.style.display = '';
  } else {
    errEl.style.display = 'none';
  }
}

// ---- Calibration screenshot -----------------------------------------
function showCalibScreenshot(data) {
  const { server: sid, image_b64, width, height } = data;
  const card = document.querySelector(`[data-server="${sid}"]`);
  if (!card) return;

  const panel   = card.querySelector('.calib-panel');
  const canvas  = card.querySelector('.calib-canvas');
  const overlay = card.querySelector('.overlay');

  panel.classList.add('open');

  const img  = new Image();
  img.onload = () => {
    canvas.width  = img.width;
    canvas.height = img.height;
    canvas.getContext('2d').drawImage(img, 0, 0);
    // Redraw existing regions on top of new screenshot (don't clear them)
    redrawOverlay(sid, overlay, canvas);
  };
  img.src = 'data:image/png;base64,' + image_b64;
}

// ---- Flash saved indicator ------------------------------------------
function flashSaved(sid) {
  const card = document.querySelector(`[data-server="${sid}"]`);
  if (!card) return;
  const btn  = card.querySelector('.btn-save-cfg');
  const orig = btn.textContent;
  btn.textContent = '✓ Uloženo';
  btn.classList.add('saved-anim');
  setTimeout(() => { btn.textContent = orig; btn.classList.remove('saved-anim'); }, 1200);
}

// ---- Show card error ------------------------------------------------
function showCardError(sid, msg) {
  const card = document.querySelector(`[data-server="${sid}"]`);
  if (!card) return;
  const errEl = card.querySelector('.error-msg');
  errEl.textContent  = msg;
  errEl.style.display = '';
}

// ---- HTML escape helper ---------------------------------------------
function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
