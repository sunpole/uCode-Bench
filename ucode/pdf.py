"""M03/M04/M05: one path of vector rectangles, native DeviceCMYK K100."""
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm
from .config import Experiment, QRFrame
from . import __version__


def write_pdf(frames: list[QRFrame], path: Path, config: Experiment, *, on_progress=None, cancel=None) -> None:
    if getattr(config,"pdf_profile","standard")=="compact":
        from .compact_pdf import write_pdf as compact_write
        return compact_write(frames,path,config,on_progress=on_progress,cancel=cancel)
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    if not frames:
        raise ValueError("No QR frames")
    module = config.module_mm * mm
    side = (21 + 2 * config.quiet_modules) * module
    canvas = Canvas(str(path), pagesize=(side, side), pageCompression=1, invariant=1,
                    enforceColorSpace="CMYK")
    canvas.setTitle(f"uCode: {len(frames)} QR Code")
    canvas.setCreator(f"uCode {__version__}")
    for index, frame in enumerate(frames, 1):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Запись PDF остановлена; прежние файлы сохранены")
        if frame.size != 21 or any(len(row) != 21 for row in frame.matrix) or frame.version != 1 or frame.error != "M":
            raise ValueError("Only ordinary QR V1-M frames are supported")
        canvas.setFillColorCMYK(*(v / 100 for v in getattr(config, "ink", (0, 0, 0, 100))))
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
        if on_progress:
            on_progress(index, len(frames))
    canvas.save()


def write_single_files(frames: list[QRFrame], directory: Path, config: Experiment, *, on_progress=None, cancel=None) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=False)
    paths = []
    digits = max(4, len(str(len(frames))))
    for index, frame in enumerate(frames):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Создание отдельных PDF остановлено")
        path = directory / f"{index + 1:0{digits}d}_{frame.payload}.pdf"
        write_pdf([frame], path, config)
        paths.append(path)
        if on_progress:
            on_progress(index + 1, len(frames))
    return paths
