'use strict';
/* Career HQ front end: a small hash-routed single page. No build step, no framework. */

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const initials = (name) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
const firstName = (name) => name.split(/\s+/)[0];
const money = (v) => '$' + (v < 0.01 ? v.toFixed(5) : v.toFixed(4));
const num = (v) => Number(v || 0).toLocaleString();

// Simple line icons (24x24, drawn with the current text color), so the app needs no icon font.
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.3-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.6c2.6.2 4.4 1.9 5 5.4"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>',
  scale: '<path d="M12 3v18M7 21h10M5 7h14"/><path d="M5 7l-3 6a3 3 0 0 0 6 0L5 7zM19 7l-3 6a3 3 0 0 0 6 0l-3-6z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
  network: '<circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M10.8 7.2 6.2 16.8M13.2 7.2l4.6 9.6M7.5 19h9"/>',
  gauge: '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/><circle cx="12" cy="18" r="1.3"/>',
  chat: '<path d="M4 5h16v10H9l-5 4V5z"/><path d="M8 9h8M8 12h5"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5 5-2z"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
};
const icon = (name, size = 18) => `<svg class="ic" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;

// The user's 1-3 recruiting tracks, loaded from /api/lookups. Colors follow track order.
let trackList = [];
const trackOf = (key) => trackList.find((t) => t.key === key);
const trackChip = (key, label = 'short') => {
  const t = trackOf(key);
  return t ? `<span class="chip t${t.position}">${esc(t[label])}</span>` : '';
};
async function refreshTracks() {
  lookups = await api('/lookups');
  trackList = lookups.tracks;
}

let status = null;
let lookups = { employers: [], paths: [] };
const pathName = (key) => lookups.paths.find((p) => p.key === key)?.name || '';

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
}

function toast(message) {
  const t = $('#toast');
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3800);
}

async function api(path, options = {}) {
  const res = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json' } });
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = body?.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}

/* ---------- shell ---------- */

async function refreshStatus() {
  status = await api('/status');
  if (!trackList.length && !status.needs_setup) await refreshTracks();
  const contacts = await api('/contacts');
  const pending = contacts.reduce((n, c) => n + c.pending, 0);
  const badge = $('#nav-pending');
  badge.hidden = pending === 0;
  badge.textContent = pending;
  $('#sidebar-foot').innerHTML = `
    <div class="row"><span class="dot ${status.ai_ready ? '' : 'off'}"></span>${status.ai_ready ? 'AI ready · ' + esc(status.model) : 'No AI key found'}</div>
    <div class="row">${status.empty ? 'Nothing set up yet' : status.database === 'sample' ? 'Sample data (made up)' : 'Your data'}</div>
    <div class="row">Today: ${money(status.spent_today_usd)} of $${status.daily_budget_usd.toFixed(2)}</div>
    ${status.needs_setup ? '' : '<div class="row"><a class="linkish small" href="#/setup/1">Edit setup</a></div>'}
    ${status.empty ? '' : '<div class="row"><button class="linkish small" id="start-over" style="color:var(--muted)">Start over</button></div>'}`;
  $('#start-over')?.addEventListener('click', openStartOver);
  document.querySelector('.sidebar .nav').classList.toggle('locked', status.needs_setup);
}

function setActiveNav(route) {
  document.querySelectorAll('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.route === route));
}

const routes = {
  network: renderNetwork,
  contact: renderContact,
  usage: renderUsage,
  dashboard: renderDashboard,
  setup: renderSetup,
  targets: renderTargets,
  connections: renderConnections,
  welcome: renderWelcome,
  internships: renderInternships,
  employer: renderEmployer,
  decisions: renderDecisions,
};

async function router() {
  const [route, id] = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/');
  let view = routes[route] ? route : 'dashboard';
  // A blank Career HQ opens on the welcome page; a half-finished one goes back to setup.
  if (status?.empty && view !== 'setup') view = 'welcome';
  else if (status?.needs_setup && !status.empty) view = 'setup';
  setActiveNav({ contact: 'network', employer: 'internships' }[view] || view);
  const main = $('#main');
  try {
    await routes[view](main, id);
  } catch (err) {
    main.innerHTML = `<div class="page"><div class="error-box">${esc(err.message)}</div></div>`;
  }
  refreshStatus().catch(() => {});
}

/* ---------- "AI is working" panel ---------- */

// A centered panel listing what the agent is doing, advanced on a timer while the call runs. The
// steps describe the work honestly but aren't tied to real progress, so there's no percentage.
function startThinking(title, steps, expect, stepMs = 3500) {
  const bg = document.createElement('div');
  bg.className = 'thinking-bg';
  bg.innerHTML = `<div class="thinking" role="status" aria-live="polite">
    <div class="thinking-mark">${icon('spark', 26)}</div>
    <h3>${esc(title)}</h3>
    <ol>${steps.map((x) => `<li>${esc(x)}</li>`).join('')}</ol>
    <p class="small muted" style="margin:10px 0 0">${esc(expect)}</p></div>`;
  document.body.appendChild(bg);
  const lis = [...bg.querySelectorAll('li')];
  let i = 0;
  lis[0].classList.add('on');
  const timer = setInterval(() => {
    if (i < lis.length - 1) { lis[i].className = 'done'; i += 1; lis[i].className = 'on'; }
  }, stepMs);
  return () => { clearInterval(timer); bg.remove(); };
}

/* ---------- modal ---------- */

function openModal(title, html, onMount) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = html;
  $('#modal-bg').hidden = false;
  onMount?.($('#modal-body'));
  $('#modal-body').querySelector('input, textarea, select')?.focus();
}
function closeModal() { $('#modal-bg').hidden = true; $('#modal-body').innerHTML = ''; }

/* ---------- Networking: contacts + open questions ---------- */

async function renderNetwork(main) {
  const [contacts, questions] = await Promise.all([api('/contacts'), api('/questions')]);
  const open = questions.filter((q) => q.status === 'open');
  const answered = questions.length - open.length;
  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div><h1>Networking</h1><p class="sub">Log a conversation, let the AI suggest updates, approve what's right.</p></div>
        <button class="btn primary" id="new-contact">+ New contact</button>
      </div>
      <div class="grid-2">
        <div>
          <div class="toolbar"><input type="search" id="contact-search" placeholder="Search people or employers" aria-label="Search contacts"></div>
          <div class="card" id="contact-list"></div>
        </div>
        <div class="card card-pad">
          <div class="eyebrow">What you're still trying to learn</div>
          <div class="progress" title="${answered} of ${questions.length} answered"><span style="width:${questions.length ? (100 * answered) / questions.length : 0}%"></span></div>
          <p class="small muted" style="margin:-6px 0 14px">${answered} of ${questions.length} questions answered through conversations</p>
          ${open.map((q) => `<div class="q-item"><p>${esc(q.text)}</p><span class="small muted">${esc(q.path_name || 'All paths')}${q.employer ? ' · ' + esc(q.employer) : ''}</span></div>`).join('') || '<p class="empty">No open questions.</p>'}
          ${answered ? `<details class="blocked" style="margin-top:12px"><summary>${answered} answered</summary>${questions.filter((q) => q.status === 'answered').map((q) => `<div class="q-item answered"><p>${esc(q.text)}</p><span class="small">${esc(q.answer)}</span></div>`).join('')}</details>` : ''}
        </div>
      </div>
    </div>`;

  const list = $('#contact-list');
  const draw = (filter) => {
    const f = filter.trim().toLowerCase();
    const shown = contacts.filter((c) => !f || `${c.name} ${c.employer || ''} ${c.role}`.toLowerCase().includes(f));
    list.innerHTML = shown.map((c) => `
      <a class="contact-row" href="#/contact/${c.id}">
        <span class="avatar">${esc(initials(c.name))}</span>
        <span class="who"><b>${esc(c.name)}</b><span>${esc(c.role)}${c.employer ? ' · ' + esc(c.employer) : ''}</span>
          <span class="when">${c.last_contacted ? 'Last talked ' + fmtDate(c.last_contacted) : 'Not contacted yet'}</span></span>
        <span class="flags">${c.pending ? `<span class="chip garnet">${c.pending} to review</span>` : ''}${c.track ? trackChip(c.track) : ''}</span>
      </a>`).join('') || (contacts.length ? '<div class="card-pad empty">No contacts match.</div>'
      : '<div class="card-pad empty">No contacts yet. Add the people you talk to here. Not sure who to talk to? <a class="linkish" href="#/connections">Connections</a> suggests who to look for.</div>');
  };
  draw('');
  $('#contact-search').addEventListener('input', (e) => draw(e.target.value));
  $('#new-contact').onclick = openNewContact;
}

async function openNewContact() {
  lookups = await api('/lookups');
  openModal('New contact', `
    <form class="stack" id="contact-form">
      <label class="field">Name<input type="text" name="name" required maxlength="120"></label>
      <label class="field">Employer<select name="employer_id"><option value="">None</option>${lookups.employers.map((e) => `<option value="${e.id}">${esc(e.name)}</option>`).join('')}</select></label>
      <label class="field">Role<input type="text" name="role" maxlength="160"></label>
      <label class="field">How you met<input type="text" name="how_met" maxlength="200"></label>
      <div class="actions"><span class="spacer"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">Save contact</button></div>
    </form>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#contact-form').onsubmit = async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      data.employer_id = data.employer_id ? Number(data.employer_id) : null;
      try {
        const { id } = await api('/contacts', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        location.hash = `#/contact/${id}`;
      } catch (err) { toast(err.message); }
    };
  });
}

/* ---------- Contact profile: the Networking Intelligence workflow ---------- */

const KIND = {
  answer_question: { group: 'Answers to your open questions', label: 'Answers a question' },
  learning: { group: 'What you learned', label: 'Career learning' },
  new_question: { group: 'New questions to resolve', label: 'New question' },
  task: { group: 'Follow-ups', label: 'Follow-up task' },
  contact_note: { group: 'Notes about this person', label: 'Contact note' },
  employer_note: { group: 'Employer notes', label: 'Employer note' },
};
const KIND_ORDER = Object.keys(KIND);
const STATUS_CHIP = {
  not_analyzed: '<span class="chip">Not analyzed</span>',
  analyzed: '<span class="chip ok">Analyzed</span>',
  blocked: '<span class="chip amber">Blocked by provider filter</span>',
  failed: '<span class="chip garnet">Analysis failed</span>',
};

async function renderContact(main, id) {
  const [c, lk] = await Promise.all([api(`/contacts/${id}`), api('/lookups')]);
  lookups = lk;
  const open = c.tasks.filter((t) => t.status === 'open');
  main.innerHTML = `
    <div class="page">
      <div class="crumbs"><a href="#/network">Networking</a> / ${esc(c.name)}</div>
      <div class="profile-head">
        <span class="avatar lg">${esc(initials(c.name))}</span>
        <div>
          <h1>${esc(c.name)}</h1>
          <div class="meta">${esc(c.role)}${c.employer ? ' · ' + esc(c.employer) : ''}${c.how_met ? ' · Met via ' + esc(c.how_met) : ''}</div>
        </div>
        ${c.track ? `<span style="margin-left:auto">${trackChip(c.track, 'name')}</span>` : ''}
      </div>
      <div class="grid-2">
        <div class="stack">
          <div class="card card-pad composer">
            <div class="actions" style="margin-bottom:10px"><h2>Log a conversation</h2><span class="spacer"></span>
              ${c.has_sample_notes ? '<button class="linkish small" id="sample">Load sample notes</button>' : ''}</div>
            <form id="conv-form" class="stack">
              <textarea id="conv-notes" maxlength="${status?.max_note_chars || 8000}" placeholder="Paste or type your notes from the call or coffee chat. Rough is fine." aria-label="Conversation notes"></textarea>
              <div class="actions">
                <label class="field" style="flex-direction:row;align-items:center;gap:8px">Date <input type="date" id="conv-date" value="${status?.today || ''}" style="width:auto"></label>
                <span class="counter" id="conv-count">0 characters</span>
                <span class="spacer"></span>
                <button type="button" class="btn" id="save-only">Save notes</button>
                <button class="btn primary" id="save-analyze">Save &amp; analyze</button>
              </div>
            </form>
          </div>
          <div class="card">
            <div class="card-head"><h2>Conversations</h2><span class="small muted">${c.conversations.length}</span></div>
            <div id="conv-list">${c.conversations.map((cv) => conversationHtml(cv, c)).join('') || '<div class="card-pad empty">No conversations logged yet.</div>'}</div>
          </div>
        </div>
        <div class="stack">
          <div class="card card-pad">
            <div class="eyebrow" style="margin-bottom:10px">Follow-ups</div>
            <ul class="side-list">${c.tasks.map((t) => `<li><label class="task ${t.status}"><input type="checkbox" data-task="${t.id}" ${t.status === 'done' ? 'checked' : ''}><span>${esc(t.description)}${t.due ? ` <span class="muted small">· due ${fmtDate(t.due)}</span>` : ''}</span></label></li>`).join('') || '<li class="empty">No follow-ups yet.</li>'}</ul>
            ${open.length ? '' : ''}
          </div>
          <div class="card card-pad">
            <div class="eyebrow" style="margin-bottom:10px">About ${esc(firstName(c.name))}</div>
            <ul class="side-list">${c.notes.map((n) => `<li>${esc(n.text)}<span class="src">${n.occurred_on ? 'From conversation on ' + fmtDate(n.occurred_on) : 'Added manually'}</span></li>`).join('') || '<li class="empty">No notes yet.</li>'}</ul>
          </div>
          <div class="card card-pad">
            <div class="eyebrow" style="margin-bottom:10px">What ${esc(firstName(c.name))} taught you</div>
            <ul class="side-list">
              ${c.questions_answered.map((q) => `<li><b>${esc(q.text)}</b><br>${esc(q.answer)}<span class="src">Answered ${fmtDate(q.answered_at)}</span></li>`).join('')}
              ${c.learnings.map((l) => `<li>${esc(l.text)}<span class="src">${esc(pathName(l.path) || 'General')}</span></li>`).join('')}
              ${c.questions_answered.length + c.learnings.length ? '' : '<li class="empty">Approved learnings and answers appear here.</li>'}
            </ul>
          </div>
        </div>
      </div>
    </div>`;
  wireContact(c);
}

