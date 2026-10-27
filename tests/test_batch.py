"""Tests for the optional TXT -> real PDF pipeline."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from ucode.batch import load_codes, make_template, run_batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-batch-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_templates_have_exact_line_counts_and_do_not_overwrite(self):
        for count in (200, 1000, 10000):
            path = make_template(self.base / "templates", count)
            codes = load_codes(path)
            self.assertEqual(len(codes), count)
            self.assertEqual(codes[0], "200000000000")
            self.assertEqual(codes[-1], str(200000000000 + count - 1))
            self.assertNotEqual(path, make_template(self.base / "templates", count))

    def test_import_rejects_blanks_wrong_width_and_non_digits(self):
        path = self.base / "bad.txt"
        for value in ("", "200000000000\n\n200000000001\n", "20000000000\n",
                      "20000000000A\n", " 200000000000\n"):
            path.write_text(value, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_codes(path)
        path.write_bytes(b"\xef\xbb\xbf200000000000\r\n200000000001\r\n")
        self.assertEqual(load_codes(path), ["200000000000", "200000000001"])

    def test_both_outputs_are_real_and_vector_qa_is_recorded(self):
        source = self.base / "sample.txt"
        source.write_text("200000000123\n200000000456\n", encoding="utf-8")
        # Structural QA must work even when Poppler's raster tools are absent.
        with patch("ucode.batch.shutil.which", return_value=None):
            folder = run_batch(source, self.base / "jobs", mode="both")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "LIMITED")
        self.assertEqual(manifest["count"], 2)
        self.assertEqual(manifest["qa"]["multipage"]["status"], "PASS")
        self.assertEqual(manifest["qa"]["singles"]["checked"], 2)
        self.assertEqual(len(list((folder / "singles").glob("*.pdf"))), 2)
        combined = folder / "all-2-pages.pdf"
        reader = PdfReader(combined, strict=True)
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width), 41.10236, places=3)
            self.assertAlmostEqual(float(page.mediabox.height), 41.10236, places=3)
            self.assertIn(b"0 0 0 1 k", page.get_contents().get_data())

    def test_multipage_only_and_cancellation(self):
        source = self.base / "numbers.txt"
        source.write_text("200000000000\n200000000001\n", encoding="utf-8")
        with patch("ucode.batch.shutil.which", return_value=None):
            folder = run_batch(source, self.base / "jobs", mode="multipage")
        self.assertFalse((folder / "singles").exists())
        self.assertTrue((folder / "all-2-pages.pdf").exists())
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            run_batch(source, self.base / "cancelled", cancel=event)
        self.assertFalse((self.base / "cancelled").exists())


if __name__ == "__main__":
    unittest.main()
