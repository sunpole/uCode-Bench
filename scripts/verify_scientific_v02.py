"""Real, bounded scientific pipeline verification; does not install engines."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucode.scientific import run_scientific

parser = argparse.ArgumentParser()
parser.add_argument("--count", type=int, choices=(200, 1000, 10000), default=200)
args = parser.parse_args()
last = [0.0]
events = []
def observe(event):
    events.append(event)
    if time.monotonic() - last[0] > 3 or event["percent"] == 100:
        print(f"{event['stage']}: {event['done']}/{event['total']} total={event['percent']:.1f}%", flush=True)
        last[0] = time.monotonic()
folder = run_scientific(ROOT / "output/v02-scientific", args.count, methods=["pypdf"], events=observe,
                        progress=lambda text: print(text, flush=True))
result = json.loads((folder / "scientific.json").read_text(encoding="utf-8"))
(folder / "progress-evidence.json").write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
assert result["status"] == "COMPLETE", result["errors"]
assert events[-1]["percent"] == 100
assert all(a["percent"] <= b["percent"] for a, b in zip(events, events[1:])), "Progress regressed"
assert all(len(m["trials"]) == 3 for run in result["runs"] for m in run["methods"] if m["status"] == "PASS")
print("PASS scientific:", folder, flush=True)
