"""Custom count x chosen CPU modes x repeats; no hidden matrix axes."""
from dataclasses import asdict,replace
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .affinity import select_cpus
from .resource_lab import LabConfig,build_cases,run_lab
from .trial_results import trial_rows,cpu_name,seconds_text,recommendation


def custom_config(app):
    from .lab_ui import UNITS,_parts
    from .ui_layout import QA_MODES
    try: count=int(app.lab_count_control.input.get().replace(" ","").replace("\u00a0","")); repeats=int(app.lab_repeats.get())
    except ValueError as exc: raise ValueError("Введите одно количество кодов и число повторов") from exc
    if not 1<=count<=10000: raise ValueError("Количество кодов: от 1 до 10 000")
    if not 1<=repeats<=10: raise ValueError("Повторов каждого режима: от 1 до 10")
    choices=tuple(part.lower().replace(" ","").replace("−","-").replace("все","all") for part in _parts(app.lab_cpus.get()))
    if not choices: raise ValueError("Отметьте хотя бы один режим ядер")
    choices=tuple(sorted(choices,key=lambda value:(0,int(value)) if value.isascii() and value.isdigit() else (1,0 if value=="all-2" else 1)))
    units=UNITS[app.lab_units.get()]
    largest=max(len(select_cpus(app.hardware["cpu"],unit,choice)) for unit in units for choice in choices)
    config=LabConfig(counts=(count,),cpu_counts=choices,cpu_units=units,backends=("process",),ram_modes=("auto",),
        repeats=repeats,warmups=0,batch_size=min(32,max(1,count//largest)),workers=0,output_mode="multipage",
        print_settings=asdict(app.print_settings),pdf_profiles=(app.print_settings.pdf_profile,),activity_modes=("normal",),
        qa_mode=QA_MODES[app.qa_mode_var.get()])
    for case in build_cases(config,app.hardware["cpu"]):
        if case["status"]=="SKIPPED": raise ValueError("Проверьте выбор ядер: "+case["reason"])
    return config


class TestControls:
    def __init__(self,app,parent):
        self.app=app; self.frame=ttk.Frame(parent); self.frame.pack(fill="both",expand=True)
        self.expanded=False; self.valid=False; self.rows=[]; self.page=0
        self.page_size=2 if float(app.root.tk.call("tk","scaling"))>=1.85 else 3
        self.plan=tk.StringVar(master=app.root)
        ttk.Label(self.frame,textvariable=self.plan,style="Accent.TLabel",wraplength=900).pack(anchor="w")
        self.table=ttk.Treeview(self.frame,columns=("cpu","repeat","pdf","qa","total","status"),show="headings",
                              height=self.page_size,style="History.Treeview",selectmode="none")
        for key,title,width in (("cpu","Режим CPU",175),("repeat","Повтор",65),("pdf","PDF, сек",100),
                                ("qa","QA, сек",100),("total","Всего, сек",110),("status","Итог",140)):
            self.table.heading(key,text=title); self.table.column(key,width=width,minwidth=0)
        self.table.pack(fill="both",expand=True,pady=3)
        row=ttk.Frame(self.frame); row.pack(anchor="w")
        self.previous=app.edit(ttk.Button(row,text="‹",command=lambda:self.turn(-1))); self.previous.pack(side="left")
        self.next=app.edit(ttk.Button(row,text="›",command=lambda:self.turn(1))); self.next.pack(side="left",padx=5)
        self.position=tk.StringVar(master=app.root,value="После запуска здесь будут все отдельные результаты")
        ttk.Label(row,textvariable=self.position,style="Muted.TLabel").pack(side="left",padx=7)
        self.render()

    def refresh(self):
        self.valid=False
        try:
            config=custom_config(self.app); cases=build_cases(config,self.app.hardware["cpu"])
            from .lab_ui import _count
            modes=len(cases); order=" → ".join(cpu_name(case) for case in cases)
            if len(order)>55: order=order[:52]+"…"
            self.plan.set(f"{_count(modes,('режим','режима','режимов'))} × {_count(config.repeats,('повтор','повтора','повторов'))} = {_count(modes*config.repeats,('запуск','запуска','запусков'))}. Порядок: {order}. Без прогрева.")
            self.valid=True
        except (ValueError,KeyError) as exc: self.plan.set(str(exc))
        self.update_buttons()

    def toggle(self):
        if self.app.busy: return
        self.expanded=not self.expanded
        if self.expanded:
            self.frame.pack_forget(); self.app.lab_advanced.pack(fill="both",expand=True)
            self.app.lab_options_button.configure(text="К простому управлению")
        else:
            self.app.lab_advanced.pack_forget(); self.frame.pack(fill="both",expand=True)
            self.app.lab_options_button.configure(text="Все параметры…")
        self.app.lab_refresh()

    def start(self):
        if self.app.busy: return
        if self.expanded:
            from .lab_ui import start_lab
            return start_lab(self.app)
        try:
            config=custom_config(self.app)
            from .lab_ui import read_form
            from .lab_worker import atomic_json
            try: saved=replace(read_form(self.app),counts=config.counts)
            except ValueError: saved=config
            path=self.app.preferences_path.with_name("lab-settings.json")
            path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(path,asdict(saved))
            self.rows=[]; self.page=0; self.render()
            self.app.lab_simple_run=True
            destination=Path(self.app.destination_var.get() or self.app.output_root/"jobs")
            self.app.begin()
            def event(value):
                value=dict(value)
                if "run_index" in value:
                    stage=value["stage"].split(" · ",1)[-1]
                    value["stage"]=f"Тест {value['run_index']}/{value['runs_total']} · CPU {value['cpu_count']} · повтор {value['repeat_index']}/{config.repeats} · {stage}"
                self.app.events.put(("progress",value))
            self.app.launch(lambda:run_lab(destination/"laboratory",config,cancel=self.app.cancel,events=event,
                                          progress=lambda _:self.app.events.put(("status","Подготовка следующего запуска…"))))
        except (OSError,ValueError) as exc: self.app.status_var.set(str(exc))

    def complete(self,data):
        self.rows=trial_rows(data); self.page=0; self.render()
        expected={"full":"COMPLETE","deferred":"UNVERIFIED","vector":"LIMITED"}[data["config"].get("qa_mode","full")]
        done=sum(row["status"]==expected and not row["warmup"] for row in self.rows)
        count=data["config"]["counts"][0]
        label={"COMPLETE":"ГОТОВО","UNVERIFIED":"СОЗДАНО БЕЗ ПРОВЕРКИ","LIMITED":"ПРОВЕРЕНО ЧАСТИЧНО"}.get(data["status"],data["status"])
        self.app.result_var.set(f"{label} · {count} кодов · {done} из {len(self.rows)} запусков")
        self.app.result_details.set(recommendation(data))

    def turn(self,amount):
        if not self.app.busy: self.page+=amount; self.render()

    def render(self):
        pages=max(1,(len(self.rows)+self.page_size-1)//self.page_size); self.page=max(0,min(self.page,pages-1))
        self.table.delete(*self.table.get_children())
        labels={"COMPLETE":"Пройдено","ERROR":"Ошибка","INVALID":"Ошибка QA","NOT_RUN":"Не выполнен",
                "CANCELLED":"Остановлен","SKIPPED":"Пропущен","LIMITED":"QA неполная","RESOURCE_LIMIT":"Нехватка ресурсов","UNVERIFIED":"Без проверки"}
        for row in self.rows[self.page*self.page_size:(self.page+1)*self.page_size]:
            self.table.insert("","end",values=(row["cpu"],row["repeat"],seconds_text(row["production"]),
                "Выкл." if row["qa_mode"]=="deferred" else seconds_text(row["qa"]),seconds_text(row["total"]),labels.get(row["status"],row["status"])))
        if self.rows: self.position.set(f"{self.rows[0]['count']} кодов: результаты {self.page*self.page_size+1}–{min(len(self.rows),(self.page+1)*self.page_size)} из {len(self.rows)}. Все строки — в отчёте ниже.")
        else: self.position.set("После запуска здесь будут все отдельные результаты")
        self.update_buttons()

    def update_buttons(self):
        self.previous.configure(state="normal" if not self.app.busy and self.page>0 else "disabled")
        self.next.configure(state="normal" if not self.app.busy and (self.page+1)*self.page_size<len(self.rows) else "disabled")
