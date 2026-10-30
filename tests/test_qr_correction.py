from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ucode.qr import encode_numbers
from ucode.qrdecode import decode_numeric_v1,decode_numeric_v1_m,DecodeError
from ucode.print_settings import PrintSettings
from ucode.batch import run_batch
from ucode.execution import ExecutionOptions,encode_values
from ucode.audit import audit_job


class CorrectionTests(unittest.TestCase):
    def test_h_pipeline_uses_h_expected_frames(self):
        from dataclasses import asdict
        from ucode.pipeline_plan import PipelineConfig
        from ucode.pipeline_lab import run_pipeline_lab
        with tempfile.TemporaryDirectory() as temp:
            cfg=PipelineConfig(counts=(3,),allocations=('logical:1:0',),schedules=('queue',),batches=(1,),repeats=1,
                               qa_mode='vector',telemetry_modes=('off',),print_settings=asdict(PrintSettings(pdf_profile='compact',error_correction='H')))
            folder=run_pipeline_lab(Path(temp),cfg)
            report=json.loads((folder/'pipeline.json').read_text(encoding='utf-8'))
            self.assertEqual(report['cases'][0]['status'],'LIMITED',report['cases'][0])

    def test_standard_pdf_and_console_round_trip(self):
        from ucode.test_commands import parse_script,command_text
        from ucode.pdf import write_pdf
        from ucode.quality import check_pdf
        command=parse_script('test lab --codes 3 --ecc H')[0]
        self.assertEqual(parse_script(command_text(command))[0].config.print_settings['error_correction'],'H')
        with tempfile.TemporaryDirectory() as temp:
            for level in 'LMQH':
                frames=encode_numbers(['500000000000'],error_correction=level)
                settings=PrintSettings(error_correction=level)
                path=Path(temp)/(level+'.pdf');write_pdf(frames,path,settings)
                self.assertEqual(check_pdf(path,frames,settings,render_samples=False)['status'],'PASS')

    def test_all_levels_bch_rs_payload_and_negative_cases(self):
        for level in 'LMQH':
            frame=encode_numbers(['500000000000'],error_correction=level)[0]
            self.assertEqual(frame.error,level)
            self.assertEqual(decode_numeric_v1(frame.matrix,level),frame.payload)
            with self.assertRaises(DecodeError):decode_numeric_v1(frame.matrix,'H' if level!='H' else 'L')
            if level!='M':
                with self.assertRaises(DecodeError):decode_numeric_v1_m(frame.matrix)
            broken=[list(r) for r in frame.matrix];broken[20][20]=not broken[20][20]
            with self.assertRaises(DecodeError):decode_numeric_v1(broken,level)
        with self.assertRaises(ValueError):PrintSettings(error_correction='S')

    def test_execution_backends_retain_requested_level(self):
        for backend in ('serial','thread','process'):
            for level in 'LMQH':
                frames,_=encode_values(['500000000000','500000000001'],error_correction=level,
                                       options=ExecutionOptions(backend,2,1))
                self.assertEqual([f.error for f in frames],[level,level])
                self.assertEqual(decode_numeric_v1(frames[1].matrix,level),'500000000001')

    def test_real_pdf_every_level_mode_stream_and_reaudit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input.txt';source.write_text('500000000000\n500000000001\n500000000002\n')
            for level in 'LMQH':
                for streaming in (False,True):
                    for mode in ('multipage','singles','both'):
                        with self.subTest(level=level,streaming=streaming,mode=mode):
                            result=run_batch(source,root,mode=mode,settings=PrintSettings(pdf_profile='compact',error_correction=level),
                                             qa_mode='vector',force_disk=streaming)
                            report=json.loads((result/'manifest.json').read_text(encoding='utf-8'))
                            self.assertEqual(report['status'],'LIMITED',report.get('errors'))
                            self.assertEqual(report['print']['ecc'],level)
                            audit=audit_job(result,render_samples=False)
                            self.assertEqual(json.loads((audit/'audit.json').read_text(encoding='utf-8'))['status'],'LIMITED')
