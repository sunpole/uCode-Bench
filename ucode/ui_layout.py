"""Compact Tk layout; business operations remain in BatchWindow."""
from tkinter import ttk
import tkinter as tk
from pathlib import Path
from .ui_theme import COLORS, apply_dark_theme
from .ui_choices import ChoiceMenu

POLICIES = {"Сохранить строки": "preserve", "Только уникальные": "unique"}
EXECUTION_METHODS = {"Последовательно": "serial", "Процессы": "process", "Потоки (GIL)": "thread"}
PDF_PROFILES={"Обычный":"standard","Компактный":"compact"}
QA_MODES={"Полная":"full","Без растра":"vector","Отложена":"deferred"}


def build_window(app, help_text):
    root = app.root
    app.style = apply_dark_theme(root)
    root.title("uCode — QR / PDF · кнопочные настройки")
    root.protocol("WM_DELETE_WINDOW", app.close)
    app.edit_controls = []
    body = ttk.Frame(root, padding=(14, 8))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(3, weight=1)
    header = ttk.Frame(body)
    header.grid(row=0, column=0, sticky="ew")
    ttk.Label(header, text="uCode", style="Title.TLabel").pack(side="left")
    ttk.Label(header, text="QR  /  PDF", style="Accent.TLabel").pack(side="left", padx=12)
    ttk.Label(header, text=f"{app.engine_info.name} {app.engine_info.version}",
              style="Muted.TLabel").pack(side="right")
    toolbar = ttk.Frame(body)
    toolbar.grid(row=2, column=0, sticky="ew", pady=(5, 5))
    app.menus = []
    base = app.menu(toolbar, "База TXT")
    base.add_command(label="Открыть TXT…", command=app.choose)
    base.add_command(label="Проверить выбранный файл", command=app.inspect_input)
    create = app.menu(toolbar, "Создать номера")
    for count in (200, 1000, 10000):
        create.add_command(label=f"{count:,}".replace(",", " "), command=lambda n=count: app.template(n))
    create.add_separator()
    create.add_command(label="Другое количество…", command=app.show_generation)
    types = app.menu(toolbar, "Тип кода")
    from .generators import generators
    for generator in generators():
        types.add_command(label=generator.name + (" ✓" if generator.available else " — В разработке"),
                          state="normal" if generator.available else "disabled",
                          command=app.show_generation)
    settings = app.menu(toolbar, "Настройки")
    settings.add_command(label="Экземпляры и повторы TXT", command=lambda:app.notebook.select(app.pages["print"]))
    settings.add_command(label="Размер PDF и белое поле", command=lambda: app.geometry_dialog(False))
    settings.add_command(label="Размер модуля", command=lambda: app.geometry_dialog(True))
    settings.add_command(label="Цвет CMYK и формат PDF", command=app.color_dialog)
    settings.add_command(label="CPU, RAM и диск", command=app.show_resources)
    settings.add_command(label="Печать K100", command=app.use_k100)
    settings.add_separator()
    settings.add_command(label="Восстановить стандартные настройки", command=app.restore_defaults)
    tests = app.menu(toolbar, "Тесты")
    tests.add_command(label="Настроить и запустить тесты",command=app.show_lab)
    tests.add_command(label="Конвейер: QR и PDF на разных CPU",command=lambda:app.notebook.select(app.pages["pipeline"]))
    tests.add_command(label="История результатов",command=app.show_history)
    tests.add_separator()
    scientific=tk.Menu(tests,tearoff=False)
    tests.add_cascade(label="Научный профиль — всегда с проверкой",menu=scientific)
    for label, count in (("Быстрый — 200", 200), ("Средний — 1 000", 1000),
                         ("Большой — 10 000", 10000), ("Полный — 200 → 1 000 → 10 000", "all")):
        scientific.add_command(label=label, command=lambda n=count: app.start_test(n))
    tests.add_separator()
    tests.add_command(label="Выбрать движки объединения", command=app.performance_dialog)
    tests.add_command(label="Предыдущие результаты", command=lambda: app.open_path(app.output_root / "benchmarks"))
    ttk.Button(toolbar, text="Справка", command=app.show_help).pack(side="right")

    app.notebook = ttk.Notebook(body)
    app.notebook.grid(row=3, column=0, sticky="nsew", pady=(0, 7))
    app.pages = {}
    for key, title in (("generation", "Генерация"), ("print", "PDF и цвет"),
                       ("resources", "CPU / RAM"), ("lab", "Тесты"), ("search","Подбор ПК"), ("pipeline","Конвейер"), ("history","История"),
                       ("tests", "Объединение"), ("help", "Справка")):
        page = ttk.Frame(app.notebook, padding=(8, 4))
        app.notebook.add(page, text=title)
        app.pages[key] = page
    _generation(app)
    _print(app)
    _resources(app)
    from .lab_ui import build_lab
    build_lab(app)
    from .search_ui import SearchView
    app.search_view=SearchView(app)
    from .pipeline_ui import PipelineView
    app.pipeline_view=PipelineView(app)
    from .history_ui import HistoryView
    app.history_view=HistoryView(app)
    page = app.pages["tests"]
    ttk.Label(page, text="Научный профиль: 3 повтора · QR V1-M · K100\n"
              "Настройки и экземпляры обычной генерации на него не влияют.", style="Muted.TLabel").pack(anchor="w")
    app.engine_options_frame = ttk.Frame(page)
    app.engine_options_frame.pack(fill="both", expand=True, pady=6)
    ttk.Label(app.engine_options_frame, text="Откройте выбор движков, чтобы проверить их доступность.").pack(anchor="w")
    app.edit(ttk.Button(page, text="Выбрать движки", command=app.performance_dialog)).pack(anchor="w")
    page = app.pages["help"]
    app.help_text = tk.Text(page, height=7, width=85, wrap="word", borderwidth=0,
                           background=COLORS["background"], foreground=COLORS["text"],
                           insertbackground=COLORS["text"], font=("Segoe UI", 9), relief="flat")
    app.help_text.pack(fill="both", expand=True)
    app.help_text.insert("1.0", help_text)
    app.help_text.configure(state="disabled")

    ttk.Label(body, textvariable=app.geometry_summary, style="Muted.TLabel", wraplength=900).grid(
        row=4, column=0, sticky="w", pady=(0, 6))
    controls = ttk.Frame(body)
    controls.grid(row=5, column=0, sticky="ew", pady=(0, 5))
    app.generate = ttk.Button(controls, text="СОЗДАТЬ PDF", style="Primary.TButton", command=app.start)
    app.generate.pack(side="left")
    app.stop = ttk.Button(controls, text="Остановить", style="Danger.TButton", command=app.request_cancel)
    app.stop.pack(side="left", padx=9)
    ttk.Label(controls,text="PDF:").pack(side="left",padx=(5,3))
    app.verification_buttons={}
    for label,value,key in (("С проверкой","Полная","full"),("Без проверки","Отложена","deferred"),("Частично","Без растра","vector")):
        button=app.edit(ttk.Radiobutton(controls,text=label,value=value,variable=app.qa_mode_var,
                                       style="Choice.TRadiobutton",command=app.remember))
        button.pack(side="left",padx=2); app.verification_buttons[key]=button
    ttk.Label(controls, text="1 код = 1 страница", style="Muted.TLabel").pack(side="right")
    app.phase_label = ttk.Label(body, textvariable=app.status_var, wraplength=900)
    app.phase_label.grid(row=6, column=0, sticky="w")
    app.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
    app.progress.grid(row=7, column=0, sticky="ew", pady=(6, 5))
    metrics = ttk.Frame(body)
    metrics.grid(row=8, column=0, sticky="ew")
    ttk.Label(metrics, textvariable=app.elapsed_var, style="Muted.TLabel").pack(side="left")
    ttk.Label(metrics, textvariable=app.speed_var, style="Muted.TLabel").pack(side="right")
    result = ttk.Frame(body, padding=(0, 6, 0, 0))
    result.grid(row=9, column=0, sticky="ew")
    ttk.Label(result, textvariable=app.result_var, style="Result.TLabel", wraplength=900).pack(anchor="w")
    ttk.Label(result, textvariable=app.result_details, style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(2, 4))
    actions = ttk.Frame(result)
    actions.pack(anchor="w")
    app.open = ttk.Button(actions, text="Открыть PDF", command=app.open_pdf)
    app.open.pack(side="left")
    app.folder_button = ttk.Button(actions, text="Открыть папку", command=app.open_result)
    app.folder_button.pack(side="left", padx=7)
    app.report_button = ttk.Button(actions, text="Посмотреть отчёт", command=app.open_report)
    app.report_button.pack(side="left")
    app.audit_button=ttk.Button(actions,text="Проверить PDF",command=app.start_audit)
    app.audit_button.pack(side="left",padx=7)
    app.notebook.bind("<<NotebookTabChanged>>",lambda event:app.update_buttons() if hasattr(app,"generate") else None,add="+")


