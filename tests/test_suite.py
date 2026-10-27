import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ucode.suite import build_comparison, run_suite, write_comparison


def method(name="pypdf", category="merge", seconds=1.0, status="PASS", count=200, directory=None):
    return {"name": name, "category": category, "status": status, "reason": "<unsupported>" if status != "PASS" else "",
            "trials": [] if status == "SKIPPED" else [
                {"seconds": seconds, "cpu_seconds": seconds / 2, "peak_rss_bytes": 1048576,
                 "output_bytes": 1234, "path": str(directory / f"{name}-{index}.pdf") if directory else "",
                 "qa": {"status": "PASS" if status == "PASS" else "FAIL", "pages_checked": count,
                        "decoded_samples": [{"page": 1}, {"page": 101}, {"page": 200}]}} for index in range(3)]}


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-suite-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_scaling_and_baseline_are_measured_and_category_specific(self):
        small = {"methods": [method(), method("fast", seconds=0.5), method("Direct PDF", category="direct", seconds=2)]}
        large = {"methods": [method(seconds=4, count=1000), method("fast", seconds=1, count=1000),
                              method("Direct PDF", category="direct", seconds=8, count=1000)]}
        rows = build_comparison(small, large, self.root)
        fast = next(row for row in rows if row["name"] == "fast")
        self.assertEqual(fast["results"]["200"]["speedup_vs_pypdf"], 2)
        self.assertEqual(fast["results"]["1000"]["speedup_vs_pypdf"], 4)
        self.assertEqual(fast["time_growth_1000_vs_200"], 2)
        self.assertEqual(fast["per_page_growth_1000_vs_200"], 0.4)
        self.assertEqual(fast["results"]["1000"]["qa_pages_checked"], 3000)
        direct = next(row for row in rows if row["category"] == "direct")
        self.assertIsNone(direct["results"]["200"]["speedup_vs_pypdf"])

    def test_missing_or_invalid_results_are_not_extrapolated(self):
        small = {"methods": [method("missing", status="SKIPPED"), method("bad", status="INVALID")]}
        rows = build_comparison(small, None, self.root, missing_1000_reason="No QA qualification")
        self.assertTrue(all(row["results"]["1000"]["status"] == "SKIPPED" for row in rows))
        self.assertTrue(all(row["results"]["1000"]["median_seconds"] is None for row in rows))
        self.assertTrue(all(row["time_growth_1000_vs_200"] is None for row in rows))
        self.assertTrue(all(row["results"]["200"]["speedup_vs_pypdf"] is None for row in rows))

    def test_portable_links_are_inside_suite_only(self):
        inside = self.root / "runs" / "200"
        rows = build_comparison({"methods": [method(directory=inside)]}, None, self.root,
                                path_200=inside / "report.json")
        result = rows[0]["results"]["200"]
        self.assertEqual(result["pdf_files"][0], "runs/200/pypdf-0.pdf")
        self.assertEqual(result["report_html"], "runs/200/report.html")
        external = build_comparison({"methods": [method(directory=self.root.parent)]}, None, self.root)
        self.assertEqual(external[0]["results"]["200"]["pdf_files"], [])

    def test_suite_uses_200_qualification_before_1000(self):
        calls = []
        def run(output, config, **kwargs):
            calls.append((config.count, kwargs.get("allowed_methods")))
            directory = Path(output) / f"run-{config.count}"
            directory.mkdir(parents=True)
            report = {"status": "COMPLETE", "methods": [method(count=config.count, directory=directory)]}
            (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
            return directory
        with patch("ucode.suite.run_experiment", side_effect=run), patch("ucode.suite.load_qualifying_methods", return_value=["pypdf"]) as qualify:
            directory = run_suite(self.root)
        self.assertEqual(calls, [(200, None), (1000, ["pypdf"])])
        qualify.assert_called_once()
        result = json.loads((directory / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "COMPLETE")
        self.assertTrue((directory / "comparison.html").is_file())
        with (directory / "comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)

    def test_rejected_gate_preserves_200_report_and_no_1000_run(self):
        def run(output, config, **kwargs):
            directory = Path(output) / "run-200"
            directory.mkdir(parents=True)
            report = {"status": "COMPLETE", "methods": [method(status="INVALID", directory=directory)]}
            (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
            return directory
        with patch("ucode.suite.run_experiment", side_effect=run) as execute, patch("ucode.suite.load_qualifying_methods", side_effect=ValueError("No PASS methods")):
            directory = run_suite(self.root)
        execute.assert_called_once()
        result = json.loads((directory / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["stages"]["1000"]["status"], "SKIPPED")
        self.assertIn("No PASS methods", result["stages"]["1000"]["reason"])
        self.assertTrue(result["has_invalid_results"])
        with self.assertRaises(FileExistsError):
            write_comparison(result, directory)

    def test_html_escapes_engine_names_and_reasons(self):
        def run(output, config, **kwargs):
            directory = Path(output) / f"run-{config.count}"
            directory.mkdir(parents=True)
            (directory / "report.json").write_text(json.dumps({"status": "ERROR", "methods": [method("<script>", status="SKIPPED")]}), encoding="utf-8")
            return directory
        with patch("ucode.suite.run_experiment", side_effect=run):
            directory = run_suite(self.root)
        source = (directory / "comparison.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", source)
        self.assertIn("&lt;script&gt;", source)
        self.assertIn("&lt;unsupported&gt;", source)


if __name__ == "__main__":
    unittest.main()
