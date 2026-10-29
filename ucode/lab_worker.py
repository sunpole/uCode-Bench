"""One isolated CPU/RAM experiment. Imported by name; no GUI at import."""
import json
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from .affinity import apply_affinity, cpu_keys
from .hardware import memory_info
from .resource_monitor import ram_budget, create_owned_job, TreeMonitor

_JOB_HANDLE = None


def code_fingerprint(package=None):
    digest=hashlib.sha256()
    package=Path(package) if package is not None else Path(__file__).parent
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode()); digest.update(path.read_bytes())
    for name in ("merge-pdflib.mjs","PdfBoxMerge.java","pdfsharp/Program.cs","pdfsharp/PdfSharpMerge.csproj"):
        path=package.parent/"scripts"/name
        if path.is_file(): digest.update(name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path); temporary = path.with_name(path.name + ".next-"+uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    for attempt in range(20):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==19: raise
            # Windows readers/AV may briefly deny FILE_SHARE_DELETE.
            time.sleep(.01)


def main(request_path):
    global _JOB_HANDLE
    request_path = Path(request_path).resolve()
    folder = request_path.parent
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = {"status": "RUNNING", "seconds": {}, "errors": [], "warmup": request.get("warmup", False),"runtime_code_root":str(Path(__file__).resolve().parents[1])}
    cancel = threading.Event(); watcher_stop = threading.Event(); monitor = None
    started = time.perf_counter()
    from .progress_series import ProgressSeries
    timeline=ProgressSeries() if request.get("timeline_mode","off")=="on" else None
    def watch():
        while not watcher_stop.wait(.05):
            if (folder / "cancel.flag").exists(): cancel.set()
    watcher = threading.Thread(target=watch, daemon=True)
    try:
        result["affinity"] = apply_affinity(request["cpus"])
        watcher.start()
        if request.get("source_digest") and request["source_digest"] != code_fingerprint():
            raise RuntimeError("Исходники изменились во время серии; сравнение недействительно")
        budget = ram_budget(request["ram_mode"], memory_info()["available_bytes"])
        result["ram_budget"] = budget
        try: _JOB_HANDLE = create_owned_job(budget["budget_bytes"])
        except OSError as exc: raise NotImplementedError("Не удалось создать изолированный Windows job: " + str(exc)) from exc
        result["ram_enforcement"] = ("Windows owned job aggregate commit limit + sampled RSS guard" if os.name == "nt" else
                                     "Sampled tree RSS guard + cooperative cancel; not a kernel RAM quota")
        from .cpu_telemetry import CPUTrace
        telemetry=CPUTrace(request["cpus"],folder/"cpu-samples.csv") if request.get("telemetry_mode","cpu")=="cpu" else None
        monitor = TreeMonitor(cancel, budget,telemetry=telemetry).start()
        # Imports are included in outer trial time, separately from production.
        from .batch import run_batch
        from .execution import ExecutionOptions,execution_plan
        from .hardware import inspect_cpu
        from .print_settings import PrintSettings
        from .engines import get_engine
        if request.get("engine_version") and request["engine_version"] != get_engine().info().version:
            raise RuntimeError("Версия движка изменилась во время серии")
        count = request["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count<1:
            raise ValueError("Количество должно быть положительным")
        from .resources import check_resources
        check_resources(folder,count,streaming=count>10000)
        source = folder / "codes.txt"
        with source.open("x", encoding="utf-8") as stream:
            for i in range(count):
                if i%256==0 and cancel.is_set(): raise InterruptedError("Подготовка базы остановлена")
                stream.write(f"{(200000000000+i)%10**12:012d}\n")
        last_update = [0.0]
        def progress(value):
            if timeline: timeline.observe(value)
            if telemetry: telemetry.set_phase(value["stage"])
            now = time.perf_counter()
            if now-last_update[0] >= .05 or value["percent"] == 100:
                try: atomic_json(folder / "progress.json", value)
                except PermissionError: pass  # optional live observation; final trial/report writes remain mandatory
                last_update[0] = now
        settings = PrintSettings(**{**request.get("print_settings", {}),"pdf_profile":request.get("pdf_profile","standard")})
        workers = request["workers"] if request["backend"] != "serial" else 1
        options=ExecutionOptions(request["backend"],workers,request["batch_size"],
                                 tuple(request["cpus"]) if request["backend"]=="process" else (),request.get("cpu_unit","logical"))
        if request.get("strategy")!="pipeline":
            estimated=execution_plan(options,count,inspect_cpu(),memory_info()["available_bytes"],buffered=count>10000)
            if estimated["required_ram_estimate_bytes"]>budget["budget_bytes"]:
                raise ValueError("Выбранный RAM budget меньше предварительной оценки; уменьшите работников или увеличьте бюджет")
        if request.get("strategy")=="pipeline":
            from .pipeline import run_pipeline_trial
            result.update(run_pipeline_trial(folder,request,settings,cancel,progress,budget,telemetry.bind if telemetry else None))
        elif request.get("strategy")=="split":
            from .batch_strategies import run_split_trial
            result.update(run_split_trial(folder,request,settings,cancel,progress,budget))
        else:
            job = run_batch(source, folder / "jobs", mode=request["output_mode"], settings=settings,
                            execution=options,qa_mode=request.get("qa_mode","full"),activity=request.get("activity","normal"),
                            events=progress, cancel=cancel,temporary_data=request.get("temporary_data",False),
                            execution_observer=telemetry.bind if telemetry else None)
            manifest = json.loads((job / "manifest.json").read_text(encoding="utf-8"))
            result["manifest"] = manifest
            result["job"] = job.relative_to(folder).as_posix()
            result["pdf_bytes"]=manifest["files"].get("multipage",{}).get("bytes",0)+manifest["files"].get("singles",{}).get("bytes",0)
            result["status"] = manifest["status"]
            result["errors"].extend(manifest.get("errors", []))
            if manifest["status"] == "LIMITED" and request.get("qa_mode","full")=="full":
                result["errors"].append("Нет растрового QA; этот вариант не участвует в рейтинге")
            if manifest["status"] == "INVALID": result["errors"].append("QA FAIL; этот вариант не участвует в рейтинге")
            result["seconds"] = {"production": manifest["seconds"].get("production_until_pdf_closed"),
                                 "total_including_qa": manifest["seconds"]["total_including_qa"],
                                 **{k: v for k, v in manifest["seconds"].items() if k not in ("total_including_qa",)}}
            requested_keys = cpu_keys(request["cpus"])
            for cpus in manifest["execution"].get("worker_affinity", {}).values():
                valid=bool(cpus) and (len(cpus)==1 and set(cpu_keys(cpus)).issubset(set(requested_keys)) if options.cpus else cpu_keys(cpus)==requested_keys)
                if not valid:
                    result["status"] = "INVALID"
                    result["errors"].append("Worker не подтвердил наследование CPU affinity")
    except (NotImplementedError, ValueError) as exc:
        result.update(status="SKIPPED", errors=[str(exc)])
    except Exception as exc:
        result.update(status="ERROR", errors=[type(exc).__name__ + ": " + str(exc)])
    finally:
        watcher_stop.set()
        if watcher.ident is not None: watcher.join(1)
        if monitor is not None:
            result["memory"] = monitor.finish()
            if monitor.reason:
                result["status"] = "RESOURCE_LIMIT"
                result["errors"].append(monitor.reason)
        try: result["storage_total_bytes"]=sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
        except OSError: result["storage_total_bytes"]=None
        result["seconds"]["worker_wall"] = time.perf_counter() - started
        if timeline: result["timeline"]=timeline.data(result["status"])
        atomic_json(folder / "trial.json", result)
    return 0 if result["status"] in ("COMPLETE","UNVERIFIED","LIMITED") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
