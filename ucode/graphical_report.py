"""Offline, read-only projections of measured trials. No PDF access or new QA."""
import hashlib
import html
import json
import math
from pathlib import Path
import statistics
import uuid

MAX_ROWS = 4096
MAX_JSON = 64 * 1024**2
EXPECTED = {"full": {"PASS", "COMPLETE"}, "deferred": {"UNVERIFIED"}, "vector": {"LIMITED"}}


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def stats(values):
    if not values or not all(number(v) for v in values):
        return None
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _phases(trial, kind, strategy):
    s = trial.get("seconds", {})
    wall = s.get("launcher_wall")
    if not number(wall):
        return None
    if kind == "cpu-pipeline-lab":
        # QR/PDF service sums overlap; only measured pipeline wall can stack.
        values = {"Конвейер QR + PDF": s.get("production"), "Проверка": s.get("quality_checks")}
    elif strategy == "split":
        values = {"Создание частей": s.get("parts_creation"), "Объединение": s.get("merge"), "Проверка": s.get("quality_checks")}
    else:
        writes = [s.get(k) for k in ("write_singles", "write_multipage") if k in s]
        values = {"Кодирование QR": s.get("code_encoding"), "Запись PDF": sum(writes) if writes and all(number(v) for v in writes) else None,
                  "Проверка": s.get("quality_checks")}
    if not all(number(v) for v in values.values()) or sum(values.values()) > wall + 1e-6:
        return None
    values["Подготовка, запуск и прочее"] = max(0, wall - sum(values.values()))
    return values


def _cpu(trials):
    phases = {}
    for t in trials:
        trace = t.get("memory", {}).get("cpu_telemetry") or {}
        for phase, values in trace.get("phases", {}).items():
            stat = values.get("selected_cpu_load_pct") or {}
            if all(number(stat.get(k)) for k in ("min", "mean", "max", "sampled_seconds")) and stat["sampled_seconds"] > 0:
                phases.setdefault(phase, []).append(stat)
    result = {}
    for phase, values in phases.items():
        duration = sum(v["sampled_seconds"] for v in values)
        result[phase] = {"min": min(v["min"] for v in values), "mean": sum(v["mean"] * v["sampled_seconds"] for v in values) / duration,
                         "max": max(v["max"] for v in values), "sampled_seconds": duration, "observed_repeats": len(values)}
    return result or None


def _label(case):
    parts = [str(case.get("id", case.get("name", "Вариант")))]
    if case.get("allocation"):
        unit, qr, pdf = case["allocation"].split(":")
        parts.append(("ядра " if unit == "physical" else "SMT ") + qr + " QR + " + pdf + " PDF")
    elif case.get("cpu_choice"):
        parts.append(str(case["cpu_choice"]) + (" ядер" if case.get("cpu_unit") == "physical" else " CPU"))
    names = {"queue": "очередь", "equal": "равные части", "process": "процессы", "thread": "потоки Python", "serial": "последовательно"}
    for key in ("backend", "schedule"):
        if key in case and case[key] != "pipeline":
            parts.append(names.get(case[key], str(case[key])))
    if case.get("batch_size"):
        parts.append("порция " + str(case["batch_size"]))
    if "processes_per_cpu" in case:
        parts.append(str(case["processes_per_cpu"])+" процессов на CPU · всего "+str(case.get("workers","?")))
    if case.get("strategy") == "split":
        parts.append(str(case.get("part_count")) + " частей / " + str(case.get("part_mode")) + " / " + str(case.get("merger")))
    for key in ("pdf_profile", "activity", "ram_mode"):
        if key in case:
            parts.append(str(case[key]))
    return " · ".join(parts)


