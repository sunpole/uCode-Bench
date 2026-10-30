"""Versioned uCode test commands: the same validated configs as the GUI, no shell."""
from dataclasses import asdict,dataclass
import argparse
import json
from pathlib import Path
import shlex
import time

from .resource_lab import LabConfig,preview as lab_preview
from .pc_search import SearchConfig,preview_search
from .pipeline_plan import PipelineConfig,build_pipeline_cases
from .print_settings import PrintSettings
from .test_archive import archived_test

MERGERS={"qpdf":"qpdf","mutool":"MuPDF (mutool)","pymupdf":"PyMuPDF","pikepdf":"pikepdf","pypdf":"pypdf","pdfrw":"pdfrw",
         "pdfium":"PDFium (pypdfium2)","pdfcpu":"pdfcpu","pdfbox":"Apache PDFBox","pdf-lib":"pdf-lib (Node.js)","pdfsharp":"PDFsharp (.NET)"}
UNITS={"cores":"physical","smt":"logical","physical":"physical","logical":"logical"}
QA={"on":"full","off":"deferred","full":"full","vector":"vector","deferred":"deferred"}


class Parser(argparse.ArgumentParser):
    def error(self,message): raise ValueError(message)
    def exit(self,status=0,message=None): raise ValueError(message or "Справка: docs/TEST_COMMANDS.md")


def values(text,cast=str):
    parts=[]
    for part in text.split(","):
        if not part.strip(): raise ValueError("Пустое значение между запятыми")
        parts.append(cast(part.strip()))
    return tuple(dict.fromkeys(parts))


def merger_names(text):
    if text=="all": return tuple(MERGERS.values())
    result=[]
    for value in values(text):
        if value in MERGERS: result.append(MERGERS[value])
        elif value in MERGERS.values(): result.append(value)
        else: raise ValueError("Неизвестный движок: "+value)
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True)
class TestCommand:
    kind:str
    config:object


def parser_for(kind):
    p=Parser(prog="test "+kind,add_help=False,allow_abbrev=False)
    p.add_argument("--codes",default="200")
    p.add_argument("--repeats",type=int,default=3)
    p.add_argument("--qa",choices=QA,default="full")
    p.add_argument("--module",type=float,default=.5); p.add_argument("--quiet",type=int,default=4)
    p.add_argument("--ink",default="0,0,0,100")
    p.add_argument("--pdf",default="compact"); p.add_argument("--metrics",default="off")
    p.add_argument("--xy",choices=("on","off"),default="off")
    p.add_argument('--background',choices=('white','color','transparent'),default='white')
    p.add_argument('--paper',default='0,0,0,0')
    p.add_argument("--batch",default="32"); p.add_argument("--ram",default="auto")
    if kind in ("lab","search"):
        p.add_argument("--unit",default="cores"); p.add_argument("--cpu",default="1")
        p.add_argument("--backend",default="process"); p.add_argument("--activity",default="minimal")
    if kind=="lab":
        p.add_argument("--warmups",type=int,default=0); p.add_argument("--workers",type=int,default=0)
        p.add_argument("--files",choices=("multipage","singles","both"),default="multipage")
    if kind=="search":
        p.add_argument("--each-cpu",choices=("on","off"),default="off")
        p.add_argument("--search",choices=("staged","full"),default="full"); p.add_argument("--keep-best",type=int,default=2)
        p.add_argument("--parts",default="10"); p.add_argument("--part-mode",default="sequential,parallel")
        p.add_argument("--mergers",default="pypdf")
    if kind=="pipeline":
        p.add_argument("--split",default="cores:1+0"); p.add_argument("--schedule",default="equal,queue")
        p.add_argument("--processes-per-core",default="1")
    return p


