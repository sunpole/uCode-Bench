"""Minimal local Windows GUI; all PDF work runs outside the tkinter thread."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import webbrowser

from .config import Experiment


class Application:
    def __init__(self, root, output_root=None):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.output_root = Path(output_root or Path(__file__).resolve().parents[1] / "output" / "runs")
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.closing = False
        self.latest_directory = None
        self.qualifying_report = None
        self.worker = None
        root.title("uCode — QR-бенчмарк")
        root.geometry("760x570")
        root.minsize(650, 460)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="uCode", font=("Segoe UI", 24, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Локальная лаборатория QR и PDF", font=("Segoe UI", 12)).pack(anchor="w", pady=(0, 14))
        ttk.Label(frame, text="200 номеров · QR Code M · 0,5 мм · поле 4 модуля · CMYK K100\n"
                  "Три повтора. Допуск к 1000: QA PASS и медиана <120 с.", wraplength=690).pack(anchor="w", pady=(0, 16))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.create_button = ttk.Button(buttons, text="Создать 200 QR", command=lambda: self.start("create"))
        self.run_button = ttk.Button(buttons, text="Запустить бенчмарк", command=lambda: self.start("benchmark"))
        self.open_button = ttk.Button(buttons, text="Открыть результаты", command=self.open_results)
        self.next_button = ttk.Button(buttons, text="Перейти к 1000", command=lambda: self.start("1000"))
        self.batch_button = ttk.Button(buttons, text="TXT → реальные PDF (200 / 1 000 / 10 000)", command=self.open_batch)
        for index, button in enumerate((self.create_button, self.run_button, self.open_button, self.next_button, self.batch_button)):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 5, 5 if index % 2 == 0 else 0), pady=5, ipady=7)
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(15, 7))
        self.status = tk.StringVar(value="Готово к первому запуску.")
        ttk.Label(frame, textvariable=self.status, wraplength=690).pack(anchor="w")
        self.next_status = tk.StringVar(value="Этап на 1000 заблокирован до успешного отчёта на 200.")
        ttk.Label(frame, textvariable=self.next_status, wraplength=690).pack(anchor="w", pady=(6, 8))
        self.log = tk.Text(frame, height=9, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.cancel_button = ttk.Button(frame, text="Отменить после текущего шага", command=self.request_cancel)
        self.cancel_button.pack(anchor="e", pady=(10, 0))
        self.discover_results()
        self.update_buttons()
        root.after(100, self.drain_events)

    def discover_results(self):
        if not self.output_root.exists():
            return
        candidates = sorted(self.output_root.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            self.latest_directory = candidates[0].parent
        from .benchmark import load_qualifying_methods
        for report in candidates:
            try:
                methods = load_qualifying_methods(report)
            except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if methods:
                self.qualifying_report = report
                self.next_status.set("Допуск к 1000: " + ", ".join(methods) + ". Запуск только по кнопке.")
                break

    def update_buttons(self):
        enabled = "disabled" if self.busy else "normal"
        self.create_button.configure(state=enabled)
        self.batch_button.configure(state=enabled)
        self.run_button.configure(state=enabled)
        self.open_button.configure(state="normal" if self.latest_directory and not self.busy else "disabled")
        self.next_button.configure(state="normal" if self.qualifying_report and not self.busy else "disabled")
        self.cancel_button.configure(state="normal" if self.busy and not self.cancel_event.is_set() else "disabled")

    def start(self, operation):
        from tkinter import messagebox
        if self.busy:
            return
        allowed_methods = None
        if operation == "1000":
            from .benchmark import load_qualifying_methods
            try:
                if self.qualifying_report is None:
                    raise ValueError("Сначала нужен успешный отчёт на 200 файлов.")
                allowed_methods = load_qualifying_methods(self.qualifying_report)
                if not allowed_methods:
                    raise ValueError("В отчёте нет методов, допущенных к 1000.")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.qualifying_report = None
                self.update_buttons()
                messagebox.showerror("Нет допуска к 1000", str(exc), parent=self.root)
                return
        self.cancel_event = threading.Event()
        self.busy = True
        self.update_buttons()
        self.progress.start(20)
        self.status.set("Запуск 1000 файлов…" if operation == "1000" else "Создание 200 QR…" if operation == "create" else "Бенчмарк 200 файлов…")

        def work():
            try:
                from .benchmark import create_inputs, run_experiment
                callback = lambda message: self.events.put(("progress", str(message)))
                config = Experiment(count=1000 if operation == "1000" else 200)
                if operation == "create":
                    directory = create_inputs(self.output_root, config, progress=callback, cancel=self.cancel_event)
                else:
                    directory = run_experiment(self.output_root, config, progress=callback, cancel=self.cancel_event, allowed_methods=allowed_methods)
                directory = Path(directory)
                report_path = directory / "report.json"
                report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"status": "COMPLETE"}
                self.events.put(("done", {"directory": directory, "report": report}))
            except Exception as exc:
                self.events.put(("cancelled" if type(exc).__name__ == "Cancelled" else "error", f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=work, name="ucode-worker", daemon=False)
        self.worker.start()

    def append_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain_events(self):
        from tkinter import messagebox
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                    self.append_log(value)
                else:
                    self.busy = False
                    self.progress.stop()
                    if kind == "done":
                        self.discover_results()
                        self.latest_directory = value["directory"]
                        report = value["report"]
                        run_status = report.get("status", "ERROR")
                        failed_methods = [m.get("name", "?") for m in report.get("methods", []) if m.get("status") in ("ERROR", "INVALID")]
                        if run_status == "CANCELLED":
                            message = "Отменено. Сохранённые результаты: "
                        elif run_status == "ERROR":
                            message = "Ошибка запуска. Отчёт и сохранённые результаты: "
                        elif run_status != "COMPLETE":
                            message = "Запуск не завершён (" + str(run_status) + "). Результаты: "
                        elif failed_methods:
                            message = "Бенчмарк завершён с ошибками методов: " + ", ".join(failed_methods) + ". Отчёт: "
                        else:
                            message = "Готово: "
                        self.status.set(message + str(self.latest_directory))
                        self.append_log(message + str(self.latest_directory))
                        if report.get("error"):
                            self.append_log(str(report["error"]))
                        if run_status == "ERROR" and not self.closing:
                            messagebox.showerror("Ошибка uCode", str(report.get("error", "Подробности сохранены в отчёте.")), parent=self.root)
                    elif kind == "cancelled":
                        self.status.set("Отменено. Уже созданные файлы оставлены на диске.")
                        self.append_log(value)
                    else:
                        self.status.set("Операция завершилась с ошибкой. Сохранённые результаты оставлены на диске.")
                        self.append_log(value)
                        if not self.closing:
                            messagebox.showerror("Ошибка uCode", value, parent=self.root)
                    self.update_buttons()
        except queue.Empty:
            pass
        worker_finished = self.worker is None or not self.worker.is_alive()
        if self.closing and not self.busy and worker_finished:
            self.root.destroy()
        else:
            self.root.after(100, self.drain_events)

    def request_cancel(self):
        self.cancel_event.set()
        self.status.set("Отмена запрошена. Ожидание окончания текущего шага; результаты сохраняются.")
        self.update_buttons()

    def open_batch(self):
        from .batch_gui import open_window
        open_window(self.root)

    def open_results(self):
        if self.latest_directory is None:
            return
        report = self.latest_directory / "report.html"
        if report.exists():
            webbrowser.open(report.resolve().as_uri())
        elif hasattr(os, "startfile"):
            os.startfile(str(self.latest_directory.resolve()))

    def close(self):
        if self.busy or (self.worker is not None and self.worker.is_alive()):
            self.closing = True
            self.request_cancel()
        else:
            self.root.destroy()


def main():
    import tkinter as tk
    root = tk.Tk()
    # Keep Tk variables owned by the creating thread until the worker exits.
    application = Application(root)
    root.mainloop()
    del application
