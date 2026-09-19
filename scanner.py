from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from pypdf import PdfReader

COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,6}\s?-?\d{3}[A-Z]?)\b")
TERM_RE = re.compile(r"\b((?:Winter|Spring|Summer|Fall|Autumn)\s+20\d{2})\b", re.IGNORECASE)
INSTRUCTOR_RE = re.compile(r"\bInstructor(?:s)?\s*:?\s*(.+)", re.IGNORECASE)
DATE_RE = re.compile(
    r"((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*20\d{2})?|"
    r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/20\d{2})?\b|\bWeek\s+\d+\b)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\s*[-–]\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?\b")
WEIGHT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?\s*%)\b")
DAY_RE = re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)

EVENT_TYPE_KEYWORDS = {
    "lecture": "lecture",
    "class": "lecture",
    "lab": "lab",
    "tutorial": "tutorial",
    "assignment": "assignment",
    "quiz": "quiz",
    "midterm": "midterm",
    "exam": "exam",
    "project": "project",
    "presentation": "presentation",
    "report": "report",
    "milestone": "milestone",
}


@dataclass
class ParsedCourse:
    source_file: str
    file_hash: str
    file_type: str
    course_code: str | None = None
    course_name: str | None = None
    term: str | None = None
    instructor: str | None = None
    notes: str | None = None
    events: list[dict] = field(default_factory=list)
    class_sessions: list[dict] = field(default_factory=list)
    extraction_notes: list[str] = field(default_factory=list)


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_outline_file(path: Path) -> ParsedCourse:
    file_hash = sha256_of_file(path)
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return parse_html(path, file_hash)
    if suffix == ".pdf":
        return parse_pdf(path, file_hash)
    raise ValueError(f"Unsupported file type: {path}")


def parse_html(path: Path, file_hash: str) -> ParsedCourse:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    course = ParsedCourse(source_file=path.name, file_hash=file_hash, file_type="html")
    _extract_course_identity(lines, course)
    _extract_from_lines(lines, course, locator_prefix="line")
    _extract_from_html_tables(soup, course)
    return course


def parse_pdf(path: Path, file_hash: str) -> ParsedCourse:
    reader = PdfReader(str(path))
    course = ParsedCourse(source_file=path.name, file_hash=file_hash, file_type="pdf")
    all_lines: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_lines = [line.strip() for line in text.splitlines() if line.strip()]
        all_lines.extend(page_lines)
        _extract_from_lines(page_lines, course, locator_prefix=f"page {idx} line")
    _extract_course_identity(all_lines, course)
    return course


def _extract_course_identity(lines: Iterable[str], course: ParsedCourse) -> None:
    joined = "\n".join(lines)
    if not course.course_code:
        m = COURSE_CODE_RE.search(joined)
        if m:
            course.course_code = m.group(1).replace("-", " ").strip()

    if not course.term:
        m = TERM_RE.search(joined)
        if m:
            course.term = m.group(1).strip()

    if not course.instructor:
        for line in lines:
            m = INSTRUCTOR_RE.search(line)
            if m:
                course.instructor = m.group(1).strip()
                break

    if not course.course_name and course.course_code:
        for line in lines:
            if course.course_code in line:
                candidate = line.replace(course.course_code, "").strip(" -:|\t")
                if candidate and len(candidate.split()) >= 2:
                    course.course_name = candidate
                    break
    if not course.course_name:
        for line in lines:
            if "course outline" in line.lower() and len(line.split()) > 2:
                course.course_name = line.strip()
                break


def _extract_from_lines(lines: Iterable[str], course: ParsedCourse, locator_prefix: str) -> None:
    term_year = _year_from_term(course.term)
    for idx, line in enumerate(lines, start=1):
        lowered = line.lower()
        event_type = _event_type_from_text(lowered)
        has_date = bool(DATE_RE.search(line)) or _has_tbd_marker(lowered)
        if event_type and has_date:
            date_text, date_iso = _extract_date(line, term_year)
            status = _derive_status(line, date_text)
            event = {
                "title": _derive_event_title(line, event_type),
                "event_type": event_type,
                "date_text": date_text,
                "date_iso": date_iso,
                "time_text": _extract_time(line),
                "location": _extract_location(line),
                "description": line,
                "weight": _extract_weight(line),
                "status": status,
                "source_locator": f"{locator_prefix} {idx}",
                "source_excerpt": line[:500],
            }
            course.events.append(event)

        if DAY_RE.search(line) and TIME_RE.search(line):
            course.class_sessions.append(
                {
                    "day_of_week": _extract_days(line),
                    "start_time": _extract_time_start(line),
                    "end_time": _extract_time_end(line),
                    "location": _extract_location(line),
                    "raw_text": line,
                    "status": _derive_status(line, None),
                    "source_locator": f"{locator_prefix} {idx}",
                }
            )


