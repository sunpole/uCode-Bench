import json
from pathlib import Path
import tempfile
import unittest

from ucode.pipeline_plan import PipelineConfig,build_pipeline_cases
from ucode.pipeline_memory import memory_plan
from test_lab_interface import cpu_fixture


class ProcessCountTests(unittest.TestCase):
    def test_14_cores_times_1_2_5_10_is_exactly_eight_runs_not_extra_cores(self):
        from ucode.test_commands import parse_command,command_text,preview_command
        command=parse_command('test pipeline --codes 10000 --split cores:14+0 --schedule queue --batch 32 --repeats 2 --processes-per-core 1,2,5,10 --metrics cpu --qa off --xy on')
        self.assertEqual(parse_command(command_text(command)),command)
        rows=build_pipeline_cases(command.config,cpu_fixture(14))
        self.assertEqual([c['workers'] for c in rows],[14,28,70,140])
        self.assertTrue(all(len(c['cpus'])==14 and len(c['qr_cpus'])==14 for c in rows))
        self.assertEqual(preview_command(command,cpu_fixture(14))['runs'],8)

    def test_measured_memory_plan_has_headroom_buffers_and_no_faked_ram_fill(self):
        base=32*1024**2
        plan=memory_plan(10000,140,32,base)
        self.assertEqual(plan['per_process_bytes'],48*1024**2)
        self.assertEqual(plan['bounded_values'],8960)
        self.assertEqual(plan['required_bytes'],256*1024**2+140*48*1024**2+8960*40000)
        self.assertEqual(memory_plan(10000,140,32,None)['per_process_bytes'],128*1024**2)

    def test_invalid_multipliers_are_rejected_and_equal_partitions_count_processes(self):
        from ucode.pipeline_plan import Tasks
        for values in ((),(0,),(11,),('2',),(True,)):
            with self.assertRaises(ValueError):PipelineConfig(processes_per_cpu=values)
        tasks=Tasks(10,4,2,'equal');sizes=[]
        for slot in range(4):
            count=0
            while (part:=tasks.take(slot)) is not None:count+=part[1]
            sizes.append(count)
        self.assertEqual(sizes,[3,3,2,2])

    def test_multiple_processes_on_one_cpu_are_summed_not_counted_as_extra_cores(self):
        from ucode.cpu_telemetry import CPUTrace
        now=[0.0];cpu=cpu_fixture(1)['available_cpus'][0]
        with tempfile.TemporaryDirectory() as temp:
            trace=CPUTrace([cpu],Path(temp)/'cpu.csv',clock=lambda:now[0])
            trace.bind({'worker_affinity':{'100':[cpu],'101':[cpu]}})
            trace.sample([{'identity':(100,1),'cpu_seconds':0},{'identity':(101,1),'cpu_seconds':0}])
            now[0]=1
            trace.sample([{'identity':(100,1),'cpu_seconds':.3},{'identity':(101,1),'cpu_seconds':.4}])
            data=trace.finish()
            self.assertAlmostEqual(data['phases']['Вся операция']['selected_cpu_load_pct']['mean'],70)
            self.assertEqual(data['bound_worker_count'],2)


class RealProcessCountTests(unittest.TestCase):
    def test_two_processes_per_selected_cpu_real_pdf_qa_and_affinity(self):
        from ucode.pipeline_lab import run_pipeline_lab
        from ucode.hardware import inspect_cpu
        from ucode.affinity import cpu_keys
        before=cpu_keys(inspect_cpu()['available_cpus'])
        with tempfile.TemporaryDirectory() as temp:
            cfg=PipelineConfig(counts=(4,),allocations=('physical:1:0',),schedules=('equal','queue'),batches=(1,),
                               repeats=1,qa_mode='full',telemetry_modes=('cpu',),processes_per_cpu=(1,2))
            folder=run_pipeline_lab(Path(temp),cfg)
            data=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'COMPLETE',data.get('errors'))
            self.assertEqual(len(data['cases']),4)
            for case in data['cases']:
                t=case['trials'][0];info=t['manifest']['execution'];factor=case['processes_per_cpu']
                self.assertEqual(t['manifest']['qa']['multipage']['status'],'PASS')
                self.assertEqual(len(info['worker_pids']),factor)
                self.assertEqual(sum(v['pages'] for v in info['worker_tasks'].values()),4)
                self.assertTrue(all(v['pages']>0 for v in info['worker_tasks'].values()))
                self.assertEqual(len({tuple(cpu_keys(v)) for v in info['worker_affinity'].values()}),1)
                self.assertEqual(t['memory']['cpu_telemetry']['bound_worker_count'],factor)
                if factor>1:
                    self.assertGreater(info['memory_startup_observation']['rss_bytes'],0)
                    self.assertEqual(info['ram_plan']['phase'],'measured_startup')
            self.assertEqual(cpu_keys(inspect_cpu()['available_cpus']),before)

    def test_memory_refusal_after_one_real_probe_cleans_up_without_launching_ten(self):
        from unittest.mock import patch
        import multiprocessing as mp
        from ucode.pipeline import prepared_pages,PipelineBudgetError
        from ucode.print_settings import PrintSettings
        from ucode.hardware import inspect_cpu
        cpu=inspect_cpu()['available_cpus'][0];info={}
        def measured(*args,**kwargs):
            result=memory_plan(*args,**kwargs)
            if not kwargs.get('minimum'):result['required_bytes']=100*1024**3
            return result
        req={'count':4,'qr_cpus':[cpu],'pdf_cpus':[],'batch_size':1,'ram_budget_bytes':1024**3,'schedule':'queue','processes_per_cpu':10}
        with patch('ucode.pipeline_memory.memory_plan',side_effect=measured):
            with self.assertRaises(PipelineBudgetError):next(prepared_pages(req,PrintSettings(),None,lambda:None,info))
        self.assertEqual(len(info['worker_pids']),1)
        self.assertFalse(mp.active_children())

    def test_gui_command_and_saved_multiplier_fit_at_150_percent(self):
        import gc
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        from ucode.test_commands import parse_command
        from ucode.test_navigation import apply_to_controls,from_controls
        with tempfile.TemporaryDirectory() as temp:
            try:root=tk.Tk()
            except tk.TclError as exc:self.skipTest(str(exc))
            root.withdraw();root.tk.call('tk','scaling',2.0);app=BatchWindow(root,Path(temp)/'out')
            try:
                app.hardware['cpu']=cpu_fixture(14)
                command=parse_command('test pipeline --codes 10000 --split cores:14+0 --schedule queue --processes-per-core 1,2,5,10 --repeats 2 --qa off')
                apply_to_controls(app,command);app.pipeline_view.refresh();root.update_idletasks()
                self.assertEqual(from_controls(app,'pipeline'),command)
                self.assertIn('результатов: 8',app.pipeline_view.plan.get())
                self.assertIn('14/28/70/140',app.pipeline_view.plan.get())
                self.assertLessEqual(root.winfo_reqheight(),668)
                self.assertLessEqual(root.winfo_reqwidth(),1326)
            finally:root.destroy();del app,root;gc.collect()


if __name__=='__main__':unittest.main()