function conversationHtml(cv, contact) {
  const pending = cv.proposals.filter((p) => p.status === 'pending').length;
  const run = cv.last_run;
  let body = '';
  if (cv.injection_flag.length) {
    body += `<div class="warning"><b>Possible prompt injection.</b> These notes contain text that tries to give the AI orders. It was treated as plain text, and any suggestion based on it is blocked.
      ${cv.injection_flag.map((s) => `<div style="margin-top:6px"><q>${esc(s.length > 220 ? s.slice(0, 220) + '…' : s)}</q></div>`).join('')}</div>`;
  }
  if (run && run.outcome !== 'ok') {
    body += `<div class="error-box">${esc(run.error || 'The analysis did not complete.')} Nothing was changed. Your notes are saved.</div>`;
  }
  if (cv.summary) body += `<div class="summary">${esc(cv.summary)}</div>`;
  if (cv.proposals.length) {
    body += `<div class="review">${KIND_ORDER.filter((k) => cv.proposals.some((p) => p.kind === k)).map((k) => `
      <div class="group-title">${KIND[k].group}</div>
      ${cv.proposals.filter((p) => p.kind === k).map((p) => proposalHtml(p, contact)).join('')}`).join('')}</div>`;
  } else if (cv.analysis_status === 'analyzed') {
    body += '<p class="muted small">The AI found nothing worth saving in these notes.</p>';
  }
  if (run && run.outcome === 'ok' && run.blocked_reasons.length) {
    body += `<details class="blocked"><summary>${run.blocked_reasons.length} suggestion${run.blocked_reasons.length > 1 ? 's' : ''} blocked by safety checks</summary><ul>
      ${run.blocked_reasons.map((b) => `<li><b>${esc(KIND[b.kind]?.label || b.kind)}:</b> “${esc(b.text)}” — ${esc(b.reason)}</li>`).join('')}</ul></details>`;
  }
  if (run) {
    body += `<div class="run-meta"><span>${esc(run.model)}</span><span>${num(run.input_tokens)} input (${num(run.cached_tokens)} cached)</span><span>${num(run.output_tokens)} output</span><span>${money(run.cost_usd)}</span><span>${(run.latency_ms / 1000).toFixed(1)} s</span>${run.tools_used.length ? `<span>Looked up: ${esc([...new Set(run.tools_used)].join(', ').replaceAll('_', ' '))}</span>` : ''}</div>`;
  }
  const canAnalyze = cv.analysis_status !== 'analyzed' || (pending === 0 && cv.proposals.length === 0);
  return `
    <div class="conv" data-conv="${cv.id}">
      <div class="conv-head"><span class="date">${fmtDate(cv.occurred_on)}</span>${STATUS_CHIP[cv.analysis_status] || ''}
        ${pending ? `<span class="chip garnet">${pending} to review</span>` : ''}
        <span class="spacer" style="flex:1"></span>
        ${canAnalyze && cv.analysis_status !== 'analyzed' ? `<button class="btn sm" data-analyze="${cv.id}">Analyze with AI</button>` : ''}</div>
      <p class="notes-text clamped" data-notes>${esc(cv.notes)}</p>
      <button class="linkish small" data-expand>Show full notes</button>
      ${body}
    </div>`;
}

function proposalHtml(p, contact) {
  let target = '';
  if (p.kind === 'answer_question' && p.question_text) target = `Question: <b>${esc(p.question_text)}</b>`;
  else if (p.kind === 'contact_note') target = `Saves to <b>${esc(contact.name)}</b>`;
  else if (p.kind === 'task') target = `Follow-up${p.due ? ` · due <b>${fmtDate(p.due)}</b>` : ''}`;
  if (p.employer_name && p.kind !== 'contact_note') target += `${target ? ' · ' : ''}Employer: <b>${esc(p.employer_name)}</b>`;
  if (p.path && p.kind !== 'answer_question') target += `${target ? ' · ' : ''}${esc(pathName(p.path))}`;
  if (p.status !== 'pending') {
    return `<div class="proposal decided k-${p.kind}"><p class="p-text">${esc(p.text)}</p>
      <span class="chip ${p.status === 'approved' ? 'ok' : ''}">${p.status === 'approved' ? 'Approved and saved' : 'Rejected, nothing saved'}</span></div>`;
  }
  return `
    <div class="proposal k-${p.kind}" data-proposal="${p.id}">
      ${target ? `<div class="p-target">${target}</div>` : ''}
      <p class="p-text" data-text>${esc(p.text)}</p>
      <div class="evidence">“${esc(p.evidence)}”</div>
      ${p.rationale ? `<p class="why">${esc(p.rationale)}</p>` : ''}
      <div class="actions">
        <button class="btn primary sm" data-approve="${p.id}">Approve</button>
        <button class="btn sm" data-reject="${p.id}">Reject</button>
        <button class="btn ghost sm" data-edit="${p.id}">Edit</button>
      </div>
    </div>`;
}

function wireContact(c) {
  const notes = $('#conv-notes');
  const count = () => { $('#conv-count').textContent = `${notes.value.length.toLocaleString()} characters`; };
  notes.addEventListener('input', count);
  $('#sample')?.addEventListener('click', async () => {
    const { notes: text } = await api(`/contacts/${c.id}/sample-notes`);
    notes.value = text;
    count();
  });

  const save = async (analyze) => {
    const text = notes.value.trim();
    if (text.length < 30) { toast('Add a bit more detail first (at least 30 characters).'); return; }
    try {
      const { id } = await api(`/contacts/${c.id}/conversations`, { method: 'POST', body: JSON.stringify({ notes: text, occurred_on: $('#conv-date').value }) });
      if (analyze) await runAnalysis(id, c.id);
      else { toast('Notes saved.'); await renderContact($('#main'), c.id); }
    } catch (err) { toast(err.message); }
  };
  $('#save-only').onclick = () => save(false);
  $('#conv-form').onsubmit = (e) => { e.preventDefault(); save(true); };

  $('#conv-list').addEventListener('click', async (e) => {
    const t = e.target;
    if (t.matches('[data-expand]')) {
      const p = t.previousElementSibling;
      p.classList.toggle('clamped');
      t.textContent = p.classList.contains('clamped') ? 'Show full notes' : 'Show less';
    } else if (t.dataset.analyze) {
      await runAnalysis(Number(t.dataset.analyze), c.id);
    } else if (t.dataset.approve) {
      const card = t.closest('[data-proposal]');
      const edited = card.querySelector('textarea')?.value;
      await decide(t.dataset.approve, 'approve', edited, c.id);
    } else if (t.dataset.reject) {
      await decide(t.dataset.reject, 'reject', null, c.id);
    } else if (t.dataset.edit) {
      const card = t.closest('[data-proposal]');
      const textEl = card.querySelector('[data-text]');
      if (!card.querySelector('textarea')) {
        textEl.outerHTML = `<textarea aria-label="Edit suggestion">${esc(textEl.textContent)}</textarea>`;
        t.textContent = 'Editing';
        t.disabled = true;
        card.querySelector('textarea').focus();
      }
    }
  });

  document.querySelectorAll('[data-task]').forEach((box) => {
    box.addEventListener('change', async () => {
      try { await api(`/tasks/${box.dataset.task}/toggle`, { method: 'POST' }); await renderContact($('#main'), c.id); }
      catch (err) { toast(err.message); }
    });
  });

  // The "Show full notes" link is only useful when the notes are actually clamped.
  document.querySelectorAll('[data-notes]').forEach((p) => {
    if (p.scrollHeight <= p.clientHeight + 2) p.nextElementSibling.hidden = true;
  });
}

