"""Public-behavior QA regression tests; no package installation required."""

from pathlib import Path
import shutil
import tempfile
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel, QRNumber
from reportlab.pdfgen.canvas import Canvas

from ucode.config import Experiment, QRFrame
from ucode.qrdecode import DecodeError, decode_numeric_v1_m
from ucode.quality import check_pdf


def symbol(payload="200000000000"):
    qr = QRCode(1, QRErrorCorrectLevel.M)
    qr.addData(QRNumber(payload))
    qr.make()
    return QRFrame(payload, tuple(tuple(bool(cell) for cell in row) for row in qr.modules))


def write_fixture(path, frames, *, rgb=False, size_mm=14.5):
    unit = 0.5 * 72 / 25.4
    canvas = Canvas(str(path), pagesize=(size_mm * 72 / 25.4,) * 2)
    for frame in frames:
        if rgb:
            canvas.setFillColorRGB(0, 0, 0)
        else:
            canvas.setFillColorCMYK(0, 0, 0, 1)
        for row, cells in enumerate(frame.matrix):
            for column, dark in enumerate(cells):
                if dark:
                    canvas.rect((column + 4) * unit, (24 - row) * unit, unit, unit, fill=1, stroke=0)
        canvas.showPage()
    canvas.save()


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ucode-quality-")
        self.root = Path(self.temp.name)
        self.config = Experiment(count=2)
        self.frames = [symbol(), symbol("200000000001")]

    def tearDown(self):
        self.temp.cleanup()

    def test_independent_decoder_recovers_numbers_and_leading_zeros(self):
        for payload in ("200000000000", "200000000001", "000000000001", "999999999999"):
            with self.subTest(payload=payload):
                self.assertEqual(decode_numeric_v1_m(symbol(payload).matrix), payload)

    def test_decoder_rejects_damaged_data_and_format(self):
        for row, col in ((20, 20), (0, 8), (0, 0)):
            matrix = [list(row) for row in self.frames[0].matrix]
            matrix[row][col] = not matrix[row][col]
            with self.subTest(location=(row, col)), self.assertRaises(DecodeError):
                decode_numeric_v1_m(matrix)

    def test_every_page_vector_payload_and_exact_geometry_pass(self):
        path = self.root / "valid.pdf"
        write_fixture(path, self.frames)
        qa = check_pdf(path, self.frames, self.config, render_samples=False)
        self.assertEqual(qa["status"], "PASS", qa)
        self.assertEqual(qa["pages_checked"], 2)

    def test_rgb_is_invalid(self):
        path = self.root / "rgb.pdf"
        write_fixture(path, self.frames, rgb=True)
        self.assertEqual(check_pdf(path, self.frames, self.config, render_samples=False)["status"], "FAIL")

    def test_incorrect_dimension_is_invalid(self):
        path = self.root / "size.pdf"
        write_fixture(path, self.frames, size_mm=15)
        self.assertEqual(check_pdf(path, self.frames, self.config, render_samples=False)["status"], "FAIL")

    def test_wrong_order_and_wrong_txt_payload_are_invalid(self):
        path = self.root / "order.pdf"
        write_fixture(path, list(reversed(self.frames)))
        self.assertEqual(check_pdf(path, self.frames, self.config, render_samples=False)["status"], "FAIL")
        path2 = self.root / "payload.pdf"
        write_fixture(path2, self.frames)
        altered = [QRFrame("200000000123", self.frames[0].matrix), self.frames[1]]
        self.assertEqual(check_pdf(path2, altered, self.config, render_samples=False)["status"], "FAIL")

    def test_quiet_zone_paint_is_invalid(self):
        source = self.root / "quiet_source.pdf"
        target = self.root / "quiet.pdf"
        write_fixture(source, self.frames)
        reader = PdfReader(source)
        writer = PdfWriter()
        for page in reader.pages:
            stream = DecodedStreamObject()
            stream.set_data(page.get_contents().get_data() + b"\n0 0 0 1 k 0 0 1 1 re f\n")
            page[NameObject("/Contents")] = stream
            writer.add_page(page)
        with target.open("wb") as file:
            writer.write(file)
        self.assertEqual(check_pdf(target, self.frames, self.config, render_samples=False)["status"], "FAIL")

    def test_nearly_identity_transform_is_invalid_before_accumulation(self):
        source = self.root / "transform_source.pdf"
        target = self.root / "transform.pdf"
        write_fixture(source, self.frames)
        reader = PdfReader(source)
        writer = PdfWriter()
        for page in reader.pages:
            stream = DecodedStreamObject()
            # Each translation fits the rectangle-coordinate tolerance, but
            # repeated concatenation would move the QR by 2 whole PDF points.
            stream.set_data(b"1 0 0 1 0.0002 0 cm\n" * 10000 + page.get_contents().get_data())
            page[NameObject("/Contents")] = stream
            writer.add_page(page)
        with target.open("wb") as file:
            writer.write(file)
        qa = check_pdf(target, self.frames, self.config, render_samples=False)
        self.assertEqual(qa["status"], "FAIL", qa)
        self.assertTrue(any("Nonidentity transformation" in error for error in qa["errors"]), qa)

    def test_page_rgb_transparency_group_is_invalid(self):
        source = self.root / "group_source.pdf"
        target = self.root / "group.pdf"
        write_fixture(source, self.frames)
        reader = PdfReader(source)
        writer = PdfWriter()
        for page in reader.pages:
            page[NameObject("/Group")] = DictionaryObject({
                NameObject("/Type"): NameObject("/Group"),
                NameObject("/S"): NameObject("/Transparency"),
                NameObject("/CS"): NameObject("/DeviceRGB"),
            })
            writer.add_page(page)
        with target.open("wb") as file:
            writer.write(file)
        qa = check_pdf(target, self.frames, self.config, render_samples=False)
        self.assertEqual(qa["status"], "FAIL", qa)
        self.assertTrue(any("transparency groups" in error for error in qa["errors"]), qa)

    def test_raster_image_is_invalid(self):
        from PIL import Image
        from reportlab.lib.utils import ImageReader

        path = self.root / "raster.pdf"
        canvas = Canvas(str(path), pagesize=(14.5 * 72 / 25.4,) * 2)
        for _ in self.frames:
            canvas.drawImage(ImageReader(Image.new("RGB", (21, 21), "black")), 0, 0, width=41, height=41)
            canvas.showPage()
        canvas.save()
        self.assertEqual(check_pdf(path, self.frames, self.config, render_samples=False)["status"], "FAIL")

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm not installed")
    def test_rendered_pdf_is_actually_decoded(self):
        path = self.root / "render.pdf"
        write_fixture(path, self.frames)
        qa = check_pdf(path, self.frames, self.config)
        self.assertEqual(qa["status"], "PASS", qa)
        self.assertEqual([sample["payload"] for sample in qa["decoded_samples"]], [frame.payload for frame in self.frames])
        self.assertTrue(all(Path(sample["png"]).is_file() for sample in qa["decoded_samples"]))


if __name__ == "__main__":
    unittest.main()
