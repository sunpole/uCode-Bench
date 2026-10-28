"""One visible row per requested repeat; full QA gates recommendations."""
import csv
import html
from pathlib import Path
import statistics

from .history import case_result


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
                "workers":manifest.get("execution",{}).get("effective_workers"),
                "reason":"; ".join(map(str,trial.get("errors",[]))) or str(case.get("reason",""))})
    return result


def case_statistics(data):
    result=[]
    for case in data["cases"]:
        verified=case_result(case,data["config"])
        if verified["status"]!="PASS": continue
        totals=[trial["seconds"]["total_including_qa"] for trial in case["trials"] if not trial.get("warmup")]
        result.append({"case":case,"cpu":cpu_name(case),"summary":verified["summary"],
                       "mean_total":statistics.mean(totals),"min_total":min(totals),"max_total":max(totals)})
    return result


def recommendation(data):
    valid=case_statistics(data)
    if not valid: return "Нет полного успешного набора: проверьте статусы отдельных запусков."
    if len(valid)!=len(data["cases"]): return "Часть режимов не завершена с полной QA; общего победителя нет."
    keys={(row["case"]["count"],row["case"].get("cpu_unit"),row["case"].get("backend"),row["case"].get("ram_mode"),
           row["case"].get("pdf_profile","standard"),row["case"].get("activity","normal")) for row in valid}
    if len(keys)!=1: return "Параметры различаются; сравнивайте отдельные группы в подробном отчёте."
    best=min(valid,key=lambda row:row["summary"]["median_with_qa_seconds"])
    near=[row for row in valid if row["summary"]["median_with_qa_seconds"]<=best["summary"]["median_with_qa_seconds"]*1.05]
    smaller=min(near,key=lambda row:len(row["case"].get("cpus",[])))
    label="Один замер" if data["config"]["repeats"]==1 else f"Медиана {data['config']['repeats']} замеров"
    if len(valid)>1 and len(near)>1:
        return f"Разница до 5%: можно выбрать {smaller['cpu']}. {label}."
    prefix="Быстрее с проверкой" if len(valid)>1 else "Полное время с проверкой"
    return f"{prefix}: {best['cpu']} — {best['summary']['median_with_qa_seconds']:.3f} сек. {label}.".replace(".",",",1)


def seconds_text(value): return "—" if value is None else f"{value:.3f}".replace(".",",")


def write_trial_results(folder,data):
    folder=Path(folder); rows=trial_rows(data)
    headings=("№","Кодов","Режим CPU","Повтор","Прогрев","Создание PDF, сек","Проверка, сек","Всего с QA, сек","Статус","Работников факт","Причина")
    table=[(row["number"],row["count"],row["cpu"],row["repeat"],"да" if row["warmup"] else "нет",
            row["production"],row["qa"],row["total"],row["status"],row["workers"],row["reason"]) for row in rows]
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
    text+='<p>Каждая строка — отдельный проход. Прогрев помечен отдельно и исключён из сводки. Невыполненные строки не содержат вымышленных времён. Рекомендация учитывает полную QA, относится к этому ПК и тиражу. Порог 5% — практическое правило выбора меньшего количества ядер, не доказательство статистического равенства.</p>'
    text+=table_html(headings,table)
    text+='<h2>Сводка успешных режимов</h2>'+table_html(("Кодов","CPU","Создание: медиана, сек","С QA: среднее, сек","С QA: минимум, сек","С QA: максимум, сек"),summary)
    text+='<p><a href="all-results.csv">Все строки CSV</a> · <a href="comparison.html">Полные параметры и фазы</a> · <a href="ОТЧЁТ.txt">Текстовый отчёт</a></p></html>'
    with (folder/"all-results.html").open("x",encoding="utf-8") as stream: stream.write(text)
