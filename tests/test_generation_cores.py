"""Explicit CPU controls, own-load math, frozen code and real small PDFs."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ucode.affinity import select_cpus,cpu_keys
from ucode.app_settings import GenerationPreferences
from ucode.execution import ExecutionOptions,execution_plan
from ucode.generation_cpu import execution_options
from test_lab_interface import cpu_fixture


class CorePlanTests(unittest.TestCase):
    def test_one_all_minus_two_and_all_mean_real_physical_cpu_sets(self):
        hardware={"cpu":cpu_fixture(14)}
        for choice,number in (("1",1),("all-2",12),("all",14)):
            p=GenerationPreferences(execution_backend="process",workers=number,cpu_choice=choice)
            options=execution_options(p,hardware)
            plan=execution_plan(options,50000,hardware["cpu"],11*1024**3,buffered=True)
            self.assertEqual(plan["effective_workers"],number)
            self.assertEqual(len({c['core'] for c in options.cpus}),number)
        p=GenerationPreferences(execution_backend="serial",workers=28,cpu_choice="all")
        with self.assertRaises(ValueError): execution_options(p,hardware)

    def test_ram_max_is_a_bounded_useful_cache_not_forced_allocation(self):
        from ucode.execution import useful_cache_mib
        normal=useful_cache_mib(ExecutionOptions(),11*1024**3)
        maximum=useful_cache_mib(ExecutionOptions(ram_mode="max"),11*1024**3)
        self.assertGreater(maximum,normal); self.assertLessEqual(maximum,512)

    def test_time_weighted_own_cpu_means_and_bound_cpu_attribution(self):
        from ucode.cpu_telemetry import CPUTrace
        with tempfile.TemporaryDirectory() as temp:
            cpus=select_cpus(cpu_fixture(2),"physical","all"); clock=[0.]
            trace=CPUTrace(cpus,Path(temp)/"samples.csv",clock=lambda:clock[0])
            trace.bind({"worker_affinity":{"100":[cpus[0]],"101":[cpus[1]]}})
            def stats(root,a,b): return [{"identity":identity,"cpu_seconds":cpu} for identity,cpu in (((os.getpid(),1),root),((100,1),a),((101,1),b))]
            trace.phase="Кодирование QR"; trace.sample(stats(10,0,0))
            clock[0]=1; trace.sample(stats(10.2,.8,.6))
            clock[0]=3; trace.sample(stats(10.6,1.8,.6))
            data=trace.finish(); phase=data["phases"]["Кодирование QR"]
            self.assertAlmostEqual(phase["busy_core_equivalents"]["mean"],1)
            self.assertAlmostEqual(phase["selected_cpu_load_pct"]["mean"],50)
            self.assertEqual(phase["peak_busy_worker_cpus"],2)
            self.assertEqual(phase["all_worker_cpus_busy_seconds"],1)
            self.assertAlmostEqual(next(iter(phase["per_cpu_pct"].values()))["mean"],60)

    def test_integrity_error_stops_instead_of_scheduling_hundreds_of_failures(self):
        from ucode.frozen_runtime import assert_trial_integrity
        with self.assertRaises(RuntimeError): assert_trial_integrity({"errors":["RuntimeError: Исходники изменились во время серии"]})


class RealCoreTests(unittest.TestCase):
    def setUp(self):
        from ucode.hardware import inspect_cpu
        self.cpu=inspect_cpu()
        if not self.cpu.get("available_physical") or self.cpu["available_physical"]<2: self.skipTest("Нужны два физических ядра")

    def test_production_processes_are_pinned_to_distinct_real_cores_and_no_sampler(self):
        from ucode.batch import run_batch
        from ucode.audit import audit_job
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/"codes.txt"; source.write_text(''.join(f'{200000000000+i}\n' for i in range(7)),encoding='utf-8')
            before=cpu_keys(self.cpu["available_cpus"])
            mask=tuple(select_cpus(self.cpu,"physical",2))
            events=[]
            job=run_batch(source,root/"output",mode="multipage",execution=ExecutionOptions("process",2,1,mask),force_disk=True,
                          qa_mode="deferred",activity="minimal",events=events.append)
            m=json.loads((job/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual((m["status"],m["seconds"]["quality_checks"]),("UNVERIFIED",0))
            affinities=m["execution"]["worker_affinity"]
            self.assertEqual(len(affinities),2)
            self.assertEqual({tuple(cpu_keys(v)) for v in affinities.values()},{tuple(cpu_keys([c])) for c in mask})
            self.assertTrue(any(e["execution"]["confirmed_processes"]==2 for e in events))
            self.assertFalse(list(job.rglob("cpu-samples.csv")))
            from ucode.hardware import inspect_cpu
            self.assertEqual(cpu_keys(inspect_cpu()["available_cpus"]),before)
            audit=audit_job(job,render_samples=False)
            self.assertEqual(json.loads((audit/"audit.json").read_text(encoding="utf-8"))["status"],"LIMITED")

    def test_lab_cpu_metrics_on_off_and_frozen_code_survives_live_fingerprint_change(self):
        from ucode.resource_lab import LabConfig,run_lab
        from ucode.lab_worker import code_fingerprint
        config=LabConfig(counts=(3,),cpu_units=("physical",),cpu_counts=("2",),backends=("process",),ram_modes=("auto",),
                         repeats=1,batch_size=1,pdf_profiles=("compact",),activity_modes=("minimal",),qa_mode="deferred",telemetry_modes=("off","cpu"))
        with tempfile.TemporaryDirectory() as temp:
            folder=run_lab(Path(temp),config)
            data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"UNVERIFIED",data)
            off,on=data["cases"]
            self.assertNotIn("cpu_telemetry",off["trials"][0]["memory"])
            trace=on["trials"][0]["memory"]["cpu_telemetry"]
            self.assertGreater(trace["samples"],0)
            self.assertGreaterEqual(trace["bound_worker_count"],1)
            self.assertEqual(len(data["telemetry_overhead_pairs"]),1)
            self.assertTrue((folder/"cpu-load.html").is_file())
            self.assertEqual(code_fingerprint(folder/".runtime/ucode"),data["source_digest"])
            self.assertEqual(Path(on["trials"][0]["runtime_code_root"]),folder/".runtime")
            # Corrupt only this test-owned frozen copy: a new trial must refuse it.
            from ucode.resource_lab import _run_trial
            request=json.loads(next((folder/"trials").glob("*/request.json")).read_text(encoding="utf-8"))
            with patch("ucode.lab_worker.code_fingerprint",return_value="changed-live-build"):
                result=_run_trial(folder/"live-change-check",request,None,None)
            self.assertEqual(result["status"],"UNVERIFIED",result)
            with (folder/".runtime/ucode/qr.py").open("a",encoding="utf-8") as stream: stream.write('\n# changed test-owned frozen build\n')
            result=_run_trial(folder/"integrity-check",request,None,None)
            self.assertEqual(result["status"],"ERROR",result)
            self.assertIn("Исходники изменились",str(result["errors"]))


class CoreWindowTests(unittest.TestCase):
    def test_visible_buttons_run_selected_core_and_save_all_and_smt(self):
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        from ucode.app_settings import load_user_preferences
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            try: window=tk.Tk()
            except tk.TclError as exc: self.skipTest(str(exc))
            window.withdraw(); app=BatchWindow(window,root/"out")
            try:
                if not app.hardware["cpu"].get("available_physical"): self.skipTest("Нет физической топологии")
                app.generation_cpu.buttons["all"].invoke()
                options=app.read_generation_options()
                self.assertEqual(options.cpu_choice,"all")
                self.assertEqual(options.workers,app.hardware["cpu"]["available_physical"])
                app.generation_cpu.unit_picker.choose("logical")
                self.assertEqual(app.read_generation_options().workers,app.hardware["cpu"]["available_logical"])
                app.generation_cpu.unit_picker.choose("physical")
                app.generation_cpu.buttons["1"].invoke()
                app.main_pdf_picker.choose("Компактный"); app.main_activity_picker.choose("minimal")
                self.assertEqual(app.print_settings.pdf_profile,"compact")
                self.assertEqual(app.read_generation_options().activity,"minimal")
                source=root/"codes.txt"; source.write_text('200000000001\n200000000002\n',encoding='utf-8')
                app.input_var.set(str(source)); app.qa_mode_var.set("Отложена"); app.start(); app.worker.join(15); app.poll()
                self.assertFalse(app.busy)
                result=json.loads((app.last_output/"manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(result["status"],"UNVERIFIED")
                self.assertEqual(result["execution"]["backend"],"process")
                self.assertEqual(len(result["execution"]["worker_affinity"]),1)
                app.generation_cpu.buttons["all"].invoke(); app.generation_cpu.ram.set("max"); app.remember()
                settings=load_user_preferences(app.preferences_path)[2]
                self.assertEqual((settings.cpu_choice,settings.ram_mode),("all","max"))
                app.lab_telemetry_picker.choose("off,cpu")
                from ucode.test_controls import custom_config
                cfg=custom_config(app)
                self.assertEqual(cfg.telemetry_modes,("off","cpu"))
            finally:
                if app.worker: app.worker.join(20)
                window.destroy(); del app,window
                import gc
                gc.collect()
