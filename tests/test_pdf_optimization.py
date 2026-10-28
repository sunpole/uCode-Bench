"""Real vector PDFs, unchanged independent QA and explicit deferred checks."""
import json
from pathlib import Path
import tempfile
import unittest
import shutil

from pypdf import PdfReader
from ucode.batch import run_batch
from ucode.print_settings import PrintSettings


class CompactPdfTests(unittest.TestCase):
    def test_pair_metrics_compare_only_matching_cpu_ram_and_activity(self):
        from ucode.lab_report import optimization_pairs
        common={"count":7,"cpu_unit":"logical","cpus":[{"group":0,"logical":0}],"workers":1,
                "backend":"serial","ram_mode":"max","activity":"minimal","status":"PASS"}
        before={**common,"id":"A","pdf_profile":"standard","summary":{"status":"PASS","median_seconds":4,
                "median_with_qa_seconds":6,"median_pdf_bytes":1000}}
        after={**common,"id":"B","pdf_profile":"compact","summary":{"status":"PASS","median_seconds":2,
                "median_with_qa_seconds":5,"median_pdf_bytes":600}}
        pair=optimization_pairs([before,after])[0]
        self.assertEqual(pair["generation_speedup"],2)
        self.assertEqual(pair["size_saved_percent"],40)
        self.assertEqual(optimization_pairs([before,{**after,"activity":"normal"}]),[])

    @unittest.skipUnless(shutil.which("pdftoppm"),"Poppler unavailable")
    def test_default_raster_binary_geometry_is_identical(self):
        from ucode.qr import encode_numbers
        from ucode.pdf import write_pdf
        from PIL import Image,ImageChops
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); frames=encode_numbers(["000000000001","200000000002"])
            for profile in ("standard","compact"):
                pdf=root/(profile+".pdf")
                write_pdf(frames,pdf,PrintSettings(pdf_profile=profile))
                subprocess.run([shutil.which("pdftoppm"),"-r","1016","-f","1","-l","1","-singlefile","-png",str(pdf),str(root/profile)],check=True,capture_output=True)
            with Image.open(root/"standard.png") as a,Image.open(root/"compact.png") as b:
                # Merged paths remove repeated edge painting. Antialiasing gray
                # values can differ at boundaries; black/white coverage must not.
                binary=lambda image:image.convert("L").point(lambda value:255 if value>=128 else 0)
                self.assertIsNone(ImageChops.difference(binary(a),binary(b)).getbbox())

    def test_modes_roundtrip_and_old_preferences_keep_full_qa(self):
        from ucode.app_settings import GenerationPreferences,save_preferences,load_user_preferences
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"settings.json"
            cfg=PrintSettings(pdf_profile="compact")
            prefs=GenerationPreferences(qa_mode="deferred",activity="minimal")
            save_preferences(path,cfg,"multipage",generation=prefs)
            self.assertEqual(load_user_preferences(path),(cfg,"multipage",prefs,""))
            path.write_text(json.dumps({"schema_version":1,"mode":"multipage",
                "settings":{"module_mm":.5,"quiet_modules":4}}),encoding="utf-8")
            cfg,_,prefs,_=load_user_preferences(path)
            self.assertEqual((cfg.pdf_profile,prefs.qa_mode,prefs.activity),("standard","full","normal"))

    def test_compact_cancel_and_no_overwrite(self):
        from ucode.compact_pdf import write_pdf
        from ucode.qr import encode_numbers
        import threading
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); frames=encode_numbers(["000000000001","200000000002"])
            existing=root/"existing.pdf"; existing.write_bytes(b"KEEP")
            with self.assertRaises(FileExistsError): write_pdf(frames,existing,PrintSettings())
            self.assertEqual(existing.read_bytes(),b"KEEP")
            stop=threading.Event(); path=root/"partial.pdf"
            with self.assertRaises(InterruptedError):
                write_pdf(frames,path,PrintSettings(),cancel=stop,on_progress=lambda done,total:stop.set())
            self.assertTrue(path.is_file())
            self.assertNotIn(b"%%EOF",path.read_bytes())

    def test_shared_document_resources_and_repeated_contents(self):
        from ucode.qr import encode_numbers
        from ucode.pdf import write_pdf
        from ucode.quality import check_pdf
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); values=["000000000001","200000000002"]
            encoded=encode_numbers(values); frames=[encoded[0]]*3+[encoded[1]]*3
            normal=root/"standard.pdf"; compact=root/"compact.pdf"
            write_pdf(frames,normal,PrintSettings())
            settings=PrintSettings(pdf_profile="compact")
            write_pdf(frames,compact,settings)
            self.assertLess(compact.stat().st_size,normal.stat().st_size)
            reader=PdfReader(compact,strict=True)
            parent=reader.trailer["/Root"]["/Pages"]
            self.assertIn("/MediaBox",parent)
            self.assertIn("/Resources",parent)
            pages=[ref.get_object() for ref in parent["/Kids"]]
            self.assertTrue(all("/Resources" not in page and "/MediaBox" not in page for page in pages))
            self.assertEqual(pages[0]["/Contents"][1],pages[2]["/Contents"][1])
            self.assertNotEqual(pages[0]["/Contents"][1],pages[3]["/Contents"][1])
            qa=check_pdf(compact,frames,settings,render_samples=False)
            self.assertEqual(qa["status"],"PASS",qa)
            self.assertEqual(qa["pages_checked"],6)
            self.assertEqual(qa["content_decodes"],2)
            self.assertEqual(qa["cached_content_pages"],4)
            self.assertNotIn(b"/Font",compact.read_bytes())

    def test_shared_contents_do_not_bypass_page_geometry_or_expected_payload(self):
        from ucode.qr import encode_numbers
        from ucode.pdf import write_pdf
        from ucode.quality import check_pdf
        from ucode.config import QRFrame
        from pypdf import PdfWriter
        from pypdf.generic import NameObject,RectangleObject
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); frame=encode_numbers(["000000000001"])[0]; frames=[frame]*3
            settings=PrintSettings(pdf_profile="compact"); path=root/"shared.pdf"
            write_pdf(frames,path,settings)
            wrong=[frame,QRFrame("200000000002",frame.matrix),frame]
            self.assertEqual(check_pdf(path,wrong,settings,render_samples=False)["status"],"FAIL")
            reader=PdfReader(path); writer=PdfWriter()
            for index,page in enumerate(reader.pages):
                if index==1: page[NameObject("/MediaBox")]=RectangleObject([0,0,50,50])
                writer.add_page(page)
            damaged=root/"damaged.pdf"
            with damaged.open("wb") as stream: writer.write(stream)
            self.assertEqual(check_pdf(damaged,frames,settings,render_samples=False)["status"],"FAIL")

    def test_unique_color_and_custom_geometry_pass_original_qa(self):
        from ucode.qr import encode_numbers
        from ucode.pdf import write_pdf
        from ucode.quality import check_pdf
        with tempfile.TemporaryDirectory() as temp:
            frames=encode_numbers([f"{200000000000+i:012d}" for i in range(7)])
            settings=PrintSettings(.7,5,(100,0,0,0),pdf_profile="compact")
            path=Path(temp)/"color.pdf"; write_pdf(frames,path,settings)
            self.assertEqual(check_pdf(path,frames,settings,render_samples=False)["status"],"PASS")

    def test_deferred_qa_is_not_pass_and_can_be_audited_later(self):
        from ucode.audit import audit_job
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/"input.txt"
            source.write_text("000000000001\n200000000002\n",encoding="utf-8")
            folder=run_batch(source,root/"jobs",mode="multipage",settings=PrintSettings(pdf_profile="compact"),
                             qa_mode="deferred",activity="minimal")
            data=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"],"UNVERIFIED")
            self.assertEqual(data["qa"]["status"],"NOT_RUN")
            self.assertNotIn("sha256",data["files"]["multipage"])
            before=(folder/"manifest.json").read_bytes()
            result=audit_job(folder,render_samples=False)
            audit=json.loads((result/"audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"],"LIMITED")
            self.assertEqual(audit["qa"]["multipage"]["status"],"PASS")
            self.assertEqual(before,(folder/"manifest.json").read_bytes())

    def test_lab_profile_axis_does_not_merge_standard_and_compact(self):
        from ucode.resource_lab import LabConfig,build_cases
        cpu={"available_cpus":[{"id":0,"logical":0,"group":0,"core":0}]}
        config=LabConfig(counts=(2,),cpu_counts=("1",),backends=("serial",),ram_modes=("max",),
                         pdf_profiles=("standard","compact"))
        cases=build_cases(config,cpu)
        self.assertEqual([row["pdf_profile"] for row in cases],["standard","compact"])
        self.assertTrue(all(row["status"]=="PENDING" for row in cases))
