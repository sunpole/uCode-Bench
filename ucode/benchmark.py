"""M07: explicit stage boundaries, isolated timings, strict qualification gate."""
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import Experiment, QRFrame
from .data import generate_numbers, write_numbers


class Cancelled(RuntimeError):
    pass


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Отменено после текущего шага; сохранённые файлы оставлены")


def _new_directory(output_root, count, prefix="run"):
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone(timedelta(hours=3))).strftime("%Y%m%d-%H%M%S")
    directory = root / f"{prefix}-{count}-{stamp}-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    (directory / "measurements").mkdir()
    return directory


def _json_new(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def _measure(directory, config, kind, output, *, tag, **extra):
    request = directory / "measurements" / f"{tag}.request.json"
    response = directory / "measurements" / f"{tag}.result.json"
    _json_new(request, {"config": config.to_dict(), "kind": kind, "output": str(output), **extra})
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, "-m", "ucode.worker", str(request), str(response)],
                          cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True,
                          timeout=600 if config.count == 1000 else 180, creationflags=flags)
    if not response.exists():
        raise RuntimeError(f"Worker exit={proc.returncode}: {proc.stderr[-2000:]}")
    result = json.loads(response.read_text(encoding="utf-8"))
    if proc.returncode or result["status"] != "OK":
        raise RuntimeError(result.get("error", proc.stderr[-2000:]))
    result.pop("status")
    result["worker_wall_seconds"] = time.perf_counter() - started
    result["path"] = str(output)
    return result


