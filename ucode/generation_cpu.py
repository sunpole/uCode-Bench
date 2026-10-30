"""Visible production CPU selection; each encoder process gets one verified CPU."""
import tkinter as tk
from tkinter import ttk
from .affinity import select_cpus
from .execution import ExecutionOptions
from .ui_choices import ChoiceMenu


def execution_options(preferences,hardware):
    cpus=() if preferences.cpu_choice=="legacy" else tuple(select_cpus(hardware["cpu"],preferences.cpu_unit,preferences.cpu_choice))
    if cpus and (preferences.execution_backend!="process" or preferences.workers!=len(cpus)):
        raise ValueError("Настройки ядер изменились; выберите число ядер ещё раз")
    return ExecutionOptions(preferences.execution_backend,preferences.workers,preferences.batch_size,cpus,preferences.cpu_unit,preferences.ram_mode)


class GenerationCPU:
    def __init__(self,app,page):
        self.app=app; self.syncing=False
        p=app.generation_preferences
        self.choice=tk.StringVar(master=app.root,value=p.cpu_choice)
        self.unit=tk.StringVar(master=app.root,value=p.cpu_unit)
        self.ram=tk.StringVar(master=app.root,value=p.ram_mode)
        self.summary=tk.StringVar(master=app.root)
        row=ttk.Frame(page); row.grid(row=6,column=0,sticky="w",pady=(5,1))
        ttk.Label(row,text="QR:").pack(side="left")
        self.unit_picker=ChoiceMenu(app,row,self.unit,"CPU",[("Ядра","physical"),("SMT","logical")],command=self.change_unit)
        self.unit_picker.button.pack(side="left",padx=3)
        self.buttons={}
        for key in ("1","all-2","all"):
            b=app.edit(ttk.Radiobutton(row,variable=self.choice,value=key,style="Choice.TRadiobutton",command=self.select))
            b.pack(side="left",padx=3); self.buttons[key]=b
        self.picker=ChoiceMenu(app,row,self.choice,"Другое",(),command=self.select)
        self.picker.button.pack(side="left",padx=4)
        ChoiceMenu(app,row,self.ram,"ОЗУ",[("Авто","auto"),("Макс. с резервом","max")],command=lambda:(app.refresh_plan(),app.remember())).button.pack(side="left",padx=4)
        ttk.Label(row,text="PDF: 1 процесс",style="Muted.TLabel").pack(side="left",padx=4)
        # Old serial/28 means one task, never 28 cores. Migrate its actual mode.
        if self.choice.get()=="legacy" and p.execution_backend in ("serial","process"):
            n=1 if p.execution_backend=="serial" else p.workers
            maximum=app.hardware["cpu"].get("available_physical") or 0
            self.unit.set("physical" if n<=maximum else "logical")
            self.choice.set(str(n))
        self.refresh()
        if self.choice.get()!="legacy": self.select(save=False)
        for var in (app.backend_var,app.workers_var): var.trace_add("write",self.advanced_changed)

    def refresh(self):
        cpu=self.app.hardware["cpu"]
        for choice,b in self.buttons.items():
            try:
                n=len(select_cpus(cpu,self.unit.get(),choice))
                b.configure(text=("1 ядро" if self.unit.get()=="physical" else "1 поток") if choice=="1" else f"{'Все −2' if choice=='all-2' else 'Все'} ({n})")
                state="normal"
            except ValueError: b.configure(text="Все −2" if choice=="all-2" else "Все" if choice=="all" else "1 ядро"); state="disabled"
            for i,(widget,_) in enumerate(self.app.edit_controls):
                if widget is b: self.app.edit_controls[i]=(widget,state)
            b.configure(state="disabled" if self.app.busy else state)
        cap=cpu.get("available_physical" if self.unit.get()=="physical" else "available_logical") or 0
        self.picker.set_options([(f"{n} {'ядер' if self.unit.get()=='physical' else 'потоков SMT'}",str(n)) for n in range(1,cap+1)]+[("Ручные настройки","legacy")])

    def select(self,save=True):
        if self.app.busy: return
        if self.choice.get()=="legacy":
            self.app.refresh_plan()
            if save: self.app.remember()
            return
        try:
            cpus=select_cpus(self.app.hardware["cpu"],self.unit.get(),self.choice.get())
            self.syncing=True
            self.app.backend_var.set("Процессы"); self.app.workers_var.set(str(len(cpus)))
        except ValueError as exc: self.app.status_var.set(str(exc))
        finally: self.syncing=False
        self.app.refresh_plan()
        self.app.status_var.set(f"QR: {self.app.workers_var.get()} отдельных процессов · запись PDF: 1 процесс · загрузка CPU измеряется в тестах")
        if save: self.app.remember()

    def change_unit(self):
        try: select_cpus(self.app.hardware["cpu"],self.unit.get(),self.choice.get())
        except ValueError: self.choice.set("all")
        self.refresh(); self.select()

    def advanced_changed(self,*_):
        if not self.syncing:
            self.choice.set("legacy")
            self.app.refresh_plan()
