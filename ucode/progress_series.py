"""Bounded observations of actual counters; no I/O, polling, or PDF payloads."""
from functools import wraps
import math
import time


def counter_kind(stage):
    if stage.startswith("Кодирование "):
        return "encoded_codes"
    if stage in ("Создание PDF", "Отдельные PDF", "Конвейер QR → подготовка → PDF"):
        return "written_pages"
    return None


class ProgressSeries:
    def __init__(self, *, clock=None, interval=.5, max_points=128):
        if interval <= 0 or max_points < 4:
            raise ValueError("Неверные параметры ряда XY")
        self.clock=clock or time.perf_counter; self.started=self.clock()
        self.interval=interval; self.max_points=max_points; self.segments=[]; self.current=None
        self.omitted_segments=0

    def observe(self, event):
        stage=str(event.get("stage", "")); kind=counter_kind(stage)
        done=event.get("done"); total=event.get("total")
        if not kind or type(done) is not int or type(total) is not int or not 0 <= done <= total or total < 1:
            return
        elapsed=self.clock()-self.started
        if not math.isfinite(elapsed) or elapsed < 0:
            return
        p=self.current
        if p is None or p["stage"]!=stage or p["target"]!=total or done<p["last_done"]:
            if len(self.segments)>=8:
                self.omitted_segments+=1; return
            p={"stage":stage,"counter_kind":kind,"target":total,"points":[[elapsed,done,None,0]],
               "observations":1,"compactions":0,"last_time":elapsed,"last_done":done,
               "delta":0,"duration":0.,"min":None,"max":None}
            self.segments.append(p); self.current=p; return
        dt=elapsed-p["last_time"]
        if dt <= 0 or (dt<self.interval and done!=total):
            return
        delta=done-p["last_done"]; rate=delta/dt
        p["last_time"]=elapsed; p["last_done"]=done; p["delta"]+=delta; p["duration"]+=dt
        p["min"]=rate if p["min"] is None else min(p["min"],rate)
        p["max"]=rate if p["max"] is None else max(p["max"],rate)
        p["observations"]+=1; p["points"].append([elapsed,done,rate,dt])
        if len(p["points"])>self.max_points:
            points=p["points"]; valid=[i for i,v in enumerate(points) if v[2] is not None]
            keep={0,len(points)-1,min(valid,key=lambda i:points[i][2]),max(valid,key=lambda i:points[i][2])}
            for i in range(0,len(points),2):
                if len(keep)>=self.max_points//2+2: break
                keep.add(i)
            p["points"]=[points[i] for i in sorted(keep)]; p["compactions"]+=1

    def data(self,status):
        return {"schema":1,"status":status,"interval_seconds":self.interval,"max_points_per_segment":self.max_points,
                "clock_scope":"Elapsed since observer start, not launcher_wall; rate = counter delta / actual observed interval",
                "point_fields":["elapsed_seconds","completed","codes_per_second","observed_interval_seconds"],
                "omitted_segments":self.omitted_segments,"segments":[{k:p[k] for k in ("stage","counter_kind","target","points","observations","compactions")} |
                {"stats":{"min":p["min"],"mean":p["delta"]/p["duration"] if p["duration"] else None,"max":p["max"]}} for p in self.segments]}


def record_operation(function):
    """Production-only observer when explicitly selected; save after existing timers."""
    @wraps(function)
    def call(*args,**kwargs):
        mode=kwargs.get("timeline_mode","off")
        if mode not in ("off","on"):
            raise ValueError("XY: on/off")
        if mode=="off":
            return function(*args,**kwargs)
        series=ProgressSeries(); callback=kwargs.get("events"); final=[]
        def observe(event):
            series.observe(event)
            if event.get("percent")==100: final.append(event)
            elif callback: callback(event)
        folder=function(*args,**{**kwargs,"events":observe})
        import json
        from pathlib import Path
        from .lab_worker import atomic_json
        root=Path(folder); manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
        manifest["timeline_mode"]="on"; manifest["timeline"]=series.data(manifest["status"])
        atomic_json(root/"manifest.json",manifest)
        atomic_json(root/"timeline.json",manifest["timeline"])
        from .test_archive import write_text_report
        write_text_report(root/"production.html",manifest,"uCode — создание PDF и график XY")
        with (root/"ОТЧЁТ.txt").open("a",encoding="utf-8") as stream:
            stream.write("\nГрафик XY: production.html; наблюдения: timeline.json. Запись XY включена.\n")
        if callback:
            for event in final: callback(event)
        return folder
    return call
