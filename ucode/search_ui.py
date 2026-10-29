"""One compact PC-search panel; settings are buttons, large work is user started."""
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .pc_search import SearchConfig,preview_search,run_search
from .ui_choices import ChoiceMenu,NumberSet,NumericChoiceMenu
from .ui_layout import QA_MODES
from .mergers import available_adapters


class SearchView:
    def __init__(self,app):
        self.app=app; self.valid=False; root=app.root; page=app.pages["search"]
        saved={}; self.path=app.preferences_path.with_name("pc-search-settings.json")
        try:
            saved=json.loads(self.path.read_text(encoding="utf-8"))
            axes=("counts","cpu_units","cpu_counts","backends","batches","pdf_profiles","activities","part_counts","part_modes","mergers")
            saved=asdict(SearchConfig(**{k:tuple(v) if k in axes else v for k,v in saved.items()}))
        except (OSError,TypeError,ValueError): saved={}
        def variable(key,default):
            value=saved.get(key,default)
            return tk.StringVar(master=root,value=",".join(map(str,value)) if isinstance(value,(list,tuple)) else str(value))
        self.counts=variable("counts",(200,1000,10000,100000)); self.repeats=variable("repeats",3)
        self.units=variable("cpu_units",("physical",)); self.methods=variable("backends",("serial","process","thread"))
        self.pdf=variable("pdf_profiles",("standard","compact")); self.activities=variable("activities",("normal","minimal"))
        self.batches=variable("batches",(32,)); self.parts=variable("part_counts",(10,)); self.part_modes=variable("part_modes",("sequential","parallel"))
        self.mergers=variable("mergers",tuple(row.name for row in available_adapters()))
        self.mode=variable("search_mode","staged"); self.best=variable("keep_best",2)
        self.ram=variable("ram_mode","auto")
        self.telemetry=variable("telemetry_mode","cpu")
        self.all_cpus=tk.BooleanVar(master=root,value=saved.get("all_cpu_counts",True))
        self.cpu_counts=variable("cpu_counts",tuple(app.lab_cpus.get().split(",")))
        self.plan=tk.StringVar(master=root)
        row=ttk.Frame(page); row.pack(anchor="w")
        ttk.Label(row,text="Тиражи:").pack(side="left")
        self.count_control=NumberSet(app,row,self.counts,"Выбранные тиражи",maximum=None)
        self.count_control.picker.button.pack(side="left",padx=5); self.count_control.spin.pack(side="left"); self.count_control.add_button.pack(side="left",padx=5)
        ttk.Label(row,text="Повторов:").pack(side="left",padx=5)
        app.edit(ttk.Spinbox(row,textvariable=self.repeats,from_=1,to=10,width=3)).pack(side="left")
        row=ttk.Frame(page); row.pack(anchor="w",pady=2)
        ChoiceMenu(app,row,self.units,"CPU",[("Физические ядра","physical"),("Потоки SMT","logical"),("Ядра и SMT","physical,logical")]).button.pack(side="left")
        app.edit(ttk.Checkbutton(row,text="Все количества CPU этого ПК",variable=self.all_cpus,style="Choice.TCheckbutton")).pack(side="left",padx=6)
        self.cpu_picker=ChoiceMenu(app,row,self.cpu_counts,"CPU",[(str(n),str(n)) for n in range(1,app.hardware['cpu']['available_logical']+1)]+[("Все −2","all-2"),("Все","all")],multiple=True)
        self.cpu_picker.button.pack(side="left",padx=3)
        ChoiceMenu(app,row,self.methods,"Способы",[("По очереди","serial"),("Процессы","process"),("Потоки Python","thread")],multiple=True).button.pack(side="left")
        self.ram_picker=NumericChoiceMenu(app,row,self.ram,"ОЗУ",[("Авто","auto"),("Макс. с резервом","max"),("Половина","50%"),("80% бюджета","80%")],minimum=256,maximum=max(256,(app.hardware['ram'].get('total_bytes') or 128*1024**3)//1024**2),suffix="MiB")
        self.ram_picker.button.pack(side="left",padx=5)
        row=ttk.Frame(page); row.pack(anchor="w")
        ChoiceMenu(app,row,self.mode,"Поиск",[("Отбор + крайние CPU-наборы","staged"),("Прямой PDF: все варианты","full")]).button.pack(side="left")
        ttk.Label(row,text="Лидеров:").pack(side="left",padx=5)
        app.edit(ttk.Spinbox(row,textvariable=self.best,from_=1,to=8,width=3)).pack(side="left")
        ChoiceMenu(app,row,self.pdf,"PDF",[("Обычный","standard"),("Компактный","compact")],multiple=True).button.pack(side="left",padx=6)
        ChoiceMenu(app,row,self.activities,"Расходы",[("Обычные","normal"),("Минимум","minimal")],multiple=True).button.pack(side="left")
        row=ttk.Frame(page); row.pack(anchor="w",pady=2)
        NumericChoiceMenu(app,row,self.batches,"Кодов за шаг",[(str(n),str(n)) for n in (1,8,32,128,512,1000)],multiple=True).button.pack(side="left")
        NumericChoiceMenu(app,row,self.parts,"Частей",[(str(n),str(n)) for n in (2,4,10,14,20,28,100)],multiple=True,minimum=2,maximum=1024).button.pack(side="left",padx=5)
        ChoiceMenu(app,row,self.part_modes,"Части",[("По очереди","sequential"),("Одновременно","parallel")],multiple=True).button.pack(side="left")
        ChoiceMenu(app,row,self.mergers,"Объединение",[(row.name,row.name) for row in available_adapters()],multiple=True).button.pack(side="left",padx=5)
        ChoiceMenu(app,row,self.telemetry,"CPU-замеры",[("ВКЛ","cpu"),("ВЫКЛ","off")]).button.pack(side="left")
        ttk.Label(page,textvariable=self.plan,style="Accent.TLabel",wraplength=900).pack(anchor="w",pady=3)
        ttk.Label(page,text="С галочкой — все количества CPU; без неё — выбранные здесь. Итог один PDF.",
                  style="Muted.TLabel",wraplength=900).pack(anchor="w")
        for var in (self.counts,self.repeats,self.units,self.methods,self.pdf,self.activities,self.batches,self.parts,self.part_modes,self.mergers,self.mode,self.best,self.all_cpus,self.ram,self.telemetry,self.cpu_counts):
            var.trace_add("write",lambda *_:self.refresh())
        self.refresh()

    def config(self):
        from .lab_ui import _parts
        app=self.app
        return SearchConfig(counts=tuple(int(n.replace(" ","")) for n in _parts(self.counts.get())),repeats=int(self.repeats.get()),
            cpu_units=_parts(self.units.get()),cpu_counts=_parts(self.cpu_counts.get()),all_cpu_counts=self.all_cpus.get(),
            backends=_parts(self.methods.get()),batches=tuple(map(int,_parts(self.batches.get()))),pdf_profiles=_parts(self.pdf.get()),activities=_parts(self.activities.get()),
            qa_mode=QA_MODES[app.qa_mode_var.get()],ram_mode=self.ram.get(),search_mode=self.mode.get(),keep_best=int(self.best.get()),telemetry_mode=self.telemetry.get(),
            part_counts=tuple(map(int,_parts(self.parts.get()))),part_modes=_parts(self.part_modes.get()),mergers=_parts(self.mergers.get()),print_settings=asdict(app.print_settings))

    def refresh(self):
        self.valid=False
        try:
            cfg=self.config(); plan=preview_search(cfg,self.app.hardware["cpu"])
            self.plan.set(f"Кандидатов: {plan['candidates']} · запусков до {plan['trials_upper_bound']} · место до {plan['estimated_disk_bytes']/1024**3:.1f} ГиБ (оценка с запасом).")
            self.valid=bool(plan["candidates"])
        except (ValueError,KeyError,TypeError) as exc: self.plan.set(str(exc))
        if hasattr(self.app,"generate"): self.app.update_buttons()

    def start(self):
        app=self.app
        if app.busy: return
        try:
            cfg=self.config()
            from .lab_worker import atomic_json
            self.path.parent.mkdir(parents=True,exist_ok=True); atomic_json(self.path,asdict(cfg))
            app.remember(); app.begin()
            destination=Path(app.destination_var.get() or app.output_root/"jobs")
            app.launch(lambda:run_search(destination/"search",cfg,cancel=app.cancel,events=lambda value:app.events.put(("progress",value))))
        except (OSError,ValueError) as exc: app.status_var.set(str(exc))
