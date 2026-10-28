"""One operator window for TXT/PDF and separately measured scientific tests."""
from __future__ import annotations
import dataclasses
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
import webbrowser

from .batch import load_codes, make_template, run_batch
from .print_settings import PrintSettings, format_duration
from .app_settings import GenerationPreferences, load_user_preferences, save_preferences
from .generation_plan import build_plan
from .ui_layout import POLICIES, EXECUTION_METHODS, PDF_PROFILES,QA_MODES,build_window
from .engines import get_engine
from .hardware import inspect_hardware, probe_directory
from .execution import ExecutionOptions, execution_plan
from .open_reports import open_html_report

PROJECT = Path(__file__).resolve().parents[1]
HELP_TEXT = """1. База TXT → Открыть: UTF-8, одна строка — ровно 12 цифр.
2. Либо задайте любое количество до 10 000; готовые пресеты есть в меню.
3. Укажите экземпляры каждого значения и выберите политику повторов TXT.
   Например: 200 уникальных × 3 экземпляра = 600 кодов.
   «Сохранить строки» оставляет все повторяющиеся строки, как в исходном TXT.
4. «PDF и цвет»: размер, модуль, белое поле, CMYK и формат файлов.
5. СОЗДАТЬ PDF. Дождитесь кодирования, записи и проверки.
6. Откройте PDF, папку или понятный ОТЧЁТ.txt.

Процент учитывает фактически обработанные коды, страницы и QA.
100% означает завершение выбранного режима; статус качества указан отдельно.
По умолчанию QA полная. «Без растра» = LIMITED, «Отложена» = UNVERIFIED.
«Проверить PDF» запускает полную проверку готового тиража с отдельным отчётом.
«Компактный» PDF: общие данные документа, без шрифтов, объединённые контуры.
«Минимум расходов»: реже обновлять прогресс, без хешей и второй копии TXT.
Коды, размеры, CMYK, контроль ввода, RAM и отмена при этом сохраняются.
Лаборатория → «Сравнить PDF (первые)»: 4 варианта обычный/компактный ×
обычные/минимальные расходы на первых выбранных CPU/RAM/количестве.
В лаборатории QA всегда полная; скорость создания и время с QA раздельны.
Остановка сохраняет уже созданные файлы. Старые результаты не удаляются.

Сейчас работает QR Code V1-M: 12 цифр, до 10 000 строк.
Безопасный итог после умножения на экземпляры — максимум 10 000 кодов.
Один код соответствует одной странице. «Оба» сохраняет тираж в двух видах.
Белое поле минимум 4 модуля. По умолчанию — одна чёрная краска K100.
Цветной CMYK проверяется по выбранным компонентам; бледные коды могут
не пройти декодирование. Реальная пробная печать и сканер обязательны
для проверки вашего носителя. PDF/X пока не сертифицирован.

«Тесты» — отдельная научная методика: 3 повтора, раздельные времена
создания и объединения, QA. Перед 1000/10000 проверяется допуск.
Производственные результаты и результаты тестов не смешиваются.
Сейчас — наблюдаемая скорость по короткому окну (около 3 секунд).
Средняя этапа — обработанный объём / время с начала данного этапа.
«CPU / RAM»: физические ядра и логические CPU показаны раздельно.
«Лаборатория»: выберите физические ядра или логические потоки текущего ПК.
Галочки 1/2/4/6/8/12/Все −2/Все — отдельные варианты серии, не их сумма.
«Все −2» исключает два выбранных ядра/потока из теста, но не резервирует
их исключительно для Windows. Недоступные кнопки отключены.
Прогрев — дополнительные пробные PDF для файлового кэша перед замерами.
0 выключает прогрев. Эти запуски сохраняются, но не входят в медиану;
они добавляются к каждому варианту. Каждый повтор запускается в новом
процессе, поэтому прогрев не сохраняет Python-пул между замерами.
«Замеры» — число учитываемых запусков; обычно достаточно трёх.
Доступные CPU учитывают ограничения процесса. SMT не удваивает число ядер.
Процессы параллельно кодируют QR; запись PDF и QA пока последовательны.
Размер партии определяет число кодов на задачу. Для маленького TXT запуск
процессов может занять больше времени, чем последовательное кодирование.
RAM проверяется предварительно с запасом, это не жёсткий лимит потребления.
Скорость диска не определяется по названию NVMe/SATA. Проверка 32 КиБ —
проверка возможности записи и fsync, а не тест пропускной способности.
У стороннего объединителя без обратной связи промежуточных процентов нет:
секундомер продолжает работать, остановка ожидает возврата этого вызова.
"""


