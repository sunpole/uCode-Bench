"""Isolated test-only bounded QR -> PDF preparation -> ordered PDF assembler."""
from collections import deque
import bisect
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
import zlib

from .affinity import apply_affinity,cpu_keys
from .pipeline_plan import Tasks,balanced_ranges


class PipelineBudgetError(ValueError):
    pass


def page_encoder(settings):
    """Cache the fixed physical grid once in each PDF preparation process."""
    from .compact_pdf import _number,_rectangles
    unit=settings.module_mm*72/25.4
    pos=[_number((i+settings.quiet_modules)*unit) for i in range(21)]
    size=[_number(i*unit) for i in range(22)]
    prefix=" ".join(_number(v/100,9) for v in settings.ink)+" k\nn\n"
    def encode(frame):
        if frame.version!=1 or frame.error!="M" or frame.size!=21 or any(len(row)!=21 for row in frame.matrix): raise ValueError("Только QR V1-M")
        rects=_rectangles(frame.matrix) if settings.pdf_profile=="compact" else ((x,y,1,1) for y,row in enumerate(reversed(frame.matrix)) for x,dark in enumerate(row) if dark)
        return zlib.compress((prefix+"".join(f"{pos[x]} {pos[y]} {size[w]} {size[h]} re\n" for x,y,w,h in rects)+"f\n").encode())
    return encode


def _stage_worker(pipe,stop,cpu,stage,settings,measure_memory=False):
    try:
        verified=apply_affinity([cpu])["verified_cpus"]
        from .engines import get_engine
        engine=get_engine(); engine.prepare_encoding(); prepare=page_encoder(settings)
        baseline=None
        if measure_memory:
            from .pipeline_memory import ready_memory
            baseline=ready_memory()
        pipe.send(("ready",os.getpid(),verified,baseline))
        while not stop.is_set():
            task=pipe.recv()
            if task is None: break
            start,value=task; qr_seconds=pdf_seconds=0.; began=time.perf_counter()
            if stage in ("qr","full"):
                frames=engine.encode([f"{(200000000000+i)%10**12:012d}" for i in range(start,start+value)],cancel=stop)
                qr_seconds=time.perf_counter()-began
            else: frames=value
            if stage in ("pdf","full"):
                timer=time.perf_counter()
                rows=[(start+i+1,frame.payload,prepare(frame)) for i,frame in enumerate(frames)]
                pdf_seconds=time.perf_counter()-timer
            else: rows=frames
            pipe.send(("done",start,rows,qr_seconds,pdf_seconds,began,time.perf_counter()))
    except (EOFError,BrokenPipeError): pass
    except BaseException as exc:
        try: pipe.send(("error",type(exc).__name__+": "+str(exc)))
        except (EOFError,OSError): pass
    finally: pipe.close()


