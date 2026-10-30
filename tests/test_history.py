"""Saved-evidence history must remain bounded, read-only and honest about QA."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


def example():
    trials=[]
    for i,seconds in enumerate((2,4,6),1):
        trials.append({"status":"COMPLETE","warmup":False,"seconds":{"production":seconds,"total_including_qa":seconds+1},
            "relative_folder":f"trials/C0001-{i:02d}","job":"jobs/pdf-2",
            "manifest":{"count":2,"status":"COMPLETE","mode":"multipage","qa_mode":"full",
                "qa":{"raster_available":True,"multipage":{"status":"PASS"}},
                "files":{"multipage":{"name":"all-2-pages.pdf"}}}})
    return {"schema_version":1,"kind":"resource-lab","status":"COMPLETE","config":{"repeats":3,"output_mode":"multipage"},
            "source_digest":"a"*64,"hardware":{"cpu":{"name":"Fixture CPU"}},"engine":{"version":"4.4.9"},
            "cases":[{"id":"C0001","count":2,"status":"PASS","cpu_unit":"physical","cpus":[{"group":0,"logical":0}],
                      "backend":"serial","pdf_profile":"standard","activity":"normal","ram_mode":"max","trials":trials}]}


def save(root,data,name="lab-fixture"):
    folder=Path(root)/name; folder.mkdir(parents=True,exist_ok=True)
    path=folder/"lab.json"; path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    return path


class HistoryTests(unittest.TestCase):
    def test_medians_are_recomputed_warmup_is_excluded_and_input_not_modified(self):
        from ucode.history import read_run
        data=example(); warmup=copy.deepcopy(data["cases"][0]["trials"][0]); warmup.update(warmup=True,seconds={"production":100,"total_including_qa":101})
        data["cases"][0]["trials"].insert(0,warmup)
        data["cases"][0]["summary"]={"status":"PASS","median_with_qa_seconds":.001}
        with tempfile.TemporaryDirectory() as temp:
            path=save(temp,data); before=path.read_bytes()
            result=read_run(path)["results"][0]
            self.assertEqual(result["summary"]["median_seconds"],4)
            self.assertEqual(result["summary"]["median_with_qa_seconds"],5)
            self.assertIn("повторная проверка PDF не выполнялась",result["reason"])
            self.assertEqual(path.read_bytes(),before)

    def test_incomplete_failed_and_unverified_qa_never_display_successful_medians(self):
        from ucode.history import case_result
        mutations=(lambda d:d["cases"][0]["trials"].pop(),
                   lambda d:d["cases"][0]["trials"][0].update(status="ERROR"),
                   lambda d:d["cases"][0]["trials"][0]["manifest"]["qa"]["multipage"].update(status="FAIL"),
                   lambda d:d["cases"][0]["trials"][0]["manifest"].update(qa_mode="deferred"),
                   lambda d:d["cases"][0]["trials"][0].update(seconds=[]),
                   lambda d:d["cases"][0]["trials"][0]["seconds"].update(total_including_qa=.01))
        for change in mutations:
            data=example(); change(data)
            with self.subTest(change=change):
                result=case_result(data["cases"][0],data["config"])
                self.assertNotEqual(result["status"],"PASS")
                self.assertEqual(result["summary"],{})

    def test_corrupt_report_is_visible_and_missing_directory_is_not_created(self):
        from ucode.history import scan_history
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); missing=root/"missing"
            self.assertEqual(scan_history(missing)["entries"],[])
            self.assertFalse(missing.exists())
            good=save(root,example()); bad=save(root,{},"lab-bad")
            before={path:path.read_bytes() for path in (good,bad)}
            result=scan_history(root)
            self.assertEqual(len(result["entries"]),2)
            self.assertEqual({item.status for item in result["entries"]},{"COMPLETE","ОШИБКА"})
            self.assertEqual(before,{path:path.read_bytes() for path in before})

    def test_size_limit_and_cancel_do_not_start_any_work(self):
        from ucode.history import read_run,scan_history
        with tempfile.TemporaryDirectory() as temp:
            path=save(temp,example())
            with self.assertRaises(ValueError): read_run(path,max_bytes=16)
            stop=threading.Event(); stop.set()
            with self.assertRaises(InterruptedError): scan_history(temp,cancel=stop)

    def test_untrusted_field_types_are_reported_and_false_complete_is_not_green(self):
        from ucode.history import read_run,scan_history
        with tempfile.TemporaryDirectory() as temp:
            data=example(); data["cases"][0]["backend"]=[]
            path=save(temp,data)
            with self.assertRaises(ValueError): read_run(path)
            data=example(); data["cases"][0]["trials"].pop()
            save(temp,data)
            self.assertEqual(scan_history(temp)["entries"][0].status,"UNVERIFIED")

    def test_large_index_entries_remain_visible_for_manual_selection(self):
        from ucode.history import scan_history
        with tempfile.TemporaryDirectory() as temp:
            save(temp,example())
            with patch("ucode.history.MAX_INDEX_BYTES",1): result=scan_history(temp)
            self.assertEqual(result["entries"][0].status,"ОТКРОЙТЕ")

    def test_pdf_links_cannot_leave_the_selected_run_and_missing_pdf_is_explicit(self):
        from ucode.history import artifact_path,pdf_for_case
        with tempfile.TemporaryDirectory() as temp:
            path=save(temp,example()); case=example()["cases"][0]
            self.assertIsNone(pdf_for_case(path,case))
            pdf=path.parent/"trials/C0001-01/jobs/pdf-2/all-2-pages.pdf"
            pdf.parent.mkdir(parents=True); pdf.write_bytes(b"PDF fixture; opening only, no QA claim")
            self.assertEqual(pdf_for_case(path,case),pdf.resolve())
            for value in ("../elsewhere.pdf","..\\elsewhere.pdf",str(Path(temp).resolve()/"other.pdf"),"C:\\other.pdf"):
                with self.subTest(value=value),self.assertRaises(ValueError): artifact_path(path,value)

    def test_scan_does_not_recurse_into_neighbor_projects(self):
        from ucode.history import scan_history
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"chosen"; root.mkdir()
            save(Path(temp)/"other",example())
            save(root/"nested-project",example())
            self.assertEqual(scan_history(root)["entries"],[])
