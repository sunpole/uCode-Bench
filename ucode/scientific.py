"""Bounded 200 -> 1000 -> 10000 scientific runs, separate from print jobs."""
import json
from pathlib import Path
import time
from .batch import _make_directory
from .benchmark import Cancelled, load_qualifying_methods, run_experiment
from .config import Experiment
from .print_settings import format_duration
from .resources import check_resources


from .test_archive import archived_test


@archived_test
def run_scientific(output_root, size, *, cancel=None, events=None, progress=None, methods=None):
    if size not in (200, 1000, 10000, "all"):
        raise ValueError("Выберите 200, 1000, 10000 или полный тест")
    sizes = (200, 1000, 10000) if size in (10000, "all") else (200, 1000) if size == 1000 else (200,)
    check_resources(output_root, max(sizes), scientific=True)
    folder = _make_directory(output_root, "scientific")
    result = {"schema_version": 1, "kind": "scientific-3-repeat", "status": "RUNNING", "runs": [],
              "requested": size, "repeats": 3, "errors": [], "rules": "200: QA PASS + median <120 s; 1000: QA PASS before 10000"}
    started = time.perf_counter()
    progress = progress or (lambda message: None)
    completed = 0
    previous = None
    try:
        allowed = ["Direct PDF", *methods] if methods is not None else None
        for count in sizes:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Тест остановлен; результаты сохранены")
            if previous:
                allowed = load_qualifying_methods(previous, target_count=count)
                if methods is not None:
                    allowed = [name for name in allowed if name == "Direct PDF" or name in methods]
            progress(f"Научный тест {count:,}: три повтора, генерация / объединение / QA".replace(",", " "))
            def update(event):
                if events:
                    value = dict(event)
                    value["percent"] = min(99.9, 100 * (completed + count * event["percent"] / 100) / sum(sizes))
                    value["stage"] = f"{count:,} · {event['stage']}".replace(",", " ")
                    events(value)
            run = run_experiment(folder / "runs", Experiment(count=count), progress=progress, cancel=cancel,
                                 allowed_methods=allowed, events=update if events else None)
            previous = run / "report.json"
            data = json.loads(previous.read_text(encoding="utf-8"))
            result["runs"].append({"count": count, "report": str(previous.relative_to(folder)),
                                   "status": data["status"], "methods": data["methods"]})
            if data["status"] == "CANCELLED":
                raise Cancelled("Тест остановлен")
            if data["status"] != "COMPLETE":
                raise ValueError(f"Этап {count} не завершён: {data.get('error', data['status'])}")
            completed += count
        result["status"] = "COMPLETE" if all(m["status"] in ("PASS", "SKIPPED") for run in result["runs"] for m in run["methods"]) else "INVALID"
    except (Cancelled, InterruptedError) as exc:
        result.update(status="CANCELLED", errors=[str(exc)])
    except Exception as exc:
        result.update(status="ERROR", errors=[str(exc)])
    result["elapsed_seconds"] = time.perf_counter() - started
    with (folder / "scientific.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    rows = ["uCode — НАУЧНЫЙ ТЕСТ", "Статус: " + result["status"],
            "Три повтора; генерация и объединение измеряются отдельно.",
            "QA и импорты Python вне времени метода; запуск внешних движков включён.",
            "Живой мониторинг рабочего процесса включён во время наблюдаемого метода.",
            "Вся серия: " + format_duration(result["elapsed_seconds"]), ""]
    for run in result["runs"]:
        rows.append(f"{run['count']} кодов — {run['status']}")
        for method in run["methods"]:
            rows.append(f"  {method['name']}: {method['status']} · медиана {format_duration(method.get('median_seconds'))} · {method.get('reason', '')}")
        rows.append("Подробности и реальные PDF: " + run["report"])
    rows.extend(result["errors"])
    with (folder / "ОТЧЁТ.txt").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(rows))
    if events and result["status"] == "COMPLETE":
        events({"stage": "Тесты завершены", "done": completed, "total": sum(sizes), "percent": 100,
                "elapsed": time.perf_counter() - started, "speed": completed / max(.001, time.perf_counter() - started)})
    return folder
