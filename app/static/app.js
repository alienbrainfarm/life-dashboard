/* =============================================================
   Life Dashboard — Frontend JS
   Fetches all data from the Flask REST API and renders the UI.
   All edits persist to TinyDB via the API.
   ============================================================= */

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────
const TODAY      = new Date(new Date().setHours(0, 0, 0, 0));
const MONTHS     = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const WEEK_DAYS  = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const SWATCHES   = ['#4f46e5','#0ea5e9','#10b981','#f59e0b','#ec4899','#8b5cf6','#ef4444','#64748b'];
const CAT_COLORS = { work:'#4f46e5', personal:'#ec4899', holiday:'#10b981', birthday:'#f59e0b' };

// ── Application state ────────────────────────────────────────────────────────
const STATE = {
  tasks:       [],
  events:      [],
  projects:    [],
  year_events: [],
  holidays:    [],
  recurring:   [],
  gcal_events: [],
  weekBgUrl:   null,  // today's AI-generated background URL, or null for SVG fallback
  modal: {
    table:     null,   // 'tasks' | 'events' | 'projects' | 'year_events' | 'recurring'
    id:        null,   // null = create, number = update
    defaults:  {},     // pre-fill values (e.g. default category)
  },
};

let projectChart = null;
let goalsChart   = null;

// ── API helpers ──────────────────────────────────────────────────────────────
async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

const apiGet    = (path)           => api('GET',    path);
const apiPost   = (path, body)     => api('POST',   path, body);
const apiPut    = (path, body)     => api('PUT',    path, body);
const apiDelete = (path)           => api('DELETE', path);

