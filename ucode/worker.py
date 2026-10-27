"""A fresh process for each measured trial; no QA inside timed region."""
import json
import sys
import traceback
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
        if kind in ("encode", "direct"):
            from .data import generate_numbers
            from .qr import encode_numbers
            numbers = generate_numbers(config)
        if kind in ("singles",):
            frames = [QRFrame.from_dict(f) for f in json.loads(Path(request["frames"]).read_text(encoding="utf-8"))]
        if kind == "encode":
            frames = []
            def action():
                frames.extend(encode_numbers(numbers))
            metrics = measure(action)
            with output.open("x", encoding="utf-8") as stream:
                json.dump([f.to_dict() for f in frames], stream)
        elif kind == "singles":
            from .pdf import write_single_files
            metrics = measure(lambda: write_single_files(frames, output, config))
        elif kind == "direct":
            from .pdf import write_pdf
            metrics = measure(lambda: write_pdf(encode_numbers(numbers), output, config))
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
    except Exception as exc:
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
