/* Academic Dashboard — vanilla JS frontend. No build step. */

const TYPE_COLORS = {
  lecture: '--t-lecture', lab: '--t-lab', tutorial: '--t-tutorial',
  assignment: '--t-assignment', quiz: '--t-quiz', midterm: '--t-midterm',
  exam: '--t-exam', project: '--t-project', milestone: '--t-milestone',
  presentation: '--t-presentation', report: '--t-report',
  participation: '--t-participation', holiday: '--t-holiday', other: '--t-other',
};
const TYPE_LABELS = {
  lecture: 'Lecture', lab: 'Lab', tutorial: 'Tutorial', assignment: 'Assignment',
  quiz: 'Quiz', midterm: 'Midterm', exam: 'Exam', project: 'Project',
  milestone: 'Milestone', presentation: 'Presentation', report: 'Report',
  participation: 'Participation', holiday: 'Break', other: 'Other',
};
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

const state = {
  view: 'overview',
  events: [],        // occurrence rows from /api/events (dated deliverables)
  allEvents: [],     // unfiltered
  courses: [],
  summary: null,
  today: null,       // Date
  filters: { course: '', type: '', status: '', from: '', to: '' },
  calMode: 'month',
  calCursor: null,   // Date anchoring the calendar
  selectedCourse: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const typeColor = (t) => cssVar(TYPE_COLORS[t] || '--t-other');

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

/* ---------- date helpers ---------- */
const toISO = (d) => d.toISOString().slice(0, 10);
function parseISO(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
function fmtTime(t) {
  if (!t) return '';
  const [h, m] = t.split(':').map(Number);
  const ap = h >= 12 ? 'PM' : 'AM';
  const hh = ((h + 11) % 12) + 1;
  return `${hh}:${String(m).padStart(2, '0')} ${ap}`;
}
function daysBetween(a, b) { return Math.round((b - a) / 86400000); }

/* ---------- data load ---------- */
async function loadAll() {
  const todayParam = new URLSearchParams(location.search).get('today');
  const q = todayParam ? `?today=${todayParam}` : '';
  const [summary, courses, events] = await Promise.all([
    api('/api/summary' + q),
    api('/api/courses'),
    api('/api/events'),
  ]);
  state.summary = summary;
  state.today = parseISO(summary.today);
  state.courses = courses;
  state.allEvents = events;
  if (!state.calCursor) state.calCursor = new Date(state.today);
  populateFilterOptions();
  applyFilters();
}

function populateFilterOptions() {
  const fCourse = $('#f-course');
  const mCourse = $('#m-course');
  const courseOpts = state.courses.map(c => `<option value="${c.code}">${c.code} — ${c.name}</option>`).join('');
  fCourse.innerHTML = '<option value="">All courses</option>' + courseOpts;
  mCourse.innerHTML = '<option value="">(none / general)</option>' + courseOpts;
  const types = [...new Set(state.allEvents.map(e => e.type))].sort();
  $('#f-type').innerHTML = '<option value="">All types</option>' +
    types.map(t => `<option value="${t}">${TYPE_LABELS[t] || t}</option>`).join('');
  // legend
  $('#legend').innerHTML = '';
  ['assignment','quiz','midterm','exam','project','milestone','presentation','report','participation','holiday']
    .forEach(t => $('#legend').append(
      el('div', { class: 'legend-item' },
        el('span', { class: 'legend-dot', style: `background:${typeColor(t)}` }),
        TYPE_LABELS[t])));
}

function applyFilters() {
  const f = state.filters;
  state.events = state.allEvents.filter(e => {
    if (f.course && e.course_code !== f.course) return false;
    if (f.type && e.type !== f.type) return false;
    if (f.status) {
      if (f.status === 'conflict' && e.status !== 'conflict') return false;
      if (f.status !== 'conflict' && (e.occ_status || e.status) !== f.status) return false;
    }
    if (f.from && (!e.date || e.date < f.from)) return false;
    if (f.to && (!e.date || e.date > f.to)) return false;
    return true;
  });
  render();
}

/* ---------- rendering dispatch ---------- */
function render() {
  $('#page-title').textContent = { overview: 'Overview', calendar: 'Calendar', deadlines: 'Upcoming deadlines', courses: 'Courses' }[state.view];
  const showFilters = state.view !== 'overview';
  $('#filters').style.visibility = showFilters ? 'visible' : 'hidden';
  const v = $('#view'); v.innerHTML = '';
  if (state.view === 'overview') renderOverview(v);
  else if (state.view === 'calendar') renderCalendar(v);
  else if (state.view === 'deadlines') renderDeadlines(v);
  else if (state.view === 'courses') renderCourses(v);
}

/* ---------- Overview ---------- */
function statusBadge(status) {
  const label = { confirmed: 'Confirmed', tentative: 'Tentative', tbd: 'TBD', conflict: 'Conflict' }[status] || status;
  return el('span', { class: `badge badge-${status}` }, label);
}

function renderOverview(root) {
  const s = state.summary;
  const todayStr = state.today.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  root.append(el('div', { class: 'muted', style: 'margin-bottom:14px' }, `Today is ${todayStr}`));

  if (s.conflicts.length) {
    root.append(el('div', { class: 'banner banner-warn' },
      el('div', {},
        el('b', {}, `${s.conflicts.length} date conflict${s.conflicts.length > 1 ? 's' : ''} found across your outlines. `),
        'The sources disagree on these dates — they are shown but not resolved automatically. ',
        ...s.conflicts.map(c => el('a', { href: '#', style: 'color:var(--primary);margin-right:8px', onclick: (e) => { e.preventDefault(); openEventDrawer(c.id); } }, `${c.course_code} ${c.title}`)))));
  }
  if (s.tbd_count) {
    root.append(el('div', { class: 'banner banner-info' },
      el('div', {}, el('b', {}, `${s.tbd_count} assessment${s.tbd_count > 1 ? 's' : ''} without a firm date. `),
        'These are marked TBD/tentative in the outlines (e.g. final exams to be set by the Registrar).')));
  }

  const cards = el('div', { class: 'grid cards' });
  const stat = (num, label, cls = '') => el('div', { class: 'card stat-card' },
    el('div', { class: 'stat-num ' + cls }, String(num)), el('div', { class: 'stat-label' }, label));
  cards.append(
    stat(s.due_today.length, 'Due today', s.due_today.length ? 'text-warn' : ''),
    stat(s.next_7_days.length, 'Next 7 days'),
    stat(s.next_30_days.length, 'Next 30 days'),
    stat(s.upcoming_count, 'Upcoming items'),
    stat(s.overdue.length, 'Overdue'),
  );
  root.append(cards);

  // Next major assessment
  root.append(el('div', { class: 'section-title' }, 'Next major assessment'));
  if (s.next_major) {
    root.append(deadlineRow(s.next_major));
  } else {
    root.append(el('div', { class: 'card muted' }, 'No dated major assessments ahead.'));
  }

  // Due today / next 7
  root.append(el('div', { class: 'section-title' }, 'Coming up (next 7 days)'));
  const seven = dedupById([...s.due_today, ...s.next_7_days]);
  if (seven.length) root.append(el('div', { class: 'deadline-list' }, ...seven.map(deadlineRow)));
  else root.append(el('div', { class: 'card muted' }, 'Nothing due in the next 7 days.'));
}

function dedupById(list) {
  const seen = new Set(); const out = [];
  for (const e of list) { const k = e.id + (e.date || ''); if (seen.has(k)) continue; seen.add(k); out.push(e); }
  return out.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
}

/* ---------- Deadline row (shared) ---------- */
function deadlineRow(e) {
  const hasDate = !!e.date;
  const d = hasDate ? parseISO(e.date) : null;
  const diff = hasDate ? daysBetween(state.today, d) : null;
  const overdue = hasDate && diff < 0;

  const dateBox = hasDate
    ? el('div', { class: 'd-date' },
        el('div', { class: 'dow' }, DOW[d.getDay()]),
        el('div', { class: 'dnum' }, String(d.getDate())),
        el('div', { class: 'dmon' }, MONTHS[d.getMonth()].slice(0, 3)))
    : el('div', { class: 'd-date' }, el('div', { class: 'dnum', style: 'font-size:14px' }, 'TBD'));

  let daysLabel = '';
  let daysCls = 'days-left';
  if (hasDate) {
    if (diff === 0) { daysLabel = 'Today'; daysCls += ' today'; }
    else if (diff < 0) { daysLabel = `${-diff}d overdue`; daysCls += ' past'; }
    else if (diff <= 7) { daysLabel = `in ${diff}d`; daysCls += ' soon'; }
    else { daysLabel = `in ${diff}d`; }
  } else { daysLabel = 'no date'; }

  const meta = el('div', { class: 'd-meta' },
    el('span', {}, chip(e.type)),
    e.time ? el('span', {}, '🕑 ' + fmtTime(e.time)) : null,
    e.location ? el('span', {}, '📍 ' + e.location) : null,
    e.weight ? el('span', {}, 'Weight: ' + e.weight) : null,
  );

  const right = el('div', { class: 'd-right' },
    statusBadge(e.status),
    e.origin === 'manual' ? el('span', { class: 'badge badge-manual' }, 'Manual') : null,
    el('div', { class: daysCls }, daysLabel));

  const row = el('div', { class: 'deadline' + (overdue ? ' overdue' : ''), onclick: () => openEventDrawer(e.id, e) },
    dateBox,
    el('div', { class: 'd-main' },
      el('div', { class: 'd-title' }, `${e.course_code || 'General'} — ${e.title}`),
      meta),
    right);
  row.style.borderLeftColor = overdue ? cssVar('--overdue') : typeColor(e.type);
  return row;
}

function chip(type) {
  return el('span', { class: 'chip' },
    el('span', { class: 'dot', style: `background:${typeColor(type)}` }),
    TYPE_LABELS[type] || type);
}

/* ---------- Deadlines view ---------- */
function renderDeadlines(root) {
  const dated = state.events.filter(e => e.date && e.type !== 'holiday')
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));
  const tbd = state.events.filter(e => !e.date && !['lecture', 'lab', 'tutorial'].includes(e.type));

  if (!dated.length && !tbd.length) { root.append(el('div', { class: 'empty-state' }, 'No deadlines match your filters.')); return; }

  const overdue = dated.filter(e => daysBetween(state.today, parseISO(e.date)) < 0);
  const upcoming = dated.filter(e => daysBetween(state.today, parseISO(e.date)) >= 0);

  if (overdue.length) {
    root.append(el('div', { class: 'section-title' }, `Overdue (${overdue.length})`));
    root.append(el('div', { class: 'deadline-list' }, ...overdue.map(deadlineRow)));
  }
  root.append(el('div', { class: 'section-title' }, `Upcoming (${upcoming.length})`));
  root.append(upcoming.length ? el('div', { class: 'deadline-list' }, ...upcoming.map(deadlineRow))
    : el('div', { class: 'card muted' }, 'Nothing upcoming with a firm date.'));

  if (tbd.length) {
    root.append(el('div', { class: 'section-title' }, `No firm date / TBD (${dedupById(tbd).length})`));
    root.append(el('div', { class: 'deadline-list' }, ...dedupById(tbd).map(deadlineRow)));
  }
}

