from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from ucode.operator_web import OperatorHTTP,document,ASSETS,APPROVED_SHA256


class OperatorWebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.server=OperatorHTTP(self.folder);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        service=self.server.service
        if service.busy:
            service.cancel.set()
            if service.host:service.host.stop(force=True)
        if service.worker:service.worker.join(10)
        self.server.shutdown();self.server.server_close();self.thread.join(5);self.temp.cleanup()
    def api(self,path,value=None,headers=None):
        data=None if value is None else json.dumps(value).encode()
        defaults={'Content-Type':'application/json','X-UCode-Token':self.server.token} if data else {}
        request=Request(self.server.base+'api/'+path,data=data,headers=defaults if headers is None else headers)
        with urlopen(request,timeout=15) as response:return json.load(response)
    def wait_done(self):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            state=self.api('state')
            if not state['busy']:return state
            time.sleep(.02)
        self.fail('Owned operation did not finish')
    def load(self):
        source=self.folder/'mine.txt';source.write_text('000000100000\n000000100003\n000000100006\n',encoding='utf-8')
        self.server.service.load(source);return self.wait_done()
    def test_approved_bytes_and_every_style_block_are_preserved(self):
        raw=(ASSETS/'operator-approved.html').read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),APPROVED_SHA256)
        original=raw.decode('utf-8');runtime=document(self.server.token).decode('utf-8')
        source_styles=re.findall(r'<style[^>]*>([\s\S]*?)</style>',original)
        for block in source_styles:self.assertIn('<style>'+block+'</style>',runtime)
        self.assertNotRegex(runtime,r'<script[^>]+src=')
        self.assertIn('async function rtAPI',runtime);self.assertIn('window.UCODE_RUNTIME=true',runtime)
    def test_token_origin_and_json_are_required_for_mutations(self):
        for headers in ({'Content-Type':'application/json'},{'Content-Type':'application/json','X-UCode-Token':self.server.token,'Origin':'https://example.org'}):
            with self.assertRaises(HTTPError) as caught:self.api('stop-request',{},headers)
            self.assertEqual(caught.exception.code,403)
        with self.assertRaises(HTTPError):urlopen(self.server.origin+'/api/state',timeout=5)
    def test_actual_source_random_rows_and_live_search(self):
        state=self.load();self.assertEqual(state['source']['count'],3)
        self.assertEqual(self.api('rows?page=3')['rows'][-1],[3,'000000100006'])
        self.assertEqual(self.api('search?q=100003')['rows'],[[2,'000000100003']])
        with urlopen(self.server.base+'api/preview?page=2') as response:
            self.assertIn(b'<path',response.read());self.assertIn('image/svg+xml',response.headers['Content-Type'])
    def test_real_generation_through_loopback_api_and_path_invalidation(self):
        state=self.load();form=state['form'];form.update(cpu_choice='1',workers=1,execution_backend='process',telemetry='off',qa_mode='vector')
        self.api('configure',form);self.api('preflight',{});state=self.wait_done();self.assertTrue(state['path_approved'])
        self.api('generate',{});state=self.wait_done();result=state['result']
        self.assertEqual(result['count'],3);self.assertEqual(result['files'],1);self.assertEqual(result['status'],'LIMITED')
        self.assertEqual(len(self.api('archive')),1)
        form['copies_per_value']=2;state=self.api('configure',form);self.assertTrue(state['path_approved'])
        form['output_directory']=str(self.folder/'other');state=self.api('configure',form);self.assertFalse(state['path_approved'])
        with self.assertRaises(HTTPError):self.api('generate',{})
    def test_lab_config_is_complete_and_independent_and_small_test_runs(self):
        self.load();before=self.api('state')['form'];configs=self.api('configs');cfg=configs['LabConfig']
        cfg.update(counts=[2],cpu_counts=['1'],cpu_units=['logical'],backends=['serial'],ram_modes=['max'],repeats=1,warmups=0,
                   pdf_profiles=['compact'],activity_modes=['minimal'],telemetry_modes=['off'],qa_mode='deferred')
        plan=self.api('test-plan',{'name':'LabConfig','config':cfg});self.assertEqual(plan['plan']['runs'],1)
        self.assertEqual(self.api('state')['form'],before)
        command=self.api('console-plan',{'text':plan['command']});self.assertEqual(command['commands'][0]['config']['counts'],[2])
        self.api('test-start',{'name':'LabConfig','config':cfg});state=self.wait_done()
        self.assertEqual(state['result']['status'],'UNVERIFIED',state['result']);self.assertEqual(state['result']['kind'],'resource-lab')
    def test_stop_nonce_cannot_skip_delay(self):
        service=self.server.service;service.busy=True
        request=self.api('stop-request',{})
        with self.assertRaises(HTTPError):self.api('stop',{'nonce':request['nonce']})
        self.assertFalse(service.cancel.is_set());service._stop_at-=3.1
        self.api('stop',{'nonce':request['nonce']});self.assertTrue(service.cancel.is_set());service.busy=False
    def test_saved_source_cache_restores_without_reindex_and_old_fields_remain(self):
        import importlib
        from unittest.mock import patch
        from ucode.operator_service import OperatorService
        self.load()
        with patch('ucode.operator_models.SourceIndex.build',side_effect=AssertionError('unexpected reindex')):
            restored=OperatorService(self.folder)
        self.assertEqual(restored.index.row(2),'000000100003')
        inventory=Path(__file__).resolve().parents[1]/'docs/UI_REDESIGN_INVENTORY.json'
        for item in json.loads(inventory.read_text(encoding='utf-8'))['configuration_classes']:
            module=importlib.import_module(item['file'].removesuffix('.py').replace('/','.'))
            self.assertTrue(set(item['fields']).issubset(getattr(module,item['class']).__dataclass_fields__))
    def test_cmyk_background_console_round_trip_and_current_help(self):
        cfg=self.api('configs')['LabConfig'];cfg['print_settings'].update(ink=[0,0,0,0],background_mode='color',background_ink=[0,0,0,100])
        plan=self.api('test-plan',{'name':'LabConfig','config':cfg})
        parsed=self.api('console-plan',{'text':plan['command']})['commands'][0]['config']
        self.assertEqual(parsed['print_settings']['background_mode'],'color')
        self.assertEqual(parsed['print_settings']['background_ink'],[0,0,0,100])
        self.assertIn('--background',self.api('commands-help')['text'])
        topic=self.api('help')['topics'][0];self.assertIn('Путь',topic['short'])
