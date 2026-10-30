"""Settings are operated by buttons, with numeric entry only for custom values."""
import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from ucode.batch_gui import BatchWindow
from ucode.lab_ui import read_form
from ucode.test_controls import custom_config
from test_lab_interface import cpu_fixture


class ButtonSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.root.withdraw(); self.app=BatchWindow(self.root,Path(self.temp.name)/"output")

    def tearDown(self):
        if hasattr(self,"app"):
            self.root.destroy(); self.app=self.root=None; gc.collect()

    def test_settings_have_no_editable_text_entries_or_comboboxes(self):
        def walk(parent):
            for child in parent.winfo_children():
                yield child; yield from walk(child)
        for key in ("lab","generation","print","resources"):
            with self.subTest(page=key):
                entries=[widget for widget in walk(self.app.pages[key]) if widget.winfo_class() in ("TEntry","TCombobox") and str(widget.cget("state"))!="readonly"]
                self.assertEqual(entries,[])

    def test_profile_menu_multiple_choice_updates_real_config_and_caption(self):
        picker=self.app.lab_pdf_picker
        self.app.lab_pdf_profiles.set("standard,compact")
        picker.menu.invoke(picker.values["compact"])
        self.assertEqual(read_form(self.app).pdf_profiles,("standard",))
        self.assertIn("Обычный",picker.button.cget("text"))
        picker.menu.invoke(picker.values["compact"])
        self.assertEqual(read_form(self.app).pdf_profiles,("standard","compact"))
        self.assertIn("выбрано 2",picker.button.cget("text"))

    def test_execution_and_activity_menus_do_not_require_english_input(self):
        self.app.lab_backends.set("Последовательно,Процессы")
        picker=self.app.lab_backend_picker
        picker.menu.invoke(picker.values["serial"])
        self.assertEqual(read_form(self.app).backends,("process",))
        self.app.lab_activities.set("normal,minimal")
        picker=self.app.lab_activity_picker; picker.menu.invoke(picker.values["normal"])
        self.assertEqual(read_form(self.app).activity_modes,("minimal",))
        self.assertIn("Минимум расходов",picker.button.cget("text"))

    def test_ram_custom_number_and_safe_max_are_preserved(self):
        self.app.lab_ram.set("auto")
        control=self.app.lab_ram_control; control.input.set("1,5"); control.add_button.invoke()
        self.assertEqual(read_form(self.app).ram_modes,("auto","1536MiB"))
        control.picker.menu.invoke(control.picker.values["max"])
        self.assertIn("max",read_form(self.app).ram_modes)
        self.assertIn("1536MiB",control.picker.selected())

    def test_quantity_spin_and_add_button_support_single_or_multiple_counts(self):
        control=self.app.lab_count_control
        control.input.set("2000")
        self.assertEqual(custom_config(self.app).counts,(2000,))
        self.app.test_controls.toggle()
        control.input.set("5000"); control.add_button.invoke()
        self.assertEqual(read_form(self.app).counts,(2000,5000))
        self.assertEqual(control.input.get(),"5000")
        self.app.test_controls.toggle()
        self.assertEqual(custom_config(self.app).counts,(5000,))
        self.app.test_controls.toggle()
        control.picker.menu.invoke(control.picker.values["2000"])
        self.assertEqual(read_form(self.app).counts,(5000,))

    def test_numeric_input_validity_is_updated_before_start(self):
        self.app.show_lab()
        self.app.lab_count_control.input.set("0")
        self.assertFalse(self.app.test_controls.valid)
        self.assertTrue(self.app.generate.instate(["disabled"]))
        self.app.lab_count_control.input.set("2000")
        self.assertTrue(self.app.test_controls.valid)
        self.assertTrue(self.app.generate.instate(["!disabled"]))
        self.app.lab_count_control.input.set("100001")
        self.assertEqual(custom_config(self.app).counts,(100001,))
        self.assertTrue(self.app.generate.instate(["!disabled"]))

    def test_arbitrary_cpu_menu_and_warmup_worker_buttons(self):
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_units.set("Физические: 1 поток/ядро"); self.app.lab_refresh()
        picker=self.app.lab_cpu_picker
        picker.menu.invoke(picker.values["7"])
        self.assertIn("7",custom_config(self.app).cpu_counts)
        self.app.lab_warmup_picker.menu.invoke(self.app.lab_warmup_picker.values["2"])
        self.app.lab_workers_picker.menu.invoke(self.app.lab_workers_picker.values["3"])
        self.assertEqual((read_form(self.app).warmups,read_form(self.app).workers),(2,3))
        self.assertEqual(custom_config(self.app).warmups,0)
        self.app.hardware["cpu"]=cpu_fixture(256)
        self.app.lab_units.set("Логические CPU"); self.app.lab_refresh()
        picker=self.app.lab_cpu_picker
        self.assertIn("100",picker.values)
        picker.menu.invoke(picker.values["100"])
        self.assertIn("100",self.app.lab_cpus.get().split(","))

    def test_print_mode_menus_apply_actual_cmyk_profile_and_qa_preferences(self):
        self.app.pdf_picker.menu.invoke(self.app.pdf_picker.values["Компактный"])
        self.assertEqual(self.app.print_settings.pdf_profile,"compact")
        self.app.qa_picker.menu.invoke(self.app.qa_picker.values["Отложена"])
        self.assertEqual(self.app.read_generation_options().qa_mode,"deferred")
        self.assertEqual(self.app.print_settings.ink,(0,0,0,100))

    def test_busy_buttons_lock_and_legacy_invalid_selection_can_be_removed(self):
        self.app.lab_pdf_profiles.set("standard")
        self.app.busy=True; self.app.update_buttons()
        self.assertTrue(self.app.lab_pdf_picker.button.instate(["disabled"]))
        self.app.busy=False; self.app.update_buttons()
        self.app.lab_cpus.set("1,9999")
        picker=self.app.lab_cpu_picker
        self.assertIn("9999",picker.values)
        picker.menu.invoke(picker.values["9999"])
        self.assertEqual(self.app.lab_cpus.get(),"1")

    def test_production_worker_and_history_filter_are_buttons(self):
        self.app.worker_picker.menu.invoke(self.app.worker_picker.values["1"])
        self.assertEqual(self.app.read_generation_options().workers,1)
        picker=self.app.history_view.filter_picker
        picker.menu.invoke(picker.values["Успешные"])
        self.assertEqual(self.app.history_view.filter.get(),"Успешные")

    def test_physical_core_button_selects_actual_core_masks(self):
        from ucode.resource_lab import build_cases
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_units.set("Логические CPU")
        self.app.lab_unit_buttons["physical"].invoke()
        self.app.lab_cpus.set("2,12,all")
        config=custom_config(self.app)
        self.assertEqual(config.cpu_units,("physical",))
        cases=build_cases(config,self.app.hardware["cpu"])
        self.assertEqual([len(case["cpus"]) for case in cases],[2,12,14])
        for case in cases:
            self.assertEqual(len({cpu["core"] for cpu in case["cpus"]}),len(case["cpus"]))
        self.assertIn("Ядра",self.app.lab_unit_buttons["physical"].cget("text"))

    def test_large_txt_preview_and_real_streamed_pdf_from_primary(self):
        import json
        from unittest.mock import patch
        from ucode.stream_data import SourceInfo
        path=Path(self.temp.name)/"large-preview.txt"
        path.write_text("000000000001\n200000000002\n",encoding="utf-8")
        self.app.input_var.set(str(path))
        with patch("ucode.stream_data.inspect_codes",return_value=SourceInfo(100001,100001,"000000000001","200000000002")):
            self.app.inspect_input()
        self.assertEqual(self.app.current_plan.total_codes,100001)
        self.assertTrue(self.app.generate.instate(["!disabled"]))
        self.app.verification_buttons["deferred"].invoke()
        with patch("ucode.batch.STREAM_THRESHOLD",1):
            self.app.generate.invoke(); self.app.worker.join(timeout=10)
            self.assertFalse(self.app.worker.is_alive()); self.app.poll()
        data=json.loads((self.app.last_output/"manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(data["streaming"])
        self.assertEqual(data["count"],2)
        self.assertEqual(data["status"],"UNVERIFIED",data)

    def test_resources_link_opens_physical_tests_without_starting_work(self):
        from unittest.mock import patch
        self.app.hardware["cpu"]=cpu_fixture(14)
        self.app.lab_units.set("Логические CPU"); self.app.lab_cpus.set("28")
        self.assertFalse(self.app.cpu_extra_frame.winfo_manager())
        with patch.object(self.app,"refresh_hardware"):
            self.app.core_tests_button.invoke()
        self.assertEqual(self.app.notebook.select(),str(self.app.pages["lab"]))
        self.assertEqual(custom_config(self.app).cpu_units,("physical",))
        self.assertEqual(custom_config(self.app).cpu_counts,("1",))
        self.assertIsNone(self.app.worker)
        self.app.cpu_extra_button.invoke()
        self.assertEqual(self.app.cpu_extra_frame.winfo_manager(),"pack")
        self.app.cpu_extra_button.invoke()
        self.assertFalse(self.app.cpu_extra_frame.winfo_manager())
