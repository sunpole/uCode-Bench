"""Validate and project recorded counter observations, never synthesize old curves."""
import math


def _finite(v):
    return type(v) in (int,float) and math.isfinite(v) and v>=0


def timeline_views(data):
    result=[]; omitted=0
    def add(timeline,label,status):
        nonlocal omitted
        if not isinstance(timeline,dict) or timeline.get("schema")!=1: return
        for segment in timeline.get("segments",[]):
            if len(result)>=4096: omitted+=1; continue
            points=segment.get("points",[]); target=segment.get("target")
            if type(target) is not int or target<1 or not isinstance(points,list) or not 1<=len(points)<=128: continue
            valid=all(isinstance(p,list) and len(p)==4 and _finite(p[0]) and type(p[1]) is int and 0<=p[1]<=target and
                      (p[2] is None or _finite(p[2])) and _finite(p[3]) for p in points)
            if not valid or any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(points,points[1:])): continue
            kind=segment.get('counter_kind')
            if kind not in ('encoded_codes','written_pages'): continue
            stats=segment.get('stats',{})
            result.append({'label':label+' · '+str(segment.get('stage','')),'status':status,'target':target,'points':points,
                'counter_kind':kind,'stats':{k:v if _finite(v) else None for k,v in ((k,stats.get(k)) for k in ('min','mean','max'))},
                'observations':segment.get('observations'),'compactions':segment.get('compactions',0)})
    def visit(node,prefix,depth=0):
        if depth>8: return
        add(node.get('timeline'),prefix,node.get('status','UNKNOWN'))
        for case in node.get('cases',[]):
            for i,trial in enumerate(case.get('trials',[]),1):
                if not trial.get('warmup'): add(trial.get('timeline'),f"{prefix} · {case.get('count','?')} кодов · {case.get('id','?')} · повтор {i}",trial.get('status','UNKNOWN'))
        for i,run in enumerate(node.get('runs',[]),1):
            visit(run.get('result') or {},prefix+f' / команда {i}',depth+1)
    visit(data,'Серия')
    return result,omitted
