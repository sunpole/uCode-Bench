"""Measured lab statistics and plain TXT/CSV/HTML; failed runs cannot win."""
import csv
import html
import json
from pathlib import Path
import statistics


def summarize_trials(trials, repeats, count):
    rows = [row for row in trials if not row.get("warmup")]
    valid = len(rows) == repeats and all(row["status"] == "COMPLETE" and
            isinstance(row.get("seconds", {}).get("production"), (float, int)) and row["seconds"]["production"] > 0 for row in rows)
    if not valid:
        status = "CANCELLED" if any(row["status"] == "CANCELLED" for row in trials) else "SKIPPED" if trials and all(row["status"] == "SKIPPED" for row in trials) else "INVALID"
        return {"status": status, "median_seconds": None, "codes_per_second": None, "completed_repeats": sum(row["status"] == "COMPLETE" for row in rows)}
    values = [row["seconds"]["production"] for row in rows]
    median = statistics.median(values)
    totals = [row["seconds"].get("total_including_qa") for row in rows]
    total = statistics.median(totals) if all(isinstance(v, (float, int)) and v > 0 for v in totals) else None
    peaks = [row.get("memory", {}).get("peak_tree_rss_bytes") for row in rows]
    launchers=[row["seconds"].get("launcher_wall") for row in rows]
    launcher=statistics.median(launchers) if all(isinstance(v,(int,float)) and v>0 for v in launchers) else None
    return {"status": "PASS", "median_seconds": median, "codes_per_second": count / median,
            "min_seconds": min(values), "max_seconds": max(values), "mean_seconds": statistics.mean(values),
            "spread_seconds": max(values)-min(values), "median_with_qa_seconds": total,
            "codes_per_second_with_qa": count / total if total else None,
            "median_launcher_wall_seconds": launcher,
            "peak_observed_tree_rss_bytes": max((v for v in peaks if v is not None), default=None),
            "completed_repeats": repeats}


def recommendations(cases,group_by_ram=True):
    groups = {}
    for case in cases:
        summary = case.get("summary", {})
        if summary.get("status") == "PASS" and summary.get("median_with_qa_seconds"):
            groups.setdefault((case["count"], case["ram_mode"] if group_by_ram else "all"), []).append(case)
    result = []
    for (count, ram), rows in sorted(groups.items()):
        best = min(rows, key=lambda row: row["summary"]["median_with_qa_seconds"])
        near = [row for row in rows if row["summary"]["median_with_qa_seconds"] <= best["summary"]["median_with_qa_seconds"] * 1.05]
        def budget(row):
            values=[trial.get("ram_budget",{}).get("budget_bytes",float("inf")) for trial in row["trials"] if not trial.get("warmup")]
            return statistics.median(values) if values else float("inf")
        economical = min(near, key=lambda row: (len(row["cpus"]), budget(row), row["summary"]["median_with_qa_seconds"]))
        result.append({"count": count, "ram_mode": ram, "fastest_case": best["id"],
                       "near_best_fewer_cpus_case": economical["id"],
                       "rule": "Fewest allowed CPUs among measured results within 5% of fastest median including QA; not statistical significance"})
    return result


