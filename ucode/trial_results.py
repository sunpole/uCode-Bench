"""One row per repeat; unchecked timings stay separate from verified results."""
import csv
import html
from pathlib import Path
import statistics

from .history import case_result
from .qa_policy import LIMITED_STATUS


def cpu_name(case):
    number=len(case.get("cpus",[]))
    forms=("ядро","ядра","ядер") if case.get("cpu_unit")=="physical" else ("поток","потока","потоков")
    form=0 if number%10==1 and number%100!=11 else 1 if 2<=number%10<=4 and not 12<=number%100<=14 else 2
    label=f"{number} {forms[form]}" if number else "недоступно"
    return f"Все ({label})" if case.get("cpu_choice")=="all" else label


def trial_rows(data):
    result=[]
    for case in data["cases"]:
        warmups=[trial for trial in case["trials"] if trial.get("warmup")]
        measured=[trial for trial in case["trials"] if not trial.get("warmup")]
        planned=[(i+1,True,trial) for i,trial in enumerate(warmups)]
        planned.extend((i+1,False,measured[i] if i<len(measured) else {}) for i in range(data["config"]["repeats"]))
        for repeat,warmup,trial in planned:
            seconds=trial.get("seconds",{}); manifest=trial.get("manifest",{})
            status=trial.get("status","SKIPPED" if case.get("status")=="SKIPPED" else "NOT_RUN")
            result.append({"number":len(result)+1,"case":case["id"],"count":case["count"],"cpu":cpu_name(case),
                "repeat":repeat,"warmup":warmup,"production":seconds.get("production"),
                "qa":seconds.get("quality_checks"),"total":seconds.get("total_including_qa"),"status":status,
                "qa_mode":manifest.get("qa_mode",data["config"].get("qa_mode","full")),
                "workers":manifest.get("execution",{}).get("effective_workers"),
                "reason":"; ".join(map(str,trial.get("errors",[]))) or str(case.get("reason",""))})
    return result


def case_statistics(data):
    result=[]
    for case in data["cases"]:
        verified=case_result(case,data["config"])
        expected=LIMITED_STATUS.get(data["config"].get("qa_mode","full"),"PASS")
        if verified["status"]!=expected or not verified["summary"]: continue
        totals=[trial["seconds"]["total_including_qa"] for trial in case["trials"] if not trial.get("warmup")]
        result.append({"case":case,"cpu":cpu_name(case),"summary":verified["summary"],
                       "mean_total":statistics.mean(totals),"min_total":min(totals),"max_total":max(totals)})
    return result


def recommendation(data):
    mode=data["config"].get("qa_mode","full")
    scope={"full":"с проверкой","deferred":"без проверки","vector":"с частичной проверкой"}[mode]
    warning=" Качество PDF не проверялось." if mode=="deferred" else " Полная проверка качества не выполнялась." if mode=="vector" else ""
    valid=case_statistics(data)
    if not valid: return "Нет полного успешного набора: проверьте статусы отдельных запусков."+warning
    if len(valid)!=len(data["cases"]): return "Часть режимов не завершена; общего победителя нет."+warning
    keys={(row["case"]["count"],row["case"].get("cpu_unit"),row["case"].get("backend"),row["case"].get("ram_mode"),
           row["case"].get("pdf_profile","standard"),row["case"].get("activity","normal")) for row in valid}
    if len(keys)!=1: return "Параметры различаются; сравнивайте отдельные группы в подробном отчёте."+warning
    metric="median_with_qa_seconds" if mode=="full" else "median_operation_seconds"
    best=min(valid,key=lambda row:row["summary"][metric])
    near=[row for row in valid if row["summary"][metric]<=best["summary"][metric]*1.05]
    smaller=min(near,key=lambda row:len(row["case"].get("cpus",[])))
    label="Один замер" if data["config"]["repeats"]==1 else f"Медиана {data['config']['repeats']} замеров"
    if len(valid)>1 and len(near)>1:
        return f"Разница до 5% {scope}: можно выбрать {smaller['cpu']}. {label}."+warning
    prefix="Быстрее" if len(valid)>1 else "Полное время"
    return f"{prefix} {scope}: {best['cpu']} — {seconds_text(best['summary'][metric])} сек. {label}."+warning


def seconds_text(value): return "—" if value is None else f"{value:.3f}".replace(".",",")


def write_trial_results(folder,data):
    folder=Path(folder); rows=trial_rows(data)
    mode=data["config"].get("qa_mode","full")
    scope={"full":"Полная проверка PDF","deferred":"БЕЗ ПРОВЕРКИ PDF — качество не подтверждено","vector":"Частичная проверка PDF — структуры и матрицы, без растровых образцов"}[mode]
    headings=("№","Кодов","Режим CPU","Повтор","Прогрев","Создание PDF, сек","Проверка, сек","Всего, сек","Статус","Работников факт","Причина","Режим проверки")
    table=[(row["number"],row["count"],row["cpu"],row["repeat"],"да" if row["warmup"] else "нет",
            row["production"],row["qa"],row["total"],row["status"],row["workers"],row["reason"],row["qa_mode"]) for row in rows]
    with (folder/"all-results.csv").open("x",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream); writer.writerow(headings); writer.writerows(table)
    esc=lambda value:html.escape("—" if value is None else seconds_text(value) if isinstance(value,float) else str(value))
    summary=[]
    for item in case_statistics(data):
        summary.append((item["case"]["count"],item["cpu"],item["summary"]["median_seconds"],item["mean_total"],item["min_total"],item["max_total"]))
    def table_html(titles,values):
        return '<div class="table"><table><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in titles)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in values)+'</tbody></table></div>'
    text='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>uCode — все результаты</title><style>body{background:#0b1220;color:#edf4fc;font:16px Segoe UI,Arial;margin:24px}a{color:#5ce0bd}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #31445e;text-align:left}th{background:#21344d}.table{overflow:auto}p{max-width:1000px;line-height:1.5}</style>'
    text+=f'<h1>Все результаты: {len(rows)}</h1><p>'+esc(recommendation(data))+'</p>'
    text+='<p>'+esc(scope)+'</p>'
    text+='<p>Каждая строка — отдельный проход. Прогрев помечен отдельно и исключён из сводки. Невыполненные строки не содержат вымышленных времён. Сравнение относится только к выбранному режиму проверки, этому ПК и тиражу. UNVERIFIED и LIMITED не входят в рейтинг полной QA. Порог 5% — практическое правило выбора меньшего количества ядер, не доказательство статистического равенства.</p>'
    text+=table_html(headings,table)
    text+='<h2>Сводка завершённых режимов</h2>'+table_html(("Кодов","CPU","Создание: медиана, сек","Всего: среднее, сек","Всего: минимум, сек","Всего: максимум, сек"),summary)
    text+='<p><a href="all-results.csv">Все строки CSV</a> · <a href="comparison.html">Полные параметры и фазы</a> · <a href="ОТЧЁТ.txt">Текстовый отчёт</a></p></html>'
    with (folder/"all-results.html").open("x",encoding="utf-8") as stream: stream.write(text)
