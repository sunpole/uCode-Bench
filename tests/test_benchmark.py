import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ucode.benchmark import _summarize, _verify_txt, load_qualifying_methods, run_experiment
from ucode.config import Experiment
from ucode.data import generate_numbers, write_numbers


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-benchmark-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def qualifying_report(self, name="pypdf", category="merge"):
        config = Experiment()
        write_numbers(generate_numbers(config), self.root / "numbers.txt")
        artifact = self.root / "test.pdf"
        artifact.write_bytes(b"preserved test artifact for gate validation")
        qa = {"status": "PASS", "errors": [], "pages_checked": 200, "render_samples": True,
              "decoded_samples": [{"page": p, "payload": v} for p, v in (
                  (1, "200000000000"), (101, "200000000100"), (200, "200000000199"))]}
        trial = {"seconds": 1.0, "qa": qa, "path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}
        value = {"schema_version": 1, "status": "COMPLETE", "config": config.to_dict(),
                 "stages": {"numbers_txt_sha256": _verify_txt(self.root / "numbers.txt", config),
                            "single_files": [{"qa": qa} for _ in range(3)]},
                 "methods": [{"name": name, "category": category, "status": "PASS", "eligible_for_1000": True,
                              "trials": [dict(trial) for _ in range(3)]}]}
        path = self.root / "report.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path, value, artifact

    def test_numbers_exact_and_txt_readback_rejects_wrong_order(self):
        numbers = generate_numbers(Experiment())
        self.assertEqual((numbers[0], numbers[-1], len(numbers)), ("200000000000", "200000000199", 200))
        path = self.root / "numbers.txt"
        write_numbers(numbers[::-1], path)
        with self.assertRaises(ValueError):
            _verify_txt(path, Experiment())
        with self.assertRaises(FileExistsError):
            write_numbers(numbers, path)

    def test_one_bad_repeat_invalidates_even_with_fast_median(self):
        method = {"status": "PENDING", "trials": [{"seconds": 1, "output_bytes": 2, "qa": {"status": s}} for s in ("PASS", "FAIL", "PASS")]}
        _summarize(method, Experiment())
        self.assertEqual(method["status"], "INVALID")
        self.assertFalse(method["eligible_for_1000"])

    def test_gate_accepts_three_verified_trials(self):
        path, _, _ = self.qualifying_report()
        self.assertEqual(load_qualifying_methods(path), ["pypdf"])

    def test_gate_refuses_changed_pdf(self):
        path, _, artifact = self.qualifying_report()
        artifact.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            load_qualifying_methods(path)

    def test_gate_refuses_empty_source_qa(self):
        path, value, _ = self.qualifying_report()
        value["stages"]["single_files"] = []
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_qualifying_methods(path)

    def test_gate_refuses_structural_only_qa(self):
        path, value, _ = self.qualifying_report()
        value["methods"][0]["trials"][0]["qa"]["render_samples"] = False
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_qualifying_methods(path)

    def test_1000_without_qualification_does_not_create_outputs(self):
        output = self.root / "must-not-exist"
        with self.assertRaises(ValueError):
            run_experiment(output, Experiment(count=1000))
        self.assertFalse(output.exists())

    def test_cancelled_run_preserves_report_and_never_qualifies(self):
        event = threading.Event()
        event.set()
        with patch("ucode.environment.inspect_environment", return_value={}):
            directory = run_experiment(self.root / "cancel", Experiment(count=2), cancel=event)
        result = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "CANCELLED")
        self.assertTrue((directory / "numbers.txt").exists())
        self.assertFalse(any(m["eligible_for_1000"] for m in result["methods"]))


if __name__ == "__main__":
    unittest.main()