def prepared_pages(request,settings,cancel,guard,info,observer=None,on_ready=None):
    """Yield completed pages in any order; the disk page tree restores TXT order.

    One bounded message per process, no giant equal-part result in RAM. Equal
    assigns each stage its exact fixed range; queue assigns the next free packet.
    This function may restrict its *isolated trial* parent to PDF CPUs.
    """
    from .pipeline_memory import memory_plan
    factor=request.get("processes_per_cpu",1)
    if type(factor) is not int or not 1<=factor<=10: raise ValueError("Процессов на CPU: 1–10")
    count=request["count"]; qr=request["qr_cpus"]*factor; pdf=request["pdf_cpus"]*factor; batch=request["batch_size"]
    workers=len(qr)+len(pdf)
    # A lower-bound reservation admits only the first real process. Its measured
    # startup memory then determines whether the remaining pool may be launched.
    plan=memory_plan(count,workers,batch,minimum=factor>1)
    in_flight=plan["bounded_values"]; required=plan["required_bytes"]
    info.update(required_ram_estimate_bytes=required,bounded_values_estimate=in_flight,
                worker_affinity={},worker_pids=[],worker_tasks={},max_pending_values=0,
                completed_values=0,qr_service_sum=0.,pdf_service_sum=0.,assembler_active_seconds=0.,
                processes_per_cpu=factor,requested_processes=workers,selected_cpu_count=len(request["qr_cpus"])+len(request["pdf_cpus"]),
                ram_plan=plan)
    if required>request["ram_budget_bytes"]: raise PipelineBudgetError("Безопасного бюджета ОЗУ недостаточно; уменьшите CPU или кодов за шаг")
    context=mp.get_context("spawn"); stop=context.Event(); pool=[]
    tasks=Tasks(count,len(qr),batch,request["schedule"])
    pending=[deque() for _ in pdf]; shared=deque(); pending_values=0
    ends=[start+size for start,size in balanced_ranges(count,len(pdf))] if pdf else []
    def check():
        guard()
        if cancel is not None and cancel.is_set(): raise InterruptedError("Конвейер остановлен")
    def receive(worker):
        try: message=worker["pipe"].recv()
        except (OSError,EOFError) as exc: raise RuntimeError("Процесс конвейера завершился без результата") from exc
        if message[0]=="error": raise RuntimeError(message[1])
        return message
    def ready(worker,msg):
        _,pid,mask,*extra=msg
        if cpu_keys(mask)!=cpu_keys([worker["cpu"]]): raise RuntimeError("Привязка процесса к CPU не подтверждена")
        worker.update(ready=True,pid=pid)
        info["worker_pids"].append(pid); info["worker_affinity"][str(pid)]=mask
        info["worker_tasks"][str(pid)]={"stage":worker["stage"],"cpu":mask,"pages":0,"packets":0,"service_seconds":0.}
        if observer: observer(info)
        return extra[0] if extra else None
    try:
        for stage,cpus in (("qr" if pdf else "full",qr),("pdf",pdf)):
            for slot,cpu in enumerate(cpus):
                check(); parent,child=context.Pipe()
                probe=factor>1 and not pool
                process=context.Process(target=_stage_worker,args=(child,stop,cpu,stage,settings,probe),name="ucode-pipeline-"+stage)
                try: process.start()
                except BaseException: parent.close(); child.close(); raise
                child.close(); pool.append({"process":process,"pipe":parent,"stage":stage,"slot":slot,"cpu":cpu,"ready":False,"active":None})
                if probe:
                    while not parent.poll(.05):
                        check()
                        if process.exitcode is not None: raise RuntimeError("Процесс калибровки завершился без готовности")
                    msg=receive(pool[-1])
                    if msg[0]!="ready": raise RuntimeError("Нет подтверждения готовности процесса калибровки")
                    observation=ready(pool[-1],msg)
                    plan=memory_plan(count,workers,batch,(observation or {}).get("baseline_bytes"))
                    info.update(ram_plan=plan,memory_startup_observation=observation,required_ram_estimate_bytes=plan["required_bytes"])
                    if plan["required_bytes"]>request["ram_budget_bytes"]:
                        raise PipelineBudgetError("Измеренный план памяти не помещается в безопасный бюджет; сократите множитель")
        # Spawn while the parent still has the union mask, then reserve PDF CPUs.
        if pdf: info["assembler_affinity"]=apply_affinity(request["pdf_cpus"])
        info["assembler_scope"]="Final serial assembler shares PDF CPUs" if pdf else "Final serial assembler shares full-cycle CPUs"
        ready_pages=0; announced=False
        while ready_pages<count:
            check(); changed=False
            for worker in pool:
                pipe=worker["pipe"]; process=worker["process"]
                if pipe.poll():
                    changed=True; msg=receive(worker)
                    if msg[0]=="ready":
                        ready(worker,msg)
                    elif msg[0]=="done":
                        _,start,rows,qr_s,pdf_s,began,ended=msg
                        expected=worker["active"]
                        size=expected[1] if worker["stage"]!="pdf" else len(expected[1])
                        if start!=expected[0] or len(rows)!=size: raise RuntimeError("Процесс вернул неверную порцию")
                        worker["active"]=None
                        stats=info["worker_tasks"][str(worker["pid"])]
                        stats["pages"]+=size; stats["packets"]+=1; stats["service_seconds"]+=ended-began
                        info["qr_service_sum"]+=qr_s; info["pdf_service_sum"]+=pdf_s
                        for stage,seconds in (("qr",qr_s),("pdf",pdf_s)):
                            if seconds:
                                first=began+(qr_s if stage=="pdf" else 0)
                                info[stage+"_first_service"]=min(info.get(stage+"_first_service",first),first)
                                info[stage+"_last_service"]=max(info.get(stage+"_last_service",0),ended-(pdf_s if stage=="qr" else 0))
                        if worker["stage"]=="qr":
                            if [f.payload for f in rows]!=[f"{(200000000000+i)%10**12:012d}" for i in range(start,start+size)]: raise RuntimeError("QR-процесс изменил номера")
                            if request["schedule"]=="equal":
                                groups={}
                                for offset,frame in enumerate(rows): groups.setdefault(bisect.bisect_right(ends,start+offset),[]).append(frame)
                                offset=0
                                for slot,frames in groups.items(): pending[slot].append((start+offset,frames)); offset+=len(frames)
                            else: shared.append((start,rows))
                            pending_values+=size; info["max_pending_values"]=max(info["max_pending_values"],pending_values)
                        else:
                            for offset,row in enumerate(rows):
                                if row[0]!=start+offset+1 or row[1]!=f"{(200000000000+start+offset)%10**12:012d}": raise RuntimeError("PDF-процесс изменил порядок/номера")
                                timer=time.perf_counter(); yield row
                                info["assembler_active_seconds"]+=time.perf_counter()-timer
                                ready_pages+=1; info["completed_values"]=ready_pages
                    else: raise RuntimeError("Неизвестный ответ процесса конвейера")
                elif process.exitcode is not None: raise RuntimeError(f"Процесс конвейера завершился: {process.exitcode}")
                if not all(w["ready"] for w in pool): continue
                if not announced:
                    if on_ready: on_ready()
                    announced=True
                if worker["active"] is not None: continue
                if worker["stage"]=="pdf":
                    queue=pending[worker["slot"]] if request["schedule"]=="equal" else shared
                    task=queue.popleft() if queue else None
                    if task: pending_values-=len(task[1])
                else:
                    task=tasks.take(worker["slot"]) if pending_values<len(qr)*batch else None
                if task is not None:
                    worker["active"]=task; pipe.send(task); changed=True
            if not changed: time.sleep(.002)
    finally:
        stop.set()
        for worker in pool:
            try: worker["pipe"].send(None)
            except (OSError,EOFError): pass
        deadline=time.monotonic()+.5
        for w in pool: w["process"].join(max(0,deadline-time.monotonic()))
        for w in pool:
            p=w["process"]
            if p.is_alive(): p.terminate()
            p.join(2)
            if p.is_alive(): p.kill(); p.join(2)
            w["pipe"].close(); p.close()


