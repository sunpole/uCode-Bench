"""Compact user-started lab form; whole series runs sequentially."""
from dataclasses import asdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .resource_lab import LabConfig, preview, run_lab
from .ui_layout import EXECUTION_METHODS,PDF_PROFILES,QA_MODES
from .affinity import select_cpus
from .ui_choices import ChoiceMenu,NumberSet

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
    if hasattr(app,"lab_unit_buttons"):
        _idle_state(app,app.lab_unit_buttons["physical"],"normal" if cpu.get("available_physical") else "disabled")
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
                style="Choice.TCheckbutton",
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
    if hasattr(app,"lab_cpu_picker"):
        numbers=range(1,cap+1) if cap else ()
        special=([("Все −2","all-2")] if cap and cap>2 else [])+[("Все","all")]
        app.lab_cpu_picker.set_options([(str(n),str(n)) for n in numbers if cap and n<=cap]+special)
        if cap is None: app.lab_cpu_picker.set_options(())
    if hasattr(app,"lab_workers_picker"):
        app.lab_workers_picker.set_options([("Автоматически","0")]+[(str(n),str(n)) for n in range(1,cpu["available_logical"]+1)])


def toggle_cpu(app,choice):
    selected=[part.lower().replace("все","all").replace("−","-").replace(" ","") for part in _parts(app.lab_cpus.get())]
    if choice in selected: selected.remove(choice)
    else: selected.append(choice)
    app.lab_cpus.set(",".join(selected))


