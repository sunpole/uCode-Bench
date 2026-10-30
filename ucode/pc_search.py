"""Machine-local search, real trials only; staged search never claims exhaustive proof."""
from dataclasses import asdict,dataclass,field
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import statistics
import time

from .affinity import select_cpus,cpu_keys
from .batch import _make_directory
from .hardware import inspect_hardware
from .lab_worker import code_fingerprint,atomic_json
from .resource_lab import _run_trial
from .lab_report import summarize_trials
from .history import case_result
from .performance_catalog import inspect_catalog


@dataclass(frozen=True)
class SearchConfig:
    counts:tuple=(200,1000,10000,100000)
    repeats:int=3
    cpu_units:tuple=("physical",)
    cpu_counts:tuple=("1","all")
    all_cpu_counts:bool=True
    backends:tuple=("serial","process","thread")
    batches:tuple=(32,)
    pdf_profiles:tuple=("standard","compact")
    activities:tuple=("normal","minimal")
    qa_mode:str="full"
    ram_mode:str="auto"
    telemetry_mode:str="cpu"
    search_mode:str="staged"
    keep_best:int=2
    part_counts:tuple=(10,)
    part_modes:tuple=("sequential","parallel")
    mergers:tuple=("qpdf","MuPDF (mutool)","PyMuPDF","pikepdf","pypdf","pdfrw","PDFium (pypdfium2)","pdfcpu","Apache PDFBox","pdf-lib (Node.js)","PDFsharp (.NET)")
    print_settings:dict=field(default_factory=dict)
    timeline_mode:str="off"

    def __post_init__(self):
        if self.timeline_mode not in ("on","off"): raise ValueError("XY: on/off")
        from .print_settings import PrintSettings
        for axis in (self.counts,self.cpu_units,self.cpu_counts,self.backends,self.batches,self.pdf_profiles,self.activities,self.part_counts,self.part_modes,self.mergers):
            if not isinstance(axis,tuple) or not axis or len(axis)>64: raise ValueError("Выберите непустые наборы параметров, до64 значений")
        if any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in self.counts): raise ValueError("Количество кодов: положительные целые")
        if any(isinstance(n,bool) or not isinstance(n,int) or not 2<=n<=1024 for n in self.part_counts): raise ValueError("Частей: от2 до1024")
        if set(self.cpu_units)-{"physical","logical"} or set(self.backends)-{"serial","process","thread"}: raise ValueError("Неверный тип CPU/способ выполнения")
        if set(self.pdf_profiles)-{"standard","compact"} or set(self.activities)-{"normal","minimal"}: raise ValueError("Неверные PDF/расходы")
        if set(self.part_modes)-{"sequential","parallel"}: raise ValueError("Неверный способ создания частей")
        if self.qa_mode not in ("full","vector","deferred") or self.search_mode not in ("staged","full"): raise ValueError("Неверный режим поиска/QA")
        if not isinstance(self.ram_mode,str) or (self.ram_mode not in ("auto","max","80%","50%") and not (self.ram_mode.endswith("MiB") and self.ram_mode[:-3].isdigit())): raise ValueError("Выберите один допустимый бюджет ОЗУ")
        if isinstance(self.repeats,bool) or not isinstance(self.repeats,int) or not 1<=self.repeats<=10: raise ValueError("Повторы:1–10")
        if isinstance(self.keep_best,bool) or not isinstance(self.keep_best,int) or not 1<=self.keep_best<=8 or any(isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=1000 for n in self.batches): raise ValueError("Неверные число лидеров/порции кодов")
        PrintSettings(**self.print_settings)
        if self.telemetry_mode not in ("cpu","off"): raise ValueError("Неверный режим CPU-замеров")


def candidates(config,cpu):
    result=[]; seen={}
    for unit in config.cpu_units:
        try: maximum=len(select_cpus(cpu,unit,"all"))
        except ValueError: maximum=0
        choices=tuple(map(str,range(1,maximum+1))) if config.all_cpu_counts and maximum else config.cpu_counts
        for choice,backend,batch,pdf,activity in itertools.product(choices,config.backends,config.batches,config.pdf_profiles,config.activities):
            row={"family":f"F{len(result)+1:04d}","cpu_unit":unit,"cpu_choice":choice,"backend":backend,
                 "batch_size":batch,"pdf_profile":pdf,"activity":activity,"cpus":[],"workers":1,"status":"PENDING","reason":""}
            try:
                row["cpus"]=select_cpus(cpu,unit,choice)
                if backend=="serial" and len(row["cpus"])!=1: continue
                row["workers"]=1 if backend=="serial" else len(row["cpus"])
                if os.name=="nt" and len({item["group"] for item in row["cpus"]})>1: raise ValueError("Windows multi-group forced affinity не поддерживается")
                identity=(tuple(sorted(cpu_keys(row["cpus"]))),backend,batch,pdf,activity)
                if identity in seen: raise ValueError("Эквивалентный CPU-набор уже представлен в "+seen[identity])
                seen[identity]=row["family"]
            except ValueError as exc: row.update(status="SKIPPED",reason=str(exc))
            result.append(row)
            if len(result)>4096: raise ValueError("Более4096 кандидатов; сократите выбранные параметры")
    return result