def run_pipeline_trial(folder,request,settings,cancel,events,budget,observer=None):
    from .batch import _make_directory
    from .batch_strategies import NumericFrames
    from .stream_batch import ResourceGuard
    from .stream_pdf import write_pdf,DiskReader
    from .quality import check_pdf
    from .audit import qa_status
    from .lab_worker import atomic_json
    from .generators import get_generator
    job=_make_directory(Path(folder)/"jobs","pipeline"); count=request["count"]
    guard=ResourceGuard(job,cancel); expected=NumericFrames(count,cancel,guard)
    report={"kind":"txt-batch-pdf","schema_version":1,"pipeline_contract":3,"strategy":"pipeline","streaming":True,
            "generator":"qr","mode":"multipage","count":count,"status":"RUNNING","qa_mode":request["qa_mode"],
            "print":get_generator("qr").describe_settings(settings),"seconds":{},"files":{},"qa":{},"errors":[],"execution":{}}
    info=report["execution"]; info.update(backend="pipeline",allocation=request["allocation"],schedule=request["schedule"],
        qr_cpus=request["qr_cpus"],pdf_cpus=request["pdf_cpus"],batch_size=request["batch_size"])
    shutil.copyfile(Path(folder)/"codes.txt",job/"codes.txt")
    started=time.perf_counter(); last=[0.]; stage_times={}
    def event(stage,done,total,percent):
        timer=stage_times.setdefault(stage,time.perf_counter())
        events({"stage":stage,"done":done,"total":total,"percent":min(99.9,percent),"speed":done/max(.001,time.perf_counter()-timer),"unit":"страниц"})
    def written(done,total):
        now=time.perf_counter()
        if now-last[0]>=.1 or done==total:
            event("Конвейер QR → подготовка → PDF",done,total,80*done/total if request["qa_mode"]!="deferred" else 99*done/total); last[0]=now
    pages=prepared_pages({**request,"ram_budget_bytes":budget["budget_bytes"]},settings,cancel,guard,info,observer,
        lambda:event("Конвейер QR → подготовка → PDF",0,count,0))
    try:
        event("Запуск процессов конвейера",0,count,0)
        target=job/f"all-{count}-pages.pdf"
        write_pdf(expected,target,settings,job/"pdf-index.sqlite",prepared=pages,cancel=cancel,guard=guard,on_progress=written)
        report["seconds"]["production_until_pdf_closed"]=time.perf_counter()-started
        report["seconds"]["pipeline_wall"]=report["seconds"]["production_until_pdf_closed"]
        report["seconds"]["qr_service_sum"]=info["qr_service_sum"]
        report["seconds"]["pdf_service_sum"]=info["pdf_service_sum"]
        report["seconds"]["assembler_active"]=info["assembler_active_seconds"]
        report["files"]["multipage"]={"name":target.name,"bytes":target.stat().st_size,"pages":count}
        timer=time.perf_counter()
        if request["qa_mode"]=="deferred": report.update(status="UNVERIFIED",qa={"status":"NOT_RUN","multipage":{"status":"NOT_RUN"}}); seconds=0.
        else:
            raster=request["qa_mode"]=="full" and shutil.which("pdftoppm") is not None
            event("Проверка итогового PDF",0,count,80)
            qa=check_pdf(target,expected,settings,render_samples=raster,cancel=cancel,
                reader_factory=lambda:DiskReader(target,job/"pdf-index.sqlite",cancel=cancel,guard=guard),
                on_progress=lambda done,total:event("Проверка итогового PDF",done,total,80+19*done/total))
            report["qa"]={"multipage":qa,"raster_available":raster}; report["status"]=qa_status(report["qa"],raster)
            if request["qa_mode"]=="full" and not raster: report["errors"].append("Нет растрового QA: pdftoppm недоступен; полный рейтинг исключён")
            if qa["status"]!="PASS": report["errors"].append("QA FAIL: "+str(qa.get("errors",[])))
            seconds=time.perf_counter()-timer
        report["seconds"]["quality_checks"]=seconds
    except PipelineBudgetError as exc:
        report.update(status="RESOURCE_LIMIT",errors=[str(exc)])
    except BaseException as exc:
        report.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) or cancel.is_set() else "ERROR",errors=[str(exc)])
    finally:
        pages.close()
        report["seconds"]["total_including_qa"]=time.perf_counter()-started
        atomic_json(job/"manifest.json",report)
    return {"manifest":report,"status":report["status"],"job":job.relative_to(folder).as_posix(),"errors":report["errors"],
            "pdf_bytes":report["files"].get("multipage",{}).get("bytes",0),
            "seconds":{"production":report["seconds"].get("production_until_pdf_closed"),**report["seconds"]}}