// ── Data loading ─────────────────────────────────────────────────────────────
async function loadAll() {
  const [tasks, events, projects, year_events, holidays, recurring, gcal_events] = await Promise.all([
    apiGet('/api/tasks'),
    apiGet('/api/events'),
    apiGet('/api/projects'),
    apiGet('/api/year_events'),
    apiGet('/api/holidays'),
    apiGet('/api/recurring'),
    apiGet('/api/gcal_events'),
  ]);
  STATE.tasks        = tasks;
  STATE.events       = events;
  STATE.projects     = projects;
  STATE.year_events  = year_events;
  STATE.holidays     = holidays;
  STATE.recurring    = recurring;
  STATE.gcal_events  = gcal_events;
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function fmtDate(d) {
  const dt = new Date(d + 'T00:00:00');
  return `${MONTHS[dt.getMonth()]} ${dt.getDate()}`;
}

function parseDate(s) {
  return new Date(s + 'T00:00:00');
}

function startOfWeek(d) {
  const sd = new Date(d);
  sd.setDate(d.getDate() - d.getDay()); // Sunday
  return sd;
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() &&
         a.getMonth()    === b.getMonth()    &&
         a.getDate()     === b.getDate();
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── KPI bar ──────────────────────────────────────────────────────────────────
function updateKPIs() {
  const weekEnd = new Date(TODAY);
  weekEnd.setDate(TODAY.getDate() + 7);

  const tasksDue = STATE.tasks.filter(t => !t.done && parseDate(t.due) <= weekEnd).length;
  const doneCnt  = STATE.tasks.filter(t => t.done).length;

  const next14 = new Date(TODAY);
  next14.setDate(TODAY.getDate() + 14);
  const evCnt = STATE.events.filter(e => {
    const d = parseDate(e.date);
    return d >= TODAY && d <= next14;
  }).length;

  const projActive = STATE.projects.filter(p => p.pct < 100).length;

  document.getElementById('kpi-tasks-due').textContent = tasksDue;
  document.getElementById('kpi-done').textContent      = doneCnt;
  document.getElementById('kpi-events').textContent    = evCnt;
  document.getElementById('kpi-projects').textContent  = projActive;
}

// ── Today display ─────────────────────────────────────────────────────────────
function renderTodayDisplay() {
  const opts = { weekday:'long', year:'numeric', month:'long', day:'numeric' };
  document.getElementById('today-display').textContent =
    TODAY.toLocaleDateString('en-US', opts);
}

// ── Week view (background image + day card strip) ─────────────────────────────
// Day header colours keyed by getDay() (0=Sun … 6=Sat)
const DAY_COLORS = ['#8b5cf6','#4f46e5','#e85d5d','#0ea5e9','#f59e0b','#10b981','#ec4899'];

function renderWeekPath() {
  const el = document.getElementById('week-grid');

  // 7 days starting today
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(TODAY);
    d.setDate(TODAY.getDate() + i);
    return d;
  });

  // ── Background ────────────────────────────────────────────────────────────
  let bgHtml;
  if (STATE.weekBgUrl) {
    bgHtml = `<div class="week-bg" style="background-image:url(${STATE.weekBgUrl})"></div>`;
  } else {
    // Static SVG forest (no signs)
    bgHtml = `
<div class="week-bg" style="padding:0">
<svg viewBox="0 0 900 520" xmlns="http://www.w3.org/2000/svg"
     style="display:block;width:100%;height:100%;object-fit:cover" aria-hidden="true">
  <defs>
    <linearGradient id="wps-sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#3e7a55"/>
      <stop offset="52%"  stop-color="#7ec47a"/>
      <stop offset="100%" stop-color="#c2ea92"/>
    </linearGradient>
    <radialGradient id="wps-glow" cx="50%" cy="19%" r="34%">
      <stop offset="0%"   stop-color="#fffdcc" stop-opacity="1"/>
      <stop offset="45%"  stop-color="#fde96a" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#c2ea92" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="wps-path" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"   stop-color="#a87840"/>
      <stop offset="55%"  stop-color="#bf9550"/>
      <stop offset="100%" stop-color="#d2b070"/>
    </linearGradient>
    <linearGradient id="wps-ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#4a8840"/>
      <stop offset="100%" stop-color="#255825"/>
    </linearGradient>
  </defs>
  <rect width="900" height="520" fill="url(#wps-sky)"/>
  <ellipse cx="450" cy="100" rx="200" ry="115" fill="url(#wps-glow)"/>
  <path d="M 0 292 Q 230 278 450 282 Q 670 278 900 290 L 900 520 L 0 520 Z" fill="url(#wps-ground)"/>
  <g fill="#2e6225" opacity="0.52">
    <ellipse cx="192" cy="270" rx="48" ry="31"/><ellipse cx="266" cy="262" rx="40" ry="26"/>
    <ellipse cx="338" cy="267" rx="27" ry="18"/><ellipse cx="560" cy="264" rx="29" ry="20"/>
    <ellipse cx="632" cy="260" rx="43" ry="28"/><ellipse cx="706" cy="268" rx="37" ry="24"/>
  </g>
  <path d="M 282 520 C 275 458, 292 385, 342 320 C 382 266, 375 196, 433 108 L 467 108
           C 525 196, 518 266, 558 320 C 608 385, 625 458, 618 520 Z" fill="url(#wps-path)"/>
  <rect x="175" y="352" width="20" height="168" fill="#5c2a08"/>
  <ellipse cx="185" cy="292" rx="76" ry="82" fill="#27601e"/>
  <ellipse cx="150" cy="318" rx="52" ry="58" fill="#2f7825"/>
  <ellipse cx="210" cy="270" rx="58" ry="66" fill="#338a28"/>
  <rect x="705" y="358" width="20" height="162" fill="#5c2a08"/>
  <ellipse cx="715" cy="298" rx="72" ry="78" fill="#27601e"/>
  <ellipse cx="748" cy="325" rx="50" ry="55" fill="#2f7825"/>
  <ellipse cx="680" cy="276" rx="55" ry="63" fill="#338a28"/>
  <rect x="8" y="280" width="52" height="240" fill="#461a06" rx="6"/>
  <ellipse cx="74"  cy="188" rx="136" ry="148" fill="#1b4a15"/>
  <ellipse cx="20"  cy="226" rx="90"  ry="98"  fill="#225818"/>
  <ellipse cx="130" cy="170" rx="114" ry="126" fill="#26681c"/>
  <ellipse cx="66"  cy="143" rx="107" ry="118" fill="#2a701e"/>
  <rect x="840" y="276" width="52" height="244" fill="#461a06" rx="6"/>
  <ellipse cx="826" cy="186" rx="132" ry="145" fill="#1b4a15"/>
  <ellipse cx="878" cy="223" rx="88"  ry="96"  fill="#225818"/>
  <ellipse cx="770" cy="168" rx="110" ry="124" fill="#26681c"/>
  <ellipse cx="832" cy="141" rx="104" ry="116" fill="#2a701e"/>
</svg>
</div>`;
  }

  // ── Day card strip ────────────────────────────────────────────────────────
  const stripCards = days.map((d, i) => {
    const isToday = i === 0;
    const color   = DAY_COLORS[d.getDay()];
    const dayEvents = STATE.events.filter(e => sameDay(parseDate(e.date), d));
    const dayGcal   = STATE.gcal_events.filter(e => sameDay(parseDate(e.date), d));
    const dayTasks  = STATE.tasks.filter(t => !t.done && sameDay(parseDate(t.due), d));
    const items     = [...dayEvents.map(e => e.title), ...dayGcal.map(e => e.title), ...dayTasks.map(t => t.text)].slice(0, 3);

    const itemsHtml = items.map(txt => {
      const label = txt.length > 16 ? txt.slice(0, 15) + '\u2026' : txt;
      return `<div class="day-card-item">${esc(label)}</div>`;
    }).join('');

    return `
<div class="day-card${isToday ? ' today' : ''}">
  <div class="day-card-header" style="background:${color}">
    <span class="day-card-name">${WEEK_DAYS[d.getDay()]}</span>
  </div>
  <div class="day-card-body">
    <div class="day-card-date">${d.getDate()}</div>
    ${itemsHtml}
  </div>
</div>`;
  }).join('');

  el.innerHTML = bgHtml + '<div class="week-strip">' + stripCards + '</div>';
}

