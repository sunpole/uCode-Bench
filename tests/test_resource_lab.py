"""CPU/RAM experiment contracts; actual PDFs stay at two pages."""
import json
import csv
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


def model():
    cpus = [{"id": i, "group": 0, "logical": i, "core": i // 2} for i in range(28)]
    return {"available_cpus": cpus, "available_logical": 28, "available_physical": 14}


class LabPlanTests(unittest.TestCase):
    def test_windows_reader_lock_is_retried_without_losing_final_json(self):
        from ucode.lab_worker import atomic_json
        real_replace=Path.replace; attempts=[]
        def replace(path,target):
            attempts.append(path)
            if len(attempts)<3: raise PermissionError("reader holds target")
            return real_replace(path,target)
        with tempfile.TemporaryDirectory() as temp:
            destination=Path(temp)/"progress.json"
            with patch.object(Path,"replace",replace): atomic_json(destination,{"percent":50})
            self.assertEqual(json.loads(destination.read_text()),{"percent":50})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(Path(temp).iterdir()),[destination])

    def test_physical_and_logical_all_minus_two_are_distinct(self):
        from ucode.affinity import select_cpus
        self.assertEqual(len(select_cpus(model(), "logical", "all-2")), 26)
        physical = select_cpus(model(), "physical", "all-2")
        self.assertEqual(len(physical), 12)
        self.assertEqual(len({cpu["core"] for cpu in physical}), 12)
        self.assertEqual(len(select_cpus(model(), "physical", "all")), 14)
        with self.assertRaises(ValueError): select_cpus(model(), "physical", "36")
        with self.assertRaises(ValueError): select_cpus(model(), "logical", "0")

    def test_safe_ram_budget_is_not_memory_allocation(self):
        from ucode.resource_monitor import ram_budget
        free = 11 * 1024**3
        maximum = ram_budget("max", free)
        half = ram_budget("50%", free)
        self.assertLess(maximum["budget_bytes"], free)
        self.assertGreaterEqual(maximum["reserve_bytes"], 1024**3)
        self.assertEqual(half["budget_bytes"], maximum["budget_bytes"] // 2)
        self.assertFalse(maximum["force_allocation"])

    def test_ram_guard_cancels_on_observed_limit_without_allocating_ram(self):
        from ucode.resource_monitor import TreeMonitor
        stop=threading.Event(); budget={"budget_bytes":100,"reserve_bytes":10}
        sample={"rss":101,"private":None,"identity":(1,1),"cpu_seconds":.1}
        monitor=TreeMonitor(stop,budget)
        with patch("ucode.resource_monitor.tree_stats",return_value=[sample]), patch("ucode.resource_monitor.memory_info",return_value={"available_bytes":10000}):
            monitor.sample()
        self.assertTrue(stop.is_set())
        self.assertTrue(monitor.reason)

    def test_thread_encoding_matches_serial_and_cancels_cleanly(self):
        from ucode.execution import ExecutionOptions, encode_values
        from ucode.hardware import inspect_cpu
        if inspect_cpu()["available_logical"]<2: self.skipTest("Нужны два CPU")
        values=[f"{200000000000+i:012d}" for i in range(7)]
        serial,_=encode_values(values)
        threaded,meta=encode_values(values,options=ExecutionOptions("thread",2,1))
        self.assertEqual(threaded,serial)
        self.assertLessEqual(meta["max_in_flight_values"],2)
        stop=threading.Event()
        with self.assertRaises(InterruptedError):
            encode_values(values,options=ExecutionOptions("thread",2,1),cancel=stop,on_progress=lambda done,total:stop.set())
        self.assertFalse(any(thread.name.startswith("ucode-encoder") for thread in threading.enumerate()))

    def test_matrix_defaults_three_repeats_and_skips_unavailable(self):
        from ucode.resource_lab import LabConfig, build_cases
        config = LabConfig(counts=(200, 500, 1000, 10000), cpu_counts=("1", "2", "36", "all-2"),
                           backends=("serial", "process", "thread"), ram_modes=("50%", "max"))
        cases = build_cases(config, model())
        self.assertEqual(config.repeats, 3)
        self.assertEqual(len(cases), 96)
        skipped = [case for case in cases if case["status"] == "SKIPPED"]
        self.assertEqual(len(skipped), 24)
        self.assertTrue(all(case["reason"] for case in skipped))
        with self.assertRaises(ValueError): LabConfig(counts=(0,))
        with self.assertRaisesRegex(ValueError,"4096"):
            LabConfig(counts=tuple(range(1,65)),cpu_counts=tuple(map(str,range(1,65))),
                      cpu_units=("logical","physical"),ram_modes=("auto","50%","80%","max"))

    def test_equivalent_physical_twelve_and_all_minus_two_are_not_repeated(self):
        from ucode.resource_lab import LabConfig,build_cases
        cases=build_cases(LabConfig(counts=(2,),cpu_counts=("12","all-2"),cpu_units=("physical",),
            backends=("process",),ram_modes=("max",)),model())
        self.assertEqual(cases[0]["status"],"PENDING")
        self.assertEqual(cases[1]["status"],"SKIPPED")
        self.assertEqual(cases[1]["equivalent_case"],cases[0]["id"])

    def test_failed_or_incomplete_trials_cannot_win(self):
        from ucode.lab_report import summarize_trials
        rows = [{"status": "COMPLETE", "seconds": {"production": value}, "warmup": False} for value in (2, 4, 3)]
        good = summarize_trials(rows, 3, 200)
        self.assertEqual(good["median_seconds"], 3)
        self.assertAlmostEqual(good["codes_per_second"], 200 / 3)
        warmup={"status":"COMPLETE","seconds":{"production":.001},"warmup":True}
        self.assertEqual(summarize_trials([warmup,*rows],3,200)["median_seconds"],3)
        self.assertIsNone(summarize_trials(rows[:-1], 3, 200)["median_seconds"])
        rows[0]["status"] = "INVALID"
        self.assertIsNone(summarize_trials(rows, 3, 200)["median_seconds"])


class RealLabTests(unittest.TestCase):
    def test_forced_cancel_kills_only_owned_trial_and_its_child(self):
        from ucode.resource_lab import _run_trial
        from ucode.resource_monitor import _windows_stats,_linux_stats
        import os,signal,subprocess,sys,time
        reader=_windows_stats if os.name=="nt" else _linux_stats
        real_popen=subprocess.Popen
        helper='''import json,os,subprocess,sys,time
from pathlib import Path
from ucode.resource_monitor import create_owned_job,_windows_stats,_linux_stats
job=create_owned_job(1024**3)
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'])
stats=(_windows_stats if os.name=='nt' else _linux_stats)(child.pid)
folder=Path(sys.argv[1])
(folder/'child.json').write_text(json.dumps({'pid':child.pid,'identity':stats['identity']}))
(folder/'progress.json').write_text(json.dumps({'percent':1}))
time.sleep(60)
'''
        stop=threading.Event()
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/"trial"
            def launch(args,**kwargs): return real_popen([sys.executable,"-c",helper,str(folder)],**kwargs)
            try:
                with patch("ucode.resource_lab.subprocess.Popen",side_effect=launch):
                    result=_run_trial(folder,{"warmup":False},stop,lambda event:stop.set(),timeout=10,cancel_grace=.05)
                self.assertEqual(result["status"],"CANCELLED")
                info=json.loads((folder/"child.json").read_text())
                alive=False
                for _ in range(20):
                    try:
                        current=reader(info["pid"])
                        alive=current["identity"]==tuple(info["identity"]) and current["rss"]>0
                    except OSError: alive=False
                    if not alive: break
                    time.sleep(.05)
                self.assertFalse(alive,"Owned helper child survived forced cancellation")
            finally:
                if (folder/"child.json").exists():
                    info=json.loads((folder/"child.json").read_text())
                    try:
                        if reader(info["pid"])["identity"]==tuple(info["identity"]):
                            os.kill(info["pid"],signal.SIGTERM if os.name=="nt" else signal.SIGKILL)
                    except OSError: pass

    def test_isolated_cpu_affinity_pdf_metrics_and_reports(self):
        from ucode.resource_lab import LabConfig, run_lab
        from ucode.hardware import inspect_cpu
        before=inspect_cpu()["available_cpus"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = run_lab(root, LabConfig(counts=(2,), cpu_counts=("1",), backends=("serial",),
                                            ram_modes=("max",), repeats=1))
            data = json.loads((folder / "lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "COMPLETE", data)
            trial = data["cases"][0]["trials"][0]
            self.assertEqual(len(trial["affinity"]["verified_cpus"]), 1)
            self.assertEqual(trial["manifest"]["count"], 2)
            self.assertEqual(trial["manifest"]["qa"]["multipage"]["status"], "PASS")
            self.assertGreater(trial["memory"]["peak_tree_rss_bytes"], 0)
            self.assertGreater(trial["seconds"]["production"], 0)
            for name in ("ОТЧЁТ.txt", "comparison.csv", "comparison.html"):
                self.assertTrue((folder / name).is_file())
            with (folder/"comparison.csv").open(encoding="utf-8-sig",newline="") as stream:
                csv_rows=list(csv.reader(stream))
            self.assertTrue(all(len(row)==len(csv_rows[0]) for row in csv_rows))
            from ucode.lab_report import write_reports
            data["cases"][0]["reason"]="<script>alert(1)</script>"
            write_reports(folder,data)
            document=(folder/"comparison.html").read_text(encoding="utf-8")
            self.assertEqual(document.count("<script>"),1)  # fixed offline chart code only
            self.assertNotIn("<script>alert(1)</script>",document)
        self.assertEqual(inspect_cpu()["available_cpus"],before)

    def test_live_cancel_preserves_partial_series_and_reaps_trial_tree(self):
        from ucode.resource_lab import LabConfig,run_lab
        from ucode.resource_monitor import tree_stats
        import os
        before={item["identity"] for item in tree_stats(os.getpid())}
        stop=threading.Event()
        with tempfile.TemporaryDirectory() as temp:
            folder=run_lab(Path(temp),LabConfig(counts=(2,),cpu_counts=("1",),backends=("process",),
                ram_modes=("max",),repeats=3),cancel=stop,events=lambda value:stop.set())
            data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"CANCELLED")
            self.assertLess(len(data["cases"][0]["trials"]),3)
            self.assertEqual(data["recommendations"],[])
            self.assertTrue((folder/"ОТЧЁТ.txt").exists())
        after={item["identity"] for item in tree_stats(os.getpid())}
        self.assertFalse(after-before)

    def test_cancelled_series_preserves_reports_and_does_not_start_jobs(self):
        from ucode.resource_lab import LabConfig, run_lab
        with tempfile.TemporaryDirectory() as temp:
            stop = threading.Event(); stop.set()
            folder = run_lab(Path(temp), LabConfig(counts=(2,), cpu_counts=("1",),
                backends=("serial",), ram_modes=("max",), repeats=1), cancel=stop)
            data = json.loads((folder / "lab.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "CANCELLED")
            self.assertFalse(list(folder.glob("trials/*/request.json")))
            self.assertTrue((folder / "ОТЧЁТ.txt").is_file())
