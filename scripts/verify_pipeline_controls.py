"""Retained small evidence only, never a throughput benchmark for large runs."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from ucode.pipeline_plan import PipelineConfig
    from ucode.pipeline_lab import run_pipeline_lab
    from ucode.hardware import inspect_cpu
    from ucode.lab_worker import atomic_json
    root=Path(__file__).resolve().parents[1]
    cpu=inspect_cpu()
    if cpu.get("available_physical",0)<3: raise SystemExit("Small proof needs 3 physical cores")
    cfg=PipelineConfig(counts=(7,),allocations=("physical:2:1","logical:2:2"),schedules=("equal","queue"),
                       batches=(1,),repeats=1,qa_mode="full",telemetry_modes=("off","cpu"),print_settings={"pdf_profile":"compact"})
    folder=run_pipeline_lab(root/"output/pipeline-proof",cfg)
    data=json.loads((folder/"pipeline.json").read_text(encoding="utf-8"))
    proof={"scope":"Small Windows integration only; maximum 7 pages per real PDF; no large throughput claim",
           "source_digest":data["source_digest"],"status":data["status"],"cases":len(data["cases"]),
           "trials":sum(len(c["trials"]) for c in data["cases"]),"config":asdict(cfg),"errors":data["errors"],
           "checks":[{"id":c["id"],"allocation":c["allocation"],"schedule":c["schedule"],"telemetry_mode":c["telemetry_mode"],
                     "status":c["status"],"qa":[t["manifest"]["qa"]["multipage"]["status"] for t in c["trials"]],
                     "worker_pages":[[{"stage":v["stage"],"pages":v["pages"]} for v in t["manifest"]["execution"]["worker_tasks"].values()] for t in c["trials"]]} for c in data["cases"]]}
    atomic_json(folder/"verification.json",proof)
    public=root/"results/cpu-pipeline"; public.mkdir(parents=True,exist_ok=True)
    atomic_json(public/"verification.json",proof)
    print(json.dumps({"folder":str(folder),"status":data["status"],"cases":len(data["cases"])},ensure_ascii=False))
    return 0 if data["status"]=="COMPLETE" else 2


if __name__=="__main__": raise SystemExit(main())
