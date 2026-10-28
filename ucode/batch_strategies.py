"""One final PDF: sequential or parallel disjoint parts + measured merge + final QA."""
import json
import math
import multiprocessing as mp
from pathlib import Path
import shutil
import time

from .affinity import apply_affinity,cpu_keys
from .batch import run_batch,_make_directory,_check_cancel
from .execution import ExecutionOptions
from .lab_worker import atomic_json,code_fingerprint
from .print_settings import PrintSettings


def part_job(folder,request,settings,stop):
    folder=Path(folder); result={"status":"ERROR","errors":[]}
    try:
        if request.get("source_digest") and request["source_digest"]!=code_fingerprint(): raise RuntimeError("Сборка изменилась во время создания частей")
        result["affinity"]=apply_affinity(request["cpus"])
        source=folder/"codes.txt"
        with source.open("x",encoding="utf-8") as stream:
            for index in range(request["start"],request["start"]+request["count"]):
                if index%256==0: _check_cancel(stop)
                stream.write(f"{(200000000000+index)%10**12:012d}\n")
        updated=[0.0]
        def event(value):
            now=time.monotonic()
            if now-updated[0]>.1 or value["percent"]==100:
                try: atomic_json(folder/"progress.json",value)
                except PermissionError: pass
                updated[0]=now
        job=run_batch(source,folder/"j",mode="multipage",settings=settings,
            execution=ExecutionOptions(request["backend"],1 if request["backend"]=="serial" else len(request["cpus"]),request["batch_size"]),
            qa_mode="deferred",activity=request["activity"],force_disk=True,temporary_data=True,cancel=stop,events=event)
        manifest=json.loads((job/"manifest.json").read_text(encoding="utf-8"))
        result.update(status=manifest["status"],manifest=manifest,errors=manifest.get("errors",[]),pdf=str((job/f"all-{request['count']}-pages.pdf").resolve()))
        for cpus in manifest["execution"].get("worker_affinity",{}).values():
            if cpus is None or cpu_keys(cpus)!=cpu_keys(request["cpus"]):
                result.update(status="INVALID",errors=["CPU affinity части не подтверждена"])
    except BaseException as exc:
        result.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else "ERROR",errors=[str(exc)])
    finally: atomic_json(folder/"part.json",result)


class NumericFrames:
    """Independent expected QR values, bounded encoding for final merged QA."""
    def __init__(self,count,cancel,guard): self.count=count; self.cancel=cancel; self.guard=guard
    def __len__(self): return self.count
    def __getitem__(self,index):
        from .engines import get_engine
        self.guard(); _check_cancel(self.cancel)
        return get_engine().encode([f"{(200000000000+index)%10**12:012d}"])[0]
    def __iter__(self):
        from .engines import get_engine
        for start in range(0,self.count,64):
            self.guard(); _check_cancel(self.cancel)
            yield from get_engine().encode([f"{(200000000000+i)%10**12:012d}" for i in range(start,min(start+64,self.count))],cancel=self.cancel)


