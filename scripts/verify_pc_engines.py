"""User-invoked small proof of every registered merger; not a large speed ranking."""
import json
from pathlib import Path
import shutil
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ucode.batch import _make_directory
from ucode.mergers import available_adapters
from ucode.performance_catalog import inspect_catalog
from ucode.print_settings import PrintSettings
from ucode.qr import encode_numbers
from ucode.pdf import write_pdf
from ucode.quality import check_pdf


def main():
    directory=_make_directory(ROOT/"output/engine-proof","all")
    frames=encode_numbers(["000000000001","200000000002"]); settings=PrintSettings(); inputs=[]
    for index,frame in enumerate(frames):
        path=directory/f"input-{index}.pdf"; write_pdf([frame],path,settings); inputs.append(path)
    catalog=inspect_catalog(); result={"kind":"small-engine-proof","count":2,"repeats":3,
        "scope":"Two-page smoke; Python imports may be warm, CLI startup is included; no large-workload winner claimed","engines":[]}
    probes={item["name"]:item for item in catalog["mergers"]}
    for index,adapter in enumerate(available_adapters()):
        info=probes[adapter.name]; row={"name":adapter.name,"version":info.get("version"),"family":info["family"],"language":info["language"],"trials":[]}
        row["status"]="SKIPPED" if not info["available"] else "PASS"
        for repeat in range(3) if info["available"] else ():
            path=directory/f"{index+1:02d}-{repeat+1}.pdf"
            try:
                start=time.perf_counter(); adapter.merge(inputs,path); merged=time.perf_counter()-start
                start=time.perf_counter(); qa=check_pdf(path,frames,settings,render_samples=bool(shutil.which("pdftoppm"))); checked=time.perf_counter()-start
                status="PASS" if qa["status"]=="PASS" and qa["render_samples"] else "LIMITED" if qa["status"]=="PASS" else "INVALID"
                row["trials"].append({"status":status,"merge_seconds":merged,"qa_seconds":checked,"bytes":path.stat().st_size,"qa":qa})
                if status!="PASS": row["status"]=status
            except Exception as exc:
                row["status"]="ERROR"; row["trials"].append({"status":"ERROR","error":type(exc).__name__+": "+str(exc)})
        result["engines"].append(row)
        (directory/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(adapter.name,row["status"],flush=True)
    print("Evidence:",directory,flush=True)
    return 0 if all(row["status"]=="PASS" for row in result["engines"]) else 1


if __name__=="__main__": raise SystemExit(main())