// ── Upcoming events ──────────────────────────────────────────────────────────

function nextOccurrence(month, day) {
  const thisYear = new Date(TODAY.getFullYear(), month - 1, day);
  return thisYear >= TODAY ? thisYear : new Date(TODAY.getFullYear() + 1, month - 1, day);
}

function renderUpcomingEvents() {
  const next14 = new Date(TODAY);
  next14.setDate(TODAY.getDate() + 14);

  // Regular events
  const evItems = STATE.events
    .map(e => ({ ...e, dt: parseDate(e.date), _type: 'event' }))
    .filter(e => e.dt >= TODAY && e.dt <= next14);

  // Dutch holidays
  const holItems = STATE.holidays
    .map(h => ({ ...h, dt: parseDate(h.date), _type: 'holiday', time: '' }))
    .filter(h => h.dt >= TODAY && h.dt <= next14);

  // Recurring events (birthdays etc.) — compute next occurrence
  const recItems = STATE.recurring
    .map(r => {
      const dt = nextOccurrence(r.month, r.day);
      return { ...r, dt, date: dt.toISOString().slice(0, 10), time: '', _type: 'recurring' };
    })
    .filter(r => r.dt >= TODAY && r.dt <= next14);

  // Google Calendar events
  const gcalItems = STATE.gcal_events
    .map(e => ({ ...e, dt: parseDate(e.date), _type: 'gcal' }))
    .filter(e => e.dt >= TODAY && e.dt <= next14);

  const all = [...evItems, ...holItems, ...recItems, ...gcalItems].sort((a, b) => a.dt - b.dt);

  const html = all.map(e => {
    const color = CAT_COLORS[e.cat] || 'var(--muted)';
    const label = e.cat === 'holiday' ? '🏖 Holiday'
                : e.cat === 'birthday' ? '🎂 Birthday'
                : e._type === 'gcal' ? '📅 GCal'
                : e.cat;
    const meta  = e.time ? `${esc(e.time)} · ` : '';
    const actions = e._type === 'holiday'
      ? `<button class="icon-btn delete" onclick="deleteItem('holidays',${e.id})" title="Remove">🗑</button>`
      : e._type === 'recurring'
      ? `<button class="icon-btn" onclick="openModal('recurring',${e.id})" title="Edit">✏️</button>
         <button class="icon-btn delete" onclick="deleteItem('recurring',${e.id})" title="Delete">🗑</button>`
      : e._type === 'gcal'
      ? ''
      : `<button class="icon-btn" onclick="openModal('events',${e.id})" title="Edit">✏️</button>
         <button class="icon-btn delete" onclick="deleteItem('events',${e.id})" title="Delete">🗑</button>`;

    return `
    <div class="event-item">
      <div class="event-date">
        <div class="month">${MONTHS[e.dt.getMonth()]}</div>
        <div class="day">${e.dt.getDate()}</div>
      </div>
      <div class="event-body">
        <div class="title">${esc(e.title)}</div>
        <div class="meta">${meta}<span style="color:${color};font-weight:600">${label}</span></div>
      </div>
      <div class="task-actions">${actions}</div>
    </div>`;
  }).join('') || '<p style="color:var(--muted);font-size:.85rem">No events in the next 14 days.</p>';

  document.getElementById('upcoming-events').innerHTML = html;
}

