"""Additional engine contracts and real vector-CMYK integration checks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ucode.mergers.base import MergeError
from ucode.mergers.pdfrw import PdfrwAdapter
from ucode.mergers.pdfium import PdfiumAdapter


class ExtraMergerContractTests(unittest.TestCase):
    def test_existing_output_is_preserved_before_loading_engine(self):
        with tempfile.TemporaryDirectory(prefix="ucode-extra-") as temporary:
            root = Path(temporary)
            source, output = root / "source.pdf", root / "existing.pdf"
            source.write_bytes(b"test input")
            output.write_bytes(b"preserved result")
            for adapter in (PdfrwAdapter(), PdfiumAdapter()):
                with self.subTest(engine=adapter.name), self.assertRaises(FileExistsError):
                    adapter.merge([source], output)
                self.assertEqual(output.read_bytes(), b"preserved result")

    def test_missing_engine_is_explicit_and_creates_no_output(self):
        with tempfile.TemporaryDirectory(prefix="ucode-extra-") as temporary:
            root = Path(temporary)
            source, output = root / "source.pdf", root / "result.pdf"
            source.write_bytes(b"test input")
            with patch("ucode.mergers.base.importlib.util.find_spec", return_value=None):
                for adapter in (PdfrwAdapter(), PdfiumAdapter()):
                    with self.subTest(engine=adapter.name):
                        self.assertFalse(adapter.probe()["available"])
                        with self.assertRaisesRegex(MergeError, "not installed"):
                            adapter.merge([source], output)
                        self.assertFalse(output.exists())


class _ExtraMergerIntegration:
    adapter_class = None

    def test_merge_preserves_explicit_order_vector_k100_and_geometry(self):
        from ucode.config import Experiment
        from ucode.pdf import write_pdf
        from ucode.qr import encode_numbers
        from ucode.quality import check_pdf

        config = Experiment(count=2)
        frames = encode_numbers(["200000000000", "200000000001"])
        with tempfile.TemporaryDirectory(prefix="ucode-extra-") as temporary:
            root = Path(temporary)
            paths = [root / "02.pdf", root / "01.pdf"]
            for frame, path in zip(frames, paths):
                write_pdf([frame], path, config)
            output = root / "merged.pdf"
            self.adapter_class().merge(paths[::-1], output)
            qa = check_pdf(output, frames[::-1], config, render_samples=False)
            self.assertEqual(qa["status"], "PASS", qa)
            self.assertEqual(qa["pages_checked"], 2)

    def test_broken_input_is_an_error_without_an_output_file(self):
        with tempfile.TemporaryDirectory(prefix="ucode-extra-") as temporary:
            root = Path(temporary)
            source, output = root / "broken.pdf", root / "result.pdf"
            source.write_bytes(b"not a PDF")
            with self.assertRaises(Exception):
                self.adapter_class().merge([source], output)
            self.assertFalse(output.exists())


@unittest.skipUnless(importlib.util.find_spec("pdfrw"), "pdfrw is unavailable")
class PdfrwIntegrationTests(_ExtraMergerIntegration, unittest.TestCase):
    adapter_class = PdfrwAdapter


@unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "pypdfium2 is unavailable")
class PdfiumIntegrationTests(_ExtraMergerIntegration, unittest.TestCase):
    adapter_class = PdfiumAdapter


if __name__ == "__main__":
    unittest.main()
