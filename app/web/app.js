/* Coffee Chat Tracker — interface logic. No frameworks, no network. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

let STATE = {
  people: [], settings: {}, statuses: [], actions: [], coverage: [], questions: [],
  chats: { current: [], upcoming: [] },
};
let CURRENT = null;        // person open in the drawer

const STATUS_TONE = {
  uninitiated: '', outreach_sent: 'warn', awaiting_reply: 'warn',
  scheduled: 'gold', chat_done: 'ok', thankyou_sent: 'ok',
  no_response: 'bad',
};

/* ------------------------------------------------------------- plumbing */

let OFFLINE = false;

async function api(path, method = 'GET', body) {
  const opts = { method, headers: { 'X-CCT-Token': window.CCT_TOKEN } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(path, opts);
  } catch (netError) {
    // The server is gone. Say so loudly rather than doing nothing, which is
    // indistinguishable from the app ignoring you.
    goOffline();
    throw new Error('Lost contact with the app.');
  }
  if (OFFLINE) goOnline();

  let data;
  try { data = await res.json(); } catch (e) { data = { ok: false, error: 'Bad reply from the app server.' }; }
  if (res.status === 403) {
    goOffline('This window is out of date — the app was restarted since you opened it.');
    throw new Error('Session expired.');
  }
  if (!res.ok && data.error) throw new Error(data.error);
  return data;
}

function goOffline(message) {
  if (OFFLINE) return;
  OFFLINE = true;
  let bar = document.getElementById('offline-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'offline-bar';
    document.body.appendChild(bar);
  }
  bar.innerHTML = `<strong>${esc(message || 'Lost contact with the app.')}</strong>
    Nothing you type right now is being saved.
    <button class="btn sm" onclick="location.reload()">Reload</button>
    <span class="small">If reloading does not help, quit and reopen Coffee Chat Tracker.</span>`;
  bar.className = 'offline-bar show';
}

function goOnline() {
  OFFLINE = false;
  const bar = document.getElementById('offline-bar');
  if (bar) bar.className = 'offline-bar';
}

function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* Files ride to the local server as base64 inside the usual JSON call, so
   there is one request path and one place the token is checked. */
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.onerror = () => reject(new Error('That file could not be read.'));
    reader.readAsDataURL(file);
  });
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    // Clipboard API can be refused; fall back to the old selection trick.
    try {
      const scratch = document.createElement('textarea');
      scratch.value = text;
      scratch.style.cssText = 'position:fixed;opacity:0;left:-9999px';
      document.body.appendChild(scratch);
      scratch.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(scratch);
      return ok;
    } catch (e2) {
      return false;
    }
  }
}

let toastTimer;
function toast(message, bad = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('bad', !!bad);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), bad ? 6000 : 2800);
}

function statusLabel(key) {
  const found = STATE.statuses.find(s => s.key === key);
  return found ? found.label : (key || '—');
}

function dateLabel(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (isNaN(d)) return String(value).slice(0, 10);
  const days = Math.round((Date.now() - d.getTime()) / 86400000);
  const stamp = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days > 1 && days < 30) return `${stamp} · ${days}d ago`;
  if (days < 0) return stamp;
  return stamp;
}

