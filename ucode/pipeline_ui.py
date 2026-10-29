"""Button menus for explicit, predictable CPU pipeline experiments."""
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .pipeline_plan import PipelineConfig,build_pipeline_cases,allocation_label
from .ui_choices import ChoiceMenu,NumberSet
from .ui_layout import QA_MODES


class PipelineView:
    def __init__(self,app):
        self.app=app; self.valid=False; self.path=app.preferences_path.with_name("pipeline-settings.json")
        saved={}
        try:
            raw=json.loads(self.path.read_text(encoding="utf-8"))
            saved=asdict(PipelineConfig(**{k:tuple(v) if k in ("counts","allocations","schedules","batches","telemetry_modes") else v for k,v in raw.items()}))
        except (OSError,ValueError,TypeError): pass
        def var(key,default):
            value=saved.get(key,default)
            return tk.StringVar(master=app.root,value=",".join(map(str,value)) if isinstance(value,(list,tuple)) else str(value))
        cpu=app.hardware["cpu"]; physical=cpu.get("available_physical") or 0; logical=cpu["available_logical"]
        self.options=[]
        for unit,number,reserve in (("physical",physical,2),("logical",logical,4)):
            if number:
                if number<=reserve: reserve=max(1,number//2)
                if number>reserve: self.options.append(f"{unit}:{number-reserve}:{reserve}")
                self.options.append(f"{unit}:{number}:0")
        default=tuple(v for v in self.options if not v.endswith(":0")) or tuple(self.options[:1])
        self.options=list(dict.fromkeys(self.options+list(saved.get("allocations",()))))
        self.counts=var("counts",(1000,)); self.allocations=var("allocations",default)
        self.schedules=var("schedules",("equal","queue")); self.batches=var("batches",(32,))
        self.repeats=var("repeats",3); self.ram=var("ram_mode","auto"); self.telemetry=var("telemetry_modes",("cpu",))
        self.unit=tk.StringVar(master=app.root,value="physical"); self.qr=tk.StringVar(master=app.root,value=max(1,physical-2)); self.pdf=tk.StringVar(master=app.root,value=min(2,max(0,physical-1)))
        self.plan=tk.StringVar(master=app.root); self.hardware=tk.StringVar(master=app.root)
        page=app.pages["pipeline"]
        ttk.Label(page,textvariable=self.hardware,style="Muted.TLabel",wraplength=900).pack(anchor="w")
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        self.count_control=NumberSet(app,row,self.counts,"Кодов в PDF",maximum=None)
        for widget in (self.count_control.picker.button,self.count_control.spin,self.count_control.add_button): widget.pack(side="left",padx=(0,4))
        self.repeat_picker=ChoiceMenu(app,row,self.repeats,"Повторов",[(str(n),str(n)) for n in range(1,11)])
        self.repeat_picker.button.pack(side="left")
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        self.alloc_picker=ChoiceMenu(app,row,self.allocations,"QR + PDF",[(allocation_label(v),v) for v in self.options],multiple=True)
        self.alloc_picker.button.pack(side="left")
        self.unit_picker=ChoiceMenu(app,row,self.unit,"Добавить",[("Ядра","physical"),("Потоки SMT","logical")]); self.unit_picker.button.pack(side="left",padx=4)
        for label,var in (("QR:",self.qr),("PDF:",self.pdf)):
            ttk.Label(row,text=label).pack(side="left",padx=(4,2))
            app.edit(ttk.Spinbox(row,textvariable=var,from_=0 if label=="PDF:" else 1,to=max(1,logical),width=3)).pack(side="left")
        self.add_button=app.edit(ttk.Button(row,text="Добавить",command=self.add)); self.add_button.pack(side="left",padx=4)
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        self.schedule_picker=ChoiceMenu(app,row,self.schedules,"Распределение",[("Равные части","equal"),("Общая очередь","queue")],multiple=True)
        self.schedule_picker.button.pack(side="left")
        self.batch_control=NumberSet(app,row,self.batches,"Кодов за шаг",maximum=1000,options=[(str(n),str(n)) for n in (1,8,32,128,512,1000)])
        self.batch_control.picker.button.pack(side="left",padx=4)
        self.batch_control.spin.configure(width=4); self.batch_control.spin.pack(side="left")
        self.batch_control.add_button.pack(side="left",padx=4)
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        ChoiceMenu(app,row,self.ram,"ОЗУ",[("Авто","auto"),("Макс. с резервом","max"),("Половина","50%")]).button.pack(side="left")
        self.telemetry_picker=ChoiceMenu(app,row,self.telemetry,"Замеры CPU",[("ВКЛ","cpu"),("ВЫКЛ","off"),("Сравнить ВКЛ/ВЫКЛ","off,cpu")]); self.telemetry_picker.button.pack(side="left",padx=4)
        ttk.Label(page,textvariable=self.plan,style="Accent.TLabel",wraplength=900).pack(anchor="w",pady=2)
        ttk.Label(page,text="Равные части: каждому свой диапазон. Очередь: следующая порция свободному. Итоговый PDF собирает один процесс.",style="Muted.TLabel",wraplength=900).pack(anchor="w")
        for var in (self.counts,self.allocations,self.schedules,self.batches,self.repeats,self.ram,self.telemetry): var.trace_add("write",lambda *_:self.refresh())
        self.refresh()

    def config(self):
        parts=lambda var:tuple(v.strip() for v in var.get().split(",") if v.strip())
        return PipelineConfig(counts=tuple(map(int,parts(self.counts))),allocations=parts(self.allocations),schedules=parts(self.schedules),
            batches=tuple(map(int,parts(self.batches))),repeats=int(self.repeats.get()),qa_mode=QA_MODES[self.app.qa_mode_var.get()],
            ram_mode=self.ram.get(),telemetry_modes=parts(self.telemetry),print_settings=asdict(self.app.print_settings))

    def add(self):
        from .pipeline_plan import partition
        try:
            token=f"{self.unit.get()}:{int(self.qr.get())}:{int(self.pdf.get())}"
            partition(self.app.hardware["cpu"],token)
            if token not in self.options: self.options.append(token)
            self.alloc_picker.set_options([(allocation_label(v),v) for v in self.options])
            self.allocations.set(",".join(dict.fromkeys(self.alloc_picker.selected()+[token])))
        except ValueError as exc: self.app.status_var.set(str(exc))

    def refresh(self):
        self.valid=False; cpu=self.app.hardware["cpu"]
        self.hardware.set(f"Этот ПК: {cpu.get('available_physical') or '?'} ядер / {cpu['available_logical']} потоков SMT. QR + PDF = CPU для кодов + CPU для страниц.")
        try:
            cfg=self.config(); cases=build_pipeline_cases(cfg,cpu); ready=[c for c in cases if c["status"]!="SKIPPED"]
            runs=len(ready)*cfg.repeats; pages=sum(c["count"] for c in ready)*cfg.repeats
            self.valid=bool(ready)
            self.plan.set(f"Вариантов: {len(ready)} · повторов каждого: {cfg.repeats} · результатов: {runs} · пропущено: {len(cases)-len(ready)} · PDF-страниц: {pages:,}".replace(","," "))
        except (ValueError,KeyError) as exc: self.plan.set(str(exc))
        if hasattr(self.app,"generate"): self.app.update_buttons()

    def start(self):
        if self.app.busy: return
        try:
            from .pipeline_lab import run_pipeline_lab
            from .lab_worker import atomic_json
            cfg=self.config(); self.path.parent.mkdir(parents=True,exist_ok=True); atomic_json(self.path,asdict(cfg))
            self.app.remember(); self.app.begin()
            destination=Path(self.app.destination_var.get() or self.app.output_root/"jobs")/"pipeline-tests"
            self.app.launch(lambda:run_pipeline_lab(destination,cfg,cancel=self.app.cancel,events=lambda value:self.app.events.put(("progress",value))))
        except (OSError,ValueError) as exc: self.app.status_var.set(str(exc))