/* ---------- Calendar ---------- */
function classSessionsForDate(d) {
  // Expand recurring class sessions onto a given date within the term range.
  const out = [];
  const dow = DOW[d.getDay()];
  for (const c of state.courses) {
    if (state.filters.course && c.code !== state.filters.course) continue;
    for (const s of c.sessions) {
      if (s.online || !s.days.includes(dow)) continue;
      if (s.start_date && toISO(d) < s.start_date) continue;
      if (s.end_date && toISO(d) > s.end_date) continue;
      if (state.filters.type && s.kind !== state.filters.type) continue;
      if (state.filters.status && state.filters.status !== 'confirmed') continue;
      out.push({
        id: `s-${c.code}-${s.kind}-${dow}`, course_code: c.code, title: `${TYPE_LABELS[s.kind]}`,
        type: s.kind, time: s.start_time, end_time: s.end_time, location: s.location,
        status: 'confirmed', origin: 'class', date: toISO(d), isClass: true,
        _session: s, _course: c,
      });
    }
  }
  return out;
}

function eventsForDate(iso) {
  const evs = state.events.filter(e => e.date === iso && e.type !== 'holiday');
  return evs;
}

function renderCalendar(root) {
  const toolbar = el('div', { class: 'cal-toolbar' });
  const title = el('div', { class: 'cal-title' });
  const prev = el('button', { class: 'btn btn-sm', onclick: () => shiftCal(-1) }, '‹');
  const next = el('button', { class: 'btn btn-sm', onclick: () => shiftCal(1) }, '›');
  const todayBtn = el('button', { class: 'btn btn-sm', onclick: () => { state.calCursor = new Date(state.today); render(); } }, 'Today');
  const modes = el('div', { class: 'cal-modes' },
    ...['month', 'week', 'day'].map(m => el('button', {
      class: 'cal-mode' + (state.calMode === m ? ' active' : ''),
      onclick: () => { state.calMode = m; render(); }
    }, m[0].toUpperCase() + m.slice(1))));
  toolbar.append(el('div', { class: 'cal-nav' }, prev, todayBtn, next, title), modes);
  root.append(toolbar);

  if (state.calMode === 'month') renderMonth(root, title);
  else if (state.calMode === 'week') renderWeek(root, title);
  else renderDay(root, title);
}