def chart_model(data):
    """Keep scopes/QA/count/diagnostics/source separate; never infer a speed curve."""
    if "archive_schema" in data:
        data = data.get("data", {})
    groups = {}; omitted = 0; seen = 0

    def add(node, case, path, scientific=False):
        nonlocal seen, omitted
        seen += 1
        if seen > MAX_ROWS:
            omitted += 1
            return
        cfg = node.get("config", {})
        count = case.get("count", cfg.get("count"))
        if type(count) is not int or count <= 0:
            return
        kind = node.get("kind", "scientific")
        qa = "full" if scientific else case.get("qa_mode", cfg.get("qa_mode", "full"))
        diagnostics = case.get("telemetry_mode", cfg.get("telemetry_mode", "off"))
        trials = [t for t in case.get("trials", []) if not t.get("warmup")]
        repeats = cfg.get("repeats", 3)
        status = case.get("status", "UNKNOWN")
        allowed = EXPECTED.get(qa, set())
        scope = ("Объединение готовых PDF, без QA" if case.get("category") == "merge" else "Прямое создание PDF, без QA") if scientific else "Весь запуск, с выбранной проверкой"
        if scientific:
            values = [t.get("seconds") for t in trials]
            good = status == "PASS" and all(t.get("qa", {}).get("status") == "PASS" and not t.get("qa", {}).get("errors") and not t.get("errors") for t in trials)
        else:
            values = [t.get("seconds", {}).get("launcher_wall") for t in trials]
            good = status in allowed and all(t.get("status") in allowed and not t.get("errors") for t in trials)
        good = good and len(trials) == repeats and bool(trials) and all(number(v) and v > 0 for v in values)
        # Group identity deliberately includes the command/source/profile, never a cross-PC rating.
        key = json.dumps([path, kind, count, qa, diagnostics, cfg.get("timeline_mode","off"), scope, node.get("source_digest"), node.get("comparison_profile_hash", node.get("profile_hash")), cfg.get("output_mode"), cfg.get("print_settings")], sort_keys=True)
        group = groups.setdefault(key, {"id": hashlib.sha256(key.encode()).hexdigest()[:16], "count": count, "qa": qa,
            "diagnostics": diagnostics, "scope": scope, "source": str(node.get("source_digest", "не указан"))[:16],
            "label": f"{path} · {count:,} кодов · {qa} · CPU-замеры {diagnostics} · XY {cfg.get('timeline_mode','off')} · {scope}".replace(",", " "), "rows": []})
        phase_values = [_phases(t, kind, case.get("strategy")) for t in trials] if good and not scientific else []
        phase_keys = list(phase_values[0]) if phase_values and all(phase_values) else []
        phases = {k: statistics.mean(v[k] for v in phase_values) for k in phase_keys}
        if scientific:
            ram = [t.get("peak_rss_bytes") for t in trials]; pdf = [t.get("output_bytes") for t in trials]
        else:
            ram = [t.get("memory", {}).get("peak_tree_rss_bytes") for t in trials]; pdf = [t.get("pdf_bytes") for t in trials]
        def units(values, divisor):
            return stats([v / divisor for v in values]) if good and all(number(v) for v in values) else None
        row = {"id": str(case.get("id", case.get("name", "Вариант"))), "label": _label(case), "status": status,
               "eligible": good, "reason": str(case.get("reason") or ("" if good else "Нет полного корректного набора повторов с требуемыми временами и статусами")),
               "wall": stats(values) if good else None,
               "speed": {"median": count / statistics.median(values), "min": count / max(values), "max": count / min(values)} if good else None,
               "ram": units(ram, 1024**2), "pdf": units(pdf, 1024**2), "phases": phases or None,
               "cpu": _cpu(trials) if good and not scientific else None,
               "trials": [{"repeat": i, "status": t.get("status", t.get("qa", {}).get("status", "?")),
                           "seconds": values[i-1] if number(values[i-1]) else None} for i, t in enumerate(trials, 1)]}
        group["rows"].append(row)

    def visit(node, path, depth=0):
        if depth > 8:
            return
        for case in node.get("cases", []):
            add(node, case, path)
        for method in node.get("methods", []):
            # comparison.json stores scale summaries instead of raw repetitions.
            if isinstance(method.get("results"), dict):
                continue
            add(node, method, path, True)
        for i, run in enumerate(node.get("runs", []), 1):
            nested = run.get("result") or {"config": {"count": run.get("count"), "repeats": 3}, "methods": run.get("methods", [])}
            visit(nested, path + f" / {i}", depth + 1)

    visit(data, "Серия")
    from .xy_report import timeline_views
    timelines,omitted_timelines=timeline_views(data)
    return {"schema": 2, "status": str(data.get("status", "UNKNOWN")), "groups": list(groups.values()), "omitted": omitted,
            "timelines":timelines,"omitted_timelines":omitted_timelines}


def graphical_section(data):
    """Embed one dependency-free component. Data never becomes HTML or JS source."""
    from .graphical_template import TEMPLATE
    from .xy_template import XY_FUNCTION
    model = chart_model(data)
    payload = json.dumps(model, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return TEMPLATE.replace("__XY_FUNCTION__",XY_FUNCTION).replace("__GRAPH_DATA__", payload)


def embed_graphs(document, data):
    """Add graphics after the title, without rewriting measurements or tables."""
    if data.get("status") == "RUNNING":
        return document
    position = document.find("</h1>")
    if position < 0:
        return graphical_section(data) + document
    position += len("</h1>")
    return document[:position] + graphical_section(data) + document[position:]


def write_graphical_copy(source, destination):
    """New immutable view of a bounded JSON snapshot; historical files stay intact."""
    source = Path(source)
    with source.open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError("Отчёт больше 64 МиБ")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-отчёт uCode")
    if "archive_schema" in data:
        data = data["data"]
    # Reuse archive filtering: copied views need neither payloads nor machine paths.
    from .test_archive import sanitize
    data = sanitize(data)
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    path = destination / ("graphs-" + uuid.uuid4().hex + ".html")
    title = "uCode — графические результаты теста"
    document = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + title + '</title><body style="margin:24px;background:#0b1220;color:#edf4fc;font:16px Segoe UI,Arial;overflow-wrap:anywhere"><h1>' + title + '</h1><p>Сохранённый результат; повторная генерация и проверка PDF не выполнялись. SHA-256 исходного JSON: ' + hashlib.sha256(raw).hexdigest() + '</p>'
    document += graphical_section(data) + '<details><summary>Параметры и все сохранённые измерения</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></details></body></html>'
    with path.open("x", encoding="utf-8") as stream:
        stream.write(document)
    return path


def cli_main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog="uCode graphs", description="Графики сохранённого теста без запуска и повторной QA")
    parser.add_argument("--input", type=Path, required=True, help="lab/pipeline/pc-search/commands/scientific/report.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]/"output"/"graphical-reports")
    args = parser.parse_args(argv)
    print(write_graphical_copy(args.input, args.output))
    return 0
