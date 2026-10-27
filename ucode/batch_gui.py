"""Operator-friendly uCode PDF batch window. All long-running operations use a worker."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .batch import load_codes, make_template, run_batch
from .print_settings import PrintSettings, format_duration, human_report

PROJECT = Path(__file__).resolve().parents[1]
HELP_TEXT = """uCode — КРАТКАЯ ИНСТРУКЦИЯ

1. Подготовьте UTF-8 TXT. Каждая строка — ровно 12 цифр, без пробелов.
   Пустые строки не допускаются. Сейчас: от 1 до 10 000 кодов.
2. Выберите свой TXT кнопкой «Открыть TXT».
   Кнопки 200 / 1 000 / 10 000 создают примеры, не заменяют ваш файл.
3. Выберите результат: отдельные PDF, один общий PDF либо оба вида.
4. Укажите общий физический размер квадратной страницы PDF.
   В него входят сам QR и белое поле.
5. Белое поле: от 4 до 20 модулей. Меньше 4 нарушает стандарт QR.
   При изменении поля и неизменном общем размере сам QR уменьшается.
6. Нажмите «Создать PDF», затем «Показать файлы».

РЕЗУЛЬТАТ
output/jobs/pdf-.../singles/             — отдельные PDF
output/jobs/pdf-.../all-N-pages.pdf      — общий PDF
output/jobs/pdf-.../ОТЧЁТ.txt            — понятное время и качество
output/jobs/pdf-.../manifest.json        — подробная диагностика

КАК ОЦЕНИВАТЬ ВРЕМЯ
В «ОТЧЁТ.txt» есть общее фактическое время в ч/мин/сек,
время кодирования, создания PDF и проверки. QA считается отдельно.

ПЕЧАТЬ
QR версии 1/M, векторный C0 M0 Y0 K100, без RGB-чёрного.
Минимальное поле — 4 модуля. PDF/X-профиль пока не заявлен.
Очень мелкие модули могут плохо читаться: выполните реальную
пробную печать и проверьте сканером.

