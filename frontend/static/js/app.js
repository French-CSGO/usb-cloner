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
  const d = await api('GET', '/storage/info').catch(() => null);
  if (!d) return;
  state.sshdMounted = d.sshd?.mounted ?? d.mounted ?? false;
  state.ssdPath     = d.ssd?.path  ?? d.path ?? '';
  state.sshdPath    = d.sshd?.path ?? '';

  const sshd = state.sshdMounted;
  document.getElementById('storage-block').innerHTML = `
    <div class="storage-row">
      <span class="storage-icon">💾</span>
      <div class="storage-info">
        <span class="storage-label">SSD</span>
        <span class="storage-path">${esc(state.ssdPath)}</span>
      </div>
      <span class="sshd-badge mounted">READY</span>
    </div>
    <div class="storage-row" style="margin-top:6px">
      <span class="storage-icon">🗄️</span>
      <div class="storage-info">
        <span class="storage-label">SSHD</span>
        <span class="storage-path">${esc(state.sshdPath)}</span>
      </div>
      <span class="sshd-badge ${sshd ? 'mounted' : 'unmounted'}">${sshd ? 'MOUNTED' : 'UNMOUNTED'}</span>
    </div>
    <div class="sshd-actions" style="margin-top:8px">
      <button class="btn btn-green btn-sm" onclick="openModal('sshd-mount')">Mount</button>
      <button class="btn btn-ghost btn-sm" onclick="doUnmountSshd()">Unmount</button>
      <button class="btn btn-ghost btn-sm" onclick="refreshDevices()">⟳</button>
    </div>`;
}

async function refreshDevices() {
  const [devs, assoc] = await Promise.all([
    api('GET', '/devices').catch(() => []),
    api('GET', '/assignments').catch(() => ({})),
  ]);
  state.devices     = devs;
  state.assignments = assoc;
  renderDevices();
  // Only rebuild assign modal if it is NOT currently open — prevents wiping
  // fields the user is actively filling in during auto-refresh.
  if (document.getElementById('modal-assign').classList.contains('hidden')) {
    updateAssignModal();
  }
  updateChangeDiskSelect();
}

