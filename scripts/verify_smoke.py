"""Small real-PDF checks only. Large performance workloads are user started."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucode.batch import _make_directory, run_batch
from ucode.print_settings import PrintSettings


def main():
    base = _make_directory(ROOT / "output/smoke", "generation")
    summary = []
    for index, (count, mode, ink) in enumerate(((2, "both", (0, 0, 0, 100)),
                                               (7, "multipage", (0, 0, 0, 100)),
                                               (2, "singles", (100, 0, 0, 0)))):
        source = base / f"source-{index}.txt"
        with source.open("x", encoding="utf-8") as stream:
            stream.write("\n".join(f"{200000000000 + i:012d}" for i in range(count)) + "\n")
        samples = []
        folder = run_batch(source, base / "jobs", mode=mode, settings=PrintSettings(ink=ink), events=samples.append)
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "COMPLETE", data
        assert data["count"] == count and data["engine"]["version"]
        assert samples[-1]["percent"] == 100
        assert all(a["percent"] <= b["percent"] for a, b in zip(samples, samples[1:]))
        assert all("average_speed" in event for event in samples)
        assert (folder / "ОТЧЁТ.txt").is_file()
        for key in ("multipage", "singles"):
            if key in data["qa"]:
                assert data["qa"][key]["status"] == "PASS"
        (folder / "progress-evidence.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({"count": count, "mode": mode, "ink": ink, "status": data["status"],
                        "engine": data["engine"], "seconds": data["seconds"],
                        "folder": str(folder.relative_to(base))})
        print(f"PASS: {count} values / {mode} / {data['engine']['name']} {data['engine']['version']}", flush=True)
    (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Evidence:", base, flush=True)


if __name__ == "__main__":
    main()
