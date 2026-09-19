"""One-off inspection helper: dump readable text/structure from each outline."""
import sys
from pathlib import Path
from bs4 import BeautifulSoup
import pdfplumber

DATA = Path(__file__).resolve().parent.parent / "Data" / "Fall 2026 Classes"


def dump_html(path: Path):
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in soup(["style", "script"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    print(f"\n{'='*100}\nFILE: {path.name}\nTITLE: {title}\n{'='*100}")

    # Schedule info block
    sched = soup.select_one(".schedule-info")
    if sched:
        print("\n----- SCHEDULE-INFO BLOCK -----")
        print(sched.get_text("\n", strip=True))

    # Tables
    for i, table in enumerate(soup.find_all("table")):
        print(f"\n----- TABLE {i} -----")
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if any(cells):
                print(" | ".join(cells))

    # Full text
    print("\n----- FULL TEXT -----")
    text = soup.get_text("\n", strip=True)
    lines = [l for l in text.splitlines() if l.strip()]
    print("\n".join(lines))


def dump_pdf(path: Path):
    print(f"\n{'='*100}\nFILE: {path.name}\n{'='*100}")
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            print(f"\n----- PAGE {pno} -----")
            print(page.extract_text() or "(no text)")
            for ti, table in enumerate(page.extract_tables()):
                print(f"\n--- PAGE {pno} TABLE {ti} ---")
                for row in table:
                    print(" | ".join("" if c is None else str(c) for c in row))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    for f in sorted(DATA.iterdir()):
        if target and target not in f.name:
            continue
        if f.suffix.lower() == ".html":
            dump_html(f)
        elif f.suffix.lower() == ".pdf":
            dump_pdf(f)