async function refreshProfiles() {
  const [ssd, combined] = await Promise.all([
    api('GET', '/profiles/ssd').catch(() => []),
    api('GET', '/profiles/combined').catch(() => []),
  ]);
  state.profiles         = ssd;
  state.profilesCombined = combined;
  renderProfiles();
  renderSyncTable();
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
    const player = d.player || state.assignments[d.uid] || state.assignments[d.name];
    const playerHtml = player
      ? `<span class="player-badge">${esc(player)}</span>`
      : `<span class="no-player">unassigned</span>`;
    const model  = [d.vendor, d.model].filter(Boolean).join(' ').trim() || d.tran;
    const serial = d.serial
      ? `<div class="device-serial">S/N ${esc(d.serial)}</div>` : '';
    return `
      <div class="device-card" onclick="selectDevice('${esc(d.name)}')">
        <div class="device-name">
          /dev/${esc(d.name)}
          <span class="size-tag">${esc(d.size)}</span>
        </div>
        <div class="device-vendor">${esc(model)}</div>
        ${serial}
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
    const cancelBtn = (status === 'running' || status === 'pending')
      ? `<button class="task-cancel" title="Cancel" onclick="cancelTask('${esc(t.job_id)}','${esc(t.task_id)}')">✕</button>`
      : '';
    return `
      <div class="task-row">
        <span class="task-label" title="${esc(label)}">${esc(label)}</span>
        <div class="task-bar">
          <div class="task-fill ${status}" style="width:${pct}%"></div>
        </div>
        <span class="task-pct">${pct}%</span>
        <span class="task-speed">${esc(speed)}</span>
        <span class="task-status ${status}">${status}</span>
        ${cancelBtn}
      </div>`;
  }).join('');
}

async function cancelTask(jobId, taskId) {
  await api('DELETE', `/jobs/${jobId}/tasks/${taskId}`).catch(() => null);
  log(`Task ${taskId} cancelled`, 'warn');
}

// ── tabs ──────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
  document.getElementById(`tab-${name}`)?.classList.add('active');
  document.getElementById(`pane-${name}`)?.classList.remove('hidden');
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
    const current = state.assignments[d.uid] || state.assignments[d.name] || '';
    const serialNote = d.serial
      ? `<span class="assign-serial">${esc(d.serial)}</span>` : '';
    return `
      <div class="form-field">
        <label>/dev/${esc(d.name)} — ${esc(d.size)} ${serialNote}</label>
        <input type="text" class="assign-input" data-uid="${esc(d.uid)}"
               value="${esc(current)}" placeholder="player name (blank = skip)">
      </div>`;
  }).join('');
}

async function doAssign() {
  const inputs = document.querySelectorAll('.assign-input');
  // Preserve assignments for keys not currently connected (they keep their uid entry)
  const currentUids = new Set(state.devices.map(d => d.uid));
  const newAssoc = {};
  for (const [k, v] of Object.entries(state.assignments)) {
    if (!currentUids.has(k)) newAssoc[k] = v;
  }
  inputs.forEach(inp => {
    const uid    = inp.dataset.uid;
    const player = inp.value.trim();
    if (player) newAssoc[uid] = player;
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
  sel.innerHTML = state.devices.map(d => {
    const player = d.player || state.assignments[d.uid] || state.assignments[d.name] || 'unassigned';
    return `<option value="${esc(d.name)}">/dev/${esc(d.name)} — ${esc(player)}</option>`;
  }).join('');
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

// ── dual storage sync ─────────────────────────────────────────

function renderSyncTable() {
  const el = document.getElementById('sync-table');
  if (!el) return;
  const rows = state.profilesCombined || [];
  if (!rows.length) {
    el.innerHTML = '<div class="no-profiles">No profiles on either storage</div>';
    return;
  }
  el.innerHTML = rows.map(p => {
    const onSsd  = p.on_ssd;
    const onSshd = p.on_sshd;
    const ssdIcon  = onSsd  ? '<span style="color:var(--green)">SSD ✓</span>'
                            : '<span style="color:var(--txt3)">SSD —</span>';
    const sshdIcon = onSshd ? '<span style="color:var(--cyan)">SSHD ✓</span>'
                            : '<span style="color:var(--txt3)">SSHD —</span>';
    const pullBtn = onSshd
      ? `<button class="btn btn-ghost btn-sm" onclick="syncOne('pull','${esc(p.name)}')">↓ Pull</button>`
      : '';
    const pushBtn = onSsd
      ? `<button class="btn btn-ghost btn-sm" onclick="syncOne('push','${esc(p.name)}')">↑ Push</button>`
      : '';
    return `
      <div class="profile-row">
        <span class="profile-name">${esc(p.name)}</span>
        <span style="display:flex;gap:6px;font-size:10px">${ssdIcon} ${sshdIcon}</span>
        <div class="profile-actions">${pullBtn}${pushBtn}
          <button class="icon-btn del" title="Delete from SSD"
            onclick="deleteProfile('${esc(p.name)}')">✕</button>
        </div>
      </div>`;
  }).join('');
}

async function syncAll(direction) {
  if (!state.sshdMounted) { toast('SSHD not mounted', 'err'); return; }
  log(`Sync ${direction === 'pull' ? 'SSHD→SSD' : 'SSD→SSHD'} (all)…`, 'info');
  const r = await api('POST', `/sync/${direction}`).catch(() => null);
  if (r?.job_id) toast(`Sync job ${r.job_id} started`, 'info');
}

async function syncOne(direction, name) {
  if (!state.sshdMounted) { toast('SSHD not mounted', 'err'); return; }
  log(`Sync ${direction} ${name}…`, 'info');
  const r = await api('POST', `/sync/${direction}`, { names: [name] }).catch(() => null);
  if (r?.job_id) toast(`Sync ${name} started`, 'info');
}

// ── disk browser ─────────────────────────────────────────────
let _allDisks = [];

async function openDiskBrowser() {
  openModal('disk-browser');
  await loadDiskBrowser();
}

async function loadDiskBrowser() {
  const body = document.getElementById('disk-browser-body');
  body.innerHTML = '<div style="color:var(--txt3);text-align:center;padding:20px">Loading…</div>';
  _allDisks = await api('GET', '/disks').catch(() => []);
  renderDiskBrowser();
}

function renderDiskBrowser() {
  const body = document.getElementById('disk-browser-body');
  if (!_allDisks.length) {
    body.innerHTML = '<div style="color:var(--txt3);text-align:center;padding:20px">No block devices found</div>';
    return;
  }
  body.innerHTML = _allDisks.map(d => {
    const tagClass = d.is_sshd ? 'sshd'
                   : d.is_usb  ? 'usb'
                   : d.tran === 'nvme' ? 'nvme'
                   : d.tran === 'sata' ? 'sata' : 'unknwn';
    const tagLabel = d.is_sshd ? 'SSHD'
                   : d.is_usb  ? 'USB'
                   : (d.tran || '?').toUpperCase();
    const info = [d.vendor, d.model].filter(Boolean).join(' ') || `tran: ${d.tran}`;

    const parts = (d.partitions || []).map(p => `
      <div class="part-row">
        <span class="part-name">/dev/${esc(p.name)}</span>
        <span class="disk-size">${esc(p.size)}</span>
        <span class="part-fs">${esc(p.fstype || '—')}</span>
        <span class="part-mnt">${p.mountpoint ? '⇒ ' + esc(p.mountpoint) : ''}</span>
      </div>`).join('');

    const useMountBtn = !d.is_sshd ? `
      <button class="btn btn-ghost btn-sm"
        onclick="prefillSshd('${esc(d.name)}')">
        Use as SSHD
      </button>` : '';
    const useMasterBtn = `
      <button class="btn btn-ghost btn-sm"
        onclick="prefillMaster('${esc(d.name)}')">
        Use as Master
      </button>`;

    return `
      <div class="disk-entry">
        <div class="disk-entry-header">
          <input type="checkbox" class="usb-chk" data-disk="${esc(d.name)}"
            ${d.is_usb ? 'checked' : ''} ${d.is_sshd ? 'disabled' : ''}
            onchange="updateUsbCheckPreview()">
          <span class="disk-dev">/dev/${esc(d.name)}</span>
          <span class="disk-size">${esc(d.size)}</span>
          <span class="disk-info">${esc(info)}</span>
          <span class="disk-tag ${tagClass}">${tagLabel}</span>
          ${d.player ? `<span class="player-badge">${esc(d.player)}</span>` : ''}
        </div>
        ${parts ? `<div class="disk-parts">${parts}</div>` : ''}
        <div class="disk-actions">${useMountBtn}${useMasterBtn}</div>
      </div>`;
  }).join('');
}

function updateUsbCheckPreview() {
  // visual feedback only — actual save on "Apply"
}

async function saveUsbSelection() {
  const checked = [...document.querySelectorAll('.usb-chk:checked')]
    .map(c => c.dataset.disk);
  await api('POST', '/devices/select', { names: checked });
  toast(`USB selection saved (${checked.length} disk${checked.length !== 1 ? 's' : ''})`, 'ok');
  log(`USB keys set: ${checked.join(', ') || '(none)'}`, 'ok');
  closeModal('disk-browser');
  await refreshDevices();
}

function prefillSshd(name) {
  document.getElementById('sshd-disk').value = name;
  closeModal('disk-browser');
  openModal('sshd-mount');
}

function prefillMaster(name) {
  document.getElementById('master-disk').value = name;
  closeModal('disk-browser');
  openModal('create-master');
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
