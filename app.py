from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from scanner import ParsedCourse, parse_outline_file
from storage import get_connection, init_db

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTLINE_DIR = ROOT / "course-outlines"
SUPPORTED_SUFFIXES = {".html", ".htm", ".pdf"}

app = Flask(__name__)


def _event_key(source_file: str, event: dict) -> str:
    raw = "|".join(
        [
            source_file,
            event.get("title") or "",
            event.get("event_type") or "",
            event.get("date_text") or "",
            event.get("time_text") or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _upsert_course(conn, course: ParsedCourse) -> int:
    conn.execute(
        """
        INSERT INTO courses(source_file, course_code, course_name, term, instructor, notes)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_file) DO UPDATE SET
            course_code=excluded.course_code,
            course_name=excluded.course_name,
            term=excluded.term,
            instructor=excluded.instructor,
            notes=excluded.notes
        """,
        (
            course.source_file,
            course.course_code,
            course.course_name,
            course.term,
            course.instructor,
            "\n".join(course.extraction_notes) if course.extraction_notes else None,
        ),
    )
    row = conn.execute("SELECT id FROM courses WHERE source_file = ?", (course.source_file,)).fetchone()
    return int(row["id"])


def _save_course_extract(conn, course: ParsedCourse) -> None:
    course_id = _upsert_course(conn, course)
    conn.execute("DELETE FROM class_sessions WHERE course_id = ?", (course_id,))
    conn.execute("DELETE FROM events WHERE source_file = ? AND is_manual = 0", (course.source_file,))

    for sess in course.class_sessions:
        conn.execute(
            """
            INSERT INTO class_sessions(course_id, day_of_week, start_time, end_time, location, raw_text, status, source_file, source_locator)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course_id,
                sess.get("day_of_week"),
                sess.get("start_time"),
                sess.get("end_time"),
                sess.get("location"),
                sess.get("raw_text"),
                sess.get("status", "confirmed"),
                course.source_file,
                sess.get("source_locator"),
            ),
        )

    for event in course.events:
        conn.execute(
            """
            INSERT OR IGNORE INTO events(event_key, course_id, title, event_type, date_text, date_iso, time_text,
                                         location, description, weight, status, source_file, source_locator,
                                         source_excerpt, is_manual)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                _event_key(course.source_file, event),
                course_id,
                event.get("title") or "Untitled event",
                event.get("event_type") or "other",
                event.get("date_text"),
                event.get("date_iso"),
                event.get("time_text"),
                event.get("location"),
                event.get("description"),
                event.get("weight"),
                event.get("status", "confirmed"),
                course.source_file,
                event.get("source_locator"),
                event.get("source_excerpt"),
            ),
        )


def _outline_files(outline_dir: Path) -> list[Path]:
    if not outline_dir.exists():
        return []
    return sorted([p for p in outline_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES])


def scan_outlines(outline_dir: Path) -> dict:
    init_db()
    files = _outline_files(outline_dir)

    report = {
        "scanned_at": datetime.utcnow().isoformat(),
        "outline_dir": str(outline_dir),
        "files_discovered": [f.name for f in files],
        "courses": [],
        "course_event_counts": {},
        "ambiguous_dates": [],
        "conflicts": [],
        "unreliable_extractions": [],
    }

    with get_connection() as conn:
        tracked_rows = conn.execute("SELECT path FROM source_documents").fetchall()
        tracked = {r["path"] for r in tracked_rows}
        current = {f.name for f in files}

        removed = tracked - current
        for removed_file in removed:
            conn.execute("DELETE FROM source_documents WHERE path = ?", (removed_file,))
            conn.execute("DELETE FROM class_sessions WHERE source_file = ?", (removed_file,))
            conn.execute("DELETE FROM events WHERE source_file = ? AND is_manual = 0", (removed_file,))
            conn.execute("DELETE FROM courses WHERE source_file = ?", (removed_file,))

        by_course_dates: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        all_courses: list[ParsedCourse] = []

        for file_path in files:
            parsed = parse_outline_file(file_path)
            all_courses.append(parsed)

            existing = conn.execute(
                "SELECT file_hash FROM source_documents WHERE path = ?", (file_path.name,)
            ).fetchone()
            changed = existing is None or existing["file_hash"] != parsed.file_hash

            conn.execute(
                """
                INSERT INTO source_documents(path, file_hash, file_type, last_scanned_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    file_hash=excluded.file_hash,
                    file_type=excluded.file_type,
                    last_scanned_at=excluded.last_scanned_at
                """,
                (file_path.name, parsed.file_hash, parsed.file_type, datetime.utcnow().isoformat()),
            )

            if changed:
                _save_course_extract(conn, parsed)

            code = parsed.course_code or f"Unknown ({file_path.name})"
            report["courses"].append(
                {
                    "source_file": parsed.source_file,
                    "course_code": parsed.course_code,
                    "course_name": parsed.course_name,
                    "term": parsed.term,
                    "instructor": parsed.instructor,
                }
            )
            report["course_event_counts"][code] = len(parsed.events)

            if not parsed.course_code or not parsed.course_name:
                report["unreliable_extractions"].append(
                    f"{file_path.name}: missing {'course code' if not parsed.course_code else 'course name'}"
                )

            for event in parsed.events:
                if event.get("status") in {"tentative", "tbd"} or (event.get("date_text") and not event.get("date_iso")):
                    report["ambiguous_dates"].append(
                        {
                            "course": parsed.course_code,
                            "title": event.get("title"),
                            "date_text": event.get("date_text"),
                            "status": event.get("status"),
                            "source_file": parsed.source_file,
                        }
                    )
                key = event.get("title") or ""
                dt = event.get("date_text") or "TBD"
                by_course_dates[code][key].add(dt)

        conn.execute("DELETE FROM conflicts")
        for course_code, events in by_course_dates.items():
            for title, dates in events.items():
                if len(dates) > 1:
                    values = sorted(dates)
                    conn.execute(
                        """
                        INSERT INTO conflicts(course_code, field_name, first_value, second_value, source_file, details)
                        VALUES(?, 'date', ?, ?, '', ?)
                        """,
                        (course_code, values[0], values[1], f"Conflicting dates for {title}"),
                    )
                    report["conflicts"].append(
                        {
                            "course": course_code,
                            "title": title,
                            "values": values,
                        }
                    )

    return report


def _events_query(filters: dict | None = None):
    filters = filters or {}
    where = ["1=1"]
    params = []

    if filters.get("course_id"):
        where.append("e.course_id = ?")
        params.append(filters["course_id"])
    if filters.get("event_type"):
        where.append("e.event_type = ?")
        params.append(filters["event_type"])
    if filters.get("status"):
        where.append("e.status = ?")
        params.append(filters["status"])
    if filters.get("start"):
        where.append("(e.date_iso IS NULL OR e.date_iso >= ?)")
        params.append(filters["start"])
    if filters.get("end"):
        where.append("(e.date_iso IS NULL OR e.date_iso <= ?)")
        params.append(filters["end"])

    query = f"""
        SELECT e.*, c.course_code, c.course_name
        FROM events e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE {' AND '.join(where)}
        ORDER BY (e.date_iso IS NULL), e.date_iso ASC, e.id ASC
    """
    return query, params


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    payload = request.get_json(silent=True) or {}
    outline_dir = Path(payload.get("outline_dir") or DEFAULT_OUTLINE_DIR)
    report = scan_outlines(outline_dir)
    return jsonify(report)


@app.route("/api/report", methods=["GET"])
def api_report():
    outline_dir = Path(request.args.get("outline_dir") or DEFAULT_OUTLINE_DIR)
    report = scan_outlines(outline_dir)
    return jsonify(report)


@app.route("/api/courses", methods=["GET"])
def api_courses():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM courses ORDER BY course_code, source_file").fetchall()
        courses = [dict(r) for r in rows]
        for course in courses:
            sessions = conn.execute(
                "SELECT * FROM class_sessions WHERE course_id = ? ORDER BY day_of_week", (course["id"],)
            ).fetchall()
            course["class_sessions"] = [dict(s) for s in sessions]
        return jsonify(courses)


@app.route("/api/conflicts", methods=["GET"])
def api_conflicts():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM conflicts ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/events", methods=["GET"])
def api_events():
    filters = {
        "course_id": request.args.get("course_id", type=int),
        "event_type": request.args.get("event_type"),
        "status": request.args.get("status"),
        "start": request.args.get("start"),
        "end": request.args.get("end"),
    }
    query, params = _events_query(filters)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/events/manual", methods=["POST"])
def api_add_manual_event():
    payload = request.get_json(force=True)
    required = ["title", "event_type", "status"]
    if any(not payload.get(key) for key in required):
        return jsonify({"error": "title, event_type, and status are required"}), 400

    event = {
        "title": payload["title"],
        "event_type": payload["event_type"],
        "date_text": payload.get("date_text"),
        "date_iso": payload.get("date_iso"),
        "time_text": payload.get("time_text"),
        "location": payload.get("location"),
        "description": payload.get("description"),
        "weight": payload.get("weight"),
        "status": payload["status"],
    }
    key = _event_key("manual", event)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO events(event_key, course_id, title, event_type, date_text, date_iso, time_text, location,
                               description, weight, status, source_file, source_locator, source_excerpt, is_manual)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 'manual-entry', ?, 1)
            ON CONFLICT(event_key) DO UPDATE SET
                title=excluded.title,
                event_type=excluded.event_type,
                date_text=excluded.date_text,
                date_iso=excluded.date_iso,
                time_text=excluded.time_text,
                location=excluded.location,
                description=excluded.description,
                weight=excluded.weight,
                status=excluded.status
            """,
            (
                key,
                payload.get("course_id"),
                event["title"],
                event["event_type"],
                event["date_text"],
                event["date_iso"],
                event["time_text"],
                event["location"],
                event["description"],
                event["weight"],
                event["status"],
                event["description"] or event["title"],
            ),
        )
    return jsonify({"ok": True})


@app.route("/api/summary", methods=["GET"])
def api_summary():
    today = date.today()
    next_7 = today + timedelta(days=7)
    next_30 = today + timedelta(days=30)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.*, c.course_code, c.course_name
            FROM events e
            LEFT JOIN courses c ON c.id = e.course_id
            WHERE e.date_iso IS NOT NULL
            ORDER BY e.date_iso ASC
            """
        ).fetchall()

    as_dict = [dict(r) for r in rows]

    def in_range(item, start, end):
        d = datetime.strptime(item["date_iso"], "%Y-%m-%d").date()
        return start <= d <= end

    due_today = [i for i in as_dict if in_range(i, today, today)]
    due_7 = [i for i in as_dict if in_range(i, today, next_7)]
    due_30 = [i for i in as_dict if in_range(i, today, next_30)]

    major_types = {"midterm", "exam", "project", "presentation"}
    major = next((i for i in as_dict if i.get("event_type") in major_types and datetime.strptime(i["date_iso"], "%Y-%m-%d").date() >= today), None)

    return jsonify(
        {
            "today": today.isoformat(),
            "due_today": due_today,
            "due_next_7_days": due_7,
            "due_next_30_days": due_30,
            "upcoming_count": len(due_30),
            "next_major_assessment": major,
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
