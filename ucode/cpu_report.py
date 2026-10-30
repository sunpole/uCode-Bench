"""Observed own CPU statistics and paired diagnostic cost, with explicit scope."""
import csv
import html
import statistics
from pathlib import Path


def overhead_pairs(data):
    groups={}
    for case in data["cases"]:
        mode=case.get("telemetry_mode")
        if mode not in ("off","cpu"): continue
        expected={"full":"COMPLETE","vector":"LIMITED","deferred":"UNVERIFIED"}[data["config"].get("qa_mode","full")]
        trials=[t for t in case["trials"] if not t.get("warmup")]
        if len(trials)!=data["config"]["repeats"] or any(t["status"]!=expected or t.get("errors") for t in trials): continue
        times=[t.get("seconds",{}).get("launcher_wall") for t in trials]
        if not all(isinstance(t,(int,float)) and t>0 for t in times): continue
        key=tuple(str(case.get(k)) for k in ("count","cpu_unit","cpus","backend","workers","ram_mode","pdf_profile","activity","allocation","schedule","batch_size","processes_per_cpu"))
        groups.setdefault(key,{})[mode]=(case,statistics.median(times))
    rows=[]
    for group in groups.values():
        if not {"off","cpu"}<=group.keys(): continue
        off,on=group["off"],group["cpu"]
        rows.append({"off_case":off[0]["id"],"on_case":on[0]["id"],"count":off[0]["count"],
                     "off_seconds":off[1],"on_seconds":on[1],"difference_pct":100*(on[1]/off[1]-1)})
    return rows


def write_cpu_report(folder,data):
    folder=Path(folder); rows=[]
    for case in data["cases"]:
        for index,trial in enumerate(case["trials"],1):
            trace=trial.get("memory",{}).get("cpu_telemetry")
            mode=case.get("telemetry_mode",data["config"].get("telemetry_mode","cpu"))
            if not trace:
                rows.append((case["id"],case["count"],index,mode,"—","Нет замеров",None,None,None,None,None,None))
                continue
            for phase,value in trace["phases"].items():
                metrics=[("uCode: занято ядер в среднем",value["busy_core_equivalents"]),("uCode: % выбранных CPU",value["selected_cpu_load_pct"])]
                metrics.extend((cpu+" — привязанные процессы, %",stat) for cpu,stat in value["per_cpu_pct"].items())
                for label,stat in metrics:
                    stat=stat or {}
                    rows.append((case["id"],case["count"],index,mode,phase,label,stat.get("min"),stat.get("mean"),stat.get("max"),stat.get("sampled_seconds"),
                                 value["peak_busy_worker_cpus"],value["all_worker_cpus_busy_seconds"]))
    fields=("Вариант","Кодов","Повтор","Замеры CPU","Этап","Показатель","min","Среднее по времени","max интервала","Наблюдали,с","Пик занятых привязанных CPU (>=20%)","Все привязанные CPU заняты,с")
    with (folder/"cpu-load.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream); writer.writerow(fields); writer.writerows(rows)
    pairs=overhead_pairs(data); data["telemetry_overhead_pairs"]=pairs
    notes=["ЗАГРУЗКА CPU — ДАННЫЕ uCode",
           "В обычной генерации подробный сбор CPU выключен. Эти замеры выполняются только в тестах.",
           "Вся операция и каждый этап: min/среднее по времени/max наблюдаемых интервалов. 1,0 занятого ядра означает CPU-время одного полностью занятого CPU.",
           "Проценты отдельного CPU относятся только к подтверждённым процессам, привязанным к этому CPU; это не общая загрузка Windows и не загрузка всего физического ядра с обоими SMT.",
           "Пустое значение = нет атрибуции/замеров. CPU родителя/непривязанных процессов учитывается в общей нагрузке, но не приписывается произвольному ядру.",
           "Порог занятости привязанного CPU >=20% за интервал. Все заняты,с — подтверждённое время, не обещание 100% загрузки каждого ядра.",
           "Шаг наблюдения 0,5с; короткие процессы и мгновенные пики могут быть пропущены. Короткий тест не подтверждает длительную полную загрузку.",
           "A/B сравнивает ВКЛ/ВЫКЛ подробных CPU-замеров. Обязательная защита RAM/отмены остаётся в обоих режимах. Порядок, кэш и посторонняя нагрузка влияют; разница не гарантирует постоянных накладных расходов."]
    for p in pairs: notes.append(f"{p['count']} кодов: без CPU-замеров {p['off_seconds']:.3f}с ({p['off_case']}), с замерами {p['on_seconds']:.3f}с ({p['on_case']}), разница {p['difference_pct']:+.1f}%.")
    if not pairs: notes.append("Полной пары ВКЛ/ВЫКЛ пока нет; влияние сбора данных не измерено этим запуском.")
    def fmt(v): return "—" if v is None else f"{v:.3f}" if isinstance(v,float) else str(v)
    text="\n".join(notes)+"\n\n"+"\n".join(" · ".join(map(fmt,row)) for row in rows)+"\n"
    (folder/"ЗАГРУЗКА_CPU.txt").write_text(text,encoding="utf-8")
    esc=lambda v:html.escape(fmt(v))
    document='<!doctype html><html lang="ru"><meta charset="utf-8"><title>uCode — загрузка CPU</title><style>body{font:16px Segoe UI,Arial;background:#0b1220;color:#edf4fc;margin:24px}a{color:#5ce0bd}th,td{border:1px solid #31445e;padding:6px}table{border-collapse:collapse}pre{white-space:pre-wrap}.table{overflow:auto}</style><h1>Загрузка CPU</h1><pre>'+html.escape('\n'.join(notes))+'</pre><div class="table"><table><tr>'+''.join('<th>'+esc(v)+'</th>' for v in fields)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table></div><p><a href="cpu-load.csv">CSV</a> · <a href="ЗАГРУЗКА_CPU.txt">TXT</a></p></html>'
    (folder/"cpu-load.html").write_text(document,encoding="utf-8")
