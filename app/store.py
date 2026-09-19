"""SQLite storage + scan/update logic for the academic dashboard.

Design goals:
  * Course outlines are the source of truth. Extracted rows are fully replaced
    for a source file when that file changes (detected via SHA-256 hash).
  * Manually-added events live in a separate table and are NEVER touched by a
    rescan, so user data is preserved.
  * Re-scan is idempotent: unchanged files are skipped; changed files have their
    derived courses/events/sessions rebuilt, avoiding duplicates.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .extract import parse_file, resolved_status
from .models import STATUS_CONFLICT

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "dashboard.db"
DEFAULT_DATA = BASE_DIR / "Data" / "Fall 2026 Classes"

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    filetype TEXT,
    sha256 TEXT,
    course_code TEXT,
    scanned_at REAL
);

CREATE TABLE IF NOT EXISTS courses (
    code TEXT PRIMARY KEY,
    name TEXT,
    term TEXT,
    instructor TEXT,
    instructor_email TEXT,
    tas TEXT,
    grading TEXT,       -- JSON
    notes TEXT,         -- JSON
    published TEXT,
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS class_sessions (
    id INTEGER PRIMARY KEY,
    course_code TEXT,
    kind TEXT,
    section TEXT,
    days TEXT,          -- JSON list
    start_time TEXT,
    end_time TEXT,
    location TEXT,
    start_date TEXT,
    end_date TEXT,
    online INTEGER,
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    course_code TEXT,
    ekey TEXT,          -- stable identity within a course
    title TEXT,
    type TEXT,
    weight TEXT,
    location TEXT,
    description TEXT,
    status TEXT,        -- resolved status: confirmed/tentative/tbd/conflict
    source_file TEXT,
    origin TEXT DEFAULT 'extracted',   -- 'extracted' | 'manual'
    UNIQUE(course_code, ekey, origin)
);

CREATE TABLE IF NOT EXISTS event_dates (
    id INTEGER PRIMARY KEY,
    event_id INTEGER,
    date TEXT,
    end_date TEXT,
    time TEXT,
    end_time TEXT,
    status TEXT,
    source_section TEXT,
    source_text TEXT,
    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manual_events (
    id INTEGER PRIMARY KEY,
    course_code TEXT,          -- may be NULL for general events
    title TEXT NOT NULL,
    type TEXT,
    date TEXT,
    time TEXT,
    end_time TEXT,
    location TEXT,
    description TEXT,
    created_at REAL
);
"""


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _delete_source_derived(conn: sqlite3.Connection, filename: str) -> None:
    """Remove all extracted rows derived from a given source file."""
    ev_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM events WHERE source_file=? AND origin='extracted'", (filename,))]
    for eid in ev_ids:
        conn.execute("DELETE FROM event_dates WHERE event_id=?", (eid,))
    conn.execute("DELETE FROM events WHERE source_file=? AND origin='extracted'", (filename,))
    conn.execute("DELETE FROM class_sessions WHERE source_file=?", (filename,))
    # courses / source_documents get upserted, not deleted here


