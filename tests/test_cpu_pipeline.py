"""Small real PDFs and independent ownership/topology oracles for the CPU lab."""
from dataclasses import replace
import gc
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ucode.pipeline_plan import PipelineConfig,partition,Tasks,balanced_ranges,build_pipeline_cases
from test_lab_interface import cpu_fixture


class PipelinePlanTests(unittest.TestCase):
    def test_physical_12_2_and_logical_24_4_have_same_disjoint_core_groups(self):
        cpu=cpu_fixture(14)
        for token in ("physical:12:2","logical:24:4"):
            plan=partition(cpu,token)
            self.assertEqual({c['core'] for c in plan['qr_cpus']},set(range(12)))
            self.assertEqual({c['core'] for c in plan['pdf_cpus']},{12,13})
            self.assertEqual(plan['shared_physical_cores'],0)
        # Interleaved OS IDs must not place each QR/PDF group on the same cores.
        for c in cpu['available_cpus']: c['logical']=(c['id']%2)*14+c['id']//2
        self.assertEqual(partition(cpu,"logical:24:4")['shared_physical_cores'],0)
        self.assertEqual(partition(cpu,"logical:25:3")['shared_physical_cores'],1)
        with self.assertRaises(ValueError): partition(cpu,"physical:14:2")

    def test_100000_equal_28_exact_coverage_and_dynamic_faster_slot_gets_more(self):
        ranges=balanced_ranges(100000,28)
        self.assertEqual([size for _,size in ranges],[3572]*12+[3571]*16)
        for mode in ("equal","queue"):
            tasks=Tasks(103,3,8,mode); slots=[[] for _ in range(3)]
            while True:
                changed=False
                for slot in (0,1,2,0):
                    job=tasks.take(slot)
                    if job:
                        start,size=job; slots[slot].extend(range(start,start+size)); changed=True
                if not changed: break
            flat=[n for values in slots for n in values]
            self.assertEqual(sorted(flat),list(range(103)))
            self.assertEqual(len(flat),len(set(flat)))
            if mode=="equal": self.assertEqual([len(v) for v in slots],[35,34,34])
            else: self.assertGreater(len(slots[0]),len(slots[1]))

    def test_matrix_has_exact_requested_results_not_hidden_axes(self):
        cfg=PipelineConfig(counts=(2000,),allocations=("physical:1:0","physical:14:0"),schedules=("equal",),repeats=1)
        self.assertEqual(len(build_pipeline_cases(cfg,cpu_fixture(14))),2)
        cfg=replace(cfg,counts=(10000,),allocations=("physical:2:0","physical:4:0","physical:12:0"),repeats=10)
        self.assertEqual(len(build_pipeline_cases(cfg,cpu_fixture(14)))*cfg.repeats,30)
        cfg=replace(cfg,allocations=("physical:12:2","logical:24:4"),schedules=("equal","queue"),repeats=3)
        self.assertEqual(len(build_pipeline_cases(cfg,cpu_fixture(14)))*cfg.repeats,12)


