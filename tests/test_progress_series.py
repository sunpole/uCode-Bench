import json
from pathlib import Path
import tempfile
import unittest

from ucode.progress_series import ProgressSeries


class SeriesTests(unittest.TestCase):
    def test_real_time_counts_rates_and_weighted_mean(self):
        now=[10.0]; s=ProgressSeries(clock=lambda:now[0])
        for t,n in ((10,0),(11,100),(13,500),(14,500)):
            now[0]=t;s.observe({'stage':'Создание PDF','done':n,'total':500})
        part=s.data('COMPLETE')['segments'][0]
        self.assertEqual(part['points'][0],[0,0,None,0])
        self.assertEqual(part['points'][2],[3,500,200,2])
        self.assertEqual(part['stats'],{'min':0,'mean':125,'max':200})

    def test_samples_are_bounded_and_true_extrema_survive_compaction(self):
        now=[0.0];s=ProgressSeries(clock=lambda:now[0],max_points=8)
        for i in range(100):
            now[0]=i;s.observe({'stage':'Кодирование QR','done':i*i,'total':10000})
        part=s.data('CANCELLED')['segments'][0]
        self.assertLessEqual(len(part['points']),8)
        self.assertEqual(part['points'][-1][1],99*99)
        self.assertEqual(part['stats']['max'],197)
        self.assertGreater(part['compactions'],0)
        self.assertEqual(s.data('CANCELLED')['status'],'CANCELLED')

    def test_no_fake_zeros_qa_count_or_stage_reset_sum(self):
        now=[0.0];s=ProgressSeries(clock=lambda:now[0])
        s.observe({'stage':'Кодирование QR','done':50,'total':100})
        now[0]=1;s.observe({'stage':'Создание PDF','done':0,'total':100})
        now[0]=2;s.observe({'stage':'Проверка PDF','done':100,'total':103})
        parts=s.data('UNVERIFIED')['segments']
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[0]['points'][0][1],50)
        self.assertIsNone(parts[0]['stats']['mean'])
        self.assertEqual(parts[1]['points'][0][1],0)

    def test_interval_final_endpoint_and_nonfinite_observations(self):
        now=[0.0];s=ProgressSeries(clock=lambda:now[0])
        s.observe({'stage':'Создание PDF','done':0,'total':10})
        now[0]=.1;s.observe({'stage':'Создание PDF','done':3,'total':10})
        now[0]=.2;s.observe({'stage':'Создание PDF','done':10,'total':10})
        now[0]=float('nan');s.observe({'stage':'Создание PDF','done':10,'total':10})
        p=s.data('UNVERIFIED')['segments'][0]
        self.assertEqual(len(p['points']),2)
        self.assertEqual(p['points'][-1][1],10)
        json.dumps(s.data('UNVERIFIED'),allow_nan=False)

    def test_global_peak_and_minimum_points_remain_in_compressed_graph(self):
        now=[0.0];s=ProgressSeries(clock=lambda:now[0],max_points=8); count=0
        for i in range(100):
            now[0]=i
            count+=1000 if i==7 else 0 if i==13 else 1
            s.observe({'stage':'Создание PDF','done':count,'total':10000})
        part=s.data('CANCELLED')['segments'][0]
        rates=[p[2] for p in part['points'] if p[2] is not None]
        self.assertIn(1000,rates);self.assertIn(0,rates)

    def test_command_roundtrip_includes_xy_for_every_custom_test(self):
        from ucode.test_commands import parse_command,command_text
        for kind in ('lab','pipeline','search'):
            command=parse_command(f'test {kind} --codes 3 --repeats 1 --xy on --qa off')
            self.assertEqual(command.config.timeline_mode,'on')
            self.assertEqual(parse_command(command_text(command)),command)

    def test_old_reports_do_not_receive_synthetic_xy(self):
        from ucode.graphical_report import chart_model
        self.assertEqual(chart_model({'kind':'resource-lab','cases':[]})['timelines'],[])

    def test_template_marker_in_untrusted_data_stays_data(self):
        import re
        from ucode.graphical_report import graphical_section
        data={'status':'COMPLETE','timeline':{'schema':1,'segments':[{'stage':'__XY_FUNCTION__','counter_kind':'written_pages','target':1,
            'points':[[0,0,None,0],[1,1,1,1]],'stats':{'min':1,'mean':1,'max':1}}]}}
        text=graphical_section(data)
        raw=re.search(r'class="uc-chart-data">(.*?)</script>',text,re.S).group(1)
        model=json.loads(raw)
        self.assertIn('__XY_FUNCTION__',model['timelines'][0]['label'])


