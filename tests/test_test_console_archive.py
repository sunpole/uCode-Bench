"""Public test command contracts, text archive and programmatic nested Tk workflow."""
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from ucode.test_commands import parse_script,parse_command,command_text,preview_command
from ucode.test_archive import archive_scope,archive_test,archive_rows,store_test,import_tests
from test_lab_interface import cpu_fixture


class CommandTests(unittest.TestCase):
    def test_every_config_axis_roundtrips_without_a_shell(self):
        lines=[
            'test lab --codes 2000,10000 --cpu 1,2,4,12,all --unit cores,smt --backend serial,process,thread --ram auto,50%,80%,max,1024MiB --repeats 10 --warmups 2 --batch 17 --workers 0 --files both --pdf standard,compact --activity normal,minimal --metrics off,cpu --module .75 --quiet 5 --ink 10,20,30,80 --qa off',
            'test pipeline --codes 200,1000,10000,100000 --split cores:12+2,smt:24+4,cores:14+0,smt:28+0 --schedule equal,queue --batch 17,128 --metrics off,cpu --ram max --pdf compact --qa vector',
            'test search --codes 200,1000 --unit cores,smt --cpu 1,all --each-cpu off --backend serial,process,thread --batch 17,32 --parts 14,28 --part-mode sequential,parallel --mergers all --pdf standard,compact --activity normal,minimal --metrics off --ram max --search staged --keep-best 3 --qa off',
            'test scientific --codes all --mergers pypdf,pymupdf']
        for line in lines:
            with self.subTest(line=line):
                c=parse_command(line); again=parse_command(command_text(c))
                self.assertEqual(c,again)
        for line in ('python -c "print(1)"','test lab --codes 7; whoami','test lab --unknown x','test scientific --qa off','test pipeline --split cores:12+2 --batch 0'):
            with self.assertRaises(ValueError): parse_script(line)

    def test_preview_exact_counts_and_all_script_validation_before_execution(self):
        commands=parse_script('# AI-generated\ntest lab --codes 2000 --cpu 1,all --unit cores --repeats 1\ntest pipeline --codes 10000 --split cores:12+2,smt:24+4 --repeats 3 --schedule equal,queue')
        a,b=[preview_command(c,cpu_fixture(14)) for c in commands]
        self.assertEqual((a['runs'],b['runs']),(2,12))
        with tempfile.TemporaryDirectory() as temp:
            from ucode.test_commands import run_script
            with self.assertRaises(ValueError): run_script('test lab --codes 3\ntest lab --codes BAD',Path(temp)/'out')
            self.assertFalse((Path(temp)/'out').exists())

    def test_cli_plan_has_no_generation_and_error_is_nonzero(self):
        from contextlib import redirect_stdout,redirect_stderr
        import io
        from ucode.__main__ import main
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['test','--plan','pipeline','--codes','100000','--split','cores:1+0','--schedule','queue','--repeats','1','--qa','off']),0)
        self.assertEqual(json.loads(output.getvalue())[0]['runs'],1)
        with redirect_stderr(io.StringIO()): self.assertEqual(main(['test','lab','--qa','bad']),1)


