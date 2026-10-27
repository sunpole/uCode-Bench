"""Finite real-PDF verification for Windows/Linux; all evidence stays local."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucode.batch import make_template, run_batch
from ucode.print_settings import PrintSettings
from ucode.resources import check_resources
from pypdf import PdfReader


def main():
    base = ROOT / "output/v02-verification"
    base.mkdir(parents=True, exist_ok=True)
    summary = []
    for count in (200, 1000, 10000):
        resources = check_resources(base, count)
        source = make_template(base / "templates", count)
        samples = []
        last = [0.0]
        def observe(event):
            samples.append(event)
            if time.monotonic() - last[0] > 2 or event["percent"] == 100:
                print(f"{count}: {event['stage']} {event['done']}/{event['total']} {event['percent']:.1f}%", flush=True)
                last[0] = time.monotonic()
        folder = run_batch(source, base / "jobs", mode="multipage", events=observe)
        report = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert report["status"] == "COMPLETE", report
        pdf = folder / report["files"]["multipage"]["name"]
        assert len(PdfReader(pdf).pages) == count
        assert report["qa"]["multipage"]["pages_checked"] == count
        assert len(report["qa"]["multipage"]["decoded_samples"]) == 3
        assert samples[-1]["percent"] == 100
        assert all(a["percent"] <= b["percent"] for a, b in zip(samples, samples[1:]))
        (folder / "progress-evidence.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({"count": count, "status": report["status"], "seconds": report["seconds"],
                        "pdf": str(pdf.relative_to(ROOT)), "resources": resources, "events": len(samples)})
        (base / f"summary-{os.getpid()}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"PASS real PDF {count}: {pdf}", flush=True)
    # A colored actual PDF must be recognized as colored and pass its own QA.
    source = make_template(base / "color", 200)
    folder = run_batch(source, base / "jobs", mode="multipage", settings=PrintSettings(ink=(100, 0, 0, 0)))
    colored = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert colored["status"] == "COMPLETE" and colored["print"]["k100"] is False, colored
    print("PASS colored CMYK PDF; no K100 claim", flush=True)


if __name__ == "__main__":
    main()
