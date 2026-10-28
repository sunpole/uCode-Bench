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
from .generation_plan import build_plan
from .progress import ProgressTracker
from .resources import check_resources
from .hardware import inspect_hardware
from .execution import ExecutionOptions, execution_plan, encode_values
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
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_LINES:
        raise ValueError("Количество номеров: целое число от 1 до 10 000")
    if isinstance(start, bool) or not isinstance(start, int) or start < 0 or len(str(start)) != 12 or len(str(start + count - 1)) != 12:
        raise ValueError("Начальное значение и последний номер должны содержать 12 цифр")
    target = _make_directory(output_root, f"txt-{count}") / f"codes-{count}.txt"
    write_numbers([str(start + index) for index in range(count)], target)
    return target


def iter_codes(path: Path, *, max_lines=MAX_LINES, max_bytes=2 * 1024 * 1024, generator="qr", cancel=None):
    """Bounded line reader. None limits enable a caller-owned streaming scan.

    Production still enforces 10000 total pages. No whole-file read is needed
    for validation; a single source line cannot exceed 4096 bytes.
    """
    code_module = get_generator(generator)
    if max_bytes is not None and Path(path).stat().st_size > max_bytes:
        raise ValueError("TXT превышает допустимый размер; для большой базы нужен потоковый запуск")
    seen_bytes = index = 0
    with Path(path).open("rb") as stream:
        while True:
            _check_cancel(cancel)
            raw = stream.readline(4097)
            if not raw:
                break
            index += 1
            seen_bytes += len(raw)
            if max_bytes is not None and seen_bytes > max_bytes:
                raise ValueError("TXT превышает допустимый размер")
            if len(raw) > 4096:
                raise ValueError(f"Строка {index}: превышена допустимая длина")
            if max_lines is not None and index > max_lines:
                raise ValueError(f"Слишком много строк: максимум {max_lines}")
            try:
                code = raw.removesuffix(b"\n").removesuffix(b"\r").decode("utf-8-sig" if index == 1 else "utf-8")
            except UnicodeError as exc:
                raise ValueError("TXT должен быть сохранён в UTF-8") from exc
            if not code_module.validate(code):
                raise ValueError(f"Строка {index}: {code_module.input_description}")
            yield code
    if index == 0:
        raise ValueError("TXT пустой: ожидается один код в каждой строке")


