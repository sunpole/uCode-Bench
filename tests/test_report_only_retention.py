"""Safe cleanup of isolated benchmark PDFs, preserving QA reports."""
from pathlib import Path
import tempfile
import unittest

from ucode.test_retention import discard_trial_pdfs


class ReportOnlyRetentionTests(unittest.TestCase):
    def test_disposes_only_trial_pdfs_and_keeps_reports(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/"trial"
            root.mkdir()
            pdfs=root/"jobs"/"pdf-2"/"singles"
            pdfs.mkdir(parents=True)
            for n in range(3):
                (pdfs/f"{n}.pdf").write_bytes(b"PDF data"*(n+1))
            (pdfs/"keep.json").write_text('{"status":"PASS"}',encoding="utf-8")
            (pdfs.parent/"data.sqlite").write_bytes(b"working data")
            (pdfs.parent/"pdf-index.sqlite").write_bytes(b"page index")
            (pdfs.parent/"catalog.sqlite").write_bytes(b"report index must survive")
            (root/"catalog.sqlite").write_bytes(b"test catalog must survive")
            (root/"trial.json").write_text('{"qa":"PASS"}',encoding="utf-8")
            (root/"report.html").write_text("HTML test report",encoding="utf-8")
            neighbor=Path(base)/"production.pdf"
            neighbor.write_bytes(b"keep user production")
            result=discard_trial_pdfs(root)
            self.assertEqual(result["status"],"PASS")
            self.assertEqual(result["pdf_deleted_files"],3)
            self.assertEqual(result["sqlite_deleted_files"],2)
            self.assertFalse(list(root.rglob("*.pdf")))
            self.assertFalse((pdfs.parent/"data.sqlite").exists())
            self.assertFalse((pdfs.parent/"pdf-index.sqlite").exists())
            self.assertTrue((pdfs.parent/"catalog.sqlite").is_file())
            self.assertTrue((root/"catalog.sqlite").is_file())
            self.assertTrue((root/"trial.json").is_file())
            self.assertTrue((pdfs/"keep.json").is_file())
            self.assertTrue((root/"report.html").is_file())
            self.assertTrue(neighbor.is_file())

    def test_does_not_follow_symlinks_outside_owned_trial(self):
        with tempfile.TemporaryDirectory() as base:
            root=Path(base)/"trial"
            external=Path(base)/"external"
            root.mkdir();external.mkdir()
            (external/"private.pdf").write_bytes(b"keep!")
            link=root/"linked-folder"
            try:
                link.symlink_to(external,target_is_directory=True)
            except (NotImplementedError,OSError):
                self.skipTest("Creating directory links requires OS permission")
            result=discard_trial_pdfs(root)
            self.assertEqual(result["pdf_deleted_files"],0)
            self.assertEqual((external/"private.pdf").read_bytes(),b"keep!")

    def test_rejects_nonexistent_trial(self):
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaises(ValueError):
                discard_trial_pdfs(Path(base)/"missing")


if __name__=="__main__":
    unittest.main()
