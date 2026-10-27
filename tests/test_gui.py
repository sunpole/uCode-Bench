"""Tk controller checks; these do not claim physical input/visual proof."""
import json
import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from ucode.gui import Application


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-gui-")
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Application(self.root, Path(self.temp.name))

    def tearDown(self):
        if self.app.worker is not None:
            self.app.worker.join(timeout=3)
        self.root.destroy()
        # Tk objects must be finalized on the creating thread. Otherwise cyclic
        # objects from an earlier fixture can be GC'd by the next worker thread.
        self.app = None
        self.root = None
        gc.collect()

    def test_1000_initially_disabled(self):
        self.assertTrue(self.app.next_button.instate(["disabled"]))
        self.assertIsNone(self.app.worker)

    def test_benchmark_button_uses_worker_and_displays_error_report(self):
        directory = Path(self.temp.name) / "error-run"
        directory.mkdir()
        (directory / "report.json").write_text(json.dumps({"status": "ERROR", "error": "test failure", "methods": []}), encoding="utf-8")
        with patch("ucode.benchmark.run_experiment", return_value=directory) as run, patch("tkinter.messagebox.showerror"):
            self.app.run_button.invoke()
            self.assertTrue(self.app.busy)
            self.app.worker.join(timeout=3)
            self.assertFalse(self.app.worker.is_alive())
            self.app.drain_events()
            self.assertFalse(self.app.busy)
            self.assertIn("Ошибка запуска", self.app.status.get())
            self.assertNotIn("Готово:", self.app.status.get())
            self.assertEqual(run.call_args.args[1].count, 200)

    def test_create_button_uses_200_and_returns_directory(self):
        with patch("ucode.benchmark.create_inputs", return_value=Path(self.temp.name)) as create:
            self.app.create_button.invoke()
            self.app.worker.join(timeout=3)
            self.app.drain_events()
            self.assertEqual(create.call_args.args[1].count, 200)
            self.assertEqual(self.app.latest_directory, Path(self.temp.name))
            self.assertFalse(self.app.busy)

    def test_cancel_request_sets_event_and_disables_repeated_request(self):
        self.app.busy = True
        self.app.update_buttons()
        self.app.cancel_button.invoke()
        self.assertTrue(self.app.cancel_event.is_set())
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))

    def test_close_waits_for_worker_thread_after_done_event(self):
        worker = Mock()
        worker.is_alive.return_value = True
        self.app.worker = worker
        try:
            with patch.object(self.root, "destroy") as destroy, patch.object(self.root, "after"):
                self.app.close()
                self.assertTrue(self.app.closing)
                self.app.drain_events()
                destroy.assert_not_called()
                worker.is_alive.return_value = False
                self.app.drain_events()
                destroy.assert_called_once()
        finally:
            self.app.worker = None


if __name__ == "__main__":
    unittest.main()
