"""Traceable PC-search report: wall time, phases, quality, and incomplete coverage."""
import csv
import html
import json
from pathlib import Path
import statistics
from urllib.parse import quote
from .trial_results import cpu_name

METHODS={"serial":"По очереди","process":"Процессы","thread":"Потоки Python"}
STATUSES={"PASS":"Пройдено","COMPLETE":"Пройдено","LIMITED":"Частично проверен","UNVERIFIED":"Без проверки","INVALID":"Ошибка QA",
          "ERROR":"Ошибка","RESOURCE_LIMIT":"Недостаточно ресурсов","CANCELLED":"Остановлен","SKIPPED":"Недоступен","NOT_RUN":"Не запускался"}


def strategy_text(case):
    if case.get("strategy")=="split":
        mode="одновременно" if case["part_mode"]=="parallel" else "по очереди"
        return f"{case['part_count']} частей {mode} + {case['merger']} → один PDF"
    return "Один PDF напрямую"


def phases(trial,strategy):
    seconds=trial.get("seconds",{}); wall=seconds.get("launcher_wall")
    if not isinstance(wall,(int,float)) or wall<=0: return {}
    values=({"Создание частей":seconds.get("parts_creation",0),"Объединение":seconds.get("merge",0)} if strategy=="split" else
            {"Кодирование QR":seconds.get("code_encoding",0),"Запись PDF":seconds.get("write_multipage",0)})
    values["Проверка"]=seconds.get("quality_checks",0)
    values={key:value for key,value in values.items() if isinstance(value,(int,float)) and value>=0}
    values["Подготовка, запуск и прочее"]=max(0,wall-sum(values.values()))
    return values


def report_summary(data):
    from .pc_search import SearchConfig,choose_leaders
    value=data["config"]; axes=("counts","cpu_units","cpu_counts","backends","batches","pdf_profiles","activities","part_counts","part_modes","mergers")
    config=SearchConfig(**{key:tuple(val) if key in axes else val for key,val in value.items()})
    winners=[]
    for count in sorted(set(config.counts)):
        leaders=choose_leaders([case for case in data["cases"] if case["count"]==count],config)
        if not leaders: continue
        best=leaders[0]; totals=[row["seconds"]["launcher_wall"] for row in best["trials"]]
        phase_rows=[phases(row,best.get("strategy")) for row in best["trials"]]
        times={key:statistics.median([row[key] for row in phase_rows]) for key in phase_rows[0]}
        bottleneck=max(times,key=times.get)
        winners.append({"count":count,"case":best["id"],"median_seconds":statistics.median(totals),"min_seconds":min(totals),"max_seconds":max(totals),
                        "mean_seconds":statistics.mean(totals),"bottleneck":bottleneck,"phases":times,"status":best["status"],
                        "strategy":strategy_text(best),"cpu_count":len(best["cpus"]),"cpu_unit":best["cpu_unit"],"cpu_label":cpu_name(best),"backend":best["backend"]})
    return winners


