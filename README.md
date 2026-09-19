# Academic Dashboard

A local, zero-friction dashboard that reads your course outlines, extracts the
important academic information, and puts everything in one place: **what classes
you have, what's coming up, and what you need to submit or prepare for.**

It runs entirely on your machine. No cloud, no accounts, no database server.

> Note: this project was vibe coded with the help of claude code.

---

## What it does

- **Parses your outlines** — reads every HTML and PDF course outline in
  `Data/Fall 2026 Classes/`, extracting courses, instructors, class schedules,
  and every dated deliverable (assignments, quizzes, midterms, exams, projects,
  milestones, presentations, reports).
- **Keeps the source as the source of truth** — it never invents a date. If an
  outline says *TBD*, *tentative*, or *approximate*, that uncertainty is shown
  explicitly rather than converted into a firm date.
- **Flags conflicts** — when different sections of an outline disagree on a date,
  both dates are shown and the item is marked as a conflict.
- **Traces everything back to the source** — every deadline records the source
  file, the section it came from, and the verbatim text, so you can verify it.
- **Lets you add your own events** — manual events (e.g. "Study for midterm") are
  tagged separately and are never overwritten by a re-scan.
- **Re-scans on demand** — add, edit, or remove an outline and re-scan; only
  changed files are reprocessed, and your manual events are preserved.

---

## Quick start

```bash
./run.sh
```

Then open **http://127.0.0.1:5173** in your browser.

The first run creates a virtual environment, installs dependencies, scans the
outlines into a local SQLite database (`dashboard.db`), and starts the server.

### Manual start (if you prefer)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m app.store      # scan outlines -> dashboard.db
python -m app.server     # serve at http://127.0.0.1:5173
```

---

## The dashboard

| View | What you see |
|------|--------------|
| **Overview** | Today's date, counts for due-today / next-7-days / next-30-days / total upcoming / overdue, the next major assessment, and warning banners for date conflicts and TBD items. |
| **Calendar** | Month / week / day views. Classes and deadlines are color-coded by type. Tentative items are dashed; conflicts have a ring. Click any item for details and its source. |
| **Deadlines** | A chronological list (nearest first) with days remaining, weight, and status. Overdue items are clearly marked; TBD items are grouped separately. |
| **Courses** | Pick a course to see its info, instructor, class schedule, grading breakdown, all assessments (with a *Source* button each), and notes from the outline. |

**Filters** (top bar): course, event type, status (confirmed / tentative / TBD /
conflict), and a date range.

**Add event** (sidebar): create your own events. They're tagged **Manual**.

**Re-scan outlines** (sidebar): re-reads the folder and reports what changed.

> Tip: append `?today=YYYY-MM-DD` to the URL to preview the dashboard as if it
> were a different day (useful for testing).

---

## Updating outlines during the term

1. Replace, edit, add, or remove files in `Data/Fall 2026 Classes/`.
2. Click **Re-scan outlines** (or run `python -m app.store`).

Re-scan uses a content hash per file, so unchanged files are skipped. Changed
files have their courses/events rebuilt without creating duplicates. Removing a
file removes its derived data. **Manual events are always preserved.**

---

## How uncertainty is handled

The application distinguishes four statuses:

- **Confirmed** — a firm date stated in the outline.
- **Tentative** — the outline marks it tentative / approximate / subject to change.
- **TBD** — no date given (e.g. "Final exam: to be announced by the Registrar").
- **Conflict** — two sections of an outline give different dates. Both are shown.

For example, this term's MSE 332 outline lists **Midterm 1** as *Oct 6* in the
class-plan table but *Oct 8* in the assessments table — so it's flagged as a
conflict, with both dates visible and neither chosen automatically.

---

## Project layout

```
app/
  models.py       Normalized data structures (Course, Event, ClassSession, ...)
  dateparse.py    Date/time/day parsing with explicit uncertainty rules
  parse_html.py   Parser for the LMS-style HTML outlines
  parse_pdf.py    Parser for the PDF outline
  extract.py      Parser dispatch + conflict detection
  store.py        SQLite schema, scan/update logic, manual events
  server.py       Flask API + serves the frontend
  static/         index.html, styles.css, app.js (vanilla JS, no build step)
Data/             Your course outlines (the source of truth)
scripts/          One-off inspection / extraction test helpers
dashboard.db      Generated local database (git-ignored)
```

---

## Stack & rationale

Python + Flask + SQLite on the backend, vanilla HTML/CSS/JS on the frontend.
Chosen for simplicity, reliability, local operation, minimal dependencies, and
easy future modification — no build tooling and no server infrastructure.

Dependencies (`requirements.txt`): Flask, beautifulsoup4, lxml, pdfplumber.
