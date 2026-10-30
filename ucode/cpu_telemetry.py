"""Test-only CPU attribution from own process CPU clocks, not system-wide load."""
import csv
import os
import time
import threading


def key(cpu): return f"G{cpu['group']}/CPU{cpu['logical']}"


class Weighted:
    def __init__(self): self.duration=0.; self.total=0.; self.minimum=None; self.maximum=None; self.samples=0
    def add(self,value,seconds):
        self.duration+=seconds; self.total+=value*seconds; self.samples+=1
        self.minimum=value if self.minimum is None else min(self.minimum,value)
        self.maximum=value if self.maximum is None else max(self.maximum,value)
    def data(self):
        return {"min":self.minimum,"max":self.maximum,"mean":self.total/self.duration if self.duration else None,
                "sampled_seconds":self.duration,"samples":self.samples}


class CPUTrace:
    def __init__(self,cpus,path,*,interval=.5,clock=time.perf_counter):
        self.cpus=list(cpus); self.clock=clock; self.interval=interval; self.previous={}; self.previous_time=None
        self.phase="Подготовка"; self.groups={}; self.bindings={}; self.pid_keys={}; self.errors=[]
        self.overhead_seconds=0.; self.rows=0
        self.lock=threading.RLock()
        self.stream=path.open("x",encoding="utf-8-sig",newline="")
        self.writer=csv.writer(self.stream)
        self.writer.writerow(["Этап","Интервал,с","uCode: эквивалент занятых ядер","uCode: % выбранных CPU","Занято привязанных CPU (>=20%)",*[key(c) for c in self.cpus]])

    def bind(self,info):
        # Only actual worker-reported affinity is evidence of per-CPU placement.
        for pid,cpus in info.get("worker_affinity",{}).copy().items():
            if cpus and len(cpus)==1:
                self.bindings[int(pid)]=key(cpus[0])

    def set_phase(self,phase):
        if phase==self.phase: return
        from .resource_monitor import tree_stats
        with self.lock:
            self._sample(tree_stats(os.getpid()),force=True)
            self.phase=phase

    def sample(self,stats,*,force=False):
        with self.lock: self._sample(stats,force=force)

    def _sample(self,stats,*,force=False):
        now=self.clock()
        if self.previous_time is not None and not force and now-self.previous_time<self.interval: return
        start=time.perf_counter(); current={item["identity"]:item["cpu_seconds"] for item in stats}
        if self.previous_time is None:
            self.previous_time=now; self.previous=current; return
        elapsed=now-self.previous_time
        if elapsed<.05: return
        attributed={key(c):0. for c in self.cpus}; own=0.
        for identity,value in current.items():
            before=self.previous.get(identity,0. if identity[0]!=os.getpid() else value)
            delta=max(0.,value-before); own+=delta
            cpu=self.bindings.get(identity[0])
            if cpu:
                first=self.pid_keys.setdefault(identity[0],identity)
                if first!=identity: cpu=None
            if len(self.cpus)==1: cpu=key(self.cpus[0])
            if cpu in attributed: attributed[cpu]+=delta
        values={cpu:min(100.,100*seconds/elapsed) for cpu,seconds in attributed.items()}
        equivalent=min(len(self.cpus),own/elapsed); load=100*equivalent/max(1,len(self.cpus))
        busy=sum(value>=20 for value in values.values())
        for phase in ("Вся операция",self.phase):
            group=self.groups.setdefault(phase,{"load":Weighted(),"equivalent":Weighted(),"cpus":{key(c):Weighted() for c in self.cpus},"peak_busy_worker_cpus":0,"all_worker_cpus_busy_seconds":0.})
            group["load"].add(load,elapsed); group["equivalent"].add(equivalent,elapsed)
            group["peak_busy_worker_cpus"]=max(group["peak_busy_worker_cpus"],busy)
            if busy==len(self.cpus): group["all_worker_cpus_busy_seconds"]+=elapsed
            for cpu,value in values.items():
                if len(self.cpus)==1 or cpu in self.bindings.values(): group["cpus"][cpu].add(value,elapsed)
        self.writer.writerow([self.phase,elapsed,equivalent,load,busy,*[values[key(c)] if len(self.cpus)==1 or key(c) in self.bindings.values() else None for c in self.cpus]])
        self.rows+=1; self.previous=current; self.previous_time=now
        self.overhead_seconds+=time.perf_counter()-start

    def finish(self):
        from .resource_monitor import tree_stats
        with self.lock: self._sample(tree_stats(os.getpid()),force=True)
        self.stream.close()
        return {"status":"OBSERVED" if self.rows else "INSUFFICIENT_SAMPLES","interval_seconds":self.interval,"samples":self.rows,
                "threshold_pct":20,"aggregation_overhead_seconds":self.overhead_seconds,"errors":self.errors,
                "scope":"Own process-tree CPU clocks only. Per-CPU values attribute verified single-CPU pinned workers; parent/unpinned CPU cannot be assigned to an individual core. Short processes/peaks may be missed. Interval minima/maxima are not instantaneous peaks.",
                "bound_worker_count":len(self.bindings),"requested_cpus":self.cpus,
                "phases":{phase:{"selected_cpu_load_pct":g["load"].data(),"busy_core_equivalents":g["equivalent"].data(),
                           "per_cpu_pct":{cpu:values.data() if len(self.cpus)==1 or cpu in self.bindings.values() else None for cpu,values in g["cpus"].items()},
                           "peak_busy_worker_cpus":g["peak_busy_worker_cpus"],"all_worker_cpus_busy_seconds":g["all_worker_cpus_busy_seconds"]} for phase,g in self.groups.items()}}
