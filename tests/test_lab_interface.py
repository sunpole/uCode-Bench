"""CPU choices and report dispatch, without load tests or physical UI clicks."""
import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from ucode.batch_gui import BatchWindow
from ucode.hardware import cpu_model


def cpu_fixture(cores):
    result=cpu_model([{"id":i,"group":0,"logical":i,"core":i//2} for i in range(cores*2)])
    result.update(name="Fixture CPU",presets=(1,cores*2))
    return result


class LabInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw()
        self.app=BatchWindow(self.root,Path(self.temp.name)/"output")

    def tearDown(self):
        if hasattr(self,"app"):
            self.root.destroy(); self.app=self.root=None; gc.collect()

    def test_buttons_follow_current_pc_and_physical_logical_selection(self):
        self.app.hardware["cpu"]=cpu_fixture(2)
        self.app.lab_units.set("Физические: 1 поток/ядро")
        self.app.lab_refresh()
        self.assertIn("2 ядра",self.app.lab_hardware.get())
        self.assertIn("4 потока",self.app.lab_hardware.get())
        self.assertTrue(self.app.lab_cpu_buttons["4"].instate(["disabled"]))
        self.assertTrue(self.app.lab_cpu_buttons["all-2"].instate(["disabled"]))
        self.assertIn("2",self.app.lab_cpu_buttons["all"].cget("text"))
        self.app.lab_units.set("Логические CPU")
        self.assertTrue(self.app.lab_cpu_buttons["4"].instate(["!disabled"]))
        self.assertIn("2",self.app.lab_cpu_buttons["all-2"].cget("text"))
        self.app.lab_cpus.set("1")
        self.app.lab_cpu_buttons["2"].invoke()
        from ucode.lab_ui import read_form
        self.assertEqual(read_form(self.app).cpu_counts,("1","2"))
        self.app.lab_cpu_buttons["1"].invoke()
        self.assertEqual(read_form(self.app).cpu_counts,("2",))
        self.app.busy=True; self.app.update_buttons()
        self.assertTrue(self.app.lab_cpu_buttons["2"].instate(["disabled"]))
        self.app.busy=False; self.app.update_buttons()
        self.assertTrue(self.app.lab_cpu_buttons["8"].instate(["disabled"]))

    def test_unknown_topology_is_not_invented_and_cores_match_14_core_pc(self):
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_units.set("Физические: 1 поток/ядро"); self.app.lab_refresh()
        self.assertTrue(self.app.lab_cpu_buttons["12"].instate(["!disabled"]))
        self.assertIn("12",self.app.lab_cpu_buttons["all-2"].cget("text"))
        self.assertIn("14",self.app.lab_cpu_buttons["all"].cget("text"))
        self.app.hardware["cpu"]=cpu_model([],fallback_count=8)
        self.app.lab_refresh()
        self.assertIn("неизвестно",self.app.lab_hardware.get())
        self.assertTrue(self.app.lab_cpu_buttons["1"].instate(["disabled"]))

    def test_warmup_explains_real_extra_runs_and_preview(self):
        self.app.lab_counts.set("2"); self.app.lab_cpus.set("1")
        self.app.lab_backends.set("serial"); self.app.lab_ram.set("max")
        self.app.lab_pdf_profiles.set("standard"); self.app.lab_activities.set("normal")
        self.app.lab_repeats.set("3"); self.app.lab_warmups.set("1")
        self.assertIn("не входят",self.app.lab_warmup_help.cget("text"))
        self.assertIn("прогонов: 4",self.app.lab_preview.get())

    def test_html_report_dispatch_bypasses_file_association(self):
        report=Path(self.temp.name)/"отчёт #1.html"; report.write_text("<html></html>",encoding="utf-8")
        self.app.last_report=report
        with patch("ucode.batch_gui.open_html_report") as browser,patch("ucode.batch_gui.os.startfile",create=True) as editor:
            self.app.open_report()
            browser.assert_called_once_with(report)
            editor.assert_not_called()


class BrowserDispatchTests(unittest.TestCase):
    def test_windows_uses_protocol_browser_and_uri_as_separate_argument(self):
        from ucode.open_reports import open_html_report
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"тест & #1.html"; path.write_text("<html/>",encoding="utf-8")
            exe=Path(temp)/"browser.exe"
            with patch("ucode.open_reports.sys.platform","win32"),patch("ucode.open_reports._windows_browser_executable",return_value=exe),patch("ucode.open_reports.subprocess.Popen") as launch:
                open_html_report(path)
                self.assertEqual(launch.call_args.args[0],[str(exe),path.resolve().as_uri()])
                self.assertNotIn("shell",launch.call_args.kwargs)

    def test_failure_to_find_browser_is_not_silently_sent_to_editor(self):
        from ucode.open_reports import open_html_report
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"report.html"; path.write_text("<html/>")
            with patch("ucode.open_reports.sys.platform","win32"),patch("ucode.open_reports._windows_browser_executable",side_effect=OSError("No browser")),patch("ucode.open_reports.webbrowser.open_new_tab") as fallback:
                with self.assertRaises(OSError): open_html_report(path)
                fallback.assert_not_called()
