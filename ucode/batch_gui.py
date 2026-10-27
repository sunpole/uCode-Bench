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
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .batch import load_codes, make_template, run_batch
from .print_settings import PrintSettings, format_duration
from .app_settings import load_preferences, save_preferences
from .generators import generators
from .engines import get_engine

PROJECT = Path(__file__).resolve().parents[1]
HELP_TEXT = """1. База TXT → Открыть: UTF-8, одна строка — ровно 12 цифр.
2. Либо «Создать номера»: 200, 1 000 или 10 000 кодов.
3. «Настройки»: размер PDF, модуль, белое поле, CMYK и формат файлов.
4. СОЗДАТЬ PDF. Дождитесь кодирования, записи и проверки.
5. Откройте PDF, папку или понятный ОТЧЁТ.txt.

Процент учитывает фактически обработанные коды, страницы и QA.
100% означает завершённую операцию и полную проверку.
Остановка сохраняет уже созданные файлы. Старые результаты не удаляются.

Сейчас работает QR Code V1-M: 12 цифр, до 10 000 строк.
Белое поле минимум 4 модуля. По умолчанию — одна чёрная краска K100.
Цветной CMYK проверяется по выбранным компонентам; бледные коды могут
не пройти декодирование. Реальная пробная печать и сканер обязательны
для проверки вашего носителя. PDF/X пока не сертифицирован.

«Тесты» — отдельная научная методика: 3 повтора, раздельные времена
создания и объединения, QA. Перед 1000/10000 проверяется допуск.
Производственные результаты и результаты тестов не смешиваются.
Сейчас — наблюдаемая скорость по короткому окну (около 3 секунд).
Средняя этапа — обработанный объём / время с начала данного этапа.
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
        self.print_settings, mode, warning = load_preferences(self.preferences_path)
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
        self.selected_engines = None
        self.generator_key = "qr"
        self.engine_key = "reportlab"
        self.engine_info = get_engine(self.engine_key).info()
        self.input_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=mode)
        self.filename = tk.StringVar(value="База не выбрана")
        self.file_count = tk.StringVar(value="Откройте TXT или создайте номера в меню")
        self.geometry_summary = tk.StringVar()
        self.status_var = tk.StringVar(value=warning or "Готово к работе")
        self.elapsed_var = tk.StringVar(value="Прошло: 00:00:00")
        self.speed_var = tk.StringVar(value="Скорость: — кодов/сек")
        self.result_var = tk.StringVar(value="Здесь появится результат создания PDF")
        self.result_details = tk.StringVar(value="Данные и прежние результаты сохраняются локально")
        root.title("uCode v0.2 — TXT → PDF")
        width = min(980, max(760, root.winfo_screenwidth() - 60))
        height = min(540, max(440, root.winfo_screenheight() - 130))
        root.geometry(f"{width}x{height}")
        root.minsize(min(760, width), min(440, height))
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Primary.TButton", font=("Segoe UI", 13, "bold"), padding=(18, 9))
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Result.TLabel", font=("Segoe UI", 15, "bold"))
        body = ttk.Frame(root, padding=(18, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="uCode", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text=f"TXT → печатные PDF · {self.engine_info.name} {self.engine_info.version}",
                  wraplength=900, foreground="#4c5868").grid(row=1, column=0, sticky="w", pady=(0, 10))
        toolbar = ttk.Frame(body)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.menus = []
        base = self.menu(toolbar, "База TXT")
        base.add_command(label="Открыть TXT…", command=self.choose)
        base.add_command(label="Проверить выбранный файл", command=self.inspect_input)
        create = self.menu(toolbar, "Создать номера")
        for count in (200, 1000, 10000):
            create.add_command(label=f"{count:,}".replace(",", " "), command=lambda n=count: self.template(n))
        types = self.menu(toolbar, "Тип кода")
        for generator in generators():
            types.add_command(label=generator.name + (" ✓" if generator.available else " — В разработке"),
                              state="normal" if generator.available else "disabled",
                              command=lambda: self.status_var.set("Выбран QR Code V1-M"))
        settings = self.menu(toolbar, "Настройки")
        settings.add_command(label="Размер PDF и белое поле…", command=lambda: self.geometry_dialog(False))
        settings.add_command(label="Размер модуля…", command=lambda: self.geometry_dialog(True))
        settings.add_command(label="Цвет CMYK…", command=self.color_dialog)
        settings.add_command(label="Печать K100 — одна чёрная краска", command=self.use_k100)
        formats = tk.Menu(settings, tearoff=False)
        for label, value in (("Один многостраничный PDF", "multipage"), ("Отдельные PDF", "singles"), ("Оба варианта", "both")):
            formats.add_radiobutton(label=label, variable=self.mode_var, value=value, command=self.remember)
        settings.add_cascade(label="Формат результата", menu=formats)
        tests = self.menu(toolbar, "Тесты")
        for label, count in (("Быстрый тест — 200", 200), ("Средний тест — 1 000", 1000), ("Большой тест — 10 000", 10000), ("Полный тест — 200 → 1 000 → 10 000", "all")):
            tests.add_command(label=label, command=lambda n=count: self.start_test(n))
        tests.add_separator()
        tests.add_command(label="Результаты предыдущих тестов", command=lambda: self.open_path(self.output_root / "benchmarks"))
        tests.add_command(label="Настройки производительности…", command=self.performance_dialog)
        ttk.Button(toolbar, text="Справка", command=self.show_help).pack(side="right", padx=(6, 0))
        source = ttk.LabelFrame(body, text="База TXT", padding=10)
        source.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(source, textvariable=self.filename, font=("Segoe UI", 11, "bold"), wraplength=880).pack(anchor="w")
        ttk.Label(source, textvariable=self.file_count, wraplength=880).pack(anchor="w", pady=(3, 0))
        ttk.Label(body, textvariable=self.geometry_summary, wraplength=900, foreground="#325b44").grid(row=4, column=0, sticky="w", pady=(0, 9))
        controls = ttk.Frame(body)
        controls.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.generate = ttk.Button(controls, text="СОЗДАТЬ PDF", style="Primary.TButton", command=self.start)
        self.generate.pack(side="left")
        self.stop = ttk.Button(controls, text="Остановить", command=self.request_cancel)
        self.stop.pack(side="left", padx=10)
        self.phase_label = ttk.Label(body, textvariable=self.status_var, wraplength=900)
        self.phase_label.grid(row=6, column=0, sticky="w")
        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, sticky="ew", pady=(7, 5))
        metrics = ttk.Frame(body)
        metrics.grid(row=8, column=0, sticky="ew")
        ttk.Label(metrics, textvariable=self.elapsed_var).pack(side="left")
        ttk.Label(metrics, textvariable=self.speed_var).pack(side="right")
        result = ttk.Frame(body, padding=(0, 12, 0, 0))
        result.grid(row=9, column=0, sticky="nsew")
        body.rowconfigure(9, weight=1)
        ttk.Label(result, textvariable=self.result_var, style="Result.TLabel", wraplength=900).pack(anchor="w")
        ttk.Label(result, textvariable=self.result_details, wraplength=900).pack(anchor="w", pady=(4, 8))
        actions = ttk.Frame(result)
        actions.pack(anchor="w")
        self.open = ttk.Button(actions, text="Открыть PDF", command=self.open_pdf)
        self.open.pack(side="left")
        self.folder_button = ttk.Button(actions, text="Открыть папку", command=self.open_result)
        self.folder_button.pack(side="left", padx=8)
        self.report_button = ttk.Button(actions, text="Посмотреть отчёт", command=self.open_report)
        self.report_button.pack(side="left")
        self.update_geometry()
        self.update_buttons()
        root.update_idletasks()
        needed_width = min(root.winfo_screenwidth() - 40, max(760, root.winfo_reqwidth() + 24))
        needed_height = min(root.winfo_screenheight() - 90, root.winfo_reqheight() + 24)
        root.minsize(needed_width, needed_height)
        root.geometry(f"{max(needed_width, width)}x{needed_height}")
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

    def remember(self):
        try:
            save_preferences(self.preferences_path, self.print_settings, self.mode_var.get())
        except OSError as exc:
            self.status_var.set(f"Не удалось сохранить настройки: {exc}")
        self.update_geometry()

    def update_buttons(self):
        for item in self.menus:
            item.configure(state="disabled" if self.busy else "normal")
        self.generate.configure(state="normal" if self.input_valid and not self.busy else "disabled")
        self.stop.configure(state="normal" if self.busy and not self.cancel.is_set() else "disabled")
        self.open.configure(state="normal" if self.last_pdf and not self.busy else "disabled")
        self.folder_button.configure(state="normal" if self.last_output and not self.busy else "disabled")
        self.report_button.configure(state="normal" if self.last_report and not self.busy else "disabled")

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
            self.file_count.set(f"Проверка пройдена · {len(values):,} кодов · Первый: {values[0]} · Последний: {values[-1]}".replace(",", " "))
            self.update_buttons()
            return values
        except (ValueError, OSError) as exc:
            self.input_valid = False
            self.file_count.set(f"Ошибка TXT: {exc}")
            self.generate.configure(state="disabled")
            return None

    def template(self, count):
        try:
            self.input_var.set(str(make_template(self.output_root / "templates", count)))
            self.inspect_input()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Не удалось создать номера", str(exc), parent=self.root)

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
        if numbers is None:
            messagebox.showerror("Проверьте TXT", self.file_count.get(), parent=self.root)
            return
        self.remember()
        self.begin()
        path, mode, settings = Path(self.input_var.get()), self.mode_var.get(), self.print_settings
        self.launch(lambda: run_batch(path, self.output_root / "jobs", mode=mode, settings=settings, cancel=self.cancel,
                    generator=self.generator_key, engine=self.engine_key,
                    progress=lambda s: self.events.put(("status", s)), events=lambda e: self.events.put(("progress", e))))

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
        self.last_pdf = folder / output if output and status in ("COMPLETE", "LIMITED") else None
        if self.last_pdf is None and status in ("COMPLETE", "LIMITED"):
            self.last_pdf = next((folder / "singles").glob("*.pdf"), None)
        label = {"COMPLETE": "ГОТОВО", "LIMITED": "ПРОВЕРЕНО ЧАСТИЧНО", "CANCELLED": "ОСТАНОВЛЕНО", "INVALID": "ОШИБКА КАЧЕСТВА", "ERROR": "ОШИБКА"}.get(status, status)
        self.result_var.set(f"{label} · {count:,} кодов · {format_duration(seconds)}".replace(",", " "))
        files = list(folder.glob("*.pdf")) + list((folder / "singles").glob("*.pdf"))
        size = sum(p.stat().st_size for p in files)
        quality = {"COMPLETE": "проверка пройдена", "LIMITED": "без растрового контроля", "INVALID": "ошибка качества",
                   "CANCELLED": "проверка не завершена", "ERROR": "ошибка"}.get(status, status)
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
        self.remember()

    def geometry_dialog(self, by_module=False):
        window = tk.Toplevel(self.root)
        window.title("Размер модуля" if by_module else "Размер PDF и белое поле")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        value = tk.StringVar(value=f"{self.print_settings.module_mm if by_module else self.print_settings.side_mm:g}")
        quiet = tk.StringVar(value=str(self.print_settings.quiet_modules))
        ttk.Label(frame, text="Модуль, мм:" if by_module else "Сторона PDF с полями, мм:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=value, width=14).grid(row=0, column=1, padx=10)
        ttk.Label(frame, text="Белое поле, модулей (4–20):").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=quiet, width=14).grid(row=1, column=1, padx=10)
        preview = tk.StringVar()
        def calculate(*_):
            try:
                number, q = float(value.get().replace(",", ".")), int(quiet.get())
                cfg = PrintSettings(number, q, self.print_settings.ink) if by_module else PrintSettings.from_total_side(number, q, self.print_settings.ink)
                preview.set(f"PDF {cfg.side_mm:.2f} мм · модуль {cfg.module_mm:.3f} мм · поле {cfg.white_margin_mm:.2f} мм")
                return cfg
            except ValueError as exc:
                preview.set(str(exc))
                return None
        value.trace_add("write", calculate)
        quiet.trace_add("write", calculate)
        ttk.Label(frame, textvariable=preview, wraplength=460).grid(row=2, column=0, columnspan=2, pady=12)
        def apply():
            cfg = calculate()
            if cfg is not None:
                self.print_settings = cfg
                self.remember()
                window.destroy()
        calculate()
        ttk.Button(frame, text="Применить", command=apply).grid(row=3, column=0, columnspan=2)

    def color_dialog(self):
        window = tk.Toplevel(self.root)
        window.title("Цвет CMYK, проценты")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack()
        variables = []
        for index, (name, component) in enumerate(zip("CMYK", self.print_settings.ink)):
            ttk.Label(frame, text=name + " (0–100%)").grid(row=index, column=0, pady=4)
            var = tk.StringVar(value=f"{component:g}")
            variables.append(var)
            ttk.Entry(frame, textvariable=var, width=12).grid(row=index, column=1, padx=12)
        warning = tk.StringVar(value="K100: 0 / 0 / 0 / 100. Цветной PDF не считается однокрасочным.")
        ttk.Label(frame, textvariable=warning, wraplength=370).grid(row=4, column=0, columnspan=2, pady=10)
        def apply():
            try:
                ink = tuple(float(v.get().replace(",", ".")) for v in variables)
                self.print_settings = dataclasses.replace(self.print_settings, ink=ink)
                self.remember()
                window.destroy()
            except ValueError as exc:
                warning.set(str(exc))
        ttk.Button(frame, text="Применить", command=apply).grid(row=5, column=0, columnspan=2)

    def performance_dialog(self):
        from .mergers import available_adapters
        window = tk.Toplevel(self.root)
        window.title("Реальные параметры тестов")
        frame = ttk.Frame(window, padding=16)
        frame.pack()
        ttk.Label(frame, text=f"Один рабочий процесс · логических CPU: {os.cpu_count()}\nДоступность движков определяется перед запуском.\nНедоступные получают SKIPPED; установки нет.").pack(anchor="w", pady=(0, 10))
        options = []
        for adapter in available_adapters():
            available = adapter.probe()["available"]
            var = tk.BooleanVar(value=available and (self.selected_engines is None or adapter.name in self.selected_engines))
            options.append((adapter.name, var))
            ttk.Checkbutton(frame, text=adapter.name + ("" if available else " — недоступен"), variable=var,
                            state="normal" if available else "disabled").pack(anchor="w")
        def apply():
            self.selected_engines = [name for name, var in options if var.get()]
            window.destroy()
        ttk.Button(frame, text="Применить", command=apply).pack(pady=8)

    def open_path(self, path):
        path = Path(path)
        if not path.exists():
            messagebox.showinfo("uCode", "Файлы ещё не созданы", parent=self.root)
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
        messagebox.showinfo("uCode — Справка", HELP_TEXT, parent=self.root)

    def close(self):
        if self.busy or (self.worker is not None and self.worker.is_alive()):
            self.closing = True
            self.request_cancel()
        else:
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
