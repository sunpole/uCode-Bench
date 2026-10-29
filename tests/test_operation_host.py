from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import tempfile
import unittest

from ucode.operation_host import OperationHost
from ucode.print_settings import PrintSettings
from ucode.app_settings import GenerationPreferences
from ucode.execution import ExecutionOptions


class OperationHostTests(unittest.TestCase):
    def request(self,folder):
        source=folder/'source.txt';source.write_text('200000000001\n200000000002\n',encoding='utf-8')
        return {'input':str(source),'destination':str(folder/'output'),'settings':asdict(PrintSettings(pdf_profile='compact')),
                'options':asdict(GenerationPreferences(qa_mode='deferred',timeline_mode='on')),'execution':asdict(ExecutionOptions()),
                'mode':'multipage','telemetry':'cpu','archive':str(folder/'archive')}

    def test_real_owned_worker_writes_pdf_telemetry_and_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);events=queue.Queue();host=OperationHost(folder/'operations',self.request(folder),events)
            host.start();self.assertNotEqual(host.process.pid,os.getpid());host.thread.join(20)
            if host.thread.is_alive():host.stop(force=True);host.thread.join(5)
            self.assertFalse(host.thread.is_alive())
            messages=[]
            while not events.empty():messages.append(events.get())
            done=[value for kind,value in messages if kind=='done']
            self.assertTrue(done,messages)
            manifest=json.loads((done[0]/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['status'],'UNVERIFIED')
            self.assertEqual(manifest['count'],2)
            from ucode.graphical_report import chart_model
            from ucode.test_archive import test_counts,result_rows
            graph=chart_model(manifest)['groups'][0]['rows'][0]
            self.assertTrue(graph['eligible']);self.assertEqual(len(graph['trials']),1)
            self.assertGreater(graph['pdf']['median'],0)
            self.assertEqual(test_counts(manifest),[2]);self.assertEqual(len(list(result_rows(manifest))),1)
            self.assertIn('cpu_telemetry',manifest['runtime_statistics'])
            self.assertGreater(manifest['seconds']['launcher_wall'],0)
            self.assertTrue((done[0]/'cpu-samples.csv').is_file())
            self.assertEqual(json.loads((done[0]/'archive-status.json').read_text(encoding='utf-8'))['status'],'SAVED')
            self.assertEqual(messages[-1][0],'done')
            self.assertEqual([v['percent'] for k,v in messages if k=='progress'][-1],100)

    def test_force_stop_is_scoped_to_owned_child(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);events=queue.Queue();host=OperationHost(folder/'operations',self.request(folder),events)
            host.start();pid=host.process.pid;host.stop(force=True);host.thread.join(15)
            self.assertNotEqual(pid,os.getpid());self.assertFalse(host.thread.is_alive());self.assertIsNotNone(host.process.poll())
            messages=[]
            while not events.empty():messages.append(events.get())
            self.assertTrue(any(k=='error' and 'InterruptedError' in v for k,v in messages),messages)
