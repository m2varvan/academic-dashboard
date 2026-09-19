let allEvents = [];
let allCourses = [];
let currentView = 'month';

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function daysRemaining(dateIso) {
  if (!dateIso) return '—';
  const today = new Date();
  today.setHours(0,0,0,0);
  const due = new Date(dateIso + 'T00:00:00');
  return Math.ceil((due - today) / (1000 * 60 * 60 * 24));
}

function eventClass(e) {
  return `event-pill type-${e.event_type} status-${e.status}`;
}

function showEventDetails(event) {
  const body = document.getElementById('eventDialogBody');
  body.innerHTML = `<h3>${event.title}</h3>
    <p><b>Course:</b> ${event.course_code || 'Manual/General'}</p>
    <p><b>Type:</b> ${event.event_type}</p>
    <p><b>Date:</b> ${event.date_text || 'TBD'} ${event.time_text || ''}</p>
    <p><b>Status:</b> ${event.status}</p>
    <p><b>Weight:</b> ${event.weight || 'N/A'}</p>
    <p><b>Description:</b> ${event.description || ''}</p>
    <p><b>Source:</b> ${event.source_file || 'manual'} (${event.source_locator || 'n/a'})</p>
    <p><small>${event.source_excerpt || ''}</small></p>`;
  document.getElementById('eventDialog').showModal();
}

function renderCalendar(events) {
  const cal = document.getElementById('calendar');
  const dated = events.filter(e => e.date_iso);
  if (currentView === 'day') {
    const target = new Date();
    const items = dated.filter(e => e.date_iso === target.toISOString().slice(0,10));
    cal.innerHTML = `<h4>${target.toDateString()}</h4>` + items.map(e => `<div class="${eventClass(e)}">${e.title}</div>`).join('');
    [...cal.querySelectorAll('.event-pill')].forEach((el, i) => el.onclick = () => showEventDetails(items[i]));
    return;
  }

  const start = new Date();
  const range = currentView === 'week' ? 7 : 35;
  const cells = [];
  for (let i = 0; i < range; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = d.toISOString().slice(0,10);
    const items = dated.filter(e => e.date_iso === iso);
    cells.push(`<div class="day-cell"><b>${iso}</b>${items.map(e => `<div class="${eventClass(e)}">${e.title}</div>`).join('')}</div>`);
  }
  cal.innerHTML = `<div class="calendar-grid">${cells.join('')}</div>`;
  const allPills = [...cal.querySelectorAll('.event-pill')];
  let idx = 0;
  for (let i = 0; i < range; i++) {
    const d = new Date(start); d.setDate(start.getDate()+i);
    const iso = d.toISOString().slice(0,10);
    const items = dated.filter(e => e.date_iso === iso);
    for (const ev of items) {
      allPills[idx++].onclick = () => showEventDetails(ev);
    }
  }
}

function renderDeadlines(events) {
  const tbody = document.querySelector('#deadlinesTable tbody');
  tbody.innerHTML = '';
  events.forEach(e => {
    const rem = daysRemaining(e.date_iso);
    const tr = document.createElement('tr');
    if (typeof rem === 'number' && rem < 0) tr.classList.add('overdue');
    tr.innerHTML = `<td>${e.course_code || '—'}</td><td>${e.title}</td><td>${e.event_type}</td><td>${e.date_text || 'TBD'} ${e.time_text || ''}</td>
      <td>${rem}</td><td>${e.weight || '—'}</td><td>${e.status}</td><td>${e.source_file || 'manual'}</td>`;
    tr.onclick = () => showEventDetails(e);
    tbody.appendChild(tr);
  });
}

function renderCourses() {
  const sel = document.getElementById('courseDetailSelect');
  sel.innerHTML = allCourses.map(c => `<option value="${c.id}">${c.course_code || 'Unknown'} - ${c.course_name || c.source_file}</option>`).join('');
  const filters = document.getElementById('courseFilter');
  filters.innerHTML = '<option value="">All courses</option>' + allCourses.map(c => `<option value="${c.id}">${c.course_code || c.source_file}</option>`).join('');

  const draw = () => {
    const c = allCourses.find(x => String(x.id) === sel.value);
    if (!c) return;
    const events = allEvents.filter(e => e.course_id === c.id);
    const details = document.getElementById('courseDetails');
    details.innerHTML = `<p><b>Course:</b> ${c.course_code || 'Unknown'} - ${c.course_name || ''}</p>
      <p><b>Term:</b> ${c.term || 'N/A'}</p>
      <p><b>Instructor:</b> ${c.instructor || 'N/A'}</p>
      <p><b>Schedule:</b> ${(c.class_sessions || []).map(s => `${s.day_of_week || '?'} ${s.start_time || ''}-${s.end_time || ''} ${s.location || ''}`).join('<br>') || 'N/A'}</p>
      <p><b>Assessments / Deadlines:</b></p>
      <ul>${events.map(e => `<li>${e.title} (${e.event_type}) — ${e.date_text || 'TBD'} [${e.status}] ${e.weight || ''}</li>`).join('')}</ul>`;
  };
  sel.onchange = draw;
  draw();
}

async function refresh() {
  allCourses = await fetchJSON('/api/courses');
  const params = new URLSearchParams();
  const c = document.getElementById('courseFilter').value;
  const t = document.getElementById('typeFilter').value;
  const s = document.getElementById('statusFilter').value;
  const start = document.getElementById('startFilter').value;
  const end = document.getElementById('endFilter').value;
  if (c) params.set('course_id', c);
  if (t) params.set('event_type', t);
  if (s) params.set('status', s);
  if (start) params.set('start', start);
  if (end) params.set('end', end);
  allEvents = await fetchJSON(`/api/events?${params.toString()}`);
  allEvents.sort((a,b) => (a.date_iso || '9999').localeCompare(b.date_iso || '9999'));
  renderDeadlines(allEvents);
  renderCalendar(allEvents);
  renderCourses();

  const summary = await fetchJSON('/api/summary');
  document.getElementById('summary').innerHTML = `<p>Today: ${summary.today}</p>
    <p>Due today: ${summary.due_today.length}</p>
    <p>Due next 7 days: ${summary.due_next_7_days.length}</p>
    <p>Due next 30 days: ${summary.due_next_30_days.length}</p>
    <p>Upcoming items: ${summary.upcoming_count}</p>
    <p>Next major assessment: ${summary.next_major_assessment ? summary.next_major_assessment.title + ' (' + summary.next_major_assessment.date_text + ')' : 'N/A'}</p>`;
}

async function rescan() {
  const outlineDir = document.getElementById('outlineDir').value;
  const report = await fetchJSON('/api/rescan', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ outline_dir: outlineDir || undefined })
  });
  document.getElementById('report').textContent = JSON.stringify(report, null, 2);
  await refresh();
}

document.getElementById('scanBtn').onclick = rescan;
document.getElementById('applyFilterBtn').onclick = refresh;

document.querySelectorAll('.calendar-controls button').forEach(btn => {
  btn.onclick = () => { currentView = btn.dataset.view; renderCalendar(allEvents); };
});

document.getElementById('manualForm').onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  payload.date_text = payload.date_iso || 'TBD';
  await fetchJSON('/api/events/manual', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  e.target.reset();
  await refresh();
};

rescan().catch(async () => {
  const report = await fetchJSON('/api/report');
  document.getElementById('report').textContent = JSON.stringify(report, null, 2);
  await refresh();
});