def _generation(app):
    page = app.pages["generation"]
    page.columnconfigure(0, weight=1)
    source = ttk.Frame(page)
    source.grid(row=0, column=0, sticky="ew")
    source.columnconfigure(0, weight=1)
    ttk.Label(source, textvariable=app.filename, font=("Segoe UI", 10, "bold"), wraplength=730).grid(row=0, column=0, sticky="w")
    app.edit(ttk.Button(source, text="Открыть TXT…", command=app.choose)).grid(row=0, column=1, sticky="e")
    ttk.Label(page, textvariable=app.file_count, style="Muted.TLabel", wraplength=850).grid(row=1, column=0, sticky="w", pady=(1, 2))
    numbers = ttk.Frame(page)
    numbers.grid(row=3, column=0, sticky="w", pady=4)
    ttk.Label(numbers, text="Новая база:").pack(side="left")
    app.custom_count_entry = app.edit(ttk.Spinbox(numbers, from_=1, to=1e300, width=8, textvariable=app.custom_count_var))
    app.custom_count_entry.pack(side="left", padx=6)
    app.edit(ttk.Button(numbers, text="Создать TXT", command=app.template_custom)).pack(side="left")
    app.main_pdf_picker=ChoiceMenu(app,numbers,app.pdf_profile_var,"PDF",[(label,label) for label in PDF_PROFILES],command=app.apply_pdf_profile)
    app.main_pdf_picker.button.pack(side="left",padx=6)
    app.main_activity_picker=ChoiceMenu(app,numbers,app.activity_var,"Доп. данные",[("Обычные","normal"),("Минимум","minimal")],command=app.remember)
    app.main_activity_picker.button.pack(side="left",padx=3)
    ttk.Label(page, textvariable=app.plan_var, style="Accent.TLabel", font=("Segoe UI", 10, "bold"),
              wraplength=850).grid(row=4, column=0, sticky="w", pady=(2, 5))
    destination = ttk.Frame(page)
    destination.grid(row=5, column=0, sticky="ew")
    destination.columnconfigure(1, weight=1)
    ttk.Label(destination, text="Папка PDF:").grid(row=0, column=0, padx=(0, 7))
    app.edit(ttk.Entry(destination, textvariable=app.destination_var, state="readonly"), "readonly").grid(row=0, column=1, sticky="ew")
    app.edit(ttk.Button(destination, text="Выбрать…", command=app.choose_destination)).grid(row=0, column=2, padx=(7, 0))
    from .generation_cpu import GenerationCPU
    app.generation_cpu=GenerationCPU(app,page)