// ── Week work tasks ───────────────────────────────────────────────────────────
function renderWeekWorkTasks() {
  const weekEnd = new Date(TODAY);
  weekEnd.setDate(TODAY.getDate() + 7);

  const items = STATE.tasks
    .filter(t => t.cat === 'work' && !t.done && parseDate(t.due) <= weekEnd)
    .sort((a, b) => parseDate(a.due) - parseDate(b.due));

  document.getElementById('week-work-tasks').innerHTML =
    items.length
      ? items.map(t => taskHTML(t, true)).join('')
      : '<li style="color:var(--muted);font-size:.85rem;padding:8px">All clear! 🎉</li>';
}

// ── Task lists ────────────────────────────────────────────────────────────────
function taskHTML(t, compact = false) {
  const editBtn   = `<button class="icon-btn"        onclick="openModal('tasks',${t.id})" title="Edit">✏️</button>`;
  const deleteBtn = `<button class="icon-btn delete" onclick="deleteItem('tasks',${t.id})"  title="Delete">🗑</button>`;
  return `
    <li class="task-item${t.done ? ' done' : ''}" id="task-${t.id}">
      <input type="checkbox" ${t.done ? 'checked' : ''} onchange="toggleTask(${t.id})"/>
      <span class="task-text">${esc(t.text)}</span>
      <span class="tag ${esc(t.priority)}">${esc(t.priority)}</span>
      <span class="due">${fmtDate(t.due)}</span>
      ${compact ? '' : `<div class="task-actions">${editBtn}${deleteBtn}</div>`}
    </li>`;
}

function renderTaskLists() {
  ['work', 'personal'].forEach(cat => {
    const filtered = STATE.tasks.filter(t => t.cat === cat);
    const elId = `list-${cat}`;
    document.getElementById(elId).innerHTML =
      filtered.map(t => taskHTML(t)).join('') ||
      `<li style="color:var(--muted);font-size:.85rem;padding:8px">No ${cat} tasks yet.</li>`;
  });
}

async function toggleTask(id) {
  const t = STATE.tasks.find(t => t.id === id);
  if (!t) return;
  t.done = !t.done;
  await apiPut(`/api/tasks/${id}`, t);
  renderAll();
}

// ── Projects ──────────────────────────────────────────────────────────────────
function renderProjects() {
  const el = document.getElementById('project-list');
  el.innerHTML = STATE.projects.map(p => `
    <div class="project-item">
      <div class="project-header">
        <span class="project-name">${esc(p.name)}</span>
        <div class="project-meta">
          <span>${esc(p.pct)}% · ${esc(p.deadline)}</span>
          <button class="icon-btn"        onclick="openModal('projects',${p.id})" title="Edit">✏️</button>
          <button class="icon-btn delete" onclick="deleteItem('projects',${p.id})" title="Delete">🗑</button>
        </div>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" style="width:${p.pct}%;background:${esc(p.color)}"></div>
      </div>
    </div>`).join('') || '<p style="color:var(--muted);font-size:.85rem">No projects yet.</p>';
}

// ── Year timeline ─────────────────────────────────────────────────────────────
function renderYearTimeline() {
  const el = document.getElementById('year-timeline');
  const quarters = [...new Set(STATE.year_events.map(e => e.q))];

  el.innerHTML = quarters.map(q => {
    const events = STATE.year_events.filter(e => e.q === q);
    return `
      <div class="year-quarter">
        <div class="quarter-label">${esc(q)}</div>
        <div class="quarter-events">
          ${events.map(e => `
            <div class="year-event">
              <div class="year-event-dot" style="background:${esc(e.color)}"></div>
              <div class="year-event-info">
                <div class="year-event-title">${esc(e.title)}</div>
                <div class="year-event-meta">${esc(e.date)}</div>
              </div>
              <span class="year-event-cat tag ${esc(e.cat)}">${esc(e.cat)}</span>
              <div class="task-actions">
                <button class="icon-btn"        onclick="openModal('year_events',${e.id})" title="Edit">✏️</button>
                <button class="icon-btn delete" onclick="deleteItem('year_events',${e.id})" title="Delete">🗑</button>
              </div>
            </div>`).join('')}
        </div>
      </div>`;
  }).join('') || '<p style="color:var(--muted);font-size:.85rem">No milestones yet.</p>';
}

