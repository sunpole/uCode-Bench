from .distribution import module_command
"""User-started CPU/RAM experiment matrix, separate from historical gates."""
from dataclasses import asdict, dataclass, field
import itertools
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

from .affinity import select_cpus
from .batch import _make_directory
from .hardware import inspect_hardware
from .lab_report import summarize_trials, write_reports
from .lab_worker import atomic_json, code_fingerprint
from .engines import get_engine

PROJECT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LabConfig:
    counts: tuple = (200,)
    cpu_counts: tuple = ("1", "2", "4", "6", "12", "all-2", "all")
    cpu_units: tuple = ("logical",)
    backends: tuple = ("serial", "process", "thread")
    ram_modes: tuple = ("auto",)
    repeats: int = 3
    warmups: int = 0
    batch_size: int = 1
    workers: int = 0
    output_mode: str = "multipage"
    print_settings: dict = field(default_factory=dict)
    pdf_profiles: tuple = ("standard",)
    activity_modes: tuple = ("normal",)
    qa_mode: str = "full"
    telemetry_modes: tuple = ("cpu",)
    timeline_mode: str = "off"

    def __post_init__(self):
        if self.timeline_mode not in ("on","off"): raise ValueError("XY: on/off")
        if self.qa_mode not in ("full","vector","deferred"): raise ValueError("Неверный режим проверки PDF")
        axes = (self.counts, self.cpu_counts, self.cpu_units, self.backends, self.ram_modes,self.pdf_profiles,self.activity_modes,self.telemetry_modes)
        if any(not isinstance(axis, tuple) or not axis or len(axis) > 64 for axis in axes):
            raise ValueError("Списки лаборатории должны содержать 1–64 значения")
        if any(isinstance(n, bool) or not isinstance(n, int) or n<1 for n in self.counts):
            raise ValueError("Количество: положительное целое")
        if any(str(n) not in ("all", "all-2") and not (str(n).isascii() and str(n).isdigit() and int(n)>0) for n in self.cpu_counts):
            raise ValueError("CPU: числа, all, all-2")
        if set(self.cpu_units) - {"logical", "physical"} or set(self.backends) - {"serial", "process", "thread"}:
            raise ValueError("Неизвестные CPU units/backend")
        if set(self.pdf_profiles)-{"standard","compact"} or set(self.activity_modes)-{"normal","minimal"}:
            raise ValueError("Неизвестные PDF/overhead профили")
        if set(self.telemetry_modes)-{"off","cpu"}: raise ValueError("Неверный режим замеров CPU")
        if any(mode not in ("auto", "50%", "80%", "max") and not (isinstance(mode,str) and mode.endswith("MiB") and mode[:-3].isdigit()) for mode in self.ram_modes):
            raise ValueError("RAM: auto, 50%, 80%, max, число с MiB")
        for value, minimum, maximum in ((self.repeats,1,10),(self.warmups,0,3),(self.batch_size,1,1000)):
            if isinstance(value,bool) or not isinstance(value,int) or not minimum <= value <= maximum:
                raise ValueError("Неверные повторы/прогрев/партия/работники")
        if isinstance(self.workers,bool) or not isinstance(self.workers,int) or self.workers < 0:
            raise ValueError("Работники: 0=по числу выбранных CPU или положительное целое")
        if self.output_mode not in ("multipage", "singles", "both"):
            raise ValueError("Неизвестный PDF output mode")
        from .print_settings import PrintSettings
        try:
            if not isinstance(self.print_settings,dict): raise TypeError("print_settings must be a dict")
            PrintSettings(**self.print_settings)
        except (ValueError,TypeError) as exc:
            raise ValueError("Неверные настройки PDF лаборатории: "+str(exc)) from exc
        if math.prod(len(axis) for axis in axes) > 4096:
            raise ValueError("Серия больше 4096 вариантов; сократите выбранные списки")


def build_cases(config, cpu):
    rows = []; equivalent = {}
    for count, choice, unit, backend, ram,pdf_profile,activity,telemetry in itertools.product(config.counts, config.cpu_counts, config.cpu_units, config.backends, config.ram_modes,config.pdf_profiles,config.activity_modes,config.telemetry_modes):
        row = {"id": f"C{len(rows)+1:04d}", "count": count, "cpu_choice": str(choice), "cpu_unit": unit,
               "backend": backend, "ram_mode": ram,"pdf_profile":pdf_profile,"activity":activity, "cpus": [], "workers": 1,
               "status": "PENDING", "reason": "", "trials": [],"qa_mode":config.qa_mode,"telemetry_mode":telemetry}
        try:
            row["cpus"] = select_cpus(cpu, unit, choice)
            row["workers"] = 1 if backend == "serial" else config.workers or len(row["cpus"])
            if row["workers"] > len(row["cpus"]): raise ValueError("Работников больше выбранных CPU")
            if os.name == "nt" and len({item["group"] for item in row["cpus"]}) > 1:
                raise ValueError("Windows multi-group forced affinity пока не поддерживается")
            identity=(count,unit,tuple((item["group"],item["logical"]) for item in row["cpus"]),backend,ram,row["workers"],pdf_profile,activity,telemetry)
            if identity in equivalent:
                row["equivalent_case"]=equivalent[identity]
                raise ValueError("Эквивалентный CPU-набор уже проверяется в "+equivalent[identity])
            equivalent[identity]=row["id"]
        except ValueError as exc:
            row.update(status="SKIPPED", reason=str(exc))
        rows.append(row)
    return rows