def _artifact(trial, path):
    trial["output_bytes"] = path.stat().st_size
    trial["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_txt(path, config, frames=None):
    numbers = Path(path).read_text(encoding="utf-8").splitlines()
    if numbers != generate_numbers(config):
        raise ValueError("numbers.txt does not match the required numeric sequence")
    if frames is not None and [frame.payload for frame in frames] != numbers:
        raise ValueError("QR payload order does not match numbers.txt")
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _single_qa(paths, frames, config, progress, cancel):
    from .quality import check_pdf
    errors = []
    samples = []
    control = {0, len(paths) // 2, len(paths) - 1}
    for index, (path, frame) in enumerate(zip(paths, frames)):
        _check_cancel(cancel)
        qa = check_pdf(path, [frame], config, render_samples=index in control)
        if qa["status"] != "PASS":
            errors.extend(f"{path.name}: {error}" for error in qa["errors"])
        samples.extend(qa.get("decoded_samples", []))
        if (index + 1) % 50 == 0:
            progress(f"QA отдельных PDF: {index + 1}/{len(paths)}")
    return {"status": "FAIL" if errors else "PASS", "errors": errors, "pages_checked": len(paths),
            "decoded_samples": samples, "render_samples": True}


def _summarize(method, config, sources_ok=True):
    trials = method["trials"]
    if method["status"] in ("SKIPPED", "ERROR"):
        return
    if len(trials) != config.repeats or not sources_ok or any(t["qa"]["status"] != "PASS" for t in trials):
        method["status"] = "INVALID"
        method["reason"] = "Не все три повтора и исходные PDF прошли QA"
    else:
        method["status"] = "PASS"
    if trials:
        times = [t["seconds"] for t in trials]
        method["median_seconds"] = statistics.median(times)
        method["spread_seconds"] = max(times) - min(times)
        method["output_bytes"] = trials[-1]["output_bytes"]
    method["eligible_for_1000"] = bool(config.count == 200 and method["status"] == "PASS"
                                      and method["median_seconds"] < config.threshold_seconds)


def _prepare(directory, config, progress, cancel, stages):
    write_numbers(generate_numbers(config), directory / "numbers.txt")
    _verify_txt(directory / "numbers.txt", config)
    frames_path = None
    for repeat in range(1, config.repeats + 1):
        _check_cancel(cancel)
        progress(f"M02 QR-кодирование: повтор {repeat}/3, {config.count} кодов")
        frames_path = directory / f"frames-{repeat}.json"
        trial = _measure(directory, config, "encode", frames_path, tag=f"encode-{repeat}")
        stages["qr_encoding"].append(trial)
    frames = [QRFrame.from_dict(f) for f in json.loads(frames_path.read_text(encoding="utf-8"))]
    stages["numbers_txt_sha256"] = _verify_txt(directory / "numbers.txt", config, frames)
    paths = []
    for repeat in range(1, config.repeats + 1):
        _check_cancel(cancel)
        progress(f"M04 Отдельные PDF: повтор {repeat}/3, {config.count} файлов")
        target = directory / f"singles-{repeat}"
        trial = _measure(directory, config, "singles", target, tag=f"singles-{repeat}", frames=str(frames_path))
        paths = sorted(target.glob("*.pdf"))
        if len(paths) != config.count:
            raise RuntimeError("Wrong single-file count")
        trial["output_bytes"] = sum(p.stat().st_size for p in paths)
        qa_start = time.perf_counter()
        trial["qa"] = _single_qa(paths, frames, config, progress, cancel)
        trial["qa_seconds"] = time.perf_counter() - qa_start
        trial["generation_total_seconds"] = stages["qr_encoding"][repeat - 1]["seconds"] + trial["seconds"]
        stages["single_files"].append(trial)
    return frames, paths


def create_inputs(output_root, config=Experiment(), progress=None, cancel=None):
    if config.count != 200:
        raise ValueError("Create inputs is limited to the first 200-file stage")
    progress = progress or (lambda message: None)
    from .environment import inspect_environment
    from .qr import encode_numbers
    from .pdf import write_single_files
    directory = _new_directory(output_root, config.count, "inputs")
    write_numbers(generate_numbers(config), directory / "numbers.txt")
    _verify_txt(directory / "numbers.txt", config)
    _check_cancel(cancel)
    progress("Создание 200 QR и отдельных векторных PDF")
    frames = encode_numbers(generate_numbers(config))
    txt_hash = _verify_txt(directory / "numbers.txt", config, frames)
    paths = write_single_files(frames, directory / "singles", config)
    qa = _single_qa(paths, frames, config, progress, cancel)
    _json_new(directory / "inputs.json", {"config": config.to_dict(), "qa": qa, "numbers_txt_sha256": txt_hash, "environment": inspect_environment()})
    if qa["status"] != "PASS":
        raise RuntimeError(f"QA FAIL; детали: {directory / 'inputs.json'}")
    progress(f"Готово: {directory}")
    return directory


def run_experiment(output_root, config=Experiment(), progress=None, cancel=None, allowed_methods=None):
    if config.count == 1000 and not allowed_methods:
        raise ValueError("1000 requires qualifying methods from a verified 200-file report")
    from .environment import inspect_environment
    from .mergers import available_adapters
    from .quality import check_pdf
    from .report import write_reports
    progress = progress or (lambda message: None)
    directory = _new_directory(output_root, config.count)
    started = time.perf_counter()
    result = {"schema_version": 1, "status": "RUNNING", "config": config.to_dict(), "run_directory": str(directory),
              "created_at": datetime.now(timezone(timedelta(hours=3))).isoformat(),
              "environment": inspect_environment(), "methods": [],
              "stages": {"qr_encoding": [], "single_files": [], "direct_pdf": []},
              "notes": ["Acrobat 120 s is a user-provided reference, not measured in this run.",
                        "No warmup; three measured trials. QA, imports, input reads, hashes excluded from method times.",
                        "Imports above means preloaded Python libraries; external CLI/JVM/Node/.NET startup and imports are included.",
                        "Direct includes encoding plus PDF. Merge times exclude source generation; total_seconds includes it.",
                        "RAM: fresh worker OS peak working set incl. imports/input, QA excluded. External sum is upper bound.",
                        "Only QR V1-M numeric 12-digit payloads; no PDF/X certification or physical print scan.",
                        "QA independent numeric decoder rejects damage (no error correction); raster controls first/middle/last."]}
    try:
        frames, inputs = _prepare(directory, config, progress, cancel, result["stages"])
        sources_ok = all(t["qa"]["status"] == "PASS" for t in result["stages"]["single_files"])
        work = [("Direct PDF", "direct", None)] + [(a.name, "merge", a) for a in available_adapters()]
        for name, category, adapter in work:
            _check_cancel(cancel)
            method = {"name": name, "category": category, "status": "PENDING", "reason": "", "trials": [],
                      "median_seconds": None, "spread_seconds": None, "eligible_for_1000": False, "output_bytes": None}
            result["methods"].append(method)
            if allowed_methods is not None and name not in allowed_methods:
                method.update(status="SKIPPED", reason="Не допущен по отчёту этапа 200")
                continue
            if adapter is not None:
                method["probe"] = adapter.probe()
                if not method["probe"]["available"]:
                    method.update(status="SKIPPED", reason=method["probe"].get("reason", "Unavailable"))
                    continue
                if not sources_ok:
                    method.update(status="INVALID", reason="Исходные PDF не прошли QA")
                    continue
            try:
                for repeat in range(1, config.repeats + 1):
                    _check_cancel(cancel)
                    progress(f"{name}: повтор {repeat}/3; {config.count} страниц")
                    tag = f"{category}-{name.lower().replace(' ', '-')}-{repeat}"
                    output = directory / f"{tag}.pdf"
                    extra = {"method": name, "inputs": [str(p) for p in inputs]} if adapter else {}
                    trial = _measure(directory, config, "merge" if adapter else "direct", output, tag=tag, **extra)
                    _artifact(trial, output)
                    progress(f"{name}: QA повтора {repeat}/3")
                    qa_start = time.perf_counter()
                    trial["qa"] = check_pdf(output, frames, config)
                    trial["qa_seconds"] = time.perf_counter() - qa_start
                    if adapter:
                        trial["total_seconds"] = result["stages"]["single_files"][repeat - 1]["generation_total_seconds"] + trial["seconds"]
                    else:
                        trial["total_seconds"] = trial["seconds"]
                        result["stages"]["direct_pdf"].append(trial)
                    method["trials"].append(trial)
                _summarize(method, config, sources_ok if adapter else True)
            except Cancelled:
                method.update(status="INVALID", reason="Запуск отменён до завершения трёх повторов")
                raise
            except Exception as exc:
                method.update(status="ERROR", reason=f"{type(exc).__name__}: {exc}")
                progress(f"{name}: ERROR — {exc}")
        result["status"] = "COMPLETE"
    except Cancelled as exc:
        result.update(status="CANCELLED", error=str(exc))
    except Exception as exc:
        result.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
    finally:
        result["stages"]["overall_seconds"] = time.perf_counter() - started
        write_reports(result, directory)
        progress(f"{result['status']}: {directory / 'report.html'}")
    return directory


def load_qualifying_methods(report_path):
    """Recalculate the gate and verify preserved trial artifacts; fail closed."""
    report_path = Path(report_path).resolve()
    result = json.loads(report_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("status") != "COMPLETE" or result.get("config") != Experiment().to_dict():
        raise ValueError("Нужен завершённый стандартный отчёт на 200 файлов")
    names = []
    from .mergers import available_adapters
    known = {a.name: "merge" for a in available_adapters()}
    known["Direct PDF"] = "direct"
    expected_samples = {(1, "200000000000"), (101, "200000000100"), (200, "200000000199")}
    txt_path = report_path.parent / "numbers.txt"
    if _verify_txt(txt_path, Experiment()) != result["stages"].get("numbers_txt_sha256"):
        raise ValueError("TXT source was changed after verification")
    for method in result.get("methods", []):
        if method.get("status") != "PASS" or not method.get("eligible_for_1000"):
            continue
        trials = method.get("trials", [])
        if len(trials) != 3 or known.get(method.get("name")) != method.get("category"):
            continue
        valid = True
        for trial in trials:
            seconds = trial.get("seconds")
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0 or trial.get("qa", {}).get("status") != "PASS":
                valid = False
                break
            qa = trial["qa"]
            if qa.get("errors") or qa.get("pages_checked") != 200 or qa.get("render_samples") is not True or {(s.get("page"), s.get("payload")) for s in qa.get("decoded_samples", [])} != expected_samples:
                valid = False
                break
            artifact = Path(trial.get("path", "")).resolve()
            if not artifact.is_relative_to(report_path.parent) or not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != trial.get("sha256"):
                valid = False
                break
        if valid and statistics.median(t["seconds"] for t in trials) < 120:
            if method["category"] == "merge":
                sources = result["stages"].get("single_files", [])
                if len(sources) != 3 or not all(t.get("qa", {}).get("status") == "PASS" and t["qa"].get("pages_checked") == 200 and t["qa"].get("render_samples") is True for t in sources):
                    continue
            names.append(method["name"])
    if not names:
        raise ValueError("Нет методов с тремя PASS, медианой <120 с и неизменёнными PDF")
    return names
