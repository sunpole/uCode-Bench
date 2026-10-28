"""Predictable search/parts/quality/coverage. Actual PDFs never exceed four pages."""
from dataclasses import replace
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from ucode.pc_search import SearchConfig,candidates,preview_search,run_search,choose_leaders,next_stage_candidates
from ucode.search_report import phases
from test_lab_interface import cpu_fixture
from test_history import example


class SearchPlanTests(unittest.TestCase):
    def test_current_machine_all_quantities_and_four_requested_sizes_are_planned_only(self):
        cfg=SearchConfig()
        rows=candidates(cfg,cpu_fixture(14)); plan=preview_search(cfg,cpu_fixture(14))
        self.assertEqual(cfg.counts,(200,1000,10000,100000))
        self.assertEqual({len(row["cpus"]) for row in rows if row["backend"]=="process"},set(range(1,15)))
        self.assertEqual(len(cfg.mergers),11)
        self.assertGreater(plan["trials_upper_bound"],0)
        self.assertGreater(plan["pdf_pages_upper_bound"],100000)
        self.assertLess(len(rows),4096)

    def test_unknown_topology_and_duplicate_smt_masks_are_explicit(self):
        cpu=cpu_fixture(2)
        rows=candidates(SearchConfig(counts=(2,),cpu_units=("physical","logical"),backends=("process",),pdf_profiles=("compact",),activities=("minimal",)),cpu)
        self.assertTrue(any(row["status"]=="SKIPPED" and "Эквивалентный" in row["reason"] for row in rows))
        cpu["available_cpus"]=[]; cpu["available_physical"]=None
        self.assertTrue(all(row["status"]=="SKIPPED" for row in candidates(SearchConfig(),cpu)))

    def test_parallel_phase_totals_are_not_double_counted(self):
        row={"seconds":{"launcher_wall":10,"parts_creation":6,"code_encoding":20,"write_multipage":15,"merge":2,"quality_checks":1}}
        values=phases(row,"split")
        self.assertEqual(sum(values.values()),10)
        self.assertEqual(values["Подготовка, запуск и прочее"],1)
        self.assertNotIn("Кодирование QR",values)

    def test_screening_retains_minimum_and_maximum_cpu_per_method(self):
        cfg=SearchConfig(keep_best=1)
        rows=candidates(cfg,cpu_fixture(14))
        selected=next_stage_candidates(rows,cfg)
        for backend in ("process","thread"):
            sizes={len(row["cpus"]) for row in selected if row["backend"]==backend}
            self.assertEqual(sizes,{1,14})
        self.assertTrue(any(row["backend"]=="serial" for row in selected))
        self.assertLess(len(selected),len(rows))

    def test_false_fast_result_without_quality_or_required_repeats_never_wins(self):
        data=example(); case=data["cases"][0]
        for row in case["trials"]: row["seconds"]["launcher_wall"]=row["seconds"]["total_including_qa"]+.1
        cfg=SearchConfig(counts=(2,),repeats=3)
        self.assertEqual(len(choose_leaders([case],cfg)),1)
        bad=copy.deepcopy(case); bad["trials"][0]["manifest"]["qa"]["multipage"]["status"]="FAIL"
        self.assertEqual(choose_leaders([bad],cfg),[])
        bad=copy.deepcopy(case); bad["trials"].pop()
        self.assertEqual(choose_leaders([bad],cfg),[])

    def test_tuner_timeout_scope_leaves_scientific_default_unchanged(self):
        from ucode.mergers.external import engine_timeout,run_engine
        with patch("ucode.mergers.external.subprocess.Popen") as constructor,patch("ucode.mergers.external.process_metrics",return_value={}):
            process=constructor.return_value; process.returncode=0; process.communicate.return_value=(b"",b"")
            with engine_timeout(None): run_engine(["helper"])
            self.assertIsNone(process.communicate.call_args.kwargs["timeout"])
            run_engine(["helper"])
            self.assertEqual(process.communicate.call_args.kwargs["timeout"],120)