class PipelinePDFTests(unittest.TestCase):
    def test_full_qa_without_renderer_is_excluded_with_a_clear_reason(self):
        from ucode.hardware import inspect_cpu
        from ucode.pipeline_lab import run_pipeline_lab
        if not inspect_cpu().get('available_physical'): self.skipTest('Нет физической топологии')
        with tempfile.TemporaryDirectory() as temp:
            cfg=PipelineConfig(counts=(3,),allocations=("physical:1:0",),schedules=("queue",),batches=(1,),repeats=1,qa_mode="full",telemetry_modes=("off",))
            with patch.dict(os.environ,{'PATH':''}): folder=run_pipeline_lab(Path(temp),cfg)
            data=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'PARTIAL')
            self.assertFalse(data['winners'])
            self.assertIn('pdftoppm',data['cases'][0]['reason'])

    def test_out_of_order_streams_exact_cmyk_and_final_bytes_checked(self):
        from ucode.pipeline import page_encoder
        from ucode.stream_pdf import write_pdf,DiskReader
        from ucode.engines import get_engine
        from ucode.quality import check_pdf
        from ucode.print_settings import PrintSettings
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); frames=get_engine().encode([f'{200000000000+i}' for i in range(7)])
            for profile in ("standard","compact"):
                settings=PrintSettings(ink=(10,20,30,70),pdf_profile=profile); encode=page_encoder(settings)
                path=folder/(profile+'.pdf'); index=folder/(profile+'.sqlite')
                write_pdf(frames,path,settings,index,prepared=((i+1,frames[i].payload,encode(frames[i])) for i in (6,1,4,0,5,3,2)))
                qa=check_pdf(path,frames,settings,render_samples=False,reader_factory=lambda:DiskReader(path,index))
                self.assertEqual(qa['status'],'PASS',qa)
                qa=check_pdf(path,frames,settings,render_samples=False)
                self.assertEqual(qa['status'],'PASS',qa)
                self.assertEqual(path.read_bytes().count(b'/MediaBox'),1)
            path.write_bytes(path.read_bytes().replace(b'/MediaBox [0 0',b'/MediaBox [1 0',1))
            qa=check_pdf(path,frames,settings,render_samples=False,reader_factory=lambda:DiskReader(path,index))
            self.assertEqual(qa['status'],'FAIL')

    def test_real_pipeline_and_full_cycle_preserve_pages_affinity_and_detailed_results(self):
        from ucode.hardware import inspect_cpu
        from ucode.affinity import cpu_keys
        from ucode.pipeline_lab import run_pipeline_lab
        cpu=inspect_cpu()
        if cpu.get('available_physical',0)<2: self.skipTest('Нужно 2 физических ядра')
        before=cpu_keys(cpu['available_cpus'])
        with tempfile.TemporaryDirectory() as temp:
            cfg=PipelineConfig(counts=(7,),allocations=("physical:1:1","physical:2:0"),schedules=("equal","queue"),batches=(1,),repeats=1,qa_mode="full",print_settings={"pdf_profile":"compact"})
            events=[]; folder=run_pipeline_lab(Path(temp),cfg,events=events.append)
            data=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'COMPLETE',[(c['status'],c.get('reason')) for c in data['cases']])
            self.assertEqual(len(data['cases']),4)
            for case in data['cases']:
                trial=case['trials'][0]; m=trial['manifest']; info=m['execution']
                self.assertEqual(m['qa']['multipage']['status'],'PASS')
                self.assertEqual(m['count'],7)
                self.assertGreater(info['pdf_service_sum'],0)
                self.assertEqual(len(info['worker_affinity']),len(case['cpus']))
                self.assertLessEqual(info['max_pending_values'],2*len(case['qr_cpus'])*case['batch_size'])
                self.assertTrue((folder/trial['pdf_link']).is_file())
                self.assertEqual(trial['memory']['cpu_telemetry']['bound_worker_count'],len(case['cpus']))
                if case['schedule']=='equal':
                    qr_counts=sorted(v['pages'] for v in info['worker_tasks'].values() if v['stage'] in ('qr','full'))
                    self.assertEqual(qr_counts,[3,4] if len(case['qr_cpus'])==2 else [7])
            self.assertTrue((folder/'pipeline.csv').is_file())
            self.assertEqual(events[-1]['percent'],100)
            self.assertTrue(all(v['percent']<100 for v in events[:-1]))
            self.assertEqual(cpu_keys(inspect_cpu()['available_cpus']),before)

    def test_no_qa_no_telemetry_and_cancel_and_resource_refusal(self):
        from ucode.hardware import inspect_cpu
        from ucode.pipeline_lab import run_pipeline_lab
        cpu=inspect_cpu()
        if cpu.get('available_physical',0)<2: self.skipTest('Нужно 2 ядра')
        with tempfile.TemporaryDirectory() as temp:
            cfg=PipelineConfig(counts=(7,),allocations=("physical:1:1",),schedules=("queue",),batches=(1,),repeats=1,qa_mode="deferred",telemetry_modes=("off",))
            folder=run_pipeline_lab(Path(temp),cfg)
            data=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'UNVERIFIED',data['errors'])
            t=data['cases'][0]['trials'][0]
            self.assertEqual(t['seconds']['quality_checks'],0)
            self.assertNotIn('cpu_telemetry',t['memory'])
            self.assertFalse(list(folder.rglob('cpu-samples.csv')))
            # Launch a separate tiny trial and cancel as soon as the real worker starts.
            cancel=threading.Event()
            folder=run_pipeline_lab(Path(temp),cfg,cancel=cancel,events=lambda value:cancel.set())
            data=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'CANCELLED',data)
            from ucode.pipeline import prepared_pages
            from ucode.print_settings import PrintSettings
            request={"count":7,"qr_cpus":cpu['available_cpus'][:1],"pdf_cpus":cpu['available_cpus'][1:2],"batch_size":1,"ram_budget_bytes":1,"schedule":"queue"}
            with self.assertRaisesRegex(ValueError,'бюджета'): next(prepared_pages(request,PrintSettings(),None,lambda:None,{}))


class PipelineWindowTests(unittest.TestCase):
    def test_menus_custom_partition_and_predictable_plan(self):
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        with tempfile.TemporaryDirectory() as temp:
            try: root=tk.Tk()
            except tk.TclError as exc: self.skipTest(str(exc))
            root.withdraw(); app=BatchWindow(root,Path(temp)/'out')
            try:
                app.hardware['cpu']=cpu_fixture(14); view=app.pipeline_view
                view.allocations.set('physical:12:2,logical:24:4'); view.counts.set('2000'); view.schedules.set('equal,queue'); view.repeats.set('3'); view.refresh()
                self.assertIn('результатов: 12',view.plan.get())
                app.notebook.select(app.pages['pipeline']); app.update_buttons()
                self.assertEqual(app.generate.cget('text'),'ЗАПУСТИТЬ КОНВЕЙЕР')
                view.unit.set('physical'); view.qr.set('10'); view.pdf.set('4'); view.add_button.invoke()
                self.assertIn('physical:10:4',view.alloc_picker.selected())
                view.telemetry_picker.choose('off,cpu')
                self.assertIn('результатов: 36',view.plan.get())
                app.qa_mode_var.set('Отложена')
                self.assertEqual(view.config().qa_mode,'deferred')
                app.refresh_hardware()
                if app.hardware['cpu'].get('available_physical'):
                    view.allocations.set('physical:1:0'); view.counts.set('2'); view.schedules.set('queue'); view.repeats.set('1'); view.telemetry.set('off')
                    app.generate.invoke(); app.worker.join(20); app.poll()
                    self.assertFalse(app.busy)
                    self.assertEqual(app.last_report.name,'pipeline.html')
                    self.assertTrue(app.last_pdf.is_file())
                    self.assertEqual(json.loads(view.path.read_text(encoding='utf-8'))['counts'],[2])
                    self.assertIn('UNVERIFIED',app.result_var.get())
            finally: root.destroy(); del app,root; gc.collect()


if __name__=='__main__': unittest.main()
