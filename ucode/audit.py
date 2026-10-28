"""One QA implementation for immediate and explicitly deferred validation."""
import json
from pathlib import Path
import shutil
import time


def verify_outputs(directory,frames,settings,mode,*,code_module=None,render_samples=True,cancel=None,on_progress=None):
    if mode not in ("both","multipage","singles") or not frames:
        raise ValueError("Неверный режим или пустой список кодов для QA")
    from .generators import get_generator
    code_module=code_module or get_generator("qr")
    root=Path(directory); qa={}; samples=sorted({0,len(frames)//2,len(frames)-1})
    def emit(stage,done,total):
        if on_progress: on_progress(stage,done,total)
    if mode in ("both","multipage"):
        path=root/f"all-{len(frames)}-pages.pdf"
        total=len(frames)+(len(samples) if render_samples else 0)
        emit("Проверка PDF",0,total)
        qa["multipage"]=code_module.verify(path,frames,settings,render_samples=render_samples,cancel=cancel,
            on_progress=lambda done,total:emit("Проверка PDF",done,total))
    if mode in ("both","singles"):
        paths=sorted((root/"singles").glob("*.pdf")); done=0; failures=[]; failed=0
        total=len(frames)+(len(samples) if render_samples else 0)
        emit("Проверка отдельных PDF",0,total)
        if len(paths)!=len(frames):
            failures.append({"file":"singles","errors":["Число отдельных PDF не совпадает с тиражом"]}); failed+=1
        for index,(path,frame) in enumerate(zip(paths,frames)):
            if cancel is not None and cancel.is_set(): raise InterruptedError("Проверка остановлена")
            raster=render_samples and index in samples
            result=code_module.verify(path,[frame],settings,render_samples=raster,cancel=cancel)
            done+=1+bool(raster); emit("Проверка отдельных PDF",done,total)
            if result["status"]!="PASS":
                failed+=1
                if len(failures)<20: failures.append({"index":index+1,"file":path.name,"errors":result["errors"]})
        qa["singles"]={"status":"FAIL" if failed else "PASS","checked":len(paths),
                       "rendered_samples":len(samples) if render_samples else 0,"failed_count":failed,"first_failures":failures}
    qa["raster_available"]=bool(render_samples)
    qa["scope"]="Every saved page structurally validated and independently decoded; raster first/middle/last if requested and available."
    return qa


def qa_status(qa,rendered):
    return "INVALID" if any(value.get("status")=="FAIL" for value in qa.values() if isinstance(value,dict)) else "COMPLETE" if rendered else "LIMITED"


def audit_job(directory,*,render_samples=True,cancel=None,events=None,progress=None):
    from .batch import _make_directory,load_codes
    from .generators import get_generator
    from .engines import get_engine
    from .print_settings import PrintSettings
    root=Path(directory).resolve()
    original=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    if original.get("streaming"):
        from .stream_batch import audit_stream_job
        return audit_stream_job(root,original,render_samples=render_samples,cancel=cancel,events=events)
    cfg=original["print"]
    settings=PrintSettings(cfg["module_mm"],cfg["quiet_modules"],tuple(cfg["ink"]),pdf_profile=cfg.get("pdf_profile","standard"))
    numbers=load_codes(root/"codes.txt",generator=original.get("generator","qr"),cancel=cancel)
    if len(numbers)!=original["count"]: raise ValueError("codes.txt не совпадает с числом страниц manifest")
    module=get_generator(original.get("generator","qr"))
    folder=_make_directory(root/"audits","qa")
    result={"kind":"pdf-audit","status":"RUNNING","qa":{},"errors":[],"source_job":"../.."}
    started=time.perf_counter()
    try:
        if progress: progress("Независимая проверка сохранённых PDF")
        unique=list(dict.fromkeys(numbers))
        raster=bool(render_samples and shutil.which("pdftoppm"))
        copies=2 if original["mode"]=="both" else 1
        qa_units=(len(numbers)+(len({0,len(numbers)//2,len(numbers)-1}) if raster else 0))*copies
        total_work=len(unique)+qa_units+1
        def emit(stage,done,total,base=0):
            if events: events({"stage":stage,"done":done,"total":total,"percent":min(99.9,100*(base+done)/total_work),
                               "elapsed":time.perf_counter()-started,"speed":0,"average_speed":0,"unit":"проверок"})
        encoded=get_engine().encode(unique,cancel=cancel,on_progress=lambda done,total:emit("Эталоны QR",done,total))
        if [frame.payload for frame in encoded]!=unique: raise ValueError("Неверный результат encoder для QA")
        mapping={frame.payload:frame for frame in encoded}; frames=[mapping[number] for number in numbers]
        previous=[None,0,len(unique)]
        def update(stage,done,total):
            if previous[0] is not None and stage!=previous[0]: previous[2]+=previous[1]
            previous[0],previous[1]=stage,total
            emit(stage,done,total,previous[2])
        result["qa"]=verify_outputs(root,frames,settings,original["mode"],code_module=module,render_samples=raster,
                                    cancel=cancel,on_progress=update)
        result["status"]=qa_status(result["qa"],raster)
    except (Exception,KeyboardInterrupt) as exc:
        result.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else "ERROR",errors=[str(exc)])
    result["seconds"]=time.perf_counter()-started
    (folder/"audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    from .print_settings import format_duration
    details=["uCode — ПРОВЕРКА СОХРАНЁННЫХ PDF","Статус: "+result["status"],
             f"Кодов: {len(numbers)}; время: {format_duration(result['seconds'])}",
             "Исходные PDF и manifest не изменены. Результат проверки — в audit.json.",
             "COMPLETE = структуры и растровые образцы; LIMITED = только структуры; INVALID = ошибка качества."]
    for kind in ("multipage","singles"):
        item=result["qa"].get(kind)
        if item:
            details.append(f"{kind}: {item['status']}")
            details.extend(item.get("errors",[])[:5])
            details.extend(str(value) for value in item.get("first_failures",[])[:3])
    (folder/"ОТЧЁТ.txt").write_text("\n".join(details+result["errors"])+"\n",encoding="utf-8")
    if events and result["status"]=="COMPLETE":
        events({"stage":"Проверка завершена","done":len(numbers),"total":len(numbers),"percent":100,
                "elapsed":result["seconds"],"speed":0,"average_speed":0,"unit":"проверок"})
    return folder
