"""A fresh process for each measured trial; no QA inside timed region."""
import json
import sys
import traceback
import time
from pathlib import Path
from .config import Experiment, QRFrame
from .metrics import measure


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    destination = Path(sys.argv[2])
    try:
        config = Experiment(**request["config"])
        kind = request["kind"]
        output = Path(request["output"])
        last_progress = [0.0]
        class FileCancel:
            def is_set(self):
                return bool(request.get("cancel_file")) and Path(request["cancel_file"]).exists()
        cancel = FileCancel() if request.get("cancel_file") else None
        def update(done, total):
            if time.monotonic() - last_progress[0] >= 0.1 or done == total:
                last_progress[0] = time.monotonic()
                path = Path(request["progress_file"])
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps({"done": done, "total": total}), encoding="utf-8")
                try:
                    temp.replace(path)
                except PermissionError:
                    # Windows may temporarily hold a reader handle without
                    # FILE_SHARE_DELETE. Progress is advisory; retry next tick.
                    pass
        notify = update if request.get("progress_file") else None
        engine = None
        if kind in ("encode", "direct", "singles"):
            from .engines import get_engine
            # The historical scientific profile remains fixed to QR V1-M.
            engine = get_engine(request.get("engine", "reportlab"), generator="qr",
                                mode="singles" if kind == "singles" else "multipage")
            engine.prepare()
        if kind in ("encode", "direct"):
            from .data import generate_numbers
            numbers = generate_numbers(config)
        if kind in ("singles",):
            frames = [QRFrame.from_dict(f) for f in json.loads(Path(request["frames"]).read_text(encoding="utf-8"))]
        if kind == "encode":
            frames = []
            def action():
                frames.extend(engine.encode(numbers, on_progress=notify, cancel=cancel))
            metrics = measure(action)
            with output.open("x", encoding="utf-8") as stream:
                json.dump([f.to_dict() for f in frames], stream)
        elif kind == "singles":
            metrics = measure(lambda: engine.write_singles(frames, output, config, on_progress=notify, cancel=cancel))
        elif kind == "direct":
            def direct():
                frames = engine.encode(numbers, cancel=cancel,
                    on_progress=(lambda d, t: update(d, 2 * t)) if notify else None)
                engine.write_pdf(frames, output, config, cancel=cancel,
                    on_progress=(lambda d, t: update(t + d, 2 * t)) if notify else None)
            metrics = measure(direct)
        elif kind == "merge":
            import importlib
            from .mergers import available_adapters
            adapter = next(a for a in available_adapters() if a.name == request["method"])
            if adapter.module_name:
                importlib.import_module(adapter.module_name)
            inputs = [Path(p) for p in request["inputs"]]
            metrics = measure(lambda: adapter.merge(inputs, output))
        else:
            raise ValueError(f"Unknown worker kind: {kind}")
        result = {"status": "OK", **metrics}
        if engine is not None:
            result["engine"] = engine.info().to_dict()
    except Exception as exc:
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
