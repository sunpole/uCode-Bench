"""Acceptance regressions for unified UI infrastructure."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from ucode.print_settings import PrintSettings
from ucode.app_settings import load_preferences, save_preferences
from ucode.generators import get_generator, generators
from ucode.progress import ProgressTracker
from ucode.batch import run_batch


class V02Tests(unittest.TestCase):
    def test_only_qr_is_available_and_future_modules_fail_explicitly(self):
        self.assertEqual([g.key for g in generators() if g.available], ["qr"])
        with self.assertRaises(ValueError):
            get_generator("ean13")

    def test_color_settings_roundtrip_and_invalid_ink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings = PrintSettings(ink=(100, 0, 0, 0))
            save_preferences(path, settings, "multipage")
            loaded, mode, warning = load_preferences(path)
            self.assertEqual(loaded, settings)
            self.assertFalse(loaded.is_k100)
            self.assertEqual(mode, "multipage")
            self.assertFalse(warning)
        for ink in ((0, 0, 0, 0), (101, 0, 0, 0), (False, 0, 0, 100), (0, 100)):
            with self.subTest(ink=ink), self.assertRaises(ValueError):
                PrintSettings(ink=ink)

    def test_percent_is_monotonic_and_never_complete_before_finish(self):
        events = []
        tracker = ProgressTracker(11, events.append)
        tracker.step("Кодирование", 5, 5, 0, force=True)
        tracker.step("Проверка", 5, 5, 5, force=True)
        self.assertLess(events[-1]["percent"], 100)
        tracker.finish(5)
        self.assertEqual(events[-1]["percent"], 100)
        self.assertEqual([e["percent"] for e in events], sorted(e["percent"] for e in events))

    def test_batch_color_qA_and_live_updates_match_actual_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.txt"
            source.write_text("000000000001\n200000000123\n", encoding="utf-8")
            events = []
            directory = run_batch(source, root / "jobs", mode="multipage",
                                  settings=PrintSettings(ink=(100, 0, 0, 0)), events=events.append)
            report = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(report["status"], ("COMPLETE", "LIMITED"))
            self.assertEqual(report["qa"]["multipage"]["status"], "PASS", report)
            self.assertEqual(report["print"]["ink"], [100, 0, 0, 0])
            self.assertFalse(report["print"]["k100"])
            self.assertTrue(any(e["stage"] == "Кодирование QR" and e["done"] > 0 for e in events))
            self.assertTrue(any(e["stage"] == "Создание PDF" for e in events))
            self.assertTrue(any(e["stage"] == "Проверка PDF" for e in events))
            self.assertLessEqual(events[-1]["percent"], 100)


if __name__ == "__main__":
    unittest.main()
