import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ucode.mergers.base import MergeError
from ucode.mergers.pdfsharp import HELPER, PdfSharpAdapter
from ucode.runtime import resolve_executable


class PdfSharpAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ucode-pdfsharp-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.helper = self.root / "PdfSharpMerge.dll"
        self.helper.write_bytes(b"test helper placeholder")

    def test_probe_missing_helper_does_not_install_or_launch(self):
        with patch("ucode.mergers.pdfsharp.HELPER", self.root / "missing.dll"), patch("ucode.mergers.pdfsharp.resolve_executable") as resolve:
            info = PdfSharpAdapter().probe()
        self.assertFalse(info["available"])
        self.assertIn("has not been built", info["reason"])
        resolve.assert_not_called()

    def test_probe_missing_dotnet_is_skipped(self):
        with patch("ucode.mergers.pdfsharp.HELPER", self.helper), patch("ucode.mergers.pdfsharp.resolve_executable", return_value=None):
            info = PdfSharpAdapter().probe()
        self.assertFalse(info["available"])
        self.assertIn(".NET 8", info["reason"])

    def test_existing_output_is_preserved_before_probe(self):
        source, output = self.root / "source.pdf", self.root / "output.pdf"
        source.write_bytes(b"input")
        output.write_bytes(b"preserve")
        with patch.object(PdfSharpAdapter, "probe") as probe, self.assertRaises(FileExistsError):
            PdfSharpAdapter().merge([source], output)
        probe.assert_not_called()
        self.assertEqual(output.read_bytes(), b"preserve")

    def test_manifest_preserves_1000_input_order_without_long_argv(self):
        first, second, output = self.root / "02 input.pdf", self.root / "01 input.pdf", self.root / "output.pdf"
        first.write_bytes(b"first")
        second.write_bytes(b"second")
        sources = [second, first] * 500
        info = {"available": True, "executable": "dotnet.exe", "helper": str(self.helper)}
        def run(argv):
            self.assertEqual(argv[:2], ["dotnet.exe", str(self.helper)])
            self.assertEqual(len(argv), 3)
            manifest = Path(argv[2])
            request = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(request["inputs"], [str(path) for path in sources])
            self.assertEqual(request["output"], str(output))
            output.write_bytes(b"merged")
            return {"child_cpu_seconds": 0.25, "child_peak_rss_bytes": 4096}
        with patch.object(PdfSharpAdapter, "probe", return_value=info), patch("ucode.mergers.pdfsharp.run_engine", side_effect=run):
            metrics = PdfSharpAdapter().merge(sources, output)
        self.assertEqual(metrics["child_cpu_seconds"], 0.25)
        self.assertEqual(len(list(self.root.glob("*.pdfsharp-*.json"))), 1)

    def test_empty_engine_output_is_an_error(self):
        source, output = self.root / "source.pdf", self.root / "output.pdf"
        source.write_bytes(b"input")
        info = {"available": True, "executable": "dotnet.exe", "helper": str(self.helper)}
        def run(argv):
            output.touch()
            return {}
        with patch.object(PdfSharpAdapter, "probe", return_value=info), patch("ucode.mergers.pdfsharp.run_engine", side_effect=run), self.assertRaisesRegex(MergeError, "nonempty"):
            PdfSharpAdapter().merge([source], output)


@unittest.skipUnless(HELPER.is_file() and resolve_executable("dotnet") and importlib.util.find_spec("pypdf"),
                     "Built .NET helper, dotnet and pypdf are required")
class PdfSharpIntegrationTests(unittest.TestCase):
    def test_real_pages_follow_requested_order_and_existing_file_is_preserved(self):
        from pypdf import PdfReader, PdfWriter
        with tempfile.TemporaryDirectory(prefix="ucode-pdfsharp-real-") as temporary:
            directory = Path(temporary)
            sources = []
            for index, width in enumerate((40, 70)):
                path = directory / f"source-{index}.pdf"
                with PdfWriter() as writer:
                    writer.add_blank_page(width=width, height=100)
                    with path.open("xb") as stream:
                        writer.write(stream)
                sources.append(path)
            output = directory / "merged.pdf"
            PdfSharpAdapter().merge(list(reversed(sources)), output)
            self.assertEqual([float(page.mediabox.width) for page in PdfReader(output).pages], [70, 40])
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                PdfSharpAdapter().merge(sources, output)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