function chatTimeLabel(value) {
  if (!value) return '';
  const d = new Date(value);
  if (isNaN(d)) return '';
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
    + ' at ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/* ------------------------------------------------------------ rendering */

async function refresh() {
  STATE = await api('/api/state');
  renderToday();
  renderPipeline();
  renderConnections();
  fillSettings();
  updateNavCounts();
  if (CURRENT) openPerson(CURRENT.id, true);
}

/* The server checks both on startup, so these dots are usually already
   answered by the time the window paints. */
function renderConnections() {
  const cal = STATE.calendar || {};
  if (!cal.checked) {
    setStatusDot('#status-cal', 'warn', 'Calendar — checking…');
  } else if (cal.ok && cal.demo) {
    setStatusDot('#status-cal', 'warn', 'Calendar: demo data');
  } else if (cal.ok) {
    setStatusDot('#status-cal', 'ok', 'Calendar connected');
  } else {
    setStatusDot('#status-cal', 'bad', 'Calendar blocked');
  }

  const out = STATE.outlook || {};
  if (!out.checked) {
    setStatusDot('#status-outlook', 'warn', 'Outlook — checking…');
  } else if (out.flavor === 'classic') {
    setStatusDot('#status-outlook', 'ok', 'Outlook connected');
  } else if (out.flavor === 'demo') {
    setStatusDot('#status-outlook', 'warn', 'Outlook: demo');
  } else if (out.flavor === 'unscriptable') {
    setStatusDot('#status-outlook', 'warn', 'Outlook limited');
  } else {
    setStatusDot('#status-outlook', 'bad', 'Outlook unavailable');
  }
}

function updateNavCounts() {
  $('#nav-actions').textContent = STATE.actions.length;
  $('#nav-actions').classList.toggle('hot', STATE.actions.some(a => a.urgency === 'overdue'));
  $('#nav-people').textContent = STATE.people.length;
}

function renderToday() {
  const people = STATE.people;
  const count = key => people.filter(p => p.status === key).length;
  const chatted = people.filter(p => ['chat_done', 'thankyou_sent'].includes(p.status)).length;
  const overdue = STATE.actions.filter(a => a.urgency === 'overdue').length;

  $('#stats').innerHTML = [
    { value: people.length, label: 'People tracked' },
    { value: chatted, label: 'Chats completed' },
    { value: count('scheduled'), label: 'Scheduled' },
    { value: count('outreach_sent') + count('awaiting_reply'), label: 'Awaiting reply' },
    { value: overdue, label: 'Overdue actions', alert: overdue > 0 },
  ].map(s => `<div class="stat${s.alert ? ' alert' : ''}">
      <div class="value">${s.value}</div><div class="label">${s.label}</div></div>`).join('');

  const banners = [];
  if (STATE.platform && STATE.platform.demo) {
    banners.push(`<div class="banner warn"><strong>Demo mode.</strong> This copy is not
      running on macOS, so calendar and Outlook data are simulated.</div>`);
  }
  if (!STATE.settings.user_name) {
    banners.push(`<div class="banner info">Add your name and program in
      <a href="#" data-goto="settings">Settings</a> so drafts sign off properly.</div>`);
  }
  $('#today-banners').innerHTML = banners.join('');

  $('#actions').innerHTML = STATE.actions.length ? STATE.actions.map(a => `
    <div class="action ${a.urgency}">
      <div class="grow">
        <span class="who">${esc(a.name)}</span>
        <span class="muted small">${a.firm ? ' · ' + esc(a.firm) : ''}</span>
        ${a.tier === 'A' ? '<span class="chip gold" style="margin-left:6px">Tier A</span>' : ''}
        <div class="detail">${esc(a.label)} — ${esc(a.detail)}</div>
      </div>
      ${a.kind === 'thankyou' ? `<button class="btn gold sm" data-draft="thankyou" data-id="${a.person_id}">Draft thank-you</button>` : ''}
      ${a.kind === 'followup' ? `<button class="btn gold sm" data-draft="followup" data-id="${a.person_id}">Draft nudge</button>` : ''}
      <button class="btn sm" data-open="${a.person_id}">Open</button>
      <button class="btn ghost sm" data-resolve="${esc(a.key)}"
        title="Tick this off — it goes to the bin below">Done</button>
    </div>`).join('')
    : `<div class="card empty"><div class="big">✓</div>Nothing overdue. Good place to be.</div>`;

  // Ticked off this session, and still recoverable until the app is closed.
  const binned = STATE.bin || [];
  $('#action-bin').innerHTML = binned.length ? `
    <details class="paste-box" style="margin-top:14px">
      <summary>Bin — ${binned.length} item${binned.length === 1 ? '' : 's'} ticked off</summary>
      <p class="small muted" style="margin:10px 0">Ticked off stays ticked off — it
        won't come back on its own. Put one back at any point; the list below
        only covers what you ticked off this session, and starts empty again
        next time you open the app.</p>
      ${binned.map(b => `
        <div class="action low">
          <div class="grow">
            <span class="who">${esc(b.person_name || '')}</span>
            <div class="detail">${esc(b.label)}${b.detail ? ' — ' + esc(b.detail) : ''}</div>
          </div>
          <button class="btn sm" data-restore="${esc(b.key)}">Put back</button>
        </div>`).join('')}
    </details>` : '';

  const chats = STATE.chats || { current: [], upcoming: [] };

  // Happening now — from 15 minutes before the start until 30 minutes after it.
  $('#current-chat').innerHTML = chats.current.length ? chats.current.map(c => {
    const away = c.minutes_away;
    const when = away > 0 ? `starts in ${away} min`
      : away === 0 ? 'starting now'
      : `started ${Math.abs(away)} min ago`;
    return `<div class="now-card">
      <div class="now-label">Happening now</div>
      <div class="now-who">${esc(c.name)}</div>
      <div class="small muted">${esc([c.firm, c.role].filter(Boolean).join(' · '))}</div>
      <div class="now-when">${esc(c.when_label)} — ${esc(when)}</div>
      <div class="row" style="gap:6px;margin-top:10px">
        <button class="btn gold sm" data-prep="${c.person_id}">Prep</button>
        <button class="btn sm" data-open="${c.person_id}">Open</button>
      </div>
    </div>`;
  }).join('') : '';

  $('#upcoming').innerHTML = chats.upcoming.length ? chats.upcoming.map(u => `
    <div class="action">
      <div class="grow">
        <span class="who">${esc(u.name)}</span>
        <span class="muted small">${u.firm ? ' · ' + esc(u.firm) : ''}${u.role ? ' · ' + esc(u.role) : ''}</span>
        <div class="detail">${esc(u.when_label)}</div>
      </div>
      <button class="btn gold sm" data-prep="${u.person_id}">Prep</button>
      <button class="btn sm" data-open="${u.person_id}">Open</button>
    </div>`).join('')
    : `<div class="card empty small">No chats on the calendar yet. Set a date on a
        person once they confirm.</div>`;

  $('#coverage').innerHTML = STATE.coverage.length ? STATE.coverage.map(c => {
    const total = Math.max(c.total, 1);
    const pct = n => (n / total * 100).toFixed(1) + '%';
    return `<div class="cov">
      <div>${esc(c.firm)}</div>
      <div class="bar">
        <span class="done" style="width:${pct(c.chatted)}"></span>
        <span class="sched" style="width:${pct(c.scheduled)}"></span>
        <span class="pend" style="width:${pct(c.pending)}"></span>
      </div>
      <div class="small muted">${c.chatted} spoken / ${c.total}</div>
    </div>`;
  }).join('') + `<div class="small faint" style="margin-top:10px">
      <span style="color:var(--ok)">■</span> spoken with
      <span style="color:var(--gold-500);margin-left:8px">■</span> scheduled
      <span style="color:var(--text-faint);margin-left:8px">■</span> awaiting reply</div>`
    : `<div class="empty small">Add people to see where your coverage is thin.</div>`;
}

function renderPipeline() {
  const statusSel = $('#filter-status');
  if (statusSel.options.length <= 1) {
    STATE.statuses.forEach(s => statusSel.add(new Option(s.label, s.key)));
  }
  const firmSel = $('#filter-firm');
  const firms = [...new Set(STATE.people.map(p => p.firm).filter(Boolean))].sort();
  const keepFirm = firmSel.value;
  firmSel.innerHTML = '<option value="">All firms</option>' +
    firms.map(f => `<option${f === keepFirm ? ' selected' : ''}>${esc(f)}</option>`).join('');

  const term = $('#filter-search').value.trim().toLowerCase();
  const wantStatus = statusSel.value;
  const wantFirm = firmSel.value;

  const rows = STATE.people.filter(p => {
    if (wantStatus && p.status !== wantStatus) return false;
    if (wantFirm && p.firm !== wantFirm) return false;
    if (term) {
      const hay = `${p.name} ${p.firm} ${p.role} ${p.email}`.toLowerCase();
      if (!hay.includes(term)) return false;
    }
    return true;
  });

  $('#people-rows').innerHTML = rows.map(p => `
    <tr data-id="${p.id}">
      <td class="name" data-open="${p.id}">${esc(p.name)}
        ${p.is_alum ? '' : '<span class="chip warn" style="margin-left:5px">not alum</span>'}</td>
      <td data-open="${p.id}">${esc(p.firm || '—')}</td>
      <td class="muted" data-open="${p.id}">${esc(p.role || '—')}</td>
      <td><select data-status="${p.id}">${STATE.statuses.map(s =>
        `<option value="${s.key}"${s.key === p.status ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></td>
      <td class="muted small" data-open="${p.id}">${dateLabel(p.last_outbound_at || p.first_contact_at)}</td>
      <td class="muted small" data-open="${p.id}">${p.chat_at ? dateLabel(p.chat_at) : '—'}</td>
      <td><button class="btn ghost sm" data-open="${p.id}">›</button></td>
    </tr>`).join('');

  $('#pipeline-empty').innerHTML = rows.length ? '' :
    `<div class="card empty" style="margin-top:14px"><div class="big">☕</div>
      ${STATE.people.length ? 'Nothing matches those filters.'
        : 'No one here yet. Start with second-years and younger consultants — they say yes most.'}</div>`;

  renderPipelineTree();
}

/* Who you've talked to, grouped by company, each company's own referral
   chains nested inside it — a McKinsey contact introducing you to another
   McKinsey person nests under them; a referral across firms just starts its
   own root in the new firm's tree, since that's a separate relationship. */
let TREE_MINIMIZED = false;
const TREE_COLLAPSED_FIRMS = new Set();
const PRIORITY_FIRMS = ['mckinsey', 'bain', 'bcg', 'pwc', 'ey', 'kearney'];
const STATUS_DOT = {
  outreach_sent: 'var(--warn)', awaiting_reply: 'var(--warn)',
  scheduled: 'var(--gold-500)',
  chat_done: 'var(--ok)', thankyou_sent: 'var(--ok)',
};

function renderPipelineTree() {
  const box = $('#pipeline-tree');
  if (!box) return;
  const toggle = $('#tree-toggle');
  if (toggle) toggle.textContent = TREE_MINIMIZED ? 'Show tree' : 'Hide tree';
  box.style.display = TREE_MINIMIZED ? 'none' : '';
  if (TREE_MINIMIZED) return;

  // A firm's tree is for people you're actually tracking with something to
  // show — no LinkedIn on file yet, you haven't reached out at all, or you've
  // given up on them, and there's nothing here worth a branch.
  const HIDDEN_TREE_STATUS = new Set(['uninitiated', 'no_response']);
  const eligible = STATE.people.filter(p =>
    !HIDDEN_TREE_STATUS.has(p.status) && (p.linkedin_raw || '').trim());

  if (!eligible.length) {
    box.innerHTML = `<div class="card empty small">Nobody to show yet — a person
      needs a LinkedIn profile on file (and a status past "Uninitiated", other
      than "No response") to appear in the tree.</div>`;
    return;
  }

  const byFirm = new Map();
  eligible.forEach(p => {
    const firm = (p.firm || '').trim() || 'Unassigned';
    if (!byFirm.has(firm)) byFirm.set(firm, []);
    byFirm.get(firm).push(p);
  });

  const recency = (firm) => Math.max(...byFirm.get(firm).map(p =>
    Date.parse((p.created_at || '').replace(' ', 'T')) || 0));

  const firms = [...byFirm.keys()].sort((a, b) => {
    const ai = PRIORITY_FIRMS.indexOf(a.toLowerCase());
    const bi = PRIORITY_FIRMS.indexOf(b.toLowerCase());
    if (ai !== -1 || bi !== -1) {
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    }
    return recency(b) - recency(a);
  });

  const renderNode = (p, byId, childrenOf, depth) => {
    const kids = (childrenOf.get(p.id) || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    const color = STATUS_DOT[p.status] || 'var(--text-faint)';
    return `<div class="tree-node" style="margin-left:${depth * 20}px">
      <span class="tree-dot" style="background:${color}"></span>
      <button class="btn ghost sm" data-open="${p.id}">${esc(p.name)}</button>
      <span class="small muted">${esc(statusLabel(p.status))}${p.role ? ' · ' + esc(p.role) : ''}</span>
      ${kids.map(k => renderNode(k, byId, childrenOf, depth + 1)).join('')}
    </div>`;
  };

  box.innerHTML = firms.map(firm => {
    const members = byFirm.get(firm);
    const byId = new Map(members.map(p => [p.id, p]));
    const childrenOf = new Map();
    members.forEach(p => {
      if (p.referred_by && byId.has(p.referred_by)) {
        if (!childrenOf.has(p.referred_by)) childrenOf.set(p.referred_by, []);
        childrenOf.get(p.referred_by).push(p);
      }
    });
    const roots = members.filter(p => !(p.referred_by && byId.has(p.referred_by)))
      .sort((a, b) => a.name.localeCompare(b.name));
    const isOpen = !TREE_COLLAPSED_FIRMS.has(firm);

    return `<details class="paste-box tree-firm"${isOpen ? ' open' : ''} data-firm="${esc(firm)}">
      <summary>${esc(firm)} <span class="small faint">(${members.length})</span></summary>
      <div style="margin-top:8px">
        ${roots.map(r => renderNode(r, byId, childrenOf, 0)).join('')}
      </div>
    </details>`;
  }).join('');
}

/* -------------------------------------------------------------- drawer */

async function openPerson(id, quiet = false) {
  const person = await api('/api/person/' + id);
  if (!person) return;
  CURRENT = person;
  $('#d-name').textContent = person.name;
  $('#d-sub').innerHTML = `${esc(person.role || '')}${person.role && person.firm ? ' · ' : ''}${esc(person.firm || '')}
    <span class="chip ${STATUS_TONE[person.status] || ''}" style="margin-left:6px">${esc(statusLabel(person.status))}</span>`;
  $('#d-chat-time').textContent = person.chat_at ? '☕ ' + chatTimeLabel(person.chat_at) : '';

  const f = (id_, label, value, type = 'text') =>
    `<label class="field"><span>${label}</span><input type="${type}" data-f="${id_}" value="${esc(value || '')}"></label>`;

  // What every draft for this person will offer, until it is picked again —
  // and, once they've said yes, which one of these was actually accepted.
  let saved = null;
  try { saved = JSON.parse(person.offered_slots || 'null'); } catch (e) { saved = null; }
  const savedDays = (saved && saved.days) || [];
  const today = new Date().toISOString().slice(0, 10);
  const savedWindows = [];
  savedDays.forEach(day => (day.windows || []).forEach(w => savedWindows.push({ day, w })));
  const stale = savedDays.filter(d => d.date && d.date < today).length;

  const savedBlock = savedWindows.length ? `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row between" style="margin-bottom:6px">
        <strong style="font-size:13px">Slots offered to ${esc(person.name.split(' ')[0])}</strong>
        <button class="btn ghost sm" id="d-clear-slots">Clear</button>
      </div>
      ${savedWindows.map(({ day, w }) => {
        const passed = day.date && day.date < today;
        return `<div class="slotline"${passed ? ' style="color:var(--text-faint);text-decoration:line-through"' : ''}>
          ${esc(day.label)}: ${esc(w.text)}</div>`;
      }).join('')}
      ${stale ? `<div class="small" style="color:var(--warn);margin-top:6px">
        ${stale} of these ${stale === 1 ? 'has' : 'have'} already passed — pick again
        before the next draft.</div>` : ''}
      <div class="small faint" style="margin-top:6px">Drafts use these, not fresh
        availability${person.offered_slots_at ? ' · picked ' + dateLabel(person.offered_slots_at) : ''}.</div>
    </div>` : '';

  // Once slots are out and the outreach is actually sent, this is where you
  // record whichever one they actually said yes to — typed in, not ticked,
  // since the real answer rarely matches a suggested window exactly.
  const showConfirmBox = savedWindows.length > 0
    && ['outreach_sent', 'awaiting_reply'].includes(person.status);
  const confirmBox = showConfirmBox ? `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div style="font-size:13px;font-weight:650;margin-bottom:8px">
        What time did you land on?</div>
      <div class="row" style="gap:8px">
        <input type="date" id="d-confirm-date" style="max-width:150px">
        <input type="time" id="d-confirm-start" style="max-width:110px">
        <span class="small muted">to</span>
        <input type="time" id="d-confirm-end" style="max-width:110px">
        <button class="btn gold sm" id="d-confirm-btn">Confirm</button>
      </div>
      <p class="small faint" style="margin:8px 0 0">Doesn't need to match anything
        above — enter whatever you actually agreed on. This sets the chat date,
        moves them to Chat scheduled, and downloads a calendar file that confirms
        it and cancels the other holds.</p>
    </div>` : '';

  const hasProfile = !!(person.linkedin_raw || '').trim();
  const needsLinkedinTitle = hasProfile ? '' : ' title="Upload their LinkedIn profile first — see Prep sheet"';

  $('#drawer-body').innerHTML = `
    <div class="row" style="margin-bottom:16px">
      <button class="btn primary sm" data-prep="${person.id}">Prep sheet${hasProfile ? ' ✓' : ' — start here'}</button>
      <button class="btn ${hasProfile ? 'gold' : 'ghost'} sm" data-draft="outreach" data-id="${person.id}"${needsLinkedinTitle}>Draft outreach</button>
      <button class="btn ${hasProfile ? '' : 'ghost'} sm" data-draft="followup" data-id="${person.id}"${needsLinkedinTitle}>Draft nudge</button>
      <button class="btn ${hasProfile ? 'gold' : 'ghost'} sm" data-draft="thankyou" data-id="${person.id}"${needsLinkedinTitle}>Draft thank-you</button>
      <button class="btn sm" data-slots="${person.id}">Suggest slots</button>
    </div>

    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row" style="gap:8px">
        <label class="btn gold sm" style="cursor:pointer;margin:0">
          ${person.linkedin_raw ? 'Replace LinkedIn PDF' : 'Upload LinkedIn PDF'}
          <input type="file" accept="application/pdf,.pdf" id="d-profile-pdf"
                 data-person="${person.id}" style="display:none">
        </label>
        ${person.profile_pdf ? `<a class="btn ghost sm" href="#" data-stored-file="/api/profile-pdf/${person.id}">Open stored PDF</a>` : ''}
        <span class="small faint" id="d-pdf-note" style="flex:1;min-width:200px">
          ${person.linkedin_raw
            ? 'Profile loaded — the prep sheet and outreach draft compare it against yours.'
            : 'On their profile: More → Save to PDF. Kept on this Mac.'}
        </span>
      </div>
    </div>

    ${savedBlock}
    ${confirmBox}

    <div class="grid-2">
      ${f('name', 'Name', person.name)}
      ${f('email', 'Email', person.email, 'email')}
      ${f('firm', 'Firm', person.firm)}
      ${f('role', 'Role', person.role)}
      ${f('office', 'Office', person.office)}
      ${f('grad_year', 'Grad year', person.grad_year)}
    </div>
    ${f('linkedin', 'LinkedIn', person.linkedin)}
    <div class="grid-3">
      <label class="field"><span>Status</span>
        <select data-f="status">${STATE.statuses.map(s =>
          `<option value="${s.key}"${s.key === person.status ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
      <label class="field"><span>Tier</span>
        <select data-f="tier">${['A', 'B', 'C'].map(t =>
          `<option${t === person.tier ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
      <label class="field"><span>Goizueta alum</span>
        <select data-f="is_alum"><option value="0"${!person.is_alum ? ' selected' : ''}>No</option>
        <option value="1"${person.is_alum ? ' selected' : ''}>Yes</option></select></label>
    </div>
    <div class="grid-2">
      <label class="field"><span>Chat date &amp; time</span>
        <input type="datetime-local" data-f="chat_at" value="${(person.chat_at || '').slice(0, 16)}"></label>
      <label class="field"><span>Introduced by</span>
        <select data-f="referred_by"><option value="">—</option>${STATE.people.filter(p => p.id !== person.id).map(p =>
          `<option value="${p.id}"${p.id === person.referred_by ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
    </div>
    <div class="grid-2">
      ${f('source', 'How you found them', person.source)}
      <label class="field"><span>Reached via</span>
        <select data-f="contact_channel">
          <option value=""${!person.contact_channel ? ' selected' : ''}>—</option>
          <option value="email"${person.contact_channel === 'email' ? ' selected' : ''}>Email</option>
          <option value="linkedin"${person.contact_channel === 'linkedin' ? ' selected' : ''}>LinkedIn</option>
        </select></label>
    </div>

    <div class="row" style="margin:4px 0 20px">
      <span class="small muted" id="d-savestate">Every field saves as you leave it</span>
      <div class="spacer"></div>
      <button class="btn sm" id="d-cal">Add to Apple Calendar</button>
      <button class="btn danger sm" id="d-delete">Delete</button>
    </div>

    ${person.referrals.length ? `<h2 style="margin-top:6px">They introduced you to</h2>
      <div class="row">${person.referrals.map(r =>
        `<button class="btn ghost sm" data-open="${r.id}">${esc(r.name)} · ${esc(r.firm || '')}</button>`).join('')}</div>` : ''}

    <h2>Notes</h2>
    <div class="row" style="margin-bottom:10px">
      <select id="note-kind" style="max-width:150px">
        <option value="note">Note</option><option value="question">Question I asked</option>
        <option value="takeaway">Takeaway</option><option value="prep">Prep</option>
      </select>
      <input type="text" id="note-body" placeholder="What did you learn?" style="flex:1;min-width:180px">
      <button class="btn sm" id="note-add">Add</button>
    </div>
    <div id="notes-list">${person.notes.length ? person.notes.map(n => `
      <div class="note ${n.kind}">${esc(n.body)}
        <div class="meta">${esc(n.kind)} · ${dateLabel(n.created_at)}
          <a href="#" data-delnote="${n.id}" style="margin-left:8px;color:var(--danger)">remove</a></div>
      </div>`).join('')
      : '<div class="small faint">Nothing logged yet. Write down what they said — you will reuse it in cover letters.</div>'}</div>

    ${person.mail.length ? `<h2>Mail</h2>${person.mail.map(m => `
      <div class="note"><span class="chip ${m.direction === 'in' ? 'ok' : ''}">${m.direction === 'in' ? 'received' : 'sent'}</span>
        ${esc(m.subject || '(no subject)')}<div class="meta">${dateLabel(m.occurred_at)}</div></div>`).join('')}` : ''}
  `;

  if (!quiet) {
    $('#scrim').classList.add('open');
    $('#drawer').classList.add('open');
  }
}

function closeDrawer() {
  $('#scrim').classList.remove('open');
  $('#drawer').classList.remove('open');
  CURRENT = null;
}

let saveStateTimer;
function markSaved(text = 'Saved ✓', bad = false) {
  const el = $('#d-savestate');
  if (!el) return;
  el.textContent = text;
  el.style.color = bad ? 'var(--danger)' : 'var(--ok)';
  clearTimeout(saveStateTimer);
  saveStateTimer = setTimeout(() => {
    if (!$('#d-savestate')) return;
    $('#d-savestate').textContent = 'Every field saves as you leave it';
    $('#d-savestate').style.color = '';
  }, bad ? 8000 : 2200);
}

/* One field at a time, on blur. The drawer is deliberately NOT re-rendered
   here — redrawing the form under someone's cursor loses whatever they were
   part way through typing. */
async function saveField(field, value) {
  if (!CURRENT) return;
  const patch = {};
  patch[field] = value;
  try {
    const res = await api('/api/person/' + CURRENT.id, 'POST', patch);
    CURRENT = res.person;
    markSaved();
    if (field === 'status' && value === 'scheduled' && !res.person.chat_at) {
      toast('Set the chat date below — the thank-you clock runs off it', true);
    }
    STATE = await api('/api/state');
    renderToday();
    renderPipeline();
    updateNavCounts();
  } catch (e) {
    markSaved('Not saved — ' + e.message, true);
    toast(e.message, true);
  }
}

/* --------------------------------------------------------------- modal */

function openModal(title, html) {
  $('#m-title').textContent = title;
  $('#m-body').innerHTML = html;
  $('#modal').classList.add('open');
}
function closeModal() { $('#modal').classList.remove('open'); }

/* `slotLines`, when given, comes from the per-person picker — the draft then
   offers exactly the windows that were ticked, rather than re-deriving them. */
async function openDraft(personId, kind, slotLines) {
  const labels = { outreach: 'Outreach email', followup: 'Follow-up nudge', thankyou: 'Thank-you note' };
  openModal(labels[kind] || 'Draft', '<div class="empty small">Building the draft…</div>');

  let highlights = '';
  if (kind === 'thankyou') {
    const person = await api('/api/person/' + personId);
    highlights = person.notes.filter(n => n.kind === 'takeaway').map(n => n.body).join(' ');
  }

  const payload = { person_id: personId, kind, highlights };
  if (slotLines) payload.slot_lines = slotLines;

  let draft;
  try {
    draft = await api('/api/draft', 'POST', payload);
  } catch (e) { closeModal(); return toast(e.message, true); }

  if (draft.needs_linkedin) {
    closeModal();
    toast(draft.error || 'Upload their LinkedIn profile before drafting anything for them', true);
    return openPrep(personId);
  }

  const gapNote = draft.unfilled && draft.unfilled.length
    ? `<div class="banner warn"><strong>${draft.unfilled.length} thing${draft.unfilled.length > 1 ? 's' : ''} still to write.</strong>
        Everything in [square brackets] is a part that has to sound like you. A draft
        sent with them intact reads exactly like the template everyone else sent.</div>`
    : '';

  $('#m-body').innerHTML = `
    ${gapNote}
    <label class="field"><span>Subject</span><input type="text" id="m-subject" value="${esc(draft.subject)}"></label>
    <label class="field"><span>Body</span><textarea id="m-text" rows="20">${esc(draft.body)}</textarea></label>
    <div class="row">
      <button class="btn primary" id="m-open" data-id="${personId}" data-kind="${kind}">Open draft in Outlook</button>
      <button class="btn" id="m-copy">Copy text</button>
      <div class="spacer"></div>
      <span class="small faint">Nothing is sent. Outlook opens the draft for you to finish.</span>
    </div>`;

  const textarea = $('#m-text');
  const sync = () => {
    const gaps = (textarea.value.match(/\[[^\[\]]{3,400}?\]/g) || []).length;
    $('#m-open').textContent = gaps ? `Open in Outlook (${gaps} unfilled)` : 'Open draft in Outlook';
    $('#m-open').classList.toggle('gold', gaps > 0);
    $('#m-open').classList.toggle('primary', gaps === 0);
  };
  textarea.addEventListener('input', sync);
  sync();

  $('#m-copy').onclick = async () => {
    toast(await copyText(textarea.value) ? 'Copied' : 'Could not copy — select the text manually');
  };

  $('#m-open').onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      const res = await api('/api/draft', 'POST', {
        person_id: personId, kind,
        subject: $('#m-subject').value, body: textarea.value,
        open_in_outlook: true, force: true,
      });
      if (res.ok) {
        toast(res.demo ? 'Demo mode — no draft created' : 'Draft open in Outlook');
        closeModal();
        await refresh();
      } else {
        toast(res.error || 'Could not create the draft', true);
      }
    } catch (e) {
      toast(e.message, true);
    } finally { btn.disabled = false; }
  };
}

/* ----------------------------------------------------------- prep sheet */

function qCard(text, badge, tone = '') {
  return `<div class="qbank-item ${tone}">
    <div style="flex:1">
      ${badge ? `<div class="q-badge">${esc(badge)}</div>` : ''}
      <div>${esc(text)}</div>
    </div>
    <button class="btn ghost sm" data-copy-text="${esc(text)}">Copy</button>
  </div>`;
}

function renderPrepSheet(prep) {
  const p = prep.person;
  const link = p.linkedin
    ? `<a href="${esc(p.linkedin)}" target="_blank" rel="noreferrer">their LinkedIn profile</a>`
    : 'their LinkedIn profile';

  const pasteBox = `
    <details class="paste-box"${prep.has_profile ? '' : ' open'}>
      <summary>${prep.has_profile ? 'Update their profile' : 'Add their LinkedIn profile'}</summary>
      <p class="small muted" style="margin:10px 0">
        <strong>Easiest:</strong> open ${link}, click <em>More</em> → <em>Save to PDF</em>,
        and drop the file here. The app reads the whole career out of it — no copying,
        no pasting. Otherwise select the page (⌘A), copy (⌘C) and paste below.
        Either way it stays on this Mac.
      </p>
      <div class="row" style="margin-bottom:10px">
        <label class="btn gold sm" style="cursor:pointer;margin:0">
          Upload LinkedIn PDF
          <input type="file" accept="application/pdf,.pdf" id="prep-pdf"
                 data-person="${p.id}" style="display:none">
        </label>
        <span class="small faint" id="prep-pdf-note">More → Save to PDF, on their profile.</span>
      </div>
      <textarea id="prep-raw" rows="7" placeholder="Paste the profile here…"></textarea>
      <button class="btn primary sm" id="prep-parse" data-id="${p.id}" style="margin-top:8px">
        ${prep.has_profile ? 'Re-read profile' : 'Build prep sheet'}</button>
    </details>`;

  if (!prep.has_profile) {
    return `
      ${prep.parsed_nothing ? `<div class="banner warn">That paste didn't contain anything
        recognisable as work history. Make sure the Experience section is included.</div>` : ''}
      <div class="banner info">Nothing built yet — upload ${esc(p.name.split(' ')[0])}'s
        LinkedIn profile below and the summary, career story, timeline and tailored
        questions all come from it. Until then there's nothing here to build a sheet
        from, and no drafts can go out for them either.</div>
      ${pasteBox}`;
  }

  const signals = prep.signals.length
    ? `<div class="row" style="gap:6px;margin:10px 0 16px">${prep.signals.map(s =>
        `<span class="chip gold">${esc(s.label)}</span>`).join('')}</div>` : '';

  const timeline = prep.timeline.length ? `
    <h2>Career</h2>
    <div class="card" style="padding:6px 16px">
      ${prep.timeline.map(t => `
        <div class="tl-row${t.current ? ' current' : ''}">
          <div class="tl-when">${esc(t.when)}</div>
          <div>
            <div style="font-weight:600">${esc(t.title || '—')}</div>
            <div class="small muted">${esc(t.company || '')}${t.length ? ' · ' + esc(t.length) : ''}</div>
          </div>
        </div>`).join('')}
      ${prep.education.length ? `<div class="tl-row">
        <div class="tl-when">Education</div>
        <div class="small">${prep.education.map(e =>
          esc([e.degree, e.school || e.detail].filter(Boolean).join(' · '))).join('<br>')}</div>
      </div>` : ''}
    </div>` : '';

  // What the two of you share — the part of the sheet that needs both profiles.
  const common = (prep.common || []).length ? `
    <h2>What you have in common</h2>
    <p class="small muted" style="margin:-4px 0 10px">Worked out by comparing your
      profile against theirs. Goizueta is left out on purpose — it is how you found
      them, not a reason they will remember the conversation.</p>
    ${prep.common.map(c => `
      <div class="card" style="border-left:3px solid var(--ok);margin-bottom:8px;padding:12px 14px">
        <div style="font-weight:650;margin-bottom:3px">${esc(c.label)}</div>
        <div class="small muted" style="line-height:1.55">${esc(c.note)}</div>
        <div class="qbank-item great" style="margin-top:9px">
          <div style="flex:1">${esc(c.question)}</div>
          <button class="btn ghost sm" data-copy-text="${esc(c.question)}">Copy</button>
        </div>
      </div>`).join('')}`
    : (STATE.settings.user_profile_raw ? '' : `
      <div class="banner info">Upload <em>your</em> LinkedIn PDF in
        <a href="#" data-goto="settings">Settings</a> and this sheet will also show
        what the two of you have in common, which is the strongest thing you can
        open on.</div>`);

  const trajectory = prep.trajectory ? `
    <h2>Career story</h2>
    <div class="card" style="line-height:1.65">${esc(prep.trajectory)}</div>` : '';

  const about = prep.about ? `
    <div class="card" style="margin-top:10px;border-left:3px solid var(--border-strong)">
      <div class="small muted" style="margin-bottom:4px"><strong>In their own words</strong></div>
      <div style="line-height:1.6;font-style:italic;color:var(--text-muted)">${esc(prep.about)}</div>
    </div>` : '';

  return `
    <div class="card" style="border-left:3px solid var(--gold-500)">
      <h3 style="margin-bottom:6px">Summary</h3>
      <div style="line-height:1.6">${esc(prep.summary)}</div>
      ${signals}
      <div class="small muted"><strong>First two minutes:</strong> ${esc(prep.opener)}</div>
    </div>
    ${trajectory}
    ${about}
    ${common}
    ${timeline}
    ${prepQuestionsHtml(prep)}
    ${prepFlowHtml(prep)}
    ${prepDownloadHtml(p)}
    <h2>Source</h2>
    ${pasteBox}`;
}

function prepDownloadHtml(person) {
  return `
    <div class="row" style="margin-top:22px;padding-top:16px;border-top:1px solid var(--border)">
      <button class="btn primary" data-pdf="${person.id}">Download prep notes (PDF)</button>
      <span class="small faint">Everything above, laid out to print, with ruled
        space for notes during the call.</span>
    </div>`;
}

/* Files the app keeps (your resume, uploaded LinkedIn PDFs) sit behind the
   API token, which a plain link cannot send. Fetch them with it instead: PDFs
   open in a new window, anything else downloads. */
async function openStoredFile(url) {
  try {
    const res = await fetch(url, { headers: { 'X-CCT-Token': window.CCT_TOKEN } });
    if (!res.ok) {
      let message = 'That file is not available.';
      try { message = (await res.json()).error || message; } catch (e) { /* keep default */ }
      throw new Error(message);
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    if ((blob.type || '').includes('pdf')) {
      window.open(blobUrl, '_blank');
    } else {
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = match ? match[1] : 'file';
      document.body.appendChild(link); link.click(); link.remove();
    }
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
  } catch (e) {
    toast(e.message, true);
  }
}

document.addEventListener('click', async (ev) => {
  const opener = ev.target.closest('[data-stored-file]');
  if (opener) { ev.preventDefault(); return openStoredFile(opener.dataset.storedFile); }
  if (ev.target.id === 'btn-resume-open') return openStoredFile('/api/resume');
  if (ev.target.id === 'btn-resume-remove') {
    const btn = ev.target;
    if (btn.dataset.armed !== '1') {
      btn.dataset.armed = '1'; btn.textContent = 'Really remove?';
      setTimeout(() => { btn.dataset.armed = ''; btn.textContent = 'Remove'; }, 4000);
      return;
    }
    btn.dataset.armed = ''; btn.textContent = 'Remove';
    try {
      await api('/api/resume/remove', 'POST', {});
      toast('Resume removed — drafts will no longer mention one');
    } catch (e) { toast(e.message, true); }
    return refresh();
  }
});

async function downloadPrepPdf(personId, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Building PDF…';
  try {
    const res = await fetch('/api/prep.pdf', {
      method: 'POST',
      headers: { 'X-CCT-Token': window.CCT_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_id: personId }),
    });
    if (!res.ok) throw new Error('The app could not build that PDF.');

    // Filename comes from the server so the two stay in step.
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : 'Prep notes.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast('Prep notes saved to Downloads');
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function prepQuestionsHtml(prep) {
  const tailored = (prep.tailored || []).length ? `
    <h2>Tailored to them</h2>
    <p class="small muted" style="margin:-4px 0 10px">Each of these rests on something
      specific in their profile. Fill the brackets with your own background before the call.</p>
    ${prep.tailored.map(q => qCard(q.text, q.why, 'great')).join('')}` : '';

  return `
    ${tailored}
    <h2>Company culture</h2>
    ${prep.culture.map(q => qCard(q.text, q.theme, 'good')).join('')}
    <h2>Their journey</h2>
    ${prep.journey.map(q => qCard(q.text, q.theme, 'good')).join('')}`;
}

function prepFlowHtml(prep) {
  return `
    <h2>How to run the 30 minutes</h2>
    <div class="card" style="padding:6px 16px">
      ${prep.flow.map(step => `
        <div class="tl-row">
          <div class="tl-when">${esc(step.span)}</div>
          <div>
            <div style="font-weight:600">${esc(step.stage)}</div>
            <div class="small muted" style="line-height:1.55">${esc(step.detail)}</div>
          </div>
        </div>`).join('')}
    </div>`;
}

function paintPrep(prep) {
  const personId = prep.person.id;
  $('#m-title').textContent = 'Prep — ' + prep.person.name;
  $('#m-body').innerHTML = renderPrepSheet(prep);

  const pdfInput = $('#prep-pdf');
  if (pdfInput) {
    pdfInput.onchange = async () => {
      const file = pdfInput.files && pdfInput.files[0];
      if (!file) return;
      const note = $('#prep-pdf-note');
      note.textContent = `Reading ${file.name}…`;
      try {
        const res = await api('/api/profile-pdf', 'POST', {
          person_id: personId, data: await fileToBase64(file),
        });
        toast(res.parsed.ok
          ? `Read ${res.parsed.roles} roles from ${file.name}`
          : 'The PDF was read but no work history was found', !res.parsed.ok);
        const again = await api('/api/prep', 'POST', { person_id: personId });
        paintPrep(again.prep);
        await refresh();
      } catch (e) {
        note.textContent = e.message;
        toast(e.message, true);
      }
    };
  }

  const btn = $('#prep-parse');
  if (!btn) return;
  btn.onclick = async () => {
    const raw = $('#prep-raw').value;
    if (!raw.trim()) return toast('Paste the profile first', true);
    btn.disabled = true;
    btn.textContent = 'Reading…';
    try {
      const again = await api('/api/prep', 'POST', { person_id: personId, raw });
      paintPrep(again.prep);   // re-renders and re-binds in one go
      toast(again.prep.has_profile ? 'Prep sheet built' : 'Could not read that paste',
            !again.prep.has_profile);
    } catch (e) {
      toast(e.message, true);
      btn.disabled = false;
      btn.textContent = 'Build prep sheet';
    }
  };
}

async function openPrep(personId) {
  openModal('Prep sheet', '<div class="empty small">Building the prep sheet…</div>');
  try {
    const res = await api('/api/prep', 'POST', { person_id: personId });
    paintPrep(res.prep);
  } catch (e) {
    closeModal();
    toast(e.message, true);
  }
}

/* ------------------------------------------------- per-person slot picker */

/* Same wording the server's format_slot_lines produces, recomputed here
   because unticking a window has to change the email text immediately. */
function slotLinesFor(days, tzLabel) {
  return days.filter(d => d.windows.length).map(d =>
    `${d.label}: ${d.windows.map(w => w.text).join(' or ')} ${tzLabel}`.trim());
}

function pickedDays(days, picked) {
  return days
    .map((day, di) => ({
      ...day,
      windows: day.windows.filter((w, wi) => picked.has(`${di}:${wi}`)),
    }))
    .filter(day => day.windows.length);
}

async function openSuggestSlots(personId) {
  const person = (CURRENT && CURRENT.id === personId)
    ? CURRENT : await api('/api/person/' + personId);

  openModal('Suggest slots — ' + person.name,
    '<div class="empty small">Reading your calendar…</div>');

  let data;
  try {
    data = await api('/api/slots', 'POST', {});
  } catch (e) {
    closeModal();
    return toast(e.message, true);
  }

  if (!data.days.length) {
    $('#m-body').innerHTML = `<div class="card empty">No conflict-free windows in the
      next two weeks — the calendar looks fully booked between 9am and 6pm on
      weekdays. Free up some time and try again.</div>`;
    return;
  }

  // Nothing starts ticked — pick whichever windows actually work.
  const picked = new Set();
  paintSuggestSlots(person, data, picked);
}

function paintSuggestSlots(person, data, picked) {
  const tzLabel = STATE.settings.tz_label || '';
  const banner = data.demo
    ? `<div class="banner warn">Demo calendar — these windows are simulated.</div>`
    : data.note ? `<div class="banner info">${esc(data.note)}</div>` : '';

  $('#m-body').innerHTML = `
    ${banner}
    <p class="small muted" style="margin-top:0" id="slot-intro"></p>
    <div id="slot-list"></div>
    <div class="row" style="margin:4px 0 2px">
      <button class="btn ghost sm" id="slot-more">Request 3 more days</button>
      <span class="small faint" id="slot-more-note">Keeps what you have ticked and
        looks further ahead.</span>
    </div>
    <h3 style="margin:16px 0 6px">What they'll see</h3>
    <div id="slot-preview"></div>
    <div class="row" style="margin-top:14px">
      <button class="btn primary" id="slot-save">Save for ${esc(person.name.split(' ')[0])}</button>
      <button class="btn" id="slot-copy">Copy for email</button>
      <button class="btn" id="slot-draft">Use in outreach draft</button>
    </div>
    <p class="small faint" style="margin:6px 0 0">Saved slots are what every outreach
      and nudge draft for them will offer from now on, until you pick again.</p>
    <div class="row" style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border)">
      <button class="btn gold" id="slot-ics">Download .ics holds</button>
      <span class="small faint" style="flex:1;min-width:220px">Blocks these windows in
        Apple Calendar as <strong>busy</strong> holds under
        ${esc(person.name)}'s name, so nothing else takes the time and the finder
        won't offer it to anyone else. Delete them if the chat falls through.</span>
    </div>`;

  /* The list is redrawn whenever more days arrive, so it lives in its own
     container — the change listener below is bound once, to the panel. */
  const renderList = () => {
    $('#slot-intro').innerHTML = `Conflict-free windows from your calendar,
      ${data.event_count} event${data.event_count === 1 ? '' : 's'} considered.
      Tick whichever work best to offer ${esc(person.name.split(' ')[0])}.`;
    $('#slot-list').innerHTML = data.days.map((day, di) => `
      <div class="slot-day">
        <div class="slot-day-label">${esc(day.label)}</div>
        ${day.windows.map((w, wi) => `
          <label class="slot-pick">
            <input type="checkbox" data-pick="${di}:${wi}"
                   ${picked.has(`${di}:${wi}`) ? 'checked' : ''}>
            <span>${esc(w.text)} ${esc(tzLabel)}</span>
            <span class="small faint">${w.minutes} min</span>
          </label>`).join('')}
      </div>`).join('');
  };

  const preview = () => {
    const chosen = pickedDays(data.days, picked);
    const lines = slotLinesFor(chosen, tzLabel);
    $('#slot-preview').innerHTML = lines.length
      ? lines.map(l => `<div class="slotline">• ${esc(l)}</div>`).join('')
      : `<div class="small faint">Nothing ticked — the draft would go out with no times in it.</div>`;
    return lines;
  };

  renderList();
  let lines = preview();

  $('#slot-more').onclick = async (ev) => {
    const btn = ev.currentTarget;
    const note = $('#slot-more-note');
    btn.disabled = true;
    btn.textContent = 'Reading further ahead…';
    try {
      const last = data.days[data.days.length - 1];
      const res = await api('/api/slots', 'POST', { after: last && last.date });
      if (!res.days.length) {
        note.textContent = 'Nothing further ahead fits — the calendar looks '
          + 'fully booked for those days too.';
      } else {
        // Appended, never prepended: the picked keys are positional, so
        // anything already ticked has to keep the index it was ticked under.
        // The new days arrive unticked, same as the first batch — tick
        // whichever of them actually work.
        res.days.forEach(day => data.days.push(day));
        data.event_count = res.event_count;
        note.textContent = `Now showing ${data.days.length} days.`;
        renderList();
        lines = preview();
      }
    } catch (e) {
      note.textContent = e.message;
      toast(e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Request 3 more days';
    }
  };

  $('#m-body').addEventListener('change', (ev) => {
    const box = ev.target.closest('[data-pick]');
    if (!box) return;
    if (box.checked) picked.add(box.dataset.pick);
    else picked.delete(box.dataset.pick);
    lines = preview();
  });

  /* Anything you actually act on is worth remembering — otherwise the email
     you write tomorrow offers different times than the holds already sitting
     on your calendar. */
  async function persist() {
    if (!lines.length) return false;
    try {
      const res = await api('/api/offered-slots', 'POST', {
        person_id: person.id, lines, days: pickedDays(data.days, picked),
      });
      if (CURRENT && CURRENT.id === person.id) CURRENT = res.person;
      return true;
    } catch (e) {
      toast(e.message, true);
      return false;
    }
  }

  $('#slot-save').onclick = async (ev) => {
    if (!lines.length) return toast('Tick at least one window first', true);
    const btn = ev.currentTarget;
    btn.disabled = true;
    if (await persist()) {
      toast(`${lines.length} day${lines.length === 1 ? '' : 's'} saved for ${person.name}`);
      closeModal();
      await refresh();
    }
    btn.disabled = false;
  };

  $('#slot-copy').onclick = async () => {
    if (!lines.length) return toast('Tick at least one window first', true);
    await persist();
    toast(await copyText(lines.map(l => '• ' + l).join('\n'))
      ? 'Slots copied and saved' : 'Could not copy — select the text manually');
  };

  $('#slot-draft').onclick = async () => {
    if (!lines.length) return toast('Tick at least one window first', true);
    await persist();
    openDraft(person.id, 'outreach', lines);
  };

  $('#slot-ics').onclick = async (ev) => {
    await persist();
    downloadIcs(pickedDays(data.days, picked), person.name, ev.currentTarget);
  };
}

function defaultChatTime() {
  const when = new Date();
  when.setDate(when.getDate() + 2);
  when.setHours(12, 0, 0, 0);
  const pad = n => String(n).padStart(2, '0');
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
       + `T${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

/* Scheduling someone without writing down when is the one mistake that breaks
   everything downstream — the thank-you clock, Today, and firm coverage all
   run off this date — so it gets asked for at the moment the status changes. */
function askChatDate(personId, name, existing) {
  openModal('When is the chat?', `
    <p class="small muted" style="margin-top:0">${esc(name)} just moved to
      <strong>Chat scheduled</strong>. The thank-you clock, the Today page and firm
      coverage all run off this date.</p>
    <label class="field"><span>Chat date &amp; time</span>
      <input type="datetime-local" id="sched-when" value="${esc(existing || defaultChatTime())}"></label>
    <div class="row">
      <button class="btn primary" id="sched-save">Save date</button>
      <button class="btn ghost" id="sched-skip">Skip for now</button>
      <span class="small faint">You can also set it in the panel behind this.</span>
    </div>`);

  $('#sched-save').onclick = async () => {
    const when = $('#sched-when').value;
    if (!when) return toast('Pick a date and time', true);
    try {
      await api('/api/person/' + personId, 'POST', { chat_at: when });
      closeModal();
      toast('Chat date saved');
      await refresh();
      if (CURRENT && CURRENT.id === personId) openPerson(personId, true);
    } catch (e) { toast(e.message, true); }
  };
  $('#sched-skip').onclick = () => closeModal();
}

function openAddPerson() {
  let pendingPdf = null;   // base64 blob, attached to the person right after it's created

  openModal('Add person', `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row" style="gap:8px">
        <label class="btn gold sm" style="cursor:pointer;margin:0">
          Upload LinkedIn PDF
          <input type="file" accept="application/pdf,.pdf" id="n-profile-pdf" style="display:none">
        </label>
        <span class="small faint" id="n-pdf-note" style="flex:1;min-width:200px">
          Optional — fills in what it can below (name, firm, role). Nothing already
          typed gets overwritten, and everything stays editable before you add them.
        </span>
      </div>
    </div>

    <div class="grid-2">
      <label class="field"><span>Name *</span><input type="text" id="n-name"></label>
      <label class="field"><span>Email</span><input type="email" id="n-email"></label>
      <label class="field"><span>Firm</span><input type="text" id="n-firm" list="firm-list"></label>
      <label class="field"><span>Role</span><input type="text" id="n-role" placeholder="Associate, Consultant, Partner…"></label>
      <label class="field"><span>Office</span><input type="text" id="n-office" placeholder="Atlanta"></label>
      <label class="field"><span>Grad year</span><input type="text" id="n-grad_year" placeholder="2024"></label>
    </div>
    <datalist id="firm-list">${(STATE.settings.target_firms || '').split(',')
      .map(f => f.trim()).filter(Boolean)
      .map(f => `<option value="${esc(f)}"></option>`).join('')}</datalist>

    <label class="field"><span>LinkedIn</span><input type="text" id="n-linkedin"
      placeholder="linkedin.com/in/…"></label>

    <div class="grid-3">
      <label class="field"><span>Goizueta alum</span>
        <select id="n-is_alum">
          <option value="0">No</option>
          <option value="1" selected>Yes</option>
        </select></label>
      <label class="field"><span>Tier</span>
        <select id="n-tier"><option>A</option><option selected>B</option><option>C</option></select></label>
      <label class="field"><span>Status</span>
        <select id="n-status">${STATE.statuses.map(s =>
          `<option value="${s.key}">${esc(s.label)}</option>`).join('')}</select></label>
    </div>
    <p class="small faint" style="margin:-2px 0 12px">A Goizueta alum gets a different
      opening line in every draft — the app leads with the shared programme instead of
      explaining who you are, which is the strongest opening you have.</p>

    <div class="grid-2">
      <label class="field"><span>How you found them</span><input type="text" id="n-source"
        placeholder="GCA board, Goizueta alumni list, LinkedIn, intro from…"></label>
      <label class="field"><span>Reached via</span>
        <select id="n-contact_channel">
          <option value="">—</option>
          <option value="email">Email</option>
          <option value="linkedin">LinkedIn</option>
        </select></label>
    </div>
    <p class="small faint" style="margin:-2px 0 12px">Without a LinkedIn profile — pasted
      or uploaded — the prep sheet stays empty and no drafts can go out for them.</p>
    <div class="row"><button class="btn primary" id="n-save">Add</button>
      <span class="small faint">Start with second-years and recent grads — they say yes most.</span></div>`);

  $('#n-profile-pdf').onchange = async () => {
    const input = $('#n-profile-pdf');
    const file = input.files && input.files[0];
    if (!file) return;
    const note = $('#n-pdf-note');
    note.textContent = `Reading ${file.name}…`;
    try {
      pendingPdf = await fileToBase64(file);
      const res = await api('/api/profile-pdf', 'POST', { data: pendingPdf });
      const fill = (id, value) => {
        const el = $(id);
        if (el && !el.value.trim() && value) el.value = value;
      };
      if (res.parsed && res.parsed.ok) {
        fill('#n-name', res.suggested.name);
        fill('#n-firm', res.suggested.firm);
        fill('#n-role', res.suggested.role);
        note.textContent = `Read ${res.parsed.roles} role${res.parsed.roles === 1 ? '' : 's'} `
          + `from ${file.name} — anything already typed above was left alone.`;
      } else {
        note.textContent = `${file.name} was read, but no work history was found in it. `
          + `It'll still attach when you add them.`;
      }
    } catch (e) {
      pendingPdf = null;
      input.value = '';
      note.textContent = e.message;
      toast(e.message, true);
    }
  };

  $('#n-save').onclick = async () => {
    const name = $('#n-name').value.trim();
    if (!name) return toast('A name is required', true);
    const btn = $('#n-save');
    btn.disabled = true;
    try {
      const res = await api('/api/person', 'POST', {
        name,
        email: $('#n-email').value.trim(),
        firm: $('#n-firm').value.trim(),
        role: $('#n-role').value.trim(),
        office: $('#n-office').value.trim(),
        grad_year: $('#n-grad_year').value.trim(),
        linkedin: $('#n-linkedin').value.trim(),
        is_alum: parseInt($('#n-is_alum').value, 10),
        tier: $('#n-tier').value,
        status: $('#n-status').value,
        source: $('#n-source').value.trim(),
        contact_channel: $('#n-contact_channel').value,
      });
      let person = res.person;
      if (pendingPdf) {
        try {
          const attached = await api('/api/profile-pdf', 'POST', {
            person_id: person.id, data: pendingPdf,
          });
          person = attached.person || person;
        } catch (e) {
          toast('Added, but the PDF could not be attached — upload it again from their panel', true);
        }
      }
      closeModal();
      await refresh();
      await openPerson(person.id);
      if (person.status === 'scheduled') {
        askChatDate(person.id, person.name, '');
      }
    } finally {
      btn.disabled = false;
    }
  };
}

function openImport() {
  openModal('Import a list', `
    <p class="small muted">One person per line. Any of these work:<br>
      <code class="k">Name, Firm, Role, email@firm.com</code></p>
    <label class="field"><span>Paste</span><textarea id="i-text" rows="10"
      placeholder="Preston Wilson, McKinsey &amp; Company, Co-President&#10;Jenna Shin, Bain &amp; Company, Co-President"></textarea></label>
    <button class="btn primary" id="i-go">Import</button>`);
  $('#i-go').onclick = async () => {
    const lines = $('#i-text').value.split('\n').map(l => l.trim()).filter(Boolean);
    let added = 0;
    for (const line of lines) {
      const parts = line.split(',').map(p => p.trim());
      if (!parts[0]) continue;
      const email = parts.find(p => p.includes('@')) || '';
      await api('/api/person', 'POST', {
        name: parts[0], firm: parts[1] || '', role: parts[2] || '', email,
        source: 'Imported list',
      });
      added++;
    }
    closeModal();
    await refresh();
    toast(`Added ${added} ${added === 1 ? 'person' : 'people'}`);
  };
}

/* --------------------------------------------------------------- slots */

function fillSettings() {
  const s = STATE.settings;
  const set = (id, key) => { const el = $(id); if (el) el.value = s[key] != null ? s[key] : ''; };
  ['user_name', 'user_email', 'user_pitch', 'timezone',
   'target_firms', 'followup_after_days', 'max_followups', 'thankyou_within_hours']
    .forEach(k => set('#s-' + k, k));

  const resumeNote = $('#s-resume-note');
  if (resumeNote && !resumeNote.dataset.busy) {
    const has = !!(s.resume_name || '').trim();
    resumeNote.innerHTML = has
      ? `On file: <strong>${esc(s.resume_name)}</strong> — attached to every outreach and nudge.`
      : 'PDF or Word. The app keeps its own copy, so it can always attach it.';
    $('#s-resume-btn-label').textContent = has ? 'Replace resume' : 'Upload your resume';
    $('#btn-resume-open').style.display = has ? '' : 'none';
    $('#btn-resume-remove').style.display = has ? '' : 'none';
  }

  const note = $('#s-profile-note');
  if (note && !note.dataset.busy) {
    note.textContent = (s.user_profile_raw || '').trim()
      ? 'Your profile is loaded — drafts will compare it against theirs.'
      : 'On your own profile: More → Save to PDF.';
  }
}

/* Used by the per-person "Suggest slots" picker, so a hold written from
   there matches what was actually offered. */
async function downloadIcs(days, holdLabel, button) {
  const events = (days || []).reduce((n, d) => n + d.windows.length, 0);
  if (!events) return toast('Pick at least one window first', true);
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Building…';
  try {
    const res = await fetch('/api/slots.ics', {
      method: 'POST',
      headers: { 'X-CCT-Token': window.CCT_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ days, label: holdLabel }),
    });
    if (!res.ok) {
      let message = 'Could not build the calendar file.';
      try { message = (await res.json()).error || message; } catch (e) { /* keep default */ }
      throw new Error(message);
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : 'Coffee chat holds.ics';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast(`${events} hold${events === 1 ? '' : 's'} saved — open the file to add them`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

/* Marks one of the offered windows as the one that was actually accepted:
   sets the chat date, moves the person to Chat scheduled, and hands back a
   calendar file that confirms that slot and marks every other offered window
   as cancelled — reusing the same UID each hold was given, so a calendar
   that still has them can update them in place instead of gaining a
   duplicate. If yours doesn't, the stale holds are still easy to find and
   remove by hand (search the hold title, as always). */
async function confirmSlot(personId, start, end, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Confirming…';
  try {
    const res = await fetch('/api/confirm-slot', {
      method: 'POST',
      headers: { 'X-CCT-Token': window.CCT_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ person_id: personId, start, end }),
    });
    if (!res.ok) {
      let message = 'Could not confirm that slot.';
      try { message = (await res.json()).error || message; } catch (e) { /* keep default */ }
      throw new Error(message);
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : 'Coffee chat confirmed.ics';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast('Chat confirmed — calendar file downloaded');
    await refresh();
    if (CURRENT && CURRENT.id === personId) await openPerson(personId, true);
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

/* --------------------------------------------------------------- wiring */

function switchView(name) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
}

function setStatusDot(id, tone, text) {
  $(id).innerHTML = `<span class="dot ${tone}"></span>${esc(text)}`;
}

/* Both connection tests are reachable from the sidebar and from Settings, so
   they report to whichever of the two is actually on screen. */
function connReport(html) {
  const box = $('#conn-result');
  if (box) box.innerHTML = html;
}

async function testCalendar() {
  setStatusDot('#status-cal', 'warn', 'Calendar — checking…');
  connReport('<div class="banner info">Reading your calendar…</div>');
  try {
    const res = await api('/api/detect-calendar', 'POST', {});
    const cal = res.calendar;
    if (!cal.ok) throw new Error(cal.error || 'Calendar unavailable');
    connReport(`<div class="banner info">Calendar reachable — ${cal.events}
      event${cal.events === 1 ? '' : 's'} in the next 24 hours.${cal.demo ? ' (demo data)' : ''}</div>`);
    setStatusDot('#status-cal', cal.demo ? 'warn' : 'ok',
      cal.demo ? 'Calendar: demo data' : 'Calendar connected');
    toast(cal.demo ? 'Calendar: demo data' : 'Calendar connected');
  } catch (e) {
    connReport(`<div class="banner bad">${esc(e.message)}</div>`);
    setStatusDot('#status-cal', 'bad', 'Calendar blocked');
    toast(e.message, true);
  }
}

async function testOutlook() {
  setStatusDot('#status-outlook', 'warn', 'Outlook — checking…');
  connReport('<div class="banner info">Checking Outlook…</div>');
  try {
    const res = await api('/api/detect-outlook', 'POST', {});
    const o = res.outlook;
    const good = o.flavor === 'classic';
    connReport(`<div class="banner ${good ? 'info' : 'warn'}">
      <strong>${esc(o.flavor)}</strong> — ${esc(o.detail)}
      ${o.flavor === 'unscriptable' ? `<br><br>The "new Outlook" has no scripting
        support, so mail tracking is unavailable. Everything else works. To switch
        back, open Outlook and turn off the <em>New Outlook</em> toggle at the top
        right of the window.` : ''}</div>`);
    setStatusDot('#status-outlook', good ? 'ok' : 'warn',
      good ? 'Outlook connected' : 'Outlook limited');
    toast(good ? 'Outlook connected' : 'Outlook limited — ' + o.flavor, !good);
  } catch (e) {
    connReport(`<div class="banner bad">${esc(e.message)}</div>`);
    setStatusDot('#status-outlook', 'bad', 'Outlook blocked');
    toast(e.message, true);
  }
}

document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-view], [data-open], [data-prep], [data-slots], [data-pdf], [data-draft], [data-status], [data-copy-text], [data-delnote], [data-goto], [data-resolve], [data-restore]');
  if (!t) return;

  if (t.dataset.resolve) {
    const action = (STATE.actions || []).find(a => a.key === t.dataset.resolve);
    if (!action) return;
    try {
      await api('/api/action/resolve', 'POST', {
        key: action.key, person_id: action.person_id, kind: action.kind,
        label: action.label, detail: action.detail, name: action.name,
      });
      toast('Ticked off for today — in the bin below');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (t.dataset.restore) {
    try {
      await api('/api/action/restore', 'POST', { key: t.dataset.restore });
      toast('Put back on the list');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (t.dataset.view) return switchView(t.dataset.view);
  if (t.dataset.goto) { ev.preventDefault(); closeModal(); return switchView(t.dataset.goto); }
  if (t.dataset.pdf) return downloadPrepPdf(parseInt(t.dataset.pdf, 10), t);
  if (t.dataset.prep) return openPrep(parseInt(t.dataset.prep, 10));
  if (t.dataset.slots) return openSuggestSlots(parseInt(t.dataset.slots, 10));
  if (t.dataset.open) return openPerson(parseInt(t.dataset.open, 10));
  if (t.dataset.draft) return openDraft(parseInt(t.dataset.id, 10), t.dataset.draft);
  if (t.dataset.copyText !== undefined) {
    return toast(await copyText(t.dataset.copyText)
      ? 'Question copied' : 'Could not copy — select the text manually', false);
  }

  if (t.dataset.delnote) {
    ev.preventDefault();
    await api('/api/note/' + t.dataset.delnote, 'DELETE');
    return refresh();
  }
});

document.addEventListener('change', async (ev) => {
  // Their LinkedIn PDF, from the person panel.
  if (ev.target.id === 'd-profile-pdf') {
    const file = ev.target.files && ev.target.files[0];
    if (!file || !CURRENT) return;
    const note = $('#d-pdf-note');
    note.textContent = `Reading ${file.name}…`;
    try {
      const res = await api('/api/profile-pdf', 'POST', {
        person_id: CURRENT.id, data: await fileToBase64(file),
      });
      const p = res.parsed;
      toast(p.ok ? `Read ${p.roles} roles — ${p.top_role} at ${p.top_company}`
                 : 'The PDF was read, but no work history was found', !p.ok);
      await refresh();
      return openPerson(CURRENT.id, true);
    } catch (e) {
      note.textContent = e.message;
      return toast(e.message, true);
    }
  }

  // Your resume, from Settings. Uploaded, not pointed at: the app keeps a copy
  // it is always allowed to read, so the attachment can never silently vanish.
  if (ev.target.id === 's-resume-file') {
    const file = ev.target.files && ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    const note = $('#s-resume-note');
    note.dataset.busy = '1';
    note.textContent = `Saving ${file.name}…`;
    try {
      const res = await api('/api/resume', 'POST', { name: file.name, data: await fileToBase64(file) });
      toast(`Resume saved — ${res.name} will be attached to outreach`);
    } catch (e) {
      toast(e.message, true);
    }
    delete note.dataset.busy;
    return refresh();
  }

  // Your own LinkedIn PDF, from Settings.
  if (ev.target.id === 's-profile-pdf') {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const note = $('#s-profile-note');
    note.dataset.busy = '1';
    note.textContent = `Reading ${file.name}…`;
    try {
      const res = await api('/api/profile-pdf', 'POST', {
        self: true, data: await fileToBase64(file),
      });
      const p = res.parsed;
      note.textContent = p.ok
        ? `Read ${p.roles} roles — most recently ${p.top_role} at ${p.top_company}.`
        : 'The PDF was read, but no work history was found in it.';
      toast(p.ok ? 'Your profile is loaded' : 'No work history found in that PDF', !p.ok);
      delete note.dataset.busy;
      return refresh();
    } catch (e) {
      delete note.dataset.busy;
      note.textContent = e.message;
      return toast(e.message, true);
    }
  }

  // Inline status change from the pipeline table.
  const sel = ev.target.closest('[data-status]');
  if (sel) {
    const personId = parseInt(sel.dataset.status, 10);
    try {
      const res = await api('/api/person/' + personId, 'POST', { status: sel.value });
      toast('Status updated');
      await refresh();
      if (sel.value === 'scheduled') {
        askChatDate(personId, res.person.name, (res.person.chat_at || '').slice(0, 16));
      }
      return;
    } catch (e) { return toast(e.message, true); }
  }

  // Autosave any field in the person drawer
  const field = ev.target.closest('[data-f]');
  if (field && $('#drawer').classList.contains('open')) {
    let value = field.value;
    if (field.dataset.f === 'is_alum' || field.dataset.f === 'referred_by') {
      value = value === '' ? null : parseInt(value, 10);
    }
    return saveField(field.dataset.f, value);
  }
});

document.addEventListener('input', (ev) => {
  if (['filter-search'].includes(ev.target.id)) renderPipeline();
});
document.addEventListener('change', (ev) => {
  if (['filter-status', 'filter-firm'].includes(ev.target.id)) renderPipeline();
});

/* <details> fires "toggle" without bubbling, so this has to listen on the
   capture phase to catch it delegated from a re-rendered tree. Remembers
   which firms are collapsed so a refresh triggered elsewhere doesn't close
   everything the user just opened. */
document.addEventListener('toggle', (ev) => {
  const el = ev.target;
  if (!el.classList || !el.classList.contains('tree-firm')) return;
  const firm = el.dataset.firm;
  if (el.open) TREE_COLLAPSED_FIRMS.delete(firm);
  else TREE_COLLAPSED_FIRMS.add(firm);
}, true);

document.addEventListener('click', async (ev) => {
  const id = ev.target.id;
  if (id === 'd-close' || id === 'scrim') return closeDrawer();
  if (id === 'm-close' || (ev.target.classList.contains('modal'))) return closeModal();
  if (id === 'btn-add') return openAddPerson();
  if (id === 'btn-import') return openImport();
  if (id === 'tree-toggle') {
    TREE_MINIMIZED = !TREE_MINIMIZED;
    return renderPipelineTree();
  }

  if (id === 'd-delete') {
    if (!CURRENT) return;
    const panel = ev.target;
    if (panel.dataset.armed !== '1') {
      panel.dataset.armed = '1';
      panel.textContent = 'Really delete?';
      setTimeout(() => { panel.dataset.armed = '0'; panel.textContent = 'Delete'; }, 4000);
      return;
    }
    await api('/api/person/' + CURRENT.id, 'DELETE');
    closeDrawer();
    toast('Deleted');
    return refresh();
  }

  if (id === 'd-cal') {
    const when = $('[data-f="chat_at"]').value;
    if (!when) return toast('Set a chat date first', true);
    const start = new Date(when);
    const end = new Date(start.getTime() + 60 * 60000);
    const res = await api('/api/calendar-event', 'POST', {
      title: `Coffee chat — ${CURRENT.name}${CURRENT.firm ? ' (' + CURRENT.firm + ')' : ''}`,
      start: start.toISOString(), end: end.toISOString(),
      notes: `Role: ${CURRENT.role || ''}\nEmail: ${CURRENT.email || ''}\n\nAgenda: intros, resume walk, Q&A.`,
    });
    return toast(res.ok ? 'Added to Apple Calendar' : (res.error || 'Failed'), !res.ok);
  }

  if (id === 'd-clear-slots') {
    if (!CURRENT) return;
    try {
      await api('/api/offered-slots', 'POST', { person_id: CURRENT.id, clear: true });
      toast('Cleared — drafts will work out fresh availability again');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'd-confirm-btn') {
    if (!CURRENT) return;
    const dateStr = $('#d-confirm-date').value;
    const startStr = $('#d-confirm-start').value;
    const endStr = $('#d-confirm-end').value;
    if (!dateStr || !startStr || !endStr) return toast('Pick a date, start and end time', true);
    const start = new Date(`${dateStr}T${startStr}`);
    const end = new Date(`${dateStr}T${endStr}`);
    if (!(end > start)) return toast('End time must be after the start time', true);
    return confirmSlot(CURRENT.id, start.toISOString(), end.toISOString(), ev.target);
  }

  if (id === 'note-add') {
    const body = $('#note-body').value.trim();
    if (!body || !CURRENT) return;
    try {
      await api(`/api/person/${CURRENT.id}/note`, 'POST', { body, kind: $('#note-kind').value });
      $('#note-body').value = '';
      return openPerson(CURRENT.id, true);
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'btn-save-settings' || id === 'btn-save-policy') {
    const keys = id === 'btn-save-policy'
      ? ['followup_after_days', 'max_followups', 'thankyou_within_hours']
      : ['user_name', 'user_email', 'timezone', 'target_firms'];
    const patch = {};
    keys.forEach(k => { patch[k] = $('#s-' + k).value; });
    try {
      await api('/api/settings', 'POST', patch);
      toast('Saved');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'btn-save-pitch') {
    try {
      await api('/api/settings', 'POST', { user_pitch: $('#s-user_pitch').value });
      toast('Saved — drafts will use that line verbatim');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'btn-test-calendar' || id === 'btn-side-cal') return testCalendar();
  if (id === 'btn-test-outlook' || id === 'btn-side-outlook') return testOutlook();

  if (id === 'btn-sync-outlook') {
    $('#conn-result').innerHTML = '<div class="banner info">Scanning your mailbox — this can take a minute…</div>';
    try {
      const res = await api('/api/sync-outlook', 'POST', {});
      $('#conn-result').innerHTML = `<div class="banner info">
        Scanned ${res.scanned} messages, matched ${res.matched} to people you track.
        ${res.advanced.length ? '<br>Updated: ' + esc(res.advanced.join(', ')) : ''}
        ${res.diagnostics.length ? `<br><span class="small faint">${esc(res.diagnostics.join(' · '))}</span>` : ''}</div>`;
      await refresh();
    } catch (e) {
      $('#conn-result').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`;
    }
    return;
  }
});

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') { closeModal(); closeDrawer(); }
});

/* Nothing should ever fail in silence. */
window.addEventListener('unhandledrejection', (ev) => {
  const message = (ev.reason && ev.reason.message) || String(ev.reason);
  toast(message, true);
});

/* Keep-alive. The server also has a long grace period, but the reliable
   signal is the explicit goodbye below — timers stop when the Mac sleeps. */
function beat() { if (!OFFLINE) api('/api/ping').catch(() => {}); }
setInterval(beat, 20000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) beat(); });
window.addEventListener('focus', beat);

/* Closing the window is what actually quits the app. */
window.addEventListener('pagehide', () => {
  try {
    navigator.sendBeacon('/api/close?t=' + encodeURIComponent(window.CCT_TOKEN));
  } catch (e) { /* nothing useful to do while the page is going away */ }
});

refresh().catch(e => toast(e.message, true));