def _extract_from_html_tables(soup: BeautifulSoup, course: ParsedCourse) -> None:
    term_year = _year_from_term(course.term)
    for table_idx, table in enumerate(soup.find_all("table"), start=1):
        rows = table.find_all("tr")
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])] if rows else []
        for row_idx, row in enumerate(rows[1:] if headers else rows, start=1):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not cells:
                continue
            row_text = " | ".join(cells)
            lowered = row_text.lower()
            event_type = _event_type_from_text(lowered)
            has_date = bool(DATE_RE.search(row_text)) or _has_tbd_marker(lowered)
            if event_type and has_date:
                date_text, date_iso = _extract_date(row_text, term_year)
                course.events.append(
                    {
                        "title": _derive_event_title(row_text, event_type),
                        "event_type": event_type,
                        "date_text": date_text,
                        "date_iso": date_iso,
                        "time_text": _extract_time(row_text),
                        "location": _extract_location(row_text),
                        "description": row_text,
                        "weight": _extract_weight(row_text),
                        "status": _derive_status(row_text, date_text),
                        "source_locator": f"table {table_idx} row {row_idx}",
                        "source_excerpt": row_text[:500],
                    }
                )


def _event_type_from_text(lowered: str) -> str | None:
    for key, value in EVENT_TYPE_KEYWORDS.items():
        if key in lowered:
            return value
    if "deliverable" in lowered:
        return "deliverable"
    return None


def _extract_date(text: str, term_year: int | None) -> tuple[str | None, str | None]:
    m = DATE_RE.search(text)
    if not m:
        if _has_tbd_marker(text.lower()):
            return "TBD", None
        return None, None
    date_text = m.group(1)
    if date_text.lower().startswith("week"):
        return date_text, None
    try:
        parsed = _parse_to_iso(date_text, term_year)
    except ValueError:
        return date_text, None
    return date_text, parsed


def _parse_to_iso(date_text: str, term_year: int | None) -> str:
    clean = date_text.strip()
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", clean):
        return clean
    if re.match(r"^\d{1,2}/\d{1,2}/20\d{2}$", clean):
        dt = datetime.strptime(clean, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    if re.match(r"^\d{1,2}/\d{1,2}$", clean):
        if term_year is None:
            raise ValueError("missing term year")
        dt = datetime.strptime(f"{clean}/{term_year}", "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    if re.search(r",\s*20\d{2}$", clean):
        dt = datetime.strptime(clean, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    if term_year is None:
        raise ValueError("missing term year")
    try:
        dt = datetime.strptime(f"{clean}, {term_year}", "%B %d, %Y")
    except ValueError:
        dt = datetime.strptime(f"{clean}, {term_year}", "%b %d, %Y")
    return dt.strftime("%Y-%m-%d")


def _derive_status(text: str, date_text: str | None) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["tentative", "approximately", "approx", "subject to change"]):
        return "tentative"
    if _has_tbd_marker(lowered) or date_text == "TBD":
        return "tbd"
    return "confirmed"


def _has_tbd_marker(lowered: str) -> bool:
    return any(k in lowered for k in ["tbd", "to be announced", "will be announced", "announced later"])


def _derive_event_title(text: str, event_type: str) -> str:
    parts = [p.strip() for p in re.split(r"[|:–-]", text) if p.strip()]
    for part in parts:
        if event_type in part.lower():
            return part[:180]
    return parts[0][:180] if parts else event_type.title()


def _extract_time(text: str) -> str | None:
    m = TIME_RE.search(text)
    return m.group(0) if m else None


def _extract_time_start(text: str) -> str | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    return re.split(r"[-–]", m.group(0))[0].strip()


def _extract_time_end(text: str) -> str | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    return re.split(r"[-–]", m.group(0))[1].strip()


def _extract_days(text: str) -> str | None:
    matches = DAY_RE.findall(text)
    if not matches:
        return None
    deduped = []
    for d in matches:
        title = d.title()
        if title not in deduped:
            deduped.append(title)
    return ", ".join(deduped)


def _extract_weight(text: str) -> str | None:
    m = WEIGHT_RE.search(text)
    return m.group(1) if m else None


def _extract_location(text: str) -> str | None:
    m = re.search(r"\b(?:room|location|online|zoom)\b\s*:?\s*([\w\-\s()]+)", text, re.IGNORECASE)
    return m.group(0).strip() if m else None


def _year_from_term(term: str | None) -> int | None:
    if not term:
        return None
    m = re.search(r"(20\d{2})", term)
    return int(m.group(1)) if m else None
