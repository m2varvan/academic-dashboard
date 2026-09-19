"""Parser for the MSE 333 PDF course outline (UW Simulation Analysis & Design).

The PDF has:
  * a header block with instructor, TAs, and a Lecture/Tutorial/Lab schedule
  * a Marking Scheme table
  * a Course Schedule table (Week of | Theme | Topics | Assignments/Evaluation)
    that carries the concrete dated deliverables.

The schedule header explicitly says "Date of topics are approximate", so
lecture rows are treated as tentative, while the dated deliverable cells
(with '11:59pm' due times) are firm unless marked TBS.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from . import dateparse as dp
from .models import (
    Course, ClassSession, Event, DateCandidate,
    STATUS_CONFIRMED, STATUS_TENTATIVE, STATUS_TBD,
    TYPE_LECTURE, TYPE_LAB, TYPE_TUTORIAL, TYPE_ASSIGNMENT,
    TYPE_MIDTERM, TYPE_EXAM, TYPE_PROJECT, TYPE_HOLIDAY,
)


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip())


def _event_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def parse(path: Path) -> Course:
    fname = path.name
    with pdfplumber.open(path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    full = "\n".join(pages)

    code = ""
    m = re.search(r"\b([A-Z]{2,4})\s*(\d{3})\b", full)
    if m:
        code = f"{m.group(1)} {m.group(2)}"

    name = ""
    nm = re.search(r"Fall\s*2026:\s*(.+)", full)
    if nm:
        name = _clean(nm.group(1).split("\n")[0])

    course = Course(code=code, name=name, term="Fall 2026", source_file=fname)

    im = re.search(r"Instructor\s+([A-Za-z .'-]+)", full)
    if im:
        course.instructor = _clean(im.group(1).split("email")[0])
    em = re.search(r"email\s+([\w.\-]+@[\w.\-]+)", full)
    if em:
        course.instructor_email = em.group(1)
    tas = re.findall(r"([\w.\-]+@uwaterloo\.ca)", full)
    course.tas = ", ".join(t for t in dict.fromkeys(tas) if t != course.instructor_email)

    # --- Schedule (Lecture / Tutorial / Lab lines) ---
    for kind_label, kind in [("Lecture", TYPE_LECTURE), ("Tutorial", TYPE_TUTORIAL), ("Lab", TYPE_LAB)]:
        # e.g. "Lecture M/W 1:00pm to 2:20pm CPH 3681"
        rx = re.compile(kind_label + r"\s+([A-Za-z/]+)?\s*[:]?\s*(\d{1,2}:\d{2}\s*[ap]m)\s*(?:to|-|–)\s*(\d{1,2}:\d{2}\s*[ap]m)\s*([A-Z]{2,4}\s*\d{3,4})?", re.IGNORECASE)
        sm = rx.search(full)
        if sm:
            days = dp.parse_days(sm.group(1) or "")
            start_t, _ = dp.parse_time_range(sm.group(2))
            end_t, _ = dp.parse_time_range(sm.group(3))
            loc = _clean(sm.group(4)) if sm.group(4) else None
            course.sessions.append(ClassSession(
                course_code=code, kind=kind, days=days,
                start_time=start_t, end_time=end_t, location=loc,
                start_date="2026-09-09", end_date="2026-12-08",
                source_file=fname,
            ))

    # --- Marking scheme ---
    for comp, wt in re.findall(r"(Assignments|Project|Midterm exam|Final Exam|Classworks and Pop\s*quizzes|Lab activities)\s+(\d{1,3}%)", full):
        course.grading.append({"component": _clean(comp), "weight": wt, "date": None})

    # --- Dated deliverables from the schedule table ---
    _extract_deliverables(full, course, fname)

    # --- Reading week ---
    rw = re.search(r"(W\d+:\s*[A-Za-z]+ \d{1,2}(?:\s*&\s*\d{1,2})?)\s*Reading Week", full)
    if rw:
        dates = dp.find_dates(rw.group(1))
        if dates:
            course.events.append(Event(
                course_code=code, title="Reading Week", type=TYPE_HOLIDAY,
                source_file=fname, key="reading-week",
                candidates=[DateCandidate(
                    date=dates[0][0], end_date=dates[-1][0] if len(dates) > 1 else None,
                    status=STATUS_CONFIRMED, source_section="Course Schedule",
                    source_text=_clean(rw.group(0)),
                )],
            ))

    course.notes.append(
        "Schedule note from source: 'Date of topics are approximate'. "
        "Lecture topic weeks are tentative; dated deliverables below are as stated."
    )
    return course


def _mk_due_event(course, title, etype, iso, time, snippet, fname, status=STATUS_CONFIRMED, location=None):
    course.events.append(Event(
        course_code=course.code, title=title, type=etype,
        location=location, description=snippet, source_file=fname,
        key=_event_key(title),
        candidates=[DateCandidate(
            date=iso, time=time, status=status,
            source_section="Course Schedule", source_text=snippet,
        )],
    ))


def _extract_deliverables(full: str, course: Course, fname: str) -> None:
    # The PDF's schedule table interleaves week markers (e.g. "W2: Sep 14 & 16
    # Lab") between a deliverable label and its due date. We strip those week
    # markers and the Lec/Lab/Tut column letters so the label sits next to its
    # own due date, then collapse whitespace.
    text = full
    text = re.sub(r"W\d+:\s*[A-Za-z]+ \d{1,2}(?:\s*&\s*\d{1,2})?", " ", text)
    text = re.sub(r"\b(Lec|Lab|Tut)\b", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Assignment N (due: Mon D, 11:59pm) OR Assignment N (Mon D, 11:59pm)
    for m in re.finditer(r"Assignment\s*(\d)\s*\((?:due:?\s*)?([A-Za-z]+ \d{1,2})[, ]+(\d{1,2}:\d{2}\s*[ap]m)?", text, re.IGNORECASE):
        dates = dp.find_dates(m.group(2))
        if not dates:
            continue
        t, _ = dp.parse_time_range(m.group(3) or "")
        _mk_due_event(course, f"Assignment {m.group(1)}", TYPE_ASSIGNMENT,
                      dates[0][0], t, _clean(m.group(0)), fname)

    # Enrolling project groups ... Due date: Sep 18, 11:59pm
    pg = re.search(r"Enrolling project groups\s*Due date:\s*([A-Za-z]+ \d{1,2})[, ]+(\d{1,2}:\d{2}\s*[ap]m)?", text, re.IGNORECASE)
    if pg:
        dates = dp.find_dates(pg.group(1))
        if dates:
            t, _ = dp.parse_time_range(pg.group(2) or "")
            _mk_due_event(course, "Project group enrollment", TYPE_PROJECT,
                          dates[0][0], t, _clean(pg.group(0)), fname)

    # Midterm Exam (Lec 1,2,3,4) ... Oct 26, 1:00pm to 2:20pm RCH 301
    mt = re.search(r"Midterm Exam[^A-Za-z]*\([^)]*\)\s*([A-Za-z]+ \d{1,2})[, ]+(\d{1,2}:\d{2}\s*[ap]m)\s*(?:to|-|–)\s*(\d{1,2}:\d{2}\s*[ap]m)?\s*([A-Z]{2,4}\s*\d{3,4})?", text, re.IGNORECASE)
    if mt:
        dates = dp.find_dates(mt.group(1))
        if dates:
            t, _ = dp.parse_time_range(mt.group(2))
            loc = _clean(mt.group(4)) if mt.group(4) else None
            _mk_due_event(course, "Midterm Exam", TYPE_MIDTERM, dates[0][0], t,
                          _clean(mt.group(0)), fname, location=loc)

    # Project report ... Due: Dec 6, 11:59pm
    pr = re.search(r"Project report\b.*?Due:\s*([A-Za-z]+ \d{1,2})[, ]+(\d{1,2}:\d{2}\s*[ap]m)?", text, re.IGNORECASE)
    if pr:
        dates = dp.find_dates(pr.group(1))
        if dates:
            t, _ = dp.parse_time_range(pr.group(2) or "")
            _mk_due_event(course, "Project report", TYPE_PROJECT, dates[0][0], t,
                          _clean(pr.group(0)), fname)

    # Final exam TBS by Registrar
    if re.search(r"Final exam\s*TB[SD]", text, re.IGNORECASE):
        course.events.append(Event(
            course_code=course.code, title="Final Exam", type=TYPE_EXAM,
            source_file=fname, key="final-exam",
            candidates=[DateCandidate(
                date=None, status=STATUS_TBD, source_section="Course Schedule",
                source_text="Final exam TBS by Registrar",
            )],
        ))