function shiftCal(dir) {
  const c = new Date(state.calCursor);
  if (state.calMode === 'month') c.setMonth(c.getMonth() + dir);
  else if (state.calMode === 'week') c.setDate(c.getDate() + 7 * dir);
  else c.setDate(c.getDate() + dir);
  state.calCursor = c;
  render();
}

function calEventChip(e) {
  const chipEl = el('div', {
    class: `cal-event ${e.status === 'tentative' ? 'tentative' : ''} ${e.status === 'conflict' ? 'conflict' : ''}`,
    style: `background:${typeColor(e.type)}`,
    title: `${e.course_code} — ${e.title}`,
    onclick: (ev) => { ev.stopPropagation(); e.isClass ? openClassDrawer(e) : openEventDrawer(e.id, e); },
  }, `${e.time ? fmtTime(e.time).replace(':00', '') + ' ' : ''}${e.course_code || ''} ${e.title}`);
  return chipEl;
}

function collectDayItems(d) {
  const iso = toISO(d);
  const items = [...classSessionsForDate(d), ...eventsForDate(iso)];
  return items.sort((a, b) => (a.time || '99').localeCompare(b.time || '99'));
}

function renderMonth(root, title) {
  const cur = state.calCursor;
  title.textContent = `${MONTHS[cur.getMonth()]} ${cur.getFullYear()}`;
  const first = new Date(cur.getFullYear(), cur.getMonth(), 1);
  const start = new Date(first); start.setDate(1 - first.getDay());

  const grid = el('div', { class: 'cal-grid' });
  DOW.forEach(d => grid.append(el('div', { class: 'cal-dow' }, d)));
  for (let i = 0; i < 42; i++) {
    const day = new Date(start); day.setDate(start.getDate() + i);
    const isOther = day.getMonth() !== cur.getMonth();
    const isToday = toISO(day) === toISO(state.today);
    const cell = el('div', { class: `cal-cell${isOther ? ' other-month' : ''}${isToday ? ' today' : ''}` },
      el('div', { class: 'cal-daynum' }, String(day.getDate())));
    collectDayItems(day).slice(0, 4).forEach(e => cell.append(calEventChip(e)));
    const extra = collectDayItems(day).length - 4;
    if (extra > 0) cell.append(el('div', { class: 'cal-empty' }, `+${extra} more`));
    grid.append(cell);
  }
  root.append(grid);
}

