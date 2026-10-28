"""Compact user-started lab form; whole series runs sequentially."""
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .resource_lab import LabConfig, preview, run_lab
from .ui_layout import EXECUTION_METHODS,PDF_PROFILES
from .affinity import select_cpus

UNITS = {"Логические CPU": ("logical",), "Физические: 1 поток/ядро": ("physical",), "Оба варианта": ("logical", "physical")}
BACKENDS = {label: value for label, value in EXECUTION_METHODS.items()}


def _parts(text):
    return tuple(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))


def _idle_state(app,widget,state):
    for index,(control,_) in enumerate(app.edit_controls):
        if control is widget:
            app.edit_controls[index]=(control,state)
            break
    widget.configure(state="disabled" if app.busy else state)


def _count(value,forms):
    if value is None: return "неизвестно " + forms[2]
    form=0 if value%10==1 and value%100!=11 else 1 if 2<=value%10<=4 and not 12<=value%100<=14 else 2
    return f"{value} {forms[form]}"


def refresh_cpu_buttons(app):
    cpu=app.hardware["cpu"]; units=UNITS[app.lab_units.get()]
    app.lab_hardware.set("ПК: "+_count(cpu.get("physical_cores"),("ядро","ядра","ядер"))+" / "+
        _count(cpu.get("logical_processors"),("поток","потока","потоков"))+
        f" · доступно: {cpu.get('available_physical') or '?'} / {cpu.get('available_logical') or '?'}")
    limits=[]
    for unit in units:
        try: limits.append(len(select_cpus(cpu,unit,"all")))
        except ValueError: limits.append(None)
    cap=min(limits) if all(value is not None for value in limits) else None
    extra={value for value in (16,32) if cap and value<=cap}
    choices=tuple(str(value) for value in sorted({1,2,4,6,8,12}|extra|({cap} if cap else set())))+("all-2","all")
    if tuple(app.lab_cpu_buttons)!=choices:
        old=set(app.lab_cpu_buttons.values())
        app.edit_controls[:]=[(control,state) for control,state in app.edit_controls if control not in old]
        for control in old: control.destroy()
        app.lab_cpu_buttons={}; app.lab_cpu_vars={}
        for choice in choices:
            var=tk.BooleanVar(master=app.root)
            button=app.edit(ttk.Checkbutton(app.lab_cpu_row,variable=var,
                command=lambda key=choice:toggle_cpu(app,key)))
            button.pack(side="left",padx=(0,5))
            app.lab_cpu_buttons[choice]=button; app.lab_cpu_vars[choice]=var
    selected={part.lower().replace("все","all").replace("−","-").replace(" ","") for part in _parts(app.lab_cpus.get())}
    for choice,button in app.lab_cpu_buttons.items():
        allowed=True; numbers=[]
        for unit in units:
            try: numbers.append(str(len(select_cpus(cpu,unit,choice))))
            except ValueError: allowed=False
        text=choice if choice.isdigit() else ("Все −2" if choice=="all-2" else "Все")+" ("+("/".join(numbers) if allowed else "—")+")"
        button.configure(text=text)
        app.lab_cpu_vars[choice].set(choice in selected)
        _idle_state(app,button,"normal" if allowed else "disabled")


def toggle_cpu(app,choice):
    selected=[part.lower().replace("все","all").replace("−","-").replace(" ","") for part in _parts(app.lab_cpus.get())]
    if choice in selected: selected.remove(choice)
    else: selected.append(choice)
    app.lab_cpus.set(",".join(selected))


def read_form(app):
    try:
        counts = tuple(int(value) for value in _parts(app.lab_counts.get()))
        cpu = tuple(value.lower().replace(" ", "").replace("−", "-").replace("все", "all") for value in _parts(app.lab_cpus.get()))
        backends = tuple(BACKENDS.get(value,value) for value in _parts(app.lab_backends.get()))
        ram = tuple(value.lower().replace("авто","auto").replace("макс","max").replace("mib","MiB") for value in _parts(app.lab_ram.get()))
        return LabConfig(counts=counts, cpu_counts=cpu, cpu_units=UNITS[app.lab_units.get()], backends=backends,
                         ram_modes=ram, repeats=int(app.lab_repeats.get()), warmups=int(app.lab_warmups.get()),
                         batch_size=int(app.lab_batch.get()), workers=int(app.lab_workers.get()),
                         output_mode=app.mode_var.get(), print_settings=asdict(app.print_settings),
                         pdf_profiles=tuple(PDF_PROFILES.get(value,value) for value in _parts(app.lab_pdf_profiles.get())),
                         activity_modes=tuple(value.lower().replace("минимум","minimal").replace("обычный","normal") for value in _parts(app.lab_activities.get())))
    except (ValueError, KeyError) as exc:
        raise ValueError("Проверьте списки, повторы и размеры партии: " + str(exc)) from exc


