"""Bounded, read-only history of resource-lab reports. No reruns or cross-run ranking."""
from dataclasses import dataclass
from datetime import datetime,timezone
import itertools
import json
import math
from pathlib import Path,PureWindowsPath

from .lab_report import summarize_trials
from .qa_policy import LIMITED_STATUS,limited_trial

MAX_REPORT_BYTES=32*1024**2
MAX_INDEX_BYTES=32*1024**2
MAX_INDEX_REPORTS=100


@dataclass(frozen=True)
class HistoryEntry:
    path: Path
    date: str
    status: str
    counts: str
    note: str=""


def _stop(cancel):
    if cancel is not None and cancel.is_set(): raise InterruptedError("Чтение истории остановлено")


def _positive(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>0


def _json(path,limit,cancel):
    _stop(cancel)
    with Path(path).open("rb") as stream: raw=stream.read(limit+1)
    if len(raw)>limit: raise ValueError(f"Отчёт больше разрешённых {limit//1024} КиБ; откройте HTML")
    def invalid(value): raise ValueError("Недопустимое число JSON: "+value)
    try: value=json.loads(raw.decode("utf-8-sig"),parse_constant=invalid)
    except RecursionError as exc: raise ValueError("Слишком сложная структура JSON") from exc
    _stop(cancel)
    if not isinstance(value,dict) or value.get("kind")!="resource-lab" or value.get("schema_version")!=1:
        raise ValueError("Это не поддерживаемый отчёт лаборатории CPU / PDF")
    config=value.get("config"); cases=value.get("cases")
    if not isinstance(config,dict) or not isinstance(cases,list) or len(cases)>4096:
        raise ValueError("Неверная структура или слишком много вариантов")
    if config.get("output_mode") not in ("multipage","singles","both"):
        raise ValueError("Неизвестный режим PDF в отчёте")
    repeats=config.get("repeats")
    if config.get("qa_mode","full") not in ("full","vector","deferred"): raise ValueError("Неизвестный режим проверки PDF")
    if isinstance(repeats,bool) or not isinstance(repeats,int) or not 1<=repeats<=10:
        raise ValueError("Неверное количество замеров")
    for case in cases:
        if not isinstance(case,dict) or not isinstance(case.get("trials"),list) or len(case["trials"])>13:
            raise ValueError("Неверная структура повторов")
        count=case.get("count")
        if isinstance(count,bool) or not isinstance(count,int) or count<1:
            raise ValueError("Неверный тираж в отчёте")
        for field in ("id","status","backend","cpu_unit","pdf_profile","activity"):
            if field in case and not isinstance(case[field],str): raise ValueError("Неверное поле варианта: "+field)
    return value


def _quality_pass(trial,count,mode):
    if not isinstance(trial,dict) or trial.get("status")!="COMPLETE": return False
    manifest=trial.get("manifest",{})
    if not isinstance(manifest,dict) or manifest.get("status")!="COMPLETE" or manifest.get("count")!=count: return False
    if manifest.get("mode")!=mode or manifest.get("qa_mode","full")!="full": return False
    qa=manifest.get("qa",{})
    if not isinstance(qa,dict) or not qa.get("raster_available"): return False
    required=("multipage","singles") if mode=="both" else (mode,)
    return all(isinstance(qa.get(kind),dict) and qa[kind].get("status")=="PASS" for kind in required)


def case_result(case,config):
    """Recompute medians from complete, non-warmup trials; QA is saved evidence."""
    rows=case["trials"]
    counted=[trial for trial in rows if isinstance(trial,dict) and not trial.get("warmup")]
    qa_mode=config.get("qa_mode","full")
    if qa_mode in LIMITED_STATUS and case.get("status")==LIMITED_STATUS[qa_mode] and len(counted)==config["repeats"]:
        if all(limited_trial(trial,case["count"],qa_mode,config["output_mode"]) for trial in rows):
            summary=summarize_trials(rows,config["repeats"],case["count"],qa_mode=qa_mode)
            return {"status":LIMITED_STATUS[qa_mode],"summary":summary,
                    "reason":"Проверка PDF явно выключена; качество не подтверждено" if qa_mode=="deferred" else "Сохранена только частичная проверка PDF"}
    valid=(qa_mode=="full" and case.get("status")=="PASS" and len(counted)==config["repeats"] and
           all(_quality_pass(trial,case["count"],config["output_mode"]) and
               isinstance(trial.get("seconds"),dict) and
               _positive(trial["seconds"].get("production")) and
               _positive(trial["seconds"].get("total_including_qa")) and
               trial["seconds"]["total_including_qa"]+1e-6>=trial["seconds"]["production"] for trial in counted) and
           all(isinstance(trial,dict) and trial.get("status")=="COMPLETE" for trial in rows))
    if valid:
        summary=summarize_trials(rows,config["repeats"],case["count"])
        return {"status":"PASS","summary":summary,"reason":"Сохранённая полная QA; повторная проверка PDF не выполнялась"}
    status=case.get("status","UNKNOWN")
    return {"status":"UNVERIFIED" if status=="PASS" else status,"summary":{},
            "reason":str(case.get("reason") or "Неполные замеры или нет подтверждения полной QA")[:240]}


def read_run(path,*,cancel=None,max_bytes=MAX_REPORT_BYTES):
    path=Path(path).resolve(strict=True)
    data=_json(path,max_bytes,cancel)
    results=[]
    for case in data["cases"]:
        _stop(cancel)
        results.append({"case":case,**case_result(case,data["config"])})
    return {"path":path,"data":data,"results":results}


def scan_history(root,*,cancel=None):
    root=Path(root).resolve()
    _stop(cancel)
    if not root.exists(): return {"entries":[],"limited":False}
    if not root.is_dir(): raise ValueError("Выберите папку результатов лаборатории")
    candidates=[root/"lab.json"] if (root/"lab.json").is_file() else list(itertools.islice(root.glob("lab-*/lab.json"),1001))
    candidates=[path for path in candidates if path.resolve().is_relative_to(root)]
    candidates.sort(key=lambda path:path.stat().st_mtime,reverse=True)
    limited=len(candidates)>MAX_INDEX_REPORTS; entries=[]; budget=MAX_INDEX_BYTES
    for path in candidates[:MAX_INDEX_REPORTS]:
        _stop(cancel)
        try:
            info=path.stat(); date=datetime.fromtimestamp(info.st_mtime,timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
            if info.st_size>min(budget,2*1024**2):
                entries.append(HistoryEntry(path,date,"ОТКРОЙТЕ","—","Подробности загружаются по выбору запуска")); continue
            budget-=info.st_size
            run=read_run(path,cancel=cancel,max_bytes=min(MAX_REPORT_BYTES,info.st_size+1))
            counts=", ".join(map(str,sorted({row["case"]["count"] for row in run["results"]})))
            status=str(run["data"].get("status","UNKNOWN"))
            if status=="COMPLETE" and (not any(row["status"]=="PASS" for row in run["results"]) or
                                      any(row["status"] not in ("PASS","SKIPPED") for row in run["results"])):
                status="UNVERIFIED"
            entries.append(HistoryEntry(path,date,status,counts,
                f"Вариантов: {len(run['results'])}; с сохранённой полной QA: {sum(row['status']=='PASS' for row in run['results'])}"))
        except InterruptedError: raise
        except (OSError,ValueError,TypeError,KeyError) as exc:
            entries.append(HistoryEntry(path,"—","ОШИБКА","—",str(exc)[:240]))
    _stop(cancel)
    return {"entries":entries,"limited":limited}


def artifact_path(run_file,relative):
    """Reject absolute paths, traversal and symlink/junction escapes from a run."""
    if not isinstance(relative,str) or not relative or len(relative)>4096: raise ValueError("Неверная ссылка на файл")
    win=PureWindowsPath(relative); rel=Path(relative)
    if rel.is_absolute() or win.drive or ".." in rel.parts or ".." in win.parts:
        raise ValueError("Файл находится за пределами выбранного запуска")
    base=Path(run_file).resolve(strict=True).parent
    path=(base/rel).resolve(strict=True)
    if not path.is_relative_to(base): raise ValueError("Файл находится за пределами выбранного запуска")
    return path


def pdf_for_case(run_file,case):
    for trial in case.get("trials",[]):
        if not isinstance(trial,dict) or trial.get("warmup"): continue
        manifest=trial.get("manifest",{})
        if not isinstance(manifest,dict): continue
        try:
            trial_dir=artifact_path(run_file,trial["relative_folder"])
            job=artifact_path(run_file,(trial_dir.relative_to(Path(run_file).resolve().parent)/trial["job"]).as_posix())
            files=manifest.get("files",{})
            if not isinstance(files,dict): continue
            if files.get("multipage"):
                if not isinstance(files["multipage"],dict): continue
                relative=(job.relative_to(Path(run_file).resolve().parent)/files["multipage"]["name"]).as_posix()
                pdf=artifact_path(run_file,relative)
                if pdf.is_file() and pdf.suffix.lower()==".pdf": return pdf
            elif files.get("singles"):
                if not isinstance(files["singles"],dict): continue
                relative=(job.relative_to(Path(run_file).resolve().parent)/files["singles"]["directory"]).as_posix()
                directory=artifact_path(run_file,relative)
                for pdf in directory.glob("*.pdf"):
                    path=artifact_path(run_file,pdf.relative_to(Path(run_file).resolve().parent).as_posix())
                    if path.is_file(): return path
        except (OSError,ValueError,KeyError,TypeError): continue
    return None
