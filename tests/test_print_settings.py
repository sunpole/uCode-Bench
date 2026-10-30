"""Print size + white-field configuration, timing format and real PDF QA."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from ucode.batch import run_batch
from ucode.print_settings import PrintSettings, format_duration, human_report


class PrintSettingsTests(unittest.TestCase):
    def test_default_is_the_original_14_5_mm_v1_m(self):
        config = PrintSettings()
        self.assertEqual(config.quiet_modules, 4)
        self.assertAlmostEqual(config.side_mm, 14.5)
        self.assertAlmostEqual(config.dark_matrix_mm, 10.5)
        self.assertAlmostEqual(config.white_margin_mm, 2.0)

    def test_total_mm_and_quiet_zone_are_independent(self):
        compact = PrintSettings.from_total_side(10.0, 4)
        wide = PrintSettings.from_total_side(20.0, 8)
        self.assertAlmostEqual(compact.side_mm, 10.0)
        self.assertAlmostEqual(wide.side_mm, 20.0)
        self.assertGreater(wide.white_margin_mm, compact.white_margin_mm)
        self.assertAlmostEqual(PrintSettings.from_total_side(14.5, 8).side_mm, 14.5)
        self.assertLess(PrintSettings.from_total_side(14.5, 8).dark_matrix_mm, 10.5)

    def test_nonstandard_or_nonfinite_geometry_is_rejected(self):
        for q in (0, 1, 3, 21, -1, 4.5, True):
            with self.subTest(q=q), self.assertRaises(ValueError):
                PrintSettings.from_total_side(15, q)
        for side in (0, -1, float("nan"), float("inf"), 2.1, 300):
            with self.subTest(side=side), self.assertRaises(ValueError):
                PrintSettings.from_total_side(side, 4)

    def test_human_elapsed_and_speed(self):
        self.assertEqual(format_duration(34 * 60 + 31), "34 мин 31 сек")
        self.assertEqual(format_duration(50 * 3600 + 3 * 60), "50 ч 3 мин 0 сек")
        self.assertEqual(format_duration(0.815), "0,815 сек")
        self.assertEqual(format_duration(None), "нет данных")
        summary = human_report({
            "status": "COMPLETE", "count": 10000, "mode": "both", "input_filename": "source.txt",
            "print": PrintSettings().to_dict(),
            "seconds": {"total_including_qa": 2071.0, "qr_encoding": 5.0, "write_multipage": 4.0},
            "qa": {"multipage": {"status": "PASS"}},
        })
        self.assertIn("34 мин 31 сек", summary)
        self.assertIn("10 000", summary)
        self.assertIn("Многостраничный PDF: PASS", summary)

    def test_real_vector_pdf_with_changed_settings_still_passes_QA(self):
        with tempfile.TemporaryDirectory(prefix="ucode-print-") as dirname:
            root = Path(dirname)
            source = root / "source.txt"
            source.write_text("200000000123\n200000000456\n", encoding="utf-8")
            for quiet, side in ((4, 10.0), (6, 20.0), (8, 18.5)):
                settings = PrintSettings.from_total_side(side, quiet)
                with patch("ucode.batch.shutil.which", return_value=None):
                    folder = run_batch(source, root / "jobs", mode="multipage", settings=settings)
                result = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "LIMITED", msg=result["qa"])
                self.assertEqual(result["qa"]["multipage"]["status"], "PASS")
                self.assertAlmostEqual(result["print"]["page_mm"][0], side, places=5)
                self.assertTrue((folder / "ОТЧЁТ.txt").is_file())
                pdf = folder / "all-2-pages.pdf"
                reader = PdfReader(pdf, strict=True)
                self.assertEqual(len(reader.pages), 2)
                self.assertAlmostEqual(float(reader.pages[0].mediabox.width) / (72 / 25.4),
                                       side, places=4)


if __name__ == "__main__":
    unittest.main()
