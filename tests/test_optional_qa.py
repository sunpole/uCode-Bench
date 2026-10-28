"""No-QA is an explicit operation, including actual isolated test workers."""
import copy
import csv
import gc
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from ucode.batch import run_batch
from ucode.history import case_result,read_run
from ucode.lab_report import summarize_trials
from ucode.resource_lab import LabConfig,run_lab
from ucode.trial_results import case_statistics,recommendation,trial_rows
from test_history import example


def unchecked_example():
    data=example(); data["status"]="UNVERIFIED"; data["config"]["qa_mode"]="deferred"
    case=data["cases"][0]; case["status"]="UNVERIFIED"
    for trial in case["trials"]:
        trial["status"]="UNVERIFIED"; trial["seconds"]["quality_checks"]=0
        trial["manifest"].update(status="UNVERIFIED",qa_mode="deferred",qa={"status":"NOT_RUN"})
    return data


class OptionalQaTests(unittest.TestCase):
    def test_generation_never_enters_pdf_verifier_when_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/"codes.txt"
            source.write_text("000000000001\n200000000002\n",encoding="utf-8")
            events=[]
            with patch("ucode.audit.verify_outputs",side_effect=AssertionError("QA must not run")) as verify:
                folder=run_batch(source,root/"jobs",mode="both",qa_mode="deferred",events=events.append)
            verify.assert_not_called()
            data=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"UNVERIFIED",data)
            self.assertEqual(data["qa"]["status"],"NOT_RUN")
            self.assertEqual(data["seconds"]["quality_checks"],0)
            self.assertEqual(len(PdfReader(folder/"all-2-pages.pdf").pages),2)
            self.assertEqual(len(list((folder/"singles").glob("*.pdf"))),2)
            self.assertFalse(list(folder.rglob("*.png")))
            self.assertFalse(any(e["stage"].startswith("Проверка") for e in events))
            self.assertEqual(events[-1]["percent"],100)
            self.assertIn("без проверки",(folder/"ОТЧЁТ.txt").read_text(encoding="utf-8"))

    def test_isolated_lab_without_checks_keeps_every_repeat_and_real_times(self):
        with tempfile.TemporaryDirectory() as temp:
            events=[]
            folder=run_lab(Path(temp),LabConfig(counts=(2,),cpu_counts=("1",),backends=("serial",),
                repeats=2,warmups=1,qa_mode="deferred"),events=events.append)
            data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"UNVERIFIED",data)
            case=data["cases"][0]
            self.assertEqual(case["status"],"UNVERIFIED")
            self.assertEqual(len(case["trials"]),3)
            for trial in case["trials"]:
                self.assertEqual(trial["status"],"UNVERIFIED",trial)
                self.assertEqual(trial["manifest"]["qa"]["status"],"NOT_RUN")
                self.assertEqual(trial["seconds"]["quality_checks"],0)
                self.assertGreater(trial["seconds"]["production"],0)
                job=folder/trial["relative_folder"]/trial["job"]
                self.assertEqual(len(PdfReader(job/"all-2-pages.pdf").pages),2)
            self.assertEqual(case["summary"]["completed_repeats"],2)
            self.assertIsNone(case["summary"]["median_with_qa_seconds"])
            self.assertGreater(case_statistics(data)[0]["mean_total"],0)
            self.assertEqual(data["recommendations"],[])
            self.assertEqual(data["pdf_optimization_pairs"],[])
            self.assertIn("без проверки",recommendation(data))
            self.assertIn("Качество PDF не проверялось",recommendation(data))
            self.assertEqual(len(trial_rows(data)),3)
            self.assertFalse(list(folder.rglob("*.png")))
            self.assertFalse(any(" · Проверка" in e["stage"] for e in events))
            self.assertEqual(events[-1]["percent"],100)
            history=read_run(folder/"lab.json")["results"][0]
            self.assertEqual(history["status"],"UNVERIFIED")
            self.assertGreater(history["summary"]["median_operation_seconds"],0)
            for name in ("comparison.csv","all-results.csv"):
                with (folder/name).open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.reader(stream))
                self.assertTrue(all(len(row)==len(rows[0]) for row in rows))
            self.assertIn("БЕЗ ПРОВЕРКИ PDF",(folder/"ОТЧЁТ.txt").read_text(encoding="utf-8"))

    def test_unchecked_statistics_require_actual_matching_records(self):
        data=unchecked_example()
        summary=case_result(data["cases"][0],data["config"])["summary"]
        self.assertEqual(summary["median_seconds"],4)
        self.assertEqual(summary["median_operation_seconds"],5)
        self.assertFalse(summary["quality_verified"])
        mutations=(lambda d:d["cases"][0]["trials"].pop(),
            lambda d:d["cases"][0]["trials"][0]["seconds"].update(quality_checks=1),
            lambda d:d["cases"][0]["trials"][0]["manifest"].update(count=999),
            lambda d:d["cases"][0]["trials"][0]["manifest"]["qa"].update(status="PASS"),
            lambda d:d["cases"][0]["trials"][0].update(status="ERROR"),
            lambda d:d["cases"][0]["trials"][0]["seconds"].update(production=float("nan")))
        for mutate in mutations:
            bad=copy.deepcopy(data); mutate(bad)
            with self.subTest(mutate=mutate):
                self.assertEqual(case_statistics(bad),[])
                self.assertIsNone(summarize_trials(bad["cases"][0]["trials"],3,2,qa_mode="deferred")["median_seconds"])
        full=example(); full["config"]["qa_mode"]="deferred"
        self.assertEqual(case_statistics(full),[])

    def test_cli_forwards_noqa_to_lab_and_preserves_unverified_exit_code(self):
        from ucode.__main__ import main
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); (folder/"lab.json").write_text('{"status":"UNVERIFIED"}',encoding="utf-8")
            with patch("ucode.resource_lab.run_lab",return_value=folder) as run:
                code=main(["lab","--lab-counts","2","--cpu-counts","1","--qa","deferred"])
            self.assertEqual(code,2)
            self.assertEqual(run.call_args.args[1].qa_mode,"deferred")
        with patch("ucode.suite.main") as suite,patch("sys.stderr"):
            with self.assertRaises(SystemExit): main(["suite","--qa","deferred"])
            suite.assert_not_called()

    def test_explicit_partial_qa_retains_structural_checks_and_stays_limited(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=run_lab(Path(temp),LabConfig(counts=(2,),cpu_counts=("1",),backends=("serial",),
                repeats=1,qa_mode="vector"))
            data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"LIMITED",data)
            trial=data["cases"][0]["trials"][0]
            self.assertEqual(trial["manifest"]["qa"]["multipage"]["pages_checked"],2)
            self.assertFalse(trial["manifest"]["qa"]["raster_available"])
            self.assertEqual(data["recommendations"],[])
            self.assertIn("структуры и матрицы",(folder/"ОТЧЁТ.txt").read_text(encoding="utf-8"))