def read_form(app):
    try:
        counts = tuple(int(value.replace(" ","").replace("\u00a0","")) for value in _parts(app.lab_counts.get()))
        cpu = tuple(value.lower().replace(" ", "").replace("−", "-").replace("все", "all") for value in _parts(app.lab_cpus.get()))
        backends = tuple(BACKENDS.get(value,value) for value in _parts(app.lab_backends.get()))
        ram = tuple(value.lower().replace("авто","auto").replace("макс","max").replace("mib","MiB") for value in _parts(app.lab_ram.get()))
        return LabConfig(counts=counts, cpu_counts=cpu, cpu_units=UNITS[app.lab_units.get()], backends=backends,
                         ram_modes=ram, repeats=int(app.lab_repeats.get()), warmups=int(app.lab_warmups.get()),
                         batch_size=int(app.lab_batch.get()), workers=int(app.lab_workers.get()),
                         output_mode=app.mode_var.get(), print_settings=asdict(app.print_settings),
                         pdf_profiles=tuple(PDF_PROFILES.get(value,value) for value in _parts(app.lab_pdf_profiles.get())),
                         qa_mode=QA_MODES[app.qa_mode_var.get()],
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
    app.lab_repeats=var("repeats",1); app.lab_warmups=var("warmups",0)
    app.lab_batch=var("batch_size",1); app.lab_workers=var("workers",0)
    app.lab_pdf_profiles=var("pdf_profiles",("standard","compact"))
    app.lab_activities=var("activity_modes",("normal","minimal"))
    app.lab_preview=tk.StringVar(master=app.root)
    app.lab_hardware=tk.StringVar(master=app.root)
    page=app.pages["lab"]
    app.lab_advanced=ttk.Frame(page)
    app.lab_choice_row=ttk.Frame(app.lab_advanced); app.lab_choice_row.pack(anchor="w")
    row=ttk.Frame(page); row.pack(anchor="w")
    ttk.Label(row,text="Количество кодов:").pack(side="left")
    app.lab_count_control=NumberSet(app,row,app.lab_counts,"Объёмы",menu_parent=app.lab_choice_row,maximum=None)
    app.lab_count_control.spin.pack(side="left",padx=(5,10))
    def count_changed(*_):
        if not app.lab_count_control.lock and (not hasattr(app,"test_controls") or not app.test_controls.expanded):
            app.lab_counts.set(app.lab_count_control.input.get())
    app.lab_count_control.input.trace_add("write",count_changed)
    ttk.Label(row,text="Повторов каждого режима:").pack(side="left")
    app.edit(ttk.Spinbox(row,textvariable=app.lab_repeats,width=4,from_=1,to=10)).pack(side="left",padx=7)
    app.lab_options_button=app.edit(ttk.Button(row,text="Все параметры…",command=lambda:app.test_controls.toggle()))
    app.lab_options_button.pack(side="left",padx=7)
    row=ttk.Frame(page); row.pack(anchor="w")
    app.lab_units_picker=ChoiceMenu(app,app.lab_choice_row,app.lab_units,"Сравнивать",[("Ядра","Физические: 1 поток/ядро"),("Потоки SMT","Логические CPU"),("Ядра и потоки","Оба варианта")])
    app.lab_units_picker.button.pack(side="left",padx=(0,8))
    app.lab_unit_buttons={}
    for key,label,value in (("physical","Ядра процессора","Физические: 1 поток/ядро"),("logical","Потоки SMT","Логические CPU")):
        button=app.edit(ttk.Radiobutton(row,text=label,value=value,variable=app.lab_units,style="Choice.TRadiobutton"))
        button.pack(side="left",padx=(0,6)); app.lab_unit_buttons[key]=button
    ttk.Label(row,textvariable=app.lab_hardware,style="Muted.TLabel",wraplength=400).pack(side="left",padx=(0,8))
    app.lab_cpu_picker=ChoiceMenu(app,row,app.lab_cpus,"Выбор",(),multiple=True)
    app.lab_cpu_picker.button.pack(side="left",padx=(0,6))
    app.lab_cpu_row=row
    app.lab_cpu_buttons={}; app.lab_cpu_vars={}
    row=app.lab_choice_row
    app.lab_pdf_picker=ChoiceMenu(app,row,app.lab_pdf_profiles,"PDF",[("Обычный","standard"),("Компактный","compact")],multiple=True)
    app.lab_activity_picker=ChoiceMenu(app,row,app.lab_activities,"Контроль",[("Обычный","normal"),("Минимум расходов","minimal")],multiple=True)
    app.lab_backend_picker=ChoiceMenu(app,row,app.lab_backends,"Способ",[("По очереди","serial"),("Параллельно","process"),("Потоки Python (опытный)","thread")],multiple=True,aliases=BACKENDS)
    for picker in (app.lab_pdf_picker,app.lab_activity_picker,app.lab_backend_picker): picker.button.pack(side="left",padx=(0,7))
    app.lab_count_control.picker.button.pack(side="left",padx=(0,6))
    app.lab_count_control.add_button.configure(text="Добавить объём")
    app.lab_count_control.add_button.pack(side="left")
    row=ttk.Frame(app.lab_advanced); row.pack(anchor="w")
    total_gib=(app.hardware["ram"].get("total_bytes") or 128*1024**3)/1024**3
    app.lab_ram_control=NumberSet(app,row,app.lab_ram,"Память",minimum=.25,maximum=max(.25,total_gib),default="2",suffix="MiB",factor=1024,
        options=[("Автоматически","auto"),("Половина безопасного","50%"),("80% безопасного","80%"),("Максимум с резервом","max")])
    app.lab_ram_control.picker.button.pack(side="left",padx=(0,8))
    ttk.Label(row,text="Свой лимит, ГиБ:").pack(side="left")
    app.lab_ram_control.spin.pack(side="left",padx=5); app.lab_ram_control.add_button.pack(side="left")
    row=ttk.Frame(app.lab_advanced); row.pack(anchor="w")
    app.lab_warmup_picker=ChoiceMenu(app,row,app.lab_warmups,"Прогрев",[("Выключен","0"),("1 пробный запуск","1"),("2 пробных запуска","2"),("3 пробных запуска","3")])
    app.lab_warmup_picker.button.pack(side="left",padx=(0,8))
    app.lab_workers_picker=ChoiceMenu(app,row,app.lab_workers,"Заданий одновременно",[("Автоматически","0")])
    app.lab_workers_picker.button.pack(side="left",padx=(0,8))
    ttk.Label(row,text="Кодов за один шаг:").pack(side="left")
    app.edit(ttk.Spinbox(row,textvariable=app.lab_batch,from_=1,to=1000,width=6)).pack(side="left",padx=5)
    app.lab_warmup_help=ttk.Label(app.lab_advanced,text="Прогрев: пробные PDF перед замерами; в итог не входят. 0 = выключен. Галочки CPU = варианты серии.",
                                style="Muted.TLabel",wraplength=850)
    app.lab_warmup_help.pack(anchor="w")
    ttk.Label(app.lab_advanced,textvariable=app.lab_preview,style="Accent.TLabel",wraplength=850).pack(anchor="w")
    app.lab_start_buttons=[]
    from .test_controls import TestControls
    app.test_controls=TestControls(app,page)
    def refresh(*_):
        refresh_cpu_buttons(app)
        eligible=False
        try:
            config=read_form(app); plan=preview(config,app.hardware)
            eligible=plan["eligible"]>0
            app.lab_preview.set(f"Вариантов: {plan['configurations']} · прогонов: {plan['runs']} · пропущено: {plan['skipped']} · место ≈ {plan['estimated_disk_bytes']/1024**3:.2f} ГиБ")
        except ValueError as exc: app.lab_preview.set(str(exc))
        app.lab_plan_valid=eligible
        app.test_controls.refresh()
        for button in app.lab_start_buttons: _idle_state(app,button,"normal" if eligible else "disabled")
        if hasattr(app,"generate"): app.update_buttons()
        if hasattr(app,"notebook"): app.fit_window()
    app.lab_refresh=refresh
    app.lab_count_control.after_sync=refresh
    for variable in (app.lab_cpus,app.lab_units,app.lab_backends,app.lab_ram,app.lab_repeats,app.lab_warmups,app.lab_batch,app.lab_workers,app.lab_pdf_profiles,app.lab_activities):
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
        app.lab_simple_run=False
        app.test_controls.rows=[]; app.test_controls.render()
        app.begin()
        app.launch(lambda: run_lab(destination/"laboratory",config,cancel=app.cancel,
                                  events=lambda value:app.events.put(("progress",value)),
                                  progress=lambda value:app.events.put(("status",value))))
    except (OSError,ValueError) as exc:
        app.status_var.set("Лаборатория: " + str(exc))