def _print(app):
    page = app.pages["print"]
    options = ttk.Frame(page); options.pack(anchor="w",pady=(0,3))
    ttk.Label(options, text="Экземпляров каждого:").pack(side="left")
    app.copies_entry = app.edit(ttk.Spinbox(options, from_=1, to=1e300, width=6, textvariable=app.copies_var))
    app.copies_entry.pack(side="left", padx=(6, 18))
    app.duplicate_picker=ChoiceMenu(app,options,app.duplicates_var,"Повторы TXT",[(label,label) for label in POLICIES],command=app.remember)
    app.duplicate_picker.button.pack(side="left",padx=6)
    row = ttk.Frame(page)
    row.pack(anchor="w", pady=(0, 5))
    for text, value in (("Сторона PDF, мм", "side"), ("Модуль, мм", "module")):
        app.edit(ttk.Radiobutton(row, text=text, value=value, variable=app.geometry_basis,style="Choice.TRadiobutton",
                                command=app.change_geometry_basis)).pack(side="left", padx=(0, 8))
    app.geometry_entry = app.edit(ttk.Spinbox(row, textvariable=app.geometry_value, width=10,from_=.25,to=122,increment=.05))
    app.geometry_entry.pack(side="left", padx=(0, 16))
    ttk.Label(row, text="Поле, модулей:").pack(side="left")
    app.edit(ttk.Spinbox(row, from_=4, to=20, width=5, textvariable=app.quiet_var)).pack(side="left", padx=7)
    ink = ttk.Frame(page)
    ink.pack(anchor="w", pady=2)
    ttk.Label(ink, text="CMYK, %:").pack(side="left", padx=(0, 6))
    for name, var in zip("CMYK", app.ink_vars):
        ttk.Label(ink, text=name).pack(side="left")
        app.edit(ttk.Spinbox(ink,textvariable=var,width=5,from_=0,to=100,increment=1)).pack(side="left",padx=(3,10))
    app.edit(ttk.Button(ink, text="K100", command=app.use_k100)).pack(side="left")
    app.qa_picker=ChoiceMenu(app,ink,app.qa_mode_var,"Проверка",[("С проверкой","Полная"),("Частично — без картинок","Без растра"),("Без проверки","Отложена")],command=app.remember)
    app.qa_picker.button.pack(side="left",padx=(10,0))
    mode = ttk.Frame(page)
    mode.pack(anchor="w", pady=3)
    for text, value in (("Один PDF", "multipage"), ("Отдельные PDF", "singles"), ("Оба варианта", "both")):
        app.edit(ttk.Radiobutton(mode,text=text,value=value,variable=app.mode_var,command=app.remember,style="Choice.TRadiobutton")).pack(side="left",padx=(0,10))
    app.pdf_picker=ChoiceMenu(app,mode,app.pdf_profile_var,"PDF",[(label,label) for label in PDF_PROFILES],command=app.apply_pdf_profile)
    app.pdf_picker.button.pack(side="left")
    app.edit(ttk.Checkbutton(mode,text="Минимум расходов",variable=app.activity_var,onvalue="minimal",offvalue="normal",command=app.remember,style="Choice.TCheckbutton")).pack(side="left",padx=8)
    ttk.Label(page, textvariable=app.print_preview, style="Accent.TLabel", wraplength=850).pack(anchor="w", pady=3)
    buttons = ttk.Frame(page)
    buttons.pack(anchor="w", pady=(8, 0))
    app.edit(ttk.Button(buttons, text="Применить размер и цвет", command=app.apply_print)).pack(side="left")
    app.edit(ttk.Button(buttons, text="Стандартные настройки", command=app.restore_defaults)).pack(side="left", padx=8)


