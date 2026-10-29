"""Predictable user-selected pipeline matrix and local per-repeat reports."""
from dataclasses import asdict
import csv
import html
import json
from pathlib import Path
import statistics
import time
from urllib.parse import quote

from .batch import _make_directory
from .hardware import inspect_hardware
from .pipeline_plan import build_pipeline_cases,allocation_label
from .lab_worker import atomic_json


def run_pipeline_lab(output_root,config,*,cancel=None,events=None):
    from .resource_lab import _run_trial
    from .frozen_runtime import snapshot_runtime,assert_trial_integrity
    from .history import _quality_pass
    from .qa_policy import limited_trial
    from .lab_report import summarize_trials
    from .engines import get_engine
    hardware=inspect_hardware(output_root); cases=build_pipeline_cases(config,hardware["cpu"])
    folder=_make_directory(output_root,"pipeline"); started=time.perf_counter()
    frozen=snapshot_runtime(folder)
    total=sum(c["status"]!="SKIPPED" for c in cases)*config.repeats; finished=0
    data={"kind":"cpu-pipeline-lab","schema_version":1,"status":"RUNNING","config":asdict(config),"hardware":hardware,
          "source_digest":frozen["source_digest"],"cases":cases,"errors":[],"planned_runs":total}
    expected={"full":"COMPLETE","vector":"LIMITED","deferred":"UNVERIFIED"}[config.qa_mode]
    try:
        for case in cases:
            if case["status"]=="SKIPPED": continue
            case["status"]="RUNNING"; write_pipeline_report(folder,data)
            for repeat in range(config.repeats):
                if cancel is not None and cancel.is_set(): raise InterruptedError("Серия конвейера остановлена")
                request={**frozen,**{k:v for k,v in case.items() if k not in ("trials","status","reason")},
                         "strategy":"pipeline","backend":"process","workers":len(case["qr_cpus"]),"cpu_unit":case["cpu_unit"],
                         "warmup":False,"output_mode":"multipage","ram_mode":config.ram_mode,"qa_mode":config.qa_mode,
                         "print_settings":config.print_settings,"engine_version":get_engine().info().version}
                def event(value):
                    if events: events({**value,"stage":case["id"]+f" · повтор {repeat+1}/{config.repeats} · "+value["stage"],
                                       "percent":min(99.9,100*(finished+value["percent"]/100)/max(1,total))})
                trial=_run_trial(folder/"trials"/f"{case['id']}-{repeat+1:02d}",request,cancel,event)
                case["trials"].append(trial); finished+=1
                assert_trial_integrity(trial)
                if trial["status"]=="CANCELLED": raise InterruptedError("Серия конвейера остановлена")
                good=_quality_pass(trial,case["count"],"multipage") if config.qa_mode=="full" else limited_trial(trial,case["count"],config.qa_mode,"multipage")
                good=good and not trial.get("errors")
                if trial["status"]==expected and not good: trial.update(status="INVALID",errors=["Нет требуемых доказательств качества/тиража"])
                if trial["status"] in ("SKIPPED","RESOURCE_LIMIT"): break
                write_pipeline_report(folder,data)
            case["summary"]=summarize_trials(case["trials"],config.repeats,case["count"],qa_mode=config.qa_mode)
            case["status"]=case["summary"]["status"]
            case["reason"]="; ".join(str(e) for t in case["trials"] for e in t.get("errors",[]))
            write_pipeline_report(folder,data)
        statuses={c["status"] for c in cases}
        valid={"PASS" if config.qa_mode=="full" else expected,"SKIPPED"}
        data["status"]=("COMPLETE" if config.qa_mode=="full" else expected) if statuses<=valid and finished else "PARTIAL"
    except InterruptedError as exc: data.update(status="CANCELLED",errors=[str(exc)])
    except Exception as exc: data.update(status="ERROR",errors=[type(exc).__name__+": "+str(exc)])
    finally:
        for case in cases:
            if case["status"]=="RUNNING": case["status"]=data["status"]
        data["elapsed_seconds"]=time.perf_counter()-started
        write_pipeline_report(folder,data)
    if events and data["status"] in ("COMPLETE","LIMITED","UNVERIFIED"):
        events({"stage":"PDF и отчёты сохранены","percent":100,"done":finished,"total":total,"speed":0,"unit":"запусков"})
    return folder