def preview_search(config,cpu):
    rows=candidates(config,cpu); ready=sum(row["status"]!="SKIPPED" for row in rows)
    groups={(row["cpu_unit"],row["backend"]) for row in rows if row["status"]!="SKIPPED"}
    retained=min(ready,config.keep_best+sum(1 if backend=="serial" else 2 for _,backend in groups))
    counts=sorted(set(config.counts)); stages=ready*len(counts) if config.search_mode=="full" else ready+retained*(len(counts)-1)
    split_sizes={count:len(config.cpu_units)*len({min(count,parts) for parts in config.part_counts})*len(config.part_modes)*len(config.mergers) if count>1 else 0 for count in counts}
    parts=sum(split_sizes.values())
    pages=(sum(counts)*ready if config.search_mode=="full" else counts[0]*ready+sum(counts[1:])*retained)+sum(count*split_sizes[count]*2 for count in counts)
    return {"candidates":ready,"direct_cases":stages,"split_cases":parts,"trials_upper_bound":(stages+parts)*config.repeats,
            "pdf_pages_upper_bound":pages*config.repeats,"estimated_disk_bytes":256*1024**2+pages*config.repeats*16000,
            "scope":"Direct selected variants; staged retains leaders and CPU endpoints. Split uses best measured direct profile per size/unit and maximum selected CPU mask."}


def valid_summary(case,config):
    cfg={"repeats":config.repeats,"qa_mode":config.qa_mode,"output_mode":"multipage"}
    return case_result(case,cfg)["summary"]


def choose_leaders(cases,config):
    ranked=[]
    for case in cases:
        summary=valid_summary(case,config)
        if summary.get("median_launcher_wall_seconds"):
            ranked.append((summary["median_launcher_wall_seconds"],case))
    return [row for _,row in sorted(ranked,key=lambda pair:pair[0])]


def next_stage_candidates(leaders,config):
    """Keep CPU endpoints so tiny inputs cannot eliminate all large-CPU trials."""
    selected=list(leaders[:config.keep_best])
    for unit,backend in sorted({(case["cpu_unit"],case["backend"]) for case in leaders}):
        group=[case for case in leaders if case["cpu_unit"]==unit and case["backend"]==backend]
        for size in {min(len(case["cpus"]) for case in group),max(len(case["cpus"]) for case in group)}:
            candidate=next(case for case in group if len(case["cpus"])==size)
            if candidate not in selected: selected.append(candidate)
    return [{**case,"status":"PENDING","trials":[]} for case in selected]


from .test_archive import archived_test