def write_reports(folder, data):
    folder = Path(folder)
    data["recommendations"] = recommendations(data["cases"])
    data["overall_recommendations"] = recommendations(data["cases"],False)
    from .lab_worker import atomic_json
    atomic_json(folder / "lab.json", data)
    fields = ("case", "codes", "cpu_unit", "cpu_choice", "allowed_cpu", "backend", "workers", "batch_size", "ram_mode",
              "status", "median_pdf_s", "median_with_qa_s", "codes_s", "codes_s_with_qa", "min_s", "max_s", "mean_s",
              "spread_s", "rss_peak_mib", "budget_mib", "effective_workers", "encoding_s", "pdf_write_s", "qa_s", "speedup_vs_serial_one_cpu_with_qa",
              "cpu_model", "physical_cores", "logical_cpus", "total_ram_bytes", "os", "python", "engine_version", "source_digest", "median_launcher_wall_s", "comparison_profile_sha256", "pdf_output_mode", "reason")
    baselines={}
    for case in data["cases"]:
        summary=case.get("summary",{})
        if case["backend"]=="serial" and len(case["cpus"])==1 and summary.get("status")=="PASS" and summary.get("median_with_qa_seconds"):
            baselines.setdefault((case["count"],case["ram_mode"],case["cpu_unit"]),summary["median_with_qa_seconds"])
    table = []
    for case in data["cases"]:
        summary = case.get("summary", {})
        peak = summary.get("peak_observed_tree_rss_bytes")
        successful = [trial for trial in case["trials"] if trial["status"]=="COMPLETE" and not trial.get("warmup")]
        def median_of(getter):
            values = [getter(trial) for trial in successful]
            return statistics.median(values) if values and all(v is not None for v in values) else None
        budget = median_of(lambda trial: trial.get("ram_budget",{}).get("budget_bytes"))
        effective = median_of(lambda trial: trial.get("manifest",{}).get("execution",{}).get("effective_workers"))
        encoding = median_of(lambda trial: trial["seconds"].get("code_encoding"))
        write = median_of(lambda trial: sum(trial["seconds"].get(key,0) for key in ("write_singles","write_multipage")))
        qa = median_of(lambda trial: trial["seconds"].get("quality_checks"))
        baseline=baselines.get((case["count"],case["ram_mode"],case["cpu_unit"]))
        total=summary.get("median_with_qa_seconds")
        speedup=baseline/total if baseline and total and summary.get("status")=="PASS" else None
        table.append((case["id"], case["count"], case["cpu_unit"], case["cpu_choice"], len(case["cpus"]), case["backend"],
                      case["workers"], data["config"]["batch_size"], case["ram_mode"], case["status"],
                      summary.get("median_seconds"), summary.get("median_with_qa_seconds"), summary.get("codes_per_second"),
                      summary.get("codes_per_second_with_qa"), summary.get("min_seconds"), summary.get("max_seconds"), summary.get("mean_seconds"),
                      summary.get("spread_seconds"), peak / 1024**2 if peak is not None else None,
                      budget / 1024**2 if budget is not None else None, effective, encoding, write, qa,
                      speedup,data["hardware"]["cpu"].get("name"),data["hardware"]["cpu"]["physical_cores"],
                      data["hardware"]["cpu"]["logical_processors"],data["hardware"]["ram"]["total_bytes"],
                      data.get("os"),data.get("python"),data.get("engine",{}).get("version"),data["source_digest"],summary.get("median_launcher_wall_seconds"),
                      data.get("comparison_profile_hash"),data["config"]["output_mode"],
                      case.get("reason", "")))
    with (folder / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(fields); writer.writerows(table)
    rows = ["uCode — ЛАБОРАТОРИЯ CPU / RAM", "Статус: " + data["status"],
            f"Повторы: {data['config']['repeats']}; прогрев: {data['config']['warmups']} (исключён). Ошибка QA исключает вариант из рейтинга.",
            "Производство PDF измерено до закрытия файлов; рекомендация включает QA. Старт изолированной оболочки отдельно в launcher_wall.",
            "Параллельно кодируется QR; PDF/QA последовательны. Affinity ограничивает тест, не резервирует CPU для Windows.",
            "RAM budget — разрешение для полезных данных; память не заполняется искусственно.",
            "RSS — наблюдаемый одновременный RSS дерева, shared pages могут дублироваться; короткие пики могут быть пропущены.",
            "Мониторинг включён во время. Windows job ограничивает commit дерева; Linux — sampled RSS/cooperative guard.",
            "", "CPU: "+str(data["hardware"]["cpu"].get("name")),
            f"Ядра / логические CPU: {data['hardware']['cpu']['physical_cores']} / {data['hardware']['cpu']['logical_processors']}",
            "RAM всего: "+str(data["hardware"]["ram"]["total_bytes"])+" байт; диск: "+str(data["hardware"]["disk"].get("bus")),
            "Исходники SHA-256: "+data["source_digest"],
            "PDF-профиль: "+json.dumps(data.get("comparison_profile",{}).get("print_settings",{}),ensure_ascii=False)+"; режим "+data["config"]["output_mode"],
            *["Ошибка серии: "+str(message) for message in data.get("errors",[])], "", "КОНФИГУРАЦИИ"]
    def display(value): return "—" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)
    for row in table:
        rows.append(f"{row[0]}: {row[1]} кодов · CPU {row[2]} {row[3]} ({row[4]} разрешено) · {row[5]} · RAM {row[8]} · {row[9]}")
        rows.append(f"  PDF медиана: {display(row[10])} с; с QA: {display(row[11])} с; скорость с QA: {display(row[13])} кодов/с; RSS пик: {display(row[18])} МиБ")
        rows.append(f"  RAM budget: {display(row[19])} МиБ; фактических работников: {display(row[20])}; QR / запись / QA: {display(row[21])} / {display(row[22])} / {display(row[23])} с")
        rows.append(f"  Ускорение полного времени против serial на 1 CPU: {display(row[24])}× (если такая база измерена)")
        if row[-1]: rows.append("  Причина: " + row[-1])
    rows += ["", "РЕКОМЕНДАЦИИ ПО ФАКТИЧЕСКИМ ПРОГОНАМ"]
    for rec in data["overall_recommendations"]:
        rows.append(f"{rec['count']} кодов, все выбранные RAM-режимы: быстрее {rec['fastest_case']}; экономнее в пределах 5% — {rec['near_best_fewer_cpus_case']}")
    for rec in data["recommendations"]:
        rows.append(f"{rec['count']} кодов, RAM {rec['ram_mode']}: быстрее всего {rec['fastest_case']}; меньше CPU в пределах 5% от лучшего — {rec['near_best_fewer_cpus_case']}")
    if not data["recommendations"]: rows.append("Нет полного успешного набора повторов с QA; победитель не назначен.")
    rows += ["", "Разница до 5% — эвристика удобства, не доказательство статистической значимости.",
             "Результаты относятся к этому ПК/сборке/параметрам. Проценты ускорения не экстраполируются на другие размеры.",
             "Сырые повторы, RAM budget/фактическая память, CPU affinity, фазовые времена и реальные PDF — lab.json / trials/."]
    (folder / "ОТЧЁТ.txt").write_text("\n".join(rows)+"\n", encoding="utf-8")
    headings = ("Вариант", "Кодов", "CPU тип", "CPU выбор", "CPU доступ", "Метод", "Работников", "Партия", "RAM режим",
                "Статус", "PDF медиана, с", "С QA, с", "PDF кодов/с", "С QA кодов/с", "min, с", "max, с", "mean, с", "Разброс, с", "RSS пик, МиБ", "RAM budget, МиБ", "Работники факт", "QR, с", "Запись, с", "QA, с", "Ускорение / serial1, ×",
                "CPU модель","Ядра","Логические CPU","RAM всего, байт","ОС","Python","Версия движка","Исходники SHA256","Вся оболочка, с","PDF-профиль SHA256","Режим PDF","Причина")
    header = "".join("<th>"+html.escape(title)+"</th>" for title in headings)
    body = "".join("<tr>"+"".join("<td>"+html.escape(display(value))+"</td>" for value in row)+"</tr>" for row in table)
    essential=(0,1,2,4,5,20,19,9,11,13,18,24)
    short_header="".join("<th>"+html.escape(headings[index])+"</th>" for index in essential)
    fastest={rec["fastest_case"] for rec in data["overall_recommendations"]}
    short_body="".join(('<tr style="background:#173a32">' if row[0] in fastest else '<tr>')+"".join("<td>"+html.escape(display(row[index]))+"</td>" for index in essential)+"</tr>" for row in table)
    notes = html.escape("\n".join(rows[:rows.index("КОНФИГУРАЦИИ")] + rows[rows.index("РЕКОМЕНДАЦИИ ПО ФАКТИЧЕСКИМ ПРОГОНАМ"):]))
    document = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>uCode — CPU / RAM</title><style>body{background:#0b1220;color:#edf4fc;font:15px Segoe UI,Arial;margin:24px}a{color:#5ce0bd}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #31445e;padding:7px;text-align:left;white-space:nowrap}th{background:#21344d;position:sticky;top:0}pre{white-space:pre-wrap;max-width:1100px;line-height:1.5}.table{overflow:auto;max-height:70vh}</style><h1>uCode · CPU / RAM</h1><pre>'+notes+'</pre><h2>Основные результаты</h2><p>Зелёным выделены самые быстрые успешные варианты по медиане с QA.</p><div class="table"><table><thead><tr>'+short_header+'</tr></thead><tbody>'+short_body+'</tbody></table></div><details><summary>Все фазы и параметры</summary><div class="table"><table><thead><tr>'+header+'</tr></thead><tbody>'+body+'</tbody></table></div></details><p><a href="ОТЧЁТ.txt">Понятный отчёт</a> · <a href="comparison.csv">CSV</a> · <a href="lab.json">Сырые данные</a></p></html>'
    (folder / "comparison.html").write_text(document, encoding="utf-8")