function renderWeek(root, title) {
  const cur = new Date(state.calCursor);
  const start = new Date(cur); start.setDate(cur.getDate() - cur.getDay());
  const end = new Date(start); end.setDate(start.getDate() + 6);
  title.textContent = `${MONTHS[start.getMonth()].slice(0,3)} ${start.getDate()} – ${MONTHS[end.getMonth()].slice(0,3)} ${end.getDate()}`;
  const list = el('div', { class: 'cal-list' });
  for (let i = 0; i < 7; i++) {
    const day = new Date(start); day.setDate(start.getDate() + i);
    list.append(dayBlock(day));
  }
  root.append(list);
}

function renderDay(root, title) {
  const d = new Date(state.calCursor);
  title.textContent = d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  root.append(el('div', { class: 'cal-list' }, dayBlock(d)));
}

function dayBlock(day) {
  const isToday = toISO(day) === toISO(state.today);
  const items = collectDayItems(day);
  const block = el('div', { class: 'cal-listday' + (isToday ? ' today' : '') },
    el('h4', {}, day.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) + (isToday ? ' • Today' : '')));
  if (items.length) items.forEach(e => block.append(calEventChip(e)));
  else block.append(el('div', { class: 'cal-empty' }, 'No classes or deadlines'));
  return block;
}

