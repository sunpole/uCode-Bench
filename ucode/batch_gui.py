"""Tkinter TXT import/template/PDF export window, separate from benchmark GUI."""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import threading
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from .batch import make_template, run_batch

PROJECT = Path(__file__).resolve().parents[1]


class BatchWindow:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_output = None
        root.title("uCode — TXT → печатные PDF")
        root.geometry("790x530")
        root.minsize(640, 460)
        root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="TXT → QR → PDF", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Одна строка TXT = один QR. Только 12 цифр, QR V1-M, 14,5 × 14,5 мм, векторный CMYK K100.",
                  wraplength=710).pack(anchor="w", pady=(5, 12))
        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        ttk.Label(bar, text="Создать TXT:").pack(side="left", padx=(0, 8))
        self.buttons = []
        for count in (200, 1000, 10000):
            button = ttk.Button(bar, text=f"{count:,}".replace(",", " "), command=lambda n=count: self.template(n))
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)

        source = ttk.Frame(frame)
        source.pack(fill="x", pady=(15, 4))
        self.input_var = tk.StringVar()
        ttk.Label(source, text="TXT:").pack(side="left", padx=(0, 6))
        self.entry = ttk.Entry(source, textvariable=self.input_var)
        self.entry.pack(side="left", fill="x", expand=True)
        self.browse = ttk.Button(source, text="Выбрать…", command=self.choose)
        self.browse.pack(side="left", padx=(8, 0))

        modebar = ttk.Frame(frame)
        modebar.pack(fill="x", pady=(10, 6))
        ttk.Label(modebar, text="Результат:").pack(side="left", padx=(0, 8))
        self.mode_var = tk.StringVar(value="both")
        for label, value in (("Оба варианта", "both"), ("Отдельные PDF", "singles"),
                             ("Один многостраничный PDF", "multipage")):
            ttk.Radiobutton(modebar, text=label, variable=self.mode_var, value=value).pack(side="left", padx=(0, 10))

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(12, 8))
        self.generate = ttk.Button(controls, text="Генерировать реальные PDF", command=self.start)
        self.generate.pack(side="left")
        self.stop = ttk.Button(controls, text="Остановить после шага", command=self.request_cancel)
        self.stop.pack(side="left", padx=(8, 0))
        self.open = ttk.Button(controls, text="Открыть результат", command=self.open_result)
        self.open.pack(side="left", padx=(8, 0))

        self.status = tk.StringVar(value="Выберите TXT или создайте шаблон. Никакой установки не требуется.")
        ttk.Label(frame, textvariable=self.status, wraplength=720).pack(anchor="w", pady=(8, 5))
        self.log = tk.Text(frame, wrap="word", state="disabled", font=("Consolas", 10), height=10)
        self.log.pack(fill="both", expand=True)
        self.busy = False
        self.closing = False
        self.update_buttons()
        root.after(100, self.poll)

    def append(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def update_buttons(self):
        state = "disabled" if self.busy else "normal"
        for button in self.buttons + [self.browse, self.generate]:
            button.configure(state=state)
        self.stop.configure(state="normal" if self.busy and not self.cancel.is_set() else "disabled")
        self.open.configure(state="normal" if self.last_output else "disabled")

    def template(self, count):
        try:
            path = make_template(PROJECT / "output" / "templates", count)
            self.input_var.set(str(path))
            self.status.set(f"TXT готов: {path}")
            self.append(f"Создан шаблон {count} строк: {path}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Ошибка TXT", str(exc), parent=self.root)

    def choose(self):
        path = filedialog.askopenfilename(parent=self.root, title="Выберите TXT со строками QR",
                                          filetypes=[("TXT", "*.txt"), ("Все файлы", "*.*")])
        if path:
            self.input_var.set(path)

    def start(self):
        if self.busy:
            return
        path = Path(self.input_var.get())
        if not path.is_file():
            messagebox.showerror("Нет TXT", "Выберите существующий файл TXT", parent=self.root)
            return
        try:
            from .batch import load_codes
            count = len(load_codes(path))
        except (ValueError, OSError) as exc:
            messagebox.showerror("Неверный TXT", str(exc), parent=self.root)
            return
        self.cancel = threading.Event()
        self.busy = True
        mode = self.mode_var.get()
        self.status.set(f"Запущена генерация {count} кодов, режим: {mode}")
        self.update_buttons()

        def work():
            try:
                result = run_batch(path, PROJECT / "output" / "jobs", mode=mode, cancel=self.cancel,
                                   progress=lambda s: self.events.put(("line", s)))
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=work, name="ucode-batch", daemon=False)
        self.worker.start()

    def poll(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "line":
                    self.status.set(str(value))
                    self.append(str(value))
                else:
                    self.busy = False
                    if event == "done":
                        self.last_output = Path(value)
                        report = json.loads((self.last_output / "manifest.json").read_text(encoding="utf-8"))
                        self.status.set(f"{report['status']}: {report['count']} кодов, файлы: {self.last_output}")
                        self.append("Итог: " + self.status.get())
                        if report["status"] not in ("COMPLETE", "LIMITED") and not self.closing:
                            messagebox.showwarning("Проверка PDF", "Генерация не прошла все проверки. Откройте manifest.json.", parent=self.root)
                    else:
                        self.status.set(str(value))
                        self.append(str(value))
                        if not self.closing:
                            messagebox.showerror("Ошибка", str(value), parent=self.root)
                    self.update_buttons()
        except queue.Empty:
            pass
        if self.closing and not self.busy and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
        else:
            self.root.after(100, self.poll)

    def request_cancel(self):
        self.cancel.set()
        self.status.set("Отмена запрошена; файлы не удаляются")
        self.update_buttons()

    def open_result(self):
        if self.last_output and hasattr(os, "startfile"):
            os.startfile(str(self.last_output))
        elif self.last_output:
            messagebox.showinfo("Каталог результата", str(self.last_output), parent=self.root)

    def close(self):
        if self.busy or (self.worker and self.worker.is_alive()):
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