СЛОЖНЫЕ ТИРАЖИ
Сейчас предел 10 000 кодов за запуск. Для миллионов потребуется
другой движок с порционной обработкой и защитой памяти/диска.
Программа сейчас не выбирает количество ядер и метод по скорости:
быстрейший метод должен быть подтверждён отдельным тестом на ПК.
"""


class BatchWindow:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_output = None
        self.busy = False
        self.closing = False
        self.started = None

        root.title("uCode — Создание печатных QR из TXT")
        root.geometry("900x735")
        root.minsize(750, 630)
        root.protocol("WM_DELETE_WINDOW", self.close)

        main = ttk.Frame(root, padding=18)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        head = ttk.Frame(main)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Создание QR-кодов в PDF", font=("Segoe UI", 19, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(head, text="Печатные PDF из обычного TXT · 1 строка = 1 QR", foreground="#555555").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Button(head, text="Инструкция и помощь", command=self.show_help).grid(row=0, column=1, rowspan=2, padx=(15, 0))

        source = ttk.LabelFrame(main, text="1. Выберите номера", padding=11)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)
        line = ttk.Frame(source)
        line.grid(row=0, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        self.input_var = tk.StringVar()
        self.entry = ttk.Entry(line, textvariable=self.input_var)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.browse = ttk.Button(line, text="Открыть TXT…", command=self.choose)
        self.browse.grid(row=0, column=1)
        example = ttk.Frame(source)
        example.grid(row=1, column=0, sticky="w", pady=(9, 0))
        ttk.Label(example, text="Создать пример:").pack(side="left", padx=(0, 8))
        self.templates = []
        for n in (200, 1000, 10000):
            button = ttk.Button(example, text=f"{n:,}".replace(",", " "), command=lambda value=n: self.template(value))
            button.pack(side="left", padx=(0, 7))
            self.templates.append(button)
        self.file_count = tk.StringVar(value="Допускается максимум 10 000 кодов. Только 12 цифр в строке.")
        ttk.Label(source, textvariable=self.file_count, foreground="#555555").grid(row=2, column=0, sticky="w", pady=(8, 0))

        output = ttk.LabelFrame(main, text="2. Какие PDF нужны?", padding=11)
        output.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.mode_var = tk.StringVar(value="multipage")
        self.mode_buttons = []
        for text, value in (
            ("Оба варианта: отдельные + общий", "both"),
            ("Только общий многостраничный PDF", "multipage"),
            ("Только отдельные PDF", "singles"),
        ):
            radio = ttk.Radiobutton(output, text=text, variable=self.mode_var, value=value)
            radio.pack(anchor="w", pady=2)
            self.mode_buttons.append(radio)
        ttk.Label(output, text="По умолчанию выбран один PDF: меньше файлов, меньше операций записи. Режим не означает автоматический подбор движка.", foreground="#555555", wraplength=820).pack(anchor="w", pady=(5, 0))

        geometry = ttk.LabelFrame(main, text="3. Размер и белое поле", padding=11)
        geometry.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.total_mm = tk.StringVar(value="14,5")
        self.margin = tk.StringVar(value="4")
        row = ttk.Frame(geometry)
        row.pack(fill="x")
        ttk.Label(row, text="Весь QR с белым полем, мм:").pack(side="left")
        self.size_box = ttk.Entry(row, textvariable=self.total_mm, width=10)
        self.size_box.pack(side="left", padx=(8, 24))
        ttk.Label(row, text="Белое поле, модулей:").pack(side="left")
        self.margin_box = ttk.Combobox(row, textvariable=self.margin, values=[str(i) for i in range(4, 21)], state="readonly", width=6)
        self.margin_box.pack(side="left", padx=(8, 0))
        self.geometry_summary = tk.StringVar()
        ttk.Label(geometry, textvariable=self.geometry_summary, foreground="#205b38", wraplength=820).pack(anchor="w", pady=(10, 2))
        ttk.Label(geometry, text="Ограничения: поле не меньше 4 модулей; модуль 0,25–2,0 мм. Малые размеры требуют пробной печати.", wraplength=820, foreground="#555555").pack(anchor="w")
        self.total_mm.trace_add("write", lambda *_: self.update_geometry())
        self.margin.trace_add("write", lambda *_: self.update_geometry())
        self.update_geometry()

        controls = ttk.Frame(main)
        controls.grid(row=4, column=0, sticky="ew", pady=(2, 7))
        self.generate = ttk.Button(controls, text="Создать PDF", command=self.start)
        self.generate.pack(side="left", ipady=7)
        self.stop = ttk.Button(controls, text="Остановить", command=self.request_cancel)
        self.stop.pack(side="left", padx=(9, 0), ipady=7)
        self.open = ttk.Button(controls, text="Показать файлы", command=self.open_result)
        self.open.pack(side="left", padx=(9, 0), ipady=7)
        self.elapsed_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.elapsed_var, font=("Segoe UI", 10, "bold")).pack(side="right")

        self.status_var = tk.StringVar(value=f"Готово. Движок ReportLab · один процесс · доступно логических CPU: {os.cpu_count() or 'неизвестно'}. Начните с TXT.")
        ttk.Label(main, textvariable=self.status_var, wraplength=830).grid(row=5, column=0, sticky="w", pady=(2, 8))
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.grid(row=6, column=0, sticky="ew", pady=(0, 8))

        result = ttk.LabelFrame(main, text="Результат и фактическое время", padding=9)
        result.grid(row=7, column=0, sticky="nsew")
        result.columnconfigure(0, weight=1)
        result.rowconfigure(0, weight=1)
        main.rowconfigure(7, weight=1)
        self.log = tk.Text(result, height=9, wrap="word", state="disabled", font=("Consolas", 10), bg="#f8f8f8")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(result, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.append("После генерации здесь появится понятный отчёт со временем в ч/мин/сек.")
        self.update_buttons()
        root.after(150, self.poll)

    def settings(self):
        try:
            total = float(self.total_mm.get().strip().replace(",", "."))
            q = int(self.margin.get())
            return PrintSettings.from_total_side(total, q)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Проверьте размер и белое поле: {exc}") from exc

    def update_geometry(self):
        try:
            p = self.settings()
            info = (f"Размер готового PDF: {p.side_mm:.2f} × {p.side_mm:.2f} мм. "
                    f"Чёрный QR: {p.dark_matrix_mm:.2f} мм; "
                    f"белое поле с каждой стороны: {p.white_margin_mm:.2f} мм. "
                    f"Модуль: {p.module_mm:.3f} мм.")
            self.geometry_summary.set(info.replace(".", ","))
        except ValueError as exc:
            self.geometry_summary.set(str(exc))

    def append(self, message, replace=False):
        self.log.configure(state="normal")
        if replace:
            self.log.delete("1.0", "end")
        self.log.insert("end", str(message) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def update_buttons(self):
        state = "disabled" if self.busy else "normal"
        for b in self.templates + [self.browse, self.generate]:
            b.configure(state=state)
        for b in self.mode_buttons:
            b.configure(state=state)
        self.entry.configure(state=state)
        self.size_box.configure(state=state)
        self.margin_box.configure(state="disabled" if self.busy else "readonly")
        self.stop.configure(state="normal" if self.busy and not self.cancel.is_set() else "disabled")
        self.open.configure(state="normal" if self.last_output else "disabled")

    def choose(self):
        path = filedialog.askopenfilename(parent=self.root, title="Выберите TXT с QR-номерами",
                                          filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")])
        if path:
            self.input_var.set(path)
            self.inspect_input()

    def inspect_input(self):
        try:
            values = load_codes(Path(self.input_var.get()))
            self.file_count.set(f"Проверено: {len(values):,} кодов. Первый: {values[0]}; последний: {values[-1]}.".replace(",", " "))
            return values
        except (ValueError, OSError) as exc:
            self.file_count.set(f"Ошибка TXT: {exc}")
            return None

    def template(self, count):
        try:
            path = make_template(PROJECT / "output" / "templates", count)
            self.input_var.set(str(path))
            self.inspect_input()
            self.status_var.set(f"Создан пример на {count:,} кодов. Можно запускать.".replace(",", " "))
        except (ValueError, OSError) as exc:
            messagebox.showerror("Не удалось создать TXT", str(exc), parent=self.root)

    def start(self):
        if self.busy:
            return
        numbers = self.inspect_input()
        if numbers is None:
            messagebox.showerror("Проверьте TXT", self.file_count.get(), parent=self.root)
            return
        try:
            settings = self.settings()
        except ValueError as exc:
            messagebox.showerror("Проверьте размеры", str(exc), parent=self.root)
            return

        self.cancel = threading.Event()
        self.busy = True
        self.started = time.perf_counter()
        self.update_buttons()
        self.progress.start(15)
        self.append(f"Запуск: {len(numbers)} кодов, PDF {settings.side_mm:.2f} мм, поле {settings.quiet_modules}.", replace=True)
        mode = self.mode_var.get()
        path = Path(self.input_var.get())

        def work():
            try:
                folder = run_batch(path, PROJECT / "output" / "jobs", mode=mode, settings=settings,
                                   cancel=self.cancel, progress=lambda msg: self.events.put(("progress", msg)))
                self.events.put(("done", folder))
            except Exception as exc:
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=work, name="ucode-print-worker", daemon=False)
        self.worker.start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status_var.set(str(value))
                else:
                    self.busy = False
                    self.progress.stop()
                    if kind == "done":
                        self.last_output = Path(value)
                        report = json.loads((self.last_output / "manifest.json").read_text(encoding="utf-8"))
                        self.status_var.set(f"{report['status']}: {report['count']} кодов. Нажмите «Показать файлы».")
                        self.append(human_report(report), replace=True)
                        self.append(f"\nПапка результата:\n{self.last_output}")
                        self.elapsed_var.set("Итого: " + format_duration(report.get("seconds", {}).get("total_including_qa")))
                        if report["status"] not in ("COMPLETE", "LIMITED") and not self.closing:
                            messagebox.showwarning("Ошибки PDF", "Проверьте ОТЧЁТ.txt и manifest.json", parent=self.root)
                    else:
                        self.status_var.set(str(value))
                        self.append(str(value))
                        if not self.closing:
                            messagebox.showerror("Ошибка", str(value), parent=self.root)
                    self.update_buttons()
        except queue.Empty:
            pass
        if self.busy and self.started is not None:
            self.elapsed_var.set("Идёт: " + format_duration(time.perf_counter() - self.started))
        if self.closing and not self.busy and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
        else:
            self.root.after(150, self.poll)

    def request_cancel(self):
        self.cancel.set()
        self.status_var.set("Отмена запрошена. Созданные PDF останутся на диске.")
        self.update_buttons()

    def open_result(self):
        if self.last_output and hasattr(os, "startfile"):
            os.startfile(str(self.last_output))
        elif self.last_output:
            messagebox.showinfo("Каталог результата", str(self.last_output), parent=self.root)

    def show_help(self):
        window = tk.Toplevel(self.root)
        window.title("uCode — Инструкция и требования к печати")
        window.geometry("760x620")
        window.transient(self.root)
        body = ttk.Frame(window, padding=14)
        body.pack(fill="both", expand=True)
        content = tk.Text(body, wrap="word", padx=12, pady=12, font=("Segoe UI", 10))
        content.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(body, command=content.yview)
        scrollbar.pack(side="right", fill="y")
        content.configure(yscrollcommand=scrollbar.set)
        content.insert("1.0", HELP_TEXT)
        content.configure(state="disabled")

    def close(self):
        if self.busy or (self.worker is not None and self.worker.is_alive()):
            self.closing = True
            self.request_cancel()
        else:
            self.root.destroy()


def open_window(parent):
    window = tk.Toplevel(parent)
    return BatchWindow(window)


def main():
    root = tk.Tk()
    controller = BatchWindow(root)
    root.mainloop()
    del controller


if __name__ == "__main__":
    main()