def parse_command(line):
    if len(line)>16000: raise ValueError("Команда длиннее 16000 символов")
    tokens=shlex.split(line,comments=False,posix=True)
    if not tokens or tokens[0] not in ("test","тест"): raise ValueError("Начните команду с test lab, test pipeline, test search или test scientific")
    if len(tokens)<2: raise ValueError("Укажите вид теста")
    kind=tokens[1]
    if kind=="scientific":
        p=Parser(prog="test scientific",add_help=False,allow_abbrev=False)
        p.add_argument("--codes",choices=("200","1000","10000","all"),default="200"); p.add_argument("--mergers",default="all")
        a=p.parse_args(tokens[2:])
        return TestCommand(kind,{"size":"all" if a.codes=="all" else int(a.codes),"methods":merger_names(a.mergers)})
    if kind not in ("lab","pipeline","search"): raise ValueError("Неизвестный вид теста: "+kind)
    a=parser_for(kind).parse_args(tokens[2:])
    pdf=values(a.pdf); metrics=values(a.metrics)
    settings=asdict(PrintSettings(a.module,a.quiet,tuple(float(n.strip()) for n in a.ink.split(",")),pdf[0],
                                 background_mode=a.background,background_ink=tuple(float(n.strip()) for n in a.paper.split(','))))
    common={"counts":values(a.codes,int),"repeats":a.repeats,"qa_mode":QA[a.qa],"print_settings":settings,"timeline_mode":a.xy}
    if kind=="lab":
        if len(values(a.batch,int))!=1: raise ValueError("lab: один размер порции на команду; для нескольких используйте несколько строк")
        cfg=LabConfig(**common,cpu_counts=values(a.cpu),cpu_units=tuple(UNITS[v] for v in values(a.unit)),
            backends=values(a.backend),ram_modes=values(a.ram),batch_size=int(a.batch),workers=a.workers,warmups=a.warmups,
            output_mode=a.files,pdf_profiles=pdf,activity_modes=values(a.activity),telemetry_modes=metrics)
    elif kind=="pipeline":
        if len(pdf)!=1: raise ValueError("pipeline: один PDF-профиль на команду; для нескольких используйте несколько строк")
        allocations=[]
        for part in values(a.split):
            unit,numbers=part.split(":",1); qr,pdf_count=numbers.replace(":","+").split("+")
            allocations.append(f"{UNITS[unit]}:{int(qr)}:{int(pdf_count)}")
        cfg=PipelineConfig(**common,allocations=tuple(allocations),schedules=values(a.schedule),batches=values(a.batch,int),ram_mode=a.ram,telemetry_modes=metrics,processes_per_cpu=values(a.processes_per_core,int))
    else:
        if len(metrics)!=1: raise ValueError("search: один режим CPU-замеров на команду")
        cfg=SearchConfig(**common,cpu_counts=values(a.cpu),cpu_units=tuple(UNITS[v] for v in values(a.unit)),all_cpu_counts=a.each_cpu=="on",
            backends=values(a.backend),batches=values(a.batch,int),pdf_profiles=pdf,activities=values(a.activity),ram_mode=a.ram,
            telemetry_mode=metrics[0],search_mode=a.search,keep_best=a.keep_best,part_counts=values(a.parts,int),part_modes=values(a.part_mode),mergers=merger_names(a.mergers))
    return TestCommand(kind,cfg)


def parse_script(text):
    commands=[]
    for number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line.startswith("#"): continue
        try: commands.append(parse_command(line))
        except (ValueError,KeyError,TypeError) as exc: raise ValueError(f"Строка {number}: {exc}") from exc
        if len(commands)>32: raise ValueError("В очереди не более 32 команд")
    if not commands: raise ValueError("Вставьте хотя бы одну команду")
    return commands