async function runAnalysis(conversationId, contactId) {
  const btns = document.querySelectorAll('#save-analyze, [data-analyze]');
  btns.forEach((b) => { b.disabled = true; });
  const main = $('#save-analyze');
  const label = main.innerHTML;
  main.innerHTML = '<span class="spinner"></span> Analyzing…';
  const stop = startThinking('Reading your notes', ['Looking up this person and your open questions', 'Matching the notes to employers in your Career HQ',
    'Pulling out answers, learnings and follow-ups', 'Checking every suggestion against your notes'], 'Usually 10 to 20 seconds. Nothing is saved until you approve it.', 3000);
  try {
    const r = await api(`/conversations/${conversationId}/analyze`, { method: 'POST' });
    if (r.outcome === 'ok') toast(`${r.accepted} suggestion${r.accepted === 1 ? '' : 's'} ready to review${r.blocked.length ? ` · ${r.blocked.length} blocked` : ''}.`);
    else toast(r.message || 'Analysis did not complete.');
  } catch (err) {
    toast(err.message);
  } finally {
    stop();
    main.innerHTML = label;
    await renderContact($('#main'), contactId);
    refreshStatus().catch(() => {});
    document.querySelector(`[data-conv="${conversationId}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

async function decide(id, choice, editedText, contactId) {
  try {
    const body = choice === 'approve' && editedText != null ? JSON.stringify({ text: editedText }) : '{}';
    await api(`/proposals/${id}/${choice}`, { method: 'POST', body });
    toast(choice === 'approve' ? 'Approved and saved.' : 'Rejected. Nothing was saved.');
    const y = window.scrollY;
    await renderContact($('#main'), contactId);
    window.scrollTo(0, y);
    refreshStatus().catch(() => {});
  } catch (err) { toast(err.message); }
}

/* ---------- Dashboard ---------- */

const STAGE_SHORT = { Researching: 'Research', Exploring: 'Explore', Networking: 'Network', Applied: 'Applied', Interviewing: 'Interview', Offer: 'Offer' };

function primaryLine() {
  const p = trackList.find((t) => t.role === 'Primary focus');
  const others = trackList.filter((t) => t !== p).map((t) => t.name);
  if (!p) return 'Finish setup to set your focus.';
  return `Explore ${p.name} first${others.length ? `, keeping ${others.join(' and ')} as ${others.length > 1 ? 'alternatives' : 'an alternative'}` : ''}.`;
}

function dueLabel(iso, today) {
  if (!iso) return '';
  const days = Math.round((new Date(iso + 'T12:00:00') - new Date(today + 'T12:00:00')) / 86400000);
  if (days < 0) return `Overdue · ${fmtDate(iso)}`;
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

async function renderDashboard(main) {
  const d = await api('/dashboard');
  const today = d.today;
  const longDate = new Date(today + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  const l = d.learning;
  const nc = d.next_conversation;
  const gs = d.getting_started;
  const gsLeft = gs.filter((g) => !g.done).length;

  const actionRow = (a) => `
    <li class="due-row ${a.bucket}">
      <span class="due">${esc(dueLabel(a.due, today))}</span>
      <span class="what">${a.type === 'task'
        ? `<label class="task"><input type="checkbox" data-task="${a.id}"><span>${esc(a.text)}</span></label>`
        : `<label class="task"><input type="checkbox" data-opp-done="${a.id}"><span>${esc(a.text)}</span></label>`}
        ${a.context ? `<span class="ctx">${esc(a.context)}</span>` : ''}</span>
      ${a.track ? trackChip(a.track) : ''}
    </li>`;

  const followRow = (f) => `
    <li class="due-row ${f.bucket}">
      <span class="due">${esc(f.due ? dueLabel(f.due, today) : 'No date')}</span>
      <span class="what"><label class="task"><input type="checkbox" data-task="${f.id}"><span>${esc(f.description)}</span></label>
        <span class="ctx"><a href="#/contact/${f.contact_id}">${esc(f.name)}</a>${f.employer ? ' · ' + esc(f.employer) : ''}</span></span>
    </li>`;

  const track = (p) => `
    <div class="track">
      <div class="track-head">
        <div><h3>${esc(p.name)}</h3><span class="small muted">${p.total} ${p.total === 1 ? 'opportunity' : 'opportunities'}${p.furthest_stage ? ' · furthest: ' + esc(p.furthest_stage) : ''}</span></div>
      </div>
      <div class="stages" role="img" aria-label="${esc(p.name)} stages: ${d.stages.map((s) => `${s} ${p.counts[s]}`).join(', ')}">
        ${d.stages.map((s) => `<div class="stage ${p.counts[s] ? 'on' : ''}" title="${esc(s)}"><b>${p.counts[s] || ''}</b><span>${esc(STAGE_SHORT[s] || s)}</span></div>`).join('')}
      </div>
      <ul class="opp-list">${p.opportunities.slice(0, 4).map((o) => `
        <li><div><b>${esc(o.title)}</b>${o.employer ? `<a class="ctx" href="#/employer/${o.employer_id}">${esc(o.employer)}</a>` : ''}</div>
          <span class="chip">${esc(o.status)}</span>
          ${o.next_action ? `<div class="next">Next: ${esc(o.next_action)}${o.due ? ` · <span class="${o.due < today ? 'overdue-text' : ''}">${esc(dueLabel(o.due, today))}</span>` : ''}</div>` : ''}
        </li>`).join('') || '<li class="empty">No opportunities yet.</li>'}</ul>
    </div>`;

  main.innerHTML = `
    <div class="page">
      <div class="page-head"><div><h1>Dashboard</h1><p class="sub">${esc(longDate)}</p></div></div>

      <div class="card priority">
        <div class="priority-main">
          <div class="eyebrow">Current priority</div>
          <p class="priority-text">${esc(d.priorities.current_priority || primaryLine())}</p>
          ${d.priorities.planning_note ? `<p class="small muted">${esc(d.priorities.planning_note)}</p>` : ''}
        </div>
        <div class="priority-side">
          <div class="eyebrow">Uncertainty resolved</div>
          ${l.total ? `<p class="big-fraction"><b>${l.answered}</b> of ${l.total} questions answered</p>
          <div class="progress"><span style="width:${(100 * l.answered) / l.total}%"></span></div>` : '<p class="small muted" style="margin:6px 0 8px">No open questions yet. Directions you pick in setup, and conversations you log, add them.</p>'}
          <a class="linkish small" href="#/network">See open questions →</a>
        </div>
      </div>

      ${nc ? `<div class="card next-convo">
        <div class="nc-icon">${icon('chat')}</div>
        <div class="nc-body">
          <div class="eyebrow">Your next best conversation</div>
          <p class="nc-q">${esc(nc.question)}</p>
          <p class="small" style="margin:0">${nc.type === 'contact' ? `<span class="muted">Ask:</span> <b>${esc(nc.who)}</b>, someone you know who hasn't been asked yet.`
            : nc.type === 'lead' ? `<span class="muted">Who could answer it:</span> <b>${esc(nc.who)}</b>`
              : '<span class="muted">No one lined up for this yet.</span>'}</p>
        </div>
        <a class="btn ${nc.type === 'none' ? '' : 'primary'}" href="${nc.href}" style="text-decoration:none">${esc(nc.cta)}</a>
      </div>` : ''}

      ${gsLeft ? `<div class="card card-pad getting-started">
        <div class="actions" style="margin-bottom:8px"><h2>Getting started</h2><span class="spacer"></span>
          <span class="small muted">${gs.length - gsLeft} of ${gs.length} done</span></div>
        <div class="progress" style="margin:0 0 10px"><span style="width:${(100 * (gs.length - gsLeft)) / gs.length}%"></span></div>
        <ol class="gs-list">${gs.map((g) => `<li class="${g.done ? 'done' : ''}"><span class="gs-check">${g.done ? '✓' : ''}</span>
          ${g.done ? `<span>${esc(g.label)}</span>` : `<a href="${g.href}">${esc(g.label)} →</a>`}</li>`).join('')}</ol>
      </div>` : ''}

      <div class="dash-grid">
        <div class="card">
          <div class="card-head"><h2>Coming up</h2><span class="small muted">Next ${14} days</span></div>
          <ul class="due-list">${d.upcoming.map(actionRow).join('') || '<li class="empty">Nothing due in the next two weeks.</li>'}</ul>
          ${d.later_count ? `<div class="card-foot small muted">${d.later_count} more later · <a href="#/internships">Internship HQ →</a></div>` : ''}
        </div>
        <div class="card">
          <div class="card-head"><h2>Networking follow-ups</h2><a class="linkish small" href="#/network">Networking →</a></div>
          ${d.reviews.length ? `<ul class="review-list">${d.reviews.map((r) => `
            <li><a href="#/contact/${r.contact_id}"><span class="chip garnet">${r.pending} to review</span>
              <span><b>${esc(r.name)}</b> <span class="muted">· AI suggestions from ${fmtDate(r.occurred_on)}</span></span></a></li>`).join('')}</ul>` : ''}
          <ul class="due-list">${d.followups.map(followRow).join('') || (d.reviews.length ? '' : '<li class="empty">No follow-ups. Log a conversation to create some.</li>')}</ul>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>Recruiting pipeline</h2><a class="linkish small" href="#/internships">Internship HQ →</a></div>
        <div class="tracks cols-${d.pipeline.length}">${d.pipeline.map(track).join('')}</div>
      </div>
    </div>`;

  main.querySelectorAll('[data-task]').forEach((box) => {
    box.addEventListener('change', async () => {
      try {
        await api(`/tasks/${box.dataset.task}/toggle`, { method: 'POST' });
        toast('Marked done.');
        await renderDashboard(main);
      } catch (err) { toast(err.message); }
    });
  });
  main.querySelectorAll('[data-opp-done]').forEach((box) => {
    box.addEventListener('change', () => {
      box.checked = false;   // only checked for real once the form is submitted
      const a = d.upcoming.find((x) => x.type === 'opportunity' && x.id === Number(box.dataset.oppDone));
      openCompleteForm({ id: a.id, next_action: a.text }, () => renderDashboard(main));
    });
  });
}

/* ---------- Internship HQ ---------- */

let ihqCycle = 'Upcoming internship';

function oppCard(o, today, { showEmployer = true } = {}) {
  const due = o.due ? ` · <span class="${o.due < today ? 'overdue-text' : ''}">${esc(dueLabel(o.due, today))}</span>` : '';
  const notes = (o.notes || '').trim();
  return `
    <div class="opp-card ${o.status === 'Closed' ? 'closed' : ''}" data-opp="${o.id}">
      <div class="opp-top">
        <div class="opp-title"><b>${esc(o.title)}</b>
          ${showEmployer && o.employer ? `<a class="ctx" href="#/employer/${o.employer_id}">${esc(o.employer)}</a>` : ''}
          ${o.cycle !== 'Upcoming internship' ? `<span class="chip amber" style="margin-top:4px">${esc(o.cycle)}</span>` : ''}</div>
        <select class="status-select" data-status="${o.id}" aria-label="Status of ${esc(o.title)}">
          ${OPP_STATUSES.map((st) => `<option ${st === o.status ? 'selected' : ''}>${esc(st)}</option>`).join('')}</select>
      </div>
      ${o.next_action
        ? `<div class="opp-next"><span><span class="muted">Next:</span> ${esc(o.next_action)}${due}</span><button class="btn sm" data-complete="${o.id}">Done</button></div>`
        : (o.status === 'Closed' ? '' : `<div class="opp-next"><button class="linkish small" data-edit-opp="${o.id}">+ Add a next step</button></div>`)}
      ${notes ? `<p class="opp-notes">${esc(notes)}</p>` : ''}
      <div class="opp-foot"><button class="linkish small" data-edit-opp="${o.id}">Edit</button></div>
    </div>`;
}

let OPP_STATUSES = [];
let ihqMeta = null;   // statuses, stages, cycles, employers: loaded with the Internship HQ data

async function loadIhqMeta() {
  const d = await api('/internships');
  OPP_STATUSES = d.opp_statuses;
  ihqMeta = d;
  return d;
}

async function renderInternships(main) {
  const d = await loadIhqMeta();
  const counts = Object.fromEntries(d.cycles.map((c) => [c, 0]));
  d.tracks.forEach((t) => t.opportunities.forEach((o) => { counts[o.cycle] = (counts[o.cycle] || 0) + 1; }));
  const cycles = [...d.cycles, 'All'];
  const inCycle = (o) => ihqCycle === 'All' || o.cycle === ihqCycle;
  const primary = d.tracks.find((t) => t.role === 'Primary focus');

  const trackCol = (t) => {
    const opps = t.opportunities.filter(inCycle);
    const active = opps.filter((o) => o.status !== 'Closed');
    const closed = opps.filter((o) => o.status === 'Closed');
    return `
      <div class="card track-col">
        <div class="track-col-head">
          <div><h2>${esc(t.name)}</h2><p class="small muted" style="margin:2px 0 0">${esc(t.blurb)}</p></div>
          <span class="chip t${t.position}">${esc(t.role)}</span>
        </div>
        <div class="col-section">
          <div class="actions"><div class="eyebrow">Opportunities · ${active.length}</div><span class="spacer"></span>
            <button class="linkish small" data-new-opp="${t.track}">+ Add</button></div>
          ${active.map((o) => oppCard(o, d.today)).join('') || `<p class="empty small">No ${ihqCycle === 'All' ? '' : esc(ihqCycle) + ' '}opportunities in this track.</p>`}
          ${closed.length ? `<details class="blocked"><summary>Closed · ${closed.length}</summary>${closed.map((o) => oppCard(o, d.today)).join('')}</details>` : ''}
        </div>
        <div class="col-section">
          <div class="actions"><div class="eyebrow">Employers · ${t.employers.length}</div><span class="spacer"></span>
            <button class="linkish small" data-new-employer="${t.track}">+ Add</button></div>
          <ul class="emp-list">${t.employers.map((e) => `
            <li><a href="#/employer/${e.id}">
              <span class="emp-name"><b>${esc(e.name)}</b><span class="ctx">${esc([e.location, e.path_name].filter(Boolean).join(' · '))}</span></span>
              <span class="emp-meta"><span class="chip">${esc(e.stage)}</span>
                <span class="small muted">${e.contacts} ${e.contacts === 1 ? 'person' : 'people'}${e.notes ? ` · ${e.notes} note${e.notes > 1 ? 's' : ''}` : ''}</span></span>
            </a></li>`).join('') || '<li class="empty small">No employers yet.</li>'}</ul>
        </div>
      </div>`;
  };

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div><h1>Internship HQ</h1><p class="sub">${d.tracks.length === 1 ? 'Your recruiting track' : `${d.tracks.length} recruiting tracks, side by side`}.${primary ? ` Primary focus: ${esc(primary.name)}.` : ''}</p></div>
        <div class="actions"><a class="btn ghost" href="#/setup/3" style="text-decoration:none">Edit tracks</a><button class="btn" data-new-employer="">+ Employer</button><button class="btn primary" data-new-opp="">+ Opportunity</button></div>
      </div>
      <div class="cycle-bar">
        <div class="segmented" role="tablist" aria-label="Recruiting cycle">
          ${cycles.map((c) => `<button role="tab" aria-selected="${c === ihqCycle}" class="${c === ihqCycle ? 'on' : ''}" data-cycle="${esc(c)}">${esc(c)}${c !== 'All' ? ` <span class="count">${counts[c] || 0}</span>` : ''}</button>`).join('')}
        </div>
        ${d.planning_note ? `<span class="small muted">${esc(d.planning_note)}</span>` : ''}
      </div>
      <div class="track-grid cols-${d.tracks.length}">${d.tracks.map(trackCol).join('')}</div>
    </div>`;

  main.querySelectorAll('[data-cycle]').forEach((b) => { b.onclick = () => { ihqCycle = b.dataset.cycle; renderInternships(main); }; });
  wireOpportunityControls(main, () => renderInternships(main));
  main.querySelectorAll('[data-new-employer]').forEach((b) => { b.onclick = () => openEmployerForm(null, b.dataset.newEmployer); });
}

function allOpps() { return ihqMeta ? ihqMeta.tracks.flatMap((t) => t.opportunities) : []; }
function allEmployers() { return ihqMeta ? ihqMeta.tracks.flatMap((t) => t.employers.map((e) => ({ ...e, track: t.track }))) : []; }

function wireOpportunityControls(root, rerender) {
  root.querySelectorAll('[data-status]').forEach((sel) => {
    sel.addEventListener('change', async () => {
      try {
        await api(`/opportunities/${sel.dataset.status}`, { method: 'PATCH', body: JSON.stringify({ status: sel.value }) });
        toast(`Status set to ${sel.value}.`);
        rerender();
      } catch (err) { toast(err.message); }
    });
  });
  root.querySelectorAll('[data-complete]').forEach((b) => {
    b.onclick = () => openCompleteForm(allOpps().find((o) => o.id === Number(b.dataset.complete)), rerender);
  });
  root.querySelectorAll('[data-edit-opp]').forEach((b) => {
    b.onclick = () => openOpportunityForm(allOpps().find((o) => o.id === Number(b.dataset.editOpp)), {}, rerender);
  });
  root.querySelectorAll('[data-new-opp]').forEach((b) => {
    b.onclick = () => openOpportunityForm(null, { track: b.dataset.newOpp || null, employer_id: b.dataset.employer ? Number(b.dataset.employer) : null }, rerender);
  });
}

function optionList(values, selected) {
  return values.map((v) => `<option ${v === selected ? 'selected' : ''}>${esc(v)}</option>`).join('');
}

async function openOpportunityForm(opp, preset, rerender) {
  if (!ihqMeta) await loadIhqMeta();
  const o = opp || { title: '', employer_id: preset.employer_id ?? null, status: 'Researching', cycle: ihqCycle === 'All' ? 'Upcoming internship' : ihqCycle, next_action: '', due: '', notes: '' };
  const emps = allEmployers().filter((e) => !preset.track || e.track === preset.track || opp);
  openModal(opp ? 'Edit opportunity' : 'New opportunity', `
    <form class="stack" id="opp-form">
      <label class="field">Title<input type="text" name="title" required maxlength="160" value="${esc(o.title)}"></label>
      <label class="field">Employer<select name="employer_id" required>
        <option value="">Choose an employer</option>
        ${ihqMeta.tracks.map((t) => `<optgroup label="${esc(t.name)}">${t.employers.filter((e) => emps.some((x) => x.id === e.id)).map((e) => `<option value="${e.id}" ${e.id === o.employer_id ? 'selected' : ''}>${esc(e.name)}</option>`).join('')}</optgroup>`).join('')}
      </select></label>
      <div class="form-row">
        <label class="field" style="flex:1">Status<select name="status">${optionList(ihqMeta.opp_statuses, o.status)}</select></label>
        <label class="field" style="flex:1">Cycle<select name="cycle">${optionList(ihqMeta.cycles, o.cycle)}</select></label>
      </div>
      <div class="form-row">
        <label class="field" style="flex:2">Next step<input type="text" name="next_action" maxlength="200" value="${esc(o.next_action)}"></label>
        <label class="field" style="flex:1">Due<input type="date" name="due" value="${esc(o.due)}"></label>
      </div>
      <label class="field">Notes<textarea name="notes" rows="4" maxlength="4000">${esc(o.notes)}</textarea></label>
      <div class="actions"><span class="spacer"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">${opp ? 'Save' : 'Add opportunity'}</button></div>
    </form>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#opp-form').onsubmit = async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      data.employer_id = data.employer_id ? Number(data.employer_id) : null;
      try {
        if (opp) await api(`/opportunities/${opp.id}`, { method: 'PATCH', body: JSON.stringify(data) });
        else await api('/opportunities', { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        toast(opp ? 'Saved.' : 'Opportunity added.');
        rerender();
      } catch (err) { toast(err.message); }
    };
  });
}

function openCompleteForm(o, rerender) {
  openModal('Mark next step done', `
    <form class="stack" id="complete-form">
      <p style="margin:0"><span class="muted">Done:</span> ${esc(o.next_action)}</p>
      <p class="small muted" style="margin:0">It's kept as a dated line in this opportunity's notes.</p>
      <div class="form-row">
        <label class="field" style="flex:2">What's the next step? (optional)<input type="text" name="next_action" maxlength="200"></label>
        <label class="field" style="flex:1">Due<input type="date" name="due"></label>
      </div>
      <div class="actions"><span class="spacer"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">Mark done</button></div>
    </form>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#complete-form').onsubmit = async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      try {
        await api(`/opportunities/${o.id}/complete`, { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        toast('Marked done.');
        rerender();
      } catch (err) { toast(err.message); }
    };
  });
}

async function openEmployerForm(emp, track) {
  if (!lookups.paths.length) lookups = await api('/lookups');
  if (!ihqMeta) await loadIhqMeta();
  if (!trackList.length) await refreshTracks();
  const e = emp || { name: '', track: track || trackList[0]?.key, path: '', location: '', stage: 'Researching', summary: '' };
  openModal(emp ? `Edit ${emp.name}` : 'New employer', `
    <form class="stack" id="emp-form">
      ${emp ? '' : '<label class="field">Name<input type="text" name="name" required maxlength="160"></label>'}
      <div class="form-row">
        <label class="field" style="flex:1">Track<select name="track">${trackList.map((t) => `<option value="${esc(t.key)}" ${t.key === e.track ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
        <label class="field" style="flex:1">Stage<select name="stage">${optionList(ihqMeta.employer_stages, e.stage)}</select></label>
      </div>
      <label class="field">Career path<select name="path"><option value="">None</option>${lookups.paths.map((p) => `<option value="${p.key}" ${p.key === e.path ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <label class="field">Location<input type="text" name="location" maxlength="160" value="${esc(e.location)}"></label>
      <label class="field">What they do<textarea name="summary" rows="3" maxlength="1000">${esc(e.summary)}</textarea></label>
      <div class="actions"><span class="spacer"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">${emp ? 'Save' : 'Add employer'}</button></div>
    </form>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#emp-form').onsubmit = async (ev) => {
      ev.preventDefault();
      const data = Object.fromEntries(new FormData(ev.target));
      data.path = data.path || null;
      try {
        if (emp) {
          await api(`/employers/${emp.id}`, { method: 'PATCH', body: JSON.stringify(data) });
          closeModal(); toast('Saved.'); router();
        } else {
          const { id } = await api('/employers', { method: 'POST', body: JSON.stringify(data) });
          closeModal(); toast('Employer added.'); location.hash = `#/employer/${id}`;
        }
      } catch (err) { toast(err.message); }
    };
  });
}

/* ---------- Employer page ---------- */

async function renderEmployer(main, id) {
  const [e] = await Promise.all([api(`/employers/${id}`), loadIhqMeta()]);
  const today = ihqMeta.today;
  const rerender = () => renderEmployer(main, id);
  main.innerHTML = `
    <div class="page">
      <div class="crumbs"><a href="#/internships">Internship HQ</a> / ${esc(e.name)}</div>
      <div class="profile-head">
        <span class="avatar lg square">${esc(initials(e.name))}</span>
        <div><h1>${esc(e.name)}</h1>
          <div class="meta">${esc([e.track_name, e.path_name, e.location].filter(Boolean).join(' · '))}</div></div>
        <div class="actions" style="margin-left:auto">
          <select class="status-select" id="emp-stage" aria-label="Employer stage">${optionList(ihqMeta.employer_stages, e.stage)}</select>
          <button class="btn" id="emp-edit">Edit</button>
        </div>
      </div>
      <div class="grid-2">
        <div class="stack">
          <div class="card card-pad"><div class="eyebrow" style="margin-bottom:6px">What they do</div>
            <p style="margin:0">${esc(e.summary) || '<span class="muted">No summary yet.</span>'}</p></div>
          ${e.profile && e.profile.hq ? `<div class="card card-pad">
            <div class="actions" style="margin-bottom:8px"><div class="eyebrow">Details</div><span class="spacer"></span>
              <span class="chip amber">${e.profile.verified ? 'Verified' : `AI estimate · ${esc(e.profile.confidence || '')} confidence · verify`}</span></div>
            <div class="facts">${[['HQ', e.profile.hq], ['Hours', e.profile.typical_hours], ['Schedule', e.profile.schedule], ['Travel', e.profile.travel],
              ['Work setup', e.profile.remote_policy], ['Field/office', e.profile.field_office], ['Size', e.profile.size], ['Ownership', e.profile.ownership],
              ['Hires interns', e.profile.hires_mba_interns], ['Recruiting', e.profile.recruiting_path], ['Intern pay', e.profile.intern_pay], ['Base pay', e.profile.base_pay],
              ['Upside', e.profile.upside]].map(([k, v]) => `<span><span class="muted">${k}</span> ${esc(v || '')}</span>`).join('')}</div>
            <p class="small" style="margin:10px 0 0"><b>Typical roles:</b> ${esc(e.profile.mba_roles || '')}<br><b>Mission:</b> ${esc(e.profile.mission || '')}</p>
          </div>` : ''}
          <div class="card card-pad">
            <div class="actions" style="margin-bottom:8px"><div class="eyebrow">Opportunities · ${e.opportunities.length}</div><span class="spacer"></span>
              <button class="linkish small" data-new-opp="${e.track}" data-employer="${e.id}">+ Add</button></div>
            ${e.opportunities.map((o) => oppCard(o, today, { showEmployer: false })).join('') || '<p class="empty small">No opportunities here yet.</p>'}
          </div>
          <div class="card card-pad">
            <div class="eyebrow" style="margin-bottom:8px">Notes</div>
            <ul class="side-list">${e.notes.map((n) => `<li>${esc(n.text)}<span class="src">${n.contact
              ? `From your conversation with <a href="#/contact/${n.contact_id}">${esc(n.contact)}</a> · ${fmtDate(n.occurred_on)}`
              : `Added ${fmtDate(n.created_at)}`}</span></li>`).join('') || '<li class="empty small">No notes yet. Notes approved from networking conversations appear here too.</li>'}</ul>
            <form id="emp-note" class="actions" style="margin-top:12px">
              <input type="text" id="emp-note-text" maxlength="1000" placeholder="Add a note about ${esc(e.name)}" aria-label="New note" style="flex:1">
              <button class="btn sm">Add note</button></form>
          </div>
        </div>
        <div class="stack">
          <div class="card card-pad"><div class="eyebrow" style="margin-bottom:8px">People</div>
            <ul class="side-list">${e.contacts.map((c) => `<li><a href="#/contact/${c.id}" style="text-decoration:none"><b>${esc(c.name)}</b></a><span class="src">${esc(c.role)} · ${c.last_contacted ? 'last talked ' + fmtDate(c.last_contacted) : 'not contacted yet'}</span></li>`).join('') || '<li class="empty small">No contacts here yet.</li>'}</ul></div>
          <div class="card card-pad"><div class="eyebrow" style="margin-bottom:8px">What you've learned</div>
            <ul class="side-list">${e.learnings.map((l) => `<li>${esc(l.text)}${l.contact ? `<span class="src">From <a href="#/contact/${l.contact_id}">${esc(l.contact)}</a></span>` : ''}</li>`).join('') || '<li class="empty small">Approved learnings about this employer appear here.</li>'}</ul></div>
          <div class="card card-pad"><div class="eyebrow" style="margin-bottom:8px">Questions about ${esc(e.name)}</div>
            <ul class="side-list">${e.questions.map((q) => `<li class="${q.status === 'answered' ? 'muted' : ''}">${esc(q.text)}${q.status === 'answered' ? `<span class="src">Answered: ${esc(q.answer)}</span>` : '<span class="src">Open</span>'}</li>`).join('') || '<li class="empty small">No open questions tied to this employer.</li>'}</ul></div>
        </div>
      </div>
    </div>`;

  $('#emp-stage').addEventListener('change', async (ev) => {
    try { await api(`/employers/${e.id}`, { method: 'PATCH', body: JSON.stringify({ stage: ev.target.value }) }); toast(`Stage set to ${ev.target.value}.`); }
    catch (err) { toast(err.message); }
  });
  $('#emp-edit').onclick = () => openEmployerForm(e);
  $('#emp-note').onsubmit = async (ev) => {
    ev.preventDefault();
    const text = $('#emp-note-text').value.trim();
    if (!text) return;
    try { await api(`/employers/${e.id}/notes`, { method: 'POST', body: JSON.stringify({ text }) }); toast('Note added.'); rerender(); }
    catch (err) { toast(err.message); }
  };
  wireOpportunityControls(main, rerender);
}

/* ---------- Decision Studio ---------- */

let dsTrack = 'all';
const dsOpen = new Set();

async function renderDecisions(main) {
  const d = await api('/decisions');
  if (!trackList.length) await refreshTracks();
  const crit = d.criteria;
  const inTrack = (e) => dsTrack === 'all' || e.track === dsTrack;
  const names = Object.fromEntries(d.dealbreaker_options.map((x) => [x.key, x.name]));
  const scoreBar = (v) => v == null ? '<span class="muted small">—</span>'
    : `<span class="match"><span class="match-bar"><span style="width:${v}%"></span></span><b>${v}</b></span>`;

  const detail = (e) => `
    <div class="score-panel">
      ${crit.map((c) => {
        const cur = e.scores[c.key];
        return `<div class="score-row">
          <div class="score-crit"><b>${esc(c.name)}</b> <span class="small muted">${c.share.toFixed(0)}%</span><span class="ctx">${esc(c.hint)}</span></div>
          <div class="score-btns" role="group" aria-label="${esc(c.name)} score">
            ${[1, 2, 3, 4, 5].map((n) => `<button type="button" class="${cur?.score === n ? 'on' : ''}" data-score="${e.id}:${c.key}:${n}" title="${['', 'Poor', 'Weak', 'Okay', 'Good', 'Excellent'][n]}">${n}</button>`).join('')}
            <button type="button" class="clear ${cur ? '' : 'hide'}" data-score="${e.id}:${c.key}:0" title="Clear">×</button>
          </div>
          <input type="text" class="score-note" data-note="${e.id}:${c.key}" maxlength="300" placeholder="Why? (optional)" value="${esc(cur?.note || '')}" ${cur ? '' : 'disabled'} aria-label="Note for ${esc(c.name)}">
        </div>`;
      }).join('')}
      ${d.dealbreakers.length ? `<div class="q-label">Does it hit any of your deal-breakers?</div>
        <div class="choices">${d.dealbreakers.map((k) => `<button type="button" class="choice ${e.dealbreakers_hit.some((h) => h.key === k) ? 'on' : ''}" data-hit="${e.id}:${k}">${esc(names[k] || k)}</button>`).join('')}</div>` : ''}
      <p class="small muted" style="margin:12px 0 0">1 = poor fit, 3 = okay, 5 = excellent. Unscored priorities don't count against the match; they show up as unknowns.</p>
    </div>`;

  const row = (e) => `
    <div class="ds-row ${dsOpen.has(e.id) ? 'open' : ''}">
      <button type="button" class="ds-line" data-toggle="${e.id}" aria-expanded="${dsOpen.has(e.id)}">
        <span class="ds-rank">${e.rank ?? ''}</span>
        <span class="ds-name"><b>${esc(e.name)}</b><span class="ctx">${esc(e.location || '')}</span></span>
        <span>${trackChip(e.track)}</span>
        <span class="ds-score">${scoreBar(e.score)}</span>
        <span class="ds-info small">
          <span class="muted">${e.scored ? `${e.coverage}% of weight scored` : 'Not scored'}${e.ai_estimated ? ` · <span class="ai-est">${e.ai_estimated === e.scored ? 'all' : e.ai_estimated} AI-estimated</span>` : ''}</span>
          <span>${e.dealbreakers_hit.length ? `<span class="chip garnet">${esc(e.dealbreakers_hit.map((h) => h.name).join(', '))}</span>`
            : !e.scored ? `<span class="muted">Start with:</span> ${esc(e.biggest_unknown?.name || '')}`
            : e.biggest_unknown ? `<span class="muted">Biggest unknown:</span> ${esc(e.biggest_unknown.name)}` : '<span class="muted">Fully scored</span>'}</span></span>
      </button>
      ${dsOpen.has(e.id) ? detail(e) + `<div class="ds-foot"><a class="linkish small" href="#/employer/${e.id}">Open ${esc(e.name)} →</a></div>` : ''}
    </div>`;

  const section = (title, list, help) => list.length ? `
    <div class="card" style="margin-bottom:16px">
      <div class="card-head"><h2>${title}</h2><span class="small muted">${help}</span></div>
      ${list.map(row).join('')}
    </div>` : '';

  const ranked = d.ranked.filter(inTrack);
  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div><h1>Decision Studio</h1><p class="sub">Score employers 1–5 on what matters to you. The match is a plain weighted average of your scores: no AI judgment in the number.</p></div>
        <a class="btn ghost" href="#/setup/2" style="text-decoration:none">Edit priorities</a>
      </div>
      <div class="grid-2">
        <div>
          ${trackList.length > 1 ? `<div class="segmented" style="margin-bottom:14px">
            <button type="button" class="${dsTrack === 'all' ? 'on' : ''}" data-ds-track="all">All tracks</button>
            ${trackList.map((t) => `<button type="button" class="${dsTrack === t.key ? 'on' : ''}" data-ds-track="${esc(t.key)}">${esc(t.name)}</button>`).join('')}</div>` : ''}
          ${section('Ranking', ranked, 'Click an employer to score it')}
          ${ranked.length ? '' : '<div class="card card-pad empty" style="margin-bottom:16px">No scored employers here yet. Open one below and give it a few scores.</div>'}
          ${section('Not scored yet', d.unscored.filter(inTrack), 'Score a few priorities to rank it')}
          ${section('Ruled out by a deal-breaker', d.ruled_out.filter(inTrack), 'Not ranked')}
        </div>
        <div class="stack">
          <div class="card card-pad">
            <div class="actions" style="margin-bottom:10px"><div class="eyebrow">Your weights</div><span class="spacer"></span>
              <button type="button" class="linkish small" id="ds-reset">Reset to my ranking</button></div>
            ${crit.map((c) => `<div class="weight">
              <div class="weight-top"><span>${esc(c.name)}</span><b data-share="${c.key}">${c.share.toFixed(0)}%</b></div>
              <input type="range" min="0" max="40" step="1" value="${c.weight}" data-weight="${c.key}" aria-label="Weight for ${esc(c.name)}">
            </div>`).join('')}
            <p class="small muted" style="margin:8px 0 0">Percent of the match each priority carries. Drag to see the ranking change.</p>
          </div>
          <div class="card card-pad">
            <div class="actions" style="margin-bottom:8px"><div class="eyebrow">Deal-breakers</div><span class="spacer"></span><a class="linkish small" href="#/setup/2">Edit</a></div>
            ${d.dealbreakers.length ? `<div class="choices">${d.dealbreakers.map((k) => `<span class="chip">${esc(names[k] || k)}</span>`).join('')}</div>` : '<p class="small muted" style="margin:0">None.</p>'}
          </div>
        </div>
      </div>
    </div>`;

  const rerender = () => { const y = window.scrollY; renderDecisions(main).then(() => window.scrollTo(0, y)); };
  main.querySelectorAll('[data-ds-track]').forEach((b) => { b.onclick = () => { dsTrack = b.dataset.dsTrack; rerender(); }; });
  main.querySelectorAll('[data-toggle]').forEach((b) => {
    b.onclick = () => { const id = Number(b.dataset.toggle); if (dsOpen.has(id)) dsOpen.delete(id); else dsOpen.add(id); rerender(); };
  });
  main.querySelectorAll('[data-score]').forEach((b) => {
    b.onclick = async () => {
      const [id, key, n] = b.dataset.score.split(':');
      const note = main.querySelector(`[data-note="${id}:${key}"]`)?.value || '';
      try {
        await api(`/employers/${id}/scores/${key}`, { method: 'PUT', body: JSON.stringify({ score: Number(n) || null, note }) });
        rerender();
      } catch (err) { toast(err.message); }
    };
  });
  main.querySelectorAll('[data-note]').forEach((inp) => {
    inp.addEventListener('change', async () => {
      const [id, key] = inp.dataset.note.split(':');
      const e = [...d.ranked, ...d.unscored, ...d.ruled_out].find((x) => x.id === Number(id));
      const cur = e?.scores[key];
      if (!cur) return;
      try { await api(`/employers/${id}/scores/${key}`, { method: 'PUT', body: JSON.stringify({ score: cur.score, note: inp.value }) }); toast('Note saved.'); }
      catch (err) { toast(err.message); }
    });
  });
  main.querySelectorAll('[data-hit]').forEach((b) => {
    b.onclick = async () => {
      const [id, key] = b.dataset.hit.split(':');
      const e = [...d.ranked, ...d.unscored, ...d.ruled_out].find((x) => x.id === Number(id));
      const keys = new Set(e.dealbreakers_hit.map((h) => h.key));
      if (keys.has(key)) keys.delete(key); else keys.add(key);
      try { await api(`/employers/${id}/dealbreakers`, { method: 'PUT', body: JSON.stringify({ keys: [...keys] }) }); rerender(); }
      catch (err) { toast(err.message); }
    };
  });
  // Weights: show the new percentages while dragging, save and re-rank on release.
  const sliders = [...main.querySelectorAll('[data-weight]')];
  sliders.forEach((sl) => {
    sl.addEventListener('input', () => {
      const total = sliders.reduce((n, x) => n + Number(x.value), 0) || 1;
      sliders.forEach((x) => { main.querySelector(`[data-share="${x.dataset.weight}"]`).textContent = `${Math.round((100 * Number(x.value)) / total)}%`; });
    });
    sl.addEventListener('change', async () => {
      try { await api(`/criteria/${sl.dataset.weight}`, { method: 'PATCH', body: JSON.stringify({ weight: Number(sl.value) }) }); rerender(); }
      catch (err) { toast(err.message); }
    });
  });
  $('#ds-reset').onclick = async () => { await api('/criteria/reset', { method: 'POST' }); toast('Weights reset to your ranking.'); rerender(); };
}

/* ---------- Target employers: profile questions -> Target Scout -> reactions -> top 10 ---------- */

const REACTIONS = [['interested', 'Interested'], ['maybe', 'Maybe'], ['no', 'Not for me']];

async function renderTargets(main) {
  const b = await api('/targets');
  if (!trackList.length) await refreshTracks();
  if (!b.profile_complete) {
    main.innerHTML = `<div class="page"><div class="page-head"><div><h1>Target employers</h1></div></div>
      <div class="card placeholder"><h2>Answer the About you questions first</h2><p>The Target Scout suggests employers from your answers about the work and life you want.</p>
      <p><a class="btn primary" href="#/setup/1" style="margin-top:12px;text-decoration:none">Answer the questions</a></p></div></div>`;
    return;
  }

  const today = b.runs_today, cap = b.runs_per_day;
  const pending = b.candidates.filter((c) => !c.reaction && !c.employer_id);
  const p = (c) => c.params;
  const card = (c) => `
    <div class="cand ${c.reaction ? 'r-' + c.reaction : ''}" data-cand="${c.id}">
      <div class="cand-top">
        <div><b>${esc(c.name)}</b> ${trackChip(c.track)} ${c.from_user ? '<span class="chip">On your list</span>' : ''}
          <span class="ctx">${esc(p(c).sub_sector)} · ${esc(p(c).hq)}</span></div>
        <div class="cand-score">${c.score == null ? '' : `<b>${c.score}</b><span class="small muted">est. match</span>`}</div>
      </div>
      <p class="cand-why">${esc(c.why)}</p>
      <div class="facts">
        ${[['Hours', p(c).typical_hours], ['Schedule', p(c).schedule], ['Travel', p(c).travel], ['Work setup', p(c).remote_policy],
           ['Field/office', p(c).field_office], ['Size', p(c).size], ['Ownership', p(c).ownership], ['Hires interns', p(c).hires_mba_interns],
           ['Recruiting', p(c).recruiting_path], ['Intern pay', p(c).intern_pay], ['Base pay', p(c).base_pay], ['Upside', p(c).upside]]
          .map(([k, v]) => `<span><span class="muted">${k}</span> ${esc(v)}</span>`).join('')}
      </div>
      <details class="blocked"><summary>Roles, mission and fit by priority</summary>
        <p class="small"><b>Typical roles:</b> ${esc(p(c).mba_roles)}<br><b>The work:</b> ${esc(p(c).kind_of_work)}<br><b>Mission:</b> ${esc(p(c).mission)}<br><b>Other locations:</b> ${esc(p(c).other_locations)}</p>
        <ul class="fit-list">${Object.entries(c.fit).map(([k, v]) => `<li><span class="fit-score">${v.score}</span> <b>${esc(CRIT_NAMES[k] || k)}</b> <span class="muted">${esc(v.reason)}</span></li>`).join('')}</ul>
      </details>
      ${c.dealbreakers_hit.length ? `<div class="warning" style="margin:8px 0 0">May hit your deal-breaker${c.dealbreakers_hit.length > 1 ? 's' : ''}: <b>${esc(c.dealbreakers_hit.map((h) => h.name).join(', '))}</b>. It won't enter your top ${b.top_n}.</div>` : ''}
      <div class="actions" style="margin-top:10px">
        ${c.employer_id ? `<a class="chip ok" href="#/employer/${c.employer_id}" style="text-decoration:none">In Career HQ →</a>` : `<div class="segmented">${REACTIONS.map(([k, label]) => `<button type="button" class="${c.reaction === k ? 'on' : ''}" data-react="${c.id}:${k}">${label}</button>`).join('')}</div>`}
        <span class="spacer"></span><span class="small muted">AI estimate · ${esc(c.confidence)} confidence</span>
      </div>
    </div>`;

  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div><h1>Target employers</h1><p class="sub">The Target Scout suggests employers from your answers. React to each one; your top ${b.top_n} is ranked with your own Decision Studio weights.</p></div>
        <div class="actions"><button class="btn ghost" id="tg-edit">Edit answers</button>
          <button class="btn ${b.total ? '' : 'primary'}" id="tg-suggest" ${today >= cap ? 'disabled' : ''}>${b.total ? 'Suggest more' : 'Suggest employers'}</button></div>
      </div>
      <div class="warning" style="margin-top:0">Every fact and fit score here comes from the AI's memory, not a live source, and can be wrong or out of date. Verify them in conversations; after you add an employer, its details stay labeled as AI estimates.</div>
      ${b.total ? '' : `<div class="card placeholder"><h2>Ready when you are</h2><p>The Target Scout reads your tracks, priorities, deal-breakers and answers, then suggests about 15 employers with their location, hours, travel, pay and more. It takes about a minute and costs well under a cent.</p></div>`}
      ${b.total ? `<div class="grid-2">
        <div>
          <div class="actions" style="margin-bottom:10px"><div class="eyebrow">Suggestions · rated ${b.rated} of ${b.total}</div></div>
          ${pending.map(card).join('')}
          ${b.candidates.filter((c) => c.reaction || c.employer_id).length ? `<details class="blocked" ${pending.length ? '' : 'open'}><summary>Already rated · ${b.candidates.filter((c) => c.reaction || c.employer_id).length}</summary>
            ${b.candidates.filter((c) => c.reaction || c.employer_id).map(card).join('')}</details>` : ''}
        </div>
        <div class="stack">
          <div class="card card-pad top-card">
            <div class="eyebrow" style="margin-bottom:8px">Your top ${b.top_n}</div>
            ${b.top.length ? `<ol class="top-list">${b.top.map((c) => `<li><span class="top-rank">${c.rank}</span><span class="top-name"><b>${esc(c.name)}</b><span class="ctx">${esc(c.reaction === 'interested' ? 'Interested' : 'Maybe')} · ${esc(trackOf(c.track)?.short || '')}</span></span><b class="top-score">${c.score}</b></li>`).join('')}</ol>`
              : '<p class="small muted" style="margin:0">Mark suggestions Interested or Maybe to build your list.</p>'}
            <p class="small muted">Ranked by estimated match with your weights. Interested beats Maybe on a tie; deal-breakers and "Not for me" are left out.</p>
            ${b.top.some((c) => !c.employer_id) ? `<button class="btn primary" id="tg-add" style="width:100%;justify-content:center">Add ${b.top.filter((c) => !c.employer_id).length} to Career HQ</button>` : (b.top.length ? '<p class="small" style="margin:0">All of your top list is in Career HQ. <a class="linkish" href="#/decisions">Open Decision Studio →</a></p>' : '')}
          </div>
          <p class="small muted" style="padding:0 4px">${today} of ${cap} suggestion runs used today.</p>
        </div>
      </div>` : ''}
    </div>`;

  const rerender = () => { const y = window.scrollY; renderTargets(main).then(() => window.scrollTo(0, y)); };
  $('#tg-edit').onclick = () => { location.hash = '#/setup/1'; };
  $('#tg-suggest').onclick = () => runScout(main);
  main.querySelectorAll('[data-react]').forEach((btn) => {
    btn.onclick = async () => {
      const [id, r] = btn.dataset.react.split(':');
      const cur = b.candidates.find((c) => c.id === Number(id));
      try { await api(`/targets/${id}/reaction`, { method: 'PUT', body: JSON.stringify({ reaction: cur.reaction === r ? null : r }) }); rerender(); }
      catch (err) { toast(err.message); }
    };
  });
  $('#tg-add')?.addEventListener('click', async () => {
    try {
      const r = await api('/targets/add-top', { method: 'POST' });
      toast(`Added ${r.added.length} employers to Career HQ, with their details and fit scores as AI estimates.`);
      await refreshTracks();
      rerender();
    } catch (err) { toast(err.message); }
  });
}

const CRIT_NAMES = { work: 'Enjoyable work & ownership', pay: 'Compensation & upside', lifestyle: 'Location & lifestyle', impact: 'Mission & impact',
  team: 'Team & mentorship', growth: 'Learning & growth', stability: 'Stability', brand: 'Brand & exit options' };

async function runScout(main) {
  const btn = $('#tg-suggest');
  btn.disabled = true;
  const stop = startThinking('Finding employers that fit you', ['Reading your answers, tracks and priorities', 'Choosing employers across your tracks',
    'Filling in location, hours, travel and pay', 'Scoring each one on your priorities', 'Checking for duplicates and deal-breakers'],
  'Usually 40 to 60 seconds.', 9000);
  try {
    const r = await api('/targets/suggest', { method: 'POST' });
    toast(r.outcome === 'ok' ? `${r.added} employers suggested${r.blocked.length ? ` · ${r.blocked.length} left out by safety checks` : ''}.` : r.message);
  } catch (err) { toast(err.message); } finally { stop(); }
  await renderTargets(main);
  refreshStatus().catch(() => {});
}

/* ---------- Welcome: a blank Career HQ ---------- */

async function renderWelcome(main) {
  const tile = (ic, title, text) => `<div class="w-tile"><span class="w-ic">${icon(ic, 20)}</span><b>${title}</b><span>${text}</span></div>`;
  main.innerHTML = `
    <div class="page welcome">
      <div class="card welcome-card">
        <div class="w-hero">
          <span class="brand-mark big">C</span>
          <h1>Find the career that fits you</h1>
          <p>Not sure what you want to do next? Career HQ helps you choose a direction, find employers and people worth your time, and learn something real from every conversation.</p>
        </div>
        <div class="w-body">
          <div class="w-tiles">
            ${tile('compass', 'Directions', 'The AI suggests career paths from your answers, each with the questions to settle first.')}
            ${tile('target', 'Employers', 'A ranked top 10 to target, with hours, travel, pay and fit for each.')}
            ${tile('network', 'People & force multipliers', 'Who could answer your questions, where to find them, and groups that multiply your effort.')}
            ${tile('chat', 'Conversations that teach', 'Paste your notes; approve the answers, learnings and follow-ups the AI pulls out.')}
          </div>
          <div class="actions" style="justify-content:center;margin-top:22px"><button class="btn primary lg" id="w-start">Set up my Career HQ</button>
            <button class="btn lg" id="w-sample">Explore with sample data</button></div>
          <p class="small muted" style="margin:14px 0 0">Setup takes about 5 minutes: questions about you, what matters to you, then the directions you'll explore. The sample is a made-up user comparing outdoor recreation and energy careers.</p>
        </div>
      </div>
    </div>`;
  $('#w-start').onclick = () => { wiz = null; location.hash = '#/setup/1'; };
  $('#w-sample').onclick = async () => {
    try {
      await api('/sample', { method: 'POST' });
      trackList = [];
      await refreshStatus();
      toast('Sample data loaded. Everything in it is made up.');
      if (location.hash === '#/dashboard') router(); else location.hash = '#/dashboard';
    } catch (err) { toast(err.message); }
  };
}

function openStartOver() {
  openModal('Start over?', `
    <div class="stack">
      <p style="margin:0">This deletes everything in this Career HQ: setup answers, tracks, employers, contacts, conversations and notes. It can't be undone. (The AI cost log is kept, so the daily budget still counts.)</p>
      <label class="field">Type START OVER to confirm<input type="text" id="so-confirm" autocomplete="off"></label>
      <div class="actions"><span class="spacer"></span><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="so-go">Delete everything</button></div>
    </div>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#so-go').onclick = async () => {
      try {
        await api('/reset', { method: 'POST', body: JSON.stringify({ confirm: $('#so-confirm').value.trim() }) });
        closeModal();
        wiz = null; trackList = [];
        await refreshStatus();
        toast('Career HQ is blank again.');
        if (location.hash === '#/dashboard') router(); else location.hash = '#/dashboard';
      } catch (err) { toast(err.message); }
    };
  });
}

/* ---------- Setup wizard: 1 About you, 2 What matters, 3 Directions ---------- */

const OTHER = '__other';
const CRIT_ORDER = ['work', 'pay', 'lifestyle', 'impact', 'team', 'growth', 'stability', 'brand'];
const ROLE_DEFAULTS = ['Primary focus', 'Strong alternative', 'Exploring'];
const EXCLUSIVE = ['None', 'Not sure yet'];   // picking one of these clears the rest of a multi question
let wiz = null;   // the wizard's working copy: answers, ranking, deal-breakers, picked tracks

async function renderSetup(main, stepParam) {
  const [pf, pr, tr, dl] = await Promise.all([api('/profile'), api('/priorities'), api('/tracks'), api('/directions')]);
  const ranked = pr.criteria.filter((c) => c.rank);
  if (!wiz) {
    wiz = {
      answers: { ...pf.answers, known_employers: [...(pf.answers.known_employers || [])] },
      ranking: ranked.map((c) => c.key),
      breakers: new Set(pr.dealbreakers),
      breakersAnswered: ranked.length > 0,
      picks: tr.tracks.map((t) => ({ key: t.key, name: t.name, role: t.role, blurb: t.blurb, in_use: t.in_use, direction_id: null })),
      custom: '',
    };
  }
  const questions = pf.sections.flatMap((x) => x.questions);
  const isAnswered = (q) => (q.type === 'multi' ? (wiz.answers[q.key] || []).length > 0 : !!wiz.answers[q.key]);
  const profileDone = questions.every(isAnswered) && Object.keys(pf.answers).length > 0;
  const prioritiesDone = ranked.length > 0;
  const first = tr.tracks.length === 0;
  let step = Math.min(3, Math.max(1, Number(stepParam) || 1));
  if (step >= 2 && !profileDone) step = 1;
  if (step === 3 && !prioritiesDone) step = 2;

  const stepper = `<div class="stepper">${['About you', 'What matters', 'Directions'].map((label, i) => {
    const n = i + 1;
    const reachable = n === 1 || (n === 2 && profileDone) || (n === 3 && profileDone && prioritiesDone);
    return `<a class="step ${n === step ? 'on' : ''} ${reachable ? '' : 'off'}" ${reachable ? `href="#/setup/${n}"` : ''}><span class="step-num">${n}</span>${label}</a>`;
  }).join('<span class="step-line"></span>')}</div>`;

  let body = '';
  if (step === 1) body = setupAboutYou(pf, questions, isAnswered);
  if (step === 2) body = setupPriorities(pr);
  if (step === 3) body = setupDirections(tr, dl);

  main.innerHTML = `
    <div class="page setup-page">
      <div class="eyebrow">${first ? 'Set up your Career HQ' : 'Edit your setup'}</div>
      ${stepper}
      ${body}
    </div>`;
  const rerender = () => { const y = window.scrollY; renderSetup(main, step).then(() => window.scrollTo(0, y)); };
  if (step === 1) wireAboutYou(main, pf, questions, rerender);
  if (step === 2) wirePriorities(main, rerender);
  if (step === 3) wireDirections(main, tr, dl, rerender, first);
}

function setupAboutYou(pf, questions, isAnswered) {
  const a = wiz.answers;
  const answered = questions.filter(isAnswered).length;
  const q = (x) => {
    const val = a[x.key];
    const on = (k) => (x.type === 'multi' ? (val || []).includes(k) : val === k);
    return `<div class="pq" data-q="${x.key}">
      <div class="q-label">${esc(x.label)}${x.type === 'multi' ? ` <span class="muted">(${x.max ? `up to ${x.max}` : 'pick any'})</span>` : ''}</div>
      <div class="choices">${x.options.map((o) => `<button type="button" class="choice ${on(o.key) ? 'on' : ''}" data-opt="${esc(o.key)}">${esc(o.label)}</button>`).join('')}</div>
    </div>`;
  };
  return `
    <h1>About you</h1>
    <p class="sub">${questions.length} quick questions, all multiple choice. "Not sure yet" is a fine answer: the AI uses all of this to suggest directions, employers and people to meet.</p>
    <div class="progress" style="margin:14px 0 6px"><span style="width:${(100 * answered) / questions.length}%"></span></div>
    <p class="small muted" style="margin:0 0 6px">${answered} of ${questions.length} answered</p>
    ${pf.sections.map((sec) => `<h2 class="sec-title">${esc(sec.title)}</h2><div class="card card-pad">${sec.questions.map(q).join('')}</div>`).join('')}
    <h2 class="sec-title">Employers already on your list <span class="muted small">(optional)</span></h2>
    <div class="card card-pad">
      <p class="small muted" style="margin:0 0 8px">One per line, up to ${pf.max_known_employers}. The Target Scout will include them.</p>
      <textarea id="known" rows="3" placeholder="e.g. a company you've always wanted to work for">${esc((a.known_employers || []).join('\n'))}</textarea>
    </div>
    <div class="actions" style="margin-top:18px"><span class="spacer"></span><button class="btn primary" id="wz-next">Save and continue</button></div>`;
}

function wireAboutYou(main, pf, questions, rerender) {
  const a = wiz.answers;
  main.querySelectorAll('.pq').forEach((box) => {
    const x = questions.find((y) => y.key === box.dataset.q);
    box.querySelectorAll('[data-opt]').forEach((btn) => {
      btn.onclick = () => {
        const k = btn.dataset.opt;
        if (x.type === 'single') a[x.key] = a[x.key] === k ? undefined : k;
        else {
          const cur = new Set(a[x.key] || []);
          if (cur.has(k)) cur.delete(k);
          else if (EXCLUSIVE.includes(k)) { cur.clear(); cur.add(k); }
          else { EXCLUSIVE.forEach((e) => cur.delete(e)); if (!x.max || cur.size < x.max) cur.add(k); else toast(`Pick at most ${x.max}.`); }
          a[x.key] = [...cur];
        }
        rerender();
      };
    });
  });
  $('#known').oninput = (e) => { a.known_employers = e.target.value.split('\n').map((t) => t.trim()).filter(Boolean); };
  $('#wz-next').onclick = async () => {
    try {
      await api('/profile', { method: 'PUT', body: JSON.stringify(a) });
      location.hash = '#/setup/2';
    } catch (err) { toast(err.message); }
  };
}

function setupPriorities(pr) {
  const s = wiz;
  return `
    <h1>What matters to you?</h1>
    <p class="sub">Your ranking sets the starting weights in Decision Studio, which scores employers the same way for every user. You can fine-tune the weights there.</p>
    <h2 class="sec-title">Click your priorities in order, most important first</h2>
    <div class="card card-pad">
      <p class="small muted" style="margin:0 0 12px">Rank at least your top 3; the rest keep the order shown. Click one again to take it back out.</p>
      <div class="rank-list">${CRIT_ORDER.map((key) => {
        const c = pr.criteria.find((x) => x.key === key);
        const pos = s.ranking.indexOf(key);
        return `<button type="button" class="rank-item ${pos >= 0 ? 'on' : ''}" data-rank="${key}">
          <span class="rank-num">${pos >= 0 ? pos + 1 : ''}</span>
          <span><b>${esc(c.name)}</b><span class="ctx">${esc(c.hint)}</span></span></button>`;
      }).join('')}</div>
      ${s.ranking.length ? '<button type="button" class="linkish small" id="rank-reset" style="margin-top:10px">Start the ranking over</button>' : ''}
    </div>
    <h2 class="sec-title">Which of these would rule an employer out?</h2>
    <div class="card card-pad">
      <p class="small muted" style="margin:0 0 12px">An employer that hits one is set aside instead of ranked.</p>
      <div class="choices">${pr.dealbreaker_options.map((d) => `<button type="button" class="choice ${s.breakers.has(d.key) ? 'on' : ''}" data-breaker="${d.key}">${esc(d.name)}</button>`).join('')}
        <button type="button" class="choice ${s.breakersAnswered && !s.breakers.size ? 'on' : ''}" data-breaker="__none">None of these</button></div>
    </div>
    <div class="actions" style="margin-top:18px"><a class="btn ghost" href="#/setup/1" style="text-decoration:none">Back</a><span class="spacer"></span>
      <button class="btn primary" id="wz-next">Save and continue</button></div>`;
}

function wirePriorities(main, rerender) {
  const s = wiz;
  main.querySelectorAll('[data-rank]').forEach((b) => {
    b.onclick = () => {
      const i = s.ranking.indexOf(b.dataset.rank);
      if (i >= 0) s.ranking.splice(i, 1); else s.ranking.push(b.dataset.rank);
      rerender();
    };
  });
  $('#rank-reset')?.addEventListener('click', () => { s.ranking = []; rerender(); });
  main.querySelectorAll('[data-breaker]').forEach((b) => {
    b.onclick = () => {
      const k = b.dataset.breaker;
      s.breakersAnswered = true;
      if (k === '__none') s.breakers.clear();
      else if (s.breakers.has(k)) s.breakers.delete(k); else s.breakers.add(k);
      rerender();
    };
  });
  $('#wz-next').onclick = async () => {
    if (s.ranking.length < 3) { toast('Rank at least your top 3 priorities.'); return; }
    if (!s.breakersAnswered) { toast('Pick your deal-breakers, or "None of these".'); return; }
    const ranking = [...s.ranking, ...CRIT_ORDER.filter((k) => !s.ranking.includes(k))];
    try {
      await api('/priorities', { method: 'PUT', body: JSON.stringify({ ranking, dealbreakers: [...s.breakers] }) });
      location.hash = '#/setup/3';
    } catch (err) { toast(err.message); }
  };
}

function setupDirections(tr, dl) {
  const picks = wiz.picks;
  const full = picks.length >= 3;
  const pickedNames = new Set(picks.map((p) => p.name.toLowerCase()));
  const dirCard = (d) => `
    <div class="dir-card ${pickedNames.has(d.name.toLowerCase()) ? 'picked' : ''}">
      <div class="actions"><h3>${esc(d.name)}</h3><span class="spacer"></span>
        ${pickedNames.has(d.name.toLowerCase()) ? '<span class="chip ok">Picked</span>'
          : `<button class="btn sm" data-pick-dir="${d.id}" ${full ? 'disabled' : ''}>+ Add as a track</button>`}</div>
      <p class="dir-one">${esc(d.one_liner)}</p>
      <p class="small">${esc(d.why_fit)}</p>
      <div class="dir-grid small">
        <div><span class="muted">Example roles</span>${d.example_roles.map((r) => `<div>${esc(r)}</div>`).join('')}</div>
        <div><span class="muted">Kinds of employers</span>${d.employer_types.map((r) => `<div>${esc(r)}</div>`).join('')}</div>
      </div>
      <p class="small" style="margin:8px 0 0"><span class="muted">Trade-offs:</span> ${esc(d.tradeoffs)}</p>
      <details class="blocked"><summary>Questions to answer before committing (${d.questions.length})</summary>
        <ul>${d.questions.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>
        <p class="small muted" style="margin:4px 0 0">Picking this direction adds them to your open questions, so your networking has something to learn.</p></details>
    </div>`;
  return `
    <h1>Which directions will you explore?</h1>
    <p class="sub">Keep 1 to 3. Each becomes a track: a column in Internship HQ, a pipeline on your Dashboard, and a lens for the AI's suggestions.</p>
    <h2 class="sec-title">Your tracks · ${picks.length} of 3</h2>
    <div class="card card-pad">
      ${picks.length ? picks.map((p, i) => `
        <div class="pick-row" data-pick="${i}">
          <span class="chip t${i + 1}">${i + 1}</span>
          <input type="text" class="pick-name" value="${esc(p.name)}" maxlength="60" aria-label="Track name">
          <div class="segmented">${ROLE_DEFAULTS.map((r) => `<button type="button" class="${p.role === r ? 'on' : ''}" data-role="${esc(r)}">${esc(r)}</button>`).join('')}</div>
          <button type="button" class="icon-btn" data-remove title="${p.in_use ? 'Has employers or opportunities: move them first' : 'Remove'}" ${p.in_use ? 'disabled' : ''}>×</button>
        </div>`).join('') : '<p class="empty small" style="margin:0">No tracks yet. Let the AI suggest some below, or pick your own.</p>'}
    </div>
    <h2 class="sec-title">Let the AI suggest directions</h2>
    <div class="card card-pad">
      <div class="actions"><p class="small muted" style="margin:0;flex:1">The Path Finder reads your answers, priorities and deal-breakers and proposes five different directions, with why each fits you, example roles, trade-offs and the questions you'd need answered.</p>
        <button class="btn ${dl.directions.length ? '' : 'primary'}" id="pf-suggest">${dl.directions.length ? 'Suggest again' : 'Suggest directions'}</button></div>
      ${dl.directions.length ? `<div class="dir-list">${dl.directions.map(dirCard).join('')}</div>` : ''}
    </div>
    <h2 class="sec-title">Or choose your own</h2>
    <div class="card card-pad">
      <div class="choices">${tr.presets.map((p) => `<button type="button" class="choice ${pickedNames.has(p.name.toLowerCase()) ? 'on' : ''}" data-preset="${esc(p.name)}" ${full && !pickedNames.has(p.name.toLowerCase()) ? 'disabled' : ''}>${esc(p.name)}</button>`).join('')}</div>
      <div class="actions" style="margin-top:10px"><input type="text" id="custom-track" maxlength="60" placeholder="Or name your own, e.g. Sports business" value="${esc(wiz.custom)}" style="flex:1">
        <button class="btn sm" id="add-custom" ${full ? 'disabled' : ''}>Add</button></div>
    </div>
    <div class="actions" style="margin-top:18px"><a class="btn ghost" href="#/setup/2" style="text-decoration:none">Back</a><span class="spacer"></span>
      <button class="btn primary" id="wz-finish">${tr.tracks.length ? 'Save' : 'Finish setup'}</button></div>`;
}

function addPick(p) {
  const picks = wiz.picks;
  if (picks.length >= 3) { toast('Three tracks at most.'); return; }
  if (picks.some((x) => x.name.toLowerCase() === p.name.toLowerCase())) return;
  const role = picks.some((x) => x.role === 'Primary focus') ? ROLE_DEFAULTS[Math.min(picks.length, 2)] : 'Primary focus';
  picks.push({ key: null, in_use: 0, direction_id: null, blurb: '', ...p, role });
}

function wireDirections(main, tr, dl, rerender, first) {
  const picks = wiz.picks;
  main.querySelectorAll('[data-pick]').forEach((row) => {
    const p = picks[Number(row.dataset.pick)];
    row.querySelector('.pick-name').oninput = (e) => { p.name = e.target.value; };
    row.querySelectorAll('[data-role]').forEach((b) => {
      b.onclick = () => {
        if (b.dataset.role === 'Primary focus') picks.forEach((x) => { if (x !== p && x.role === 'Primary focus') x.role = 'Strong alternative'; });
        p.role = b.dataset.role;
        rerender();
      };
    });
    row.querySelector('[data-remove]').onclick = () => {
      picks.splice(picks.indexOf(p), 1);
      if (picks.length && !picks.some((x) => x.role === 'Primary focus')) picks[0].role = 'Primary focus';
      rerender();
    };
  });
  main.querySelectorAll('[data-pick-dir]').forEach((b) => {
    b.onclick = () => {
      const d = dl.directions.find((x) => x.id === Number(b.dataset.pickDir));
      addPick({ name: d.name, blurb: d.one_liner, direction_id: d.id });
      rerender();
    };
  });
  main.querySelectorAll('[data-preset]').forEach((b) => {
    b.onclick = () => {
      const name = b.dataset.preset;
      const i = picks.findIndex((x) => x.name.toLowerCase() === name.toLowerCase());
      if (i >= 0 && !picks[i].in_use) picks.splice(i, 1);
      else if (i < 0) addPick({ name, blurb: tr.presets.find((p) => p.name === name)?.blurb || '' });
      if (picks.length && !picks.some((x) => x.role === 'Primary focus')) picks[0].role = 'Primary focus';
      rerender();
    };
  });
  $('#custom-track').oninput = (e) => { wiz.custom = e.target.value; };
  $('#add-custom').onclick = () => {
    const name = wiz.custom.trim();
    if (!name) { toast('Type a name for the track first.'); return; }
    addPick({ name });
    wiz.custom = '';
    rerender();
  };
  $('#pf-suggest').onclick = async () => {
    const btn = $('#pf-suggest');
    btn.disabled = true;
    const stop = startThinking('Finding directions for you', ['Reading your answers', 'Weighing your priorities and deal-breakers',
      'Picking five different directions', 'Writing the questions you\'d need answered'], 'Usually about 15 seconds.', 3500);
    try {
      const r = await api('/directions/suggest', { method: 'POST' });
      toast(r.outcome === 'ok' ? `${r.added} directions suggested.` : r.message);
    } catch (err) { toast(err.message); } finally { stop(); }
    rerender();
    refreshStatus().catch(() => {});
  };
  $('#wz-finish').onclick = async () => {
    if (!picks.length) { toast('Keep at least one track.'); return; }
    const payload = picks.map((p) => ({ key: p.key, name: p.name.trim(), role: picks.length === 1 ? 'Primary focus' : p.role,
      blurb: (p.blurb || '').trim(), direction_id: p.direction_id }));
    if (payload.some((p) => !p.name)) { toast('Every track needs a name.'); return; }
    try {
      const r = await api('/tracks', { method: 'PUT', body: JSON.stringify({ tracks: payload }) });
      wiz = null; trackList = [];
      await refreshTracks();
      await refreshStatus();
      toast(first ? `Your Career HQ is ready${r.questions_added ? `, with ${r.questions_added} questions to explore` : ''}.` : 'Setup saved.');
      const next = first ? '#/targets' : '#/dashboard';
      if (location.hash === next) router(); else location.hash = next;
    } catch (err) { toast(err.message); }
  };
}

/* ---------- Connections & force multipliers ---------- */

async function openFoundForm(lead) {
  lookups = await api('/lookups');
  const match = lookups.employers.find((e) => e.name.toLowerCase() === (lead.detail.where || '').toLowerCase());
  openModal('Add the person you found', `
    <form class="stack" id="found-form">
      <p class="small muted" style="margin:0">Suggested: ${esc(lead.detail.role)} · ${esc(lead.detail.where)}</p>
      <label class="field">Their name<input type="text" name="name" required maxlength="120"></label>
      <label class="field">Role<input type="text" name="role" maxlength="160" value="${esc(lead.detail.role.split(/\s+(?:who|that|responsible|working|focused|with)\s+|[,(;]/)[0].trim().slice(0, 80))}"></label>
      <label class="field">Employer<select name="employer_id"><option value="">Not in Career HQ</option>
        ${lookups.employers.map((e) => `<option value="${e.id}" ${match && match.id === e.id ? 'selected' : ''}>${esc(e.name)}</option>`).join('')}</select></label>
      <p class="small muted" style="margin:0">Why they're worth talking to${lead.detail.answers_question ? ', and the question they could answer,' : ''} is saved as a note on their profile.</p>
      <div class="actions"><span class="spacer"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">Add contact</button></div>
    </form>`, (root) => {
    root.querySelector('[data-close]').onclick = closeModal;
    root.querySelector('#found-form').onsubmit = async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target));
      data.employer_id = data.employer_id ? Number(data.employer_id) : null;
      try {
        const { contact_id: id } = await api(`/connections/${lead.id}/contact`, { method: 'POST', body: JSON.stringify(data) });
        closeModal();
        toast('Contact added. Log your conversation here when you talk.');
        location.hash = `#/contact/${id}`;
      } catch (err) { toast(err.message); }
    };
  });
}