class RealSearchTests(unittest.TestCase):
    def setUp(self):
        from ucode.hardware import inspect_cpu
        self.physical=inspect_cpu().get("available_physical")
        if not self.physical: self.skipTest("Физическая топология неизвестна")
    def config(self,**kwargs):
        return replace(SearchConfig(counts=(3,),repeats=1,cpu_counts=("1","2"),all_cpu_counts=False,backends=("serial",),
            pdf_profiles=("compact",),activities=("minimal",),batches=(1,),part_counts=(2,),mergers=("pypdf",),qa_mode="vector"),**kwargs)

    def test_single_sequential_and_parallel_parts_have_same_real_codes_and_final_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=run_search(Path(temp),self.config())
            data=json.loads((folder/"pc-search.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"LIMITED",data)
            self.assertEqual(len(data["cases"]),3)
            for case in data["cases"]:
                trial=case["trials"][0]; manifest=trial["manifest"]
                self.assertEqual(manifest["qa"]["multipage"]["status"],"PASS",trial)
                job=folder/trial["relative_folder"]/trial["job"]
                self.assertEqual(len(PdfReader(job/"all-3-pages.pdf").pages),3)
                if case["strategy"]=="split":
                    self.assertEqual(manifest["parts"]["count"],2)
                    self.assertGreaterEqual(trial["seconds"]["merge"],0)
                    self.assertFalse(list(job.rglob(".work-*")))
                    self.assertFalse(list(job.rglob("data.sqlite")))
                    if manifest["parts"]["mode"]=="parallel":
                        self.assertEqual(manifest["parts"]["concurrency"],min(2,self.physical))
                        from ucode.audit import audit_job
                        audit=audit_job(job,render_samples=False)
                        checked=json.loads((audit/"audit.json").read_text(encoding="utf-8"))
                        self.assertEqual(checked["status"],"LIMITED",checked)
            self.assertEqual(data["winners"][0]["count"],3)
            self.assertTrue((folder/"pc-search.html").is_file())

    def test_staged_search_records_pruning_and_never_runs_unrequested_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=self.config(counts=(2,4),backends=("serial","thread"),pdf_profiles=("standard","compact"),keep_best=1,part_modes=("sequential",),qa_mode="deferred")
            from ucode.engines import get_engine
            with patch("ucode.pc_search.inspect_catalog",return_value={"encoders":[{"version":get_engine().info().version,"name":"fixture"}],"mergers":[{"name":"pypdf","available":True,"version":"test"}],"candidates":[],"interpreters":{"reason":"fixture"}}):
                folder=run_search(Path(temp),cfg)
            data=json.loads((folder/"pc-search.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"UNVERIFIED",data)
            self.assertGreater(data["stages"][1]["not_retested_after_screen"],0)
            self.assertEqual({case["count"] for case in data["cases"]},{2,4})
            self.assertTrue(all(t["seconds"]["quality_checks"]==0 for c in data["cases"] for t in c["trials"]))
            self.assertIn("БЕЗ ПРОВЕРКИ",(folder/"ОТЧЁТ.txt").read_text(encoding="utf-8"))

    def test_cancel_while_parts_are_active_stops_only_owned_work(self):
        with tempfile.TemporaryDirectory() as temp:
            stop=threading.Event(); events=[]
            def event(value):
                events.append(value)
                if "Создание частей" in value["stage"]: stop.set()
            folder=run_search(Path(temp),self.config(qa_mode="deferred"),cancel=stop,events=event)
            data=json.loads((folder/"pc-search.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"CANCELLED",data)
            self.assertTrue(all(value["percent"]<100 for value in events))
            self.assertTrue((folder/"ОТЧЁТ.txt").is_file())

    def test_unavailable_merger_is_visible_and_does_not_get_a_fake_time(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=run_search(Path(temp),self.config(mergers=("not-installed-engine",),part_modes=("sequential",),qa_mode="deferred"))
            data=json.loads((folder/"pc-search.json").read_text(encoding="utf-8"))
            skipped=[row for row in data["cases"] if row["status"]=="SKIPPED"]
            self.assertEqual(len(skipped),1)
            self.assertEqual(skipped[0]["trials"],[])


class SearchWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.app=BatchWindow(self.root,Path(self.temp.name)/"output")
    def tearDown(self):
        if hasattr(self,"app"):
            if self.app.worker: self.app.worker.join(timeout=20)
            self.root.destroy()
            self.app=self.root=None
            import gc
            gc.collect()

    def test_main_search_button_saves_settings_and_opens_browser_report(self):
        if not self.app.hardware["cpu"].get("available_physical"): self.skipTest("Нет physical topology")
        view=self.app.search_view
        view.counts.set("2"); view.repeats.set("1"); view.all_cpus.set(False); self.app.lab_cpus.set("1")
        view.methods.set("serial"); view.pdf.set("compact"); view.activities.set("minimal"); view.parts.set("2"); view.mergers.set("pypdf")
        self.app.qa_mode_var.set("Отложена")
        self.app.notebook.select(self.app.pages["search"]); self.app.update_buttons()
        self.assertEqual(self.app.generate.cget("text"),"НАЧАТЬ ПОДБОР")
        self.app.generate.invoke(); self.app.worker.join(timeout=20)
        self.assertFalse(self.app.worker.is_alive()); self.app.poll()
        data=json.loads((self.app.last_output/"pc-search.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"],"UNVERIFIED",data)
        self.assertEqual(len(data["cases"]),3)
        self.assertEqual(self.app.last_report.name,"pc-search.html")
        self.assertTrue(self.app.last_pdf.is_file())
        with patch("ucode.batch_gui.open_html_report") as browser:
            self.app.open_report(); browser.assert_called_once_with(self.app.last_report)
        self.assertTrue(view.path.is_file())