def command_text(command):
    c=command.config
    if command.kind=="scientific":
        reverse={v:k for k,v in MERGERS.items()}
        return shlex.join(["test","scientific","--codes",str(c["size"]),"--mergers",",".join(reverse[v] for v in c["methods"])])
    settings=PrintSettings(**c.print_settings)
    args=["test",command.kind,"--codes",",".join(map(str,c.counts)),"--repeats",str(c.repeats),"--qa",c.qa_mode,
          "--module",str(settings.module_mm),"--quiet",str(settings.quiet_modules),"--ink",",".join(f"{n:g}" for n in settings.ink)]
    if settings.background_mode!='white' or any(settings.background_ink):
        args.extend(['--background',settings.background_mode,'--paper',','.join(f'{n:g}' for n in settings.background_ink)])
    def add(name,value): args.extend(["--"+name,",".join(map(str,value)) if isinstance(value,tuple) else str(value)])
    add("xy",c.timeline_mode)
    if command.kind=="pipeline":
        add("processes-per-core",c.processes_per_cpu)
        add("pdf",settings.pdf_profile)
        add("split",tuple(("cores" if v.split(":")[0]=="physical" else "smt")+":"+"+".join(v.split(":")[1:]) for v in c.allocations))
        add("schedule",c.schedules); add("batch",c.batches); add("ram",c.ram_mode); add("metrics",c.telemetry_modes)
    else:
        add("unit",c.cpu_units); add("cpu",c.cpu_counts); add("backend",c.backends); add("pdf",c.pdf_profiles)
        if command.kind=="lab":
            for name,value in (("metrics",c.telemetry_modes),("batch",c.batch_size),("ram",c.ram_modes),("activity",c.activity_modes),("warmups",c.warmups),("workers",c.workers),("files",c.output_mode)): add(name,value)
        else:
            reverse={v:k for k,v in MERGERS.items()}
            for name,value in (("metrics",c.telemetry_mode),("batch",c.batches),("ram",c.ram_mode),("activity",c.activities),("each-cpu","on" if c.all_cpu_counts else "off"),("search",c.search_mode),("keep-best",c.keep_best),("parts",c.part_counts),("part-mode",c.part_modes),("mergers",tuple(reverse[v] for v in c.mergers))): add(name,value)
    return shlex.join(args)


def preview_command(command,cpu):
    c=command.config
    if command.kind=="pipeline":
        cases=build_pipeline_cases(c,cpu); ready=[row for row in cases if row["status"]!="SKIPPED"]
        return {"kind":command.kind,"variants":len(ready),"runs":len(ready)*c.repeats,"skipped":len(cases)-len(ready),"exact":True,"processes":sorted({row['workers'] for row in ready}),
                "pages":sum(row["count"] for row in ready)*c.repeats}
    if command.kind=="lab":
        p=lab_preview(c,{"cpu":cpu})
        return {"kind":command.kind,"variants":p["eligible"],"runs":p["runs"],"skipped":p["skipped"],"exact":True,
                "note":"Прогрев включён в число запусков, но исключён из измеренных повторов"}
    if command.kind=="search":
        p=preview_search(c,cpu)
        return {"kind":command.kind,"variants":p["candidates"],"runs":p["trials_upper_bound"],"skipped":None,"exact":False,"pages":p["pdf_pages_upper_bound"]}
    return {"kind":"scientific","variants":None,"runs":None,"skipped":None,"exact":False,"note":"Три повтора; следующие размеры только после допуска. Исторический профиль всегда с полной QA."}


def execute(command,root,*,cancel=None,events=None):
    if command.kind=="lab":
        from .resource_lab import run_lab
        return run_lab(root/"laboratory",command.config,cancel=cancel,events=events)
    if command.kind=="pipeline":
        from .pipeline_lab import run_pipeline_lab
        return run_pipeline_lab(root/"pipeline",command.config,cancel=cancel,events=events)
    if command.kind=="search":
        from .pc_search import run_search
        return run_search(root/"search",command.config,cancel=cancel,events=events)
    from .scientific import run_scientific
    return run_scientific(root/"scientific",command.config["size"],methods=list(command.config["methods"]),cancel=cancel,events=events)


