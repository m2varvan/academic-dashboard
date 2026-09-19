from pathlib import Path
import tempfile
import unittest

from scanner import parse_outline_file


class ScannerTests(unittest.TestCase):
    def test_html_extracts_course_and_event_statuses(self):
        html = """
        <html><body>
          <h1>MSCI 431 - Course Outline</h1>
          <p>Term: Fall 2026</p>
          <p>Instructor: Dr. Ada Lovelace</p>
          <p>Assignment 1 due September 24, 2026 (tentative) 10%</p>
          <p>Final Exam date TBD</p>
          <p>Monday 09:30 AM - 10:50 AM Room: E2-1306</p>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "outline.html"
            path.write_text(html, encoding="utf-8")
            parsed = parse_outline_file(path)

        self.assertEqual(parsed.course_code, "MSCI 431")
        self.assertEqual(parsed.term, "Fall 2026")
        self.assertIn("Ada", parsed.instructor)
        self.assertTrue(any(e["status"] == "tentative" for e in parsed.events))
        self.assertTrue(any(e["status"] == "tbd" for e in parsed.events))
        self.assertTrue(parsed.class_sessions)


if __name__ == "__main__":
    unittest.main()
