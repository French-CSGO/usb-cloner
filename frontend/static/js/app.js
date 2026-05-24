/* ═══════════════════════════════════════════════════════════════
   USB KEY MANAGER — frontend JS
   Socket.io + REST API + live UI updates
═══════════════════════════════════════════════════════════════ */

'use strict';

// ── state ─────────────────────────────────────────────────────
const state = {
  devices:     [],
  assignments: {},
  profiles:    [],
  tasks:       {},   // task_id → latest progress data
  sshdMounted: false,
};

// ── Socket.io ─────────────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
  setWsStatus(true);
  log('Connected to USB Manager', 'ok');
  pollAll();
});

socket.on('disconnect', () => {
  setWsStatus(false);
  log('Disconnected — reconnecting…', 'err');
});

socket.on('progress', (data) => {
  state.tasks[data.task_id] = data;
  renderTasks();
});

socket.on('job_complete', (data) => {
  const type = data.errors === 0 ? 'ok' : 'err';
  const msg  = data.errors === 0
    ? `Operation complete — ${data.ok} task(s) done`
    : `Operation done — ${data.ok} OK, ${data.errors} error(s)`;
  toast(msg, type);
  log(msg, type);
  // Clean done tasks after 5 s
  setTimeout(() => {
    Object.keys(state.tasks).forEach(k => {
      if (['done', 'error'].includes(state.tasks[k]?.status))
        delete state.tasks[k];
    });
    renderTasks();
    pollAll();
  }, 5000);
});

// ── WebSocket status ──────────────────────────────────────────
function setWsStatus(ok) {
  const dot   = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');
  dot.className   = 'dot' + (ok ? ' live' : '');
  label.textContent = ok ? 'LIVE' : 'OFFLINE';
}

// ── API helper ────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  try {
    const r = await fetch('/api' + path, opts);
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } catch (e) {
    toast(e.message, 'err');
    log(e.message, 'err');
    throw e;
  }
}

// ── poll ──────────────────────────────────────────────────────
async function pollAll() {
  await Promise.all([
    refreshMount(),
    refreshDevices(),
    refreshProfiles(),
  ]);
}

async function refreshMount() {
  const d = await api('GET', '/mount/status').catch(() => null);
  if (!d) return;
  state.sshdMounted = d.mounted;
  const badge = document.getElementById('sshd-badge');
  badge.textContent = d.mounted ? 'MOUNTED' : 'UNMOUNTED';
  badge.className   = 'sshd-badge ' + (d.mounted ? 'mounted' : 'unmounted');
}

async function refreshDevices() {
  const [devs, assoc] = await Promise.all([
    api('GET', '/devices').catch(() => []),
    api('GET', '/assignments').catch(() => ({})),
  ]);
  state.devices     = devs;
  state.assignments = assoc;
  renderDevices();
  updateAssignModal();
  updateChangeDiskSelect();
}

async function refreshProfiles() {
  const profs = await api('GET', '/profiles').catch(() => []);
  state.profiles = profs;
  renderProfiles();
}

// Auto-refresh every 10 s
setInterval(pollAll, 10000);

// ── render devices ────────────────────────────────────────────
function renderDevices() {
  const el = document.getElementById('device-list');
  if (!state.devices.length) {
    el.innerHTML = '<div class="no-devices">No USB keys detected</div>';
    return;
  }
  el.innerHTML = state.devices.map(d => {
    const player = d.player || state.assignments[d.name];
    const playerHtml = player
      ? `<span class="player-badge">${esc(player)}</span>`
      : `<span class="no-player">unassigned</span>`;
    const model = [d.vendor, d.model].filter(Boolean).join(' ').trim() || d.tran;
    return `
      <div class="device-card" onclick="selectDevice('${esc(d.name)}')">
        <div class="device-name">
          /dev/${esc(d.name)}
          <span class="size-tag">${esc(d.size)}</span>
        </div>
        <div class="device-vendor">${esc(model)}</div>
        <div class="device-player">${playerHtml}</div>
      </div>`;
  }).join('');
}

function selectDevice(name) {
  document.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
  const cards = document.querySelectorAll('.device-card');
  state.devices.forEach((d, i) => {
    if (d.name === name) cards[i]?.classList.add('selected');
  });
}

// ── render profiles ───────────────────────────────────────────
function renderProfiles() {
  const el = document.getElementById('profiles-list');
  if (!state.profiles.length) {
    el.innerHTML = '<div class="no-profiles">No profiles saved</div>';
    return;
  }
  el.innerHTML = state.profiles.map(p => `
    <div class="profile-row">
      <span class="profile-name">${esc(p.name)}</span>
      <span class="profile-size">${fmtBytes(p.size)}</span>
      <div class="profile-actions">
        <button class="icon-btn del" title="Delete" onclick="deleteProfile('${esc(p.name)}')">✕</button>
      </div>
    </div>`).join('');
}