def write_search_report(folder,data):
    from .cpu_report import write_cpu_report
    write_cpu_report(folder,data)
    from .lab_worker import atomic_json
    folder=Path(folder); data["winners"]=report_summary(data); atomic_json(folder/"pc-search.json",data)
    def number(value): return "—" if value is None else f"{value:.3f}".replace(".",",") if isinstance(value,float) else str(value)
    rows=[]
    for case in data["cases"]:
        for index in range(data["config"]["repeats"]):
            trial=case["trials"][index] if index<len(case["trials"]) else {}
            seconds=trial.get("seconds",{}); memory=trial.get("memory",{})
            phase=phases(trial,case.get("strategy")); status=trial.get("status","SKIPPED" if case["status"]=="SKIPPED" else "NOT_RUN")
            rows.append((case["id"],case["count"],strategy_text(case),"Ядра" if case["cpu_unit"]=="physical" else "Потоки SMT",len(case["cpus"]),METHODS[case["backend"]],case["batch_size"],case["pdf_profile"],case["activity"],
                         index+1,seconds.get("launcher_wall"),seconds.get("code_encoding"),seconds.get("write_multipage"),seconds.get("parts_creation"),seconds.get("merge"),seconds.get("quality_checks"),
                         phase.get("Подготовка, запуск и прочее"),memory.get("observed_cpu_seconds"),memory.get("peak_tree_rss_bytes"),trial.get("pdf_bytes"),trial.get("storage_total_bytes"),trial.get("manifest",{}).get("parts",{}).get("concurrency"),STATUSES.get(status,status),
                         "; ".join(map(str,trial.get("errors",[]))) if trial else case.get("reason","")))
    fields=("Вариант","Кодов","Способ","CPU тип","CPU разрешено","Кодирование","Кодов за шаг","PDF","Расходы","Повтор","Полное время,с","QR,с (сумма)","Запись PDF,с (сумма)",
            "Части — полное время,с","Объединение,с","Проверка,с","Подготовка/запуск/прочее,с","CPU-сек наблюд.","RSS пик,байт","Итоговый PDF,байт","Каталог запуска,байт","Частей одновременно","Статус","Причина")
    with (folder/"pc-search.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream); writer.writerow(fields); writer.writerows(rows)
    mode=data["config"]["qa_mode"]
    scope={"full":"Полная проверка PDF включена.","vector":"Только частичная проверка PDF; результат LIMITED.","deferred":"БЕЗ ПРОВЕРКИ PDF: качество не подтверждено, результаты UNVERIFIED."}[mode]
    notes=["uCode — ПОДБОР НА ЭТОМ ПК","Статус: "+data["status"],scope,
           "Самый быстрый — только среди фактически завершённых корректных вариантов этого ПК/тиража/сборки.",
           "Поэтапный поиск переносит лидеров и крайние CPU-наборы каждого способа на следующие размеры; остальные там не проверены." if data["config"]["search_mode"]=="staged" else "Полный перебор выбранных параметров прямой генерации; это не все возможные библиотеки/алгоритмы.",
           "Разбивка: лучший измеренный профиль прямой генерации для каждого тиража/типа CPU, максимальный выбранный CPU-набор и все выбранные движки/числа частей/способы. Остальные сочетания профилей разбивки не проверяются.",
           f"Повторы:{data['config']['repeats']}; прогрев выключен. Полное время включает запуск, подготовку, PDF и выбранную проверку.",
           "Один повтор — предварительный замер. Разница менее5% не доказывает устойчивого превосходства.",
           "В каждом варианте один итоговый PDF. Части создаются заново в каждом повторе; объединение и финальная QA входят во время.",
           "Для параллельных частей QR/запись в CSV — суммы перекрывающихся времен; для распределения полного времени используется фактическая длительность создания частей.",
           "CPU — разрешённый набор, не доказательство полной загрузки. Частей одновременно не больше их числа и разрешённых CPU; последовательный кодировщик в каждой части использует один поток.",
           "Самая долгая фаза не доказывает причину: запись PDF включает CPU/сжатие/IO. CPU/RSS наблюдаемые, короткие процессы/пики могут быть пропущены; shared RSS может считаться повторно.",
           "При нехватке RAM/диска вариант не получает победу. Пропущенные/непроверенные варианты не объявляются медленнее.",
           "", "РЕЗУЛЬТАТЫ"]
    for winner in data["winners"]:
        notes.append(f"{winner['count']} кодов: {winner['case']}, {winner['strategy']}, {winner['cpu_label']}, {METHODS[winner['backend']]}.")
        notes.append(f"  Медиана {number(winner['median_seconds'])}с; min/max {number(winner['min_seconds'])}/{number(winner['max_seconds'])}с; статус {winner['status']}.")
        notes.append("  Больше всего времени: "+winner["bottleneck"]+". "+"; ".join(f"{key}: {number(value)}с" for key,value in winner["phases"].items()))
    if not data["winners"]: notes.append("Корректного полного набора замеров для рекомендации пока нет.")
    notes.extend("Ошибка: "+str(value) for value in data.get("errors",[]))
    for stage in data["stages"]:
        notes.append(f"Тираж{stage['count']}: проверено{stage['tested']} конфигураций; не перепроверено после отбора{stage['not_retested_after_screen']}.")
    notes += ["", "ПОКРЫТИЕ И ИНСТРУМЕНТЫ", "Генераторы QR: "+", ".join(row["name"] for row in data["catalog"]["encoders"]),
              "Реализованные способы кодирования: serial/process/thread; параллельное создание отдельных частей — через независимые процессы."]
    for item in data["catalog"]["mergers"]:
        notes.append(f"{item['name']} · {item.get('family',item['name'])} · {item.get('language','?')}: {'доступен' if item['available'] else 'SKIPPED'}; {item.get('version')}; {item.get('reason','')}")
    for item in data["catalog"]["candidates"]:
        notes.append(f"{item['name']}: {'установлен' if item['installed'] else 'не установлен'}; НЕ ПОДКЛЮЧЁН; {item['reason']}")
    notes += [data["catalog"]["interpreters"]["reason"]+"; адаптер не подключён.","Исходники SHA256: "+data["source_digest"],
              "Старые результаты сохранены. Сырые повторы/пути/метрики: pc-search.json; все строки: pc-search.csv."]
    notes.append("Загрузка CPU min/среднее/max по этапам и привязанным процессам: cpu-load.html, ЗАГРУЗКА_CPU.txt, cpu-load.csv.")
    (folder/"ОТЧЁТ.txt").write_text("\n".join(notes)+"\n",encoding="utf-8")
    esc=lambda value:html.escape(number(value))
    def table(titles,values):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(value)+'</th>' for value in titles)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in row)+'</tr>' for row in values)+'</tbody></table></div>'
    summary=[(w["count"],w["case"],w["strategy"],w["cpu_label"],w["median_seconds"],w["min_seconds"],w["max_seconds"],w["bottleneck"],STATUSES.get(w["status"],w["status"])) for w in data["winners"]]
    document='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>uCode — подбор на ПК</title><style>body{background:#0b1220;color:#edf4fc;font:16px Segoe UI,Arial;margin:24px}a{color:#5ce0bd}table{border-collapse:collapse}th,td{padding:8px;border:1px solid #31445e;text-align:left}th{background:#21344d}.scroll{overflow:auto}pre{white-space:pre-wrap;line-height:1.5}</style><h1>Подбор на этом ПК</h1><p>'+esc(scope)+'</p>'
    from .pc_search import SearchConfig,choose_leaders
    config=SearchConfig(**{k:tuple(v) if k in ("counts","cpu_units","cpu_counts","backends","batches","pdf_profiles","activities","part_counts","part_modes","mergers") else v for k,v in data["config"].items()})
    complete=choose_leaders(data["cases"],config)
    allowed=", ".join(map(str,sorted({len(c["cpus"]) for c in complete}))) or "нет"
    state="СЕРИЯ НЕ ЗАВЕРШЕНА — сравнение всех вариантов не получено" if data["status"] not in ("COMPLETE","UNVERIFIED","LIMITED") else "Серия завершена"
    document+='<p><strong>'+esc(state)+'</strong> · '+esc(data["status"])+'</p><p>Полные корректные варианты: '+esc(len(complete))+'. Разрешённые CPU-наборы этих вариантов: '+esc(allowed)+'. Фактическая загрузка — в отдельном отчёте CPU.</p>'
    if data.get("errors"): document+='<p style="color:#ffb6a3">'+esc('; '.join(data["errors"]))+'</p>'
    document+='<h2>Лучшие среди завершённых вариантов</h2>'
    document+=table(("Кодов","Вариант","Способ","CPU","Медиана,с","min,с","max,с","Дольше всего","Качество"),summary)
    document+='<p><a href="cpu-load.html">Загрузка CPU: min / среднее / max</a></p><h2>Все отдельные запуски</h2>'+table(fields,rows)
    document+='<h2>Методика, ограничения и доступность</h2><pre>'+html.escape('\n'.join(notes))+'</pre><p><a href="pc-search.csv">CSV</a> · <a href="ОТЧЁТ.txt">Отчёт TXT</a></p>'
    links=[]
    for case in data["cases"]:
        for trial in case["trials"]:
            name=trial.get("manifest",{}).get("files",{}).get("multipage",{}).get("name")
            if name and trial.get("job"):
                path=Path(trial["relative_folder"])/trial["job"]/name
                links.append('<a href="'+quote(path.as_posix())+'">'+html.escape(case["id"]+' · PDF')+'</a>')
    document+='<details><summary>Готовые PDF</summary>'+"<br>".join(links)+'</details></html>'
    from .graphical_report import embed_graphs
    (folder/"pc-search.html").write_text(embed_graphs(document,data),encoding="utf-8")
