"""Quick harness to print extraction output for manual verification."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extract import scan_folder, resolved_status

DATA = Path(__file__).resolve().parent.parent / "Data" / "Fall 2026 Classes"

courses = scan_folder(DATA)
for c in courses:
    print(f"\n{'='*80}\n{c.code} — {c.name}\n  instructor: {c.instructor} <{c.instructor_email}>")
    print(f"  TAs: {c.tas}")
    print(f"  sessions ({len(c.sessions)}):")
    for s in c.sessions:
        print(f"    [{s.kind}] {s.days} {s.start_time}-{s.end_time} @ {s.location} online={s.online}")
    print(f"  events ({len(c.events)}):")
    for e in c.events:
        st = resolved_status(e)
        ds = " / ".join(f"{cd.date or 'None'}({cd.status},{cd.source_section})" for cd in e.candidates)
        print(f"    - {e.title} [{e.type}] wt={e.weight} status={st}")
        print(f"        candidates: {ds}")
    print(f"  grading rows: {len(c.grading)}")
