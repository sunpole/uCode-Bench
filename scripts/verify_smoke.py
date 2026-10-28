"""Small real-PDF checks only. Large performance workloads are user started."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucode.batch import _make_directory, run_batch
from ucode.print_settings import PrintSettings
from ucode.execution import ExecutionOptions
from ucode.hardware import inspect_cpu


def main():
    base = _make_directory(ROOT / "output/smoke", "generation")
    summary = []
    cases = ((2, "both", (0, 0, 0, 100), 1, False, "serial"),
             (7, "multipage", (0, 0, 0, 100), 1, False, "serial"),
             (2, "singles", (100, 0, 0, 0), 1, False, "serial"),
             (2, "multipage", (0, 0, 0, 100), 3, True, "serial"),
             (7, "multipage", (0, 0, 0, 100), 1, False, "process"),
             (2, "both", (100, 0, 0, 0), 3, True, "process"))
    for index, (count, mode, ink, copies, duplicate, backend) in enumerate(cases):
        source = base / f"source-{index}.txt"
        values = [f"{200000000000 + i:012d}" for i in range(count)]
        if duplicate:
            values.append(values[0])
        with source.open("x", encoding="utf-8") as stream:
            stream.write("\n".join(values) + "\n")
        samples = []
        folder = run_batch(source, base / "jobs", mode=mode, settings=PrintSettings(ink=ink), events=samples.append,
                           execution=ExecutionOptions(backend, min(2, inspect_cpu()["available_logical"]), 1),
                           copies_per_value=copies, duplicate_policy="unique" if duplicate else "preserve")
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "COMPLETE", data
        assert data["count"] == count * copies and data["engine"]["version"]
        assert data["generation"]["unique_values"] == count
        assert data["generation"]["encoded_values"] == count
        assert data["execution"]["backend"] == backend
        if backend == "process":
            assert len(data["execution"]["worker_pids"]) == data["execution"]["effective_workers"]
        assert samples[-1]["percent"] == 100
        assert all(a["percent"] <= b["percent"] for a, b in zip(samples, samples[1:]))
        assert all("average_speed" in event for event in samples)
        assert (folder / "ОТЧЁТ.txt").is_file()
        for key in ("multipage", "singles"):
            if key in data["qa"]:
                assert data["qa"][key]["status"] == "PASS"
        (folder / "progress-evidence.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({"count": count * copies, "unique_values": count, "copies_per_value": copies,
                        "mode": mode, "ink": ink, "status": data["status"],
                        "execution": data["execution"], "hardware": data["hardware"],
                        "engine": data["engine"], "seconds": data["seconds"],
                        "folder": str(folder.relative_to(base))})
        print(f"PASS: {count} values x {copies} copies = {data['count']} codes / {mode} / {data['engine']['name']} {data['engine']['version']}", flush=True)
    (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Evidence:", base, flush=True)


if __name__ == "__main__":
    main()
