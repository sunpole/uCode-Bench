"""Native Tk history controls, no physical clicks and no large workloads."""
import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from ucode.batch_gui import BatchWindow
from test_history import example,save


class HistoryUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.app=BatchWindow(self.root,self.folder/"output")

    def tearDown(self):
        if hasattr(self,"app"):
            if self.app.worker: self.app.worker.join(timeout=5)
            self.root.destroy(); self.app=self.root=None; gc.collect()

    def finish_read(self):
        self.app.worker.join(timeout=5)
        self.assertFalse(self.app.worker.is_alive())
        self.app.poll()
        self.assertFalse(self.app.busy)

    def test_real_two_page_lab_is_browsable_without_changing_saved_files(self):
        from ucode.resource_lab import LabConfig,run_lab
        destination=self.folder/"my-results"
        run=run_lab(destination/"laboratory",LabConfig(counts=(2,),cpu_counts=("1",),backends=("serial",),ram_modes=("max",),repeats=1))
        original={p:p.read_bytes() for p in run.rglob("*") if p.is_file()}
        self.app.destination_var.set(str(destination))
        self.app.last_output=run; self.app.last_report=run/"comparison.html"
        self.app.show_history(); self.finish_read()
        view=self.app.history_view
        self.assertEqual(len(view.entries),1)
        self.assertEqual(view.entries[0].status,"COMPLETE")
        self.assertEqual(self.app.last_output,run)
        view.buttons["cases"].invoke(); self.finish_read()
        self.assertEqual(view.mode,"cases")
        self.assertEqual(view.run["results"][0]["status"],"PASS")
        self.assertTrue(view.buttons["pdf"].instate(["!disabled"]))
        with patch("ucode.batch_gui.open_html_report") as browser:
            view.buttons["report"].invoke()
            self.assertTrue(browser.call_args.args[0].samefile(run/"comparison.html"))
        with patch.object(self.app,"open_path") as opened:
            view.buttons["pdf"].invoke()
            self.assertEqual(opened.call_args.args[0].suffix,".pdf")
            self.assertTrue(opened.call_args.args[0].is_file())
        self.assertEqual(original,{p:p.read_bytes() for p in run.rglob("*") if p.is_file()})

    def test_paging_search_status_filter_and_missing_pdf(self):
        for index in range(7): save(self.folder,example(),f"lab-example-{index}")
        view=self.app.history_view; view.refresh(self.folder); self.finish_read()
        self.assertIn(len(view.table.get_children()),(3,4))
        self.assertTrue(view.buttons["next"].instate(["!disabled"]))
        seen=set(view.table.get_children())
        while view.buttons["next"].instate(["!disabled"]):
            view.buttons["next"].invoke()
            seen.update(view.table.get_children())
            self.assertLessEqual(len(view.table.get_children()),4)
        self.assertEqual(len(seen),7)
        view.search.set("lab-example-0")
        self.assertEqual(len(view.table.get_children()),1)
        view.buttons["cases"].invoke(); self.finish_read()
        self.assertTrue(view.buttons["pdf"].instate(["disabled"]))
        view.search.set(""); view.filter.set("С проблемами")
        self.assertEqual(view.table.get_children(),())
        self.assertTrue(view.buttons["report"].instate(["disabled"]))

    def test_bad_json_does_not_replace_generation_result_or_leave_busy_state(self):
        path=save(self.folder,{},"lab-broken")
        self.app.last_output=self.folder/"previous-job"
        view=self.app.history_view; view.refresh(self.folder); self.finish_read()
        self.assertEqual(view.entries[0].status,"ОШИБКА")
        view.show_cases(); self.finish_read()
        self.assertEqual(view.mode,"runs")
        self.assertEqual(self.app.last_output,self.folder/"previous-job")
        self.assertIn("История:",self.app.status_var.get())
        self.assertEqual(path.read_text(encoding="utf-8"),"{}")
