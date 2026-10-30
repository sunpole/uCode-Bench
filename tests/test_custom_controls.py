"""Exact user-selected launch counts and every individual result, small PDFs only."""
import copy
import csv
import gc
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from ucode.batch_gui import BatchWindow
from ucode.resource_lab import preview,build_cases
from ucode.test_controls import custom_config
from ucode.trial_results import trial_rows,case_statistics,write_trial_results,recommendation
from test_history import example
from test_lab_interface import cpu_fixture


def sample(cpus,repeats):
    data=example(); template=data["cases"][0]; trial=template["trials"][0]
    data["config"]["repeats"]=repeats; data["cases"]=[]
    for index,n in enumerate(cpus,1):
        case=copy.deepcopy(template); case.update(id=f"C{index:04d}",cpu_choice=str(n),cpus=[{}]*n,trials=[])
        for repeat in range(1,repeats+1):
            row=copy.deepcopy(trial); row["seconds"]={"production":repeat,"total_including_qa":repeat+1,"quality_checks":1}
            case["trials"].append(row)
        data["cases"].append(case)
    return data


class IndividualResultsTests(unittest.TestCase):
    def test_two_modes_once_mean_exactly_two_results(self):
        data=sample((1,14),1)
        self.assertEqual(len(trial_rows(data)),2)
        self.assertEqual([row["repeat"] for row in trial_rows(data)],[1,1])

    def test_three_modes_ten_repeats_show_all_thirty_rows_and_statistics(self):
        data=sample((2,4,12),10); rows=trial_rows(data)
        self.assertEqual(len(rows),30)
        self.assertEqual([row["repeat"] for row in rows],list(range(1,11))*3)
        stats=case_statistics(data)
        self.assertEqual([row["mean_total"] for row in stats],[6.5]*3)
        self.assertEqual([row["min_total"] for row in stats],[2]*3)
        self.assertEqual([row["max_total"] for row in stats],[11]*3)

    def test_missing_and_failed_rows_remain_visible_without_fake_times_or_winner(self):
        data=sample((1,2),2); data["cases"][1]["trials"]=[]; data["cases"][1]["status"]="CANCELLED"
        rows=trial_rows(data)
        self.assertEqual(len(rows),4)
        self.assertIsNone(rows[-1]["production"])
        self.assertEqual(rows[-1]["status"],"NOT_RUN")
        self.assertIn("победителя нет",recommendation(data))

    def test_equal_times_do_not_claim_one_mode_is_faster(self):
        text=recommendation(sample((1,14),1))
        self.assertIn("Разница до 5%",text)
        self.assertNotIn("Быстрее",text)

    def test_csv_and_browser_report_have_every_trial_and_escape_text(self):
        data=sample((2,4,12),10); data["cases"][0]["reason"]="<script>bad()</script>"
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); write_trial_results(folder,data)
            with (folder/"all-results.csv").open(encoding="utf-8-sig",newline="") as stream: rows=list(csv.reader(stream))
            self.assertEqual(len(rows),31)
            document=(folder/"all-results.html").read_text(encoding="utf-8")
            self.assertIn("Все результаты: 30",document)
            self.assertEqual(document.count("<script>"),1)  # fixed offline chart code only
            self.assertNotIn("<script>bad()</script>",document)
            self.assertIn("&lt;script&gt;",document)


class CustomControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.app=BatchWindow(self.root,Path(self.temp.name)/"output")

    def tearDown(self):
        if hasattr(self,"app"):
            if self.app.worker: self.app.worker.join(timeout=10)
            self.root.destroy(); self.app=self.root=None; gc.collect()

    def test_custom_quantity_and_one_all_do_not_expand_into_hidden_axes(self):
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_counts.set("2 000"); self.app.lab_repeats.set("1"); self.app.lab_cpus.set("1,all")
        self.app.lab_units.set("Физические: 1 поток/ядро")
        config=custom_config(self.app)
        self.assertEqual(config.counts,(2000,)); self.assertEqual(config.repeats,1); self.assertEqual(config.warmups,0)
        self.assertEqual(preview(config,self.app.hardware)["runs"],2)
        self.assertEqual(len(build_cases(config,self.app.hardware["cpu"])),2)
        self.assertEqual((len(config.backends),len(config.pdf_profiles),len(config.activity_modes),len(config.ram_modes)),(1,1,1,1))

    def test_ten_thousand_two_four_twelve_ten_repeats_plan_only(self):
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_counts.set("10000"); self.app.lab_repeats.set("10"); self.app.lab_cpus.set("12,2,4")
        self.app.lab_units.set("Физические: 1 поток/ядро")
        config=custom_config(self.app)
        self.assertEqual(config.cpu_counts,("2","4","12"))
        self.assertEqual(preview(config,self.app.hardware)["runs"],30)
        self.assertIn("30 запусков",self.app.test_controls.plan.get())
        self.assertIsNone(self.app.worker)

    def test_real_two_small_runs_from_the_single_primary_button(self):
        if self.app.hardware["cpu"]["available_logical"]<2: self.skipTest("Need two available CPUs")
        self.app.show_lab(); self.app.lab_units.set("Логические CPU")
        self.app.lab_counts.set("2"); self.app.lab_repeats.set("1"); self.app.lab_cpus.set("1,2")
        self.assertEqual(self.app.generate.cget("text"),"ЗАПУСТИТЬ ТЕСТЫ")
        self.assertTrue(self.app.generate.instate(["!disabled"]))
        self.app.generate.invoke(); self.app.worker.join(timeout=20)
        self.assertFalse(self.app.worker.is_alive()); self.app.poll()
        data=json.loads((self.app.last_output/"lab.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"],"COMPLETE",data)
        self.assertEqual(len(self.app.test_controls.rows),2)
        self.assertEqual([len(case["trials"]) for case in data["cases"]],[1,1])
        self.assertEqual(self.app.last_report.name,"all-results.html")
        self.assertEqual(self.app.report_button.cget("text"),"Все результаты (2)")

    def test_simple_and_expanded_controls_fit_at_150_percent(self):
        self.root.tk.call("tk","scaling",2.0)
        # New widgets use the scaling of their own interpreter on construction.
        other=tk.Tk(); other.withdraw(); other.tk.call("tk","scaling",2.0)
        app=BatchWindow(other,Path(self.temp.name)/"dpi"/"output")
        try:
            app.hardware["cpu"]=cpu_fixture(14)
            app.lab_counts.set("10000"); app.lab_repeats.set("10"); app.lab_cpus.set("2,4,12")
            app.lab_units.set("Физические: 1 поток/ядро")
            for expanded in (False,True):
                if app.test_controls.expanded!=expanded: app.test_controls.toggle()
                other.update_idletasks()
                self.assertLessEqual(other.winfo_reqheight(),668)
                self.assertLessEqual(other.winfo_reqwidth(),1326)
        finally:
            other.destroy(); del app; gc.collect()