def preview(config, hardware):
    cases = build_cases(config, hardware["cpu"])
    ready = [case for case in cases if case["status"] != "SKIPPED"]
    repeats = config.repeats + config.warmups
    return {"configurations": len(cases), "eligible": len(ready), "skipped": len(cases)-len(ready),
            "runs": len(ready)*repeats,
            "estimated_disk_bytes": 256*1024**2 + sum(case["count"] for case in ready)*repeats*16000*(2 if config.output_mode=="both" else 1),
            "time_estimate": None}


def _run_trial(folder, request, cancel, on_progress, timeout=None, cancel_grace=15, *, report_only=False):
    folder.mkdir(parents=True, exist_ok=False)
    atomic_json(folder / "request.json", request)
    env = dict(os.environ, PYTHONUTF8="1")
    args = module_command("ucode.lab_worker",(folder/"request.json").resolve())
    if request.get("runtime_root"): env["UCODE_ASSET_ROOT"]=request["asset_root"]
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {"start_new_session": True}
    started = time.perf_counter(); cancelling = None; seen = None; timed_out = False
    with (folder / "worker.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(args, cwd=request.get("runtime_root",PROJECT), env=env, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        try:
            while process.poll() is None:
                elapsed = time.perf_counter()-started
                stopping = cancel is not None and cancel.is_set()
                if timeout is not None and elapsed > timeout: timed_out = True
                if stopping or timed_out:
                    if cancelling is None:
                        (folder/"cancel.flag").write_text("stop", encoding="ascii"); cancelling=time.monotonic()
                    if time.monotonic()-cancelling > cancel_grace:
                        if os.name=="nt": process.terminate()
                        else: os.killpg(process.pid, signal.SIGKILL)
                        break
                path=folder/"progress.json"
                if path.exists() and on_progress:
                    try:
                        stamp=path.stat().st_mtime_ns
                        if stamp != seen: on_progress(json.loads(path.read_text(encoding="utf-8"))); seen=stamp
                    except (OSError, ValueError): pass
                time.sleep(.05)
            process.wait(timeout=5)
        finally:
            if process.poll() is None:
                if os.name=="nt": process.kill()
                else: os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    result_path=folder/"trial.json"
    if result_path.exists():
        result=json.loads(result_path.read_text(encoding="utf-8"))
    else:
        result={"status": "CANCELLED" if cancelling is not None else "ERROR", "seconds": {},
                "errors": [f"Нет завершённого trial.json, exitcode={process.returncode}"], "warmup": request["warmup"]}
    result["seconds"]["launcher_wall"] = time.perf_counter()-started
    if timed_out:
        result.update(status="ERROR",errors=[f"Превышен таймаут варианта {timeout} с"])
    if process.returncode != 0 and result["status"] in ("COMPLETE","UNVERIFIED","LIMITED"):
        result.update(status="ERROR", errors=["Успешный JSON при ненулевом exitcode рабочего процесса"])
    result["folder"] = folder.name
    if report_only:
        from .test_retention import discard_trial_pdfs
        result["retention"] = discard_trial_pdfs(folder)
        atomic_json(folder/"trial.json",result)
    return result


from .test_archive import archived_test


@archived_test
def run_lab(output_root, config, *, cancel=None, events=None, progress=None, report_only=False):
    hardware = inspect_hardware(output_root)
    cases = build_cases(config, hardware["cpu"])
    plan = preview(config, hardware)
    folder = _make_directory(output_root, "lab")
    data = {"schema_version": 1, "kind": "resource-lab", "status": "RUNNING", "config": asdict(config),
            "hardware": hardware, "source_digest": code_fingerprint(), "python": platform.python_version(),
            "engine": get_engine().info().to_dict(), "gil_enabled": getattr(sys,"_is_gil_enabled",lambda:True)(),
            "os": platform.system()+" "+platform.release(), "preview": plan, "cases": cases, "errors": []}
    from .print_settings import PrintSettings
    profile={"output_mode":config.output_mode,"print_settings":asdict(PrintSettings(**config.print_settings)),
             "source_digest":data["source_digest"],"python":data["python"],"engine":data["engine"],"gil_enabled":data["gil_enabled"],
             "timing":"production before QA; operation includes selected QA mode; wrapper separately", "metrics_interval_seconds":.05,
             "pdf_profiles":config.pdf_profiles,"activity_modes":config.activity_modes,"qa_mode":config.qa_mode,"telemetry_modes":config.telemetry_modes}
    data["comparison_profile"]=profile
    data["comparison_profile_hash"]=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
    from .frozen_runtime import snapshot_runtime,assert_trial_integrity
    frozen=snapshot_runtime(folder)
    data["runtime_snapshot"]={"folder":".runtime","source_digest":frozen["source_digest"]}
    data["source_digest"]=frozen["source_digest"]
    started=time.perf_counter(); completed=0; total=max(1,plan["runs"])
    try:
        if hardware["disk"]["free_bytes"] < plan["estimated_disk_bytes"]:
            raise ValueError("Недостаточно места для всей серии; сократите размеры, повторы или выбранные оси")
        for case in cases:
            if cancel is not None and cancel.is_set(): raise InterruptedError("Серия остановлена")
            if case["status"]=="SKIPPED": continue
            case["status"]="RUNNING"
            for repeat in range(config.warmups+config.repeats):
                if cancel is not None and cancel.is_set(): raise InterruptedError("Серия остановлена")
                warmup=repeat<config.warmups
                if progress: progress(f"{case['id']} · {case['count']} кодов · CPU {case['cpu_choice']} {case['cpu_unit']} · {case['backend']} · {case['pdf_profile']}/{case['activity']} · {'прогрев' if warmup else 'повтор'} {repeat+1}")
                request={"count": case["count"], "cpus": case["cpus"], "backend": case["backend"],"cpu_unit":case["cpu_unit"],
                         **frozen,"telemetry_mode":case["telemetry_mode"],
                         "qa_mode":config.qa_mode,"timeline_mode":config.timeline_mode,
                         "workers": case["workers"], "batch_size": config.batch_size, "ram_mode": case["ram_mode"],
                         "output_mode": config.output_mode, "print_settings": config.print_settings, "warmup": warmup,
                         "pdf_profile":case["pdf_profile"],"activity":case["activity"],
                         "source_digest": data["source_digest"], "engine_version": data["engine"]["version"]}
                def update(value):
                    if events:
                        event=dict(value); event["percent"]=min(99.9,100*(completed+value["percent"]/100)/total)
                        event["stage"]=case["id"]+" · "+value["stage"]
                        event.update(run_index=completed+1,runs_total=plan["runs"],repeat_index=repeat+1,
                                     cpu_count=len(case["cpus"]),cpu_unit=case["cpu_unit"])
                        events(event)
                if cancel is not None and cancel.is_set(): raise InterruptedError("Серия остановлена")
                trial = _run_trial(folder/"trials"/f"{case['id']}-{repeat+1:02d}", request, cancel, update, report_only=report_only)
                trial["relative_folder"] = "trials/"+trial["folder"]
                case["trials"].append(trial); completed+=1
                assert_trial_integrity(trial)
                if trial["status"]=="CANCELLED": raise InterruptedError("Серия остановлена")
                if warmup and trial["status"]!={"full":"COMPLETE","deferred":"UNVERIFIED","vector":"LIMITED"}[config.qa_mode]: break
                write_reports(folder,data)
            case["summary"]=summarize_trials(case["trials"],config.repeats,case["count"],qa_mode=config.qa_mode)
            case["status"]=case["summary"]["status"]
            case["reason"]="; ".join(str(message) for trial in case["trials"] for message in trial.get("errors",[]))
            write_reports(folder,data)
        statuses={case["status"] for case in cases}
        expected={"full":"PASS","deferred":"UNVERIFIED","vector":"LIMITED"}[config.qa_mode]
        data["status"]=("COMPLETE" if config.qa_mode=="full" else expected) if expected in statuses and statuses<={expected,"SKIPPED"} else "SKIPPED" if statuses=={"SKIPPED"} else "INVALID"
    except (InterruptedError,KeyboardInterrupt) as exc:
        data.update(status="CANCELLED",errors=[str(exc)])
    except Exception as exc:
        data.update(status="ERROR",errors=[type(exc).__name__+": "+str(exc)])
    finally:
        for case in cases:
            if case["status"] in ("PENDING","RUNNING"):
                case["status"]="CANCELLED" if data["status"]=="CANCELLED" else "NOT_RUN"
                case["summary"]=summarize_trials(case["trials"],config.repeats,case["count"],qa_mode=config.qa_mode)
        data["elapsed_seconds"]=time.perf_counter()-started
        from .trial_results import write_trial_results
        write_trial_results(folder,data)
        write_reports(folder,data)
    if events and data["status"] in ("COMPLETE","UNVERIFIED","LIMITED"):
        events({"stage":"Серия создана без проверки" if data["status"]=="UNVERIFIED" else "Серия завершена", "done":completed,"total":total,"percent":100,
                "elapsed":data["elapsed_seconds"],"speed":0,"average_speed":0,"unit":"прогонов"})
    return folder
