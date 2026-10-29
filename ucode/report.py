"""M09: escaped, local reports; generation and merge results stay separate."""
from __future__ import annotations

import copy
import csv
import html
import json
import math
from pathlib import Path
import statistics

from .config import Experiment


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fmt(value, digits=4):
    return f"{value:.{digits}f}" if _number(value) else "—"


def _escape(value):
    return html.escape(str(value), quote=True)


def _display(value):
    return _escape(value if value is not None else "—")


def _normalized(result):
    result = copy.deepcopy(result)
    config = result.get("config", {})
    sources = result.get("stages", {}).get("single_files", [])
    sources_valid = len(sources) == 3 and all(
        t.get("qa", {}).get("status") == "PASS" and t.get("qa", {}).get("pages_checked") == config.get("count")
        for t in sources
    )
    for method in result.get("methods", []):
        trials = method.get("trials", [])
        valid_trials = len(trials) == 3 and all(
            t.get("qa", {}).get("status") == "PASS" and t.get("qa", {}).get("pages_checked") == config.get("count")
            and _number(t.get("seconds")) and t["seconds"] >= 0 for t in trials
        )
        source_qa_valid = method.get("category") != "merge" or sources_valid
        if method.get("status") == "PASS" and (not valid_trials or not source_qa_valid):
            method["status"] = "INVALID"
            method["reason"] = "Неполные измерения либо QA результатов/исходных PDF не PASS во всех трёх повторах. " + str(method.get("reason", ""))
        times = [t["seconds"] for t in trials if _number(t.get("seconds")) and t["seconds"] >= 0]
        method["median_seconds"] = statistics.median(times) if times else None
        method["spread_seconds"] = max(times) - min(times) if times else None
        median = method.get("median_seconds")
        method["eligible_for_1000"] = bool(
            result.get("status") == "COMPLETE" and config == Experiment().to_dict()
            and method.get("status") == "PASS" and valid_trials
            and source_qa_valid and _number(median) and 0 <= median < 120
        )
    return result


def _metric_cells(trial):
    ram = trial.get("peak_rss_bytes")
    return (
        f"<td>{_fmt(trial.get('seconds'))}</td>"
        f"<td>{_fmt(trial.get('total_seconds', trial.get('generation_total_seconds')))}</td>"
        f"<td>{_fmt(trial.get('cpu_seconds'))}</td>"
        f"<td>{_fmt(ram / 1048576 if _number(ram) else None, 2)}</td>"
        f"<td>{_display(trial.get('output_bytes'))}</td>"
    )


