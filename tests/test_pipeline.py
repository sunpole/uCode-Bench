import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import full_comparison, install_engines


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-export-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_sanitization_preserves_json_and_raw_evidence(self):
        suite = self.root / "output" / "suite"
        raw = json.dumps({"path": str(suite / "run" / "result.pdf"), "python": str(Path.home() / "python.exe")})
        with patch.object(full_comparison, "ROOT", self.root):
            copied = full_comparison.public_text(raw, suite)
        value = json.loads(copied)
        self.assertNotIn(str(self.root), value["path"])
        self.assertNotIn(str(Path.home()), value["python"])
        self.assertEqual(json.loads(raw)["path"], str(suite / "run" / "result.pdf"))

    def test_complete_local_archive_contains_pdf_and_portable_report(self):
        suite = self.root / "output" / "suite-test"
        suite.mkdir(parents=True)
        (suite / "result.pdf").write_bytes(b"fixture PDF bytes")
        (suite / "comparison.json").write_text(json.dumps({"path": str(suite / "result.pdf")}), encoding="utf-8")
        job = self.root / "job"
        job.mkdir()
        with patch.object(full_comparison, "ROOT", self.root):
            exported, archive = full_comparison.export_results(suite, job)
        self.assertTrue((suite / "result.pdf").exists())
        self.assertTrue((exported / "comparison.json").exists())
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(zipped.read("result.pdf"), b"fixture PDF bytes")
            self.assertNotIn(str(self.root), json.loads(zipped.read("comparison.json"))["path"])
        manifest = json.loads((exported / "archive.json").read_text())
        self.assertEqual(manifest["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_archive_traversal_is_rejected_without_touching_neighbor(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "x") as zipped:
            zipped.writestr("../outside.txt", "bad")
        with self.assertRaises(ValueError):
            install_engines.extract_verified(archive, self.root / "target")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_existing_download_with_wrong_hash_is_preserved(self):
        path = self.root / "tool.zip"
        path.write_bytes(b"original")
        with self.assertRaises(ValueError):
            install_engines.download("https://invalid.example/test", path, "0" * 64)
        self.assertEqual(path.read_bytes(), b"original")

    def test_dotnet_setup_disables_global_first_run_mutations(self):
        with patch.object(install_engines, "ROOT", self.root):
            environment = install_engines.local_environment()
        self.assertEqual(environment["DOTNET_GENERATE_ASPNET_CERTIFICATE"], "false")
        self.assertEqual(environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"], "false")
        self.assertTrue(Path(environment["DOTNET_CLI_HOME"]).is_relative_to(self.root))


if __name__ == "__main__":
    unittest.main()
