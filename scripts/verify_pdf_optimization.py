"""Small A/B proof: four profiles, three repeats, seven real PDF pages each.

No large workloads. For 200/500/1000/10000 use the user-started GUI lab.
"""
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ucode.resource_lab import LabConfig,run_lab


def main():
    config=LabConfig(counts=(7,),cpu_counts=("1",),backends=("serial",),ram_modes=("max",),
                     pdf_profiles=("standard","compact"),activity_modes=("normal","minimal"),repeats=3)
    folder=run_lab(ROOT/"output/optimization-smoke",config)
    data=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
    assert data["status"]=="COMPLETE",data
    assert len(data["cases"])==4
    for case in data["cases"]:
        assert case["status"]=="PASS" and len(case["trials"])==3,case
        assert case["summary"]["median_pdf_bytes"]>0
        for trial in case["trials"]:
            manifest=trial["manifest"]
            assert manifest["qa_mode"]=="full"
            assert manifest["status"]=="COMPLETE"
            assert manifest["print"]["pdf_profile"]==case["pdf_profile"]
            assert manifest["activity"]==case["activity"]
            assert manifest["count"]==manifest["qa"]["multipage"]["pages_checked"]==7
            assert manifest["qa"]["multipage"]["status"]=="PASS"
            assert len(manifest["qa"]["multipage"]["decoded_samples"])==3
    assert len(data["pdf_optimization_pairs"])==len(data["overhead_pairs"])==2
    with (folder/"comparison.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.reader(stream))
    assert len(rows)==5 and all(len(row)==len(rows[0]) for row in rows)
    print("PASS: four PDF/activity variants, three repeats, seven pages, full independent QA",flush=True)
    for pair in data["pdf_optimization_pairs"]+data["overhead_pairs"]:
        print(f"{pair['baseline']} -> {pair['candidate']}: generation {pair['generation_speedup']:.3f}x; "
              f"with QA {pair['speedup_with_qa']:.3f}x; PDF {pair['baseline_pdf_bytes']} -> {pair['candidate_pdf_bytes']} bytes",flush=True)
    print("Evidence:",folder,flush=True)


if __name__=="__main__": main()
