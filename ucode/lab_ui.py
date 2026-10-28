"""Compact user-started lab form; whole series runs sequentially."""
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .resource_lab import LabConfig, preview, run_lab
from .ui_layout import EXECUTION_METHODS

UNITS = {"Логические CPU": ("logical",), "Физические: 1 поток/ядро": ("physical",), "Оба варианта": ("logical", "physical")}
BACKENDS = {label: value for label, value in EXECUTION_METHODS.items()}


def _parts(text):
    return tuple(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))


def read_form(app):
    try:
        counts = tuple(int(value) for value in _parts(app.lab_counts.get()))
        cpu = tuple(value.lower().replace(" ", "").replace("−", "-").replace("все", "all") for value in _parts(app.lab_cpus.get()))
        backends = tuple(BACKENDS.get(value,value) for value in _parts(app.lab_backends.get()))
        ram = tuple(value.lower().replace("авто","auto").replace("макс","max").replace("mib","MiB") for value in _parts(app.lab_ram.get()))
        return LabConfig(counts=counts, cpu_counts=cpu, cpu_units=UNITS[app.lab_units.get()], backends=backends,
                         ram_modes=ram, repeats=int(app.lab_repeats.get()), warmups=int(app.lab_warmups.get()),
                         batch_size=int(app.lab_batch.get()), workers=int(app.lab_workers.get()),
                         output_mode=app.mode_var.get(), print_settings=asdict(app.print_settings))
    except (ValueError, KeyError) as exc:
        raise ValueError("Проверьте списки, повторы и размеры партии: " + str(exc)) from exc


def build_lab(app):
    saved = {}
    path = app.preferences_path.with_name("lab-settings.json")
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        for key in ("counts","cpu_counts","cpu_units","backends","ram_modes"): value[key]=tuple(value[key])
        saved=asdict(LabConfig(**value))
    except (OSError, ValueError, KeyError, TypeError): pass
    def var(key, default):
        value=saved.get(key,default)
        return tk.StringVar(master=app.root,value=",".join(map(str,value)) if isinstance(value,(list,tuple)) else str(value))
    app.lab_counts=var("counts",(200,))
    app.lab_cpus=var("cpu_counts",("1","2","4","6","12","all-2","all"))
    backends=saved.get("backends",("serial","process"))
    app.lab_backends=tk.StringVar(master=app.root,value=",".join(next(label for label,key in BACKENDS.items() if key==backend) for backend in backends))
    units=tuple(saved.get("cpu_units",("logical",)))
    app.lab_units=tk.StringVar(master=app.root,value=next((label for label,value in UNITS.items() if value==units),"Логические CPU"))
    app.lab_ram=var("ram_modes",("auto",))
    app.lab_repeats=var("repeats",3); app.lab_warmups=var("warmups",0)
    app.lab_batch=var("batch_size",1); app.lab_workers=var("workers",0)
    app.lab_preview=tk.StringVar(master=app.root)
    page=app.pages["lab"]
    def entry(row,label,variable,width):
        ttk.Label(row,text=label).pack(side="left")
        app.edit(ttk.Entry(row,textvariable=variable,width=width)).pack(side="left",padx=(5,10))
    row=ttk.Frame(page); row.pack(anchor="w")
    entry(row,"Кодов:",app.lab_counts,23)
    app.edit(ttk.Button(row,text="200 / 500 / 1000 / 10000",command=lambda: app.lab_counts.set("200,500,1000,10000"))).pack(side="left")
    row=ttk.Frame(page); row.pack(anchor="w")
    entry(row,"CPU:",app.lab_cpus,27)
    app.edit(ttk.Combobox(row,textvariable=app.lab_units,values=tuple(UNITS),state="readonly",width=25),"readonly").pack(side="left")
    row=ttk.Frame(page); row.pack(anchor="w")
    entry(row,"Методы:",app.lab_backends,30)
    entry(row,"RAM:",app.lab_ram,16)
    row=ttk.Frame(page); row.pack(anchor="w")
    for label,variable,width in (("Повторы:",app.lab_repeats,3),("Прогрев:",app.lab_warmups,3),
                                 ("Партия:",app.lab_batch,5),("Работники (0=CPU):",app.lab_workers,5)):
        entry(row,label,variable,width)
    ttk.Label(page,textvariable=app.lab_preview,style="Accent.TLabel",wraplength=850).pack(anchor="w")
    row=ttk.Frame(page); row.pack(anchor="w",pady=1)
    app.edit(ttk.Button(row,text="Первый вариант",command=lambda: start_lab(app,True))).pack(side="left")
    app.edit(ttk.Button(row,text="Вся выбранная серия",command=lambda: start_lab(app,False))).pack(side="left",padx=7)
    ttk.Label(page,text="CPU: числа, all, all-2 · Методы: serial,process,thread · RAM: auto,50%,80%,max,4096MiB",
              style="Muted.TLabel",wraplength=850).pack(anchor="w")
    def refresh(*_):
        try:
            config=read_form(app); plan=preview(config,app.hardware)
            app.lab_preview.set(f"Вариантов: {plan['configurations']} · прогонов: {plan['runs']} · SKIPPED: {plan['skipped']} · место ≈ {plan['estimated_disk_bytes']/1024**3:.2f} ГиБ\n"
                                "max RAM — полезные данные с резервом ОС. Время серии пока не оценено.")
        except ValueError as exc: app.lab_preview.set(str(exc))
        if hasattr(app,"notebook"): app.fit_window()
    for variable in (app.lab_counts,app.lab_cpus,app.lab_units,app.lab_backends,app.lab_ram,app.lab_repeats,app.lab_warmups,app.lab_batch,app.lab_workers):
        variable.trace_add("write",refresh)
    refresh()


def start_lab(app, first=False):
    if app.busy: return
    try:
        config=read_form(app)
        if first:
            from dataclasses import replace
            config=replace(config,counts=config.counts[:1],cpu_counts=config.cpu_counts[:1],cpu_units=config.cpu_units[:1],
                           backends=config.backends[:1],ram_modes=config.ram_modes[:1])
        path=app.preferences_path.with_name("lab-settings.json")
        path.parent.mkdir(parents=True,exist_ok=True)
        from .lab_worker import atomic_json
        atomic_json(path,asdict(read_form(app)))
        destination=Path(app.destination_var.get()) if app.destination_var.get() else app.output_root/"jobs"
        app.begin()
        app.launch(lambda: run_lab(destination/"laboratory",config,cancel=app.cancel,
                                  events=lambda value:app.events.put(("progress",value)),
                                  progress=lambda value:app.events.put(("status",value))))
    except (OSError,ValueError) as exc:
        app.status_var.set("Лаборатория: " + str(exc))