def clock_text(seconds):
    whole = max(0, int(seconds))
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}"


class BatchWindow:
    def __init__(self, root, output_root=None):
        self.root = root
        self.output_root = Path(output_root or PROJECT / "output")
        self.preferences_path = self.output_root.parent / ".local-state" / "user-settings.json"
        self.print_settings, mode, self.generation_preferences, warning = load_user_preferences(self.preferences_path)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_output = None
        self.last_pdf = None
        self.last_report = None
        self.busy = self.closing = False
        self.started = None
        self.current_event = None
        self.input_valid = False
        self.plan_valid = False
        self.source_values = None
        self.current_plan = None
        self._performance_loaded = False
        self.selected_engines = None
        self.generator_key = "qr"
        self.engine_key = "reportlab"
        self.engine_info = get_engine(self.engine_key).info()
        self.hardware = inspect_hardware(self.output_root)
        self.input_var = tk.StringVar(master=self.root)
        self.mode_var = tk.StringVar(master=self.root, value=mode)
        self.pdf_profile_var=tk.StringVar(master=self.root,value=next(label for label,key in PDF_PROFILES.items() if key==self.print_settings.pdf_profile))
        self.qa_mode_var=tk.StringVar(master=self.root,value=next(label for label,key in QA_MODES.items() if key==self.generation_preferences.qa_mode))
        self.activity_var=tk.StringVar(master=self.root,value=self.generation_preferences.activity)
        self.copies_var = tk.StringVar(master=self.root, value=str(self.generation_preferences.copies_per_value))
        self.duplicates_var = tk.StringVar(master=self.root, value=next(label for label, value in POLICIES.items() if value == self.generation_preferences.duplicate_policy))
        self.custom_count_var = tk.StringVar(master=self.root, value=str(self.generation_preferences.template_count))
        self.destination_var = tk.StringVar(master=self.root, value=self.generation_preferences.output_directory or str(self.output_root / "jobs"))
        self.backend_var = tk.StringVar(master=self.root, value=next(label for label, value in EXECUTION_METHODS.items() if value == self.generation_preferences.execution_backend))
        self.workers_var = tk.StringVar(master=self.root, value=str(self.generation_preferences.workers))
        self.batch_size_var = tk.StringVar(master=self.root, value=str(self.generation_preferences.batch_size))
        self.hardware_summary = tk.StringVar(master=self.root)
        self.execution_preview = tk.StringVar(master=self.root)
        self.plan_var = tk.StringVar(master=self.root, value="Выберите TXT, чтобы увидеть итог страниц")
        self.geometry_basis = tk.StringVar(master=self.root, value="side")
        self.geometry_value = tk.StringVar(master=self.root, value=f"{self.print_settings.side_mm:g}")
        self.quiet_var = tk.StringVar(master=self.root, value=str(self.print_settings.quiet_modules))
        self.ink_vars = [tk.StringVar(master=self.root, value=f"{v:g}") for v in self.print_settings.ink]
        self.print_preview = tk.StringVar(master=self.root)
        self.filename = tk.StringVar(master=self.root, value="База не выбрана")
        self.file_count = tk.StringVar(master=self.root, value="Откройте TXT или создайте номера в меню")
        self.geometry_summary = tk.StringVar(master=self.root)
        self.status_var = tk.StringVar(master=self.root, value=warning or "Готово к работе")
        self.elapsed_var = tk.StringVar(master=self.root, value="Прошло: 00:00:00")
        self.speed_var = tk.StringVar(master=self.root, value="Скорость: — кодов/сек")
        self.result_var = tk.StringVar(master=self.root, value="Здесь появится результат создания PDF")
        self.result_details = tk.StringVar(master=self.root, value="Данные и прежние результаты сохраняются локально")
        build_window(self, HELP_TEXT)
        self.refresh_hardware()
        self.update_geometry()
        self.refresh_plan()
        self.update_buttons()
        for var in (self.copies_var, self.duplicates_var, self.backend_var, self.workers_var, self.batch_size_var,self.qa_mode_var,self.activity_var):
            var.trace_add("write", self.refresh_plan)
        for var in (self.geometry_value, self.quiet_var, *self.ink_vars):
            var.trace_add("write", self.preview_print)
        self.preview_print()
        self.fit_window()
        root.after(100, self.poll)

    def menu(self, frame, text):
        button = ttk.Menubutton(frame, text=text + " ▾")
        menu = tk.Menu(button, tearoff=False)
        button.configure(menu=menu)
        button.pack(side="left", padx=(0, 6))
        self.menus.append(button)
        return menu

    def update_geometry(self):
        p = self.print_settings
        mode = {"multipage": "Один PDF", "singles": "Отдельные PDF", "both": "Оба варианта"}[self.mode_var.get()]
        color = "K100" if p.is_k100 else "CMYK " + "/".join(f"{v:g}" for v in p.ink)
        self.geometry_summary.set(f"QR Code · {p.side_mm:.2f} × {p.side_mm:.2f} мм · модуль {p.module_mm:.3f} мм · поле {p.white_margin_mm:.2f} мм · {color} · {mode}")

    def edit(self, widget, idle_state="normal"):
        self.edit_controls.append((widget, idle_state))
        return widget

    def fit_window(self):
        self.root.update_idletasks()
        width = min(self.root.winfo_screenwidth() - 40, max(760, self.root.winfo_reqwidth() + 16))
        height = min(self.root.winfo_screenheight() - 90, self.root.winfo_reqheight() + 16)
        self.root.minsize(width, height)
        current_width, current_height = self.root.winfo_width(), self.root.winfo_height()
        if width > current_width or height > current_height:
            self.root.geometry(f"{max(width, current_width, min(980, self.root.winfo_screenwidth() - 40))}x{max(height, current_height)}")

    def read_generation_options(self):
        try:
            copies, count = int(self.copies_var.get()), int(self.custom_count_var.get())
            workers, batch_size = int(self.workers_var.get()), int(self.batch_size_var.get())
        except ValueError as exc:
            raise ValueError("Количество и экземпляры должны быть целыми числами") from exc
        return GenerationPreferences(copies, POLICIES.get(self.duplicates_var.get(), ""), count,
                                     self.destination_var.get(), EXECUTION_METHODS.get(self.backend_var.get(), ""), workers, batch_size,
                                     QA_MODES.get(self.qa_mode_var.get(),""),self.activity_var.get())

    def refresh_plan(self, *_):
        self.plan_valid = False
        self.current_plan = None
        if self.input_valid and self.source_values:
            try:
                options = self.read_generation_options()
                plan = build_plan(self.source_values, copies_per_value=options.copies_per_value,
                                  duplicate_policy=options.duplicate_policy, types=(self.generator_key,))
                basis = "уникальных" if options.duplicate_policy == "unique" or not plan.duplicate_records else "строк TXT"
                text = f"{len(plan.selected_values):,} {basis} × {plan.copies_per_value:,} экз. = {plan.total_codes:,} кодов".replace(",", " ")
                if plan.duplicate_records and options.duplicate_policy == "preserve":
                    text += f" · уникальных: {plan.unique_values}"
                execution = execution_plan(ExecutionOptions(options.execution_backend, options.workers, options.batch_size),
                    plan.unique_values, self.hardware["cpu"], self.hardware["ram"]["available_bytes"])
                self.execution_preview.set(f"Кодирование: {execution['backend']} · рабочих процессов: {execution['effective_workers']} · партия: {options.batch_size}")
                self.plan_var.set(text)
                self.current_plan = plan
                self.plan_valid = True
            except ValueError as exc:
                self.plan_var.set(str(exc))
                self.execution_preview.set(str(exc))
        else:
            self.plan_var.set("Выберите TXT, чтобы увидеть итог страниц")
        if hasattr(self, "generate"):
            self.update_buttons()

    def remember(self):
        saved = False
        try:
            options = self.read_generation_options()
            save_preferences(self.preferences_path, self.print_settings, self.mode_var.get(), generation=options)
            self.generation_preferences = options
            saved = True
        except (OSError, ValueError) as exc:
            self.status_var.set(f"Настройки не сохранены: {exc}")
        self.update_geometry()
        return saved

    def update_buttons(self):
        for item in self.menus:
            item.configure(state="disabled" if self.busy else "normal")
        for widget, idle_state in self.edit_controls:
            if widget.winfo_exists():
                widget.configure(state="disabled" if self.busy else idle_state)
        self.generate.configure(state="normal" if self.input_valid and self.plan_valid and not self.busy else "disabled")
        self.generate.configure(text="СОЗДАТЬ PDF (БЕЗ QA)" if self.qa_mode_var.get()=="Отложена" else "СОЗДАТЬ PDF")
        self.audit_button.configure(state="normal" if self.last_output and (self.last_output/"manifest.json").is_file() and not self.busy else "disabled")
        self.stop.configure(state="normal" if self.busy and not self.cancel.is_set() else "disabled")
        self.open.configure(state="normal" if self.last_pdf and not self.busy else "disabled")
        self.folder_button.configure(state="normal" if self.last_output and not self.busy else "disabled")
        self.report_button.configure(state="normal" if self.last_report and not self.busy else "disabled")
        self.report_button.configure(text="Отчёт в браузере" if self.last_report and self.last_report.suffix.lower() in (".html",".htm") else "Посмотреть отчёт")

    def show_generation(self):
        self.notebook.select(self.pages["generation"])
        self.custom_count_entry.focus_set()

    def show_lab(self):
        self.refresh_hardware()
        self.notebook.select(self.pages["lab"])

    def show_resources(self):
        self.notebook.select(self.pages["resources"])
        self.refresh_hardware()

    def refresh_hardware(self):
        try:
            directory = self.destination_var.get() or self.output_root
            self.hardware = inspect_hardware(directory)
            cpu, ram, disk = (self.hardware[key] for key in ("cpu", "ram", "disk"))
            def gib(value): return f"{value / 1024**3:.1f} ГиБ" if value is not None else "неизвестно"
            self.hardware_summary.set(
                f"{cpu.get('name') or 'Модель CPU неизвестна'}\n"
                f"Ядра / логические CPU: {cpu['physical_cores'] or '?'} / {cpu['logical_processors'] or '?'} · доступно {cpu['available_physical'] or '?'} / {cpu['available_logical']} · групп: {cpu['groups'] or '?'}\n"
                f"RAM: {gib(ram['total_bytes'])}, свободно {gib(ram['available_bytes'])} · диск {disk['bus'] or '?'}, свободно {gib(disk['free_bytes'])}")
            if hasattr(self, "workers_entry"):
                self.workers_entry.configure(values=cpu["presets"])
            if hasattr(self,"lab_refresh"): self.lab_refresh()
            self.refresh_plan()
        except (ValueError, OSError) as exc:
            self.hardware_summary.set(f"Ресурсы не определены: {exc}")
            self.status_var.set(str(exc))

    def probe_output(self):
        try:
            result = probe_directory(self.destination_var.get() or self.output_root)
            self.status_var.set(f"Запись {result['bytes'] // 1024} КиБ + fsync: успешно; скорость диска не измерялась")
        except (ValueError, OSError) as exc:
            self.status_var.set(f"Проверка записи: {exc}")

    def choose_destination(self):
        path = filedialog.askdirectory(parent=self.root, title="Папка готовых PDF")
        if path:
            self.destination_var.set(path)
            self.remember()

    def choose(self):
        path = filedialog.askopenfilename(parent=self.root, title="База TXT — 12 цифр в строке", filetypes=[("TXT UTF-8", "*.txt"), ("Все файлы", "*.*")])
        if path:
            self.input_var.set(path)
            self.inspect_input()

    def inspect_input(self):
        name = Path(self.input_var.get()).name or "База не выбрана"
        self.filename.set(name if len(name) <= 65 else name[:30] + "…" + name[-30:])
        try:
            values = load_codes(Path(self.input_var.get()))
            self.input_valid = True
            self.source_values = values
            self.refresh_plan()
            self.file_count.set(f"Проверка пройдена · {len(values):,} кодов · Первый: {values[0]} · Последний: {values[-1]}".replace(",", " "))
            self.update_buttons()
            self.fit_window()
            return values
        except (ValueError, OSError) as exc:
            self.input_valid = False
            self.source_values = None
            self.refresh_plan()
            self.file_count.set(f"Ошибка TXT: {str(exc)[:180]}")
            self.generate.configure(state="disabled")
            self.fit_window()
            return None

    def template(self, count):
        try:
            self.input_var.set(str(make_template(self.output_root / "templates", count)))
            self.inspect_input()
        except (ValueError, OSError) as exc:
            self.status_var.set(f"Номера не созданы: {exc}")

    def template_custom(self):
        try:
            count = int(self.custom_count_var.get())
            self.template(count)
            self.remember()
        except ValueError:
            self.status_var.set("Количество номеров должно быть целым числом от 1 до 10 000")

    def begin(self):
        self.cancel = threading.Event()
        self.busy = True
        self.started = time.perf_counter()
        self.current_event = None
        self.last_output = self.last_pdf = self.last_report = None
        self.progress["value"] = 0
        self.result_var.set("Выполняется…")
        self.update_buttons()

    def start(self):
        if self.busy:
            return
        numbers = self.inspect_input()
        if numbers is None or not self.plan_valid:
            self.status_var.set(self.file_count.get() if numbers is None else self.plan_var.get())
            return
        options = self.read_generation_options()
        destination = Path(options.output_directory) if options.output_directory else self.output_root / "jobs"
        self.remember()
        self.begin()
        path, mode, settings = Path(self.input_var.get()), self.mode_var.get(), self.print_settings
        self.launch(lambda: run_batch(path, destination, mode=mode, settings=settings, cancel=self.cancel,
                    copies_per_value=options.copies_per_value, duplicate_policy=options.duplicate_policy,
                    generator=self.generator_key, engine=self.engine_key,
                    execution=ExecutionOptions(options.execution_backend, options.workers, options.batch_size),
                    qa_mode=options.qa_mode,activity=options.activity,
                    progress=lambda s: self.events.put(("status", s)), events=lambda e: self.events.put(("progress", e))))

    def start_audit(self):
        if self.busy or self.last_output is None: return
        source=self.last_output
        self.begin()
        from .audit import audit_job
        self.launch(lambda:audit_job(source,cancel=self.cancel,events=lambda value:self.events.put(("progress",value)),
                                     progress=lambda value:self.events.put(("status",value))))

    def apply_pdf_profile(self):
        self.print_settings=dataclasses.replace(self.print_settings,pdf_profile=PDF_PROFILES[self.pdf_profile_var.get()])
        self.remember(); self.preview_print()

    def start_test(self, count):
        if self.busy:
            return
        self.begin()
        self.status_var.set("Проверка ресурсов и допуска к тесту…")
        def task():
            from .scientific import run_scientific
            return run_scientific(self.output_root / "benchmarks", count, cancel=self.cancel,
                    events=lambda e: self.events.put(("progress", e)),
                    progress=lambda s: self.events.put(("status", s)), methods=self.selected_engines)
        self.launch(task)

    def launch(self, action):
        def work():
            try:
                self.events.put(("done", Path(action())))
            except Exception as exc:
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))
        self.worker = threading.Thread(target=work, name="ucode-operator", daemon=False)
        self.worker.start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(str(value))
                elif kind == "progress":
                    self.current_event = value
                    self.progress["value"] = value["percent"]
                    counts = f"{value['done']:,} / {value['total']:,}".replace(",", " ")
                    percent = f"{value['percent']:.1f}".replace(".", ",")
                    self.status_var.set(f"{value['stage']} · {counts} · всего {percent}%")
                    unit = value.get("unit", "кодов")
                    average = value.get("average_speed", value["speed"])
                    text = (f"Итоговая: {average:.1f} {unit}/сек" if value["percent"] == 100 else
                            f"Сейчас: {value['speed']:.1f} · средняя этапа: {average:.1f} {unit}/сек")
                    self.speed_var.set(text.replace(".", ","))
                else:
                    self.busy = False
                    if kind == "done":
                        self.complete(Path(value))
                    else:
                        self.result_var.set("Операция остановлена" if "InterruptedError" in str(value) else "ОШИБКА")
                        self.status_var.set(str(value))
                        self.result_details.set("Уже созданные файлы сохранены")
                    self.update_buttons()
        except queue.Empty:
            pass
        if self.busy and self.started is not None:
            self.elapsed_var.set("Прошло: " + clock_text(time.perf_counter() - self.started))
        if self.closing and not self.busy and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
        else:
            self.root.after(100, self.poll)

    def complete(self, folder):
        self.last_output = folder
        if (folder/"audit.json").is_file():
            data=json.loads((folder/"audit.json").read_text(encoding="utf-8"))
            self.last_output=folder.parent.parent
            self.last_report=folder/"ОТЧЁТ.txt"
            self.last_pdf=next(self.last_output.glob("all-*-pages.pdf"),None)
            if self.last_pdf is None: self.last_pdf=next((self.last_output/"singles").glob("*.pdf"),None)
            self.result_var.set("ПРОВЕРКА: "+data["status"])
            self.result_details.set("Исходный PDF и manifest сохранены; QA записан отдельно")
            if data["status"]=="COMPLETE": self.progress["value"]=100
            return
        if (folder / "lab.json").exists():
            result=json.loads((folder/"lab.json").read_text(encoding="utf-8"))
            self.last_report=folder/"comparison.html"
            self.last_pdf=next(folder.glob("trials/*/jobs/*/all-*-pages.pdf"),None)
            self.result_var.set("ЛАБОРАТОРИЯ: " + result["status"])
            self.result_details.set(f"Вариантов: {len(result['cases'])} · рекомендации только по полным успешным повторам; откройте отчёт")
            if result["status"]=="COMPLETE": self.progress["value"]=100
            self.elapsed_var.set("Прошло: "+clock_text(result["elapsed_seconds"]))
            return
        manifest = folder / "manifest.json"
        if not manifest.exists():
            self.last_report = folder / "ОТЧЁТ.txt"
            self.last_pdf = None
            result = json.loads((folder / "scientific.json").read_text(encoding="utf-8"))
            self.result_var.set("ТЕСТЫ ЗАВЕРШЕНЫ" if result["status"] == "COMPLETE" else "ТЕСТЫ: " + result["status"])
            self.result_details.set("Три повтора; генерация и объединение измерены отдельно. Откройте отчёт.")
            if result["status"] == "COMPLETE":
                self.progress["value"] = 100
            return
        report = json.loads(manifest.read_text(encoding="utf-8"))
        status, count = report["status"], report["count"]
        seconds = report.get("seconds", {}).get("total_including_qa", 0)
        self.elapsed_var.set("Прошло: " + clock_text(seconds))
        self.last_report = folder / "ОТЧЁТ.txt"
        output = report.get("files", {}).get("multipage", {}).get("name")
        self.last_pdf = folder / output if output and status in ("COMPLETE", "LIMITED","UNVERIFIED") else None
        if self.last_pdf is None and status in ("COMPLETE", "LIMITED","UNVERIFIED"):
            self.last_pdf = next((folder / "singles").glob("*.pdf"), None)
        label = {"COMPLETE": "ГОТОВО", "LIMITED": "ПРОВЕРЕНО ЧАСТИЧНО", "CANCELLED": "ОСТАНОВЛЕНО", "INVALID": "ОШИБКА КАЧЕСТВА", "ERROR": "ОШИБКА"}.get(status, status)
        if status=="UNVERIFIED": label="СОЗДАНО БЕЗ QA"
        self.result_var.set(f"{label} · {count:,} кодов · {format_duration(seconds)}".replace(",", " "))
        files = list(folder.glob("*.pdf")) + list((folder / "singles").glob("*.pdf"))
        size = sum(p.stat().st_size for p in files)
        quality = {"COMPLETE": "проверка пройдена", "LIMITED": "без растрового контроля", "INVALID": "ошибка качества",
                   "CANCELLED": "проверка не завершена", "ERROR": "ошибка","UNVERIFIED":"качество не проверялось"}.get(status, status)
        self.result_details.set(f"PDF: {len(files):,} · {size / 1024**2:.2f} МиБ · {count / max(seconds, .001):.1f} кодов/сек · {quality}".replace(",", " "))
        if status == "COMPLETE":
            self.progress["value"] = 100
        self.status_var.set("PDF и отчёт сохранены" if status == "COMPLETE" else "Подробности проверки — в отчёте")

    def request_cancel(self):
        self.cancel.set()
        self.status_var.set("Остановка запрошена. Созданные файлы сохраняются.")
        self.update_buttons()

    def use_k100(self):
        self.print_settings = dataclasses.replace(self.print_settings, ink=(0, 0, 0, 100))
        for var, value in zip(self.ink_vars, self.print_settings.ink):
            var.set(f"{value:g}")
        self.remember()

    def geometry_dialog(self, by_module=False):
        self.notebook.select(self.pages["print"])
        self.geometry_basis.set("module" if by_module else "side")
        self.change_geometry_basis()
        self.geometry_entry.focus_set()

    def change_geometry_basis(self):
        value = self.print_settings.module_mm if self.geometry_basis.get() == "module" else self.print_settings.side_mm
        self.geometry_value.set(f"{value:g}")
        self.preview_print()

    def preview_print(self, *_):
        try:
            try:
                value = float(self.geometry_value.get().replace(",", "."))
                quiet = int(self.quiet_var.get())
                ink = tuple(float(v.get().replace(",", ".")) for v in self.ink_vars)
            except ValueError as exc:
                raise ValueError("Размер, поле и CMYK должны быть числами") from exc
            profile=PDF_PROFILES[self.pdf_profile_var.get()]
            cfg = (PrintSettings(value, quiet, ink,pdf_profile=profile) if self.geometry_basis.get() == "module" else
                   PrintSettings.from_total_side(value, quiet, ink,pdf_profile=profile))
            self.print_preview.set(f"PDF {cfg.side_mm:.2f} × {cfg.side_mm:.2f} мм · модуль {cfg.module_mm:.3f} мм · поле {cfg.white_margin_mm:.2f} мм")
            return cfg
        except ValueError as exc:
            self.print_preview.set(str(exc))
            return None

    def apply_print(self):
        cfg = self.preview_print()
        if cfg is not None:
            self.print_settings = cfg
            if self.remember():
                self.status_var.set("Размер и цвет PDF применены")

    def color_dialog(self):
        self.notebook.select(self.pages["print"])

    def restore_defaults(self):
        if self.busy:
            return
        self.print_settings = PrintSettings()
        self.pdf_profile_var.set("Обычный")
        self.qa_mode_var.set("Полная"); self.activity_var.set("normal")
        self.mode_var.set("multipage")
        self.copies_var.set("1")
        self.duplicates_var.set(next(label for label, value in POLICIES.items() if value == "preserve"))
        self.custom_count_var.set("200")
        self.destination_var.set(str(self.output_root / "jobs"))
        self.backend_var.set("Последовательно")
        self.workers_var.set("1")
        self.batch_size_var.set("32")
        self.geometry_basis.set("side")
        self.geometry_value.set(f"{self.print_settings.side_mm:g}")
        self.quiet_var.set("4")
        for var, value in zip(self.ink_vars, self.print_settings.ink):
            var.set(f"{value:g}")
        saved = self.remember()
        self.refresh_plan()
        if saved:
            self.status_var.set("Стандартные настройки восстановлены")

    def performance_dialog(self):
        self.notebook.select(self.pages["tests"])
        if self._performance_loaded or self.busy:
            return
        from .mergers import available_adapters
        for child in self.engine_options_frame.winfo_children():
            child.destroy()
        self._performance_options = []
        for index, adapter in enumerate(available_adapters()):
            available = adapter.probe()["available"]
            var = tk.BooleanVar(master=self.root, value=available and (self.selected_engines is None or adapter.name in self.selected_engines))
            self._performance_options.append((adapter.name, var))
            control = ttk.Checkbutton(self.engine_options_frame,
                text=adapter.name + ("" if available else " — недоступен"), variable=var,
                command=self.apply_performance, state="normal" if available else "disabled")
            self.edit(control, "normal" if available else "disabled").grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 10), pady=2)
        self._performance_loaded = True
        self.fit_window()

    def apply_performance(self):
        self.selected_engines = [name for name, var in self._performance_options if var.get()]

    def open_path(self, path):
        path = Path(path)
        if not path.exists():
            self.status_var.set("Файлы ещё не созданы")
        elif path.suffix.lower() in (".html",".htm") and path.is_file():
            try: open_html_report(path)
            except (OSError,ValueError) as exc: self.status_var.set(str(exc))
        elif hasattr(os, "startfile"):
            os.startfile(str(path.resolve()))
        else:
            webbrowser.open(path.resolve().as_uri())

    def open_pdf(self):
        if self.last_pdf:
            self.open_path(self.last_pdf)

    def open_result(self):
        if self.last_output:
            self.open_path(self.last_output)

    def open_report(self):
        if self.last_report:
            self.open_path(self.last_report)

    def show_help(self):
        self.notebook.select(self.pages["help"])

    def close(self):
        if self.busy or (self.worker is not None and self.worker.is_alive()):
            self.closing = True
            self.request_cancel()
        else:
            self.remember()
            self.root.destroy()


def open_window(parent):
    return BatchWindow(tk.Toplevel(parent))


def main():
    root = tk.Tk()
    root.withdraw()
    controller = BatchWindow(root)
    root.deiconify()
    root.mainloop()
    del controller


if __name__ == "__main__":
    main()