class RealSeriesTests(unittest.TestCase):
    def test_gui_xy_roundtrip_persistence_and_size(self):
        import gc
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        from ucode.test_commands import parse_command
        from ucode.test_navigation import apply_to_controls,from_controls
        from ucode.app_settings import load_user_preferences
        with tempfile.TemporaryDirectory() as temp:
            try:root=tk.Tk()
            except tk.TclError as exc:self.skipTest(str(exc))
            root.withdraw();root.tk.call('tk','scaling',2.0);app=BatchWindow(root,Path(temp)/'out')
            try:
                for kind in ('lab','pipeline','search'):
                    command=parse_command(f'test {kind} --codes 3 --repeats 1 --xy on --qa off')
                    apply_to_controls(app,command)
                    self.assertEqual(from_controls(app,kind).config,command.config)
                    root.update_idletasks()
                    self.assertLessEqual(root.winfo_reqwidth(),1326)
                    self.assertLessEqual(root.winfo_reqheight(),668)
                app.remember()
                self.assertEqual(load_user_preferences(app.preferences_path)[2].timeline_mode,'on')
                for section in ('tests','console'):
                    app.notebook.select(app.pages[section]);app.update_buttons()
                    self.assertEqual(str(app.xy_picker.button.cget('state')),'disabled')
            finally:
                root.destroy();del app,root;gc.collect()

    def test_small_production_on_off_same_pdf_and_full_qa_before_final_100(self):
        from ucode.batch import run_batch
        from ucode.print_settings import PrintSettings
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'codes.txt';source.write_text('200000000000\n200000000001\n200000000002\n',encoding='utf-8')
            settings=PrintSettings(pdf_profile='compact')
            with patch('ucode.progress_series.ProgressSeries',side_effect=AssertionError('XY off')):
                off=run_batch(source,root/'off',mode='multipage',settings=settings,qa_mode='full',force_disk=True)
            def event(value):
                if value['percent']==100:
                    self.assertTrue(list((root/'on').glob('*/production.html')))
            on=run_batch(source,root/'on',mode='multipage',settings=settings,qa_mode='full',timeline_mode='on',force_disk=True,events=event)
            data=json.loads((on/'manifest.json').read_text(encoding='utf-8'))
            self.assertIn(data['status'],('COMPLETE','LIMITED'))
            self.assertEqual(data['timeline']['status'],data['status'])
            self.assertEqual(data['timeline']['segments'][-1]['points'][-1][1],3)
            self.assertFalse((off/'timeline.json').exists())
            self.assertEqual(next(on.glob('all-*.pdf')).read_bytes(),next(off.glob('all-*.pdf')).read_bytes())
            from pypdf import PdfReader
            self.assertEqual(len(PdfReader(next(on.glob('all-*.pdf'))).pages),3)
            self.assertEqual(len(PdfReader(next(off.glob('all-*.pdf'))).pages),3)
            self.assertIn('XY: ход работы',(on/'production.html').read_text(encoding='utf-8'))

    def test_real_lab_pipeline_queue_and_text_archive_preserve_xy(self):
        from ucode.test_commands import run_script
        from ucode.test_archive import archive_scope,archive_rows
        from ucode.graphical_report import chart_model
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            text='test lab --codes 3 --cpu 1 --repeats 1 --qa off --xy on\ntest pipeline --codes 3 --split cores:1+0 --schedule queue --repeats 1 --qa off --xy on'
            with archive_scope(root/'archive'):folder=run_script(text,root/'out')
            data=json.loads((folder/'commands.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'UNVERIFIED',data)
            self.assertEqual(len(archive_rows(root/'archive')),3)
            curves=chart_model(data)['timelines']
            self.assertGreaterEqual(len(curves),3)
            self.assertTrue(all(v['points'][-1][1]==3 for v in curves))
            self.assertFalse(list((root/'archive').rglob('*.pdf')))


if __name__=='__main__':unittest.main()
