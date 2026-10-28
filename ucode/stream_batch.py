"""Large production jobs: disk data/indexes, fixed in-flight QR batches, real QA."""
import json
from pathlib import Path
import shutil
import time
import tempfile

from .stream_data import DiskPlan,FrameStore
from .stream_pdf import write_pdf,DiskReader


class ResourceGuard:
    def __init__(self,directory,cancel):
        from .hardware import memory_info
        available=memory_info()["available_bytes"]
        if available is None: raise ValueError("Не удалось определить свободную ОЗУ для потоковой обработки")
        self.reserve=max(512*1024**2,available//10)
        self.directory=Path(directory); self.cancel=cancel; self.checked=0
    def __call__(self):
        from .batch import _check_cancel
        from .hardware import memory_info
        _check_cancel(self.cancel)
        now=time.monotonic()
        if now-self.checked<.25: return
        self.checked=now
        if shutil.disk_usage(self.directory).free<256*1024**2: raise RuntimeError("Остановлено: заканчивается свободное место, частичные файлы сохранены")
        free=memory_info()["available_bytes"]
        if free is None or free<self.reserve: raise RuntimeError("Остановлено: исчерпан резерв ОЗУ, частичные файлы сохранены")


def verify_stream_outputs(directory,frames,settings,mode,*,raster,cancel=None,on_progress=None,guard=lambda:None,indexed=True):
    from .quality import check_pdf
    root=Path(directory); qa={}; count=len(frames); samples={0,count//2,count-1}
    if mode in ("multipage","both"):
        path=root/f"all-{count}-pages.pdf"
        if on_progress: on_progress("Проверка PDF",0,count+(len(samples) if raster else 0))
        qa["multipage"]=check_pdf(path,frames,settings,render_samples=raster,cancel=cancel,
            on_progress=lambda done,total:on_progress("Проверка PDF",done,total) if on_progress else None,
            reader_factory=(lambda:DiskReader(path,root/"pdf-index.sqlite",cancel=cancel,guard=guard)) if indexed else None)
    if mode in ("singles","both"):
        done=failed=0; errors=[]; digits=max(4,len(str(count))); total=count+(len(samples) if raster else 0)
        actual=sum(1 for _ in (root/"singles").glob("*.pdf"))
        if actual!=count: failed+=1; errors.append("Число отдельных PDF отличается от тиража")
        for index,frame in enumerate(frames):
            guard(); rendered=raster and index in samples
            result=check_pdf(root/"singles"/f"{index+1:0{digits}d}_{frame.payload}.pdf",[frame],settings,render_samples=rendered,cancel=cancel)
            if result["status"]!="PASS":
                failed+=1
                if len(errors)<20: errors.append({"index":index+1,"errors":result["errors"]})
            done+=1+bool(rendered)
            if on_progress: on_progress("Проверка отдельных PDF",done,total)
        qa["singles"]={"status":"FAIL" if failed else "PASS","checked":actual,"failed_count":failed,"first_failures":errors}
    qa.update(raster_available=raster,scope="Every saved vector page independently decoded; disk-backed final PDF xref/page tree checked; optional first/middle/last raster")
    return qa


def run_stream_batch(input_txt,output_root,*,count_plan,settings,mode,engine,execution,qa_mode,activity,progress,cancel,events,temporary_data=False,execution_observer=None):
    from .batch import _make_directory,_sha256
    from .generators import get_generator
    from .engines import get_engine
    from .execution import execution_plan,encode_values
    from .hardware import inspect_hardware
    from .resources import check_resources
    from .progress import ProgressTracker
    from .print_settings import human_report
    from .audit import qa_status
    resource=check_resources(output_root,count_plan.total_codes,streaming=True)
    directory=_make_directory(output_root,f"pdf-{count_plan.total_codes}")
    guard=ResourceGuard(directory,cancel); hardware=inspect_hardware(directory)
    encoder=get_engine(engine); plan=None; scratch=None; started=time.perf_counter()
    report={"schema_version":1,"kind":"txt-batch-pdf","pipeline_contract":2,"streaming":True,
        "status":"RUNNING","generator":"qr","engine":encoder.info().to_dict(),"mode":mode,"count":count_plan.total_codes,
        "input_filename":Path(input_txt).name,"generation":count_plan.to_dict(),"print":get_generator("qr").describe_settings(settings),
        "resources":resource,"hardware":hardware,"execution":{},"qa_mode":qa_mode,"activity":activity,
        "files":{},"seconds":{},"qa":{},"errors":[]}
    report["print"]["pdf_writer"]="uCode DiskPDF/1 (disk-backed objects/xref)"
    tracker=None
    try:
        source=Path(input_txt)
        if activity=="normal":
            source=directory/"source-codes.txt"; shutil.copyfile(input_txt,source)
            report["files"]["source_txt"]={"name":source.name,"sha256":_sha256(source)}
        if temporary_data:
            scratch=tempfile.TemporaryDirectory(prefix=".work-",dir=directory)
            if not Path(scratch.name).resolve().is_relative_to(directory.resolve()): raise ValueError("Папка временного индекса вне результата")
        data_path=Path(scratch.name)/"data.sqlite" if scratch else directory/"data.sqlite"
        report["qr_cache_retained"]=not temporary_data
        from .execution import useful_cache_mib
        plan=DiskPlan(data_path,source,copies=count_plan.copies_per_value,policy=count_plan.duplicate_policy,cancel=cancel,guard=guard,
                      cache_mib=useful_cache_mib(execution,hardware["ram"]["available_bytes"]))
        if plan.plan.total_codes!=count_plan.total_codes: raise ValueError("Входной TXT изменился после расчёта тиража; повторите загрузку")
        count=plan.plan.total_codes; unique=plan.plan.unique_values; frames=plan.frames()
        first=plan.db.execute("SELECT value FROM rows ORDER BY id LIMIT 1").fetchone()[0]
        last=plan.db.execute("SELECT value FROM rows ORDER BY id DESC LIMIT 1").fetchone()[0]
        report.update(first_code=first,last_code=last,generation=plan.plan.to_dict())
        report["generation"].update(encoding_values_planned=unique,encoded_values=0,pdf_pages_written=0)
        with (directory/"codes.txt").open("x",encoding="utf-8",newline="\n") as out:
            for value, in plan.db.execute("SELECT value FROM rows ORDER BY id"):
                for _ in range(plan.copies): guard(); out.write(value+"\n")
        report["files"]["txt"]={"name":"codes.txt"}
        if activity=="normal": report["files"]["txt"]["sha256"]=_sha256(directory/"codes.txt")
        raster=qa_mode=="full" and shutil.which("pdftoppm") is not None
        copies=2 if mode=="both" else 1; samples=len({0,count//2,count-1}) if raster else 0
        def publish(event):
            if execution_observer: execution_observer(report["execution"])
            if events: events({**event,"execution":{"backend":execution.backend,"confirmed_processes":len(report["execution"].get("worker_pids",[])) if execution.backend=="process" else 1,"selected_cpu_count":len(execution.cpus) or report["execution"].get("effective_workers",1)}})
        tracker=ProgressTracker(unique+count*copies+(0 if qa_mode=="deferred" else (count+samples)*copies)+1,publish,min_interval=.5 if activity=="minimal" else .05)
        info=execution_plan(execution,unique,hardware["cpu"],hardware["ram"]["available_bytes"],buffered=True)
        report["execution"]=info
        def encoding(done,total): guard(); tracker.step("Кодирование QR",done,total,0)
        timer=time.perf_counter()
        encode_values(plan.values(),engine_key=engine,options=execution,plan=info.copy(),metadata=info,
            cancel=cancel,on_progress=encoding,encoding_only=True,result_store=FrameStore(plan))
        report["seconds"]["code_encoding"]=report["seconds"]["qr_encoding"]=time.perf_counter()-timer
        report["generation"]["encoded_values"]=unique
        base=unique
        if mode in ("both","singles"):
            folder=directory/"singles"; folder.mkdir(); digits=max(4,len(str(count)))
            timer=time.perf_counter(); files={"directory":"singles","count":0,"bytes":0}; report["files"]["singles"]=files
            for index,frame in enumerate(frames,1):
                guard(); path=folder/f"{index:0{digits}d}_{frame.payload}.pdf"
                encoder.write_pdf([frame],path,settings,cancel=cancel)
                files["count"]+=1; files["bytes"]+=path.stat().st_size
                tracker.step("Отдельные PDF",index,count,base)
            report["seconds"]["write_singles"]=time.perf_counter()-timer; base+=count
        if mode in ("both","multipage"):
            path=directory/f"all-{count}-pages.pdf"; timer=time.perf_counter()
            write_pdf(frames,path,settings,directory/"pdf-index.sqlite",cancel=cancel,guard=guard,
                on_progress=lambda done,total:tracker.step("Создание PDF",done,total,base))
            report["seconds"]["write_multipage"]=time.perf_counter()-timer
            report["files"]["multipage"]={"name":path.name,"bytes":path.stat().st_size,"pages":count}
            if activity=="normal": report["files"]["multipage"]["sha256"]=_sha256(path)
            base+=count
        report["generation"]["pdf_pages_written"]=count*copies
        report["seconds"]["production_until_pdf_closed"]=time.perf_counter()-started
        if qa_mode=="deferred":
            report.update(status="UNVERIFIED",qa={"status":"NOT_RUN","scope":"Explicitly disabled"})
            report["seconds"]["quality_checks"]=0.0
        else:
            timer=time.perf_counter(); previous=[None,0,base]
            def observe(stage,done,total):
                if previous[0] is not None and stage!=previous[0]: previous[2]+=previous[1]
                previous[0],previous[1]=stage,total
                tracker.step(stage,done,total,previous[2])
            report["qa"]=verify_stream_outputs(directory,frames,settings,mode,raster=raster,cancel=cancel,on_progress=observe,guard=guard)
            report["seconds"]["quality_checks"]=time.perf_counter()-timer
            report["status"]=qa_status(report["qa"],raster)
    except (Exception,KeyboardInterrupt) as exc:
        report.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else "ERROR",errors=[type(exc).__name__+": "+str(exc)])
    finally:
        if plan is not None: plan.close()
        if scratch is not None: scratch.cleanup()
        report["seconds"]["total_including_qa"]=time.perf_counter()-started
        (directory/"manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (directory/"ОТЧЁТ.txt").write_text(human_report(report),encoding="utf-8")
    if tracker and report["status"] in ("COMPLETE","UNVERIFIED","LIMITED"):
        tracker.finish(report["count"],"Создано без проверки" if qa_mode=="deferred" else "Готово")
    return directory


def audit_stream_job(root,original,*,render_samples=True,cancel=None,events=None):
    from .batch import _make_directory
    from .print_settings import PrintSettings,format_duration
    from .execution import ExecutionOptions,execution_plan,encode_values
    from .hardware import inspect_hardware
    from .audit import qa_status
    from .progress import ProgressTracker
    root=Path(root); folder=_make_directory(root/"audits","qa"); guard=ResourceGuard(folder,cancel)
    cfg=original["print"]; settings=PrintSettings(cfg["module_mm"],cfg["quiet_modules"],tuple(cfg["ink"]),pdf_profile=cfg.get("pdf_profile","standard"))
    started=time.perf_counter(); plan=None
    result={"kind":"pdf-audit","status":"RUNNING","qa":{},"errors":[],"source_job":"../..","streaming":True}
    try:
        plan=DiskPlan(folder/"expected.sqlite",root/"codes.txt",cancel=cancel,guard=guard)
        count=plan.plan.total_codes
        if count!=original["count"]: raise ValueError("codes.txt отличается от числа страниц manifest")
        raster=bool(render_samples and shutil.which("pdftoppm")); unique=plan.plan.unique_values
        copies=2 if original["mode"]=="both" else 1
        tracker=ProgressTracker(unique+(count+(len({0,count//2,count-1}) if raster else 0))*copies+1,events)
        hardware=inspect_hardware(folder); options=ExecutionOptions()
        info=execution_plan(options,unique,hardware["cpu"],hardware["ram"]["available_bytes"],buffered=True)
        def encoded(done,total): guard(); tracker.step("Эталоны QR",done,total,0)
        encode_values(plan.values(),options=options,plan=info,encoding_only=True,result_store=FrameStore(plan),cancel=cancel,on_progress=encoded)
        previous=[None,0,unique]
        def observe(stage,done,total):
            if previous[0] is not None and stage!=previous[0]: previous[2]+=previous[1]
            previous[0],previous[1]=stage,total; tracker.step(stage,done,total,previous[2])
        result["qa"]=verify_stream_outputs(root,plan.frames(),settings,original["mode"],raster=raster,cancel=cancel,on_progress=observe,guard=guard,indexed=original.get("pdf_indexed",True))
        result["status"]=qa_status(result["qa"],raster)
    except (Exception,KeyboardInterrupt) as exc:
        result.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else "ERROR",errors=[str(exc)])
    finally:
        if plan is not None: plan.close()
        result["seconds"]=time.perf_counter()-started
        (folder/"audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (folder/"ОТЧЁТ.txt").write_text("uCode — ПРОВЕРКА СОХРАНЁННОГО PDF\nСтатус: "+result["status"]+"\nВремя: "+format_duration(result["seconds"])+"\nИсходные PDF/manifest не изменены.\n"+"\n".join(result["errors"])+"\n",encoding="utf-8")
    return folder
