"""Local command line; no network, installation, or automatic next stage."""
import argparse
import json
from pathlib import Path
import sys
from .config import Experiment


def main(argv=None):
    parser = argparse.ArgumentParser(prog="uCode", description="Локальный QR/PDF бенчмарк")
    parser.add_argument("command", choices=("doctor", "create", "benchmark", "suite", "gui", "batch", "template", "generate", "lab"), nargs="?", default="gui")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--copies", type=int, default=1, help="Экземпляров каждого значения в обычной генерации")
    parser.add_argument("--duplicate-policy", choices=("preserve", "unique"), default="preserve")
    parser.add_argument("--backend", choices=("serial", "process", "thread"), default="serial")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--lab-counts", default="200")
    parser.add_argument("--cpu-counts", default="1,2,4,6,12,all-2,all")
    parser.add_argument("--cpu-unit", choices=("logical","physical","both"), default="logical")
    parser.add_argument("--backends", default="serial,process,thread")
    parser.add_argument("--ram-modes", default="auto")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=0)
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
            try:
                from .batch_gui import main as gui_main
                gui_main()
            except Exception as exc:
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(None, f"Не удалось открыть uCode: {exc}\nПроверьте Python/Tk или запустите Setup-PDF.cmd.", "uCode", 0x10)
                else:
                    print(f"uCode GUI: {exc}", file=sys.stderr)
                return 1
            return 0
        if args.command == "suite":
            from .suite import main as suite_main
            return suite_main(["--output", str(args.output.parent / "comparisons")])
        if args.command == "batch":
            return main(["gui"])
        if args.command == "template":
            from .batch import make_template
            root = args.output if args.output != Path(__file__).resolve().parent.parent / "output" / "runs" else Path(__file__).resolve().parent.parent / "output" / "templates"
            print(make_template(root, args.count))
            return 0
        if args.command == "generate":
            from .batch import run_batch
            from .execution import ExecutionOptions
            if not args.input:
                parser.error("Для команды generate требуется --input path/to/codes.txt")
            root = args.output if args.output != Path(__file__).resolve().parent.parent / "output" / "runs" else Path(__file__).resolve().parent.parent / "output" / "jobs"
            directory = run_batch(args.input, root, mode=args.mode, copies_per_value=args.copies,
                                  duplicate_policy=args.duplicate_policy,
                                  execution=ExecutionOptions(args.backend, 1 if args.workers is None else args.workers,
                                                             32 if args.batch_size is None else args.batch_size),
                                  progress=lambda message: print(message, flush=True))
            result = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            print(directory / "manifest.json")
            return 0 if result["status"] == "COMPLETE" else 2 if result["status"] == "LIMITED" else 1
        if args.command == "lab":
            from .resource_lab import LabConfig, run_lab
            config=LabConfig(counts=tuple(int(n) for n in args.lab_counts.split(",")),
                cpu_counts=tuple(args.cpu_counts.split(",")),cpu_units=("logical","physical") if args.cpu_unit=="both" else (args.cpu_unit,),
                backends=tuple(args.backends.split(",")),ram_modes=tuple(args.ram_modes.split(",")),
                repeats=args.repeats,warmups=args.warmups,workers=0 if args.workers is None else args.workers,
                batch_size=1 if args.batch_size is None else args.batch_size,output_mode=args.mode)
            default=Path(__file__).resolve().parent.parent/"output"/"runs"
            folder=run_lab(args.output if args.output!=default else default.parent/"laboratory",config,
                           progress=lambda message:print(message,flush=True))
            print(folder/"comparison.html")
            return 0 if json.loads((folder/"lab.json").read_text(encoding="utf-8"))["status"]=="COMPLETE" else 1
        from .benchmark import create_inputs, load_qualifying_methods, run_experiment
        config = Experiment(count=args.count)
        if args.command == "create":
            directory = create_inputs(args.output, config, progress=lambda message: print(message, flush=True))
            print(directory)
            return 0
        methods = None
        if config.count in (1000, 10000):
            if not args.qualifying_report:
                parser.error(f"--count {config.count} требует --qualifying-report от предыдущего проверенного этапа")
            methods = load_qualifying_methods(args.qualifying_report, target_count=config.count)
        directory = run_experiment(args.output, config, progress=lambda message: print(message, flush=True), allowed_methods=methods)
        result = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        print(directory / "report.html")
        return 0 if result["status"] == "COMPLETE" and any(m["status"] == "PASS" for m in result["methods"]) else 1
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"uCode: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
