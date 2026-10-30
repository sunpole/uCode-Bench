from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from ucode.engines import get_engine
from ucode.print_settings import PrintSettings
from ucode.quality import check_pdf
from ucode.stream_pdf import write_pdf


class BackgroundPDFTests(unittest.TestCase):
    def test_default_white_still_rejects_invisible_foreground(self):
        with self.assertRaises(ValueError): PrintSettings(ink=(0,0,0,0))
        with self.assertRaises(ValueError): PrintSettings(background_mode='color',background_ink=(0,0,0,100))

    def test_inverse_background_in_all_writers_and_strict_wrong_color(self):
        engine=get_engine();frames=engine.encode(['200000000001'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for profile in ('standard','compact','stream'):
                cfg=PrintSettings(ink=(0,0,0,0),background_mode='color',background_ink=(0,0,0,100),pdf_profile='compact' if profile=='compact' else 'standard')
                path=root/(profile+'.pdf')
                if profile=='stream': write_pdf(frames,path,cfg,root/'index.sqlite')
                else: engine.write_pdf(frames,path,cfg)
                qa=check_pdf(path,frames,cfg)
                self.assertEqual(qa['status'],'PASS',qa)
                bad=replace(cfg,background_ink=(100,0,0,0))
                self.assertEqual(check_pdf(path,frames,bad,render_samples=False)['status'],'FAIL')

    def test_transparent_mode_does_not_paint_a_background(self):
        from pypdf import PdfReader
        from pypdf.generic import ContentStream
        engine=get_engine();frames=engine.encode(['200000000001'])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'transparent.pdf';cfg=PrintSettings(background_mode='transparent',pdf_profile='compact')
            engine.write_pdf(frames,path,cfg)
            qa=check_pdf(path,frames,cfg);self.assertEqual(qa['status'],'PASS',qa)
            reader=PdfReader(path)
            operations=ContentStream(reader.pages[0].get_contents(),reader).operations
            side=cfg.side_mm*72/25.4
            self.assertFalse(any(op==b're' and len(args)==4 and abs(float(args[2])-side)<.001 for args,op in operations))