class ArchiveTests(unittest.TestCase):
    def source(self,root):
        folder=root/'source'; folder.mkdir()
        data={'kind':'cpu-pipeline-lab','status':'UNVERIFIED','config':{'counts':[7]},'hardware':{'cpu':{'name':'Fixture CPU','available_physical':14},'ram':{'total_bytes':16*1024**3}},
              'cases':[{'id':'P1','count':7,'status':'UNVERIFIED','summary':{'median_launcher_wall_seconds':1.2},'trials':[{'status':'UNVERIFIED','seconds':{'production':.8},'manifest':{'payload':'200000000001','path':'C:/Users/Secret/result.pdf'}}]}],
              'secret_token':'private','path':'C:/Users/Secret/x','errors':['failure /home/private/project/one.pdf 200000000001','<script>alert(1)</script>']}
        (folder/'pipeline.json').write_text(json.dumps(data),encoding='utf-8')
        (folder/'all.pdf').write_bytes(b'not copied'); (folder/'codes.txt').write_text('200000000001')
        return folder

    def test_text_only_idempotent_sanitized_and_failed_destination_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root); raw=(source/'pipeline.json').read_bytes()
            a=archive_test(source,root/'archive'); b=archive_test(source,root/'archive')
            self.assertEqual(a['id'],b['id']); self.assertTrue(b['duplicate'])
            self.assertEqual(len(archive_rows(root/'archive')),1)
            saved=Path(a['report']).parent
            text=(saved/'report.json').read_text(encoding='utf-8')
            self.assertNotIn('Secret',text); self.assertNotIn('200000000001',text); self.assertNotIn('private',text)
            self.assertFalse(list(saved.glob('*.pdf'))); self.assertFalse((saved/'codes.txt').exists())
            self.assertIn('&lt;script&gt;',Path(a['report']).read_text(encoding='utf-8'))
            self.assertEqual((source/'pipeline.json').read_bytes(),raw)
            (root/'blocked').write_text('file')
            error=archive_test(source,root/'blocked')
            self.assertEqual(error['status'],'ERROR')
            self.assertEqual(json.loads((source/'archive-status.json').read_text())['status'],'ERROR')
            receipts=import_tests(root,root/'archive')
            self.assertEqual(len(archive_rows(root/'archive')),1)
            self.assertTrue(receipts)

    def test_concurrent_writers_keep_all_runs_and_index(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); sources=[]
            for i in range(4):
                folder=root/str(i); folder.mkdir(); sources.append(self.source(folder))
            with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(lambda f:store_test(f,root/'archive'),sources))
            rows=archive_rows(root/'archive'); self.assertEqual(len(rows),4)
            index=(root/'archive/index.html').read_text(encoding='utf-8')
            for row in rows: self.assertIn(row['file'],index)

    def test_nested_tests_archive_after_outer_timing_and_before_final_100(self):
        from ucode.test_archive import archived_test
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root); observed=[]
            @archived_test
            def inner(): return source
            @archived_test
            def outer(events):
                inner()
                self.assertFalse((source/'archive-status.json').exists())
                events({'percent':100})
                return source
            def event(value): observed.append((value['percent'],(source/'archive-status.json').is_file()))
            with archive_scope(root/'archive'): outer(events=event)
            self.assertEqual(observed,[(100,True)])
            self.assertEqual(len(archive_rows(root/'archive')),1)

    def test_cancelled_queue_saves_metadata_and_no_pdf(self):
        from ucode.test_commands import run_script
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); cancel=threading.Event(); cancel.set()
            with archive_scope(root/'archive'): folder=run_script('test lab --codes 3 --repeats 1 --qa off',root/'out',cancel=cancel)
            data=json.loads((folder/'commands.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'CANCELLED')
            self.assertEqual(len(archive_rows(root/'archive')),1)
            self.assertFalse(list(folder.rglob('*.pdf')))

    def test_real_two_command_queue_autoarchives_after_pdf_and_qa_off(self):
        from ucode.test_commands import run_script
        from ucode.hardware import inspect_cpu
        if not inspect_cpu().get('available_physical'): self.skipTest('Нет физической топологии')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); events=[]
            text='test pipeline --codes 3 --split cores:1+0 --schedule queue --repeats 1 --qa off\ntest lab --codes 3 --cpu 1 --unit cores --repeats 1 --batch 1 --qa off'
            with archive_scope(root/'archive'): folder=run_script(text,root/'out',events=events.append)
            data=json.loads((folder/'commands.json').read_text(encoding='utf-8'))
            self.assertEqual(data['status'],'UNVERIFIED',data)
            self.assertEqual(len(data['runs']),2); self.assertEqual(len(archive_rows(root/'archive')),3)
            self.assertEqual(events[-1]['percent'],100)
            self.assertTrue(all(e['percent']<100 for e in events[:-1]))
            self.assertTrue((folder/'commands.txt').is_file())
            for row in archive_rows(root/'archive'): self.assertTrue((root/'archive'/row['file']).is_file())


class HubWindowTests(unittest.TestCase):
    def test_all_test_sections_and_compact_scientific_menu_fit_at_150_percent(self):
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        with tempfile.TemporaryDirectory() as temp:
            try: root=tk.Tk()
            except tk.TclError as exc: self.skipTest(str(exc))
            root.withdraw(); root.tk.call('tk','scaling',2.0); app=BatchWindow(root,Path(temp)/'out')
            try:
                app.performance_dialog()
                if not app.test_controls.expanded: app.test_controls.toggle()
                for key in ('lab','pipeline','search','tests','console','archive','history'):
                    app.notebook.select(app.pages[key]); app.update_buttons(); root.update_idletasks()
                    self.assertLessEqual(root.winfo_reqheight(),668,key)
                    self.assertLessEqual(root.winfo_reqwidth(),1326,key)
            finally:
                if app.worker: app.worker.join(20)
                root.destroy(); del app,root; gc.collect()

    def test_hub_commands_to_controls_and_back_and_console_primary(self):
        import tkinter as tk
        from ucode.batch_gui import BatchWindow
        from ucode.test_console_ui import copy_current
        with tempfile.TemporaryDirectory() as temp:
            try: root=tk.Tk()
            except tk.TclError as exc: self.skipTest(str(exc))
            root.withdraw(); app=BatchWindow(root,Path(temp)/'out')
            try:
                self.assertEqual(len(app.notebook.tabs()),5)
                self.assertEqual(len(app.test_notebook.tabs()),7)
                app.console_view.set_text('test pipeline --codes 3 --split cores:1+0 --schedule queue --batch 17 --repeats 1 --qa off --metrics off')
                app.console_view.apply()
                self.assertEqual(app.notebook.select(),str(app.pages['pipeline']))
                self.assertEqual(app.pipeline_view.config().batches,(17,))
                copy_current(app)
                self.assertEqual(app.notebook.select(),str(app.pages['console']))
                self.assertEqual(parse_script(app.console_view.text())[0].config,app.pipeline_view.config())
                app.update_buttons(); app.generate.invoke(); app.worker.join(20); app.poll()
                self.assertFalse(app.busy); self.assertEqual(app.last_report.name,'commands.html')
                self.assertIn('UNVERIFIED',app.result_var.get())
                self.assertGreaterEqual(len(app.archive_view.rows),2)
            finally:
                if app.worker: app.worker.join(20)
                root.destroy(); del app,root; gc.collect()


if __name__=='__main__': unittest.main()