class VisibleQaControlsTests(unittest.TestCase):
    def setUp(self):
        from ucode.batch_gui import BatchWindow
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.folder=Path(self.temp.name)
        self.app=BatchWindow(self.root,self.folder/"output")

    def tearDown(self):
        if hasattr(self,"app"):
            if self.app.worker: self.app.worker.join(timeout=15)
            self.root.destroy(); self.app=self.root=None; gc.collect()

    def test_visible_switch_disables_generation_qa_and_saves_preference(self):
        from ucode.app_settings import load_user_preferences
        source=self.folder/"codes.txt"; source.write_text("200000000001\n200000000002\n",encoding="utf-8")
        self.app.input_var.set(str(source)); self.app.inspect_input()
        self.app.verification_buttons["deferred"].invoke()
        self.assertIn("БЕЗ ПРОВЕРКИ",self.app.generate.cget("text"))
        self.assertEqual(load_user_preferences(self.app.preferences_path)[2].qa_mode,"deferred")
        with patch("ucode.audit.verify_outputs",side_effect=AssertionError("QA must not run")) as verify:
            self.app.generate.invoke(); self.app.worker.join(timeout=10)
            self.assertFalse(self.app.worker.is_alive()); self.app.poll()
        verify.assert_not_called()
        data=json.loads((self.app.last_output/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["qa"]["status"],"NOT_RUN")
        self.assertIn("БЕЗ ПРОВЕРКИ",self.app.result_var.get())
        self.assertEqual(float(self.app.progress["value"]),100)

    def test_same_visible_switch_controls_simple_and_advanced_tests(self):
        from ucode.lab_ui import read_form
        from ucode.test_controls import custom_config
        self.app.show_lab(); self.app.lab_counts.set("2"); self.app.lab_repeats.set("1"); self.app.lab_cpus.set("1")
        self.app.verification_buttons["deferred"].invoke()
        self.assertEqual(read_form(self.app).qa_mode,"deferred")
        self.assertEqual(custom_config(self.app).qa_mode,"deferred")
        self.assertIn("БЕЗ ПРОВЕРКИ",self.app.generate.cget("text"))
        self.app.generate.invoke(); self.app.worker.join(timeout=15)
        self.assertFalse(self.app.worker.is_alive()); self.app.poll()
        data=json.loads((self.app.last_output/"lab.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"],"UNVERIFIED",data)
        self.assertEqual(len(self.app.test_controls.rows),1)
        self.assertEqual(self.app.test_controls.rows[0]["qa"],0)
        row=self.app.test_controls.table.item(self.app.test_controls.table.get_children()[0])["values"]
        self.assertIn("Выкл.",row); self.assertIn("Без проверки",row)
        self.assertIn("БЕЗ ПРОВЕРКИ",self.app.result_var.get())

    def test_historical_test_cannot_silently_ignore_noqa_selection(self):
        self.app.verification_buttons["deferred"].invoke()
        self.app.start_test(200)
        self.assertIsNone(self.app.worker)
        self.assertIn("Научный профиль всегда с полной проверкой",self.app.status_var.get())