def write_pipeline_report(folder,data):
    from .cpu_report import write_cpu_report
    from .print_settings import format_duration
    folder=Path(folder); write_cpu_report(folder,data)
    rows=[]; summary=[]; data["winners"]=[]
    fmt=lambda v:"—" if v is None else f"{v:.4f}" if isinstance(v,float) else str(v)
    label={"equal":"Равные части","queue":"Общая очередь"}
    for case in data["cases"]:
        for repeat,trial in enumerate(case["trials"],1):
            seconds=trial.get("seconds",{}); info=trial.get("manifest",{}).get("execution",{})
            pdf_name=trial.get("manifest",{}).get("files",{}).get("multipage",{}).get("name")
            row=(case["id"],case["count"],allocation_label(case["allocation"]),label[case["schedule"]],case["batch_size"],repeat,case["telemetry_mode"],
                 trial["status"],seconds.get("launcher_wall"),seconds.get("production"),seconds.get("quality_checks"),
                 case["count"]/seconds["launcher_wall"] if seconds.get("launcher_wall") else None,
                 trial.get("pdf_bytes"),trial.get("memory",{}).get("peak_tree_rss_bytes"),
                 seconds.get("qr_service_sum"),seconds.get("pdf_service_sum"),seconds.get("assembler_active"),
                 info.get("max_pending_values"),len(info.get("worker_pids",[])),"; ".join(trial.get("errors",[])))
            rows.append(row)
            if pdf_name and trial.get("job"): trial["pdf_link"]=(Path("trials")/trial["folder"]/trial["job"]/pdf_name).as_posix()
        s=case.get("summary",{}); wall=s.get("median_launcher_wall_seconds")
        summary.append((case["id"],case["count"],allocation_label(case["allocation"]),label[case["schedule"]],case["batch_size"],case["telemetry_mode"],case["status"],
                        wall,s.get("median_seconds"),case["count"]/wall if wall else None,
                        min((t["seconds"]["launcher_wall"] for t in case["trials"]),default=None),max((t["seconds"]["launcher_wall"] for t in case["trials"]),default=None),case.get("reason","")))
    expected="PASS" if data["config"]["qa_mode"]=="full" else {"vector":"LIMITED","deferred":"UNVERIFIED"}[data["config"]["qa_mode"]]
    for count in sorted(set(c["count"] for c in data["cases"])):
        for mode in data["config"]["telemetry_modes"]:
            good=[c for c in data["cases"] if c["count"]==count and c["telemetry_mode"]==mode and c.get("summary",{}).get("status")==expected and c["summary"].get("median_launcher_wall_seconds")]
            if good:
                best=min(good,key=lambda c:c["summary"]["median_launcher_wall_seconds"])
                data["winners"].append({"count":count,"telemetry_mode":mode,"case":best["id"],"median_seconds":best["summary"]["median_launcher_wall_seconds"]})
    fields=("Вариант","Кодов","QR+PDF CPU","Распределение","Кодов за шаг","Повтор","CPU-замеры","Статус","Весь запуск,с","Создание PDF,с","Проверка,с","Кодов/с всего","PDF,байт","Пик RSS дерева,байт","QR: сумма времени процессов,с","PDF: сумма времени процессов,с","Сборщик: активное время,с","Макс. ожидающих значений","Подтверждено процессов","Ошибка")
    with (folder/"pipeline.csv").open("w",encoding="utf-8-sig",newline="") as out:
        writer=csv.writer(out); writer.writerow(fields); writer.writerows(rows)
    notes=["uCode — СРАВНЕНИЕ КОНВЕЙЕРА CPU", "Статус: "+data["status"],
        "QR + PDF: слева CPU для кодирования, справа для геометрии/сжатия страниц. PDF=0: каждый QR-процесс выполняет полный цикл.",
        "Окончательный сборщик один; он разделяет CPU этапа PDF (или общего пула при PDF=0). Это не дополнительное ядро.",
        "Физические ядра: по одному логическому CPU каждого ядра. SMT: логические CPU делят ресурсы физических ядер; 24+4 не равно 28 физическим ядрам.",
        "Равные части: фиксированный диапазон каждому процессу обоих этапов. Общая очередь: свободный процесс берёт следующую порцию.",
        "Кодов за шаг — размер ограниченного пакета передачи в обоих режимах, а не число процессов. Исходный порядок страниц сохраняется.",
        "Главная метрика — весь запуск (запуск процессов, подготовка TXT, создание PDF, выбранная QA, завершение). Скорость = кодов / всё время.",
        "QR/PDF суммы времени процессов перекрываются: их нельзя складывать и сравнивать с полным временем. Активное время сборщика не включает ожидание процессов/хвост xref.",
        "PDF: общий MediaBox/Resources в дереве страниц, координаты рассчитываются один раз на процесс, геометрия и Flate-сжатие выполняются параллельно.",
        "ОЗУ хранит полезные ограниченные пакеты, без принудительного заполнения. Резерв ОС и защита ресурсов сохраняются; min/среднее/max CPU — в отдельном отчёте.",
        "Без проверки: UNVERIFIED, QA=0. Частичная проверка: LIMITED. Полная: векторы всех страниц и растровые образцы; любой сбой исключает вариант.",
        "Прогрев выключен. Повторов: "+str(data["config"]["repeats"])+". Один повтор и маленькая разница не доказывают устойчивого превосходства.",
        "Лучшие — только среди завершённых выбранных вариантов этого ПК и одинакового режима CPU-замеров. Режимы ВКЛ/ВЫКЛ ранжируются отдельно.",
        "Для неполной/прерванной серии сравнение всех выбранных вариантов не получено. Старые файлы и результаты сохранены."]
    for case in data["cases"]:
        if case.get("shared_physical_cores"): notes.append(case["id"]+": QR/PDF делят физическое ядро из-за выбранной границы SMT: "+str(case["shared_physical_cores"]))
    for w in data["winners"]: notes.append(f"{w['count']} кодов, CPU-замеры {w['telemetry_mode']}: {w['case']}, медиана {w['median_seconds']:.4f} с.")
    notes.extend("Ошибка: "+str(e) for e in data.get("errors",[]))
    notes.append("Общее время серии: "+format_duration(data.get("elapsed_seconds",0)))
    text="\n".join(notes)+"\n\n"+"\n".join(" · ".join(map(fmt,row)) for row in summary)+"\n"
    (folder/"ОТЧЁТ.txt").write_text(text,encoding="utf-8")
    esc=lambda value:html.escape(fmt(value))
    def table(headers,values): return '<div class="scroll"><table><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in values)+'</table></div>'
    document='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>uCode — конвейер CPU</title><style>body{font:16px Segoe UI,Arial;background:#0b1220;color:#edf4fc;margin:24px}a{color:#5ce0bd}th,td{border:1px solid #31445e;padding:7px}table{border-collapse:collapse}pre{white-space:pre-wrap}.scroll{overflow:auto}</style><h1>Конвейер CPU: QR + PDF</h1><p><strong>'+esc(data["status"])+'</strong> · '+esc(data["config"]["qa_mode"])+'</p>'
    if data["status"] not in ("COMPLETE","LIMITED","UNVERIFIED"): document+='<p>Серия не завершена: сравнение всех выбранных вариантов ещё не получено.</p>'
    document+=table(("Вариант","Кодов","QR+PDF CPU","Распределение","Кодов за шаг","CPU-замеры","Статус","Медиана всего,с","Медиана создания,с","Кодов/с всего","min всего,с","max всего,с","Причина"),summary)
    document+='<p><a href="cpu-load.html">Загрузка CPU: min / среднее / max</a></p><h2>Каждый повтор</h2>'+table(fields,rows)+'<h2>PDF</h2>'
    document+="<br>".join('<a href="'+quote(t["pdf_link"])+'">'+esc(c["id"]+f" · повтор {i}")+'</a>' for c in data["cases"] for i,t in enumerate(c["trials"],1) if t.get("pdf_link"))
    document+='<h2>Методика</h2><pre>'+html.escape('\n'.join(notes))+'</pre><a href="pipeline.csv">CSV</a> · <a href="ОТЧЁТ.txt">TXT</a></html>'
    (folder/"pipeline.html").write_text(document,encoding="utf-8")
    atomic_json(folder/"pipeline.json",data)
