/* Coffee Chat Tracker — interface logic. No frameworks, no network. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

let STATE = {
  people: [], settings: {}, statuses: [], actions: [], coverage: [], questions: [],
  chats: { current: [], upcoming: [] },
  applications: [], application_statuses: [], deadlines: [], firms: [],
  firm_cards: [], target_firms: [], knowledge_categories: [], proposals: [],
  proposal_batches: {}, resume_walk: { body: '', versions: [], feedback: [] },
};
let CURRENT = null;        // person open in the drawer
let PANEL = null;          // { kind: 'application' | 'firm', id } behind it

const STATUS_TONE = {
  tracking: 'st-tracking', uninitiated: 'st-uninit', outreach_sent: 'st-out',
  scheduled: 'st-sched', chat_done: 'st-done', thankyou_sent: 'st-ty',
  no_response: 'st-nr',
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
  renderApplications();
  renderFirms();
  renderReview();
  renderConnections();
  fillSettings();
  fillResumeWalk();
  updateNavCounts();
  if (PANEL) reopenPanel(true);
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
  const deadlines = STATE.deadlines || [];
  const pending = (STATE.proposals || []).filter(p => p.status === 'pending');
  $('#nav-actions').textContent = STATE.actions.length + deadlines.length;
  $('#nav-actions').classList.toggle('hot',
    STATE.actions.some(a => a.urgency === 'overdue')
    || deadlines.some(d => d.urgency === 'overdue'));
  $('#nav-people').textContent = STATE.people.length;
  $('#nav-apps').textContent = (STATE.applications || []).length;
  const review = $('#nav-review');
  review.textContent = pending.length;
  review.classList.toggle('hot', pending.length > 0);
}

function renderToday() {
  const people = STATE.people;
  const count = key => people.filter(p => p.status === key).length;
  const chatted = people.filter(p => ['chat_done', 'thankyou_sent'].includes(p.status)).length;
  const overdue = STATE.actions.filter(a => a.urgency === 'overdue').length;

  $('#stats').innerHTML = [
    // "Tracked" = everyone past Uninitiated; the rest of the pipeline stays off Today.
    { value: people.filter(p => p.status !== 'uninitiated').length, label: 'People tracked' },
    { value: chatted, label: 'Chats completed' },
    { value: count('scheduled'), label: 'Scheduled' },
    { value: count('outreach_sent'), label: 'Awaiting reply' },
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

  // Deadlines and proposals are not person actions — they can't be ticked
  // off, they go away by being dealt with — so they sit above the list
  // rather than inside it.
  const deadlines = STATE.deadlines || [];
  const pending = (STATE.proposals || []).filter(p => p.status === 'pending');
  $('#today-extra').innerHTML = [
    pending.length ? `<div class="action today">
      <div class="grow"><span class="who">${pending.length} proposed change${pending.length === 1 ? '' : 's'}</span>
        <div class="detail">Read out of ${new Set(pending.map(p => p.batch_id)).size}
          transcript${new Set(pending.map(p => p.batch_id)).size === 1 ? '' : 's'} — nothing applied yet</div></div>
      <button class="btn gold sm" data-goto="review">Review</button></div>` : '',
    ...deadlines.map(d => `<div class="action ${d.urgency}">
      <div class="grow"><span class="who">${esc(d.company)}</span>
        <span class="muted small">${d.role ? ' · ' + esc(d.role) : ''}</span>
        <div class="detail">Application ${esc(d.detail)}${d.deadline ? ' · ' + esc(d.deadline) : ''}</div></div>
      <button class="btn sm" data-app="${d.application_id}">Open</button></div>`),
  ].join('');

  $('#actions').innerHTML = STATE.actions.length ? STATE.actions.map(a => `
    <div class="action ${a.urgency} clickable" data-open="${a.person_id}">
      <div class="grow">
        <span class="who">${esc(a.name)}</span>
        <span class="muted small">${a.firm ? ' · ' + esc(a.firm) : ''}</span>
        ${a.tier === 'A' ? '<span class="chip gold" style="margin-left:6px">Tier A</span>' : ''}
        <div class="detail">${esc(a.label)} — ${esc(a.detail)}</div>
      </div>
      ${a.kind === 'thankyou' ? (a.chat_done
        ? `<button class="btn gold sm" data-draft="thankyou" data-id="${a.person_id}">Draft thank-you</button>`
        : `<button class="btn sm" disabled title="Mark the chat as done first">Draft thank-you</button>`) : ''}
      ${a.kind === 'followup' ? `<button class="btn gold sm" data-draft="followup" data-id="${a.person_id}">Draft nudge</button>` : ''}
      <button class="btn sm" data-open="${a.person_id}">Open</button>
      <button class="btn ghost sm" data-resolve="${esc(a.key)}"
        title="Tick this off — it goes to the bin below">Done</button>
    </div>`).join('')
    : (deadlines.length || pending.length ? ''
      : `<div class="card empty"><div class="big">✓</div>Nothing overdue. Good place to be.</div>`);

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
    <div class="action clickable" data-open="${u.person_id}">
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
    const cf = (c.firm || '').trim().toLowerCase();
    const fm = cf && (STATE.firms || []).find(x => {
      const n = (x.firm || '').toLowerCase();
      return n === cf || cf.startsWith(n + ' ') || n.startsWith(cf + ' ');
    });
    return `<div class="cov">
      <div>${fm ? `<span data-firm="${esc(fm.firm)}" title="Open ${esc(fm.firm)}" style="cursor:pointer;text-decoration:underline">${esc(c.firm)}</span>` : esc(c.firm)}</div>
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

  renderTracking();
  renderAwaiting();
  renderPipelineTree();
}

/* Everyone currently in "Tracking", pinned above the tree and table. */
function renderTracking() {
  const box = $('#pipeline-tracking');
  if (!box) return;
  const list = STATE.people.filter(p => p.status === 'tracking')
    .sort((a, b) => (a.firm || '').localeCompare(b.firm || '') || a.name.localeCompare(b.name));
  $('#tracking-count').textContent = list.length ? `(${list.length})` : '';
  box.innerHTML = list.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Firm</th><th>Role</th><th>Draft</th><th>Chat</th><th></th></tr></thead>
      <tbody>${list.map(p => `<tr data-id="${p.id}">
        <td class="name" data-open="${p.id}">${esc(p.name)}</td>
        <td data-open="${p.id}">${esc(p.firm || '—')}</td>
        <td class="muted" data-open="${p.id}">${esc(p.role || '—')}</td>
        <td class="muted small" data-open="${p.id}">${p.has_draft || p.draft_body ? 'Ready' : '—'}</td>
        <td class="muted small" data-open="${p.id}">${p.chat_at ? dateLabel(p.chat_at) : '—'}</td>
        <td><button class="btn ghost sm" data-open="${p.id}">›</button></td>
      </tr>`).join('')}</tbody></table></div>`
    : `<div class="empty small">No one is in Tracking right now.</div>`;
}

/* When a nudge is due: N days (Settings) after the last email you sent, as
   long as they haven't written back since and you're under the nudge cap.
   Returns { sentAt, days, due, replied, capped }. */
function nudgeState(p) {
  const s = STATE.settings || {};
  const after = parseInt(s.followup_after_days, 10) || 7;
  const cap = parseInt(s.max_followups, 10) || 3;
  const sentAt = p.last_outbound_at || p.first_contact_at || '';
  const sent = sentAt ? new Date(sentAt) : null;
  const days = sent && !isNaN(sent) ? Math.floor((Date.now() - sent.getTime()) / 86400000) : null;
  const replied = !!(p.last_inbound_at && sentAt && new Date(p.last_inbound_at) > sent);
  const capped = (parseInt(p.followups_sent, 10) || 0) >= cap;
  return { sentAt, days, after, replied, capped,
           due: days !== null && days >= after && !replied && !capped };
}

/* Everyone whose outreach has gone out and who hasn't booked a chat yet. */
function renderAwaiting() {
  const box = $('#pipeline-awaiting');
  if (!box) return;
  const list = STATE.people.filter(p => p.status === 'outreach_sent')
    .map(p => ({ p, n: nudgeState(p) }))
    .sort((a, b) => (a.n.sentAt || '').localeCompare(b.n.sentAt || ''));
  $('#awaiting-count').textContent = list.length ? `(${list.length})` : '';
  box.innerHTML = list.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Firm</th><th>Outreach sent</th><th>Days</th><th>Nudges</th><th></th></tr></thead>
      <tbody>${list.map(({ p, n }) => `<tr data-id="${p.id}">
        <td class="name" data-open="${p.id}">${esc(p.name)}</td>
        <td data-open="${p.id}">${esc(p.firm || '—')}</td>
        <td class="small" data-open="${p.id}">${n.sentAt ? esc(dateLabel(n.sentAt)) : '—'}</td>
        <td class="muted small" data-open="${p.id}">${n.days === null ? '—' : n.days + 'd'}</td>
        <td class="muted small" data-open="${p.id}">${parseInt(p.followups_sent, 10) || 0}</td>
        <td style="text-align:right">${n.replied
          ? '<span class="chip st-ty">Replied</span>'
          : n.due
            ? `<button class="btn gold sm" data-draft="followup" data-id="${p.id}">Draft nudge</button>`
            : n.capped ? '<span class="small faint">Nudge limit reached</span>'
            : `<span class="small faint">Nudge in ${Math.max(0, n.after - (n.days || 0))}d</span>`}</td>
      </tr>`).join('')}</tbody></table></div>`
    : `<div class="empty small">No outreach waiting on a reply.</div>`;
}

