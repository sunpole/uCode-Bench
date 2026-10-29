"""Explicitly requested 200 -> qualified 1000 suite and portable comparisons.

This module does not install engines or publish anything. It preserves both
ordinary benchmark directories and writes a separate cross-size comparison.
Only methods whose existing 200-file qualification gate succeeds run at 1000.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import html
import json
import math
from pathlib import Path
import statistics
import time
import uuid

from .benchmark import load_qualifying_methods, run_experiment
from .config import Experiment


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _median(values):
    numbers = [value for value in values if _finite(value)]
    return statistics.median(numbers) if numbers else None


def _relative(path, directory):
    """Publish only links to artifacts contained in this suite directory."""
    if not path:
        return None
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(directory.resolve()).as_posix()
    except ValueError:
        return None


def _summary(method, count, directory, report_path, missing_reason):
    if method is None:
        return {"count": count, "status": "SKIPPED", "reason": missing_reason,
                "median_seconds": None, "spread_seconds": None, "cpu_median_seconds": None,
                "peak_rss_bytes": None, "output_bytes": None, "trial_count": 0,
                "qa_pass_count": 0, "qa_pages_checked": 0, "decoded_control_count": 0,
                "seconds_per_page": None, "speedup_vs_pypdf": None, "pdf_files": [], "report_html": None}
    trials = method.get("trials", [])
    times = [trial.get("seconds") for trial in trials]
    median = _median(times)
    spread_values = [value for value in times if _finite(value)]
    ram_values = [trial.get("peak_rss_bytes") for trial in trials if _finite(trial.get("peak_rss_bytes"))]
    pdf_files = []
    for trial in trials:
        link = _relative(trial.get("path"), directory)
        if link:
            pdf_files.append(link)
    return {
        "count": count, "status": method.get("status", "ERROR"), "reason": method.get("reason", ""),
        "median_seconds": median,
        "spread_seconds": max(spread_values) - min(spread_values) if spread_values else None,
        "cpu_median_seconds": _median(trial.get("cpu_seconds") for trial in trials),
        "peak_rss_bytes": max(ram_values) if ram_values else None,
        "output_bytes": trials[-1].get("output_bytes") if trials else None,
        "trial_count": len(trials),
        "qa_pass_count": sum(trial.get("qa", {}).get("status") == "PASS" for trial in trials),
        "qa_pages_checked": sum(trial.get("qa", {}).get("pages_checked", 0) for trial in trials),
        "decoded_control_count": sum(len(trial.get("qa", {}).get("decoded_samples", [])) for trial in trials),
        "seconds_per_page": median / count if median is not None else None,
        "speedup_vs_pypdf": None,
        "pdf_files": pdf_files,
        "report_html": _relative(report_path.with_suffix(".html"), directory) if report_path else None,
    }


def build_comparison(report_200, report_1000, directory, *, path_200=None, path_1000=None,
                     missing_1000_reason="Этап 1000 не выполнялся"):
    """Project complete raw reports into stable, relative cross-size rows."""
    directory = Path(directory).resolve()
    indexed = {}
    for count, report in ((200, report_200), (1000, report_1000)):
        indexed[count] = {(m.get("category", "merge"), m.get("name", "?")): m
                          for m in (report or {}).get("methods", [])}
    keys = sorted(set(indexed[200]) | set(indexed[1000]))
    rows = []
    for category, name in keys:
        row = {"category": category, "name": name, "time_growth_1000_vs_200": None,
               "per_page_growth_1000_vs_200": None, "results": {}}
        for count, report_path in ((200, path_200), (1000, path_1000)):
            reason = missing_1000_reason if count == 1000 else "Метод отсутствует в отчёте 200"
            row["results"][str(count)] = _summary(indexed[count].get((category, name)), count, directory,
                                                 Path(report_path) if report_path else None, reason)
        small, large = row["results"]["200"], row["results"]["1000"]
        if small["status"] == large["status"] == "PASS" and _finite(small["median_seconds"]) and small["median_seconds"] > 0 and _finite(large["median_seconds"]):
            row["time_growth_1000_vs_200"] = large["median_seconds"] / small["median_seconds"]
            row["per_page_growth_1000_vs_200"] = row["time_growth_1000_vs_200"] / 5
        rows.append(row)
    # pypdf is an explicit measured baseline only inside the merger category.
    for count in ("200", "1000"):
        baseline = next((r["results"][count]["median_seconds"] for r in rows
                         if r["category"] == "merge" and r["name"] == "pypdf"
                         and r["results"][count]["status"] == "PASS"), None)
        if _finite(baseline) and baseline > 0:
            for row in rows:
                result = row["results"][count]
                if row["category"] == "merge" and result["status"] == "PASS" and _finite(result["median_seconds"]) and result["median_seconds"] > 0:
                    result["speedup_vs_pypdf"] = baseline / result["median_seconds"]
    return rows


def _fmt(value, digits=4):
    return f"{value:.{digits}f}" if _finite(value) else "—"


def _escape(value):
    return html.escape(str(value), quote=True)


def _anchor(path, label):
    return f"<a href='{_escape(path)}'>{_escape(label)}</a>" if path else "—"


def _main_table(rows):
    parts = ["<div class='scroll'><table><thead><tr><th>Метод</th><th>200: QA</th><th>200: медиана, с</th>"
             "<th>1000: QA</th><th>1000: медиана, с</th><th>Рост времени 1000/200</th>"
             "<th>Рост времени на страницу</th></tr></thead><tbody>"]
    for row in rows:
        small, large = row["results"]["200"], row["results"]["1000"]
        parts.append(f"<tr><th scope='row'>{_escape(row['name'])}</th>"
                     f"<td class='{_escape(small['status'])}'>{_escape(small['status'])}</td><td>{_fmt(small['median_seconds'])}</td>"
                     f"<td class='{_escape(large['status'])}'>{_escape(large['status'])}</td><td>{_fmt(large['median_seconds'])}</td>"
                     f"<td>{_fmt(row['time_growth_1000_vs_200'], 2)}</td>"
                     f"<td>{_fmt(row['per_page_growth_1000_vs_200'], 2)}</td></tr>")
    if not rows:
        parts.append("<tr><td colspan='7'>Нет измеренных методов</td></tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _html(result):
    parts = ["<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>uCode — сравнение 200 и 1000 QR</title>",
             "<style>body{font:16px/1.5 system-ui,Segoe UI,sans-serif;background:#f4f6f9;color:#162238;margin:0}"
             "main{max-width:1400px;margin:auto;padding:28px}table{border-collapse:collapse;width:100%;background:white;font-variant-numeric:tabular-nums}"
             "th,td{padding:10px;text-align:left;border-bottom:1px solid #d9e0eb;vertical-align:top}thead{background:#e8edf5}"
             ".scroll{overflow:auto;border:1px solid #d9e0eb;border-radius:8px}.PASS{color:#116239}.ERROR,.INVALID,.FAIL{color:#a52929}"
             ".SKIPPED{color:#5c687a}.intro{padding:16px;background:white;border-left:4px solid #325fca;border-radius:8px}"
             "h2{margin-top:32px}a{color:#214da8}li{margin:5px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><main>",
             "<h1>uCode · сравнение 200 и 1000 QR</h1>",
             f"<p>{_escape(result['created_at'])} · статус серии: {_escape(result['status'])}</p>",
             "<div class='intro'><p>Три повтора на каждом размере. Обычный QR V1-M, 12 цифр, модуль 0,5 мм, "
             "поле 4 модуля, векторный CMYK K100, страница 14,5 × 14,5 мм.</p>"
             "<p>Объединение сравнивается с объединением; прямое создание QR + PDF выделено отдельно. "
             "На 1000 переходят только методы с тремя QA PASS и медианой &lt;120 с на 200. "
             "INVALID и ERROR не считаются успешными измерениями.</p>"
             "<p>Рост времени на страницу = (время 1000 / время 200) / 5; меньше 1 означает меньшую цену страницы на 1000. "
             "Это отношение измерений, а не прогноз. Acrobat 120 с — исходное значение пользователя; Acrobat здесь не измерялся.</p></div>",
             "<h2>Объединение готовых PDF</h2>",
             _main_table([row for row in result["methods"] if row["category"] == "merge"]),
             "<h2>Прямая генерация QR + PDF</h2>",
             _main_table([row for row in result["methods"] if row["category"] == "direct"]),
             "<h2>Полные отчёты и файлы</h2><ul>"]
    for count in ("200", "1000"):
        stage = result["stages"][count]
        parts.append(f"<li>{count} файлов: {_escape(stage['status'])}; "
                     f"{_anchor(stage.get('report_html'), 'HTML-отчёт')} · {_anchor(stage.get('report_json'), 'JSON')}"
                     f" · {_anchor(stage.get('report_csv'), 'CSV')}. {_escape(stage.get('reason', ''))}</li>")
    parts.append("</ul>")
    for row in result["methods"]:
        parts.append(f"<h3>{_escape(row['name'])}</h3><div class='scroll'><table><thead><tr><th>Файлов</th><th>Статус</th>"
                     "<th>max−min, с</th><th>CPU медиана, с</th><th>RAM пик, MiB</th><th>Размер PDF, байт</th>"
                     "<th>QA PASS / повторов</th><th>Проверено страниц</th><th>Декодировано PNG</th><th>Ускорение к pypdf</th>"
                     "<th>Сохранённые PDF</th><th>Причина / примечание</th></tr></thead><tbody>")
        for count in ("200", "1000"):
            metric = row["results"][count]
            ram = metric["peak_rss_bytes"]
            pdfs = " · ".join(_anchor(path, f"Повтор {i}") for i, path in enumerate(metric["pdf_files"], 1)) or "—"
            parts.append(f"<tr><th>{count}</th><td class='{_escape(metric['status'])}'>{_escape(metric['status'])}</td>"
                         f"<td>{_fmt(metric['spread_seconds'])}</td><td>{_fmt(metric['cpu_median_seconds'])}</td>"
                         f"<td>{_fmt(ram / 1048576 if _finite(ram) else None, 2)}</td>"
                         f"<td>{_escape(metric['output_bytes'] if metric['output_bytes'] is not None else '—')}</td>"
                         f"<td>{metric['qa_pass_count']} / {metric['trial_count']}</td><td>{metric['qa_pages_checked']}</td>"
                         f"<td>{metric['decoded_control_count']}</td><td>{_fmt(metric['speedup_vs_pypdf'], 2)}</td>"
                         f"<td>{pdfs}</td><td>{_escape(metric['reason'])}</td></tr>")
        parts.append("</tbody></table></div>")
    parts.append("<h2>Условия измерений</h2><ul>")
    parts.extend(f"<li>{_escape(note)}</li>" for note in result["notes"])
    parts.extend(["</ul>", f"<p>Полный elapsed серии до записи сравнения: {_fmt(result.get('overall_seconds'), 2)} с.</p>",
                  "<p><a href='comparison.json'>Сравнение JSON</a> · <a href='comparison.csv'>Сравнение CSV</a></p>",
                  "</main></html>"])
    return "".join(parts)


def write_comparison(result, directory):
    """Write three new reports once, retaining all source experiment files."""
    directory = Path(directory)
    paths = [directory / f"comparison.{extension}" for extension in ("json", "csv", "html")]
    if any(path.exists() for path in paths):
        raise FileExistsError("Refusing to overwrite an existing suite comparison")
    json_text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    html_text = _html(result)
    with paths[0].open("x", encoding="utf-8") as stream:
        stream.write(json_text + "\n")
    fields = ["category", "name", "count", "status", "median_seconds", "spread_seconds", "cpu_median_seconds",
              "peak_rss_bytes", "output_bytes", "trial_count", "qa_pass_count", "qa_pages_checked", "decoded_control_count",
              "seconds_per_page", "speedup_vs_pypdf", "time_growth_1000_vs_200", "per_page_growth_1000_vs_200",
              "pdf_files", "report_html", "reason"]
    with paths[1].open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for method in result["methods"]:
            for count in ("200", "1000"):
                row = dict(method["results"][count])
                row.update({key: method[key] for key in ("category", "name", "time_growth_1000_vs_200", "per_page_growth_1000_vs_200")})
                row["pdf_files"] = json.dumps(row["pdf_files"], ensure_ascii=False)
                writer.writerow(row)
    with paths[2].open("x", encoding="utf-8") as stream:
        stream.write(html_text)


from .test_archive import archived_test


@archived_test
def run_suite(output_root, progress=None):
    """Run an explicitly authorized two-size experiment, keeping the QA gate."""
    progress = progress or (lambda message: None)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone(timedelta(hours=3)))
    directory = root / f"suite-200-1000-{created.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    started = time.perf_counter()
    result = {"schema_version": 1, "status": "RUNNING", "created_at": created.isoformat(),
              "requested_counts": [200, 1000], "repeats": 3, "qualifying_methods": [], "methods": [],
              "stages": {str(count): {"status": "NOT_RUN", "report_html": None, "report_json": None,
                                     "report_csv": None, "reason": ""} for count in (200, 1000)},
              "notes": ["Explicit user request authorizes this 200 -> 1000 suite; ordinary benchmark gating remains active.",
                        "Only measured values are reported; missing results are SKIPPED, never extrapolated.",
                        "Direct PDF includes QR encoding + PDF; merge timings exclude input generation.",
                        "QA, imports, input-list loading and hashes are outside method time. Three repeats, no warmup.",
                        "Python engine imports are preloaded; external CLI/JVM/Node/.NET startup and library loading are included in adapter-call time.",
                        "RAM is each fresh worker OS peak including imports/loading. External-process sums are upper bounds.",
                        "CPU is process seconds; exact scopes, all trials and QA evidence remain in per-size reports.",
                        "pypdf speedup compares PASS merger methods at the same count; direct generation is excluded.",
                        "The 120-second threshold applies only to qualification at 200; no 1000 timing is predicted."]}
    reports = {200: None, 1000: None}
    report_paths = {200: None, 1000: None}
    reason = "Этап 1000 не выполнялся"
    try:
        progress("Серия: 200 файлов, три повтора каждого доступного метода")
        run_200 = run_experiment(directory / "runs", Experiment(count=200), progress=progress)
        report_paths[200] = Path(run_200) / "report.json"
        reports[200] = json.loads(report_paths[200].read_text(encoding="utf-8"))
        result["stages"]["200"]["status"] = reports[200].get("status", "ERROR")
        if reports[200].get("status") != "COMPLETE":
            raise ValueError("Этап 200 не завершён: " + str(reports[200].get("error", reports[200].get("status"))))
        methods = load_qualifying_methods(report_paths[200])
        result["qualifying_methods"] = methods
        progress("Допуск к 1000 подтверждён: " + ", ".join(methods))
        run_1000 = run_experiment(directory / "runs", Experiment(count=1000), progress=progress, allowed_methods=methods)
        report_paths[1000] = Path(run_1000) / "report.json"
        reports[1000] = json.loads(report_paths[1000].read_text(encoding="utf-8"))
        result["stages"]["1000"]["status"] = reports[1000].get("status", "ERROR")
        result["status"] = "COMPLETE" if reports[1000].get("status") == "COMPLETE" else "PARTIAL"
        if result["status"] == "PARTIAL":
            reason = str(reports[1000].get("error", "Этап 1000 завершился с ошибкой"))
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        result["status"] = "PARTIAL"
        result["error"] = reason
        progress("Серия сохранена с ограничением: " + reason)
    finally:
        if reports[1000] is None:
            result["stages"]["1000"].update(status="SKIPPED", reason=reason)
        for count in (200, 1000):
            path = report_paths[count]
            if path:
                for extension, field in (("html", "report_html"), ("json", "report_json"), ("csv", "report_csv")):
                    result["stages"][str(count)][field] = _relative(path.with_suffix("." + extension), directory)
        result["methods"] = build_comparison(reports[200], reports[1000], directory,
                                              path_200=report_paths[200], path_1000=report_paths[1000],
                                              missing_1000_reason=reason)
        result["has_invalid_results"] = any(metric["status"] in ("INVALID", "ERROR")
                                             for method in result["methods"] for metric in method["results"].values())
        result["overall_seconds"] = time.perf_counter() - started
        write_comparison(result, directory)
        progress(f"{result['status']}: {directory / 'comparison.html'}")
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description="uCode: явно запрошенная серия 200 + допущенные 1000 QR")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "output" / "comparisons")
    args = parser.parse_args(argv)
    directory = run_suite(args.output, progress=lambda message: print(message, flush=True))
    result = json.loads((directory / "comparison.json").read_text(encoding="utf-8"))
    print(directory / "comparison.html")
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
