"""Extraction dispatcher + conflict detection.

Chooses the correct parser per file type, then runs a conflict pass:
if a single event has multiple date candidates that disagree on the calendar
date, the event is flagged with status 'conflict' and all candidates are
retained so the UI can show every source.
"""
from __future__ import annotations

from pathlib import Path

from . import parse_html, parse_pdf
from .models import Course, STATUS_CONFLICT, STATUS_TBD, STATUS_TENTATIVE, STATUS_CONFIRMED


def parse_file(path: Path) -> Course | None:
    suffix = path.suffix.lower()
    if suffix in (".html", ".htm"):
        course = parse_html.parse(path)
    elif suffix == ".pdf":
        course = parse_pdf.parse(path)
    else:
        return None
    _detect_conflicts(course)
    return course


def is_conflict(event) -> bool:
    """A conflict is when different SOURCE SECTIONS give different dates.

    Multiple dates listed within a single cell (e.g. peer-critique sessions on
    Nov 16/18/23/25) are intentional multi-session items, not a conflict.
    """
    dated = [c for c in event.candidates if c.date]
    if len(dated) < 2:
        return False
    by_section: dict[str, set] = {}
    for c in dated:
        by_section.setdefault(c.source_section, set()).add(c.date)
    # collect one representative date per section; conflict if those differ
    section_dates = {min(v) for v in by_section.values()}
    return len(by_section) > 1 and len(section_dates) > 1


def resolved_status(event) -> str:
    """Compute the effective status of an event from its candidates."""
    dated = [c for c in event.candidates if c.date]
    if is_conflict(event):
        return STATUS_CONFLICT
    if not dated:
        return STATUS_TBD
    if any(c.status == STATUS_TENTATIVE for c in dated):
        return STATUS_TENTATIVE
    return STATUS_CONFIRMED


def _detect_conflicts(course: Course) -> None:
    for e in course.events:
        if is_conflict(e):
            for c in e.candidates:
                if c.date:
                    c.status = STATUS_CONFLICT


def scan_folder(folder: Path) -> list[Course]:
    courses: list[Course] = []
    for f in sorted(folder.iterdir()):
        if f.name.startswith("."):
            continue
        c = parse_file(f)
        if c and c.code:
            courses.append(c)
    return courses