// ── Charts ────────────────────────────────────────────────────────────────────
function initCharts() {
  // Project focus doughnut
  const ctx1 = document.getElementById('chart-projects');
  if (ctx1) {
    if (projectChart) projectChart.destroy();
    projectChart = new Chart(ctx1, {
      type: 'doughnut',
      data: {
        labels: STATE.projects.map(p => p.name),
        datasets: [{
          data: STATE.projects.map(p => Math.max(5, 100 - p.pct + 10)),
          backgroundColor: STATE.projects.map(p => p.color),
          borderWidth: 2,
          borderColor: '#fff',
        }],
      },
      options: {
        plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } },
        cutout: '60%',
      },
    });
  }

  // Goals horizontal bar
  const ctx2 = document.getElementById('chart-goals');
  if (ctx2) {
    if (goalsChart) goalsChart.destroy();
    goalsChart = new Chart(ctx2, {
      type: 'bar',
      data: {
        labels: STATE.projects.map(p => p.name.length > 22 ? p.name.slice(0, 22) + '…' : p.name),
        datasets: [{
          label: '% Complete',
          data: STATE.projects.map(p => p.pct),
          backgroundColor: STATE.projects.map(p => p.color + 'cc'),
          borderColor:      STATE.projects.map(p => p.color),
          borderWidth: 2,
          borderRadius: 6,
        }],
      },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: {
          x: { max: 100, grid: { color: '#f0f2f5' } },
          y: { grid: { display: false } },
        },
      },
    });
  }
}

