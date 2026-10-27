"""M03/M04/M05: one path of vector rectangles, native DeviceCMYK K100."""
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm
from .config import Experiment, QRFrame


def write_pdf(frames: list[QRFrame], path: Path, config: Experiment) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    if not frames:
        raise ValueError("No QR frames")
    module = config.module_mm * mm
    side = (21 + 2 * config.quiet_modules) * module
    canvas = Canvas(str(path), pagesize=(side, side), pageCompression=1, invariant=1,
                    enforceColorSpace="CMYK")
    canvas.setTitle("uCode QR benchmark")
    canvas.setCreator("uCode 0.1.0")
    for frame in frames:
        if frame.size != 21 or any(len(row) != 21 for row in frame.matrix) or frame.version != 1 or frame.error != "M":
            raise ValueError("Only ordinary QR V1-M frames are supported")
        canvas.setFillColorCMYK(0, 0, 0, 1)
        for row_index, row in enumerate(frame.matrix):
            column = 0
            while column < 21:
                if not row[column]:
                    column += 1
                    continue
                start = column
                while column < 21 and row[column]:
                    column += 1
                canvas.rect((config.quiet_modules + start) * module,
                            (config.quiet_modules + 20 - row_index) * module,
                            (column - start) * module, module, stroke=0, fill=1)
        canvas.showPage()
    canvas.save()


def write_single_files(frames: list[QRFrame], directory: Path, config: Experiment) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=False)
    paths = []
    for index, frame in enumerate(frames):
        path = directory / f"{index + 1:04d}_{frame.payload}.pdf"
        write_pdf([frame], path, config)
        paths.append(path)
    return paths