/* Who you've talked to, grouped by company, each company's own referral
   chains nested inside it — a McKinsey contact introducing you to another
   McKinsey person nests under them; a referral across firms just starts its
   own root in the new firm's tree, since that's a separate relationship. */
let TREE_MINIMIZED = false;
const TREE_COLLAPSED_FIRMS = new Set();
const PRIORITY_FIRMS = ['mckinsey', 'bain', 'bcg', 'pwc', 'ey', 'kearney'];
const STATUS_DOT = {
  tracking: 'var(--st-tracking)', uninitiated: 'var(--st-uninit)',
  outreach_sent: 'var(--st-out)', scheduled: 'var(--st-sched-dot)',
  chat_done: 'var(--st-done)', thankyou_sent: 'var(--st-ty)',
  no_response: 'var(--st-nr)',
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
  // Everyone except "Uninitiated" and "No response" gets a branch.
  const HIDDEN_TREE_STATUS = new Set(['uninitiated', 'no_response']);
  const eligible = STATE.people.filter(p =>
    !HIDDEN_TREE_STATUS.has(p.status));

  if (!eligible.length) {
    box.innerHTML = `<div class="card empty small">Nobody to show yet — a person
      needs a status other than "Uninitiated" or "No response" to appear in the tree.</div>`;
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

    return `<details class="paste-box tree-firm"${isOpen ? ' open' : ''} data-tree-firm="${esc(firm)}">
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
        <span class="row" style="gap:6px">
          <button class="btn ghost sm" id="d-clear-slots">Clear</button>
          <button class="btn sm" id="d-edit-slots">Edit</button>
        </span>
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
    && person.status === 'outreach_sent';
  const confirmBox = showConfirmBox ? `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div style="font-size:13px;font-weight:650;margin-bottom:8px">
        What time did you land on?</div>
      <div class="row" style="gap:8px">
        ${chatTimeFields('d-confirm', '', '12:00')}
        <button class="btn gold sm" id="d-confirm-btn">Confirm</button>
      </div>
      <p class="small faint" style="margin:8px 0 0">This sets the chat date,
        moves them to Chat scheduled, turns that hold into the real meeting in
        Apple Calendar and deletes the other holds.</p>
    </div>` : '';

  // Once a chat is on the calendar: see it, move it, or call it off. Both go
  // through Apple Calendar directly, so the event moves or disappears too.
  const chatDate = (person.chat_at || '').slice(0, 10);
  const chatHHMM = (person.chat_at || '').slice(11, 16);
  const chatBox = person.chat_at ? `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row between">
        <strong style="font-size:13px">☕ ${esc(chatTimeLabel(person.chat_at))}</strong>
        <span class="row" style="gap:6px">
          <button class="btn sm" id="d-chat-edit">Reschedule</button>
          <button class="btn ghost sm" id="d-chat-cancel">Cancel chat</button>
        </span>
      </div>
      ${person.status === 'scheduled' ? `<div class="row" style="gap:8px;margin-top:10px">
        <button class="btn gold sm" id="d-confirm-mail">Confirmation email</button>
      </div>` : ''}
      <div id="d-chat-editor" style="display:none;margin-top:10px">
        <div class="row" style="gap:8px">
          ${chatTimeFields('d-resched', chatDate, chatHHMM)}
          <button class="btn gold sm" id="d-resched-save">Save</button>
        </div>
        <p class="small faint" style="margin:8px 0 0">Moves the event in Apple Calendar
          (or adds it, if it isn't there).</p>
      </div>
    </div>` : '';

  const hasProfile = !!(person.linkedin_raw || '').trim() || !!(person.prep_md || '').trim();
  /* Orange = still to do, blue = done. Prep sheet and the LinkedIn upload are
     yellow until the PDF is in. */
  const profileTone = hasProfile ? 'primary' : 'yellow';
  const chatDone = ['chat_done', 'thankyou_sent'].includes(person.status);
  const nudge = nudgeState(person);
  const mailBtn = (kind, draftLabel, sentLabel) => sentMail(person, kind)
    ? `<button class="btn primary sm" data-sent="${kind}" data-id="${person.id}">${sentLabel}</button>`
    : (kind === 'followup' && !nudge.due)
      ? `<button class="btn sm" disabled title="${nudge.replied ? 'They replied'
          : nudge.days === null ? 'Send the outreach first'
          : 'Available ' + nudge.after + ' days after your last email'}">${draftLabel}</button>`
    : (kind === 'thankyou' && !chatDone)
      ? `<button class="btn sm" disabled title="Mark the chat as done first">${draftLabel}</button>`
      : `<button class="btn gold sm" data-draft="${kind}" data-id="${person.id}">${draftLabel}</button>`;

  const sentBox = (kind, label) => `<label class="row" style="gap:4px;cursor:pointer">
      <input type="checkbox" data-sent-toggle="${kind}" ${sentMail(person, kind) ? 'checked' : ''}> ${label}</label>`;
  $('#drawer-body').innerHTML = `
    <div class="card row" style="margin-bottom:12px;padding:10px 14px;gap:14px">
      <strong class="small">Sent:</strong>
      ${sentBox('outreach', 'Outreach')}
      ${sentBox('followup', 'Nudge')}
      ${sentBox('confirmation', 'Confirmation')}
      ${sentBox('thankyou', 'Thank-you')}
    </div>
    <div class="row" style="margin-bottom:16px">
      <button class="btn ${profileTone} sm" data-prep="${person.id}">Prep sheet${hasProfile ? ' ✓' : ' — start here'}</button>
      ${mailBtn('outreach', 'Draft outreach', 'Sent outreach')}
      ${mailBtn('followup', 'Draft nudge', 'Sent nudge')}
      ${mailBtn('thankyou', 'Draft thank-you', 'Sent thank-you')}
      <button class="btn sm" data-slots="${person.id}">Suggest slots</button>
    </div>

    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row" style="gap:8px">
        <label class="btn ${profileTone} sm" style="cursor:pointer;margin:0">
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

    ${chatBox}
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
        <input type="text" readonly value="${person.chat_at ? esc(chatTimeLabel(person.chat_at)) : 'Not scheduled'}"
               title="Use Reschedule / Cancel chat above, or the confirm box"></label>
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

/* Has this kind of email gone to Outlook for them? Saved copies first; for
   people contacted before copies were kept, fall back to the pipeline dates. */
function sentFlags(person) {
  try { return JSON.parse(person.sent_flags || '{}') || {}; } catch (e) { return {}; }
}

function sentMail(person, kind) {
  const flags = sentFlags(person);
  if (kind in flags) return !!flags[kind];
  if (kind === 'confirmation') return !!person.confirm_drafted_at;
  const saved = (person.sent_mail || []).some(m => m.kind === kind);
  if (saved) return true;
  if (kind === 'outreach') return !!person.first_contact_at || (person.status && !['uninitiated', 'tracking'].includes(person.status));
  if (kind === 'followup') return (parseInt(person.followups_sent, 10) || 0) > 0;
  if (kind === 'thankyou') return !!person.thankyou_sent_at;
  return false;
}

async function openSentMail(personId, kind) {
  const person = await api('/api/person/' + personId);
  const labels = { outreach: 'Sent outreach', followup: 'Sent nudges', thankyou: 'Sent thank-you' };
  const mails = (person.sent_mail || []).filter(m => m.kind === kind);
  const when = iso => { try { return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); } catch (e) { return iso; } };
  const list = mails.length ? mails.map((m, i) => `
      <div class="card" style="margin-bottom:12px;padding:12px 14px">
        <div class="row" style="margin-bottom:6px">
          <strong style="flex:1">${esc(m.subject || '(no subject)')}</strong>
          <span class="small faint">Opened in Outlook ${esc(when(m.sent_at))}</span>
          <button class="btn ghost sm" data-copy-text="${esc(m.body)}">Copy</button>
        </div>
        <pre class="sent-body">${esc(m.body)}</pre>
      </div>`).join('')
    : `<div class="empty small">No copy was kept — this went out before the app started saving sent emails.</div>`;
  openModal(labels[kind] + ' — ' + person.name, `
    ${list}
    ${kind === 'followup' ? `<div class="row"><button class="btn gold" id="m-another">Draft another nudge</button></div>` : ''}`);
  const again = $('#m-another');
  if (again) again.onclick = () => openDraft(personId, 'followup');
}

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


  const gapNote = draft.unfilled && draft.unfilled.length
    ? `<div class="banner warn"><strong>${draft.unfilled.length} thing${draft.unfilled.length > 1 ? 's' : ''} still to write.</strong>
        Everything in [square brackets] is a part that has to sound like you. A draft
        sent with them intact reads exactly like the template everyone else sent.</div>`
    : '';

  $('#m-body').innerHTML = `
    ${gapNote}
    <label class="field"><span>Subject</span><input type="text" id="m-subject" value="${esc(draft.subject)}"></label>
    <label class="field"><span>Body</span><textarea id="m-text" rows="20">${esc(draft.body)}</textarea></label>
    ${kind === 'thankyou' ? `<div class="row"><button class="btn primary" id="m-copy">Copy text</button></div>` : `
    <div class="row">
      <button class="btn primary" id="m-open" data-id="${personId}" data-kind="${kind}">Open draft in Outlook</button>
      <button class="btn" id="m-copy">Copy text</button>
      <div class="spacer"></div>
      <span class="small faint">Nothing is sent. Outlook opens the draft for you to finish.</span>
    </div>`}`;

  const textarea = $('#m-text');
  const sync = () => {
    if (!$('#m-open')) return;
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

  if ($('#m-open')) $('#m-open').onclick = async (ev) => {
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

/* Small markdown renderer for Claude's research and prep sheets: headings,
   bullets, numbered lists, bold, italics, links, paragraphs. Escapes first. */
function mdToHtml(text) {
  const inline = t => esc(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  const out = [];
  let list = null, para = [];
  const flush = () => {
    if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; }
    if (list) { out.push('</' + list + '>'); list = null; }
  };
  for (const raw of (text || '').split('\n')) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) {
      flush();
      const level = Math.min(m[1].length + 1, 4);
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^\s*[-*•]\s+(.*)/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      const kind = /^\s*\d/.test(line) ? 'ol' : 'ul';
      if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; }
      if (list !== kind) { if (list) out.push('</' + list + '>'); out.push('<' + kind + '>'); list = kind; }
      out.push('<li>' + inline(m[1]) + '</li>');
    } else {
      if (list) { out.push('</' + list + '>'); list = null; }
      para.push(line.trim());
    }
  }
  flush();
  return out.join('\n');
}

function renderCustomPrep(prep) {
  const sources = (prep.sources || []).length ? `
    <h2>Sources</h2>
    <ul class="small">${prep.sources.map(s => `<li><a href="${esc(s.url || '#')}" target="_blank"
      rel="noreferrer">${esc(s.title || s.url)}</a>${s.note ? ' — ' + esc(s.note) : ''}</li>`).join('')}</ul>` : '';
  const when = prep.researched_at ? `<span class="small faint">Researched ${esc(dateLabel(prep.researched_at))}</span>` : '';
  return `
    <div class="row" style="margin-bottom:12px">
      <span class="chip gold">Researched by Claude</span>${when}
      <div class="spacer"></div>
      <button class="btn ghost sm" data-copy-text="${esc(prep.prep_md)}">Copy prep sheet</button>
    </div>
    <div class="card md" style="border-left:3px solid var(--gold-500);line-height:1.6">${mdToHtml(prep.prep_md)}</div>
    ${prep.research_md ? `
    <details class="paste-box" style="margin-top:16px">
      <summary>Full research — their journey</summary>
      <div class="md" style="line-height:1.6;margin-top:10px">${mdToHtml(prep.research_md)}</div>
    </details>` : ''}
    ${sources}`;
}

function renderPrepSheet(prep) {
  if (prep.custom) return renderCustomPrep(prep);
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

/* Hour + quarter-hour picker. Replaces <input type="time"> everywhere: the
   hour list is the same width for every value, and minutes only come in
   :00 / :15 / :30 / :45. `attrs` goes on the wrapper; read with readTime(). */
function timePicker(attrs, hhmm) {
  let [h, m] = (hhmm || '12:00').split(':').map(Number);
  m = Math.round((m || 0) / 15) * 15;
  if (m === 60) { m = 0; h = (h + 1) % 24; }
  const h12 = h % 12 || 12, pm = h >= 12;
  const hours = Array.from({ length: 12 }, (_, i) => i + 1).map(x =>
    `<option value="${x}"${x === h12 ? ' selected' : ''}>${String(x).padStart(2, '0')}</option>`).join('');
  const mins = [0, 15, 30, 45].map(x =>
    `<option value="${x}"${x === m ? ' selected' : ''}>${String(x).padStart(2, '0')}</option>`).join('');
  return `<span class="tpick" ${attrs}><select class="tp-h" aria-label="Hour">${hours}</select><span class="tp-colon">:</span><select class="tp-m" aria-label="Minutes">${mins}</select><button type="button" class="tp-ap" data-ap="${pm ? 'PM' : 'AM'}" aria-label="AM or PM">${pm ? 'PM' : 'AM'}</button></span>`;
}
function readTime(el) {
  if (!el) return '';
  const h12 = Number(el.querySelector('.tp-h').value) % 12;
  const h = h12 + (el.querySelector('.tp-ap').dataset.ap === 'PM' ? 12 : 0);
  const m = el.querySelector('.tp-m').value;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
function setTime(el, hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  el.querySelector('.tp-h').value = String(h % 12 || 12);
  el.querySelector('.tp-m').value = String(m);
  const ap = el.querySelector('.tp-ap');
  ap.dataset.ap = ap.textContent = h >= 12 ? 'PM' : 'AM';
}
// The AM/PM toggle flips on click and reports it like any other change, so the
// 30-minute end and the slot editor both pick it up.
document.addEventListener('click', (ev) => {
  const ap = ev.target.closest('.tp-ap');
  if (!ap) return;
  ev.preventDefault();
  ev.stopPropagation();
  ap.dataset.ap = ap.textContent = ap.dataset.ap === 'PM' ? 'AM' : 'PM';
  ap.dispatchEvent(new Event('change', { bubbles: true }));
}, true);
/* HH:MM plus minutes, wrapping past midnight. */
function addMinutes(hhmm, mins) {
  const [h, m] = hhmm.split(':').map(Number);
  const t = (h * 60 + m + mins + 1440) % 1440;
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
}
const CHAT_MINUTES = 30;

/* Date + start + end, 30 minutes by default; changing the start moves the end. */
function chatTimeFields(prefix, dateStr, startHHMM) {
  const start = startHHMM || '12:00';
  return `<div class="chat-time">
      <input type="date" id="${prefix}-date" value="${esc(dateStr || '')}" style="max-width:150px">
      ${timePicker(`id="${prefix}-start"`, start)}
      <span class="small muted">to</span>
      ${timePicker(`id="${prefix}-end"`, addMinutes(start, CHAT_MINUTES))}
    </div>`;
}
// Any "<x>-start" picker drags its "<x>-end" partner along, 30 minutes later.
document.addEventListener('change', (ev) => {
  const st = ev.target.closest('.tpick[id$="-start"]');
  if (!st) return;
  const en = document.getElementById(st.id.replace(/-start$/, '-end'));
  if (en) setTime(en, addMinutes(readTime(st), CHAT_MINUTES));
});
function readChatTimeFields(prefix) {
  const d = document.getElementById(prefix + '-date').value;
  const a = readTime(document.getElementById(prefix + '-start'));
  const b = readTime(document.getElementById(prefix + '-end'));
  if (!d) return { error: 'Pick a date' };
  const start = new Date(`${d}T${a}`), end = new Date(`${d}T${b}`);
  if (!(end > start)) return { error: 'End time must be after the start time' };
  return { start: start.toISOString(), end: end.toISOString() };
}

/* '2:30pm', matching the server's fmt_time. */
function fmtSlotTime(h, m) {
  return `${h % 12 || 12}:${String(m).padStart(2, '0')}${h < 12 ? 'am' : 'pm'}`;
}

/* Wall-clock HH:MM straight out of an ISO string like 2026-09-24T14:30:00-04:00,
   so the time shown is the calendar's time zone, not the browser's. */
function isoHHMM(iso) { return (iso || '').slice(11, 16); }

/* Re-time one window in place, keeping its date and UTC offset. */
function retimeWindow(w, startHHMM, endHHMM) {
  const date = w.start.slice(0, 10);
  const offset = (w.start.match(/([+-]\d\d:\d\d|Z)$/) || [''])[0];
  const toMin = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
  const a = toMin(startHHMM), b = toMin(endHHMM);
  if (!(b > a)) return false;
  w.start = `${date}T${startHHMM}:00${offset}`;
  w.end = `${date}T${endHHMM}:00${offset}`;
  w.minutes = b - a;
  w.text = `${fmtSlotTime(Math.floor(a / 60), a % 60)} – ${fmtSlotTime(Math.floor(b / 60), b % 60)}`;
  return true;
}

/* Put the person's saved windows into the finder's list, ticked. They are
   usually missing from a fresh search — their own holds now block them. */
function mergeSaved(data, savedDays, picked) {
  savedDays.forEach(sd => {
    let day = data.days.find(d => d.date === sd.date);
    if (!day) {
      day = { date: sd.date, label: sd.label, windows: [] };
      data.days.push(day);
    }
    (sd.windows || []).forEach(w => {
      if (!day.windows.some(x => x.start === w.start && x.end === w.end)) day.windows.push({ ...w });
    });
  });
  data.days.sort((a, b) => a.date.localeCompare(b.date));
  data.days.forEach(day => day.windows.sort((a, b) => a.start.localeCompare(b.start)));
  data.days.forEach((day, di) => day.windows.forEach((w, wi) => {
    if (savedDays.some(sd => sd.date === day.date
        && (sd.windows || []).some(x => x.start === w.start && x.end === w.end))) {
      picked.add(`${di}:${wi}`);
    }
  }));
}

async function openSuggestSlots(personId, opts = {}) {
  const person = (CURRENT && CURRENT.id === personId)
    ? CURRENT : await api('/api/person/' + personId);

  openModal('Suggest slots — ' + person.name,
    '<div class="empty small">Reading your calendar…</div>');

  let data;
  try {
    data = await api('/api/slots', 'POST', { person_id: personId });
  } catch (e) {
    closeModal();
    return toast(e.message, true);
  }

  const picked = new Set();
  if (opts.editSaved) {
    let saved = null;
    try { saved = JSON.parse(person.offered_slots || 'null'); } catch (e) { saved = null; }
    mergeSaved(data, (saved && saved.days) || [], picked);
  }

  if (!data.days.length) {
    $('#m-body').innerHTML = `<div class="card empty">Every 2-hour block for the next
      six weeks is already saved for someone else. Clear an older offer and try again.</div>`;
    return;
  }

  // Nothing starts ticked (unless editing saved slots) — pick whichever work.
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
      ${sentMail(person, 'outreach') ? '<button class="btn" id="slot-nudge">Use in nudge draft</button>' : ''}
    </div>
    <p class="small faint" style="margin:6px 0 0">Saving blocks these windows in Apple
      Calendar as <strong>busy</strong> holds under ${esc(person.name)}'s name, and they're
      what every outreach and nudge draft offers until you pick again. Re-saving
      moves the holds; confirming or clearing removes them.</p>
`;

  /* The list is redrawn whenever more days arrive, so it lives in its own
     container — the change listener below is bound once, to the panel. */
  const renderList = () => {
    $('#slot-intro').innerHTML = `Open 2-hour blocks (9–11, 11–1, 1–3, 3–5) on the next weekdays —
      blocks already saved for someone else are left out. Tick whichever work best to offer ${esc(person.name.split(' ')[0])}.`;
    $('#slot-list').innerHTML = data.days.map((day, di) => `
      <div class="slot-day">
        <div class="slot-day-label">${esc(day.label)}</div>
        ${day.windows.map((w, wi) => `
          <label class="slot-pick">
            <input type="checkbox" data-pick="${di}:${wi}"
                   ${picked.has(`${di}:${wi}`) ? 'checked' : ''}>
            <span>${esc(w.text)} ${esc(tzLabel)}</span>
            <span class="small faint">${w.minutes} min</span>
          </label>
          ${picked.has(`${di}:${wi}`) ? `
          <div class="row slot-edit" style="gap:6px;margin:-2px 0 8px 36px">
            <span class="small muted">Adjust:</span>
            ${timePicker(`data-edit="${di}:${wi}" data-edge="start"`, isoHHMM(w.start))}
            <span class="small muted">to</span>
            ${timePicker(`data-edit="${di}:${wi}" data-edge="end"`, isoHHMM(w.end))}
          </div>` : ''}`).join('')}
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
      const res = await api('/api/slots', 'POST', { after: last && last.date, person_id: person.id });
      if (!res.days.length) {
        note.textContent = 'No open blocks in the next six weeks past these days — '
          + 'everything is saved for someone else.';
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
    const edit = ev.target.closest('[data-edit]');
    if (edit) {
      const [di, wi] = edit.dataset.edit.split(':').map(Number);
      const w = data.days[di].windows[wi];
      const row = edit.closest('.slot-edit');
      const start = readTime(row.querySelector('[data-edge="start"]'));
      const end = readTime(row.querySelector('[data-edge="end"]'));
      if (!start || !end || !retimeWindow(w, start, end)) {
        toast('End time must be after the start time', true);
      }
      renderList();
      lines = preview();
      return;
    }
    const box = ev.target.closest('[data-pick]');
    if (!box) return;
    if (box.checked) picked.add(box.dataset.pick);
    else picked.delete(box.dataset.pick);
    renderList();
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
      return res;
    } catch (e) {
      toast(e.message, true);
      return false;
    }
  }

  $('#slot-save').onclick = async (ev) => {
    if (!lines.length) return toast('Tick at least one window first', true);
    const btn = ev.currentTarget;
    btn.disabled = true;
    const res = await persist();
    if (res) {
      const cal = res.calendar || {};
      const holds = cal.error ? ` — Calendar not updated (${cal.error})`
        : ` — holds updated in Calendar`;
      toast(`${lines.length} day${lines.length === 1 ? '' : 's'} saved for ${person.name}${holds}`, !!cal.error);
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
  if ($('#slot-nudge')) $('#slot-nudge').onclick = async () => {
    if (!lines.length) return toast('Tick at least one window first', true);
    await persist();
    openDraft(person.id, 'followup', lines);
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
    <div class="field"><span>Chat date &amp; time</span>
      ${chatTimeFields('sched', (existing || defaultChatTime()).slice(0, 10),
                       (existing || defaultChatTime()).slice(11, 16))}</div>
    <div class="row">
      <button class="btn primary" id="sched-save">Save date</button>
      <button class="btn ghost" id="sched-skip">Skip for now</button>
      <span class="small faint">You can also set it in the panel behind this.</span>
    </div>`);

  $('#sched-save').onclick = async () => {
    const when = readChatTimeFields('sched');
    if (when.error) return toast(when.error, true);
    try {
      const res = await api('/api/chat/reschedule', 'POST', { person_id: personId, ...when });
      closeModal();
      toast(calendarNote(res.calendar, 'Chat date saved'));
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

/* -------------------------------------------------------- applications */

function appStatusLabel(key) {
  const found = (STATE.application_statuses || []).find(s => s.key === key);
  return found ? found.label : (key || '—');
}

/* How a deadline reads: nothing once it is behind you or already applied,
   red when it has passed, gold inside the next week. */
function deadlineTone(app) {
  const days = app.days_to_deadline;
  if (days == null) return '';
  if (['applied', 'interview_r1', 'interview_r2', 'offer', 'rejected', 'withdrawn']
      .includes(app.status)) return '';
  if (days < 0) return 'overdue';
  return days <= 7 ? 'soon' : '';
}

function deadlineText(app) {
  if (!app.deadline) return 'no deadline';
  const days = app.days_to_deadline;
  const stamp = String(app.deadline).slice(0, 10);
  if (days == null) return stamp;
  if (days < 0) return `${stamp} · ${-days}d ago`;
  if (days === 0) return `${stamp} · today`;
  return `${stamp} · in ${days}d`;
}

function renderApplications() {
  const sel = $('#app-status');
  if (sel.options.length <= 1) {
    (STATE.application_statuses || []).forEach(s => sel.add(new Option(s.label, s.key)));
  }
  const term = $('#app-search').value.trim().toLowerCase();
  const want = sel.value;
  const showArchived = $('#app-archived').checked;

  const rows = (STATE.applications || []).filter(a => {
    if (!showArchived && a.archived) return false;
    if (want && a.status !== want) return false;
    if (term && !`${a.company} ${a.role} ${a.office}`.toLowerCase().includes(term)) return false;
    return true;
  });

  $('#app-rows').innerHTML = rows.length ? rows.map(a => {
    const tone = deadlineTone(a);
    return `<div class="app-row ${tone}${a.archived ? ' archived' : ''}" data-app="${a.id}">
      <div class="grow" style="flex:1;min-width:0">
        <span class="co">${esc(a.company)}</span>
        ${a.is_target_firm ? '<span class="chip gold" style="margin-left:6px">target</span>' : ''}
        <div class="detail small muted">${esc(a.role || 'role not set')}${a.office ? ' · ' + esc(a.office) : ''}</div>
      </div>
      <span class="chip ${a.status === 'offer' ? 'ok' : a.status === 'rejected' ? 'bad' : ''}">${esc(appStatusLabel(a.status))}</span>
      <span class="due ${tone}">${esc(deadlineText(a))}</span>
    </div>`;
  }).join('')
    : `<div class="card empty"><div class="big">▧</div>${(STATE.applications || []).length
        ? 'Nothing matches those filters.'
        : 'No applications yet. Add the ones with the nearest deadlines first.'}</div>`;
}

function openAddApplication() {
  openModal('Add application', `
    <div class="grid-2">
      <label class="field"><span>Company *</span><input type="text" id="a-company" list="firm-list-6"></label>
      <label class="field"><span>Role</span><input type="text" id="a-role" placeholder="Summer Associate"></label>
      <label class="field"><span>Office</span><input type="text" id="a-office" placeholder="Atlanta"></label>
      <label class="field"><span>Deadline</span><input type="date" id="a-deadline"></label>
    </div>
    <datalist id="firm-list-6">${(STATE.target_firms || [])
      .map(f => `<option value="${esc(f)}"></option>`).join('')}</datalist>
    <label class="field"><span>Job link</span><input type="text" id="a-job_url" placeholder="https://…"></label>
    <label class="field"><span>Status</span>
      <select id="a-status">${(STATE.application_statuses || []).map(s =>
        `<option value="${s.key}">${esc(s.label)}</option>`).join('')}</select></label>
    <label class="field"><span>Notes</span><textarea id="a-notes" rows="3"></textarea></label>
    <div class="row"><button class="btn primary" id="a-save">Add</button>
      <span class="small faint">Everything else — the JD, the documents, the dates —
        is editable once it is open.</span></div>`);

  $('#a-save').onclick = async () => {
    const company = $('#a-company').value.trim();
    if (!company) return toast('A company is required', true);
    const btn = $('#a-save');
    btn.disabled = true;
    try {
      const res = await api('/api/application', 'POST', {
        company,
        role: $('#a-role').value.trim(),
        office: $('#a-office').value.trim(),
        deadline: $('#a-deadline').value || null,
        job_url: $('#a-job_url').value.trim(),
        status: $('#a-status').value,
        notes: $('#a-notes').value.trim(),
      });
      closeModal();
      await refresh();
      openApplication(res.application.id);
    } finally {
      btn.disabled = false;
    }
  };
}

/* ------------------------------------------------------- the side panel */

function openPanel(title, sub, html) {
  $('#p-title').textContent = title;
  $('#p-sub').innerHTML = sub;
  $('#panel-body').innerHTML = html;
  $('#panel-scrim').classList.add('open');
  $('#panel').classList.add('open');
}

function closePanel() {
  $('#panel-scrim').classList.remove('open');
  $('#panel').classList.remove('open');
  PANEL = null;
}

/* After a refresh, redraw whatever the panel is showing without stealing
   focus back from the drawer that may be sitting on top of it. */
function reopenPanel(quiet) {
  if (!PANEL) return;
  if (PANEL.kind === 'application') return openApplication(PANEL.id, quiet);
  if (PANEL.kind === 'firm') return openFirm(PANEL.id, quiet);
}

function markPanelSaved(text = 'Saved ✓', bad = false) {
  const el = $('#p-savestate');
  if (!el) return;
  el.textContent = text;
  el.style.color = bad ? 'var(--danger)' : 'var(--ok)';
  clearTimeout(saveStateTimer);
  saveStateTimer = setTimeout(() => {
    const again = $('#p-savestate');
    if (!again) return;
    again.textContent = 'Every field saves as you leave it';
    again.style.color = '';
  }, bad ? 8000 : 2200);
}

/* The same deal as the person drawer: one field, on blur, and the panel is
   not redrawn underneath whatever is being typed. */
async function saveAppField(field, value) {
  if (!PANEL || PANEL.kind !== 'application') return;
  const patch = {};
  patch[field] = value;
  try {
    await api('/api/application/' + PANEL.id, 'POST', patch);
    markPanelSaved();
    STATE = await api('/api/state');
    renderToday();
    renderApplications();
    renderFirms();
    updateNavCounts();
  } catch (e) {
    markPanelSaved('Not saved — ' + e.message, true);
    toast(e.message, true);
  }
}

async function openApplication(id, quiet = false) {
  const app = await api('/api/application/' + id);
  if (!app) return;
  PANEL = { kind: 'application', id };
  const f = (key, label, value, type = 'text') =>
    `<label class="field"><span>${label}</span><input type="${type}" data-af="${key}" value="${esc(value || '')}"></label>`;

  const firm = (STATE.firms || []).find(x => x.firm === app.target_firm);
  const tone = deadlineTone(app);

  openPanel(app.company,
    `${esc(app.role || 'role not set')}${app.office ? ' · ' + esc(app.office) : ''}
     <span class="chip" style="margin-left:6px">${esc(appStatusLabel(app.status))}</span>`, `
    <div class="card" style="margin-bottom:16px;padding:12px 14px">
      <div class="row between">
        <div>
          <strong style="font-size:13px">${esc(app.company)}</strong>
          ${app.is_target_firm ? '<span class="chip gold" style="margin-left:6px">one of the six</span>' : ''}
          <div class="small muted" style="margin-top:3px">
            ${firm ? `${firm.people_count} in the tracker · ${firm.chatted_count} spoken with ·
                      ${firm.knowledge.length} note${firm.knowledge.length === 1 ? '' : 's'} on file`
                   : 'Not one of the six target firms — no firm page for it.'}</div>
        </div>
        ${app.target_firm ? `<button class="btn sm" data-firm="${esc(app.target_firm)}">Open ${esc(app.target_firm)} page</button>` : ''}
      </div>
    </div>

    <h2 style="margin-top:0">Role</h2>
    <div class="grid-2">
      ${f('company', 'Company', app.company)}
      ${f('role', 'Role', app.role)}
      ${f('office', 'Office', app.office)}
      ${f('job_url', 'Job link', app.job_url)}
    </div>
    <label class="field"><span>Job description</span>
      <textarea data-af="jd_text" rows="6" style="font-family:var(--sans);font-size:13px">${esc(app.jd_text || '')}</textarea></label>

    <h2>My status</h2>
    <div class="grid-2">
      <label class="field"><span>Status</span>
        <select data-af="status">${(STATE.application_statuses || []).map(s =>
          `<option value="${s.key}"${s.key === app.status ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></label>
      <label class="field"><span>Archived</span>
        <select data-af="archived">
          <option value="0"${!app.archived ? ' selected' : ''}>No</option>
          <option value="1"${app.archived ? ' selected' : ''}>Yes</option></select></label>
    </div>
    <div style="margin-bottom:18px">${(app.status_history || []).length
      ? app.status_history.slice().reverse().map(h => `<div class="note">
          ${esc(appStatusLabel(h.status))}
          <div class="meta">${dateLabel(h.created_at)}${h.note ? ' · ' + esc(h.note) : ''}</div></div>`).join('')
      : '<div class="small faint">No moves recorded yet.</div>'}</div>

    <h2>Key dates</h2>
    <div class="grid-2">
      ${f('deadline', 'Deadline', (app.deadline || '').slice(0, 10), 'date')}
      ${f('applied_at', 'Applied', (app.applied_at || '').slice(0, 10), 'date')}
      ${f('interview_r1_at', 'Interview R1', (app.interview_r1_at || '').slice(0, 10), 'date')}
      ${f('interview_r2_at', 'Interview R2', (app.interview_r2_at || '').slice(0, 10), 'date')}
    </div>
    ${app.deadline ? `<p class="small ${tone === 'overdue' ? '' : 'faint'}"
      style="margin:-4px 0 16px${tone === 'overdue' ? ';color:var(--danger)' : ''}">${esc(deadlineText(app))}</p>` : ''}

    <h2>Documents</h2>
    <p class="small muted" style="margin-top:0">The tailored PDFs, wherever you keep
      them. The app stores the path and asks macOS to open the file — it never
      copies it, so the version you open is always the one on disk.</p>
    <div class="grid-2">
      ${f('resume_file', 'Resume file', app.resume_file)}
      ${f('cover_letter_file', 'Cover letter file', app.cover_letter_file)}
    </div>
    <div class="row" style="margin-bottom:18px">
      <button class="btn sm" data-open-file="resume" data-id="${app.id}">Open resume</button>
      <button class="btn sm" data-open-file="cover_letter" data-id="${app.id}">Open cover letter</button>
    </div>

    <h2>Notes</h2>
    <label class="field"><span></span>
      <textarea data-af="notes" rows="5" style="font-family:var(--sans);font-size:13px">${esc(app.notes || '')}</textarea></label>

    <div class="row" style="margin:4px 0 20px">
      <span class="small muted" id="p-savestate">Every field saves as you leave it</span>
      <div class="spacer"></div>
      <button class="btn danger sm" id="p-delete-app">Delete</button>
    </div>`);
  if (quiet) { /* redrawn in place; the panel is already open */ }
}

/* ------------------------------------------------------------- firms */

function renderFirms() {
  const cards = STATE.firm_cards || [];
  $('#firm-cards').innerHTML = `<div class="firm-grid">${cards.map(c => {
    const days = c.next_deadline_days;
    const due = days == null ? 'no application deadline'
      : days < 0 ? `deadline ${-days}d ago`
      : days === 0 ? 'deadline today'
      : `deadline in ${days}d`;
    return `<button class="firm-card" data-firm="${esc(c.firm)}">
      <div class="name">${esc(c.firm)}</div>
      <div class="line">${c.chatted_count} spoken with · ${c.people_count} in the pipeline</div>
      <div class="line">${c.knowledge_count} note${c.knowledge_count === 1 ? '' : 's'} on file</div>
      <div class="line" style="margin-top:6px;color:${days != null && days <= 7 ? 'var(--gold-600)' : 'var(--text-faint)'}">
        ${c.application_count} application${c.application_count === 1 ? '' : 's'} · ${esc(due)}</div>
    </button>`;
  }).join('')}</div>`;
}

function knowledgeCategoryLabel(key) {
  const found = (STATE.knowledge_categories || []).find(c => c.key === key);
  return found ? found.label : (key || 'Other');
}

function openFirm(firm, quiet = false) {
  const data = (STATE.firms || []).find(f => f.firm === firm);
  if (!data) return;
  PANEL = { kind: 'firm', id: firm };

  const byCategory = {};
  data.knowledge.forEach(k => (byCategory[k.category] = byCategory[k.category] || []).push(k));

  openPanel(firm,
    `${data.chatted_count} spoken with · ${data.people_count} in the pipeline ·
     ${data.knowledge.length} note${data.knowledge.length === 1 ? '' : 's'}`, `
    <div class="card" style="margin-bottom:18px;padding:12px 14px">
      <div class="small" style="line-height:1.55">${esc(data.brief || '')}</div>
      <div class="small faint" style="margin-top:7px">A fixed description of the
        firm, not something you were told — what people actually said is below,
        with their name on it.</div>
    </div>

    <h2 style="margin-top:0">Knowledge</h2>
    <p class="small muted" style="margin-top:-6px">${data.knowledge.length
      ? `${data.knowledge.length} note${data.knowledge.length === 1 ? '' : 's'} on file
         — ${data.knowledge.filter(k => k.source_type === 'chat').length} from chats,
         ${data.knowledge.filter(k => k.source_type === 'research').length} from research.
         ${(() => {
           const missing = (STATE.knowledge_categories || [])
             .filter(c => c.key !== 'other' && !data.knowledge.some(k => k.category === c.key))
             .map(c => c.label.toLowerCase());
           return missing.length ? `Nothing yet on ${missing.join(', ')}.` : 'Every category covered.';
         })()}`
      : 'Nothing on file yet. Add what you learn as you learn it.'}</p>
    ${Object.keys(byCategory).map(cat => `
      <h4 style="margin:14px 0 8px">${esc(knowledgeCategoryLabel(cat))}</h4>
      ${byCategory[cat].map(k => `
        <div class="know ${k.source_type === 'research' ? 'research' : ''}">${esc(k.body)}<div class="meta">${[
          k.source_type === 'research' ? 'research' : 'chat',
          k.source_person ? esc(k.source_person) : '',
          k.source_label ? esc(k.source_label) : '',
          k.source_url ? `<a href="${esc(k.source_url)}" target="_blank" rel="noreferrer">source</a>` : '',
          dateLabel(k.created_at),
        ].filter(Boolean).join(' · ')} <a href="#" data-delknow="${k.id}" style="margin-left:8px;color:var(--danger)">remove</a></div></div>`).join('')}`).join('')}

    <div class="card" style="margin:14px 0 16px;padding:12px 14px">
      <div class="row" style="margin-bottom:8px">
        <select id="k-category" style="max-width:180px">${(STATE.knowledge_categories || []).map(c =>
          `<option value="${c.key}">${esc(c.label)}</option>`).join('')}</select>
        <select id="k-source-type" style="max-width:150px">
          <option value="chat">From a chat</option>
          <option value="research">From research</option>
        </select>
        <input type="text" id="k-source-label" placeholder="Who or where, and when" style="flex:1;min-width:160px">
      </div>
      <div class="row">
        <textarea id="k-body" rows="2" placeholder="What did you learn about ${esc(firm)}?"
          style="flex:1;min-width:220px;font-family:var(--sans);font-size:13px"></textarea>
        <button class="btn sm" id="k-add" data-firm-add="${esc(firm)}">Add</button>
      </div>
    </div>

    <h2>People</h2>
    ${data.people.length ? data.people.map(p => `
      <div class="action clickable" data-open="${p.id}">
        <div class="grow"><span class="who">${esc(p.name)}</span>
          <span class="muted small">${p.role ? ' · ' + esc(p.role) : ''}${p.office ? ' · ' + esc(p.office) : ''}</span>
          <div class="detail">${esc(statusLabel(p.status))}${p.chat_at ? ' · chat ' + chatTimeLabel(p.chat_at) : ''}</div>
        </div>
        <button class="btn sm" data-open="${p.id}">Open</button>
      </div>`).join('')
      : '<div class="small faint">Nobody at this firm in the tracker yet.</div>'}

    <h2>Applications</h2>
    ${data.applications.length ? data.applications.map(a => `
      <div class="app-row ${deadlineTone(a)}" data-app="${a.id}">
        <div class="grow" style="flex:1;min-width:0">
          <span class="co">${esc(a.role || 'role not set')}</span>
          <div class="detail small muted">${esc(a.office || '')}</div>
        </div>
        <span class="chip">${esc(appStatusLabel(a.status))}</span>
        <span class="due ${deadlineTone(a)}">${esc(deadlineText(a))}</span>
      </div>`).join('')
      : '<div class="small faint">No application here yet.</div>'}`);
  if (quiet) { /* redrawn in place */ }
}

/* ------------------------------------------------------------- review */

/* A line-by-line diff, longest common subsequence, so the resume walk shows
   what actually moved rather than "the whole thing changed". */
function diffLines(before, after) {
  const a = String(before || '').split('\n');
  const b = String(after || '').split('\n');
  const grid = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      grid[i][j] = a[i] === b[j] ? grid[i + 1][j + 1] + 1
        : Math.max(grid[i + 1][j], grid[i][j + 1]);
    }
  }
  const left = [], right = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { left.push(['same', a[i]]); right.push(['same', b[j]]); i++; j++; }
    else if (grid[i + 1][j] >= grid[i][j + 1]) { left.push(['del', a[i]]); i++; }
    else { right.push(['add', b[j]]); j++; }
  }
  while (i < a.length) left.push(['del', a[i++]]);
  while (j < b.length) right.push(['add', b[j++]]);
  const paint = rows => rows.map(([tone, text]) =>
    `<div class="diff-line ${tone === 'same' ? '' : tone}">${esc(text) || '&nbsp;'}</div>`).join('');
  return { left: paint(left), right: paint(right) };
}

/* What a proposal would change, shown before it changes anything. */
function proposalPreview(p) {
  const payload = p.payload || {};
  if (p.kind === 'firm_knowledge') {
    return `<div class="know">${esc(payload.body || '')}
      <div class="meta">${esc(payload.firm || '')} · ${esc(knowledgeCategoryLabel(payload.category))}</div></div>`;
  }
  if (p.kind === 'resume_walk') {
    if (payload.add_feedback !== undefined) {
      return `<div class="diff-label">New coaching point</div>
        <div class="know">${esc(payload.add_feedback)}</div>`;
    }
    const current = (STATE.resume_walk || {}).body || '';
    const parts = diffLines(current, payload.new_text || '');
    return `<div class="diff">
      <div><div class="diff-label">Now</div>${parts.left || '<em class="faint">empty</em>'}</div>
      <div><div class="diff-label">Proposed</div>${parts.right}</div></div>`;
  }
  if (p.kind === 'person_update') {
    const who = STATE.people.find(x => x.id === p.person_id) || {};
    return Object.keys(payload).map(key => {
      if (key === 'takeaway') {
        return `<div class="note takeaway">${esc(payload[key])}<div class="meta">new takeaway note</div></div>`;
      }
      const was = key === 'status' ? statusLabel(who[key]) : (who[key] || '—');
      const now = key === 'status' ? statusLabel(payload[key]) : payload[key];
      return `<div class="small"><strong>${esc(key)}</strong>:
        <span style="text-decoration:line-through;color:var(--text-faint)">${esc(was)}</span>
        → ${esc(now)}</div>`;
    }).join('');
  }
  if (p.kind === 'application_update') {
    const match = (STATE.applications || []).find(a =>
      a.id === payload.match_id
      || (a.company.toLowerCase() === String(payload.company || '').toLowerCase()
          && (a.role || '').toLowerCase() === String(payload.role || '').toLowerCase()));
    return `<div class="small">${match ? `Updates <strong>${esc(match.company)}</strong>
        — ${esc(match.role || 'role not set')}` : 'Adds a new application'}:
      ${Object.keys(payload).filter(k => k !== 'match_id')
        .map(k => `<div><strong>${esc(k)}</strong>: ${esc(payload[k])}</div>`).join('')}</div>`;
  }
  return `<pre class="sent-body">${esc(JSON.stringify(payload, null, 2))}</pre>`;
}

const PROPOSAL_KIND_LABEL = {
  firm_knowledge: 'Firm knowledge', resume_walk: 'Resume walk',
  person_update: 'Person', application_update: 'Application',
};

function renderReview() {
  const all = STATE.proposals || [];
  const pending = all.filter(p => p.status === 'pending');
  const batches = {};
  pending.forEach(p => (batches[p.batch_id] = batches[p.batch_id] || []).push(p));

  $('#review-list').innerHTML = Object.keys(batches).length
    ? Object.keys(batches).map(batchId => {
      const items = batches[batchId];
      const batch = (STATE.proposal_batches || {})[batchId] || {};
      return `<div class="batch">
        <div class="row between" style="margin-bottom:6px">
          <div>
            <strong>${esc(batch.source_label || items[0].source_label || batchId)}</strong>
            <div class="small faint">${items.length} proposed change${items.length === 1 ? '' : 's'}
              · ${esc(batchId)}</div>
          </div>
          <div class="row" style="gap:6px">
            <button class="btn gold sm" data-batch-accept="${esc(batchId)}">Accept all</button>
            <button class="btn ghost sm" data-batch-reject="${esc(batchId)}">Reject all</button>
          </div>
        </div>
        ${batch.transcript ? `<details class="paste-box" style="margin-bottom:8px">
          <summary>Transcript</summary>
          <pre class="sent-body" style="margin-top:10px">${esc(batch.transcript)}</pre>
        </details>` : ''}
        ${items.map(p => `
          <div class="prop">
            <div class="row between">
              <span class="chip">${esc(PROPOSAL_KIND_LABEL[p.kind] || p.kind)}</span>
              <span class="row" style="gap:6px">
                <button class="btn gold sm" data-accept="${p.id}">Accept</button>
                <button class="btn sm" data-edit-accept="${p.id}">Edit…</button>
                <button class="btn ghost sm" data-reject="${p.id}">Reject</button>
              </span>
            </div>
            ${p.rationale ? `<div class="rationale">${esc(p.rationale)}</div>` : ''}
            ${proposalPreview(p)}
          </div>`).join('')}
      </div>`;
    }).join('')
    : `<div class="card empty"><div class="big">✓</div>Nothing waiting. Paste a
        transcript to Claude and its proposals land here.</div>`;

  const decided = all.filter(p => p.status !== 'pending').slice(0, 20);
  $('#review-decided').innerHTML = decided.length ? decided.map(p => `
    <div class="action low">
      <div class="grow">
        <span class="who">${esc(PROPOSAL_KIND_LABEL[p.kind] || p.kind)}</span>
        <div class="detail">${esc(p.source_label || p.batch_id)}${p.rationale ? ' — ' + esc(p.rationale) : ''}</div>
      </div>
      <span class="chip ${p.status === 'accepted' ? 'ok' : 'bad'}">${esc(p.status)}</span>
      <span class="small faint">${dateLabel(p.decided_at)}</span>
    </div>`).join('')
    : '<div class="small faint">Nothing decided yet.</div>';
}

/* Edit before accepting: the payload as JSON, because a proposal's shape
   depends on its kind and inventing a form per kind would go stale the first
   time a new field appears. */
function openEditProposal(id) {
  const prop = (STATE.proposals || []).find(p => p.id === id);
  if (!prop) return;
  openModal('Edit, then accept', `
    <p class="small muted">${esc(PROPOSAL_KIND_LABEL[prop.kind] || prop.kind)} —
      ${esc(prop.source_label || prop.batch_id)}. What you leave here is what
      gets applied, and what Review records as having happened.</p>
    <label class="field"><span>Payload</span>
      <textarea id="pe-json" rows="14" style="font-family:var(--mono);font-size:12.5px">${esc(JSON.stringify(prop.payload, null, 2))}</textarea></label>
    <div class="row"><button class="btn gold" id="pe-save">Accept with these changes</button>
      <span class="small faint" id="pe-note"></span></div>`);
  $('#pe-save').onclick = async () => {
    let payload;
    try {
      payload = JSON.parse($('#pe-json').value);
    } catch (e) {
      $('#pe-note').textContent = 'That is not valid JSON yet.';
      return;
    }
    await decideProposal({ id, status: 'accepted', payload });
    closeModal();
  };
}

async function decideProposal(body) {
  try {
    const res = await api('/api/proposal/decide', 'POST', body);
    const first = (res.results || [])[0] || {};
    toast(res.ok ? (first.applied || 'Done') : (first.error || res.error), !res.ok);
  } catch (e) {
    toast(e.message, true);
  }
  return refresh();
}

/* --------------------------------------------------------- resume walk */

function fillResumeWalk() {
  const walk = STATE.resume_walk || { versions: [], feedback: [] };
  const box = $('#rw-body');
  // Never overwrite what is being typed — the same rule as the drawer.
  if (box && document.activeElement !== box) box.value = walk.body || '';
  $('#rw-meta').textContent = walk.updated_at
    ? `${walk.versions.length} version${walk.versions.length === 1 ? '' : 's'} ·
       last changed ${dateLabel(walk.updated_at)}${walk.source ? ' · ' + walk.source : ''}`
    : 'Nothing written yet.';

  $('#rw-feedback').innerHTML = walk.feedback.length ? walk.feedback.map(fb => `
    <div class="note takeaway">${esc(fb.body)}<div class="meta">${fb.source ? esc(fb.source) + ' · ' : ''}${dateLabel(fb.created_at)} <a href="#" data-delfeedback="${fb.id}" style="margin-left:8px;color:var(--danger)">remove</a></div></div>`).join('')
    : '<div class="small faint">No coaching points yet.</div>';

  $('#rw-versions').innerHTML = walk.versions.length ? walk.versions.map((v, index) => `
    <details class="paste-box" style="margin-bottom:6px">
      <summary>${index === 0 ? 'Current' : 'Version ' + (walk.versions.length - index)} ·
        ${dateLabel(v.created_at)}${v.source ? ' · ' + esc(v.source) : ''}</summary>
      <pre class="sent-body" style="margin-top:10px">${esc(v.body)}</pre>
    </details>`).join('')
    : '<div class="small faint">Saving the script above starts the history.</div>';
}

/* --------------------------------------------------------------- slots */

function fillSettings() {
  const s = STATE.settings;
  const set = (id, key) => { const el = $(id); if (el) el.value = s[key] != null ? s[key] : ''; };
  ['user_name', 'user_email', 'user_pitch', 'zoom_link', 'hold_calendar', 'chat_calendar', 'timezone',
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
    const res = await api('/api/slots.ics', 'POST', { days, label: holdLabel });
    toast(res.opened
      ? `${res.count} hold${res.count === 1 ? '' : 's'} saved to the holds folder — Calendar is opening it`
      : `${res.count} hold${res.count === 1 ? '' : 's'} saved to the holds folder as "${res.file}"`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function calendarNote(cal, lead) {
  cal = cal || {};
  if (cal.error) return `${lead} — Calendar not updated (${cal.error})`;
  if (cal.updated) return `${lead} — moved in Calendar`;
  if (cal.created) return `${lead} — added to Calendar`;
  return lead;
}

/* Two-click confirm on the button itself, instead of a blocking dialog. */
function confirmInline(button, prompt) {
  if (button.dataset.armed) return true;
  const label = button.textContent;
  button.dataset.armed = '1';
  button.textContent = prompt;
  setTimeout(() => { delete button.dataset.armed; button.textContent = label; }, 4000);
  return false;
}

/* Marks one of the offered windows as the one that was actually accepted:
   sets the chat date and moves the person to Chat scheduled. The server edits
   Apple Calendar directly (the picked hold becomes the real meeting, the other
   holds are deleted) and keeps an .ics record in "confirmed slots". */
async function confirmSlot(personId, start, end, button) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Confirming…';
  try {
    const res = await api('/api/confirm-slot', 'POST', { person_id: personId, start, end });
    const cal = res.calendar || {};
    const placed = cal.created || cal.updated;
    let msg = placed ? 'Chat confirmed and added to Calendar'
      : res.imported ? 'Chat confirmed — added from the confirmed slots folder'
      : `Chat confirmed — saved "${res.file}" in the confirmed slots folder`;
    if (res.holds) msg += cal.deleted >= res.holds
      ? `; ${cal.deleted} hold${cal.deleted === 1 ? '' : 's'} removed`
      : `; ${cal.deleted || 0} of ${res.holds} holds removed (delete the rest by hand)`;
    if (cal.error) msg += ` (Calendar: ${cal.error})`;
    toast(msg + ' — next: Confirmation email in their panel', !!cal.error);
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
  const t = ev.target.closest('[data-view], [data-open], [data-prep], [data-slots], [data-pdf], [data-draft], [data-sent], [data-status], [data-copy-text], [data-delnote], [data-goto], [data-resolve], [data-restore]');
  if (!t) return;

  if (t.dataset.resolve) {
    const action = (STATE.actions || []).find(a => a.key === t.dataset.resolve);
    if (!action) return;
    try {
      await api('/api/action/resolve', 'POST', {
        key: action.key, person_id: action.person_id, kind: action.kind,
        label: action.label, detail: action.detail, name: action.name,
      });
      toast(action.kind === 'thankyou'
        ? `${action.name} moved to Thank-you sent`
        : 'Ticked off for today — in the bin below');
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
  if (t.dataset.sent) return openSentMail(parseInt(t.dataset.id, 10), t.dataset.sent);
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
  const firm = el.dataset.treeFirm;
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

  if (id === 'd-chat-edit') {
    const box = $('#d-chat-editor');
    box.style.display = box.style.display === 'none' ? '' : 'none';
    return;
  }

  if (id === 'd-resched-save') {
    if (!CURRENT) return;
    const when = readChatTimeFields('d-resched');
    if (when.error) return toast(when.error, true);
    try {
      const res = await api('/api/chat/reschedule', 'POST', { person_id: CURRENT.id, ...when });
      toast(calendarNote(res.calendar, 'Chat rescheduled'), !!res.calendar.error);
      await refresh();
      return openPerson(CURRENT.id, true);
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'd-confirm-mail') {
    if (!CURRENT) return;
    const first = (CURRENT.name || '').trim().split(' ')[0];
    const emailText = `Hi ${first},\n\nThank you for getting back to me. I am sending the calendar invite accordingly. I hope you are fine with a zoom meeting, let me know otherwise.\n\nLooking forward to chatting with you.`;
    const inviteText = `Hi ${first},\n\nSharing the invite based on the slot you suggested. I have attached my resume here for your reference. Looking forward to connecting!`;
    openModal('Confirmation email — ' + CURRENT.name, `
      <label class="field"><span>Email</span><textarea id="m-text-email" rows="7">${esc(emailText)}</textarea></label>
      <div class="row" style="margin-bottom:16px"><button class="btn primary" data-copy-from="m-text-email">Copy email</button></div>
      <label class="field"><span>Invite</span><textarea id="m-text-invite" rows="5">${esc(inviteText)}</textarea></label>
      <div class="row"><button class="btn primary" data-copy-from="m-text-invite">Copy invite</button></div>`);
    document.querySelectorAll('[data-copy-from]').forEach(b => b.onclick = async () => {
      toast(await copyText($('#' + b.dataset.copyFrom).value) ? 'Copied' : 'Could not copy — select the text manually');
    });
    return;
  }

  if (id === 'd-invite') {
    if (!CURRENT) return;
    const btn = ev.target;
    btn.disabled = true;
    const invite = id === 'd-invite';
    try {
      const res = await api(invite ? '/api/chat/invite' : '/api/chat/confirmation', 'POST',
                            { person_id: CURRENT.id });
      if (!res.ok) { toast(res.error || 'Could not create the draft', true); return; }
      let msg;
      if (res.demo) msg = 'Demo mode — nothing opened in Outlook';
      else if (invite) msg = res.attached ? 'Invite open in Outlook with your resume — press Send'
        : res.has_resume ? 'Invite open in Outlook — the resume could not be attached, add it by hand'
        : 'Invite open in Outlook — no resume uploaded in Settings';
      else msg = res.threaded ? 'Reply open in Outlook, in their thread — press Send'
        : 'No email from them found — opened a new email instead';
      toast(msg, invite && !res.attached && !res.demo);
      await refresh();
      return openPerson(CURRENT.id, true);
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; }
    return;
  }

  if (id === 'd-chat-cancel') {
    if (!CURRENT) return;
    if (!confirmInline(ev.target, 'Sure? Cancel chat')) return;
    try {
      const res = await api('/api/chat/cancel', 'POST', { person_id: CURRENT.id });
      const cal = res.calendar || {};
      toast(cal.error ? `Chat cleared — remove it from Calendar by hand (${cal.error})`
        : cal.deleted ? 'Chat cancelled and removed from Calendar'
        : 'Chat cleared — no matching event was on the calendar', !!cal.error);
      await refresh();
      return openPerson(CURRENT.id, true);
    } catch (e) { return toast(e.message, true); }
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

  if (id === 'd-edit-slots') {
    if (!CURRENT) return;
    return openSuggestSlots(CURRENT.id, { editSaved: true });
  }


  if (id === 'd-clear-slots') {
    if (!CURRENT) return;
    try {
      const res = await api('/api/offered-slots', 'POST', { person_id: CURRENT.id, clear: true });
      const cal = res.calendar || {};
      toast(cal.error ? `Cleared — remove the holds from Calendar by hand (${cal.error})`
        : 'Cleared — holds removed from Calendar', !!cal.error);
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'd-confirm-btn') {
    if (!CURRENT) return;
    const when = readChatTimeFields('d-confirm');
    if (when.error) return toast(when.error, true);
    return confirmSlot(CURRENT.id, when.start, when.end, ev.target);
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

  if (id === 'btn-save-cals') {
    try {
      await api('/api/settings', 'POST', { hold_calendar: $('#s-hold_calendar').value.trim(),
                                          chat_calendar: $('#s-chat_calendar').value.trim() });
      toast('Calendars saved — new holds and chats go there');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'btn-save-zoom') {
    try {
      await api('/api/settings', 'POST', { zoom_link: $('#s-zoom_link').value.trim() });
      toast('Zoom link saved');
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

  if (id === 'btn-cal-pull') {
    try {
      const res = await api('/api/calendar/pull', 'POST', {});
      const n = res.changes.length;
      toast(n ? `Updated from Calendar: ${res.changes.map(c => c.name).join(', ')}`
              : 'Already matches your calendar');
      await refresh();
    } catch (e) {
      toast(e.message || String(e), true);
    }
    return;
  }

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

/* ------------------------- applications, firms, review: events ---------- */

document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-app], [data-firm], [data-accept], [data-reject], '
    + '[data-edit-accept], [data-batch-accept], [data-batch-reject], [data-open-file], '
    + '[data-delknow], [data-delfeedback], [data-firm-add]');
  const id = ev.target.id;

  if (id === 'p-close' || id === 'panel-scrim') return closePanel();
  if (id === 'btn-add-app') return openAddApplication();

  if (id === 'p-delete-app') {
    if (!PANEL || PANEL.kind !== 'application') return;
    const btn = ev.target;
    if (btn.dataset.armed !== '1') {
      btn.dataset.armed = '1'; btn.textContent = 'Really delete?';
      setTimeout(() => { btn.dataset.armed = '0'; btn.textContent = 'Delete'; }, 4000);
      return;
    }
    await api('/api/application/' + PANEL.id, 'DELETE');
    closePanel();
    toast('Application deleted');
    return refresh();
  }

  if (id === 'rw-save') {
    try {
      await api('/api/resume-walk', 'POST', { body: $('#rw-body').value, source: 'you' });
      toast('Saved — the previous version is in the history below');
    } catch (e) { toast(e.message, true); }
    return refresh();
  }

  if (id === 'rw-fb-add') {
    const body = $('#rw-fb-body').value.trim();
    if (!body) return toast('Write the coaching point first', true);
    try {
      await api('/api/resume-walk/feedback', 'POST', {
        body, source: $('#rw-fb-source').value.trim(),
      });
      $('#rw-fb-body').value = '';
      $('#rw-fb-source').value = '';
    } catch (e) { toast(e.message, true); }
    return refresh();
  }

  if (!t) return;

  if (t.dataset.firmAdd) {
    const body = $('#k-body').value.trim();
    if (!body) return toast('Write the note first', true);
    try {
      await api('/api/knowledge', 'POST', {
        firm: t.dataset.firmAdd, category: $('#k-category').value,
        body, source_type: $('#k-source-type').value,
        source_label: $('#k-source-label').value.trim(),
      });
      toast('Added');
    } catch (e) { toast(e.message, true); }
    return refresh();
  }

  if (t.dataset.delknow) {
    ev.preventDefault();
    await api('/api/knowledge/' + t.dataset.delknow, 'DELETE');
    return refresh();
  }

  if (t.dataset.delfeedback) {
    ev.preventDefault();
    await api('/api/resume-walk/feedback/' + t.dataset.delfeedback, 'DELETE');
    return refresh();
  }

  if (t.dataset.openFile) {
    try {
      await api('/api/application/' + t.dataset.id + '/open', 'POST',
                { which: t.dataset.openFile });
      toast('Opening…');
    } catch (e) { toast(e.message, true); }
    return;
  }

  if (t.dataset.app) return openApplication(parseInt(t.dataset.app, 10));
  if (t.dataset.firm) return openFirm(t.dataset.firm);
  if (t.dataset.accept) return decideProposal({ id: parseInt(t.dataset.accept, 10), status: 'accepted' });
  if (t.dataset.reject) return decideProposal({ id: parseInt(t.dataset.reject, 10), status: 'rejected' });
  if (t.dataset.editAccept) return openEditProposal(parseInt(t.dataset.editAccept, 10));

  if (t.dataset.batchAccept || t.dataset.batchReject) {
    const accepting = !!t.dataset.batchAccept;
    try {
      const res = await api('/api/proposal/decide-batch', 'POST', {
        batch_id: t.dataset.batchAccept || t.dataset.batchReject,
        status: accepting ? 'accepted' : 'rejected',
      });
      toast(res.ok ? `${res.results.length} ${accepting ? 'applied' : 'rejected'}`
                   : res.error, !res.ok);
    } catch (e) { toast(e.message, true); }
    return refresh();
  }
});

/* Application fields save on blur, one at a time, exactly like the person
   drawer — and for the same reason: redrawing loses what is being typed. */
document.addEventListener('change', (ev) => {
  const field = ev.target.closest('[data-af]');
  if (field && $('#panel').classList.contains('open')) {
    let value = field.value;
    if (field.dataset.af === 'archived') value = parseInt(value, 10);
    return saveAppField(field.dataset.af, value);
  }
  if (['app-status', 'app-archived'].includes(ev.target.id)) renderApplications();
});

document.addEventListener('input', (ev) => {
  if (ev.target.id === 'app-search') renderApplications();
});

document.addEventListener('keydown', (ev) => {
  // Close the topmost thing only, so Escape out of a person opened from a
  // firm page leaves the firm page where it was.
  if (ev.key !== 'Escape') return;
  if ($('#modal').classList.contains('open')) return closeModal();
  if ($('#drawer').classList.contains('open')) return closeDrawer();
  return closePanel();
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


/* Sent / not sent ticks in the person window. They override whatever the app
   inferred, and move the pipeline status the way sending would. */
document.addEventListener('change', async (ev) => {
  const box = ev.target.closest && ev.target.closest('[data-sent-toggle]');
  if (!box || !CURRENT) return;
  const kind = box.dataset.sentToggle, on = box.checked;
  const flags = Object.assign(sentFlags(CURRENT), { [kind]: on });
  const patch = { sent_flags: JSON.stringify(flags) };
  const now = new Date().toISOString();
  const st = CURRENT.status;
  if (kind === 'outreach' && on && ['uninitiated', 'tracking'].includes(st)) {
    patch.status = 'outreach_sent'; patch.first_contact_at = now;
  }
  if (kind === 'thankyou') {
    if (on) { patch.thankyou_sent_at = now; if (st === 'chat_done') patch.status = 'thankyou_sent'; }
    else { patch.thankyou_sent_at = null; if (st === 'thankyou_sent') patch.status = 'chat_done'; }
  }
  try {
    await api('/api/person/' + CURRENT.id, 'POST', patch);
    toast((on ? 'Marked as sent' : 'Marked as not sent'));
    await refresh();
    return openPerson(CURRENT.id, true);
  } catch (e) { box.checked = !on; toast(e.message, true); }
});