def build_lab(app):
    saved = {}
    path = app.preferences_path.with_name("lab-settings.json")
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        value.setdefault("pdf_profiles",["standard","compact"])
        value.setdefault("activity_modes",["normal","minimal"])
        for key in ("counts","cpu_counts","cpu_units","backends","ram_modes","pdf_profiles","activity_modes"): value[key]=tuple(value[key])
        saved=asdict(LabConfig(**value))
    except (OSError, ValueError, KeyError, TypeError): pass
    def var(key, default):
        value=saved.get(key,default)
        return tk.StringVar(master=app.root,value=",".join(map(str,value)) if isinstance(value,(list,tuple)) else str(value))
    app.lab_counts=var("counts",(200,))
    app.lab_cpus=var("cpu_counts",("1",))
    backends=saved.get("backends",("serial","process"))
    app.lab_backends=tk.StringVar(master=app.root,value=",".join(next(label for label,key in BACKENDS.items() if key==backend) for backend in backends))
    units=tuple(saved.get("cpu_units",("physical",) if app.hardware["cpu"].get("available_physical") else ("logical",)))
    app.lab_units=tk.StringVar(master=app.root,value=next((label for label,value in UNITS.items() if value==units),"Логические CPU"))
    app.lab_ram=var("ram_modes",("auto",))
    app.lab_repeats=var("repeats",3); app.lab_warmups=var("warmups",0)
    app.lab_batch=var("batch_size",1); app.lab_workers=var("workers",0)
    app.lab_pdf_profiles=var("pdf_profiles",("standard","compact"))
    app.lab_activities=var("activity_modes",("normal","minimal"))
    app.lab_preview=tk.StringVar(master=app.root)
    app.lab_hardware=tk.StringVar(master=app.root)
    page=app.pages["lab"]
    def entry(row,label,variable,width):
        ttk.Label(row,text=label).pack(side="left")
        app.edit(ttk.Entry(row,textvariable=variable,width=width)).pack(side="left",padx=(5,10))
    row=ttk.Frame(page); row.pack(anchor="w")
    app.edit(ttk.Combobox(row,textvariable=app.lab_units,values=tuple(UNITS),state="readonly",width=25),"readonly").pack(side="left",padx=(0,8))
    ttk.Label(row,textvariable=app.lab_hardware,style="Muted.TLabel",wraplength=400).pack(side="left",padx=(0,8))
    app.lab_cpu_row=row
    app.lab_cpu_buttons={}; app.lab_cpu_vars={}
    row=ttk.Frame(page); row.pack(anchor="w")
    entry(row,"Кодов:",app.lab_counts,17)
    size_menu=app.edit(ttk.Menubutton(row,text="Объём ▾")); size_menu.pack(side="left",padx=(0,8))
    menu=tk.Menu(size_menu,tearoff=False); size_menu.configure(menu=menu)
    for label,value in (("200","200"),("500","500"),("1 000","1000"),("10 000","10000"),("Все объёмы","200,500,1000,10000")):
        menu.add_command(label=label,command=lambda text=value:app.lab_counts.set(text))
    entry(row,"PDF:",app.lab_pdf_profiles,17)
    entry(row,"Расходы:",app.lab_activities,14)
    row=ttk.Frame(page); row.pack(anchor="w")
    entry(row,"Методы:",app.lab_backends,22)
    entry(row,"RAM:",app.lab_ram,12)
    entry(row,"Свой CPU-набор:",app.lab_cpus,18)
    row=ttk.Frame(page); row.pack(anchor="w")
    for label,variable,width in (("Замеры (раз):",app.lab_repeats,3),("Прогрев (раз):",app.lab_warmups,3),
                                 ("Партия:",app.lab_batch,5),("Работники (0=CPU):",app.lab_workers,5)):
        if variable is app.lab_repeats or variable is app.lab_warmups:
            ttk.Label(row,text=label).pack(side="left")
            app.edit(ttk.Spinbox(row,textvariable=variable,width=width,from_=0 if variable is app.lab_warmups else 1,
                                to=3 if variable is app.lab_warmups else 10)).pack(side="left",padx=(5,10))
        else: entry(row,label,variable,width)
    app.lab_warmup_help=ttk.Label(page,text="Прогрев: пробные PDF перед замерами; в итог не входят. 0 = выключен. Галочки CPU = варианты серии.",
                                style="Muted.TLabel",wraplength=850)
    app.lab_warmup_help.pack(anchor="w")
    ttk.Label(page,textvariable=app.lab_preview,style="Accent.TLabel",wraplength=850).pack(anchor="w")
    row=ttk.Frame(page); row.pack(anchor="w",pady=1)
    app.lab_start_buttons=[]
    for text,command in (("Первый вариант",lambda:start_lab(app,True)),("Вся выбранная серия",lambda:start_lab(app,False)),
                         ("Сравнить PDF (первые)",lambda:start_lab(app,False,True))):
        button=app.edit(ttk.Button(row,text=text,command=command)); button.pack(side="left",padx=(0,7))
        app.lab_start_buttons.append(button)
    def refresh(*_):
        refresh_cpu_buttons(app)
        eligible=False
        try:
            config=read_form(app); plan=preview(config,app.hardware)
            eligible=plan["eligible"]>0
            app.lab_preview.set(f"Вариантов: {plan['configurations']} · прогонов: {plan['runs']} · пропущено: {plan['skipped']} · место ≈ {plan['estimated_disk_bytes']/1024**3:.2f} ГиБ")
        except ValueError as exc: app.lab_preview.set(str(exc))
        for button in app.lab_start_buttons: _idle_state(app,button,"normal" if eligible else "disabled")
        if hasattr(app,"notebook"): app.fit_window()
    app.lab_refresh=refresh
    for variable in (app.lab_counts,app.lab_cpus,app.lab_units,app.lab_backends,app.lab_ram,app.lab_repeats,app.lab_warmups,app.lab_batch,app.lab_workers,app.lab_pdf_profiles,app.lab_activities):
        variable.trace_add("write",refresh)
    refresh()


def start_lab(app, first=False,optimization=False):
    if app.busy: return
    try:
        config=read_form(app)
        if first or optimization:
            from dataclasses import replace
            config=replace(config,counts=config.counts[:1],cpu_counts=config.cpu_counts[:1],cpu_units=config.cpu_units[:1],
                           backends=config.backends[:1],ram_modes=config.ram_modes[:1],
                           pdf_profiles=("standard","compact") if optimization else config.pdf_profiles[:1],
                           activity_modes=("normal","minimal") if optimization else config.activity_modes[:1])
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