def _method_table(methods):
    ranked = sorted(
        [m for m in methods if m.get("status") == "PASS" and _number(m.get("median_seconds"))],
        key=lambda m: m["median_seconds"],
    )
    ranks = {id(method): index + 1 for index, method in enumerate(ranked)}
    rows = []
    for method in sorted(methods, key=lambda m: (0, m["median_seconds"]) if id(m) in ranks else (1, str(m.get("name", "")))):
        name = _escape(method.get("name", ""))
        status = _escape(method.get("status", ""))
        eligible = "Да" if method.get("eligible_for_1000") else "Нет"
        rows.append(
            f"<tr><td>{ranks.get(id(method), '—')}</td><th scope='row'>{name}</th>"
            f"<td class='{status}'>{status}</td>"
            f"<td>{_fmt(method.get('median_seconds'))}</td>"
            f"<td>{_fmt(method.get('spread_seconds'))}</td>"
            f"<td>{_display(method.get('output_bytes'))}</td><td>{eligible}</td>"
            f"<td>{_escape(method.get('reason', ''))}</td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='8'>Нет результатов</td></tr>")
    return (
        "<div class='scroll'><table><thead><tr><th>Место</th><th>Метод</th><th>Статус</th>"
        "<th>Медиана, с</th><th>max−min, с</th><th>Размер, байт</th><th>Допуск к 1000</th><th>Примечание</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _trial_table(trials):
    rows = []
    for index, trial in enumerate(trials, 1):
        qa = trial.get("qa", {})
        trial_text = json.dumps(trial, ensure_ascii=False, indent=2, default=str)
        rows.append(
            f"<tr><td>{index}</td>{_metric_cells(trial)}"
            f"<td>{_escape(qa.get('status', '—'))}</td>"
            f"<td><details><summary>Замер, область CPU/RAM и QA</summary><pre>{_escape(trial_text)}</pre></details></td>"
            f"<td>{_escape(trial.get('path', ''))}</td></tr>"
        )
    return (
        "<div class='scroll'><table><thead><tr><th>Повтор</th><th>Время метода, с</th><th>Генерация + метод, с</th><th>CPU, с</th>"
        "<th>Пик Working Set / RSS, MiB</th><th>Размер, байт</th><th>QA</th><th>Подробности</th><th>Файл</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _html(result):
    config = result.get("config", {})
    methods = result.get("methods", [])
    threshold = 120
    parts = ["<!doctype html><html lang='ru'><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>uCode — результаты QR-бенчмарка</title>",
             "<style>body{font:16px/1.5 system-ui,Segoe UI,sans-serif;margin:0;background:#f4f6f9;color:#162238}"
             "main{max-width:1400px;margin:auto;padding:28px}h1{margin-bottom:4px}h2{margin-top:32px}"
             "table{border-collapse:collapse;width:100%;background:white;font-variant-numeric:tabular-nums}"
             "th,td{text-align:left;border-bottom:1px solid #d9e0eb;padding:10px;vertical-align:top}"
             "thead{background:#e8edf5}tbody th{font-weight:600}.scroll{overflow:auto;border:1px solid #d9e0eb;border-radius:8px}"
             "pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,monospace}"
             ".PASS{color:#116239}.INVALID,.ERROR,.FAIL{color:#a52929}.SKIPPED{color:#5c687a}"
             ".intro{background:white;padding:18px;border-radius:10px;border-left:4px solid #325fca}"
             ".muted{color:#56657b}details{max-width:700px}a{color:#214da8}</style><main>",
             "<h1>uCode · QR-бенчмарк</h1>",
             f"<p class='muted'>{_escape(config.get('count', '—'))} файлов · "
             f"{_escape(config.get('repeats', '—'))} повтора · статус запуска: {_escape(result.get('status', '—'))}</p>",
             f"<p class='ERROR'>{_escape(result.get('error', ''))}</p>" if result.get("error") else "",
             "<div class='intro'><p>Обычный QR Code, уровень M, модуль 0,5 мм, свободное поле 4 модуля. "
             "PDF: векторный CMYK C0 M0 Y0 K100, страница 14,5 × 14,5 мм.</p>",
             f"<p>Допуск к 1000: все три QA PASS и медиана строго меньше {_fmt(threshold, 0)} с на 200 файлах. "
             "Этап на 1000 требует отдельного запуска.</p>",
             "<p>Acrobat: 120 с на объединение 200 готовых PDF — исходное значение пользователя; "
             "в этом запуске Acrobat не измерялся.</p></div>",
             "<h2>Объединение готовых PDF</h2><p>Время создания исходных файлов сюда не входит. "
             "В рейтинг входят только методы со статусом PASS.</p>",
             _method_table([m for m in methods if m.get("category") == "merge"]),
             "<h2>Прямая генерация</h2><p>QR-кодирование и создание многостраничного PDF. "
             "Оценивается отдельно от объединения.</p>",
             _method_table([m for m in methods if m.get("category") == "direct"]),
             "<h2>Измерения по этапам</h2>"]
    names = {"qr_encoding": "Кодирование QR", "single_files": "Создание отдельных PDF", "direct_pdf": "Прямой PDF"}
    stages = result.get("stages", {})
    for key, name in names.items():
        if stages.get(key):
            parts.extend([f"<h3>{name}</h3>", _trial_table(stages[key])])
    parts.append(f"<p>Общее время этапов и QA до сохранения отчётов, с: {_fmt(stages.get('overall_seconds'))}</p>")
    parts.append("<h2>Повторы каждого метода</h2>")
    for method in methods:
        parts.append(f"<h3>{_escape(method.get('name', ''))} · {_escape(method.get('status', ''))}</h3>")
        if method.get("trials"):
            parts.append(_trial_table(method["trials"]))
        else:
            parts.append(f"<p>{_escape(method.get('reason', 'Нет измерений'))}</p>")
    notes = result.get("notes", [])
    if notes:
        parts.append("<h2>Условия измерений и ограничения</h2><ul>")
        parts.extend(f"<li>{_escape(note)}</li>" for note in notes)
        parts.append("</ul>")
    parts.extend([
        "<p>QA выполняется вне измеряемого времени метода. CPU — процессные секунды. "
        "RAM — сохранённый ОС пик Working Set / RSS отдельного рабочего процесса; включает импорты и загрузку входов. "
        "При внешнем движке сумма индивидуальных пиков — верхняя оценка, а не одновременное потребление. "
        "Точная область CPU/RAM и дочерние процессы указаны в подробностях каждого замера.</p>",
        "<h2>Окружение</h2><pre>" + _escape(json.dumps(result.get("environment", {}), ensure_ascii=False, indent=2, default=str)) + "</pre>",
        f"<p class='muted'>Каталог запуска: {_escape(result.get('run_directory', ''))}</p>",
        "<p><a href='report.json'>JSON с полными данными</a> · <a href='report.csv'>CSV с повторами</a></p>",
        "</main></html>",
    ])
    from .graphical_report import embed_graphs
    return embed_graphs("".join(parts),result)


def write_reports(result: dict, directory: Path) -> None:
    """Write once; preserve prior runs, including existing partial reports."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"report.{extension}" for extension in ("json", "csv", "html")]
    for path in paths:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite report: {path}")
    normalized = _normalized(result)
    json_text = json.dumps(normalized, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    html_text = _html(normalized)
    with paths[0].open("x", encoding="utf-8") as stream:
        stream.write(json_text + "\n")
    fields = ["category", "name", "status", "trial", "seconds", "total_seconds", "qa_seconds", "worker_wall_seconds",
              "cpu_seconds", "cpu_scope", "peak_rss_bytes", "ram_scope", "child_cpu_seconds", "child_peak_rss_bytes", "output_bytes",
              "qa_status", "qa_json", "median_seconds", "spread_seconds", "eligible_for_1000", "reason", "path"]
    with paths[1].open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for method in normalized.get("methods", []):
            for index, trial in enumerate(method.get("trials", []) or [{}], 1):
                qa = trial.get("qa", {})
                row = {key: method.get(key, "") for key in ("category", "name", "status", "median_seconds", "spread_seconds", "eligible_for_1000", "reason")}
                row.update({key: trial.get(key, "") for key in ("seconds", "total_seconds", "qa_seconds", "worker_wall_seconds",
                           "cpu_seconds", "cpu_scope", "peak_rss_bytes", "ram_scope", "child_cpu_seconds", "child_peak_rss_bytes", "output_bytes", "path")})
                row.update(trial=index if trial else "", qa_status=qa.get("status", ""), qa_json=json.dumps(qa, ensure_ascii=False))
                writer.writerow(row)
    with paths[2].open("x", encoding="utf-8") as stream:
        stream.write(html_text)