def run_split_trial(folder,request,settings,cancel,events,budget):
    from .generators import get_generator
    from .mergers import available_adapters
    from .stream_batch import ResourceGuard
    from .quality import check_pdf
    from .audit import qa_status
    count=request["count"]; size=request["part_pages"]; parts=request.get("part_count",math.ceil(count/size))
    if not 2<=parts<=1024: raise ValueError("Сравнение разбивки требует от2 до1024 частей")
    adapters={adapter.name:adapter for adapter in available_adapters()}
    adapter=adapters.get(request["merger"])
    if adapter is None or not adapter.probe()["available"]: raise NotImplementedError("Движок объединения недоступен: "+request["merger"])
    job=_make_directory(Path(folder)/"j","s"); guard=ResourceGuard(job,cancel)
    parallel=request.get("part_mode")=="parallel"
    concurrency=min(parts,len(request["cpus"])) if parallel else 1
    if concurrency*256*1024**2>budget["budget_bytes"]: raise NotImplementedError("Недостаточный безопасный бюджет RAM для параллельных частей")
    slices=[request["cpus"][index::concurrency] for index in range(concurrency)] if parallel else [request["cpus"]]
    context=mp.get_context("spawn"); stop=context.Event(); active={}; results={}; next_part=0
    report={"kind":"txt-batch-pdf","streaming":True,"pdf_indexed":False,"strategy":"split","schema_version":1,"generator":"qr",
        "mode":"multipage","count":count,"qa_mode":request["qa_mode"],"print":get_generator("qr").describe_settings(settings),
        "execution":{"backend":request["backend"],"effective_workers":request["workers"],"worker_affinity":{}},
        "status":"RUNNING","files":{},"qa":{},"errors":[],"seconds":{}}
    started=time.perf_counter(); creation=started
    shutil.copyfile(Path(folder)/"codes.txt",job/"codes.txt")
    report["print"]["pdf_writer"]="uCode DiskPDF parts → "+adapter.name
    raster=request["qa_mode"]=="full" and shutil.which("pdftoppm") is not None
    qa_units=0 if request["qa_mode"]=="deferred" else count+(len({0,count//2,count-1}) if raster else 0)
    part_units=2*count+parts; all_units=part_units+1+qa_units+1
    def event(stage,units,done=0,total=count):
        events({"stage":stage,"percent":min(99.9,100*units/all_units),"done":done,"total":total,"speed":0,"unit":"страниц"})
    try:
        while next_part<parts or active:
            guard(); _check_cancel(cancel)
            for slot in range(concurrency):
                if slot in active or next_part>=parts: continue
                index=next_part; next_part+=1
                directory=job/"p"/f"{index+1:04d}"; directory.mkdir(parents=True)
                portion,extra=divmod(count,parts)
                part={"start":index*portion+min(index,extra),"count":portion+int(index<extra),"cpus":slices[slot],
                      "backend":request["backend"],"batch_size":request["batch_size"],"activity":request["activity"],"source_digest":request.get("source_digest")}
                process=context.Process(target=part_job,args=(str(directory),part,settings,stop),name="ucode-pdf-part")
                process.start(); active[slot]=(process,index,directory,part["count"])
            for slot,(process,index,directory,part_count) in list(active.items()):
                if process.is_alive(): continue
                process.join()
                path=directory/"part.json"
                if not path.is_file(): raise RuntimeError(f"Часть{index+1}: нет результата, exitcode={process.exitcode}")
                data=json.loads(path.read_text(encoding="utf-8"))
                _check_cancel(cancel)
                if process.exitcode!=0 or data["status"]!="UNVERIFIED": raise RuntimeError(f"Часть{index+1}: {data.get('errors')}")
                results[index]=data; process.close(); del active[slot]
            done=sum(row["manifest"]["count"] for row in results.values())
            partial=0.0
            for process,index,directory,n in active.values():
                try: partial+=(2*n+1)*json.loads((directory/"progress.json").read_text(encoding="utf-8"))["percent"]/100
                except (OSError,ValueError): pass
            event("Создание частей одновременно" if parallel else "Создание частей по очереди",2*done+len(results)+partial,done)
            time.sleep(.03)
        report["seconds"]["parts_creation"]=time.perf_counter()-creation
        for key in ("code_encoding","write_multipage"):
            report["seconds"][key]=sum(row["manifest"]["seconds"].get(key,0) for row in results.values())
        target=job/f"all-{count}-pages.pdf"
        event("Объединение PDF · ожидание движка",part_units,count)
        from .mergers.external import engine_timeout
        timer=time.perf_counter()
        with engine_timeout(None): adapter.merge([Path(results[index]["pdf"]) for index in range(parts)],target)
        report["seconds"]["merge"]=time.perf_counter()-timer
        guard(); _check_cancel(cancel)
        report["files"]["multipage"]={"name":target.name,"bytes":target.stat().st_size,"pages":count}
        report["seconds"]["production_until_pdf_closed"]=time.perf_counter()-started
        if request["qa_mode"]=="deferred":
            report.update(status="UNVERIFIED",qa={"status":"NOT_RUN"}); report["seconds"]["quality_checks"]=0.0
        else:
            timer=time.perf_counter(); event("Проверка итогового PDF",part_units+1,0)
            qa=check_pdf(target,NumericFrames(count,cancel,guard),settings,render_samples=raster,cancel=cancel,
                         on_progress=lambda done,total:event("Проверка итогового PDF",part_units+1+done,done,total))
            report["qa"]={"multipage":qa,"raster_available":raster}
            report["status"]=qa_status(report["qa"],raster)
            report["seconds"]["quality_checks"]=time.perf_counter()-timer
        report["parts"]={"count":parts,"pages_per_part":size,"concurrency":concurrency,"mode":request["part_mode"],"merger":request["merger"],
                         "timing_scope":"parts_creation is wall time; encoding/write are sums and overlap in parallel mode"}
    except BaseException as exc:
        report.update(status="CANCELLED" if isinstance(exc,(InterruptedError,KeyboardInterrupt)) or (cancel is not None and cancel.is_set()) else "ERROR",errors=[str(exc)])
    finally:
        stop.set()
        for process,*_ in active.values(): process.join(.5)
        for process,*_ in active.values():
            if process.is_alive(): process.terminate()
            process.join(2)
            if process.is_alive(): process.kill(); process.join(2)
            process.close()
        report["seconds"]["total_including_qa"]=time.perf_counter()-started
        atomic_json(job/"manifest.json",report)
    return {"manifest":report,"job":job.relative_to(folder).as_posix(),"status":report["status"],"errors":report["errors"],
            "pdf_bytes":report["files"].get("multipage",{}).get("bytes",0),
            "seconds":{"production":report["seconds"].get("production_until_pdf_closed"),**report["seconds"]}}