def load_codes(path: Path, *, max_lines: int = MAX_LINES, generator="qr", cancel=None) -> list[str]:
    """Compatible bounded list API; iter_codes supports incremental validation."""
    return list(iter_codes(path, max_lines=max_lines, generator=generator, cancel=cancel))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_batch(input_txt: Path, output_root: Path, *, mode: str = "both",
              settings=None,
              progress: Callable[[str], None] | None = None, cancel=None, events=None,
              generator="qr", engine="reportlab", copies_per_value=1, duplicate_policy="preserve", execution=None,
              qa_mode="full",activity="normal") -> Path:
    """Create actual PDF files and QA evidence, without overwriting old runs.

    Encoding and PDF writing are measured separately from quality checks.
    QA validates all saved vector pages. Raster decoding is sampled when
    pdftoppm is available; missing renderer yields LIMITED, never PASS.
    """
    if mode not in FORMATS:
        raise ValueError(f"Формат должен быть одним из: {', '.join(FORMATS)}")
    if qa_mode not in ("full","vector","deferred") or activity not in ("normal","minimal"):
        raise ValueError("Неверные режимы проверки/активности")
    code_module = get_generator(generator)
    config = settings if settings is not None else code_module.default_settings()
    code_module.validate_settings(config)
    print_metadata = code_module.describe_settings(config)
    selected_engine = get_engine(engine, generator=generator, mode=mode, colorspace=print_metadata["colorspace"])
    engine_metadata = selected_engine.info().to_dict()
    source_numbers = load_codes(input_txt, generator=generator, cancel=cancel)
    plan = build_plan(source_numbers, copies_per_value=copies_per_value, duplicate_policy=duplicate_policy,
                      types=(generator,))
    progress = progress or (lambda message: None)
    _check_cancel(cancel)
    resource_info = check_resources(output_root, plan.total_codes)
    numbers = list(plan.iter_values())
    encoding_numbers = list(dict.fromkeys(plan.selected_values))
    hardware = inspect_hardware(output_root)
    execution = execution or ExecutionOptions()
    if execution.backend not in selected_engine.info().execution_modes:
        raise ValueError("Движок не поддерживает выбранный способ выполнения")
    execution_info = execution_plan(execution, len(encoding_numbers), hardware["cpu"], hardware["ram"]["available_bytes"])
    if getattr(config,"pdf_profile","standard")=="compact":
        getattr(selected_engine,"prepare_encoding",selected_engine.prepare)()
    else: selected_engine.prepare()
    directory = _make_directory(output_root, f"pdf-{len(numbers)}")
    raster = qa_mode=="full" and shutil.which("pdftoppm") is not None
    copies = 2 if mode == "both" else 1
    samples = len({0, len(numbers) // 2, len(numbers) - 1}) if raster else 0
    qa_units=0 if qa_mode=="deferred" else (len(numbers)+samples)*copies
    tracker = ProgressTracker(len(encoding_numbers) + len(numbers)*copies + qa_units + 1, events,
                              min_interval=.5 if activity=="minimal" else .05,emit_every=64 if activity=="minimal" else 1)
    base = 0
    report = {
        "schema_version": 1, "kind": "txt-batch-pdf", "status": "RUNNING",
        "software_version": __version__,
        "generator": generator, "engine": engine_metadata, "pipeline_contract": 1,
        "mode": mode, "count": len(numbers), "input_filename": Path(input_txt).name,
        "generation": {**plan.to_dict(), "encoding_values_planned": len(encoding_numbers), "encoded_values": 0},
        "first_code": numbers[0], "last_code": numbers[-1],
        "print": print_metadata,
        "resources": resource_info,
        "qa_mode":qa_mode,"activity":activity,"hash_policy":"normal" if activity=="normal" else "omitted from production",
        "hardware": hardware, "execution": execution_info,
        "files": {}, "seconds": {}, "qa": {}, "errors": [],
    }
    started = time.perf_counter()

    def save_report():
        actual_singles = list((directory / "singles").glob("*.pdf"))
        if actual_singles:
            report["files"]["singles"] = {"directory": "singles", "count": len(actual_singles),
                                             "bytes": sum(p.stat().st_size for p in actual_singles)}
        report["generation"]["pdf_pages_written"] = len(actual_singles) + report["files"].get("multipage", {}).get("pages", 0)
        report["seconds"]["total_including_qa"] = round(time.perf_counter() - started, 6)
        (directory / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "ОТЧЁТ.txt").write_text(human_report(report), encoding="utf-8")

    try:
        _check_cancel(cancel)
        txt_path = directory / "codes.txt"
        original = directory / "source-codes.txt"
        if activity=="normal":
            write_numbers(source_numbers, original)
            report["files"]["source_txt"] = {"name": original.name, "sha256": _sha256(original)}
        write_numbers(numbers, txt_path)
        report["files"]["txt"] = {"name": txt_path.name}
        if activity=="normal": report["files"]["txt"]["sha256"]=_sha256(txt_path)
        progress(f"Читаем {len(numbers)} строк TXT и создаём {code_module.name}")
        tracker.step(f"Кодирование {code_module.progress_name}", 0, len(encoding_numbers), base, force=True)
        t = time.perf_counter()
        encoded, _ = encode_values(encoding_numbers, engine_key=engine, options=execution,
            encoding_only=activity=="minimal" or getattr(config,"pdf_profile","standard")=="compact",
            selected_engine=selected_engine, generator=generator, mode=mode, colorspace=print_metadata["colorspace"],
            plan=execution_info.copy(), metadata=report["execution"], cancel=cancel,
            on_progress=lambda done, total: tracker.step(f"Кодирование {code_module.progress_name}", done, total, base))
        if len(encoded) != len(encoding_numbers) or any(frame.payload != number for frame, number in zip(encoded, encoding_numbers)):
            raise ValueError("Движок изменил количество или порядок значений относительно TXT")
        cache = {frame.payload: frame for frame in encoded}
        report["generation"]["encoded_values"] = len(encoded)
        frames = [cache[number] for number in numbers]
        report["seconds"]["code_encoding"] = round(time.perf_counter() - t, 6)
        legacy_key = getattr(code_module, "legacy_timing_key", None)
        if legacy_key:
            report["seconds"][legacy_key] = report["seconds"]["code_encoding"]
        base += len(encoding_numbers)
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
            report["files"]["multipage"] = {"name": combined.name, "bytes": combined.stat().st_size,"pages":len(frames)}
            if activity=="normal": report["files"]["multipage"]["sha256"]=_sha256(combined)
            base += len(frames)

        report["seconds"]["production_until_pdf_closed"] = round(time.perf_counter() - started, 6)
        if qa_mode=="deferred":
            report["qa"]={"status":"NOT_RUN","scope":"Explicitly deferred; no quality PASS claimed"}
            report["status"]="UNVERIFIED"
            report["seconds"]["quality_checks"]=0.0
        else:
            from .audit import verify_outputs,qa_status
            progress("Независимая проверка всех страниц: матрицы, размеры и CMYK")
            qa_start=time.perf_counter(); previous=[None,0,base]
            def observe(stage,done,total):
                if previous[0] is not None and stage!=previous[0]: previous[2]+=previous[1]
                previous[0],previous[1]=stage,total
                tracker.step(stage,done,total,previous[2],unit="проверок")
            report["qa"]=verify_outputs(directory,frames,config,mode,code_module=code_module,render_samples=raster,cancel=cancel,on_progress=observe)
            report["seconds"]["quality_checks"]=round(time.perf_counter()-qa_start,6)
            report["status"]=qa_status(report["qa"],raster)
        progress(f"Результат: {report['status']}; каталог: {directory}")
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "CANCELLED" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "ERROR"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        progress(f"{report['status']}: {exc}; файлы сохранены: {directory}")
    finally:
        save_report()
    if report["status"]=="COMPLETE" or (qa_mode in ("vector","deferred") and report["status"] in ("LIMITED","UNVERIFIED")):
        tracker.finish(len(numbers),"Создано без проверки" if qa_mode=="deferred" else "Готово")
    return directory