@archived_test
def run_script(text,output_root,*,cancel=None,events=None):
    from .batch import _make_directory
    from .hardware import inspect_hardware
    from .lab_worker import atomic_json,code_fingerprint
    commands=parse_script(text); folder=_make_directory(output_root,"commands"); started=time.perf_counter()
    data={"kind":"test-command-queue","schema_version":1,"command_language":1,"source_digest":code_fingerprint(),"status":"RUNNING","hardware":inspect_hardware(folder),"commands":[command_text(c) for c in commands],"runs":[],"errors":[]}
    (folder/"commands.txt").write_text("\n".join(data["commands"])+"\n",encoding="utf-8")
    try:
        for index,command in enumerate(commands,1):
            if cancel is not None and cancel.is_set(): raise InterruptedError("Очередь остановлена")
            if code_fingerprint()!=data["source_digest"]: raise RuntimeError("Код изменился между командами; очередь остановлена, предыдущие результаты сохранены")
            def event(value):
                if events: events({**value,"stage":f"Команда {index}/{len(commands)} · "+value["stage"],"percent":min(99.9,100*(index-1+value["percent"]/100)/len(commands))})
            result=execute(command,folder/"runs",cancel=cancel,events=event)
            from .test_archive import read_test
            _,report=read_test(result)
            detail={k:report[k] for k in ("kind","status","config","source_digest","cases","winners","methods","runs","elapsed_seconds") if k in report}
            data["runs"].append({"command":command_text(command),"folder":str(result.relative_to(folder)),"status":report.get("status","ERROR"),"result":detail})
            if report.get("status") not in ("COMPLETE","UNVERIFIED","LIMITED"): raise RuntimeError("Команда завершилась со статусом "+str(report.get("status"))+"; следующие команды не запущены")
        states={r["status"] for r in data["runs"]}
        data["status"]="UNVERIFIED" if "UNVERIFIED" in states else "LIMITED" if "LIMITED" in states else "COMPLETE"
    except InterruptedError as exc: data.update(status="CANCELLED",errors=[str(exc)])
    except Exception as exc: data.update(status="ERROR",errors=[str(exc)])
    finally:
        data["elapsed_seconds"]=time.perf_counter()-started
        atomic_json(folder/"commands.json",data)
        from .test_archive import write_text_report
        write_text_report(folder/"commands.html",data,"Очередь команд uCode")
    if events and data["status"] in ("COMPLETE","UNVERIFIED","LIMITED"):
        events({"stage":"Очередь и архив сохранены","done":len(commands),"total":len(commands),"percent":100,"speed":0,"unit":"команд"})
    return folder


def cli_main(argv):
    """python -m ucode test [--plan] lab|pipeline|search|scientific ..."""
    from .runtime import ROOT as project
    from .hardware import inspect_cpu
    from .test_archive import archive_scope
    argv=list(argv)
    if argv in ([],["help"]):
        print((project/"docs/TEST_COMMANDS.md").read_text(encoding="utf-8")); return 0
    dry=argv[0]=="--plan"
    if dry: argv=argv[1:]
    if argv[:1]==["--file"]:
        if len(argv)!=2: raise ValueError("test [--plan] --file путь-к-командам.txt")
        source=Path(argv[1])
        if source.stat().st_size>512*1024: raise ValueError("Файл команд больше512 КиБ")
        text=source.read_text(encoding="utf-8-sig")
    else: text=shlex.join(["test",*argv])
    commands=parse_script(text)
    if dry:
        print(json.dumps([preview_command(c,inspect_cpu()) for c in commands],ensure_ascii=False,indent=2)); return 0
    with archive_scope(project/"output/test-archive"):
        folder=run_script(text,project/"output/console-tests",events=lambda v:print(f"{v['stage']} · {v['percent']:.1f}%",flush=True))
    print(folder/"commands.html")
    status=json.loads((folder/"commands.json").read_text(encoding="utf-8"))["status"]
    return 0 if status=="COMPLETE" else 2 if status in ("UNVERIFIED","LIMITED") else 1
