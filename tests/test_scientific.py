import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ucode.config import Experiment
from ucode.scientific import run_scientific
from ucode.resources import check_resources
from ucode.pdf import write_single_files
from ucode.benchmark import run_experiment
from types import SimpleNamespace


class ScientificTests(unittest.TestCase):
    def test_cancel_during_final_qa_preserves_cancelled_report(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("ucode.environment.inspect_environment", return_value={}), patch(
                "ucode.mergers.available_adapters", return_value=[]), patch(
                "ucode.benchmark._prepare", return_value=([], [])), patch(
                "ucode.benchmark._measure", return_value={"seconds": 1}), patch(
                "ucode.benchmark._artifact"), patch(
                "ucode.quality.check_pdf", side_effect=InterruptedError("Остановлено во время QA")):
                output = run_experiment(Path(temp), Experiment(count=2))
            result = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "CANCELLED")
            self.assertEqual(result["methods"][0]["status"], "INVALID")
            self.assertFalse(result["methods"][0]["eligible_for_1000"])

    def test_missing_drive_is_rejected_without_search_loop(self):
        missing_root = Mock()
        missing_root.exists.return_value = False
        missing_root.parent = missing_root
        with patch("ucode.resources.Path") as path:
            path.return_value.resolve.return_value = missing_root
            with self.assertRaisesRegex(ValueError, "недоступны"):
                check_resources("missing-drive", 1000)

    def test_10000_single_names_preserve_numeric_page_order_when_sorted(self):
        with tempfile.TemporaryDirectory() as temp:
            frames = [SimpleNamespace(payload=str(200000000000 + i)) for i in range(10000)]
            with patch("ucode.pdf.write_pdf") as writer:
                paths = write_single_files(frames, Path(temp) / "singles", Experiment(count=10000))
            self.assertEqual(writer.call_count, 10000)
            self.assertEqual([p.name.split("_")[1] for p in sorted(paths)], [f.payload + ".pdf" for f in frames])

    def test_large_test_keeps_three_repeats_and_qualification_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            sizes = []
            def measured(root, config, **kwargs):
                sizes.append(config.count)
                output = Path(root) / str(config.count)
                output.mkdir(parents=True)
                (output / "report.json").write_text(json.dumps({"status": "COMPLETE", "methods": [
                    {"name": "Direct PDF", "status": "PASS", "median_seconds": 1, "trials": [{}, {}, {}]}]}))
                return output
            with patch("ucode.scientific.run_experiment", side_effect=measured), patch(
                "ucode.scientific.load_qualifying_methods", return_value=["Direct PDF"]) as gate:
                folder = run_scientific(directory, 10000)
            self.assertEqual(sizes, [200, 1000, 10000])
            self.assertEqual([call.kwargs["target_count"] for call in gate.call_args_list], [1000, 10000])
            result = json.loads((folder / "scientific.json").read_text())
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["repeats"], 3)
            self.assertTrue((folder / "ОТЧЁТ.txt").is_file())

    def test_millions_and_insufficient_disk_are_rejected(self):
        self.assertEqual(Experiment(count=10000).repeats, 3)
        with self.assertRaises(ValueError):
            Experiment(count=1000000)
        with tempfile.TemporaryDirectory() as temp:
            with patch("ucode.resources.shutil.disk_usage") as usage:
                usage.return_value.free = 0
                with self.assertRaises(ValueError):
                    check_resources(temp, 10000, scientific=True)
