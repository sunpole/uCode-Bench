"""TXT -> physical one-page PDFs and/or one multipage vector CMYK PDF.

This is separate from the three-repeat benchmark and its 200 -> 1000 gate.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .print_settings import human_report
from .data import write_numbers
from .engines import get_engine
from .generators import get_generator
from .progress import ProgressTracker
from .resources import check_resources
from . import __version__

SIZES = (200, 1000, 10000)
MAX_LINES = 10000
FIRST_NUMBER = 200000000000
FORMATS = ("both", "singles", "multipage")


def _make_directory(root: Path, kind: str) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = root / f"{kind}-{stamp}-{uuid.uuid4().hex[:8]}"
        try:
            target.mkdir(exist_ok=False)
            return target
        except FileExistsError:
            continue
    raise FileExistsError("Could not reserve a unique output directory")


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Генерация отменена; созданные файлы сохранены")


def make_template(output_root: Path, count: int, *, start: int = FIRST_NUMBER) -> Path:
    """Create a non-overwriting TXT with ordered 12-digit identifiers."""
    if count not in SIZES:
        raise ValueError("Поддерживаемые шаблоны: 200, 1000 и 10000 строк")
    if isinstance(start, bool) or not isinstance(start, int) or start < 0 or len(str(start)) != 12 or len(str(start + count - 1)) != 12:
        raise ValueError("Начальное значение и последний номер должны содержать 12 цифр")
    target = _make_directory(output_root, f"txt-{count}") / f"codes-{count}.txt"
    write_numbers([str(start + index) for index in range(count)], target)
    return target


def load_codes(path: Path, *, max_lines: int = MAX_LINES, generator="qr") -> list[str]:
    """Accept UTF-8/UTF-8 BOM, LF/CRLF; reject blanks and non-numeric lines."""
    path = Path(path)
    code_module = get_generator(generator)
    with path.open("rb") as stream:
        raw_bytes = stream.read(2 * 1024 * 1024 + 1)
    if len(raw_bytes) > 2 * 1024 * 1024:
        raise ValueError("TXT больше 2 МиБ; максимум 10 000 строк")
    try:
        raw = raw_bytes.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("TXT должен быть сохранён в UTF-8") from exc
    codes = raw.splitlines()
    if not codes:
        raise ValueError("TXT пустой: ожидается один код в каждой строке")
    if len(codes) > max_lines:
        raise ValueError(f"Слишком много строк: {len(codes)}; максимум {max_lines}")
    for index, code in enumerate(codes, 1):
        if not code_module.validate(code):
            raise ValueError(f"Строка {index}: {code_module.input_description}")
    return codes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_batch(input_txt: Path, output_root: Path, *, mode: str = "both",
              settings=None,
              progress: Callable[[str], None] | None = None, cancel=None, events=None,
              generator="qr", engine="reportlab") -> Path:
    """Create actual PDF files and QA evidence, without overwriting old runs.

    Encoding and PDF writing are measured separately from quality checks.
    QA validates all saved vector pages. Raster decoding is sampled when
    pdftoppm is available; missing renderer yields LIMITED, never PASS.
    """
    if mode not in FORMATS:
        raise ValueError(f"Формат должен быть одним из: {', '.join(FORMATS)}")
    code_module = get_generator(generator)
    config = settings if settings is not None else code_module.default_settings()
    code_module.validate_settings(config)
    print_metadata = code_module.describe_settings(config)
    selected_engine = get_engine(engine, generator=generator, mode=mode, colorspace=print_metadata["colorspace"])
    engine_metadata = selected_engine.info().to_dict()
    numbers = load_codes(input_txt, generator=generator)
    progress = progress or (lambda message: None)
    _check_cancel(cancel)
    resource_info = check_resources(output_root, len(numbers))
    selected_engine.prepare()
    directory = _make_directory(output_root, f"pdf-{len(numbers)}")
    raster = shutil.which("pdftoppm") is not None
    copies = 2 if mode == "both" else 1
    samples = len({0, len(numbers) // 2, len(numbers) - 1}) if raster else 0
    tracker = ProgressTracker(len(numbers) * (1 + 2 * copies) + samples * copies + 1, events)
    base = 0
    report = {
        "schema_version": 1, "kind": "txt-batch-pdf", "status": "RUNNING",
        "software_version": __version__,
        "generator": generator, "engine": engine_metadata, "pipeline_contract": 1,
        "mode": mode, "count": len(numbers), "input_filename": Path(input_txt).name,
        "first_code": numbers[0], "last_code": numbers[-1],
        "print": print_metadata,
        "resources": resource_info,
        "files": {}, "seconds": {}, "qa": {}, "errors": [],
    }
    started = time.perf_counter()

    def save_report():
        actual_singles = list((directory / "singles").glob("*.pdf"))
        if actual_singles:
            report["files"]["singles"] = {"directory": "singles", "count": len(actual_singles),
                                             "bytes": sum(p.stat().st_size for p in actual_singles)}
        report["seconds"]["total_including_qa"] = round(time.perf_counter() - started, 6)
        (directory / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "ОТЧЁТ.txt").write_text(human_report(report), encoding="utf-8")

    try:
        _check_cancel(cancel)
        txt_path = directory / "codes.txt"
        write_numbers(numbers, txt_path)
        report["files"]["txt"] = {"name": txt_path.name, "sha256": _sha256(txt_path)}
        progress(f"Читаем {len(numbers)} строк TXT и создаём {code_module.name}")
        tracker.step(f"Кодирование {code_module.progress_name}", 0, len(numbers), base, force=True)
        t = time.perf_counter()
        frames = selected_engine.encode(numbers, cancel=cancel,
            on_progress=lambda done, total: tracker.step(f"Кодирование {code_module.progress_name}", done, total, base))
        if len(frames) != len(numbers) or any(frame.payload != number for frame, number in zip(frames, numbers)):
            raise ValueError("Движок изменил количество или порядок значений относительно TXT")
        report["seconds"]["code_encoding"] = round(time.perf_counter() - t, 6)
        legacy_key = getattr(code_module, "legacy_timing_key", None)
        if legacy_key:
            report["seconds"][legacy_key] = report["seconds"]["code_encoding"]
        base += len(numbers)
        _check_cancel(cancel)

        singles = []
        if mode in ("both", "singles"):
            progress(f"Запись {len(frames)} отдельных одностраничных PDF")
            tracker.step("Отдельные PDF", 0, len(frames), base, force=True)
            t = time.perf_counter()
            folder = directory / "singles"
            folder.mkdir(exist_ok=False)
            digits = max(4, len(str(len(frames))))
            for i, frame in enumerate(frames, 1):
                _check_cancel(cancel)
                label = (frame.payload if frame.payload.isascii() and frame.payload.isdigit() and len(frame.payload) <= 64
                         else hashlib.sha256(frame.payload.encode("utf-8")).hexdigest()[:16])
                path = folder / f"{i:0{digits}d}_{label}.pdf"
                selected_engine.write_pdf([frame], path, config)
                singles.append(path)
                tracker.step("Отдельные PDF", i, len(frames), base)
                if i == 1 or i % 100 == 0 or i == len(frames):
                    progress(f"Отдельные PDF: {i}/{len(frames)}")
            report["seconds"]["write_singles"] = round(time.perf_counter() - t, 6)
            report["files"]["singles"] = {"directory": "singles", "count": len(singles)}
            base += len(frames)

        combined = None
        if mode in ("both", "multipage"):
            _check_cancel(cancel)
            progress(f"Запись одного PDF на {len(frames)} страниц")
            tracker.step("Создание PDF", 0, len(frames), base, force=True)
            t = time.perf_counter()
            combined = directory / f"all-{len(frames)}-pages.pdf"
            selected_engine.write_pdf(frames, combined, config, cancel=cancel,
                      on_progress=lambda done, total: tracker.step("Создание PDF", done, total, base))
            report["seconds"]["write_multipage"] = round(time.perf_counter() - t, 6)
            report["files"]["multipage"] = {"name": combined.name, "bytes": combined.stat().st_size,
                                               "sha256": _sha256(combined), "pages": len(frames)}
            base += len(frames)

        progress("Независимая проверка всех страниц: матрицы, размеры и CMYK")
        qa_start = time.perf_counter()
        if combined is not None:
            _check_cancel(cancel)
            tracker.step("Проверка PDF", 0, len(frames) + samples, base, force=True, unit="проверок")
            report["qa"]["multipage"] = code_module.verify(combined, frames, config, render_samples=raster, cancel=cancel,
                on_progress=lambda done, total: tracker.step("Проверка PDF", done, total, base, unit="проверок"))
            base += len(frames) + samples
        if singles:
            tracker.step("Проверка отдельных PDF", 0, len(singles), base, force=True, unit="проверок")
            sample_indices = sorted({0, len(frames) // 2, len(frames) - 1})
            failures = []
            failed_count = 0
            for i, (path, frame) in enumerate(zip(singles, frames), 1):
                _check_cancel(cancel)
                # All files structural; only 3 independently rendered samples.
                result = code_module.verify(path, [frame], config, render_samples=raster and (i - 1 in sample_indices), cancel=cancel)
                tracker.step("Проверка отдельных PDF", i, len(singles), base, unit="проверок")
                if result["status"] != "PASS":
                    failed_count += 1
                    if len(failures) < 20:
                        failures.append({"index": i, "file": path.name, "errors": result["errors"]})
                if i % 250 == 0 or i == len(singles):
                    progress(f"QA отдельных PDF: {i}/{len(singles)}")
            report["qa"]["singles"] = {"status": "FAIL" if failed_count else "PASS",
                                           "checked": len(singles), "rendered_samples": len(sample_indices) if raster else 0,
                                           "first_failures": failures, "failed_count": failed_count}
        report["seconds"]["quality_checks"] = round(time.perf_counter() - qa_start, 6)
        check_statuses = [v["status"] for v in report["qa"].values()]
        report["status"] = ("INVALID" if "FAIL" in check_statuses else
                            "COMPLETE" if raster else "LIMITED")
        report["qa"]["raster_available"] = raster
        report["qa"]["scope"] = ("Every saved PDF page structurally validated and independently decoded. "
                                  "Raster first/middle/last on multipage and sampled singles, if available.")
        progress(f"Результат: {report['status']}; каталог: {directory}")
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "CANCELLED" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "ERROR"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        progress(f"{report['status']}: {exc}; файлы сохранены: {directory}")
    finally:
        save_report()
    if report["status"] == "COMPLETE":
        tracker.finish(len(numbers))
    return directory
