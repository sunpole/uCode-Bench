"""Local command line; no network, installation, or automatic next stage."""
import argparse
import json
from pathlib import Path
import sys
from .config import Experiment


def main(argv=None):
    parser = argparse.ArgumentParser(prog="uCode", description="Локальный QR/PDF бенчмарк")
    parser.add_argument("command", choices=("doctor", "create", "benchmark", "suite", "gui", "batch", "template", "generate"), nargs="?", default="gui")
    parser.add_argument("--count", type=int, choices=(2, 200, 1000, 10000), default=200)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "output" / "runs")
    parser.add_argument("--qualifying-report", type=Path, help="Отчёт PASS этапа 200 для явного запуска 1000")
    parser.add_argument("--input", type=Path, help="Входной UTF-8 TXT: один 12-значный код на строку")
    parser.add_argument("--mode", choices=("both", "singles", "multipage"), default="both")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            from .environment import inspect_environment
            result = inspect_environment()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["core_ready"] else 2
        if args.command == "gui":
            from .gui import main as gui_main
            gui_main()
            return 0
        if args.command == "suite":
            from .suite import main as suite_main
            return suite_main(["--output", str(args.output.parent / "comparisons")])
        if args.command == "batch":
            from .batch_gui import main as batch_main
            batch_main()
            return 0
        if args.command == "template":
            from .batch import make_template
            root = args.output if args.output != Path(__file__).resolve().parent.parent / "output" / "runs" else Path(__file__).resolve().parent.parent / "output" / "templates"
            print(make_template(root, args.count))
            return 0
        if args.command == "generate":
            from .batch import run_batch
            if not args.input:
                parser.error("Для команды generate требуется --input path/to/codes.txt")
            root = args.output if args.output != Path(__file__).resolve().parent.parent / "output" / "runs" else Path(__file__).resolve().parent.parent / "output" / "jobs"
            directory = run_batch(args.input, root, mode=args.mode, progress=lambda message: print(message, flush=True))
            result = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            print(directory / "manifest.json")
            return 0 if result["status"] == "COMPLETE" else 2 if result["status"] == "LIMITED" else 1
        from .benchmark import create_inputs, load_qualifying_methods, run_experiment
        config = Experiment(count=args.count)
        if args.command == "create":
            directory = create_inputs(args.output, config, progress=lambda message: print(message, flush=True))
            print(directory)
            return 0
        methods = None
        if config.count == 1000:
            if not args.qualifying_report:
                parser.error("--count 1000 требует --qualifying-report от завершённого этапа 200")
            methods = load_qualifying_methods(args.qualifying_report)
        directory = run_experiment(args.output, config, progress=lambda message: print(message, flush=True), allowed_methods=methods)
        result = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        print(directory / "report.html")
        return 0 if result["status"] == "COMPLETE" and any(m["status"] == "PASS" for m in result["methods"]) else 1
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"uCode: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