// ── render tasks / jobs ───────────────────────────────────────
function renderTasks() {
  const el    = document.getElementById('task-list');
  const count = document.getElementById('job-count');
  const tasks = Object.values(state.tasks);

  if (!tasks.length) {
    el.innerHTML = '<div class="no-jobs">No active operations</div>';
    count.textContent = '0';
    return;
  }
  count.textContent = tasks.filter(t => t.status === 'running').length;

  el.innerHTML = tasks.map(t => {
    const pct    = t.percent || 0;
    const status = t.status  || 'pending';
    const speed  = t.speed   || '—';
    const label  = t.label   || t.task_id;
    const eta    = t.eta != null ? `ETA ${fmtEta(t.eta)}` : '';
    return `
      <div class="task-row">
        <span class="task-label" title="${esc(label)}">${esc(label)}</span>
        <div class="task-bar">
          <div class="task-fill ${status}" style="width:${pct}%"></div>
        </div>
        <span class="task-pct">${pct}%</span>
        <span class="task-speed">${esc(speed)}</span>
        <span class="task-status ${status}">${status}</span>
      </div>`;
  }).join('');
}

// ── modal helpers ─────────────────────────────────────────────
function openModal(name) {
  if (name === 'assign') updateAssignModal();
  if (name === 'change-player') updateChangeDiskSelect();
  document.getElementById(`modal-${name}`).classList.remove('hidden');
}

function closeModal(name) {
  document.getElementById(`modal-${name}`).classList.add('hidden');
}

// Close on overlay click
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', e => {
    if (e.target === el) el.classList.add('hidden');
  });
});

// ── generic confirm ───────────────────────────────────────────
function showConfirm(title, msg, onOk) {
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-msg').textContent   = msg;
  const btn = document.getElementById('confirm-ok-btn');
  btn.onclick = () => { closeModal('confirm'); onOk(); };
  openModal('confirm');
}

// ── SSHD mount / unmount ──────────────────────────────────────
async function doMountSshd() {
  const disk = document.getElementById('sshd-disk').value.trim();
  if (!disk) return;
  closeModal('sshd-mount');
  log(`Mounting /dev/${disk}…`, 'info');
  const r = await api('POST', '/mount', { disk }).catch(() => null);
  if (r?.success) {
    toast(`SSHD mounted`, 'ok');
    log(r.message, 'ok');
    await pollAll();
  }
}

async function doUnmountSshd() {
  const r = await api('DELETE', '/mount').catch(() => null);
  toast(r?.success ? 'SSHD unmounted' : 'Unmount failed', r?.success ? 'ok' : 'err');
  await refreshMount();
}

// ── create master ─────────────────────────────────────────────
async function doCreateMaster() {
  const disk  = document.getElementById('master-disk').value.trim();
  if (!disk) return;
  closeModal('create-master');
  log(`Creating master images from /dev/${disk}…`, 'info');
  const r = await api('POST', '/operations/create-master', {
    disk,
    partition_win: pWin(),
    partition_cs2: pCs2(),
  }).catch(() => null);
  if (r?.job_id) toast(`Job ${r.job_id} started`, 'info');
}

// ── deploy ────────────────────────────────────────────────────
function confirmDeploy() {
  showConfirm(
    'Deploy All Keys',
    `Flash Windows + CS2 blank to ${state.devices.length} USB key(s)? All data will be overwritten.`,
    doDeploy
  );
}

async function doDeploy() {
  log('Deploying Windows + CS2 to all keys…', 'info');
  const r = await api('POST', '/operations/deploy', {
    partition_win: pWin(), partition_cs2: pCs2(),
  }).catch(() => null);
  if (r?.job_id) toast(`Deploy job ${r.job_id} started`, 'info');
}

// ── save ──────────────────────────────────────────────────────
function confirmSave() {
  showConfirm('Save Players', 'Save current player CS2 configs to SSHD?', doSave);
}

async function doSave() {
  log('Saving player configs…', 'info');
  const r = await api('POST', '/operations/save', { partition_cs2: pCs2() }).catch(() => null);
  if (r?.job_id) toast(`Save job ${r.job_id} started`, 'info');
}

// ── load ──────────────────────────────────────────────────────
function confirmLoad() {
  showConfirm('Load Players', 'Restore player configs from SSHD to their assigned keys?', doLoad);
}

async function doLoad() {
  log('Loading player configs…', 'info');
  const r = await api('POST', '/operations/load', { partition_cs2: pCs2() }).catch(() => null);
  if (r?.job_id) toast(`Load job ${r.job_id} started`, 'info');
}

// ── reset ─────────────────────────────────────────────────────
function confirmReset() {
  showConfirm(
    '⚠ Reset CS2 Blank',
    `Wipe CS2 partition on ALL ${state.devices.length} key(s) with blank image? Player configs will be lost!`,
    doReset
  );
}

