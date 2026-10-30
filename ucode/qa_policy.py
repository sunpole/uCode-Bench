"""Explicit non-full QA results may have timings, never a verified PASS."""
import math

LIMITED_STATUS={"deferred":"UNVERIFIED","vector":"LIMITED"}


def positive(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>0


def limited_trial(trial,count,qa_mode,output_mode=None):
    expected=LIMITED_STATUS.get(qa_mode)
    if expected is None or not isinstance(trial,dict) or trial.get("status")!=expected: return False
    manifest=trial.get("manifest",{}); times=trial.get("seconds",{})
    if not isinstance(manifest,dict) or not isinstance(times,dict): return False
    if (manifest.get("status")!=expected or manifest.get("qa_mode")!=qa_mode or
        manifest.get("count")!=count or manifest.get("errors") or trial.get("errors")): return False
    mode=manifest.get("mode")
    if mode not in ("multipage","singles","both") or (output_mode is not None and mode!=output_mode): return False
    if not positive(times.get("production")) or not positive(times.get("total_including_qa")): return False
    if times["total_including_qa"]+1e-6<times["production"]: return False
    qa=manifest.get("qa",{})
    if not isinstance(qa,dict): return False
    if qa_mode=="deferred":
        return qa.get("status")=="NOT_RUN" and times.get("quality_checks")==0
    required=("multipage","singles") if mode=="both" else (mode,)
    return qa.get("raster_available") is False and all(isinstance(qa.get(key),dict) and qa[key].get("status")=="PASS" for key in required)