/* ---------- Courses ---------- */
function renderCourses(root) {
  const layout = el('div', { class: 'course-layout' });
  const listCol = el('div', { class: 'course-list' });
  state.courses.forEach(c => {
    listCol.append(el('button', {
      class: 'course-pill' + (state.selectedCourse === c.code ? ' active' : ''),
      onclick: () => { state.selectedCourse = c.code; render(); },
    }, el('div', { class: 'cp-code' }, c.code), el('div', { class: 'cp-name' }, c.name)));
  });
  const detailCol = el('div', { class: 'course-detail' });
  layout.append(listCol, detailCol);
  root.append(layout);

  const code = state.selectedCourse || (state.courses[0] && state.courses[0].code);
  if (code) { state.selectedCourse = code; renderCourseDetail(detailCol, code); }
}

async function renderCourseDetail(root, code) {
  root.innerHTML = '<div class="muted">Loading…</div>';
  const c = await api('/api/courses/' + encodeURIComponent(code));
  root.innerHTML = '';
  root.append(el('div', { class: 'cd-head' },
    el('div', {}, el('h2', { style: 'margin:0' }, `${c.code} — ${c.name}`),
      el('div', { class: 'muted' }, c.term)),
    el('span', { class: 'chip' }, '📄 ' + (c.source_file || ''))));

  const kv = el('dl', { class: 'kv' });
  const add = (k, v) => { if (v) { kv.append(el('dt', {}, k), el('dd', {}, v)); } };
  add('Instructor', c.instructor + (c.instructor_email ? ` (${c.instructor_email})` : ''));
  add('TAs', c.tas);
  add('Published', c.published);
  root.append(kv);

  // Schedule
  root.append(el('div', { class: 'section-title' }, 'Class schedule'));
  if (c.sessions.length) {
    c.sessions.forEach(s => {
      root.append(el('div', { class: 'sched-line' },
        chip(s.kind),
        el('span', {}, s.online ? 'Online' : (s.days.join(', ') || '—')),
        el('span', { class: 'muted' }, s.start_time ? `${fmtTime(s.start_time)}–${fmtTime(s.end_time)}` : ''),
        el('span', { class: 'muted' }, s.location ? '📍 ' + s.location : '')));
    });
  } else root.append(el('div', { class: 'muted' }, 'No schedule found.'));

  // Grading breakdown
  if (c.grading && c.grading.length) {
    root.append(el('div', { class: 'section-title' }, 'Grading breakdown'));
    const table = el('table', { class: 'table' },
      el('tr', {}, el('th', {}, 'Component'), el('th', {}, 'Weight'), el('th', {}, 'Date (as stated)')));
    c.grading.forEach(g => table.append(el('tr', {},
      el('td', {}, g.component), el('td', {}, g.weight || '—'), el('td', { class: 'muted' }, g.date || '—'))));
    root.append(table);
  }

  // Deadlines & assessments
  root.append(el('div', { class: 'section-title' }, 'Deadlines & assessments'));
  const evs = (c.events || []).filter(e => e.type !== 'holiday')
    .sort((a, b) => (a.date || 'z').localeCompare(b.date || 'z'));
  if (evs.length) {
    const table = el('table', { class: 'table' },
      el('tr', {}, el('th', {}, 'Assessment'), el('th', {}, 'Type'), el('th', {}, 'Date'), el('th', {}, 'Weight'), el('th', {}, 'Status'), el('th', {}, '')));
    evs.forEach(e => {
      const dateTxt = e.candidates && e.candidates.length
        ? e.candidates.map(cd => cd.date ? (cd.date + (cd.time ? ' ' + fmtTime(cd.time) : '')) : 'TBD').join(' / ')
        : (e.date || 'TBD');
      table.append(el('tr', {},
        el('td', {}, e.title), el('td', {}, TYPE_LABELS[e.type] || e.type),
        el('td', {}, dateTxt), el('td', {}, e.weight || '—'),
        el('td', {}, statusBadge(e.status)),
        el('td', {}, el('button', { class: 'btn btn-sm', onclick: () => openEventDrawer(e.id, e) }, 'Source'))));
    });
    root.append(table);
  } else root.append(el('div', { class: 'muted' }, 'No assessments found.'));

  // Notes
  if (c.notes && c.notes.length) {
    root.append(el('div', { class: 'section-title' }, 'Notes from outline'));
    c.notes.forEach(n => root.append(el('div', { class: 'card', style: 'margin-bottom:8px' }, n)));
  }
}