async function doReset() {
  log('Resetting CS2 blank on all keys…', 'warn');
  const r = await api('POST', '/operations/reset', { partition_cs2: pCs2() }).catch(() => null);
  if (r?.job_id) toast(`Reset job ${r.job_id} started`, 'info');
}

// ── assign players ────────────────────────────────────────────
function updateAssignModal() {
  const container = document.getElementById('assign-fields');
  if (!state.devices.length) {
    container.innerHTML = '<div class="no-devices" style="color:var(--txt2)">No USB keys detected.</div>';
    return;
  }
  container.innerHTML = state.devices.map(d => {
    const current = state.assignments[d.name] || '';
    return `
      <div class="form-field">
        <label>/dev/${esc(d.name)} (${esc(d.size)})</label>
        <input type="text" class="assign-input" data-disk="${esc(d.name)}"
               value="${esc(current)}" placeholder="player name (blank = skip)">
      </div>`;
  }).join('');
}

async function doAssign() {
  const inputs = document.querySelectorAll('.assign-input');
  const newAssoc = { ...state.assignments };
  inputs.forEach(inp => {
    const disk   = inp.dataset.disk;
    const player = inp.value.trim();
    if (player) newAssoc[disk] = player;
    else        delete newAssoc[disk];
  });
  closeModal('assign');
  await api('POST', '/assignments', newAssoc);
  toast('Assignments saved', 'ok');
  log('Player assignments updated', 'ok');
  state.assignments = newAssoc;
  renderDevices();
}

// ── change player ─────────────────────────────────────────────
function updateChangeDiskSelect() {
  const sel = document.getElementById('change-disk');
  sel.innerHTML = state.devices.map(d =>
    `<option value="${esc(d.name)}">/dev/${esc(d.name)} — ${esc(d.player || state.assignments[d.name] || 'unassigned')}</option>`
  ).join('');
}

async function doChangePlayer() {
  const disk       = document.getElementById('change-disk').value;
  const newPlayer  = document.getElementById('change-new-player').value.trim();
  const saveOld    = document.getElementById('change-save-old').checked;
  if (!newPlayer) { toast('Enter a player name', 'err'); return; }
  closeModal('change-player');
  log(`Changing player on /dev/${disk} → ${newPlayer}…`, 'info');
  const r = await api('POST', '/operations/change-player', {
    disk, new_player: newPlayer, save_old: saveOld, partition_cs2: pCs2(),
  }).catch(() => null);
  if (r?.job_id) toast(`Change-player job ${r.job_id} started`, 'info');
}

// ── profiles ──────────────────────────────────────────────────
async function deleteProfile(name) {
  showConfirm('Delete Profile', `Delete profile "${name}"? This cannot be undone.`, async () => {
    await api('DELETE', `/profiles/${encodeURIComponent(name)}`);
    toast(`Profile "${name}" deleted`, 'ok');
    log(`Profile deleted: ${name}`, 'ok');
    await refreshProfiles();
  });
}

async function doRenameProfile() {
  const oldName = document.getElementById('rename-old').value.trim();
  const newName = document.getElementById('rename-new').value.trim();
  if (!oldName || !newName) return;
  closeModal('rename-profile');
  await api('POST', '/profiles/rename', { old_name: oldName, new_name: newName });
  toast(`Renamed ${oldName} → ${newName}`, 'ok');
  log(`Profile renamed: ${oldName} → ${newName}`, 'ok');
  await refreshProfiles();
}

async function doCopyProfile() {
  const src = document.getElementById('copy-src').value.trim();
  const dst = document.getElementById('copy-dst').value.trim();
  if (!src || !dst) return;
  closeModal('copy-profile');
  await api('POST', '/profiles/copy', { src, dst });
  toast(`Copied ${src} → ${dst}`, 'ok');
  log(`Profile copied: ${src} → ${dst}`, 'ok');
  await refreshProfiles();
}

// ── console log ───────────────────────────────────────────────
function log(msg, type = '') {
  const body = document.getElementById('console-body');
  const now  = new Date().toLocaleTimeString('fr-FR', { hour12: false });
  const line = document.createElement('div');
  line.className = `console-line ${type}`;
  line.innerHTML = `<span class="ts">${now}</span><span class="msg">${esc(msg)}</span>`;
  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
  // Keep max 200 lines
  while (body.children.length > 200) body.removeChild(body.firstChild);
}

// ── toast ─────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── helpers ───────────────────────────────────────────────────
const pWin = () => document.getElementById('part-win').value.trim() || '1';
const pCs2 = () => document.getElementById('part-cs2').value.trim() || '2';

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtBytes(b) {
  if (!b) return '?';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(1)} ${u[i]}`;
}

function fmtEta(s) {
  if (s < 60)   return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}m${s%60}s`;
  return `${Math.floor(s/3600)}h${Math.floor((s%3600)/60)}m`;
}