def _resources(app):
    page = app.pages["resources"]
    ttk.Label(page, textvariable=app.hardware_summary, style="Muted.TLabel", wraplength=850).pack(anchor="w")
    navigation=ttk.Frame(page); navigation.pack(anchor="w",pady=3)
    app.core_tests_button=app.edit(ttk.Button(navigation,text="Выбрать ядра для теста →",command=app.show_core_tests))
    app.core_tests_button.pack(side="left")
    def toggle():
        if app.busy: return
        if app.cpu_extra_frame.winfo_manager():
            app.cpu_extra_frame.pack_forget(); app.cpu_extra_button.configure(text="Дополнительные настройки…")
            hint.pack(after=preview,anchor="w",pady=3)
        else:
            app.cpu_extra_frame.pack(after=navigation,fill="x"); app.cpu_extra_button.configure(text="Скрыть дополнительные настройки")
            hint.pack_forget()
        app.fit_window()
    app.cpu_extra_button=app.edit(ttk.Button(navigation,text="Дополнительные настройки…",command=toggle))
    app.cpu_extra_button.pack(side="left",padx=7)
    app.cpu_extra_frame=ttk.Frame(page)
    controls = ttk.Frame(app.cpu_extra_frame)
    controls.pack(anchor="w", pady=3)
    app.execution_picker=ChoiceMenu(app,controls,app.backend_var,"Способ создания",[("По очереди","Последовательно"),("Параллельно","Процессы"),("Потоки Python (опытный)","Потоки (GIL)")],command=app.remember)
    app.execution_picker.button.pack(side="left")
    app.worker_picker=ChoiceMenu(app,controls,app.workers_var,"Заданий одновременно",[(str(n),str(n)) for n in range(1,app.hardware["cpu"]["available_logical"]+1)],command=app.remember)
    app.workers_entry=app.worker_picker.button
    app.workers_entry.pack(side="left",padx=7)
    ttk.Label(controls, text="Кодов за один шаг:").pack(side="left", padx=(10, 5))
    app.edit(ttk.Spinbox(controls, from_=1, to=1000, width=6, textvariable=app.batch_size_var)).pack(side="left")
    preview=ttk.Label(page, textvariable=app.execution_preview, style="Accent.TLabel", wraplength=850)
    preview.pack(anchor="w", pady=1)
    hint=ttk.Label(page, text="Для создания PDF выберите ядра прямо во вкладке «Генерация».\n"
              "Процессы кодируют QR параллельно. Запись общего PDF пока последовательная.",
              style="Muted.TLabel", wraplength=850)
    hint.pack(anchor="w", pady=3)
    buttons = ttk.Frame(page); buttons.pack(anchor="w", pady=2)
    app.edit(ttk.Button(buttons, text="Обновить ресурсы", command=app.refresh_hardware)).pack(side="left")
    app.edit(ttk.Button(buttons, text="Проверить запись 32 КиБ", command=app.probe_output)).pack(side="left", padx=8)
    app.edit(ttk.Button(buttons, text="Сохранить", command=app.remember)).pack(side="left")
