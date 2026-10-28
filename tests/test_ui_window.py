"""Actual Tk controllers/widgets; not a claim about native screenshot capture."""
import gc
import json
from pathlib import Path
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import patch

from ucode.batch_gui import BatchWindow, clock_text
from ucode.batch import run_batch


class OperatorWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-operator-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.app = BatchWindow(self.root, self.folder / "output")

    def tearDown(self):
        if hasattr(self, "app"):
            if self.app.worker:
                self.app.worker.join(timeout=10)
            self.root.destroy()
            self.app = self.root = None
            gc.collect()

    def test_open_txt_shows_source_count_and_enables_primary(self):
        path = self.folder / "my.txt"
        path.write_text("000000000001\n200000000099\n", encoding="utf-8")
        with patch("ucode.batch_gui.filedialog.askopenfilename", return_value=str(path)):
            self.app.choose()
        self.assertIn("2 кодов", self.app.file_count.get())
        self.assertIn("000000000001", self.app.file_count.get())
        self.assertIn("200000000099", self.app.file_count.get())
        self.assertTrue(self.app.generate.instate(["!disabled"]))
        self.assertEqual(self.app.mode_var.get(), "multipage")

    def test_invalid_txt_disables_primary_and_gives_line_number(self):
        path = self.folder / "bad.txt"
        path.write_text("200000000000\nBAD\n", encoding="utf-8")
        self.app.input_var.set(str(path))
        self.assertIsNone(self.app.inspect_input())
        self.assertIn("Строка 2", self.app.file_count.get())
        self.app.update_buttons()
        self.assertTrue(self.app.generate.instate(["disabled"]))

    def test_real_worker_generates_pdf_report_and_finishes_progress(self):
        path = self.folder / "real.txt"
        path.write_text("200000000123\n200000000456\n", encoding="utf-8")
        self.app.input_var.set(str(path))
        self.app.start()
        self.app.worker.join(timeout=10)
        self.assertFalse(self.app.worker.is_alive())
        self.app.poll()
        self.assertFalse(self.app.busy)
        self.assertIsNotNone(self.app.last_pdf)
        self.assertTrue(self.app.last_pdf.is_file())
        self.assertTrue(self.app.last_report.is_file())
        manifest = json.loads((self.app.last_output / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(manifest["status"], ("COMPLETE", "LIMITED"))
        self.assertTrue(self.app.open.instate(["!disabled"]))
        self.assertEqual(float(self.app.progress["value"]) == 100, manifest["status"] == "COMPLETE")

    def test_main_contains_no_scrollbars_and_request_fits_laptop(self):
        def children(widget):
            for item in widget.winfo_children():
                yield item
                yield from children(item)
        self.root.update_idletasks()
        self.assertFalse(any(isinstance(w, (tk.Scrollbar,)) or w.winfo_class() == "TScrollbar" for w in children(self.root)))
        self.assertLessEqual(self.root.winfo_reqwidth(), 1300)
        self.assertLessEqual(self.root.winfo_reqheight(), 700)
        self.assertEqual(clock_text(2071), "00:34:31")

    def test_required_layout_fits_1366_768_at_100_125_150_percent(self):
        for scale in (96 / 72, 120 / 72, 144 / 72):
            window = tk.Tk()
            window.withdraw()
            window.tk.call("tk", "scaling", scale)
            app = BatchWindow(window, self.folder / f"dpi-{scale}" / "out")
            window.update_idletasks()
            with self.subTest(scale=scale):
                self.assertEqual(window.getvar(str(app.plan_var)), app.plan_var.get())
                self.assertLessEqual(window.winfo_reqheight(), window.minsize()[1])
                self.assertLessEqual(window.minsize()[1], 668)
                self.assertLessEqual(window.minsize()[0], 1326)
            window.destroy()
            del app, window
            gc.collect()

    def test_dark_theme_and_settings_live_inside_the_same_window(self):
        rgb = self.root.winfo_rgb(self.root.cget("background"))
        self.assertLess(max(rgb) / 65535, .2)
        self.app.geometry_dialog(True)
        self.app.color_dialog()
        self.app.performance_dialog()
        self.app.show_help()
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)
        self.assertFalse(any(isinstance(widget, tk.Toplevel) for widget in walk(self.root)))
        self.assertEqual(self.app.notebook.select(), str(self.app.pages["help"]))

    def test_copies_preview_and_real_output_in_selected_folder(self):
        path = self.folder / "copies.txt"
        path.write_text("000000000001\n200000000002\n000000000001\n", encoding="utf-8")
        destination = self.folder / "my-pdfs"
        self.app.destination_var.set(str(destination))
        self.app.input_var.set(str(path))
        self.app.copies_var.set("3")
        self.app.duplicates_var.set("Только уникальные")
        self.app.inspect_input()
        self.assertIn("2 уникальных × 3", self.app.plan_var.get())
        self.assertIn("6 кодов", self.app.plan_var.get())
        self.app.start()
        self.app.worker.join(timeout=10)
        self.assertFalse(self.app.worker.is_alive())
        self.app.poll()
        self.assertEqual(self.app.last_output.parent.resolve(), destination.resolve())
        data = json.loads((self.app.last_output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["files"]["multipage"]["pages"], 6)
        self.assertEqual(data["generation"]["encoded_values"], 2)
        self.assertEqual(data["qa"]["multipage"]["status"], "PASS")

    def test_invalid_copies_disable_creation_and_defaults_restore(self):
        path = self.folder / "codes.txt"
        path.write_text("200000000001\n", encoding="utf-8")
        self.app.input_var.set(str(path))
        self.app.inspect_input()
        self.app.copies_var.set("0")
        self.assertTrue(self.app.generate.instate(["disabled"]))
        self.app.copies_var.set("3")
        self.assertTrue(self.app.generate.instate(["!disabled"]))
        self.app.geometry_dialog(True)
        self.app.geometry_value.set("0.7")
        self.app.apply_print()
        self.assertAlmostEqual(self.app.print_settings.module_mm, .7)
        self.app.restore_defaults()
        self.assertEqual(self.app.copies_var.get(), "1")
        self.assertAlmostEqual(self.app.print_settings.module_mm, .5)
        self.assertEqual(self.app.mode_var.get(), "multipage")

    def test_cpu_panel_and_process_worker_from_tk_thread(self):
        if self.app.hardware["cpu"]["available_logical"] < 2:
            self.skipTest("Нужны два доступных CPU")
        path = self.folder / "cpu.txt"
        path.write_text("200000000001\n200000000002\n", encoding="utf-8")
        self.app.input_var.set(str(path))
        self.app.show_resources()
        self.app.backend_var.set("Процессы")
        self.app.workers_var.set("2")
        self.app.batch_size_var.set("1")
        self.app.inspect_input()
        self.app.start()
        self.app.worker.join(timeout=15)
        self.assertFalse(self.app.worker.is_alive())
        self.app.poll()
        data = json.loads((self.app.last_output / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(data["status"], ("COMPLETE", "LIMITED"))
        self.assertEqual(data["execution"]["backend"], "process")
        self.assertEqual(len(data["execution"]["worker_pids"]), 2)
        self.assertEqual(data["qa"]["multipage"]["pages_checked"], 2)
        self.assertEqual(self.app.read_generation_options().workers, 2)

    def test_cpu_count_above_available_is_rejected(self):
        path = self.folder / "cpu.txt"
        path.write_text("200000000001\n", encoding="utf-8")
        self.app.input_var.set(str(path)); self.app.inspect_input()
        self.app.backend_var.set("Процессы")
        self.app.workers_var.set(str(self.app.hardware["cpu"]["available_logical"] + 1))
        self.assertTrue(self.app.generate.instate(["disabled"]))
        self.assertIn("CPU", self.app.plan_var.get())


class CancellationTests(unittest.TestCase):
    def test_cancel_during_encoding_keeps_input_and_never_shows_100(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.txt"
            raw = "\n".join(str(200000000000 + i) for i in range(20)) + "\n"
            source.write_text(raw, encoding="utf-8")
            stop = threading.Event()
            events = []
            def observe(value):
                events.append(value)
                if value["stage"] == "Кодирование QR" and value["done"]:
                    stop.set()
            folder = run_batch(source, root / "jobs", mode="multipage", cancel=stop, events=observe)
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "CANCELLED")
            self.assertTrue((folder / "ОТЧЁТ.txt").exists())
            self.assertEqual(source.read_text(encoding="utf-8"), raw)
            self.assertTrue(all(e["percent"] < 100 for e in events))