let cxTrack = 'all';

async function renderConnections(main) {
  const d = await api('/connections');
  if (!trackList.length) await refreshTracks();
  const inTrack = (x) => cxTrack === 'all' || x.track === cxTrack;
  const live = (list) => list.filter((x) => x.status !== 'dismissed' && inTrack(x));
  const dismissed = [...d.connects, ...d.multipliers].filter((x) => x.status === 'dismissed' && inTrack(x));
  const actions = (x) => x.status === 'added'
    ? '<span class="chip ok">In your to-dos</span>'
    : x.status === 'dismissed' ? `<button class="btn sm ghost" data-lead="${x.id}:undo">Undo</button>`
      : `<button class="btn sm primary" data-lead="${x.id}:add">Add to my to-dos</button><button class="btn sm" data-lead="${x.id}:dismiss">Dismiss</button>`;
  const connectCard = (x) => `
    <div class="lead">
      <div class="actions"><b>${esc(x.detail.role)}</b>${x.track ? trackChip(x.track) : ''}</div>
      <div class="ctx">${esc(x.detail.where)}</div>
      <p class="small" style="margin:6px 0">${esc(x.detail.why)}</p>
      ${x.detail.answers_question ? `<p class="small" style="margin:0 0 6px"><span class="muted">Could answer:</span> ${esc(x.detail.answers_question)}</p>` : ''}
      <p class="small" style="margin:0 0 6px"><span class="muted">Find them:</span> ${esc(x.detail.how_to_find)} · <span class="mono">${esc(x.detail.search_phrase)}</span></p>
      <p class="small" style="margin:0 0 8px"><span class="muted">Open with:</span> “${esc(x.detail.opening)}”</p>
      <div class="actions">${actions(x)}
        ${x.contact_id ? `<a class="btn sm ghost" href="#/contact/${x.contact_id}" style="text-decoration:none">Contact added →</a>`
          : `<button class="btn sm ghost" data-found="${x.id}">I found someone</button>`}</div>
    </div>`;
  const multCard = (x) => `
    <div class="lead">
      <div class="actions"><b>${esc(x.title)}</b><span class="chip">${esc(x.detail.type)}</span>${x.track ? trackChip(x.track) : ''}</div>
      <p class="small" style="margin:6px 0">${esc(x.detail.why)}</p>
      <p class="small" style="margin:0 0 6px"><span class="muted">Effort</span> ${esc(x.detail.effort)} · <span class="muted">Cost</span> ${esc(x.detail.cost)}</p>
      <p class="small" style="margin:0 0 8px"><span class="muted">First step:</span> ${esc(x.detail.next_step)}</p>
      <div class="actions">${actions(x)}</div>
    </div>`;
  const total = d.connects.length + d.multipliers.length;
  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div><h1>Connections &amp; force multipliers</h1><p class="sub">Who to talk to, and what multiplies your effort, for the directions you're exploring.</p></div>
        <div class="actions"><button class="btn ${total ? '' : 'primary'}" id="cx-suggest" ${d.runs_today >= d.runs_per_day ? 'disabled' : ''}>${total ? 'Suggest more' : 'Suggest connections'}</button></div>
      </div>
      <div class="warning" style="margin-top:0">These are AI suggestions from its memory. People are suggested as kinds of roles, never names, so you find the real person yourself. Check that each organization and event is current before you spend money or time on it.</div>
      ${total ? '' : `<div class="card placeholder"><h2>Find your people</h2><p>The AI looks at your tracks, open questions and target employers, then suggests the kinds of people who can answer your questions, where to find them, and the associations, alumni groups, events and programs that multiply your effort. About 20 seconds; well under a cent.</p></div>`}
      ${total && trackList.length > 1 ? `<div class="segmented" style="margin-bottom:14px">
        <button type="button" class="${cxTrack === 'all' ? 'on' : ''}" data-cx-track="all">All tracks</button>
        ${trackList.map((t) => `<button type="button" class="${cxTrack === t.key ? 'on' : ''}" data-cx-track="${esc(t.key)}">${esc(t.name)}</button>`).join('')}</div>` : ''}
      ${total ? `<div class="lead-grid">
        <div><h2 class="sec-title" style="margin-top:0">People to meet · ${live(d.connects).length}</h2>${live(d.connects).map(connectCard).join('') || '<p class="empty small">None here.</p>'}</div>
        <div><h2 class="sec-title" style="margin-top:0">Force multipliers · ${live(d.multipliers).length}</h2>${live(d.multipliers).map(multCard).join('') || '<p class="empty small">None here.</p>'}</div>
      </div>
      ${dismissed.length ? `<details class="blocked" style="margin-top:12px"><summary>Dismissed · ${dismissed.length}</summary>${dismissed.map((x) => (x.kind === 'connect' ? connectCard(x) : multCard(x))).join('')}</details>` : ''}
      <p class="small muted">${d.runs_today} of ${d.runs_per_day} suggestion runs used today. Added items become to-dos due in a week, on your Dashboard.</p>` : ''}
    </div>`;
  const rerender = () => { const y = window.scrollY; renderConnections(main).then(() => window.scrollTo(0, y)); };
  main.querySelectorAll('[data-cx-track]').forEach((b) => { b.onclick = () => { cxTrack = b.dataset.cxTrack; rerender(); }; });
  main.querySelectorAll('[data-lead]').forEach((b) => {
    b.onclick = async () => {
      const [id, action] = b.dataset.lead.split(':');
      try {
        const r = await api(`/connections/${id}/${action}`, { method: 'POST' });
        if (action === 'add') toast('Added to your to-dos, due in a week.');
        rerender();
        return r;
      } catch (err) { toast(err.message); }
    };
  });
  main.querySelectorAll('[data-found]').forEach((b) => {
    b.onclick = () => openFoundForm(d.connects.find((x) => x.id === Number(b.dataset.found)));
  });
  $('#cx-suggest').onclick = async () => {
    const btn = $('#cx-suggest');
    btn.disabled = true;
    const stop = startThinking('Finding your people', ['Reading your tracks and open questions', 'Looking at the employers you\'re targeting',
      'Choosing who could answer your questions', 'Finding associations, events and programs'], 'Usually about 20 seconds.', 4500);
    try {
      const r = await api('/connections/suggest', { method: 'POST' });
      toast(r.outcome === 'ok' ? `${r.added} suggestions${r.blocked.length ? ` · ${r.blocked.length} left out by safety checks` : ''}.` : r.message);
    } catch (err) { toast(err.message); } finally { stop(); }
    rerender();
    refreshStatus().catch(() => {});
  };
}

/* ---------- AI usage & safety ---------- */

async function renderUsage(main) {
  const u = await api('/usage');
  const a = u.averages_ok_runs;
  const t = u.totals;
  const decided = t.approved + t.rejected;
  main.innerHTML = `
    <div class="page">
      <div class="page-head"><div><h1>AI usage &amp; safety</h1><p class="sub">Measured from real model calls. Prices: gpt-6-luna, $${u.prices_per_million.input.toFixed(2)} / $${u.prices_per_million.cached_input.toFixed(2)} cached / $${u.prices_per_million.output.toFixed(2)} output per 1M tokens.</p></div></div>
      <div class="kpis">
        <div class="card kpi"><span class="eyebrow">Analyses</span><b>${t.ok_runs}</b><span class="small muted">${t.runs - t.ok_runs} stopped or failed${t.scout_runs ? ` · ${t.scout_runs} Target Scout run${t.scout_runs > 1 ? 's' : ''}` : ''}</span></div>
        <div class="card kpi"><span class="eyebrow">Avg cost per analysis</span><b>${money(a.cost_usd)}</b><span class="small muted">${num(a.input_tokens)} in · ${num(a.cached_tokens)} cached · ${num(a.output_tokens)} out</span></div>
        <div class="card kpi"><span class="eyebrow">Suggestions approved</span><b>${decided ? Math.round((100 * t.approved) / decided) + '%' : '—'}</b><span class="small muted">${t.approved} approved · ${t.rejected} rejected</span></div>
        <div class="card kpi"><span class="eyebrow">Spent today</span><b>${money(u.spent_today_usd)}</b><span class="small muted">of $${u.daily_budget_usd.toFixed(2)} daily budget</span></div>
      </div>
      <div class="card" style="margin-bottom:20px">
        <div class="card-head"><h2>Run ledger</h2><span class="small muted">${t.blocked_by_validator} suggestions blocked by safety checks overall</span></div>
        <div style="overflow-x:auto"><table class="ledger">
          <thead><tr><th>When</th><th>Conversation</th><th>Outcome</th><th class="num">Input</th><th class="num">Cached</th><th class="num">Output</th><th class="num">Cost</th><th class="num">Time</th><th>Suggestions</th></tr></thead>
          <tbody>${u.runs.map((r) => `<tr>
            <td>${fmtDate(r.created_at)} ${new Date(r.created_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</td>
            <td>${esc(r.contact || '—')}</td>
            <td>${r.outcome === 'ok' ? '<span class="chip ok">ok</span>' : `<span class="chip ${r.outcome === 'blocked_filter' ? 'amber' : 'garnet'}">${esc(r.outcome.replace('_', ' '))}</span>`}</td>
            <td class="num">${num(r.input_tokens)}</td><td class="num">${num(r.cached_tokens)}</td><td class="num">${num(r.output_tokens)}</td>
            <td class="num">${money(r.cost_usd)}</td><td class="num">${(r.latency_ms / 1000).toFixed(1)} s</td>
            <td>${r.outcome !== 'ok' ? esc(r.error) : r.kind !== 'debrief'
              ? `${r.proposals_total - r.blocked_by_validator} ${{ scout: 'employers', pathfinder: 'directions', connections: 'people and resources' }[r.kind] || 'items'} suggested${r.blocked_by_validator ? ` · <b>${r.blocked_by_validator} blocked</b>` : ''}`
              : `${r.approved} approved · ${r.rejected} rejected${r.pending ? ` · ${r.pending} pending` : ''}${r.blocked_by_validator ? ` · <b>${r.blocked_by_validator} blocked</b>` : ''}`}</td>
          </tr>`).join('') || '<tr><td colspan="9" class="empty">No AI runs yet. Analyze a conversation to see measured tokens and cost here.</td></tr>'}</tbody>
        </table></div>
      </div>
      <h2 style="margin-bottom:12px">Defenses in place</h2>
      <div class="defenses">
        <div class="card defense"><h3>You approve every change</h3><p>The AI only suggests. Nothing is written until you approve that one suggestion. It cannot send messages.</p></div>
        <div class="card defense"><h3>Every suggestion must quote your notes</h3><p>The server checks that the supporting quote appears word for word in the notes, or the suggestion is blocked.</p></div>
        <div class="card defense"><h3>Notes are treated as untrusted</h3><p>Text that tries to give the AI orders is flagged, and suggestions based on it are blocked. Emails, links, phone numbers, secrets and bulk-sharing requests are blocked too.</p></div>
        <div class="card defense"><h3>Spending limits</h3><p>$${u.daily_budget_usd.toFixed(2)} per day, ${status?.max_runs_per_hour ?? 20} analyses per hour, 3 per conversation, one at a time, and a token cap per run.</p></div>
      </div>
    </div>`;
}

function renderPlaceholder(title, text) {
  $('#main').innerHTML = `<div class="page"><div class="page-head"><div><h1>${esc(title)}</h1></div></div>
    <div class="card placeholder"><h2>Not built yet</h2><p>${esc(text)}</p><p><a class="btn" href="#/network" style="margin-top:12px;text-decoration:none">Go to Networking</a></p></div></div>`;
}

/* ---------- start ---------- */

document.querySelectorAll('#nav a[data-icon]').forEach((a) => a.insertAdjacentHTML('afterbegin', `<span class="nav-icon">${icon(a.dataset.icon)}</span>`));
$('#menu-btn').innerHTML = icon('menu', 22);
$('#menu-btn').onclick = () => document.querySelector('.sidebar').classList.toggle('open');
document.querySelector('#nav').addEventListener('click', () => document.querySelector('.sidebar').classList.remove('open'));

$('#modal-close').onclick = closeModal;
$('#modal-bg').addEventListener('click', (e) => { if (e.target.id === 'modal-bg') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#modal-bg').hidden) closeModal(); });
window.addEventListener('hashchange', router);
(async () => {
  try { await refreshStatus(); } catch { /* router shows errors */ }
  router();
})();