/* ---------- Drawer (event detail + source) ---------- */
function findEvent(id) {
  return state.allEvents.find(e => e.id === id) || (state.summary && [...state.summary.conflicts].find(e => e.id === id));
}

function openEventDrawer(id, fallback) {
  const e = findEvent(id) || fallback;
  if (!e) return;
  const body = $('#drawer-content');
  body.innerHTML = '';
  body.append(el('h2', {}, e.title));
  body.append(el('div', { class: 'muted', style: 'margin-bottom:10px' }, `${e.course_code || 'General'} · ${TYPE_LABELS[e.type] || e.type}`));

  const badges = el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px' }, statusBadge(e.status));
  if (e.origin === 'manual') badges.append(el('span', { class: 'badge badge-manual' }, 'Manually added'));
  if (e.weight) badges.append(el('span', { class: 'chip' }, 'Weight: ' + e.weight));
  body.append(badges);

  if (e.status === 'conflict') {
    body.append(el('div', { class: 'banner banner-warn', style: 'margin-top:10px' },
      el('div', {}, el('b', {}, 'Conflicting dates. '), 'The outline states different dates for this item in different sections. Both are shown below; neither has been chosen automatically.')));
  }

  // Candidate dates with source traceability
  const cands = (e.candidates && e.candidates.length) ? e.candidates : [{
    date: e.date, time: e.time, status: e.status, source_section: e.source_section || '', source_text: e.source_text || e.description || '',
  }];
  cands.forEach(cd => {
    const box = el('div', { class: 'candidate' });
    box.append(el('div', {}, el('b', {}, cd.date ? (parseISO(cd.date).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })) : 'No firm date (TBD)')));
    if (cd.time) box.append(el('div', { class: 'muted' }, '🕑 ' + fmtTime(cd.time) + (cd.end_time ? '–' + fmtTime(cd.end_time) : '')));
    if (cd.end_date && cd.end_date !== cd.date) box.append(el('div', { class: 'muted' }, 'through ' + parseISO(cd.end_date).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })));
    box.append(el('div', { style: 'margin-top:6px' }, statusBadge(cd.status || e.status)));
    if (cd.source_section) box.append(el('div', { class: 'muted small', style: 'margin-top:6px' }, 'Section: ' + cd.source_section));
    if (cd.source_text) box.append(el('div', { class: 'source-quote' }, '“' + cd.source_text + '”'));
    body.append(box);
  });

  if (e.location) body.append(el('div', { style: 'margin-top:10px' }, '📍 ' + e.location));

  // Source file
  if (e.origin !== 'manual') {
    body.append(el('div', { class: 'source-box' },
      el('div', {}, 'Source document:'),
      el('code', {}, e.source_file || '(unknown)')));
  }

  if (e.origin === 'manual') {
    body.append(el('button', {
      class: 'btn btn-ghost', style: 'margin-top:16px;color:var(--overdue)',
      onclick: async () => { await api('/api/manual-events/' + e.id.slice(1), { method: 'DELETE' }); closeDrawer(); await loadAll(); }
    }, 'Delete this event'));
  }

  $('#drawer').classList.remove('hidden');
}