def _store_course(conn: sqlite3.Connection, course) -> None:
    conn.execute(
        """INSERT INTO courses(code,name,term,instructor,instructor_email,tas,grading,notes,published,source_file)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET
             name=excluded.name, term=excluded.term, instructor=excluded.instructor,
             instructor_email=excluded.instructor_email, tas=excluded.tas,
             grading=excluded.grading, notes=excluded.notes, published=excluded.published,
             source_file=excluded.source_file""",
        (course.code, course.name, course.term, course.instructor, course.instructor_email,
         course.tas, json.dumps(course.grading), json.dumps(course.notes),
         course.published, course.source_file),
    )
    for s in course.sessions:
        conn.execute(
            """INSERT INTO class_sessions(course_code,kind,section,days,start_time,end_time,
               location,start_date,end_date,online,source_file)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (s.course_code, s.kind, s.section, json.dumps(s.days), s.start_time, s.end_time,
             s.location, s.start_date, s.end_date, int(s.online), s.source_file),
        )
    for e in course.events:
        status = resolved_status(e)
        cur = conn.execute(
            """INSERT INTO events(course_code,ekey,title,type,weight,location,description,
               status,source_file,origin)
               VALUES(?,?,?,?,?,?,?,?,?, 'extracted')
               ON CONFLICT(course_code,ekey,origin) DO UPDATE SET
                 title=excluded.title, type=excluded.type, weight=excluded.weight,
                 location=excluded.location, description=excluded.description,
                 status=excluded.status, source_file=excluded.source_file""",
            (e.course_code, e.key, e.title, e.type, e.weight, e.location, e.description,
             status, e.source_file),
        )
        eid = cur.lastrowid
        if not eid:
            row = conn.execute(
                "SELECT id FROM events WHERE course_code=? AND ekey=? AND origin='extracted'",
                (e.course_code, e.key)).fetchone()
            eid = row["id"]
        conn.execute("DELETE FROM event_dates WHERE event_id=?", (eid,))
        for c in e.candidates:
            conn.execute(
                """INSERT INTO event_dates(event_id,date,end_date,time,end_time,status,
                   source_section,source_text) VALUES(?,?,?,?,?,?,?,?)""",
                (eid, c.date, c.end_date, c.time, c.end_time, c.status,
                 c.source_section, c.source_text),
            )


def scan(data_dir: Path = DEFAULT_DATA, db_path: Path = DEFAULT_DB, force: bool = False) -> dict:
    """Scan the data folder and update the DB. Returns a summary of changes."""
    conn = connect(db_path)
    init_db(conn)

    result = {"new": [], "changed": [], "unchanged": [], "removed": [], "errors": []}
    seen_files = set()

    existing = {r["filename"]: dict(r) for r in
                conn.execute("SELECT * FROM source_documents")}

    for f in sorted(data_dir.iterdir()):
        if f.name.startswith(".") or f.suffix.lower() not in (".html", ".htm", ".pdf"):
            continue
        seen_files.add(f.name)
        digest = _sha256(f)
        prev = existing.get(f.name)
        if prev and prev["sha256"] == digest and not force:
            result["unchanged"].append(f.name)
            continue

        try:
            course = parse_file(f)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"{f.name}: {exc}")
            continue
        if not course or not course.code:
            result["errors"].append(f"{f.name}: no course code detected")
            continue

        _delete_source_derived(conn, f.name)
        _store_course(conn, course)
        conn.execute(
            """INSERT INTO source_documents(filename,filetype,sha256,course_code,scanned_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(filename) DO UPDATE SET
                 filetype=excluded.filetype, sha256=excluded.sha256,
                 course_code=excluded.course_code, scanned_at=excluded.scanned_at""",
            (f.name, f.suffix.lower().lstrip("."), digest, course.code, time.time()),
        )
        (result["changed"] if prev else result["new"]).append(f.name)

    # Detect removed source files: drop their derived data (keep manual events).
    for fname, row in existing.items():
        if fname not in seen_files:
            _delete_source_derived(conn, fname)
            # remove the course if no other source produced it
            code = row["course_code"]
            still = conn.execute(
                "SELECT 1 FROM source_documents WHERE course_code=? AND filename!=?",
                (code, fname)).fetchone()
            if not still:
                conn.execute("DELETE FROM courses WHERE code=?", (code,))
            conn.execute("DELETE FROM source_documents WHERE filename=?", (fname,))
            result["removed"].append(fname)

    conn.commit()
    conn.close()
    return result


# --- Manual events CRUD ------------------------------------------------------

def add_manual_event(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        """INSERT INTO manual_events(course_code,title,type,date,time,end_time,location,description,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (data.get("course_code"), data["title"], data.get("type", "other"),
         data.get("date"), data.get("time"), data.get("end_time"),
         data.get("location"), data.get("description", ""), time.time()),
    )
    conn.commit()
    return cur.lastrowid


def delete_manual_event(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute("DELETE FROM manual_events WHERE id=?", (event_id,))
    conn.commit()


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    summary = scan(force=force)
    print(json.dumps(summary, indent=2))
