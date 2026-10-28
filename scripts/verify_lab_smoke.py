"""Tiny resource lab with real affinity, three repeats and real two-page PDFs."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ucode.resource_lab import LabConfig, run_lab
from ucode.hardware import inspect_cpu


def main():
    choices=("1","2") if inspect_cpu()["available_logical"]>=2 else ("1",)
    config=LabConfig(counts=(2,),cpu_counts=choices,backends=("serial","process","thread"),ram_modes=("max",),repeats=3)
    folder=run_lab(ROOT/"output/lab-smoke",config)
    data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
    assert data["status"]=="COMPLETE",data
    for case in data["cases"]:
        assert case["status"]=="PASS" and len(case["trials"])==3,case
        assert case["summary"]["median_seconds"]>0
        for trial in case["trials"]:
            assert len(trial["affinity"]["verified_cpus"])==len(case["cpus"])
            assert trial["manifest"]["count"]==2
            assert trial["manifest"]["qa"]["multipage"]["status"]=="PASS"
            assert trial["memory"]["peak_tree_rss_bytes"]>0
    print("PASS: resource lab",len(data["cases"]),"cases, three repeats, two pages each",flush=True)
    print("Evidence:",folder,flush=True)


if __name__=="__main__": main()