// ── Render all sections ───────────────────────────────────────────────────────
function renderAll() {
  renderWeekPath();
  renderUpcomingEvents();
  renderWeekWorkTasks();
  renderTaskLists();
  renderProjects();
  renderYearTimeline();
  initCharts();
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deleteItem(table, id) {
  if (!confirm('Delete this item?')) return;
  await apiDelete(`/api/${table}/${id}`);
  STATE[table] = STATE[table].filter(x => x.id !== id);
  renderAll();
}

// ── Modal ─────────────────────────────────────────────────────────────────────

const MODAL_CONFIGS = {
  tasks: {
    title:  (id) => id ? 'Edit Task' : 'Add Task',
    fields: (data, defaults) => `
      <div class="form-group">
        <label>Task description</label>
        <textarea name="text" required>${esc(data.text || '')}</textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Category</label>
          <select name="cat">
            <option value="work"     ${(data.cat || defaults.cat) === 'work'     ? 'selected' : ''}>Work</option>
            <option value="personal" ${(data.cat || defaults.cat) === 'personal' ? 'selected' : ''}>Personal</option>
          </select>
        </div>
        <div class="form-group">
          <label>Priority</label>
          <select name="priority">
            <option value="high" ${data.priority === 'high' ? 'selected' : ''}>High</option>
            <option value="med"  ${data.priority === 'med'  ? 'selected' : ''}>Medium</option>
            <option value="low"  ${data.priority === 'low'  ? 'selected' : ''}>Low</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Due date</label>
        <input type="date" name="due" value="${esc(data.due || '')}" required/>
      </div>
      <input type="hidden" name="done" value="${data.done ? 'true' : 'false'}"/>`,
    parse: (f) => ({
      text:     f.get('text'),
      cat:      f.get('cat'),
      priority: f.get('priority'),
      due:      f.get('due'),
      done:     f.get('done') === 'true',
    }),
  },

  events: {
    title:  (id) => id ? 'Edit Event' : 'Add Event',
    fields: (data) => `
      <div class="form-group">
        <label>Event title</label>
        <input type="text" name="title" value="${esc(data.title || '')}" required/>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Date</label>
          <input type="date" name="date" value="${esc(data.date || '')}" required/>
        </div>
        <div class="form-group">
          <label>Time</label>
          <input type="text" name="time" value="${esc(data.time || '')}" placeholder="e.g. 2:00 PM"/>
        </div>
      </div>
      <div class="form-group">
        <label>Category</label>
        <select name="cat">
          <option value="work"     ${data.cat === 'work'     ? 'selected' : ''}>Work</option>
          <option value="personal" ${data.cat === 'personal' ? 'selected' : ''}>Personal</option>
        </select>
      </div>`,
    parse: (f) => ({
      title: f.get('title'),
      date:  f.get('date'),
      time:  f.get('time') || 'All day',
      cat:   f.get('cat'),
    }),
  },

  projects: {
    title:  (id) => id ? 'Edit Project' : 'Add Project',
    fields: (data) => `
      <div class="form-group">
        <label>Project name</label>
        <input type="text" name="name" value="${esc(data.name || '')}" required/>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Progress (%)</label>
          <input type="number" name="pct" min="0" max="100" value="${esc(data.pct ?? 0)}" required/>
        </div>
        <div class="form-group">
          <label>Deadline</label>
          <input type="text" name="deadline" value="${esc(data.deadline || '')}" placeholder="e.g. Jun 2026"/>
        </div>
      </div>
      <div class="form-group">
        <label>Category</label>
        <select name="cat">
          <option value="work"     ${data.cat === 'work'     ? 'selected' : ''}>Work</option>
          <option value="personal" ${data.cat === 'personal' ? 'selected' : ''}>Personal</option>
        </select>
      </div>
      <div class="form-group">
        <label>Colour</label>
        <div class="swatch-row" id="swatch-row">
          ${SWATCHES.map(c => `<div class="swatch${c === (data.color || SWATCHES[0]) ? ' selected' : ''}"
            style="background:${c}" data-color="${c}" onclick="selectSwatch(this)"></div>`).join('')}
        </div>
        <input type="hidden" name="color" id="color-input" value="${esc(data.color || SWATCHES[0])}"/>
      </div>`,
    parse: (f) => ({
      name:     f.get('name'),
      pct:      parseInt(f.get('pct'), 10),
      deadline: f.get('deadline'),
      cat:      f.get('cat'),
      color:    f.get('color'),
    }),
  },

  year_events: {
    title:  (id) => id ? 'Edit Milestone' : 'Add Milestone',
    fields: (data) => `
      <div class="form-group">
        <label>Milestone title</label>
        <input type="text" name="title" value="${esc(data.title || '')}" required/>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Quarter / Period</label>
          <select name="q">
            ${['Q1 2026 (Jan–Mar)','Q2 2026 (Apr–Jun)','Q3 2026 (Jul–Sep)','Q4 2026 (Oct–Dec)','2027 Horizon']
              .map(q => `<option value="${esc(q)}" ${data.q === q ? 'selected' : ''}>${esc(q)}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label>Approx. date</label>
          <input type="text" name="date" value="${esc(data.date || '')}" placeholder="e.g. Apr 2026"/>
        </div>
      </div>
      <div class="form-group">
        <label>Category</label>
        <select name="cat">
          <option value="work"     ${data.cat === 'work'     ? 'selected' : ''}>Work</option>
          <option value="personal" ${data.cat === 'personal' ? 'selected' : ''}>Personal</option>
        </select>
      </div>
      <div class="form-group">
        <label>Colour</label>
        <div class="swatch-row">
          ${SWATCHES.map(c => `<div class="swatch${c === (data.color || SWATCHES[0]) ? ' selected' : ''}"
            style="background:${c}" data-color="${c}" onclick="selectSwatch(this)"></div>`).join('')}
        </div>
        <input type="hidden" name="color" id="color-input" value="${esc(data.color || SWATCHES[0])}"/>
      </div>`,
    parse: (f) => ({
      title: f.get('title'),
      q:     f.get('q'),
      date:  f.get('date'),
      cat:   f.get('cat'),
      color: f.get('color'),
    }),
  },

  recurring: {
    title:  (id) => id ? 'Edit Recurring Event' : 'Add Recurring Event',
    fields: (data) => `
      <div class="form-group">
        <label>Title</label>
        <input type="text" name="title" value="${esc(data.title || '')}" required placeholder="e.g. Jan's Birthday"/>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Month</label>
          <select name="month">
            ${['January','February','March','April','May','June','July','August','September','October','November','December']
              .map((m, i) => `<option value="${i+1}" ${(data.month === i+1) ? 'selected' : ''}>${m}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label>Day</label>
          <input type="number" name="day" min="1" max="31" value="${esc(data.day || '')}" required/>
        </div>
      </div>
      <div class="form-group">
        <label>Category</label>
        <select name="cat">
          <option value="birthday" ${(data.cat || 'birthday') === 'birthday' ? 'selected' : ''}>Birthday</option>
          <option value="personal" ${data.cat === 'personal' ? 'selected' : ''}>Personal</option>
          <option value="work"     ${data.cat === 'work'     ? 'selected' : ''}>Work</option>
        </select>
      </div>`,
    parse: (f) => ({
      title: f.get('title'),
      month: parseInt(f.get('month'), 10),
      day:   parseInt(f.get('day'),   10),
      cat:   f.get('cat'),
    }),
  },
};

async function syncHolidays() {
  try {
    const res = await api('POST', '/api/holidays/sync');
    STATE.holidays = await apiGet('/api/holidays');
    renderUpcomingEvents();
    alert(`Synced ${res.synced} Dutch public holidays (${res.years.join(' & ')}).`);
  } catch (e) {
    alert('Failed to sync holidays: ' + e.message);
  }
}

async function syncGcal() {
  try {
    const res = await api('POST', '/api/gcal/sync');
    STATE.gcal_events = await apiGet('/api/gcal_events');
    renderUpcomingEvents();
    renderWeekPath();
    alert(`Synced ${res.synced} events from Google Calendar.`);
  } catch (e) {
    alert('Failed to sync Google Calendar: ' + e.message);
  }
}

function selectSwatch(el) {
  document.querySelectorAll('#modal-body .swatch').forEach(s => s.classList.remove('selected'));
  el.classList.add('selected');
  const colorInput = document.getElementById('color-input');
  if (colorInput) colorInput.value = el.dataset.color;
}

function openModal(table, id = null, defaultCat = null) {
  STATE.modal.table    = table;
  STATE.modal.id       = id;
  STATE.modal.defaults = defaultCat ? { cat: defaultCat } : {};

  const cfg     = MODAL_CONFIGS[table];
  const existing = id ? STATE[table].find(x => x.id === id) : {};

  document.getElementById('modal-title').textContent = cfg.title(id);
  document.getElementById('modal-body').innerHTML    = cfg.fields(existing || {}, STATE.modal.defaults);
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  STATE.modal.table = STATE.modal.id = null;
}

function closeModalOutside(e) {
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}

async function saveModal() {
  const { table, id } = STATE.modal;
  const cfg  = MODAL_CONFIGS[table];
  const form = document.getElementById('modal-body');
  const fd   = new FormData();

  form.querySelectorAll('[name]').forEach(el => {
    if (el.type === 'checkbox') fd.append(el.name, el.checked ? 'true' : 'false');
    else fd.append(el.name, el.value);
  });

  // Basic validation
  const requiredFields = form.querySelectorAll('[required]');
  for (const f of requiredFields) {
    if (!f.value.trim()) { f.focus(); f.style.borderColor = 'var(--red)'; return; }
  }

  const payload = cfg.parse(fd);

  if (id) {
    const updated = await apiPut(`/api/${table}/${id}`, payload);
    const idx = STATE[table].findIndex(x => x.id === id);
    if (idx > -1) STATE[table][idx] = updated;
  } else {
    const created = await apiPost(`/api/${table}`, payload);
    STATE[table].push(created);
  }

  closeModal();
  renderAll();
}

// ── Tab navigation ─────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('nav.tabs button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

// ── AI background image ───────────────────────────────────────────────────────
async function loadBackgroundImage() {
  // BG_BUCKET is injected by the Flask template (see index.html)
  if (!BG_BUCKET) return;
  const today = [TODAY.getFullYear(), String(TODAY.getMonth()+1).padStart(2,'0'), String(TODAY.getDate()).padStart(2,'0')].join('-');
  const url = `https://storage.googleapis.com/${BG_BUCKET}/backgrounds/${today}.png`;
  try {
    const res = await fetch(url, { method: 'HEAD' });
    if (res.ok) {
      STATE.weekBgUrl = url;
      renderWeekPath();
    }
  } catch (_) { /* SVG fallback */ }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  renderTodayDisplay();
  initTabs();
  try {
    await loadAll();
    renderAll();
    loadBackgroundImage();  // async, updates week-grid when ready
  } catch (err) {
    console.error('Failed to load data:', err);
  }
});
