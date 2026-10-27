import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ucode.mergers import available_adapters
from ucode.mergers.base import MergeError, validate_paths
from ucode.mergers.external import run_engine
from ucode.mergers.mutool import MutoolAdapter
from ucode.mergers.pikepdf import PikepdfAdapter
from ucode.mergers.pymupdf import PyMuPDFAdapter
from ucode.mergers.pypdf import PypdfAdapter
from ucode.mergers.qpdf import QpdfAdapter


class MergerContractTests(unittest.TestCase):
    def test_registry_preserves_original_engines_and_adds_independent_adapters(self):
        names = [adapter.name for adapter in available_adapters()]
        self.assertEqual(names[:5],
                         ["qpdf", "MuPDF (mutool)", "PyMuPDF", "pikepdf", "pypdf"])
        self.assertEqual(len(names), 11)
        self.assertEqual(len(set(names)), 11)

    def test_missing_executables_are_reported_without_launch(self):
        with patch("ucode.mergers.external.resolve_executable", return_value=None), patch("subprocess.run") as run:
            for adapter in (QpdfAdapter(), MutoolAdapter()):
                self.assertFalse(adapter.probe()["available"])
            run.assert_not_called()

    def test_missing_python_dependencies_are_reported(self):
        with patch("ucode.mergers.base.importlib.util.find_spec", return_value=None):
            for adapter in (PyMuPDFAdapter(), PikepdfAdapter(), PypdfAdapter()):
                result = adapter.probe()
                self.assertFalse(result["available"])
                self.assertIn("not installed", result["reason"])

    def test_empty_input_and_missing_files_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.assertRaises(MergeError):
                validate_paths([], directory / "out.pdf")
            with self.assertRaises(MergeError):
                validate_paths([directory / "missing.pdf"], directory / "out.pdf")

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "source.pdf"
            target = directory / "output.pdf"
            source.write_bytes(b"input")
            target.write_bytes(b"do not overwrite")
            for adapter in available_adapters():
                with self.assertRaises(FileExistsError):
                    adapter.merge([source], target)
                self.assertEqual(target.read_bytes(), b"do not overwrite")

    def test_qpdf_uses_utf8_argument_stream_in_requested_order(self):
        with tempfile.TemporaryDirectory(prefix="ucode merge ") as tmp:
            directory = Path(tmp)
            first, second, target = (directory / name for name in ("02.pdf", "01.pdf", "output.pdf"))
            first.write_bytes(b"a")
            second.write_bytes(b"b")

            def fake_run(argv, *, stdin_bytes):
                self.assertEqual(argv, ["qpdf.exe", "@-"])
                self.assertEqual(stdin_bytes.decode("utf-8").splitlines(),
                                 ["--empty", "--pages", str(second), "1-z", str(first), "1-z", "--", str(target)])
                target.write_bytes(b"output")
                return {"child_cpu_seconds": 0.5, "child_peak_rss_bytes": 4096}

            with patch.object(QpdfAdapter, "executable", return_value="qpdf.exe"), patch("ucode.mergers.qpdf.run_engine", side_effect=fake_run):
                metrics = QpdfAdapter().merge([second, first], target)
                self.assertEqual(metrics["child_cpu_seconds"], 0.5)

    def test_mutool_uses_no_shell_and_explicit_output(self):
        with tempfile.TemporaryDirectory(prefix="ucode merge ") as tmp:
            directory = Path(tmp)
            source, target = directory / "input file.pdf", directory / "output.pdf"
            source.write_bytes(b"input")

            def fake_run(argv, *, cwd):
                self.assertEqual(argv, ["mutool.exe", "merge", "-o", str(target), source.name])
                self.assertEqual(cwd, directory)
                target.write_bytes(b"output")
                return {}

            with patch.object(MutoolAdapter, "executable", return_value="mutool.exe"), patch("ucode.mergers.mutool.run_engine", side_effect=fake_run):
                MutoolAdapter().merge([source], target)

    def test_timeout_kills_and_reaps_child(self):
        with patch("ucode.mergers.external.subprocess.Popen") as constructor:
            process = constructor.return_value
            process.communicate.side_effect = [subprocess.TimeoutExpired(["engine"], 120), (b"", b"")]
            with self.assertRaisesRegex(MergeError, "terminated"):
                run_engine(["engine"])
            process.kill.assert_called_once_with()
            self.assertEqual(process.communicate.call_count, 2)
            self.assertFalse(constructor.call_args.kwargs["shell"])

    def test_nonzero_status_preserves_diagnostic(self):
        with patch("ucode.mergers.external.subprocess.Popen") as constructor, patch("ucode.mergers.external.process_metrics", return_value={}):
            process = constructor.return_value
            process.communicate.return_value = (b"", b"broken input")
            process.returncode = 2
            with self.assertRaisesRegex(MergeError, "code 2: broken input"):
                run_engine(["engine"])


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf is unavailable")
class PypdfIntegrationTests(unittest.TestCase):
    def test_real_pdf_pages_follow_explicit_order(self):
        from pypdf import PdfReader, PdfWriter
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            paths = []
            for name, width in (("02.pdf", 40), ("01.pdf", 70)):
                source = directory / name
                with PdfWriter() as writer:
                    writer.add_blank_page(width=width, height=100)
                    with source.open("xb") as stream:
                        writer.write(stream)
                paths.append(source)
            target = directory / "merged.pdf"
            PypdfAdapter().merge(list(reversed(paths)), target)
            reader = PdfReader(target)
            self.assertEqual([float(page.mediabox.width) for page in reader.pages], [70, 40])

    def test_broken_input_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "broken.pdf"
            source.write_bytes(b"not a PDF")
            with self.assertRaises(Exception):
                PypdfAdapter().merge([source], Path(tmp) / "out.pdf")


if __name__ == "__main__":
    unittest.main()
