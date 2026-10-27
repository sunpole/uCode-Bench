import csv
import json
from pathlib import Path
import tempfile
import unittest

from ucode.report import write_reports
from ucode.config import Experiment


def result(status="PASS", qa="PASS", count=200, seconds=1.0):
    return {
        "schema_version": 1, "status": "COMPLETE", "config": Experiment(count=count).to_dict(),
        "environment": {"host": "<script>alert('x')</script>"},
        "stages": {"overall_seconds": 5, "single_files": [{"qa": {"status": "PASS", "pages_checked": count}} for _ in range(3)]},
        "run_directory": "<test>", "notes": ["<b>untrusted</b>"],
        "methods": [{"name": "<script>adapter</script>", "category": "merge", "status": status,
                     "reason": "<img src=x onerror=bad>", "median_seconds": seconds, "spread_seconds": 0,
                     "eligible_for_1000": True, "output_bytes": 10,
                     "trials": [{"seconds": seconds, "cpu_seconds": 0.5, "peak_rss_bytes": 1048576,
                                 "cpu_scope": "process CPU test scope", "ram_scope": "OS peak test scope",
                                 "output_bytes": 10, "qa": {"status": qa, "pages_checked": count, "errors": ["<evil>"]}, "path": "a.pdf"} for _ in range(3)]}]
    }


class ReportTests(unittest.TestCase):
    def write(self, value):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        write_reports(value, directory)
        return directory

    def test_html_escapes_all_external_text_and_csv_keeps_trials(self):
        directory = self.write(result())
        html = (directory / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Объединение готовых PDF", html)
        self.assertIn("Прямая генерация", html)
        self.assertIn("process CPU test scope", html)
        self.assertIn("OS peak test scope", html)
        with (directory / "report.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([row["trial"] for row in rows], ["1", "2", "3"])
        self.assertEqual(rows[0]["cpu_seconds"], "0.5")

    def test_qa_failure_cannot_qualify_or_rank(self):
        original = result(qa="FAIL")
        directory = self.write(original)
        saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["methods"][0]["status"], "INVALID")
        self.assertFalse(saved["methods"][0]["eligible_for_1000"])
        self.assertEqual(original["methods"][0]["status"], "PASS")
        self.assertNotIn("<td>1</td><th scope='row'>", (directory / "report.html").read_text(encoding="utf-8"))

    def test_only_200_and_strictly_below_threshold_qualifies(self):
        for count, seconds, expected in ((200, 119.999, True), (200, 120, False), (2, 1, False), (1000, 1, False)):
            with self.subTest(count=count, seconds=seconds):
                directory = self.write(result(count=count, seconds=seconds))
                saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["methods"][0]["eligible_for_1000"], expected)

    def test_refuses_overwrite(self):
        directory = self.write(result())
        existing = (directory / "report.html").read_bytes()
        with self.assertRaises(FileExistsError):
            write_reports(result(seconds=50), directory)
        self.assertEqual((directory / "report.html").read_bytes(), existing)

    def test_median_recalculated_and_threshold_fixed(self):
        value = result(seconds=121)
        value["config"]["threshold_seconds"] = 999
        value["methods"][0]["median_seconds"] = 1
        value["methods"][0]["trials"][1]["seconds"] = 125
        directory = self.write(value)
        saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["methods"][0]["median_seconds"], 121)
        self.assertEqual(saved["methods"][0]["spread_seconds"], 4)
        self.assertFalse(saved["methods"][0]["eligible_for_1000"])

    def test_cancelled_run_cannot_qualify_completed_method(self):
        value = result()
        value["status"] = "CANCELLED"
        directory = self.write(value)
        saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["methods"][0]["eligible_for_1000"])

    def test_missing_source_qa_invalidates_merge(self):
        value = result()
        value["stages"]["single_files"] = []
        directory = self.write(value)
        saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["methods"][0]["status"], "INVALID")
        self.assertFalse(saved["methods"][0]["eligible_for_1000"])

    def test_skipped_has_no_made_up_timing(self):
        value = result(status="SKIPPED")
        value["methods"][0].update(trials=[], median_seconds=None, spread_seconds=None, output_bytes=None)
        directory = self.write(value)
        saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertIsNone(saved["methods"][0]["median_seconds"])
        self.assertFalse(saved["methods"][0]["eligible_for_1000"])


if __name__ == "__main__":
    unittest.main()
