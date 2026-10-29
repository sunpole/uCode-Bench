"""Explicit QR/PDF CPU partitions and bounded static/dynamic work ownership."""
from dataclasses import dataclass,field
import itertools
import os

from .affinity import select_cpus


@dataclass(frozen=True)
class PipelineConfig:
    counts:tuple=(1000,)
    allocations:tuple=("physical:12:2","logical:24:4")
    schedules:tuple=("equal","queue")
    batches:tuple=(32,)
    repeats:int=3
    qa_mode:str="deferred"
    ram_mode:str="auto"
    telemetry_modes:tuple=("cpu",)
    print_settings:dict=field(default_factory=dict)
    timeline_mode:str="off"

    def __post_init__(self):
        if self.timeline_mode not in ("on","off"): raise ValueError("XY: on/off")
        from .print_settings import PrintSettings
        for axis in (self.counts,self.allocations,self.schedules,self.batches,self.telemetry_modes):
            if not isinstance(axis,tuple) or not axis or len(axis)>64: raise ValueError("Выберите от 1 до 64 значений каждого параметра")
        if any(type(n) is not int or n<1 for n in self.counts): raise ValueError("Количество кодов: положительное целое")
        if any(type(n) is not int or not 1<=n<=1000 for n in self.batches): raise ValueError("Кодов за шаг: 1–1000")
        if type(self.repeats) is not int or not 1<=self.repeats<=10: raise ValueError("Повторы: 1–10")
        if set(self.schedules)-{"equal","queue"}: raise ValueError("Выберите равные части или общую очередь")
        if set(self.telemetry_modes)-{"off","cpu"}: raise ValueError("Неверные CPU-замеры")
        if self.qa_mode not in ("full","vector","deferred") or self.ram_mode not in ("auto","max","50%","80%"): raise ValueError("Неверный режим проверки/ОЗУ")
        for token in self.allocations: parse_allocation(token)
        PrintSettings(**self.print_settings)


def parse_allocation(token):
    try:
        unit,qr,pdf=token.split(":"); qr=int(qr); pdf=int(pdf)
        if unit not in ("physical","logical") or qr<1 or pdf<0: raise ValueError()
        return unit,qr,pdf
    except (ValueError,AttributeError): raise ValueError("Распределение: тип CPU, число для QR и число для PDF") from None


def partition(cpu,token):
    unit,qr,pdf=parse_allocation(token)
    # Keep siblings adjacent even when OS logical IDs are interleaved.
    cpus=select_cpus(cpu,unit,"all")
    cpus=sorted(cpus,key=lambda c:(c["group"],c["core"],c["logical"]))
    if qr+pdf>len(cpus): raise ValueError(f"Нужно {qr+pdf} CPU ({unit}), доступно {len(cpus)}")
    selected=cpus[:qr+pdf]
    if os.name=="nt" and len({c["group"] for c in selected})!=1: raise ValueError("Windows: разделение между processor groups пока недоступно")
    a,b=selected[:qr],selected[qr:]
    overlap={(c["group"],c["core"]) for c in a}&{(c["group"],c["core"]) for c in b}
    return {"cpu_unit":unit,"qr_cpus":a,"pdf_cpus":b,"cpus":selected,"shared_physical_cores":len(overlap)}


def balanced_ranges(count,workers):
    q,r=divmod(count,workers)
    return [(i*q+min(i,r),q+(i<r)) for i in range(workers)]


class Tasks:
    """Equal ownership remains fixed; packets stay small in both modes."""
    def __init__(self,count,workers,batch,schedule):
        self.count=count; self.batch=batch; self.schedule=schedule; self.next=0
        self.ranges=[[start,start+size] for start,size in balanced_ranges(count,workers)]
    def take(self,slot):
        if self.schedule=="equal":
            start,end=self.ranges[slot]; size=min(self.batch,end-start); self.ranges[slot][0]+=size
        else:
            start=self.next; size=min(self.batch,self.count-start); self.next+=size
        return (start,size) if size else None


def build_pipeline_cases(config,cpu):
    rows=[]
    for count,token,schedule,batch,telemetry in itertools.product(dict.fromkeys(config.counts),dict.fromkeys(config.allocations),dict.fromkeys(config.schedules),dict.fromkeys(config.batches),dict.fromkeys(config.telemetry_modes)):
        row={"id":f"P{len(rows)+1:04d}","count":count,"allocation":token,"schedule":schedule,"batch_size":batch,
             "telemetry_mode":telemetry,"backend":"pipeline","workers":0,"status":"PENDING","trials":[],"reason":""}
        try:
            row.update(partition(cpu,token)); row["workers"]=len(row["qr_cpus"])+len(row["pdf_cpus"])
        except ValueError as exc: row.update(status="SKIPPED",reason=str(exc))
        rows.append(row)
        if len(rows)>4096: raise ValueError("Более 4096 вариантов; сократите наборы параметров")
    return rows


def allocation_label(token):
    unit,qr,pdf=parse_allocation(token)
    return f"{qr}+{pdf} {'ядер' if unit=='physical' else 'потоков SMT'}"+(" · полный цикл" if not pdf else " · QR / PDF")
