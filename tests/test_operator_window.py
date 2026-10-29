import gc
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from ucode.operator_window import OperatorWindow


class NewOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ucode-v030-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.withdraw();self.app=OperatorWindow(self.root,self.folder/'output')
    def tearDown(self):
        if hasattr(self,'app'):
            self.app.cancel.set();self.app.search_cancel.set()
            if self.app.worker:self.app.worker.join(10)
            self.root.update_idletasks();self.root.destroy();self.app=self.root=None;gc.collect()
    def load(self):
        p=self.folder/'mine.txt';p.write_text('000000100000\n000000100003\n000000100006\n',encoding='utf-8')
        self.app.input_var.set(str(p));self.assertIsNotNone(self.app.inspect_input());return p
    def drain(self):
        if self.app.worker:self.app.worker.join(10)
        self.app.poll()
    def test_routes_old_test_views_and_defaults(self):
        for key in ('type','source','path','print','resources','generation','testing','other','lab','pipeline','search','tests','console','archive','history','help','contacts','legacy'):
            self.assertIn(key,self.app.pages)
        self.assertEqual(self.app.qa_mode_var.get(),'Отложена')
        self.assertEqual(self.app.generation_cpu.choice.get(),'all')
        self.assertEqual(self.app.generation_cpu.ram.get(),'max')
        self.assertEqual(self.app.telemetry_var.get(),'cpu')
    def test_source_index_and_real_preview_use_selected_code(self):
        self.load();self.app.goto_row(3);self.app.paint_preview()
        self.assertEqual(self.app.current_row,3)
        self.assertEqual(self.app.source_table.item('3','values')[1],'000000100006')
        self.assertGreater(len(self.app.preview_canvas.find_all()),50)
    def test_settings_are_applied_without_extra_apply_action(self):
        self.load();self.app.geometry_value.set('29');self.app.preview_print()
        self.assertEqual(self.app.print_settings.side_mm,29)
        self.app.background_mode_var.set('color');self.app.background_vars[3].set('100')
        for var in self.app.ink_vars:var.set('0')
        self.assertIsNotNone(self.app.preview_print())
        self.assertEqual(self.app.print_settings.background_ink,(0,0,0,100))
    def test_test_settings_do_not_change_production_order(self):
        self.load();before=self.app.order_payload()
        ctx=self.app.lab_context;ctx.qa_mode_var.set('Без растра');ctx.xy_mode_var.set('on');ctx.remember()
        self.assertEqual(self.app.order_payload(),before)
        self.assertEqual(self.app.qa_mode_var.get(),'Отложена')
    def test_path_check_stales_when_order_changes(self):
        self.load();self.app.check_destination();self.drain()
        self.assertTrue(self.app.approval.signature)
        self.app.copies_var.set('2');self.app.refresh_plan()
        self.assertIsNone(self.app.approval.signature)
        self.app.start()
        self.assertEqual(self.app.notebook.select(),str(self.app.pages['path']))
        self.assertFalse(self.app.busy)

    def test_real_generation_from_new_window_and_checked_output(self):
        self.load();self.app.generation_cpu.choice.set('1');self.app.generation_cpu.select()
        self.app.qa_mode_var.set('Полная');self.app.check_destination();self.drain()
        self.app.notebook.select(self.app.pages['generation']);self.app.start()
        self.assertTrue(self.app.busy);self.assertIsNotNone(self.app.operation_host)
        self.drain()
        self.assertFalse(self.app.busy)
        manifest=json.loads((self.app.last_output/'manifest.json').read_text(encoding='utf-8'))
        self.assertIn(manifest['status'],('COMPLETE','LIMITED'))
        self.assertEqual(manifest['files']['multipage']['pages'],3)
        self.assertTrue(self.app.last_pdf.is_file());self.assertTrue(self.app.last_report.is_file())
        self.assertEqual(self.app.last_report.name,'production.html')

    def test_stop_confirmation_requires_three_seconds_and_keeps_work_on_continue(self):
        self.app.busy=True
        callbacks=[]
        with patch.object(self.root,'after',side_effect=lambda delay,callback:callbacks.append(callback) or 'fake'):
            self.app.request_cancel()
            def buttons(widget):
                return [w for w in widget.winfo_children() if w.winfo_class()=='TButton']+sum((buttons(w) for w in widget.winfo_children()),[])
            answers=buttons(self.app.stop_dialog)
            self.assertEqual(len(answers),2)
            for turn in range(3):
                self.assertTrue(all(str(w.cget('state'))=='disabled' for w in answers))
                callbacks[-1]()
            self.assertTrue(all(str(w.cget('state'))=='normal' for w in answers))
            self.app.continue_operation()
        self.assertTrue(self.app.busy);self.assertFalse(self.app.cancel.is_set());self.app.busy=False

    def test_busy_guard_precedes_widget_bindings_and_blocks_navigation(self):
        before=self.app.notebook.select();self.app.begin()
        self.app.notebook.select(self.app.pages['print'])
        self.assertEqual(self.app.notebook.select(),before)
        self.assertTrue(self.app.source_table.bindtags()[0].startswith('OperatorGuard'))
        self.assertEqual(str(self.app.custom_count_entry.cget('state')),'disabled')
        self.app.busy=False;self.app.update_buttons()
        self.assertEqual(str(self.app.custom_count_entry.cget('state')),'normal')
