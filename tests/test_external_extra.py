"""External-engine boundaries: short argv, manifests, and output protection."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ucode.mergers.base import MergeError
from ucode.mergers.pdfbox import PdfBoxAdapter
from ucode.mergers.pdfcpu import PdfcpuAdapter
from ucode.mergers.pdflib import PdfLibAdapter


class ExternalExtraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode external ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = self.root / "02.pdf", self.root / "01.pdf"
        self.first.write_bytes(b"input two")
        self.second.write_bytes(b"input one")
        self.output = self.root / "result.pdf"

    def pdfbox_assets(self):
        directory = self.root / "tools" / "pdfbox"
        classes = directory / "classes"
        classes.mkdir(parents=True)
        jar = directory / "pdfbox-app-3.0.8.jar"
        jar.write_bytes(b"test jar")
        (classes / "PdfBoxMerge.class").write_bytes(b"test class")
        return jar, classes

    def pdflib_assets(self):
        scripts = self.root / "scripts"
        package = self.root / "node_modules" / "pdf-lib"
        scripts.mkdir()
        package.mkdir(parents=True)
        helper = scripts / "merge-pdflib.mjs"
        helper.write_text("// test helper", encoding="utf-8")
        (package / "package.json").write_text(json.dumps({"name": "pdf-lib", "version": "1.17.1"}), encoding="utf-8")
        return helper

    def test_all_adapters_preserve_existing_output_before_launch(self):
        self.output.write_bytes(b"preserve")
        for adapter in (PdfcpuAdapter(), PdfBoxAdapter(), PdfLibAdapter()):
            with self.subTest(engine=adapter.name), self.assertRaises(FileExistsError):
                adapter.merge([self.first], self.output)
            self.assertEqual(self.output.read_bytes(), b"preserve")

    def test_missing_java_and_node_assets_are_reported_without_launch(self):
        with patch("ucode.mergers.pdfbox._project_root", return_value=self.root), \
             patch("ucode.mergers.pdflib._project_root", return_value=self.root), \
             patch("ucode.mergers.external.subprocess.run") as launched:
            self.assertFalse(PdfBoxAdapter().probe()["available"])
            self.assertFalse(PdfLibAdapter().probe()["available"])
            launched.assert_not_called()

    def test_pdfcpu_keeps_input_order_and_uses_stateless_config(self):
        def run(argv, *, cwd):
            self.assertEqual(cwd, self.root)
            self.assertEqual(argv, ["pdfcpu.exe", "merge", "--mode", "create", "--conf", "disable",
                                    str(self.output), "01.pdf", "02.pdf"])
            self.output.write_bytes(b"result")
            return {"child_cpu_seconds": 0.2}

        with patch.object(PdfcpuAdapter, "executable", return_value="pdfcpu.exe"), \
             patch("ucode.mergers.pdfcpu.run_engine", side_effect=run):
            result = PdfcpuAdapter().merge([self.second, self.first], self.output)
        self.assertEqual(result["child_cpu_seconds"], 0.2)

    def test_pdfcpu_1000_basenames_fit_windows_command_line(self):
        source_directory = self.root / ("long_source_path_" * 8)
        sources = [source_directory / f"{index:04d}_200000000000.pdf" for index in range(1000)]

        def run(argv, *, cwd):
            self.assertEqual(cwd, source_directory)
            self.assertLess(len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2, 30_000)
            self.assertEqual(argv[-1000:], [source.name for source in sources])
            self.output.write_bytes(b"result")
            return {}

        with patch("ucode.mergers.pdfcpu.validate_paths", return_value=(sources, self.output)), \
             patch.object(PdfcpuAdapter, "executable", return_value="pdfcpu.exe"), \
             patch("ucode.mergers.pdfcpu.run_engine", side_effect=run):
            PdfcpuAdapter().merge(sources, self.output)

    def test_pdfbox_manifest_preserves_order_and_java_argv_stays_short(self):
        jar, classes = self.pdfbox_assets()

        def run(argv, *, cwd):
            self.assertEqual(cwd, self.root)
            self.assertEqual(argv[0], "java.exe")
            self.assertEqual(argv[2:5], ["-cp", os.pathsep.join((str(classes), str(jar))), "PdfBoxMerge"])
            self.assertEqual(Path(argv[5]).read_text(encoding="utf-8").splitlines(), [str(self.second), str(self.first)])
            self.assertEqual(argv[6], str(self.output))
            self.assertTrue(Path(argv[1].split("=", 1)[1]).is_dir())
            self.output.write_bytes(b"result")
            return {}

        with patch("ucode.mergers.pdfbox._project_root", return_value=self.root), \
             patch.object(PdfBoxAdapter, "executable", return_value="java.exe"), \
             patch("ucode.mergers.pdfbox.run_engine", side_effect=run):
            PdfBoxAdapter().merge([self.second, self.first], self.output)

    def test_pdfbox_rejects_unrepresentable_manifest_path(self):
        self.pdfbox_assets()
        with patch("ucode.mergers.pdfbox._project_root", return_value=self.root), \
             patch("ucode.mergers.pdfbox.validate_paths", return_value=([self.root / "bad\nname.pdf"], self.output)), \
             patch.object(PdfBoxAdapter, "executable", return_value="java.exe"), \
             patch("ucode.mergers.pdfbox.run_engine") as run:
            with self.assertRaisesRegex(MergeError, "line breaks"):
                PdfBoxAdapter().merge([self.first], self.output)
            run.assert_not_called()

    def test_pdflib_json_manifest_preserves_unicode_paths_and_order(self):
        helper = self.pdflib_assets()
        unicode_input = self.root / "номер QR.pdf"
        unicode_input.write_bytes(b"input")

        def run(argv, *, cwd):
            self.assertEqual(argv[:2], ["node.exe", str(helper)])
            self.assertEqual(cwd, self.root)
            request = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            self.assertEqual(request, {"inputs": [str(unicode_input), str(self.first)], "output": str(self.output)})
            self.output.write_bytes(b"result")
            return {}

        with patch("ucode.mergers.pdflib._project_root", return_value=self.root), \
             patch.object(PdfLibAdapter, "executable", return_value="node.exe"), \
             patch("ucode.mergers.pdflib.run_engine", side_effect=run):
            PdfLibAdapter().merge([unicode_input, self.first], self.output)

    def test_success_without_output_is_an_error(self):
        with patch.object(PdfcpuAdapter, "executable", return_value="pdfcpu.exe"), \
             patch("ucode.mergers.pdfcpu.run_engine", return_value={}):
            with self.assertRaisesRegex(MergeError, "nonempty"):
                PdfcpuAdapter().merge([self.first], self.output)


if __name__ == "__main__":
    unittest.main()
