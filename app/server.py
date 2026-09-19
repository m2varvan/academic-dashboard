"""Flask API + static server for the academic dashboard.

Runs entirely locally. Serves the vanilla-JS frontend from app/static and a
JSON API that reads the SQLite store. All date/status logic already lives in
the store; this layer just shapes and filters the data for the UI.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import store

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__, static_folder=None)


# --- helpers -----------------------------------------------------------------

def _conn():
    conn = store.connect()
    store.init_db(conn)
    return conn


def _event_rows(conn):
    """Return all events (extracted + manual) as normalized dicts.

    Each event may expand into multiple 'occurrences' (one per date candidate).
    Occurrences with no date are kept once, flagged TBD.
    """
    out = []

    # Extracted events + their date candidates
    events = conn.execute("SELECT * FROM events WHERE origin='extracted'").fetchall()
    for e in events:
        dates = conn.execute(
            "SELECT * FROM event_dates WHERE event_id=? ORDER BY date IS NULL, date", (e["id"],)
        ).fetchall()
        base = {
            "id": f"e{e['id']}",
            "course_code": e["course_code"],
            "title": e["title"],
            "type": e["type"],
            "weight": e["weight"],
            "location": e["location"],
            "description": e["description"],
            "status": e["status"],
            "source_file": e["source_file"],
            "origin": "extracted",
            "candidates": [dict(d) for d in dates],
        }
        if not dates:
            out.append({**base, "date": None, "time": None, "occ_status": "tbd"})
            continue
        for d in dates:
            out.append({
                **base,
                "date": d["date"],
                "end_date": d["end_date"],
                "time": d["time"],
                "end_time": d["end_time"],
                "occ_status": d["status"] or e["status"],
                "source_section": d["source_section"],
                "source_text": d["source_text"],
            })

    # Manual events
    for m in conn.execute("SELECT * FROM manual_events").fetchall():
        out.append({
            "id": f"m{m['id']}",
            "course_code": m["course_code"],
            "title": m["title"],
            "type": m["type"] or "other",
            "weight": None,
            "location": m["location"],
            "description": m["description"],
            "status": "confirmed" if m["date"] else "tbd",
            "occ_status": "confirmed" if m["date"] else "tbd",
            "source_file": None,
            "origin": "manual",
            "date": m["date"],
            "time": m["time"],
            "end_time": m["end_time"],
            "candidates": [],
        })
    return out


def _today():
    # Fixed via query param for testing, else real today.
    q = request.args.get("today")
    if q:
        return dt.date.fromisoformat(q)
    return dt.date.today()


# --- API ---------------------------------------------------------------------

@app.get("/api/courses")
def api_courses():
    conn = _conn()
    rows = conn.execute("SELECT * FROM courses ORDER BY code").fetchall()
    courses = []
    for c in rows:
        sessions = conn.execute(
            "SELECT * FROM class_sessions WHERE course_code=?", (c["code"],)).fetchall()
        courses.append({
            "code": c["code"], "name": c["name"], "term": c["term"],
            "instructor": c["instructor"], "instructor_email": c["instructor_email"],
            "tas": c["tas"], "published": c["published"], "source_file": c["source_file"],
            "grading": json.loads(c["grading"] or "[]"),
            "notes": json.loads(c["notes"] or "[]"),
            "sessions": [_session_dict(s) for s in sessions],
        })
    conn.close()
    return jsonify(courses)


def _session_dict(s):
    return {
        "kind": s["kind"], "section": s["section"], "days": json.loads(s["days"] or "[]"),
        "start_time": s["start_time"], "end_time": s["end_time"], "location": s["location"],
        "start_date": s["start_date"], "end_date": s["end_date"], "online": bool(s["online"]),
        "source_file": s["source_file"],
    }


@app.get("/api/courses/<path:code>")
def api_course(code):
    conn = _conn()
    c = conn.execute("SELECT * FROM courses WHERE code=?", (code,)).fetchone()
    if not c:
        conn.close()
        return jsonify({"error": "not found"}), 404
    sessions = conn.execute("SELECT * FROM class_sessions WHERE course_code=?", (code,)).fetchall()
    events = [e for e in _event_rows(conn) if e["course_code"] == code]
    # collapse to unique events (not per-occurrence) for the course view
    unique = {}
    for e in events:
        unique.setdefault(e["id"], e)
    conn.close()
    return jsonify({
        "code": c["code"], "name": c["name"], "term": c["term"],
        "instructor": c["instructor"], "instructor_email": c["instructor_email"],
        "tas": c["tas"], "published": c["published"], "source_file": c["source_file"],
        "grading": json.loads(c["grading"] or "[]"),
        "notes": json.loads(c["notes"] or "[]"),
        "sessions": [_session_dict(s) for s in sessions],
        "events": list(unique.values()),
    })


@app.get("/api/events")
def api_events():
    conn = _conn()
    rows = _event_rows(conn)
    conn.close()

    course = request.args.get("course")
    etype = request.args.get("type")
    status = request.args.get("status")   # confirmed|tentative|tbd|conflict
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    include_classes = request.args.get("include_classes") == "1"

    def keep(e):
        if course and e["course_code"] != course:
            return False
        if etype and e["type"] != etype:
            return False
        if status:
            if status == "tentative" and e["occ_status"] not in ("tentative",):
                return False
            elif status != "tentative" and e["occ_status"] != status:
                return False
        if date_from and (not e.get("date") or e["date"] < date_from):
            return False
        if date_to and (not e.get("date") or e["date"] > date_to):
            return False
        return True

    events = [e for e in rows if keep(e)]
    events.sort(key=lambda e: (e.get("date") is None, e.get("date") or "", e.get("time") or ""))
    return jsonify(events)


@app.get("/api/summary")
def api_summary():
    conn = _conn()
    rows = _event_rows(conn)
    conn.close()
    today = _today()
    horizon_types = {"assignment", "quiz", "midterm", "exam", "project",
                     "milestone", "presentation", "report", "other"}

    def as_date(e):
        return dt.date.fromisoformat(e["date"]) if e.get("date") else None

    dated = [e for e in rows if as_date(e) and e["type"] in horizon_types]
    dated.sort(key=lambda e: e["date"])

    due_today = [e for e in dated if as_date(e) == today]
    next7 = [e for e in dated if today < as_date(e) <= today + dt.timedelta(days=7)]
    next30 = [e for e in dated if today < as_date(e) <= today + dt.timedelta(days=30)]
    overdue = [e for e in dated if as_date(e) < today]
    upcoming = [e for e in dated if as_date(e) >= today]

    major_types = {"midterm", "exam", "project", "report"}
    next_major = next((e for e in upcoming if e["type"] in major_types), None)

    conflicts = [e for e in rows if e["status"] == "conflict"]
    tbd_items = [e for e in rows if e["status"] == "tbd" and e["type"] in horizon_types]

    return jsonify({
        "today": today.isoformat(),
        "due_today": due_today,
        "next_7_days": next7,
        "next_30_days": next30,
        "overdue": overdue,
        "upcoming_count": len(upcoming),
        "next_major": next_major,
        "conflicts": _dedup_events(conflicts),
        "tbd_count": len(_dedup_events(tbd_items)),
    })


def _dedup_events(rows):
    seen, out = set(), []
    for e in rows:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    return out


@app.post("/api/rescan")
def api_rescan():
    force = request.args.get("force") == "1"
    summary = store.scan(force=force)
    return jsonify(summary)


@app.get("/api/manual-events")
def api_manual_list():
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM manual_events ORDER BY date").fetchall()]
    conn.close()
    return jsonify(rows)


@app.post("/api/manual-events")
def api_manual_add():
    data = request.get_json(force=True)
    if not data.get("title"):
        return jsonify({"error": "title is required"}), 400
    conn = _conn()
    new_id = store.add_manual_event(conn, data)
    conn.close()
    return jsonify({"id": new_id}), 201


@app.delete("/api/manual-events/<int:event_id>")
def api_manual_delete(event_id):
    conn = _conn()
    store.delete_manual_event(conn, event_id)
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/sources")
def api_sources():
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT filename, filetype, course_code, scanned_at FROM source_documents ORDER BY course_code").fetchall()]
    conn.close()
    return jsonify(rows)


# --- static frontend ---------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(STATIC_DIR, path)


def main():
    # Ensure DB exists / is populated before first serve.
    if not store.DEFAULT_DB.exists():
        store.scan()
    app.run(host="127.0.0.1", port=5173, debug=False)


if __name__ == "__main__":
    main()
