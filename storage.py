from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "dashboard.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS source_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                file_hash TEXT NOT NULL,
                file_type TEXT NOT NULL,
                last_scanned_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT UNIQUE NOT NULL,
                course_code TEXT,
                course_name TEXT,
                term TEXT,
                instructor TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS class_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id INTEGER NOT NULL,
                day_of_week TEXT,
                start_time TEXT,
                end_time TEXT,
                location TEXT,
                raw_text TEXT,
                status TEXT DEFAULT 'confirmed',
                source_file TEXT,
                source_locator TEXT,
                FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT UNIQUE NOT NULL,
                course_id INTEGER,
                title TEXT NOT NULL,
                event_type TEXT NOT NULL,
                date_text TEXT,
                date_iso TEXT,
                time_text TEXT,
                location TEXT,
                description TEXT,
                weight TEXT,
                status TEXT NOT NULL DEFAULT 'confirmed',
                source_file TEXT,
                source_locator TEXT,
                source_excerpt TEXT,
                is_manual INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_code TEXT,
                field_name TEXT,
                first_value TEXT,
                second_value TEXT,
                source_file TEXT,
                details TEXT
            );
            """
        )
