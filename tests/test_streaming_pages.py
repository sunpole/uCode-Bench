"""Uncapped counts/real disk pipeline; actual PDFs remain at most six pages."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from ucode.batch import run_batch
from ucode.execution import ExecutionOptions
from ucode.print_settings import PrintSettings
from ucode.stream_data import SourceInfo,inspect_codes


class StreamingPageTests(unittest.TestCase):
    def source(self,root,text="000000000001\n200000000002\n"):
        path=root/"codes.txt"; path.write_text(text,encoding="utf-8"); return path
    def run_stream(self,source,root,**kwargs):
        with patch("ucode.batch.STREAM_THRESHOLD",1):
            return run_batch(source,root,**kwargs)
    def manifest(self,folder): return json.loads((folder/"manifest.json").read_text(encoding="utf-8"))

    def test_counts_above_ten_thousand_are_accepted_without_large_runs(self):
        from ucode.generation_plan import build_plan
        from ucode.app_settings import GenerationPreferences
        from ucode.resource_lab import LabConfig,build_cases
        from test_lab_interface import cpu_fixture
        info=SourceInfo(100001,100000,"000000000001","200000000002")
        self.assertEqual(build_plan(info,copies_per_value=2).total_codes,200002)
        self.assertEqual(build_plan(info,copies_per_value=2,duplicate_policy="unique").total_codes,200000)
        self.assertEqual(GenerationPreferences(template_count=100001,copies_per_value=100001).template_count,100001)
        config=LabConfig(counts=(20000,),cpu_units=("physical",),cpu_counts=("1","all"),repeats=1,backends=("process",))
        cases=build_cases(config,cpu_fixture(14))
        self.assertEqual([len(case["cpus"]) for case in cases],[1,14])
        self.assertEqual(len(cases),2)

    def test_scanner_keeps_only_summary_and_still_reports_bad_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root,"000000000001\n200000000002\n000000000001\n")
            info=inspect_codes(source,threshold=1)
            self.assertIsInstance(info,SourceInfo)
            self.assertEqual((len(info),info.unique,info[0],info[-1]),(3,2,"000000000001","000000000001"))
            source.write_text("000000000001\n200000000002\nBAD\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"Строка 3"):
                self.run_stream(source,root/"out")
            self.assertFalse((root/"out").exists())

    def test_large_source_stays_streamed_even_when_unique_output_is_small(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root,"000000000001\n000000000001\n000000000001\n")
            with patch("ucode.batch.STREAM_THRESHOLD",2):
                folder=run_batch(source,root/"out",mode="multipage",duplicate_policy="unique",qa_mode="vector")
            data=self.manifest(folder)
            self.assertTrue(data["streaming"])
            self.assertEqual(data["count"],1)
            self.assertEqual(data["status"],"LIMITED",data)
            self.assertEqual(data["generation"]["input_records"],3)

    def test_compact_copies_reuse_contents_with_disk_indexes_and_no_qa(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root,"000000000001\n200000000002\n000000000001\n")
            events=[]
            with patch("ucode.stream_batch.verify_stream_outputs",side_effect=AssertionError("QA must not run")) as verify:
                folder=self.run_stream(source,root/"out",mode="both",copies_per_value=3,duplicate_policy="unique",
                    qa_mode="deferred",activity="minimal",settings=PrintSettings(pdf_profile="compact"),events=events.append,
                    execution=ExecutionOptions("serial",1,1))
            data=self.manifest(folder); verify.assert_not_called()
            self.assertEqual(data["status"],"UNVERIFIED",data)
            self.assertTrue(data["streaming"])
            self.assertEqual(data["generation"]["encoded_values"],2)
            self.assertLessEqual(data["execution"]["max_in_flight_values"],1)
            self.assertEqual(data["seconds"]["quality_checks"],0)
            self.assertEqual((folder/"codes.txt").read_text().splitlines(),["000000000001"]*3+["200000000002"]*3)
            reader=PdfReader(folder/"all-6-pages.pdf",strict=True)
            self.assertEqual(len(reader.pages),6)
            self.assertEqual(reader.pages[0].raw_get("/Contents"),reader.pages[2].raw_get("/Contents"))
            self.assertTrue((folder/"data.sqlite").is_file()); self.assertTrue((folder/"pdf-index.sqlite").is_file())
            self.assertFalse(list(folder.rglob("*.png")))
            self.assertEqual(events[-1]["percent"],100)

    def test_all_encoding_backends_keep_real_pdf_order_and_structural_qa(self):
        from ucode.hardware import inspect_cpu
        for backend in ("serial","process","thread"):
            with self.subTest(backend=backend),tempfile.TemporaryDirectory() as temp:
                root=Path(temp); source=self.source(root)
                folder=self.run_stream(source,root/"out",mode="multipage",qa_mode="vector",
                    execution=ExecutionOptions(backend,min(2,inspect_cpu()["available_logical"]),1))
                data=self.manifest(folder)
                self.assertEqual(data["status"],"LIMITED",data)
                self.assertEqual(data["qa"]["multipage"]["status"],"PASS")
                self.assertEqual(data["qa"]["multipage"]["pages_checked"],2)
                self.assertLessEqual(data["execution"]["max_in_flight_values"],2)

    def test_full_qa_and_independent_audit_detect_final_pdf_tree_damage(self):
        from ucode.audit import audit_job
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root)
            folder=self.run_stream(source,root/"out",mode="multipage",qa_mode="full",settings=PrintSettings(ink=(100,0,0,0)))
            data=self.manifest(folder)
            self.assertIn(data["status"],("COMPLETE","LIMITED"),data)
            self.assertEqual(data["qa"]["multipage"]["status"],"PASS")
            original=(folder/"manifest.json").read_bytes()
            pdf=folder/"all-2-pages.pdf"; raw=pdf.read_bytes(); pdf.write_bytes(raw.replace(b"/Count 2",b"/Count 3"))
            audit=audit_job(folder,render_samples=False)
            result=json.loads((audit/"audit.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"],"INVALID",result)
            self.assertEqual((folder/"manifest.json").read_bytes(),original)

    def test_cancel_and_runtime_resource_failure_preserve_partial_files(self):
        from ucode.stream_batch import ResourceGuard
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=self.source(root); raw=source.read_bytes(); stop=threading.Event(); events=[]
            def observe(value):
                events.append(value)
                if value["stage"]=="Кодирование QR" and value["done"]==1: stop.set()
            folder=self.run_stream(source,root/"cancel",mode="multipage",qa_mode="deferred",cancel=stop,
                events=observe,execution=ExecutionOptions("serial",1,1))
            self.assertEqual(self.manifest(folder)["status"],"CANCELLED")
            self.assertTrue(all(e["percent"]<100 for e in events))
            real=ResourceGuard.__call__
            def exhaust(guard):
                real(guard)
                if any(guard.directory.glob("all-*-pages.pdf")): raise RuntimeError("Диск заполнен (контрольный сценарий)")
            with patch.object(ResourceGuard,"__call__",exhaust):
                folder=self.run_stream(source,root/"disk",mode="multipage",qa_mode="deferred")
            self.assertEqual(self.manifest(folder)["status"],"ERROR")
            self.assertTrue((folder/"all-2-pages.pdf").exists())
            self.assertEqual(source.read_bytes(),raw)
