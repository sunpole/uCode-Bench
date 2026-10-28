import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ucode.batch import make_template, run_batch
from ucode.engines import ReportLabEngine


class GenerationPlanTests(unittest.TestCase):
    def test_custom_template_exact_count_and_old_files_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            first = make_template(folder, 7)
            raw = first.read_bytes()
            second = make_template(folder, 7)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), raw)
            self.assertEqual(len(second.read_text().splitlines()), 7)

    def test_copies_are_real_pages_and_each_value_encodes_once(self):
        class CountingEngine(ReportLabEngine):
            encoded = []
            def encode(self, values, **kwargs):
                self.encoded.extend(values)
                return super().encode(values, **kwargs)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.txt"
            source.write_text("000000000001\n200000000002\n000000000001\n", encoding="utf-8")
            engine = CountingEngine()
            with patch.dict("ucode.engines._ENGINES", {"counting": engine}):
                out = run_batch(source, root / "out", copies_per_value=3, duplicate_policy="unique",
                                engine="counting", mode="both")
            data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(data["status"], ("COMPLETE", "LIMITED"))
            self.assertEqual(data["count"], 6)
            self.assertEqual(data["generation"]["unique_values"], 2)
            self.assertEqual(data["generation"]["input_records"], 3)
            self.assertEqual(data["generation"]["encoded_values"], 2)
            self.assertEqual(data["files"]["multipage"]["pages"], 6)
            self.assertEqual(data["qa"]["multipage"]["pages_checked"], 6)
            self.assertEqual(len(list((out / "singles").glob("*.pdf"))), 6)
            self.assertEqual(engine.encoded, ["000000000001", "200000000002"])
            self.assertEqual((out / "codes.txt").read_text().splitlines(),
                             ["000000000001"] * 3 + ["200000000002"] * 3)

    def test_default_keeps_duplicate_input_rows_and_overflow_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.txt"
            source.write_text("200000000001\n200000000001\n", encoding="utf-8")
            out = run_batch(source, root / "out", mode="multipage")
            self.assertEqual((out / "codes.txt").read_text().splitlines(), ["200000000001"] * 2)
            for copies in (0, True, -1):
                with self.assertRaises(ValueError):
                    run_batch(source, root / "forbidden", copies_per_value=copies)
                self.assertFalse((root / "forbidden").exists())

    def test_stream_validates_lazily_and_identifies_bad_line(self):
        from ucode.batch import iter_codes
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large.txt"
            path.write_bytes(b"\xef\xbb\xbf000000000001\r\n200000000002\r\nBAD\n")
            values = iter_codes(path, max_lines=None, max_bytes=None)
            self.assertEqual(next(values), "000000000001")
            self.assertEqual(next(values), "200000000002")
            with self.assertRaisesRegex(ValueError, "Строка 3"):
                next(values)

    def test_plan_counts_types_separately_from_copies(self):
        from ucode.generation_plan import build_plan
        plan = build_plan(["a", "b", "a"], copies_per_value=3, duplicate_policy="unique",
                          types=("qr", "other-test-type"))
        self.assertEqual(plan.codes_per_type, {"qr": 6, "other-test-type": 6})
        self.assertEqual(plan.total_codes, 12)
        self.assertEqual(plan.duplicate_records, 1)

    def test_plan_never_consumes_an_unbounded_source(self):
        from ucode.generation_plan import build_plan, MAX_CODES
        seen = [0]
        def source():
            for _ in range(MAX_CODES + 100):
                seen[0] += 1
                yield "200000000001"
        with self.assertRaisesRegex(ValueError, "10 000"):
            build_plan(source(), duplicate_policy="unique")
        self.assertEqual(seen[0], MAX_CODES + 1)

    def test_stream_has_bounded_lines_and_cancel(self):
        from ucode.batch import iter_codes
        import threading
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.txt"
            path.write_bytes(b"1" * 4097)
            with self.assertRaisesRegex(ValueError, "Строка 1"):
                list(iter_codes(path))
            path.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                list(iter_codes(path))
            path.write_text("200000000001\n", encoding="utf-8")
            stop = threading.Event(); stop.set()
            with self.assertRaises(InterruptedError):
                list(iter_codes(path, cancel=stop))

    def test_preferences_v1_migrate_and_old_save_preserves_generation(self):
        from ucode.app_settings import GenerationPreferences, load_user_preferences, save_preferences
        from ucode.print_settings import PrintSettings
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "settings": {"module_mm": .7,
                "quiet_modules": 5}, "mode": "both"}), encoding="utf-8")
            settings, mode, generation, warning = load_user_preferences(path)
            self.assertEqual(generation.copies_per_value, 1)
            self.assertEqual(settings.module_mm, .7)
            self.assertEqual(mode, "both")
            self.assertFalse(warning)
            options = GenerationPreferences(3, "unique", 7, str(Path(temp) / "my-pdfs"))
            save_preferences(path, settings, mode, generation=options)
            save_preferences(path, PrintSettings(), "multipage")
            self.assertEqual(load_user_preferences(path)[2], options)
            raw = path.read_text(encoding="utf-8")
            value = json.loads(raw); value["generation"]["copies_per_value"] = True
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertTrue(load_user_preferences(path)[3])
            self.assertTrue(json.loads(path.read_text())["generation"]["copies_per_value"])
