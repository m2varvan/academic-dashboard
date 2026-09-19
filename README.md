# academic-dashboard
A local, zero-friction dashboard to track classes, deadlines, and prep tasks from course outlines.

## Stack
- Python 3
- Flask (local web app)
- SQLite (local structured data)
- BeautifulSoup + pypdf (HTML/PDF extraction)
- Vanilla JS/CSS UI

## Run locally
```bash
cd /home/runner/work/academic-dashboard/academic-dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:5000`.

By default the app scans:
`/home/runner/work/academic-dashboard/academic-dashboard/course-outlines`

You can also provide any absolute folder path in the UI and click **Re-scan outlines**.

## What it does
- Inspects all `.html/.htm/.pdf` files in the outline folder.
- Extracts course metadata (code/name/term/instructor), class schedule, deadlines/events.
- Preserves uncertainty (`tentative`, `tbd`) instead of fabricating dates.
- Stores source traceability for each extracted event (`source_file`, locator, excerpt).
- Flags conflicting date values for similarly named events.
- Supports re-scan for new/changed/removed files.
- Supports manual event additions (saved separately from extracted entries).

## Structured data model
SQLite tables:
- `source_documents`
- `courses`
- `class_sessions`
- `events`
- `conflicts`

## API endpoints
- `POST /api/rescan` (optional JSON: `{ "outline_dir": "/abs/path" }`)
- `GET /api/report`
- `GET /api/summary`
- `GET /api/courses`
- `GET /api/events` (+ filters: `course_id`, `event_type`, `status`, `start`, `end`)
- `POST /api/events/manual`

## Test
```bash
python -m unittest discover -s tests -v
```
