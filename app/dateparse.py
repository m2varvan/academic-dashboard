"""Date and time parsing helpers with explicit uncertainty handling.

Core principle: we only emit a firm ISO date when the source gives an
unambiguous month + day. Anything marked tentative/approximate/TBD, or any
week-only reference, is preserved as such and never converted into a
fabricated calendar date.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import STATUS_CONFIRMED, STATUS_TENTATIVE, STATUS_TBD

# The academic term these outlines belong to.
TERM_YEAR = 2026

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# Markers that signal a date is NOT firm.
TENTATIVE_MARKERS = re.compile(
    r"\b(tentative|tentatively|approximate|approx\.?|around|about|~|"
    r"subject to change|may|might|estimated|expected)\b",
    re.IGNORECASE,
)
TBD_MARKERS = re.compile(
    r"\b(tba|tbd|tbs|to be announced|to be determined|to be scheduled|"
    r"will be announced|announced by the registrar|by registrar|"
    r"various|weekly|throughout the term|as scheduled)\b",
    re.IGNORECASE,
)

# "September 25", "Sep 25th", "Oct 8", "Dec 6"
_DATE_RE = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?",
    re.IGNORECASE,
)
# "11:59pm", "1:00pm", "01:00PM - 02:20PM"
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?", re.IGNORECASE)


def classify_status(text: str, has_date: bool) -> str:
    """Decide certainty status from surrounding source text."""
    if TBD_MARKERS.search(text) and not has_date:
        return STATUS_TBD
    if TENTATIVE_MARKERS.search(text):
        return STATUS_TENTATIVE
    if not has_date:
        return STATUS_TBD
    return STATUS_CONFIRMED


def find_dates(text: str, year: int = TERM_YEAR) -> list[tuple[str, str]]:
    """Return list of (iso_date, matched_snippet) for every month/day found."""
    out: list[tuple[str, str]] = []
    for m in _DATE_RE.finditer(text or ""):
        month = MONTHS[m.group(1).lower().rstrip(".")]
        day = int(m.group(2))
        try:
            iso = f"{year:04d}-{month:02d}-{day:02d}"
            # validate
            import datetime
            datetime.date(year, month, day)
        except ValueError:
            continue
        out.append((iso, m.group(0)))
    return out


# "September 22-23" / "Sep 22 - 23" -> second day shares the month of the first.
_SPAN_RE = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*[-\u2013]\s*(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def find_span(text: str, year: int = TERM_YEAR) -> tuple[str, str] | None:
    """Detect a single 'Month D1-D2' span; return (iso_start, iso_end) or None."""
    m = _SPAN_RE.search(text or "")
    if not m:
        return None
    month = MONTHS[m.group(1).lower().rstrip(".")]
    d1, d2 = int(m.group(2)), int(m.group(3))
    import datetime
    try:
        datetime.date(year, month, d1)
        datetime.date(year, month, d2)
    except ValueError:
        return None
    if d2 <= d1:
        return None
    return (f"{year:04d}-{month:02d}-{d1:02d}", f"{year:04d}-{month:02d}-{d2:02d}")


def to_24h(hour: int, minute: int, ampm: Optional[str]) -> str:
    if ampm:
        ap = ampm.lower().replace(".", "")
        if ap == "pm" and hour != 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
    return f"{hour:02d}:{minute:02d}"


def find_times(text: str) -> list[str]:
    """Return list of 'HH:MM' 24h times found in order."""
    out = []
    for m in _TIME_RE.finditer(text or ""):
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append(to_24h(hour, minute, ampm))
    return out


def parse_time_range(text: str) -> tuple[Optional[str], Optional[str]]:
    times = find_times(text)
    if not times:
        return None, None
    if len(times) == 1:
        return times[0], None
    return times[0], times[1]


# Map short/long day names to a canonical 3-letter form.
DAY_CANON = {
    "monday": "Mon", "mon": "Mon", "mondays": "Mon",
    "tuesday": "Tue", "tue": "Tue", "tues": "Tue", "tuesdays": "Tue",
    "wednesday": "Wed", "wed": "Wed", "wednesdays": "Wed",
    "thursday": "Thu", "thu": "Thu", "thur": "Thu", "thurs": "Thu", "thursdays": "Thu",
    "friday": "Fri", "fri": "Fri", "fridays": "Fri",
    "saturday": "Sat", "sat": "Sat",
    "sunday": "Sun", "sun": "Sun",
}


SINGLE_LETTER_DAY = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri"}


def parse_days(text: str) -> list[str]:
    found: list[str] = []
    t = text or ""
    # Word / abbreviation form first (Monday, Mon, Tuesdays, ...)
    for token in re.findall(r"[A-Za-z]{3,}", t):
        canon = DAY_CANON.get(token.lower())
        if canon and canon not in found:
            found.append(canon)
    # Single-letter slash form like "M/W" or "M/W/F" (only if no words matched)
    if not found and re.fullmatch(r"\s*[MTWRF](/[MTWRF])*\s*", t):
        for ch in re.findall(r"[MTWRF]", t):
            canon = SINGLE_LETTER_DAY[ch]
            if canon not in found:
                found.append(canon)
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return sorted(found, key=order.index)
