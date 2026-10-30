from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_operator_web as web_tests
from ucode.order_output import normalize_name,suggested_name,publish_job
from ucode.batch import run_batch
from ucode.audit import audit_job
from ucode.print_settings import PrintSettings


class OrderNames(unittest.TestCase):
    def test_names_and_windows_rules(self):
        self.assertEqual(normalize_name('My job.PDF.pdf'),'My job.pdf')
        self.assertEqual(suggested_name('500000000012',3000,'2026-10-30_18-42-07'),'QR_0012_3000_2026-10-30_18-42-07.pdf')
        for value in ('','../a','CON.pdf','LPT1','a:bad','a.','a\\b','a\x00b'):
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_name(value)

    def test_named_outputs_all_modes_and_streaming_remain_auditable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'input.txt';source.write_text('500000000000\n500000000001\n500000000002\n')
            for streaming in (False,True):
                for mode in ('multipage','singles','both'):
                    with self.subTest(streaming=streaming,mode=mode):
                        result=run_batch(source,root,mode=mode,settings=PrintSettings(pdf_profile='compact'),qa_mode='vector',force_disk=streaming)
                        result=publish_job(result,'mine.pdf')
                        report=json.loads((result/'manifest.json').read_text(encoding='utf-8'))
                        self.assertEqual(report['status'],'LIMITED')
                        if mode!='singles':self.assertTrue((result/(result.name+'.pdf')).is_file())
                        if mode!='multipage':
                            singles=result if mode=='singles' else result/'singles'
                            self.assertEqual(sorted(p.name for p in singles.glob('*.pdf')),['0001.pdf','0002.pdf','0003.pdf'])
                        audit=audit_job(result,render_samples=False)
                        self.assertEqual(json.loads((audit/'audit.json').read_text(encoding='utf-8'))['status'],'LIMITED')
            self.assertTrue((root/'mine'/'mine.pdf').is_file())
            self.assertTrue((root/'mine_6').is_dir())


class FlowAPI(unittest.TestCase):
    setUp=web_tests.OperatorWebTests.setUp
    tearDown=web_tests.OperatorWebTests.tearDown
    api=web_tests.OperatorWebTests.api
    load=web_tests.OperatorWebTests.load
    wait_done=web_tests.OperatorWebTests.wait_done
    def test_manual_name_survives_changes_and_disk_failure_blocks(self):
        state=self.load();serial=state['source_serial'];stamp=self.server.service.name_stamp
        self.api('output-name',{'name':'Custom.PDF.pdf'})
        state=self.api('state');self.assertEqual(state['output_name'],'Custom.pdf')
        from ucode.operator_service import OperatorService
        restored=OperatorService(self.folder);self.assertEqual(restored.result_name(),'Custom.pdf')
        form=state['form'];form['copies_per_value']=2
        state=self.api('configure',form);self.assertEqual(state['output_name'],'Custom.pdf')
        state=self.api('output-name',{'automatic':True})
        self.assertIn('_6_',state['output_name']);self.assertIn(stamp,state['output_name'])
        self.api('preflight',{});state=self.wait_done();self.assertTrue(state['path_approved'])
        service=self.server.service
        with patch('ucode.operator_service.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            service.refresh_approval();self.assertFalse(service.state()['path_approved'])
            with self.assertRaises(ValueError):service.start()
        self.assertEqual(state['source_serial'],serial)
