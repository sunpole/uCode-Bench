from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import threading
import unittest

from ucode.qr_payloads import KINDS,build_payload
from ucode.qr_content_codec import encode_content,decode_content
from ucode.qrdecode import DecodeError
from ucode.qr_content_job import run_content_job,qa_settings
from ucode.print_settings import PrintSettings
from ucode.quality import _decode_image
from ucode.audit import audit_job
from ucode.operator_service import OperatorService

def samples():
    result={'text':{'text':'Привет из uCode! 🙂'},'url':{'url':'https://example.com/a?x=1&b=2'},
        'email':{'email':'test@example.com','subject':'Тема & тест','message':'Привет\nВторая строка'},
        'phone':{'phone':'+7 (999) 123-45-67'},'sms':{'phone':'+79991234567','message':'Тест: привет!'},
        'contact':{'given':'Иван','family':'Тестов','phone':'+79991234567','note':'Тест; запятая,\nстрока'},
        'wifi':{'ssid':'Тест;WiFi','password':'test;,:\\"123','security':'WPA','hidden':True},
        'whatsapp':{'phone':'+79991234567','message':'Тест & привет'},
        'event':{'title':'Тест встречи','start':'2026-11-01T12:00','end':'2026-11-01T13:00','location':'Зал; 1'},
        'geo':{'latitude':'55.75','longitude':'37.62'}}
    for kind in ('pdf','images','video','app','social'):result[kind]={'url':'https://example.com/file'}
    return result

class StaticContentTests(unittest.TestCase):
    def test_transparent_and_inverted_backgrounds_remain_decodable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            settings_list=[PrintSettings(background_mode='transparent'),PrintSettings(ink=(0,0,0,0),background_mode='color',background_ink=(0,0,0,100))]
            for i,settings in enumerate(settings_list):
                request={'payload':'Тест подложки','content_kind':'text','settings':asdict(settings),'options':{'copies_per_value':1,'qa_mode':'vector'},
                         'mode':'multipage','destination':str(root),'archive':str(root/'archive'),'output_name':f'background-{i}.pdf'}
                folder=run_content_job(request,threading.Event(),lambda *args:None)
                self.assertEqual(json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['status'],'LIMITED')
                frame=encode_content(request['payload']);self.assertEqual(_decode_image(folder/'qr.png',qa_settings(settings),frame.size),request['payload'])

    def test_all_kinds_all_corrections_decode_exact_payload(self):
        self.assertEqual(set(samples()),set(KINDS))
        for kind,values in samples().items():
            payload=build_payload(kind,values)
            for level in 'LMQH':
                with self.subTest(kind=kind,level=level):
                    frame=encode_content(payload,level);self.assertEqual(decode_content(frame.matrix,level),payload)
        self.assertEqual(build_payload('phone',{'phone':'+7 (999) 123-45-67'}),'tel:+79991234567')
        self.assertIn('subject=%D0%A2',build_payload('email',samples()['email']))
        self.assertIn('S:Тест\\;WiFi;',build_payload('wifi',samples()['wifi']))

    def test_versions_utf8_padding_corruption_and_capacity(self):
        for payload in ('1234567890','HELLO WORLD','Я'*500,'abc'*800,'a'*2951):
            frame=encode_content(payload,'L');self.assertEqual(decode_content(frame.matrix,'L'),payload)
            if len(payload)==2951:self.assertEqual(frame.version,40)
            broken=[list(row) for row in frame.matrix];broken[-1][-1]=not broken[-1][-1]
            with self.assertRaises(DecodeError):decode_content(broken,'L')
            with self.assertRaises(DecodeError):decode_content(frame.matrix,'H')
        with self.assertRaises(ValueError):encode_content('Я'*1000,'H')
        for kind,values in [('url',{'url':'javascript:alert(1)'}),('url',{'url':'https://a/b%zz'}),('email',{'email':'bad\n@a.com'}),('phone',{'phone':'abc'}),('wifi',{'ssid':'','security':'WPA','password':'12345678'}),('event',{'title':'Test','start':'2026-11-02T12:00','end':'2026-11-01T12:00'})]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):build_payload(kind,values)

    def test_every_content_kind_real_pdf_png_reaudit_and_archive_privacy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for kind,values in samples().items():
                with self.subTest(kind=kind):
                    payload=build_payload(kind,values)
                    request={'payload':payload,'content_kind':kind,'settings':asdict(PrintSettings()),'options':{'copies_per_value':1,'qa_mode':'vector'},
                             'mode':'multipage','destination':str(root),'archive':str(root/'archive'),'output_name':kind+'.pdf'}
                    folder=run_content_job(request,threading.Event(),lambda *args:None)
                    report=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));self.assertEqual(report['status'],'LIMITED',report['qa'])
                    self.assertEqual((folder/'payload.txt').read_bytes(),payload.encode('utf-8'))
                    frame=encode_content(payload);self.assertEqual(_decode_image(folder/'qr.png',qa_settings(PrintSettings()),frame.size),payload)
                    audit=audit_job(folder,render_samples=False);self.assertEqual(json.loads((audit/'audit.json').read_text(encoding='utf-8'))['status'],'LIMITED')
            for path in (root/'archive').rglob('*.json'):
                text=path.read_text(encoding='utf-8');self.assertNotIn('test;,:',text);self.assertNotIn('WIFI:T:',text)

    def test_single_and_both_output_and_service_restoration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);service=OperatorService(root);service.set_content('text',{'text':'Сравнение QR'})
            self.assertEqual(service.state()['content_kind'],'text');self.assertEqual(OperatorService(root).index.first,'Сравнение QR')
            with self.assertRaises(ValueError):service.set_content('phone',{'phone':'bad'})
            self.assertEqual(service.index.first,'Сравнение QR')
            for mode in ('singles','both'):
                request={'payload':'Сравнение QR','content_kind':'text','settings':asdict(PrintSettings(error_correction='H')),
                         'options':{'copies_per_value':3,'qa_mode':'vector'},'mode':mode,'destination':str(root),'archive':str(root/'archive'),'output_name':'comparison.pdf'}
                folder=run_content_job(request,threading.Event(),lambda *args:None)
                self.assertEqual(json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['status'],'LIMITED')
                audit=audit_job(folder,render_samples=False);self.assertEqual(json.loads((audit/'audit.json').read_text(encoding='utf-8'))['status'],'LIMITED')
