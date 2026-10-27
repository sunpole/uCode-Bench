"""Contracts for engine selection, independent QA, and observed speed."""
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ucode.batch import run_batch
from ucode.progress import ProgressTracker
from ucode.engines import ReportLabEngine, get_engine
from ucode.generators import QRGenerator
from ucode.print_settings import PrintSettings


class EnginePipelineTests(unittest.TestCase):
    def test_selected_modules_drive_real_pdf_and_independent_qa(self):
        calls = []
        class TestQR(QRGenerator):
            def validate(self, value):
                calls.append("validate")
                return super().validate(value)

            def verify(self, *args, **kwargs):
                calls.append("independent-qa")
                return super().verify(*args, **kwargs)

        class RecordingEngine(ReportLabEngine):
            def info(self):
                return replace(super().info(), key="recording", name="Recording engine",
                               symbologies=("qr-test",))

            def encode(self, *args, **kwargs):
                calls.append("encode")
                return super().encode(*args, **kwargs)

            def write_pdf(self, *args, **kwargs):
                calls.append("write")
                return super().write_pdf(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.txt"
            source.write_text("000000000001\n200000000099\n", encoding="utf-8")
            with patch.dict("ucode.engines._ENGINES", {"recording": RecordingEngine()}), patch.dict(
                "ucode.generators._GENERATORS", {"qr-test": TestQR(key="qr-test")}
            ):
                folder = run_batch(source, root / "jobs", generator="qr-test", engine="recording", mode="both")
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn(data["status"], ("COMPLETE", "LIMITED"))
            self.assertEqual(data["engine"]["key"], "recording")
            self.assertEqual(data["generator"], "qr-test")
            self.assertEqual(data["qa"]["multipage"]["status"], "PASS")
            self.assertEqual(data["qa"]["singles"]["checked"], 2)
            self.assertIn("Recording engine", (folder / "ОТЧЁТ.txt").read_text(encoding="utf-8"))
            self.assertEqual(calls.count("encode"), 1)
            self.assertEqual(calls.count("write"), 3)
            self.assertEqual(calls.count("independent-qa"), 3)
            self.assertEqual(calls.count("validate"), 2)

    def test_encoder_cannot_change_txt_order_and_claim_success(self):
        class ReorderingEngine(ReportLabEngine):
            def encode(self, *args, **kwargs):
                return list(reversed(super().encode(*args, **kwargs)))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.txt"
            source.write_text("200000000001\n200000000002\n", encoding="utf-8")
            with patch.dict("ucode.engines._ENGINES", {"bad-order": ReorderingEngine()}):
                folder = run_batch(source, root / "jobs", engine="bad-order")
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "ERROR")
            self.assertIn("порядок", " ".join(data["errors"]))
            self.assertFalse(list(folder.glob("*.pdf")))

    def test_engine_cannot_self_certify_wrong_pdf(self):
        class WrongPdfEngine(ReportLabEngine):
            def write_pdf(self, frames, *args, **kwargs):
                return super().write_pdf(list(reversed(frames)), *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.txt"
            source.write_text("200000000001\n200000000002\n", encoding="utf-8")
            events = []
            with patch.dict("ucode.engines._ENGINES", {"bad-pdf": WrongPdfEngine()}):
                folder = run_batch(source, root / "jobs", engine="bad-pdf", mode="multipage", events=events.append)
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "INVALID")
            self.assertEqual(data["qa"]["multipage"]["status"], "FAIL")
            self.assertTrue(all(e["percent"] < 100 for e in events))

    def test_unsupported_capabilities_fail_before_output(self):
        class SingleOnly(ReportLabEngine):
            def info(self):
                return replace(super().info(), output_modes=("singles",))

        with tempfile.TemporaryDirectory() as temp, patch.dict("ucode.engines._ENGINES", {"single": SingleOnly()}):
            root = Path(temp) / "output"
            with self.assertRaisesRegex(ValueError, "формат результата"):
                run_batch(Path(temp) / "not-even-read.txt", root, engine="single", mode="both")
            self.assertFalse(root.exists())
        with self.assertRaisesRegex(ValueError, "тип кода"):
            get_engine(generator="datamatrix")
        with self.assertRaisesRegex(ValueError, "DeviceGray"):
            get_engine(colorspace="DeviceGray")

    def test_fixed_scientific_workers_share_the_engine(self):
        from ucode.benchmark import _measure, _new_directory
        from ucode.config import Experiment
        with tempfile.TemporaryDirectory() as temp:
            config = Experiment(count=2)
            folder = _new_directory(Path(temp), 2)
            frames = folder / "frames.json"
            encoded = _measure(folder, config, "encode", frames, tag="engine-encode")
            singles = _measure(folder, config, "singles", folder / "singles", tag="engine-singles", frames=str(frames))
            direct = _measure(folder, config, "direct", folder / "direct.pdf", tag="engine-direct")
            for value in (encoded, singles, direct):
                self.assertEqual(value["engine"]["key"], "reportlab")
                self.assertTrue(value["engine"]["version"])
            self.assertEqual(len(list((folder / "singles").glob("*.pdf"))), 2)
            values = QRGenerator().encode(["200000000000", "200000000001"])
            self.assertEqual(QRGenerator().verify(folder / "direct.pdf", values, PrintSettings(),
                                                 render_samples=False)["status"], "PASS")

    def test_old_qr_api_keeps_real_rendering_and_qa(self):
        module = QRGenerator()
        settings = module.default_settings()
        with tempfile.TemporaryDirectory() as temp:
            frames = module.encode(["000000000001"])
            pdf = Path(temp) / "code.pdf"
            module.write_pdf(frames, pdf, settings)
            self.assertEqual(module.verify(pdf, frames, settings, render_samples=False)["status"], "PASS")
            self.assertTrue(get_engine().info().available)

    def test_unknown_engine_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.txt"
            source.write_text("200000000001\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "движок"):
                run_batch(source, root / "jobs", engine="not-registered")
            self.assertFalse((root / "jobs").exists())

    def test_speed_window_and_stage_average_are_distinct_and_reset(self):
        now = [0.0]
        events = []
        tracker = ProgressTracker(1000, events.append, clock=lambda: now[0], speed_window=3)
        tracker.step("QR", 0, 100, 0, force=True)
        for t, done in ((1, 10), (2, 20), (3, 30), (4, 31), (5, 32), (6, 33)):
            now[0] = t
            tracker.step("QR", done, 100, 0, force=True)
        self.assertAlmostEqual(events[-1]["speed"], 1)
        self.assertAlmostEqual(events[-1]["average_speed"], 5.5)
        now[0] = 7
        tracker.step("QR", 0, 100, 100, force=True)
        now[0] = 8
        tracker.step("QR", 4, 100, 100, force=True)
        self.assertAlmostEqual(events[-1]["speed"], 4)
        self.assertAlmostEqual(events[-1]["average_speed"], 4)
        self.assertLess(events[-1]["percent"], 100)

    def test_first_observation_has_no_invented_speed(self):
        now = [10.0]
        events = []
        tracker = ProgressTracker(100, events.append, clock=lambda: now[0])
        tracker.step("External", 20, 100, 0, force=True)
        self.assertEqual(events[-1]["speed"], 0)
        self.assertEqual(events[-1]["average_speed"], 0)
        now[0] = 12
        tracker.step("External", 24, 100, 0, force=True)
        self.assertEqual(events[-1]["speed"], 2)
        self.assertEqual(events[-1]["average_speed"], 2)
