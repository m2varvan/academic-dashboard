"""Parser for the University of Waterloo LMS-style HTML course outlines.

All four HTML outlines share a common template:
  * a `.schedule-info` table with the class schedule (LEC/LAB/TUT rows)
  * an "Instructional Team" section
  * a "Tentative Class Plan" (weekly topics, sometimes with dated tasks)
  * an "Assessments & Activities" table: Component | Date | Location | Weight

We parse structurally from these anchors rather than by filename, and attach
verbatim source snippets + section names to every extracted record.
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from . import dateparse as dp
from .models import (
    Course, ClassSession, Event, DateCandidate,
    STATUS_CONFIRMED, STATUS_TENTATIVE, STATUS_TBD,
    TYPE_LECTURE, TYPE_LAB, TYPE_TUTORIAL, TYPE_ASSIGNMENT, TYPE_QUIZ,
    TYPE_MIDTERM, TYPE_EXAM, TYPE_PROJECT, TYPE_MILESTONE, TYPE_PRESENTATION,
    TYPE_REPORT, TYPE_PARTICIPATION, TYPE_OTHER,
)

KIND_MAP = {"LEC": TYPE_LECTURE, "LAB": TYPE_LAB, "TUT": TYPE_TUTORIAL}


def _classify_event_type(title: str) -> str:
    t = title.lower()
    if "quiz" in t:
        return TYPE_QUIZ
    if "midterm" in t or re.search(r"\bmt\b", t) or "mid-term" in t:
        return TYPE_MIDTERM
    if "final exam" in t or t.strip() == "exam" or "examination" in t or "final" in t:
        return TYPE_EXAM
    if "milestone" in t or re.search(r"\bm\d\b", t):
        return TYPE_MILESTONE
    if "presentation" in t or "design review" in t or "q&a" in t:
        return TYPE_PRESENTATION
    if "report" in t:
        return TYPE_REPORT
    if "project" in t:
        return TYPE_PROJECT
    if "participation" in t or "in-class" in t or "activities" in t or "activity" in t:
        return TYPE_PARTICIPATION
    if "assignment" in t or "homework" in t or "walkthrough" in t:
        return TYPE_ASSIGNMENT
    return TYPE_OTHER


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _section_text(soup: BeautifulSoup, heading_regex: str) -> str:
    """Grab text from a heading until the next heading of same/higher level."""
    for h in soup.find_all(re.compile(r"^h[1-4]$")):
        if re.search(heading_regex, h.get_text(" ", strip=True), re.IGNORECASE):
            parts = []
            for sib in h.next_siblings:
                if getattr(sib, "name", None) and re.match(r"^h[1-4]$", sib.name):
                    break
                if hasattr(sib, "get_text"):
                    parts.append(sib.get_text(" ", strip=True))
            return _clean(" ".join(parts))
    return ""


def _find_assessment_table(soup: BeautifulSoup):
    """Locate the table whose header mentions Component/Activity + Weight."""
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        htext = header.get_text(" ", strip=True).lower()
        if ("component" in htext or "activity" in htext) and "weight" in htext:
            return table
    return None


def parse(path: Path) -> Course:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["style", "script"]):
        tag.decompose()

    fname = path.name

    # --- Course identity ---
    title = _clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    name = re.sub(r"^Fall\s*2026:\s*", "", title, flags=re.IGNORECASE).strip()

    code = ""
    m = re.search(r"\b([A-Z]{2,4})\s*(\d{3})\b", soup.get_text(" ", strip=True))
    if m:
        code = f"{m.group(1)} {m.group(2)}"

    term = "Fall 2026"
    pub = ""
    pm = re.search(r"Published\s+([A-Za-z]+ \d{1,2},? \d{4})", soup.get_text(" ", strip=True))
    if pm:
        pub = pm.group(1)

    course = Course(code=code, name=name, term=term, source_file=fname, published=pub)

    # --- Class schedule (.schedule-info table) ---
    sched = soup.select_one(".schedule-info table") or soup.find("table")
    if sched:
        rows = sched.find_all("tr")
        for row in rows[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            course_cell = cells[0]
            km = re.search(r"\[(LEC|LAB|TUT)\]", course_cell)
            kind = KIND_MAP.get(km.group(1), TYPE_LECTURE) if km else TYPE_LECTURE
            sec_m = re.search(r"\b(\d{3})\b", course_cell)
            section = sec_m.group(1) if sec_m else ""

            joined = " ".join(cells)
            online = "online" in joined.lower()
            days = dp.parse_days(cells[1]) if len(cells) > 1 else []

            start_t = end_t = None
            location = None
            start_d = end_d = None
            # time cell usually contains 'HH:MMAM - HH:MMPM'
            for c in cells[1:]:
                if re.search(r"\d{1,2}:\d{2}\s*[ap]m", c, re.IGNORECASE):
                    start_t, end_t = dp.parse_time_range(c)
                dr = re.search(r"([A-Z][a-z]{2} \d{1,2})\s*-\s*([A-Z][a-z]{2} \d{1,2})", c)
                if dr:
                    d1 = dp.find_dates(dr.group(1))
                    d2 = dp.find_dates(dr.group(2))
                    if d1:
                        start_d = d1[0][0]
                    if d2:
                        end_d = d2[0][0]
            # location: cell that looks like a room code and isn't the time/day cell
            for c in cells[2:]:
                if re.match(r"^[A-Z]{2,4}\s*\d{3,4}$", c):
                    location = c
                    break
            if not location and online:
                location = "Online"

            course.sessions.append(ClassSession(
                course_code=code, kind=kind, section=section, days=days,
                start_time=start_t, end_time=end_t, location=location,
                start_date=start_d, end_date=end_d, online=online,
                source_file=fname,
            ))

    # --- Instructional team ---
    team = _section_text(soup, r"Instructional Team")
    # Format A: "Instructor : Ada Hurst ( adahurst@uwaterloo.ca )"
    # Format B: "Instructor : Dr. Mehrdad Pirnia: mpirnia@uwaterloo.ca"
    im = re.search(
        r"Instructor\s*:?\s*(?:Dr\.?\s*)?([A-Z][a-zA-Z .'\-]+?)\s*[:(\s]\s*([\w.\-]+@[\w.\-]+)",
        team,
    )
    if im:
        course.instructor = _clean(im.group(1)).rstrip(" :(")
        course.instructor_email = im.group(2)
    else:
        # Fall back to the schedule instructor column (last non-empty cells).
        if sched:
            last_row = sched.find_all("tr")[-1]
            cells = [_clean(c.get_text(" ", strip=True)) for c in last_row.find_all(["td", "th"])]
            instr_cell = cells[-1] if cells else ""
            em = re.search(r"([\w.\-]+@[\w.\-]+)", instr_cell)
            nm = re.match(r"([A-Z][a-z]+(?: [A-Z][a-z.\-]+)+)", instr_cell)
            if nm:
                course.instructor = nm.group(1)
            if em:
                course.instructor_email = em.group(1)

    # Teaching assistants (exclude the instructor and their email).
    ta_seg = team
    tam = re.search(r"(?:Teaching Assistants?|TAs?)\s*:?(.*)", team, re.IGNORECASE)
    if tam:
        ta_seg = tam.group(1)
    ta_emails = [e for e in re.findall(r"([\w.\-]+@uwaterloo\.ca)", ta_seg)
                 if e != course.instructor_email]
    if ta_emails:
        course.tas = ", ".join(dict.fromkeys(ta_emails))

    # --- Assessments table -> events + grading ---
    atable = _find_assessment_table(soup)
    if atable:
        rows = atable.find_all("tr")
        header = [_clean(c.get_text(" ", strip=True)).lower() for c in rows[0].find_all(["td", "th"])]

        def col_index(*names):
            for i, h in enumerate(header):
                if any(n in h for n in names):
                    return i
            return None

        ci_comp = col_index("component", "activity") or 0
        ci_date = col_index("date", "due")
        ci_loc = col_index("location", "submission")
        ci_wt = col_index("weight")

        for row in rows[1:]:
            cells = [_clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
            if not any(cells):
                continue
            # normalize leading dashes used for sub-items (---IP - Milestone 1)
            comp = cells[ci_comp] if ci_comp < len(cells) else cells[0]
            comp = re.sub(r"^[-\u2013\s]+", "", comp).strip()
            if not comp:
                continue
            date_txt = cells[ci_date] if ci_date is not None and ci_date < len(cells) else ""
            loc_txt = cells[ci_loc] if ci_loc is not None and ci_loc < len(cells) else ""
            wt_txt = cells[ci_wt] if ci_wt is not None and ci_wt < len(cells) else ""
            wt_txt = re.sub(r"^[-\u2013\s]+", "", wt_txt).strip()

            # record grading breakdown
            course.grading.append({
                "component": comp,
                "weight": wt_txt or None,
                "date": date_txt or None,
            })

            etype = _classify_event_type(comp)
            dates = dp.find_dates(date_txt)
            times = dp.find_times(date_txt)
            status = dp.classify_status(date_txt, has_date=bool(dates))

            candidates: list[DateCandidate] = []
            snippet = f"{comp} | {date_txt} | {wt_txt}".strip(" |")
            span = dp.find_span(date_txt)
            if dates:
                if span:
                    # e.g. "September 22-23" -> a single spanning item
                    candidates.append(DateCandidate(
                        date=span[0], end_date=span[1],
                        time=times[0] if times else None, status=status,
                        source_section="Assessments & Activities", source_text=snippet,
                    ))
                else:
                    # discrete dates (e.g. Nov 16, 18, 23, 25) -> one candidate each
                    for iso, _ in dates:
                        candidates.append(DateCandidate(
                            date=iso, time=times[0] if times else None, status=status,
                            source_section="Assessments & Activities", source_text=snippet,
                        ))
            else:
                candidates.append(DateCandidate(
                    date=None, status=status,
                    source_section="Assessments & Activities",
                    source_text=f"{comp} | {date_txt or '(no date given)'} | {wt_txt}".strip(" |"),
                ))


            course.events.append(Event(
                course_code=code, title=comp, type=etype,
                weight=wt_txt or None, location=loc_txt or None,
                description=date_txt, source_file=fname,
                candidates=candidates, key=_event_key(comp),
            ))

    # --- Dated tasks inside the "Tentative Class Plan" table ---
    _parse_class_plan(soup, course, fname)

    # --- Notes ---
    for label, rx in [("Course Description", r"Course Description"),
                      ("Late / Missed Content", r"Late / Missed")]:
        txt = _section_text(soup, rx)
        if txt:
            course.notes.append(f"{label}: {txt[:600]}")

    return course


def _event_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def _parse_class_plan(soup: BeautifulSoup, course: Course, fname: str) -> None:
    """The class-plan table sometimes carries dated tasks (e.g. 'MT1 (Oct 6th)').

    These are captured as additional date candidates so the conflict detector
    can compare them against the assessment-table dates.
    """
    plan_table = None
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        htext = header.get_text(" ", strip=True).lower()
        if "week" in htext and ("topic" in htext or "task" in htext):
            plan_table = table
            break
    if not plan_table:
        return

    for row in plan_table.find_all("tr")[1:]:
        cells = [_clean(c.get_text(" ", strip=True)) for c in row.find_all(["td", "th"])]
        task_text = " ".join(cells)
        dates = dp.find_dates(task_text)
        if not dates:
            continue
        # only interested in graded markers in the task column
        low = task_text.lower()
        if not any(k in low for k in ["mt", "midterm", "quiz", "exam", "assignment", "project", "milestone"]):
            continue
        title = None
        etype = TYPE_OTHER
        if re.search(r"\bmt\s*1\b|midterm 1", low):
            title, etype = "Midterm 1", TYPE_MIDTERM
        elif re.search(r"\bmt\s*2\b|midterm 2", low):
            title, etype = "Midterm 2", TYPE_MIDTERM
        if not title:
            continue
        # attach as a candidate to the matching existing event (for conflict check)
        target = next((e for e in course.events if e.title.lower().startswith(title.lower())), None)
        cand = DateCandidate(
            date=dates[0][0], status=STATUS_TENTATIVE if "tentative" in low else STATUS_CONFIRMED,
            source_section="Tentative Class Plan",
            source_text=_clean(task_text),
        )
        if target:
            target.candidates.append(cand)
        else:
            course.events.append(Event(
                course_code=course.code, title=title, type=etype,
                source_file=fname, candidates=[cand], key=_event_key(title),
            ))