function openClassDrawer(e) {
  const s = e._session, c = e._course;
  const body = $('#drawer-content');
  body.innerHTML = '';
  body.append(el('h2', {}, `${c.code} — ${TYPE_LABELS[s.kind]}`));
  body.append(el('div', { class: 'muted', style: 'margin-bottom:10px' }, c.name));
  body.append(el('div', {}, `${s.days.join(', ')} · ${fmtTime(s.start_time)}–${fmtTime(s.end_time)}`));
  if (s.location) body.append(el('div', { style: 'margin-top:6px' }, '📍 ' + s.location));
  if (s.start_date) body.append(el('div', { class: 'muted', style: 'margin-top:6px' }, `Term: ${s.start_date} → ${s.end_date}`));
  body.append(el('div', { class: 'source-box' }, el('div', {}, 'Source document:'), el('code', {}, s.source_file)));
  $('#drawer').classList.remove('hidden');
}

function closeDrawer() { $('#drawer').classList.add('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); }

/* ---------- events / wiring ---------- */
function wire() {
  $$('.nav-item').forEach(b => b.addEventListener('click', () => {
    $$('.nav-item').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    state.view = b.dataset.view;
    render();
  }));

  $('#f-course').addEventListener('change', e => { state.filters.course = e.target.value; applyFilters(); });
  $('#f-type').addEventListener('change', e => { state.filters.type = e.target.value; applyFilters(); });
  $('#f-status').addEventListener('change', e => { state.filters.status = e.target.value; applyFilters(); });
  $('#f-from').addEventListener('change', e => { state.filters.from = e.target.value; applyFilters(); });
  $('#f-to').addEventListener('change', e => { state.filters.to = e.target.value; applyFilters(); });
  $('#f-clear').addEventListener('click', () => {
    state.filters = { course: '', type: '', status: '', from: '', to: '' };
    $('#f-course').value = ''; $('#f-type').value = ''; $('#f-status').value = '';
    $('#f-from').value = ''; $('#f-to').value = '';
    applyFilters();
  });

  $$('[data-close-drawer]').forEach(x => x.addEventListener('click', closeDrawer));
  $$('[data-close-modal]').forEach(x => x.addEventListener('click', closeModal));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeDrawer(); closeModal(); } });

  $('#add-event-btn').addEventListener('click', () => $('#modal').classList.remove('hidden'));
  $('#manual-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    const data = Object.fromEntries(fd.entries());
    if (!data.title) return;
    await api('/api/manual-events', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    ev.target.reset();
    closeModal();
    await loadAll();
  });

  $('#rescan-btn').addEventListener('click', async () => {
    const st = $('#scan-status');
    st.textContent = 'Scanning…';
    try {
      const r = await api('/api/rescan', { method: 'POST' });
      const parts = [];
      if (r.new.length) parts.push(`${r.new.length} new`);
      if (r.changed.length) parts.push(`${r.changed.length} changed`);
      if (r.removed.length) parts.push(`${r.removed.length} removed`);
      if (r.errors.length) parts.push(`${r.errors.length} errors`);
      st.textContent = parts.length ? parts.join(', ') : `Up to date (${r.unchanged.length} files)`;
      await loadAll();
    } catch (e) { st.textContent = 'Scan failed: ' + e.message; }
    setTimeout(() => { st.textContent = ''; }, 6000);
  });
}

wire();
loadAll().catch(e => {
  $('#view').innerHTML = `<div class="empty-state">Failed to load data: ${e.message}<br>Try running a re-scan.</div>`;
});
