"""Verify the re-scan lifecycle: change detection, dedup, removal, manual preservation."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import store

src = Path(__file__).resolve().parent.parent / "Data" / "Fall 2026 Classes"
tmp = Path(tempfile.mkdtemp())
for f in src.iterdir():
    if not f.name.startswith("."):
        shutil.copy2(f, tmp / f.name)
db = tmp / "test.db"

print("scan1:", {k: len(v) for k, v in store.scan(tmp, db).items()})
print("scan2 (idempotent):", {k: len(v) for k, v in store.scan(tmp, db).items()})

# Modify one file -> should be reported as changed
target = tmp / "Fall 2026_ Search Engines.html"
target.write_text(target.read_text() + "<!-- edit -->")
r = store.scan(tmp, db)
print("scan3 after edit -> changed:", r["changed"], "| unchanged:", len(r["unchanged"]))

# Add a manual event, then rescan -> must survive
conn = store.connect(db); store.init_db(conn)
store.add_manual_event(conn, {"title": "My study block", "date": "2026-10-01", "type": "other"})
conn.close()
store.scan(tmp, db)
conn = store.connect(db)
print("manual events after rescan:", conn.execute("SELECT COUNT(*) FROM manual_events").fetchone()[0])

# Remove a file -> derived data dropped, manual preserved
(tmp / "Fall 2026_ Search Engines.html").unlink()
r = store.scan(tmp, db)
print("scan4 after removal -> removed:", r["removed"])
print("courses remaining:", conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0])
print("MSE 541 removed:", conn.execute("SELECT COUNT(*) FROM courses WHERE code='MSE 541'").fetchone()[0] == 0)
print("manual event preserved:", conn.execute("SELECT COUNT(*) FROM manual_events").fetchone()[0] == 1)
conn.close()
shutil.rmtree(tmp)
print("OK")
