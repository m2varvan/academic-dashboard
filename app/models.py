"""Normalized data structures shared between parsers and the data store.

These dataclasses are the intermediate representation produced by parsers.
They are deliberately independent of the SQLite schema so the extraction
layer and storage layer can evolve separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# --- Status vocabulary -------------------------------------------------------
# Every event carries an explicit certainty status. We never silently convert
# a tentative/approximate/TBD marker into a firm date.
STATUS_CONFIRMED = "confirmed"
STATUS_TENTATIVE = "tentative"   # source says tentative / approximate / ~ / week N
STATUS_TBD = "tbd"               # source explicitly has no date (TBA / TBD / various)
STATUS_CONFLICT = "conflict"     # multiple sources disagree on the date

# --- Event type vocabulary ---------------------------------------------------
TYPE_LECTURE = "lecture"
TYPE_LAB = "lab"
TYPE_TUTORIAL = "tutorial"
TYPE_ASSIGNMENT = "assignment"
TYPE_QUIZ = "quiz"
TYPE_MIDTERM = "midterm"
TYPE_EXAM = "exam"
TYPE_PROJECT = "project"
TYPE_MILESTONE = "milestone"
TYPE_PRESENTATION = "presentation"
TYPE_REPORT = "report"
TYPE_PARTICIPATION = "participation"
TYPE_OTHER = "other"
TYPE_HOLIDAY = "holiday"  # reading week etc.


@dataclass
class DateCandidate:
    """A single candidate date for an event, tagged with where it came from.

    Multiple candidates on one event => potential conflict. `date` may be None
    when the source states a deliverable exists but gives no resolvable date.
    """
    date: Optional[str]            # ISO 'YYYY-MM-DD' or None
    end_date: Optional[str] = None  # for multi-day / range items
    time: Optional[str] = None     # 'HH:MM' 24h, or None
    end_time: Optional[str] = None
    status: str = STATUS_CONFIRMED
    source_section: str = ""       # e.g. 'Assessments & Activities'
    source_text: str = ""          # verbatim snippet for verification

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    """An academic deliverable / assessment / graded item / holiday."""
    course_code: str
    title: str
    type: str
    weight: Optional[str] = None            # e.g. '20%' as stated
    location: Optional[str] = None
    description: str = ""
    source_file: str = ""
    candidates: list[DateCandidate] = field(default_factory=list)
    # a stable identity within a course used for dedup across re-scans
    key: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["candidates"] = [c.to_dict() for c in self.candidates]
        return d


@dataclass
class ClassSession:
    """A recurring weekly meeting (lecture/lab/tutorial)."""
    course_code: str
    kind: str                # lecture / lab / tutorial
    section: str = ""
    days: list[str] = field(default_factory=list)   # ['Mon','Wed']
    start_time: Optional[str] = None                 # 'HH:MM'
    end_time: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None                 # term range
    end_date: Optional[str] = None
    online: bool = False
    source_file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Course:
    code: str
    name: str
    term: str = ""
    instructor: str = ""
    instructor_email: str = ""
    tas: str = ""
    grading: list[dict] = field(default_factory=list)   # [{component, weight, comment}]
    notes: list[str] = field(default_factory=list)
    source_file: str = ""
    published: str = ""
    sessions: list[ClassSession] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sessions"] = [s.to_dict() for s in self.sessions]
        d["events"] = [e.to_dict() for e in self.events]
        return d
