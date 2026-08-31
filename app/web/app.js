/* Coffee Chat Tracker — interface logic. No frameworks, no network. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

let STATE = { people: [], settings: {}, statuses: [], actions: [], coverage: [], upcoming: [], questions: [] };
let SLOTS = null;          // last generated availability
let CURRENT = null;        // person open in the drawer

const STATUS_TONE = {
  uninitiated: '', outreach_sent: 'warn', awaiting_reply: 'warn',
  scheduled: 'gold', chat_done: 'ok', thankyou_sent: 'ok',
  nurturing: 'ok', no_response: 'bad',
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

/* ------------------------------------------------------------ rendering */

async function refresh() {
  STATE = await api('/api/state');
  renderToday();
  renderPipeline();
  fillSettings();
  renderPrep();
  updateNavCounts();
  if (CURRENT) openPerson(CURRENT.id, true);
}

function updateNavCounts() {
  $('#nav-actions').textContent = STATE.actions.length;
  $('#nav-actions').classList.toggle('hot', STATE.actions.some(a => a.urgency === 'overdue'));
  $('#nav-people').textContent = STATE.people.length;
}

function renderToday() {
  const people = STATE.people;
  const count = key => people.filter(p => p.status === key).length;
  const chatted = people.filter(p => ['chat_done', 'thankyou_sent', 'nurturing'].includes(p.status)).length;
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
        <div class="detail">${esc(a.label)} — ${esc(a.detail)}</div>
      </div>
      ${a.kind === 'thankyou' ? `<button class="btn gold sm" data-draft="thankyou" data-id="${a.person_id}">Draft thank-you</button>` : ''}
      ${a.kind === 'followup' ? `<button class="btn gold sm" data-draft="followup" data-id="${a.person_id}">Draft nudge</button>` : ''}
      <button class="btn sm" data-open="${a.person_id}">Open</button>
    </div>`).join('')
    : `<div class="card empty"><div class="big">✓</div>Nothing overdue. Good place to be.</div>`;

  $('#upcoming').innerHTML = STATE.upcoming.length ? STATE.upcoming.map(u => `
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
      <div>${esc(c.firm)} ${c.is_target ? '<span class="chip gold">target</span>' : ''}</div>
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
        ${p.is_alum ? '<span class="chip ok" style="margin-left:5px">alum</span>' : ''}</td>
      <td>${esc(p.firm || '—')}</td>
      <td class="muted">${esc(p.role || '—')}</td>
      <td><select data-status="${p.id}">${STATE.statuses.map(s =>
        `<option value="${s.key}"${s.key === p.status ? ' selected' : ''}>${esc(s.label)}</option>`).join('')}</select></td>
      <td class="muted small">${dateLabel(p.last_outbound_at || p.first_contact_at)}</td>
      <td class="muted small">${p.chat_at ? dateLabel(p.chat_at) : '—'}</td>
      <td><button class="btn ghost sm" data-open="${p.id}">›</button></td>
    </tr>`).join('');

  $('#pipeline-empty').innerHTML = rows.length ? '' :
    `<div class="card empty" style="margin-top:14px"><div class="big">☕</div>
      ${STATE.people.length ? 'Nothing matches those filters.'
        : 'No one here yet. Start with second-years and younger consultants — they say yes most.'}</div>`;
}

function renderPrep() {
  $('#call-structure').innerHTML = [
    ['Before', 'Research them and the firm. Send the request with your resume and three hour-long slots. Once confirmed, send a calendar invite with an agenda.'],
    ['First 2 minutes', 'Small talk. Make it personal. Reference something specific they have said or done.'],
    ['Set the structure', '"Thank you for taking the time — I\'d like to introduce myself and then hear more about your experience. Does that work for you?"'],
    ['Resume walk', '90 seconds to 2 minutes. Thread your history into why consulting.'],
    ['Q&A', 'Tailor to their background. Follow the flow rather than your list.'],
    ['After', 'Thank-you note inside 24 hours with specifics. Contact any introductions within 24 hours. Log what you learned.'],
  ].map(([k, v]) => `<div style="display:grid;grid-template-columns:130px 1fr;gap:14px;padding:8px 0;border-bottom:1px solid var(--border)">
      <div style="font-weight:600;color:var(--navy-700)">${k}</div><div class="muted">${esc(v)}</div></div>`).join('')
    .replace(/border-bottom:1px solid var\(--border\)"><div style="font-weight:600;color:var\(--navy-700\)">After/, 'border-bottom:0"><div style="font-weight:600;color:var(--navy-700)">After');

  const tier = $('#q-tabs button.active').dataset.tier;
  const list = STATE.questions.filter(q => !tier || q.tier === tier);
  $('#questions').innerHTML = list.map((q, i) => `
    <div class="qbank-item ${q.tier}">
      <div class="grow" style="flex:1">${esc(q.text)}</div>
      <button class="btn ghost sm" data-copy-q="${i}">Copy</button>
    </div>`).join('');
  $('#questions').dataset.list = JSON.stringify(list.map(q => q.text));
}

/* -------------------------------------------------------------- drawer */

async function openPerson(id, quiet = false) {
  const person = await api('/api/person/' + id);
  if (!person) return;
  CURRENT = person;
  $('#d-name').textContent = person.name;
  $('#d-sub').innerHTML = `${esc(person.role || '')}${person.role && person.firm ? ' · ' : ''}${esc(person.firm || '')}
    <span class="chip ${STATUS_TONE[person.status] || ''}" style="margin-left:6px">${esc(statusLabel(person.status))}</span>`;

  const f = (id_, label, value, type = 'text') =>
    `<label class="field"><span>${label}</span><input type="${type}" data-f="${id_}" value="${esc(value || '')}"></label>`;

  $('#drawer-body').innerHTML = `
    <div class="row" style="margin-bottom:16px">
      <button class="btn primary sm" data-draft="outreach" data-id="${person.id}">Draft outreach</button>
      <button class="btn sm" data-draft="followup" data-id="${person.id}">Draft nudge</button>
      <button class="btn gold sm" data-draft="thankyou" data-id="${person.id}">Draft thank-you</button>
      <button class="btn sm" data-prep="${person.id}">Prep sheet${person.linkedin_raw ? ' ✓' : ''}</button>
    </div>

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
      ${f('next_action', 'Next action', person.next_action)}
      ${f('next_action_date', 'Due', (person.next_action_date || '').slice(0, 10), 'date')}
    </div>
    ${f('source', 'How you found them', person.source)}

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

async function openDraft(personId, kind) {
  const labels = { outreach: 'Outreach email', followup: 'Follow-up nudge', thankyou: 'Thank-you note' };
  openModal(labels[kind] || 'Draft', '<div class="empty small">Building the draft…</div>');

  let highlights = '';
  if (kind === 'thankyou') {
    const person = await api('/api/person/' + personId);
    highlights = person.notes.filter(n => n.kind === 'takeaway').map(n => n.body).join(' ');
  }

  let draft;
  try {
    draft = await api('/api/draft', 'POST', { person_id: personId, kind, highlights });
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
      <summary>${prep.has_profile ? 'Update the pasted profile' : 'Paste their LinkedIn profile'}</summary>
      <p class="small muted" style="margin:10px 0">
        LinkedIn requires a login and blocks automated fetching from outside the
        browser, so this reads a tab you already have open instead. Open ${link}
        in Safari or Chrome, make it the front tab, and click Fetch — or select
        the page (⌘A), copy (⌘C), and paste below yourself. Either way, nothing
        leaves this Mac. The Experience and Education sections are the parts
        that matter.
      </p>
      <div class="row" style="margin-bottom:8px">
        <button class="btn ghost sm" id="prep-fetch" data-id="${p.id}">Fetch from open browser tab</button>
      </div>
      <textarea id="prep-raw" rows="7" placeholder="Paste the profile here…"></textarea>
      <button class="btn primary sm" id="prep-parse" data-id="${p.id}" style="margin-top:8px">
        ${prep.has_profile ? 'Re-read profile' : 'Build prep sheet'}</button>
    </details>`;

  if (!prep.has_profile) {
    return `
      ${prep.parsed_nothing ? `<div class="banner warn">That paste didn't contain anything
        recognisable as work history. Make sure the Experience section is included —
        or just work from the general questions below.</div>` : ''}
      ${pasteBox}
      <div class="banner info">Without a profile these questions are solid but generic.
        Paste the profile above and they become specific to ${esc(p.name)}.</div>
      ${prepQuestionsHtml(prep)}
      ${prepFlowHtml(prep)}
      ${prepDownloadHtml(p)}`;
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

  return `
    <div class="card" style="border-left:3px solid var(--gold-500)">
      <h3 style="margin-bottom:6px">Summary</h3>
      <div style="line-height:1.6">${esc(prep.summary)}</div>
      ${signals}
      <div class="small muted"><strong>First two minutes:</strong> ${esc(prep.opener)}</div>
    </div>
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

  const fetchBtn = $('#prep-fetch');
  if (fetchBtn) {
    fetchBtn.onclick = async () => {
      fetchBtn.disabled = true;
      fetchBtn.textContent = 'Reading tab…';
      try {
        const res = await api('/api/browser-profile', 'POST', {});
        $('#prep-raw').value = res.text || '';
        toast(res.demo ? 'Demo profile loaded (not running on macOS)'
                        : `Pulled from ${res.browser}: ${res.url}`);
      } catch (e) {
        toast(e.message, true);
      } finally {
        fetchBtn.disabled = false;
        fetchBtn.textContent = 'Fetch from open browser tab';
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

function openAddPerson() {
  openModal('Add person', `
    <div class="row" style="margin-bottom:10px">
      <button class="btn ghost sm" id="n-fetch">Fill from open LinkedIn tab</button>
      <span class="small faint">Reads the profile you're already looking at in Safari or Chrome.</span>
    </div>
    <div class="grid-2">
      <label class="field"><span>Name *</span><input type="text" id="n-name"></label>
      <label class="field"><span>Email</span><input type="email" id="n-email"></label>
      <label class="field"><span>Firm</span><input type="text" id="n-firm"></label>
      <label class="field"><span>Role</span><input type="text" id="n-role"></label>
    </div>
    <label class="field"><span>LinkedIn URL</span><input type="text" id="n-linkedin"></label>
    <label class="field"><span>How you found them</span><input type="text" id="n-source" placeholder="GCA board, LinkedIn, intro from…"></label>
    <div class="row"><button class="btn primary" id="n-save">Add</button>
      <span class="small faint">Start with second-years and recent grads.</span></div>`);

  $('#n-fetch').onclick = async () => {
    const fbtn = $('#n-fetch');
    fbtn.disabled = true;
    fbtn.textContent = 'Reading tab…';
    try {
      const res = await api('/api/browser-profile', 'POST', {});
      if (res.name) $('#n-name').value = res.name;
      if (res.firm) $('#n-firm').value = res.firm;
      if (res.role) $('#n-role').value = res.role;
      if (res.url) $('#n-linkedin').value = res.url;
      $('#n-source').value = 'LinkedIn';
      toast(res.demo ? 'Demo profile loaded (not running on macOS)'
                      : 'Filled from the open profile — check it over before saving.');
    } catch (e) {
      toast(e.message, true);
    } finally {
      fbtn.disabled = false;
      fbtn.textContent = 'Fill from open LinkedIn tab';
    }
  };

  $('#n-save').onclick = async () => {
    const name = $('#n-name').value.trim();
    if (!name) return toast('A name is required', true);
    const res = await api('/api/person', 'POST', {
      name, email: $('#n-email').value.trim(), firm: $('#n-firm').value.trim(),
      role: $('#n-role').value.trim(), linkedin: $('#n-linkedin').value.trim(),
      source: $('#n-source').value.trim(),
    });
    closeModal();
    await refresh();
    openPerson(res.person.id);
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

const DAY_NAMES = [['1', 'Mon'], ['2', 'Tue'], ['3', 'Wed'], ['4', 'Thu'], ['5', 'Fri'], ['6', 'Sat'], ['7', 'Sun']];

function fillSettings() {
  const s = STATE.settings;
  const set = (id, key) => { const el = $(id); if (el) el.value = s[key] != null ? s[key] : ''; };
  ['user_name', 'user_email', 'user_program', 'user_school', 'user_phone',
   'user_linkedin', 'resume_path', 'timezone', 'target_firms',
   'followup_after_days', 'max_followups', 'thankyou_within_hours']
    .forEach(k => set('#s-' + k, k));
  ['work_start', 'work_end', 'tz_label', 'min_window_minutes', 'buffer_minutes',
   'lead_days', 'horizon_days', 'slots_wanted', 'max_per_day', 'excluded_calendars']
    .forEach(k => set('#r-' + k, k));

  const active = new Set((s.work_days || '1,2,3,4,5').split(','));
  $('#r-work_days').innerHTML = DAY_NAMES.map(([n, label]) =>
    `<button class="btn sm ${active.has(n) ? 'primary' : ''}" data-day="${n}">${label}</button>`).join('');

  const sig = [s.user_name, s.user_program, s.user_school,
    [s.user_email, s.user_phone].filter(Boolean).join(' | '), s.user_linkedin]
    .filter(Boolean).join('\n');
  $('#sig-preview').textContent = 'Best,\n' + (sig || '[fill in your details above]');
}

function renderSlots() {
  if (!SLOTS) return;
  const banner = SLOTS.demo
    ? `<div class="banner warn">Demo calendar — install on your Mac to read the real one.</div>`
    : SLOTS.note ? `<div class="banner info">${esc(SLOTS.note)}</div>` : '';
  $('#slots-banner').innerHTML = banner;

  if (!SLOTS.days.length) {
    $('#slots-result').innerHTML = `<div class="card empty">No windows fit those rules.
      Try widening your working hours, shortening the minimum window, or looking
      further ahead.</div>`;
    return;
  }

  const emailBlock = SLOTS.lines.map(l => '• ' + l).join('\n');
  $('#slots-result').innerHTML = `
    <div class="card">
      <div class="row between" style="margin-bottom:12px">
        <h3 style="margin:0">Offer these</h3>
        <span class="small faint">${SLOTS.event_count} calendar events considered</span>
      </div>
      ${SLOTS.lines.map(l => `<div class="slotline">• ${esc(l)}</div>`).join('')}
      <div class="row" style="margin-top:12px">
        <button class="btn primary" id="btn-copy-slots">Copy for email</button>
        <span class="small faint">Paste straight into an outreach draft.</span>
      </div>
      <div class="row" style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border)">
        <input type="text" id="slots-label" placeholder="Offering these to… (optional)"
               style="max-width:240px">
        <button class="btn" id="btn-ics">Download .ics</button>
        <span class="small faint" style="flex:1;min-width:220px">Adds these windows to
          Apple Calendar as <strong>busy</strong> holds, so nothing else takes the slot
          and they won't be offered to anyone else. Delete them if the chat falls through.</span>
      </div>
    </div>`;
  $('#btn-copy-slots').onclick = async () => {
    toast(await copyText(emailBlock) ? 'Slots copied' : 'Could not copy — select the text manually');
  };
  $('#btn-ics').onclick = (ev) => downloadSlotsIcs(ev.currentTarget);
}

async function downloadSlotsIcs(button) {
  if (!SLOTS || !SLOTS.days.length) return toast('Find your availability first', true);
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Building…';
  try {
    const res = await fetch('/api/slots.ics', {
      method: 'POST',
      headers: { 'X-CCT-Token': window.CCT_TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: SLOTS.days, label: ($('#slots-label').value || '').trim() }),
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
    const events = SLOTS.days.reduce((n, d) => n + d.windows.length, 0);
    toast(`${events} hold${events === 1 ? '' : 's'} saved — open the file to add them`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

async function findSlots() {
  const btn = $('#btn-find-slots');
  btn.disabled = true; btn.textContent = 'Reading your calendar…';
  try {
    SLOTS = await api('/api/slots', 'POST', {});
    renderSlots();
  } catch (e) {
    $('#slots-banner').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`;
    $('#slots-result').innerHTML = '';
  } finally {
    btn.disabled = false; btn.textContent = 'Find my availability';
  }
}

async function saveRules() {
  const patch = {};
  ['work_start', 'work_end', 'tz_label', 'min_window_minutes', 'buffer_minutes',
   'lead_days', 'horizon_days', 'slots_wanted', 'max_per_day', 'excluded_calendars']
    .forEach(k => { patch[k] = $('#r-' + k).value; });
  patch.work_days = $$('#r-work_days button.primary').map(b => b.dataset.day).join(',');
  await api('/api/settings', 'POST', patch);
  toast('Rules saved');
  await refresh();
}

/* --------------------------------------------------------------- wiring */

function switchView(name) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === name));
}

function setStatusDot(id, tone, text) {
  $(id).innerHTML = `<span class="dot ${tone}"></span>${esc(text)}`;
}

document.addEventListener('click', async (ev) => {
  const t = ev.target.closest('[data-view], [data-open], [data-prep], [data-pdf], [data-draft], [data-status], [data-day], [data-copy-q], [data-copy-text], [data-delnote], [data-goto], [data-tier]');
  if (!t) return;

  if (t.dataset.view) return switchView(t.dataset.view);
  if (t.dataset.goto) { ev.preventDefault(); return switchView(t.dataset.goto); }
  if (t.dataset.pdf) return downloadPrepPdf(parseInt(t.dataset.pdf, 10), t);
  if (t.dataset.prep) return openPrep(parseInt(t.dataset.prep, 10));
  if (t.dataset.open) return openPerson(parseInt(t.dataset.open, 10));
  if (t.dataset.draft) return openDraft(parseInt(t.dataset.id, 10), t.dataset.draft);
  if (t.dataset.copyText !== undefined) {
    return toast(await copyText(t.dataset.copyText)
      ? 'Question copied' : 'Could not copy — select the text manually', false);
  }

  if (t.dataset.day) {
    t.classList.toggle('primary');
    return;
  }
  if (t.dataset.tier !== undefined && t.parentElement.id === 'q-tabs') {
    $$('#q-tabs button').forEach(b => b.classList.remove('active'));
    t.classList.add('active');
    return renderPrep();
  }
  if (t.dataset.copyQ !== undefined) {
    const list = JSON.parse($('#questions').dataset.list || '[]');
    const ok = await copyText(list[parseInt(t.dataset.copyQ, 10)]);
    return toast(ok ? 'Question copied' : 'Could not copy — select the text manually');
  }
  if (t.dataset.delnote) {
    ev.preventDefault();
    await api('/api/note/' + t.dataset.delnote, 'DELETE');
    return refresh();
  }
});

document.addEventListener('change', async (ev) => {
  // Inline status change from the pipeline table
  const sel = ev.target.closest('[data-status]');
  if (sel) {
    try {
      await api('/api/person/' + sel.dataset.status, 'POST', { status: sel.value });
      toast('Status updated');
      return refresh();
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

document.addEventListener('click', async (ev) => {
  const id = ev.target.id;
  if (id === 'd-close' || id === 'scrim') return closeDrawer();
  if (id === 'm-close' || (ev.target.classList.contains('modal'))) return closeModal();
  if (id === 'btn-add') return openAddPerson();
  if (id === 'btn-import') return openImport();
  if (id === 'btn-find-slots') return findSlots();
  if (id === 'btn-save-rules') return saveRules();

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
      : ['user_name', 'user_email', 'user_program', 'user_school', 'user_phone',
         'user_linkedin', 'resume_path', 'timezone', 'target_firms'];
    const patch = {};
    keys.forEach(k => { patch[k] = $('#s-' + k).value; });
    try {
      await api('/api/settings', 'POST', patch);
      toast('Saved');
      return refresh();
    } catch (e) { return toast(e.message, true); }
  }

  if (id === 'btn-test-calendar') {
    $('#conn-result').innerHTML = '<div class="banner info">Reading your calendar…</div>';
    try {
      const res = await api('/api/slots', 'POST', {});
      $('#conn-result').innerHTML = `<div class="banner info">Read ${res.event_count}
        events and found ${res.days.length} offerable day${res.days.length === 1 ? '' : 's'}.
        ${res.demo ? ' (demo data)' : ''}</div>`;
      setStatusDot('#status-cal', res.demo ? 'warn' : 'ok', res.demo ? 'Calendar: demo' : 'Calendar connected');
    } catch (e) {
      $('#conn-result').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`;
      setStatusDot('#status-cal', 'bad', 'Calendar blocked');
    }
    return;
  }

  if (id === 'btn-test-outlook') {
    $('#conn-result').innerHTML = '<div class="banner info">Checking Outlook…</div>';
    try {
      const res = await api('/api/detect-outlook', 'POST', {});
      const o = res.outlook;
      const good = o.flavor === 'classic';
      $('#conn-result').innerHTML = `<div class="banner ${good ? 'info' : 'warn'}">
        <strong>${esc(o.flavor)}</strong> — ${esc(o.detail)}
        ${o.flavor === 'unscriptable' ? `<br><br>The "new Outlook" has no scripting
          support, so mail tracking is unavailable. Everything else works. To switch
          back, open Outlook and turn off the <em>New Outlook</em> toggle at the top
          right of the window.` : ''}</div>`;
      setStatusDot('#status-outlook', good ? 'ok' : 'warn',
        good ? 'Outlook connected' : 'Outlook limited');
    } catch (e) {
      $('#conn-result').innerHTML = `<div class="banner bad">${esc(e.message)}</div>`;
      setStatusDot('#status-outlook', 'bad', 'Outlook blocked');
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