@archived_test
def run_search(output_root,config,*,cancel=None,events=None):
    from .search_report import write_search_report
    hardware=inspect_hardware(output_root); catalog=inspect_catalog()
    families=candidates(config,hardware["cpu"]); plan=preview_search(config,hardware["cpu"])
    folder=_make_directory(output_root,"pc"); started=time.perf_counter(); counts=sorted(set(config.counts))
    data={"kind":"pc-performance-search","schema_version":1,"status":"RUNNING","config":asdict(config),"hardware":hardware,
          "catalog":catalog,"source_digest":code_fingerprint(),"plan":plan,"cases":[],"stages":[],"errors":[]}
    data["profile_hash"]=hashlib.sha256(json.dumps({"config":data["config"],"source":data["source_digest"],"catalog":catalog},sort_keys=True).encode()).hexdigest()
    from .frozen_runtime import snapshot_runtime,assert_trial_integrity
    frozen=snapshot_runtime(folder)
    data["source_digest"]=frozen["source_digest"]
    data["profile_hash"]=hashlib.sha256(json.dumps({"config":data["config"],"source":data["source_digest"],"catalog":catalog},sort_keys=True).encode()).hexdigest()
    data["runtime_snapshot"]={"folder":".runtime","source_digest":frozen["source_digest"]}
    finished=0
    def stopped():
        if cancel is not None and cancel.is_set(): raise InterruptedError("Подбор остановлен")
    def execute(prototype,count,**strategy):
        nonlocal finished
        stopped()
        case={**prototype,**strategy,"id":f"C{len(data['cases'])+1:04d}","count":count,"trials":[],"qa_mode":config.qa_mode}
        data["cases"].append(case)
        if case["status"]=="SKIPPED": return case
        case["status"]="RUNNING"
        for repeat in range(config.repeats):
            stopped()
            request={"count":count,"cpus":case["cpus"],"backend":case["backend"],"workers":case["workers"],"batch_size":case["batch_size"],
                     **frozen,"cpu_unit":case["cpu_unit"],"telemetry_mode":config.telemetry_mode,"timeline_mode":config.timeline_mode,
                     "pdf_profile":case["pdf_profile"],"activity":case["activity"],"ram_mode":config.ram_mode,"qa_mode":config.qa_mode,
                     "warmup":False,"output_mode":"multipage","print_settings":config.print_settings,"temporary_data":True,
                     "source_digest":data["source_digest"],"engine_version":catalog["encoders"][0]["version"],
                     **strategy}
            def event(value):
                if events:
                    events({**value,"percent":min(99.9,100*(finished+value["percent"]/100)/max(1,plan["trials_upper_bound"])),
                            "stage":f"{count} кодов · {case['id']} · повтор{repeat+1}/{config.repeats} · "+value["stage"]})
            trial=_run_trial(folder/"t"/f"{len(data['cases']):04d}-{repeat+1:02d}",request,cancel,event)
            trial["relative_folder"]=(Path("t")/trial["folder"]).as_posix()
            case["trials"].append(trial); finished+=1
            assert_trial_integrity(trial)
            if trial["status"]=="CANCELLED": raise InterruptedError("Подбор остановлен")
            if trial["status"] in ("SKIPPED","RESOURCE_LIMIT"): break
        case["summary"]=summarize_trials(case["trials"],config.repeats,count,qa_mode=config.qa_mode)
        case["status"]=case["summary"]["status"]
        case["reason"]="; ".join(str(message) for trial in case["trials"] for message in trial.get("errors",[]))
        write_search_report(folder,data)
        return case
    try:
        current=families
        for index,count in enumerate(counts):
            stage=[]
            for prototype in current: stage.append(execute({**prototype,"status":prototype.get("status","PENDING")},count,strategy="direct"))
            leaders=choose_leaders(stage,config)
            data["stages"].append({"count":count,"tested":sum(bool(case["trials"]) for case in stage),"skipped":sum(case["status"]=="SKIPPED" for case in stage),
                "leaders":[case["id"] for case in leaders[:config.keep_best]],
                "not_retested_after_screen":max(0,sum(row["status"]!="SKIPPED" for row in families)-len(stage)) if index else 0})
            if not leaders: raise RuntimeError(f"На{count} нет полного корректного набора замеров; следующий размер не запущен")
            current=families if config.search_mode=="full" else next_stage_candidates(leaders,config)
        for count in counts:
            if count<2: continue
            leaders=choose_leaders([case for case in data["cases"] if case["count"]==count and case.get("strategy")=="direct"],config)
            for unit in config.cpu_units:
                best=next((case for case in leaders if case["cpu_unit"]==unit),leaders[0])
                masks=[]
                for choice in (("all",) if config.all_cpu_counts else config.cpu_counts):
                    try: masks.append(select_cpus(hardware["cpu"],unit,choice))
                    except ValueError: pass
                mask=max(masks,key=len) if masks else []
                prototype={**best,"cpu_unit":unit,"cpu_choice":"all" if config.all_cpu_counts else str(len(mask)),"cpus":mask,
                           "workers":1 if best["backend"]=="serial" else len(mask),"status":"PENDING","trials":[]}
                probes={row["name"]:row for row in catalog["mergers"]}
                for number,mode,merger in itertools.product(sorted({min(count,n) for n in config.part_counts}),config.part_modes,config.mergers):
                    candidate=dict(prototype)
                    if not mask: candidate.update(status="SKIPPED",reason="Выбранный CPU-набор недоступен на этом ПК")
                    elif not probes.get(merger,{}).get("available"):
                        candidate.update(status="SKIPPED",reason=probes.get(merger,{}).get("reason","Движок не зарегистрирован"))
                    execute(candidate,count,strategy="split",part_count=number,part_pages=math.ceil(count/number),part_mode=mode,merger=merger)
        expected={"full":"PASS","vector":"LIMITED","deferred":"UNVERIFIED"}[config.qa_mode]
        statuses={case["status"] for case in data["cases"]}
        data["status"]=("COMPLETE" if config.qa_mode=="full" else expected) if statuses<={expected,"SKIPPED"} else "PARTIAL"
    except InterruptedError as exc: data.update(status="CANCELLED",errors=[str(exc)])
    except Exception as exc: data.update(status="ERROR",errors=[type(exc).__name__+": "+str(exc)])
    finally:
        data["elapsed_seconds"]=time.perf_counter()-started
        for case in data["cases"]:
            if case["status"]=="RUNNING": case["status"]="CANCELLED" if data["status"]=="CANCELLED" else "ERROR"
        write_search_report(folder,data)
    if events and data["status"] in ("COMPLETE","LIMITED","UNVERIFIED"):
        events({"stage":"Подбор завершён","percent":100,"done":finished,"total":finished,"speed":0,"unit":"запусков"})
    return folder
