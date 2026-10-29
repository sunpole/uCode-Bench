"""Paged browser for all local test types, with text-only historical import."""
import json
import sqlite3
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog,ttk

from .test_archive import archive_rows,import_tests,KINDS,STATES


class ArchiveView:
    def __init__(self,app):
        self.app=app; self.rows=[]; self.page=0; self.visible=[]
        self.path=app.preferences_path.with_name("archive-settings.json")
        app.archive_root=app.output_root/"test-archive"
        try:
            saved=json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved.get("directory"),str) and saved["directory"]: app.archive_root=Path(saved["directory"])
        except (OSError,ValueError,AttributeError): pass
        self.note=tk.StringVar(master=app.root,value="Новые тесты сохраняются автоматически после измерений. Только текст, без PDF и входных TXT.")
        page=app.pages["archive"]; row=ttk.Frame(page); row.pack(anchor="w")
        for text,action in (("Обновить",self.refresh),("Добавить старые тесты…",self.import_old),("Папка архива…",self.choose),("Все в браузере",self.open_index)):
            app.edit(ttk.Button(row,text=text,command=action)).pack(side="left",padx=(0,5))
        self.table=ttk.Treeview(page,columns=("date","kind","cpu","codes","status"),show="headings",height=3,style="History.Treeview")
        for key,label,width in (("date","Дата UTC",160),("kind","Вид теста",145),("cpu","Процессор",260),("codes","Кодов",120),("status","Статус",120)):
            self.table.heading(key,text=label); self.table.column(key,width=width,minwidth=0)
        self.table.pack(fill="both",expand=True,pady=3)
        self.table.bind("<Double-1>",lambda event:self.open_report())
        ttk.Label(page,textvariable=self.note,style="Muted.TLabel",wraplength=900).pack(anchor="w")
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        for text,action in (("‹",lambda:self.turn(-1)),("›",lambda:self.turn(1)),("Открыть отчёт",self.open_report),("Графики",self.open_graphs),("Графики из JSON…",self.choose_graphs),("Открыть папку",lambda:app.open_path(app.archive_root))):
            app.edit(ttk.Button(row,text=text,command=action)).pack(side="left",padx=(0,5))
        self.position=tk.StringVar(master=app.root)
        ttk.Label(row,textvariable=self.position).pack(side="left")
        self.refresh()

    def refresh(self):
        try: self.rows=archive_rows(self.app.archive_root); self.render()
        except (OSError,ValueError,sqlite3.Error) as exc: self.note.set("Архив: "+str(exc))
    def render(self):
        size=3; pages=max(1,(len(self.rows)+size-1)//size); self.page=max(0,min(self.page,pages-1))
        self.visible=self.rows[self.page*size:(self.page+1)*size]; self.table.delete(*self.table.get_children())
        for i,r in enumerate(self.visible): self.table.insert("","end",iid=str(i),values=(r["created"][:19].replace("T"," "),KINDS.get(r["kind"],r["kind"]),r["cpu"],r["counts"],STATES.get(r["status"],r["status"])))
        self.position.set(f"{self.page+1} / {pages} · записей: {len(self.rows)}"+(" (первые1000)" if len(self.rows)==1000 else ""))
    def turn(self,amount): self.page+=amount; self.render()
    def choose(self):
        chosen=filedialog.askdirectory(parent=self.app.root,title="Локальная папка архива тестов",initialdir=str(self.app.archive_root))
        if chosen:
            from .lab_worker import atomic_json
            self.app.archive_root=Path(chosen); self.path.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(self.path,{"directory":chosen,"pdf":False}); self.page=0; self.refresh()
    def open_index(self): self.app.open_path(self.app.archive_root/"index.html")
    def open_report(self):
        selected=self.table.selection()
        if not selected: return
        path=(self.app.archive_root/self.visible[int(selected[0])]["file"]).resolve()
        if not path.is_relative_to(self.app.archive_root.resolve()): self.note.set("Ссылка выходит за папку архива"); return
        self.app.open_path(path)
    def open_graphs(self):
        selected=self.table.selection()
        if not selected:
            self.note.set("Выберите сохранённый тест или нажмите «Графики из JSON…»")
            return
        path=(self.app.archive_root/self.visible[int(selected[0])]["file"]).resolve()
        if not path.is_relative_to(self.app.archive_root.resolve()):
            self.note.set("Ссылка выходит за папку архива"); return
        self.create_graphs(path.with_name("report.json"))
    def choose_graphs(self):
        if self.app.busy: return
        chosen=filedialog.askopenfilename(parent=self.app.root,title="Сохранённый JSON-отчёт теста uCode",initialdir=str(self.app.output_root),filetypes=[("Отчёт uCode","*.json")])
        if chosen: self.create_graphs(Path(chosen))
    def create_graphs(self,source):
        if self.app.busy: return
        from .graphical_report import write_graphical_copy
        self.app.busy=True; self.app.started=None; self.app.update_buttons()
        self.note.set("Подготовка графиков из сохранённых измерений…")
        def work():
            try:
                report=write_graphical_copy(source,self.app.archive_root/"views")
                self.app.events.put(("archive_graph",str(report)))
            except Exception as exc: self.app.events.put(("archive_error",str(exc)))
        self.app.worker=threading.Thread(target=work,name="ucode-graphs",daemon=False); self.app.worker.start()
    def import_old(self):
        if self.app.busy: return
        source=filedialog.askdirectory(parent=self.app.root,title="Папка с предыдущими результатами uCode",initialdir=str(self.app.output_root))
        if not source: return
        self.app.cancel=threading.Event(); self.app.busy=True; self.app.started=None; self.app.update_buttons()
        def work():
            try:
                receipts=import_tests(source,self.app.archive_root,cancel=self.app.cancel)
                self.app.events.put(("archive_import",{"saved":sum(r["status"]=="SAVED" and not r.get("duplicate") for r in receipts),"errors":sum(r["status"]=="ERROR" for r in receipts)}))
            except Exception as exc: self.app.events.put(("archive_error",str(exc)))
        self.app.worker=threading.Thread(target=work,name="ucode-archive",daemon=False); self.app.worker.start()
