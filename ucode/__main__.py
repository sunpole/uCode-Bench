"""Local command line; no network, installation, or automatic next stage."""
import argparse
import json
from pathlib import Path
import sys
from .config import Experiment


def main(argv=None):
    command_args=list(sys.argv[1:] if argv is None else argv)
    if command_args[:1]==["graphs"]:
        from .graphical_report import cli_main
        try: return cli_main(command_args[1:])
        except (ValueError,KeyError,TypeError,OSError) as exc:
            print("uCode graphs: "+str(exc),file=sys.stderr); return 1
    if command_args[:1]==["test"]:
        from .test_commands import cli_main
        try: return cli_main(command_args[1:])
        except (ValueError,KeyError,TypeError,OSError) as exc:
            print("uCode test: "+str(exc),file=sys.stderr); return 1
    parser = argparse.ArgumentParser(prog="uCode", description="Локальный QR/PDF бенчмарк")
    parser.add_argument("command", choices=("doctor", "create", "benchmark", "suite", "gui", "gui-browser", "gui-legacy", "batch", "template", "generate", "lab","audit","pc-search"), nargs="?", default="gui")
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
    parser.add_argument("--pdf-profile",choices=("standard","compact"),default="standard")
    parser.add_argument("--qa",choices=("full","vector","deferred"),default="full")
    parser.add_argument("--activity",choices=("normal","minimal"),default="normal")
    parser.add_argument("--xy",choices=("on","off"),default="off",help="Запись фактических наблюдений XY")
    parser.add_argument("--pdf-profiles",default="standard")
    parser.add_argument("--activity-modes",default="normal")
    parser.add_argument("--search-counts",default="200,1000,10000,100000")
    parser.add_argument("--search-mode",choices=("staged","full"),default="staged")
    parser.add_argument("--keep-best",type=int,default=2)
    parser.add_argument("--all-cpu-counts",action="store_true")
    parser.add_argument("--parts",default="10")
    parser.add_argument("--mergers",default="qpdf,MuPDF (mutool),PyMuPDF,pikepdf,pypdf,pdfrw,PDFium (pypdfium2),pdfcpu,Apache PDFBox,pdf-lib (Node.js),PDFsharp (.NET)")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "output" / "runs")
    parser.add_argument("--qualifying-report", type=Path, help="Отчёт PASS этапа 200 для явного запуска 1000")
    parser.add_argument("--input", type=Path, help="Входной UTF-8 TXT: один 12-значный код на строку")
    parser.add_argument("--mode", choices=("both", "singles", "multipage"), default="both")
    args = parser.parse_args(argv)
    if args.qa!="full" and args.command not in ("generate","lab","pc-search"):
        parser.error("--qa vector/deferred доступен в generate и lab; исторический научный тест всегда с полной проверкой")
    try:
        if args.command == "doctor":
            from .environment import inspect_environment
            result = inspect_environment()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["core_ready"] else 2
        if args.command in ("gui","gui-browser","gui-legacy"):
            try:
                if args.command=='gui-legacy':from .batch_gui import main as gui_main
                elif args.command=='gui-browser':from .operator_web import main as gui_main
                else:from .operator_desktop import main as gui_main
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
            from .print_settings import PrintSettings
            from .execution import ExecutionOptions
            if not args.input:
                parser.error("Для команды generate требуется --input path/to/codes.txt")
            root = args.output if args.output != Path(__file__).resolve().parent.parent / "output" / "runs" else Path(__file__).resolve().parent.parent / "output" / "jobs"
            directory = run_batch(args.input, root, mode=args.mode, copies_per_value=args.copies,
                                  settings=PrintSettings(pdf_profile=args.pdf_profile),qa_mode=args.qa,activity=args.activity,timeline_mode=args.xy,
                                  duplicate_policy=args.duplicate_policy,
                                  execution=ExecutionOptions(args.backend, 1 if args.workers is None else args.workers,
                                                             32 if args.batch_size is None else args.batch_size),
                                  progress=lambda message: print(message, flush=True))
            result = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            print(directory / "manifest.json")
            return 0 if result["status"] == "COMPLETE" else 2 if result["status"] in ("LIMITED","UNVERIFIED") else 1
        if args.command=="audit":
            from .audit import audit_job
            if args.input is None: parser.error("audit --input указывает папку генерации")
            folder=audit_job(args.input)
            print(folder/"ОТЧЁТ.txt")
            status=json.loads((folder/"audit.json").read_text(encoding="utf-8"))["status"]
            return 0 if status=="COMPLETE" else 2 if status=="LIMITED" else 1
        if args.command=="pc-search":
            from .pc_search import SearchConfig,run_search
            cfg=SearchConfig(counts=tuple(map(int,args.search_counts.split(","))),repeats=args.repeats,
                cpu_units=("logical","physical") if args.cpu_unit=="both" else (args.cpu_unit,),cpu_counts=tuple(args.cpu_counts.split(",")),
                all_cpu_counts=args.all_cpu_counts,backends=tuple(args.backends.split(",")),pdf_profiles=tuple(args.pdf_profiles.split(",")),
                activities=tuple(args.activity_modes.split(",")),qa_mode=args.qa,timeline_mode=args.xy,ram_mode=args.ram_modes,
                search_mode=args.search_mode,keep_best=args.keep_best,part_counts=tuple(map(int,args.parts.split(","))),mergers=tuple(n.strip() for n in args.mergers.split(",")))
            folder=run_search(args.output,cfg,events=lambda value:print(value,flush=True))
            print(folder/"pc-search.html")
            status=json.loads((folder/"pc-search.json").read_text(encoding="utf-8"))["status"]
            return 0 if status=="COMPLETE" else 2 if status in ("UNVERIFIED","LIMITED") else 1
        if args.command == "lab":
            from .resource_lab import LabConfig, run_lab
            config=LabConfig(counts=tuple(int(n) for n in args.lab_counts.split(",")),
                cpu_counts=tuple(args.cpu_counts.split(",")),cpu_units=("logical","physical") if args.cpu_unit=="both" else (args.cpu_unit,),
                backends=tuple(args.backends.split(",")),ram_modes=tuple(args.ram_modes.split(",")),
                repeats=args.repeats,warmups=args.warmups,workers=0 if args.workers is None else args.workers,
                batch_size=1 if args.batch_size is None else args.batch_size,output_mode=args.mode,qa_mode=args.qa,timeline_mode=args.xy)
            from dataclasses import replace
            config=replace(config,pdf_profiles=tuple(args.pdf_profiles.split(",")),activity_modes=tuple(args.activity_modes.split(",")))
            default=Path(__file__).resolve().parent.parent/"output"/"runs"
            folder=run_lab(args.output if args.output!=default else default.parent/"laboratory",config,
                           progress=lambda message:print(message,flush=True))
            print(folder/"comparison.html")
            status=json.loads((folder/"lab.json").read_text(encoding="utf-8"))["status"]
            return 0 if status=="COMPLETE" else 2 if status in ("UNVERIFIED","LIMITED") else 1
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
