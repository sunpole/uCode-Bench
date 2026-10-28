"""One-window paged history. Disk reads run in the existing owned worker slot."""
import math
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog,ttk

from .history import scan_history,read_run,artifact_path,pdf_for_case

PAGE_SIZE=4
STATUSES={"PASS":"QA PASS*","COMPLETE":"Завершён","SKIPPED":"Пропущен","UNVERIFIED":"Не подтверждён",
          "CANCELLED":"Остановлен","RUNNING":"Не завершён","NOT_RUN":"Не выполнен","INVALID":"Ошибка проверки",
          "ERROR":"Ошибка","ОШИБКА":"Ошибка чтения","ОТКРОЙТЕ":"Откройте замеры"}


def _short(value,size=70): return str(value).replace("\n"," ").replace("\r"," ")[:size]
def _status(value): return STATUSES.get(value,_short(value,24))
def _dict(value): return value if isinstance(value,dict) else {}
def _seconds(value): return "—" if value is None else f"{value:.4f}".replace(".",",")


class HistoryView:
    def __init__(self,app):
        self.app=app; self.root_path=None; self.entries=[]; self.run=None; self.mode="runs"; self.page=0; self.visible=[]
        self.rows_per_page=3 if float(app.root.tk.call("tk","scaling"))>=1.85 else PAGE_SIZE
        self.note="Сохранённые результаты. Новая генерация и QA здесь не запускаются."
        page=app.pages["history"]
        self.filter=tk.StringVar(master=app.root,value="Все")
        self.search=tk.StringVar(master=app.root)
        row=ttk.Frame(page); row.pack(fill="x")
        for text,command in (("Мои тесты",self.own_folder),("Другая папка…",self.choose_folder),("Обновить",self.refresh)):
            app.edit(ttk.Button(row,text=text,command=command)).pack(side="left",padx=(0,6))
        app.edit(ttk.Combobox(row,values=("Все","Успешные","С проблемами"),textvariable=self.filter,state="readonly",width=13),"readonly").pack(side="left",padx=6)
        ttk.Label(row,text="Поиск:").pack(side="left")
        app.edit(ttk.Entry(row,textvariable=self.search,width=14)).pack(side="left",padx=5)
        self.table=ttk.Treeview(page,columns=("a","b","c","d","e","f"),show="headings",height=self.rows_per_page,style="History.Treeview",selectmode="browse")
        self.table.pack(fill="both",expand=True,pady=3)
        self.table.tag_configure("good",foreground="#5ce0bd"); self.table.tag_configure("bad",foreground="#f28a8a")
        self.table.bind("<<TreeviewSelect>>",lambda event:self.selected())
        self.table.bind("<Double-1>",lambda event:self.show_cases())
        self.details=tk.Text(page,height=2,width=85,wrap="word",font=("Segoe UI",8),relief="flat",borderwidth=0,
                             background="#0b1220",foreground="#a5b7ce",state="disabled")
        self.details.pack(fill="x")
        row=ttk.Frame(page); row.pack(fill="x",pady=2)
        self.buttons={}
        for key,text,command in (("back","← Запуски",self.back),("cases","Замеры →",self.show_cases),
                                 ("previous","‹",lambda:self.turn(-1)),("next","›",lambda:self.turn(1)),
                                 ("report","Отчёт в браузере",lambda:self.open("report")),
                                 ("pdf","PDF",lambda:self.open("pdf")),("folder","Папка",lambda:self.open("folder"))):
            button=ttk.Button(row,text=text,command=command); button.pack(side="left",padx=(0,5)); self.buttons[key]=button
        self.page_label=tk.StringVar(master=app.root)
        ttk.Label(row,textvariable=self.page_label,style="Muted.TLabel").pack(side="left",padx=5)
        self.filter.trace_add("write",lambda *_:self.render(reset=True))
        self.search.trace_add("write",lambda *_:self.render(reset=True))
        def opened(event):
            if (app.notebook.select()==str(page) and self.root_path is None and not app.busy and hasattr(app,"generate")):
                self.own_folder()
        app.notebook.bind("<<NotebookTabChanged>>",opened,add="+")
        self.render()

    def own_folder(self): self.refresh(Path(self.app.destination_var.get() or self.app.output_root/"jobs")/"laboratory")

    def choose_folder(self):
        chosen=filedialog.askdirectory(parent=self.app.root,title="Папка с запусками лаборатории или одним lab.json",
                                       initialdir=str(self.root_path or self.app.output_root))
        if chosen: self.refresh(Path(chosen))

    def launch(self,kind,action):
        if self.app.busy: return
        self.app.cancel=threading.Event(); self.app.busy=True; self.app.started=None
        self.app.status_var.set("Чтение сохранённых результатов…")
        self.app.update_buttons()
        def work():
            try: self.app.events.put(("history",(kind,action())))
            except Exception as exc: self.app.events.put(("history_error",str(exc)))
        self.app.worker=threading.Thread(target=work,name="ucode-history",daemon=False)
        self.app.worker.start()

    def refresh(self,root=None):
        if self.app.busy: return
        if root is not None: self.root_path=Path(root)
        if self.root_path is None: return self.own_folder()
        self.launch("scan",lambda:scan_history(self.root_path,cancel=self.app.cancel))

    def receive(self,kind,value):
        if kind=="scan":
            self.entries=value["entries"]; self.run=None; self.mode="runs"
            self.note="Показаны первые 100 запусков; выберите более точную папку." if value["limited"] else "Сохранённые результаты; повторная QA не выполнялась."
            self.app.status_var.set(f"История: {len(self.entries)} запусков · "+_short(self.root_path.name,50))
        else:
            self.run=value; self.mode="cases"
            data=value["data"]; cpu=_dict(_dict(data.get("hardware")).get("cpu"))
            self.note=f"{_short(cpu.get('name','CPU неизвестен'),35)} · {_short(data.get('os','ОС неизвестна'),16)} · код {_short(data.get('source_digest','?'),8)} · QA сохранённая."
            self.app.status_var.set("Сохранённые замеры; прогрев исключён, повторная QA не запускалась")
        self.render(reset=True)
        self.app.fit_window()

    def rows(self):
        data=self.entries if self.mode=="runs" else self.run["results"]
        result=[]; query=self.search.get().casefold().strip()
        for index,item in enumerate(data):
            status=item.status if self.mode=="runs" else item["status"]
            good=status in ("COMPLETE","PASS")
            if self.filter.get()=="Успешные" and not good: continue
            if self.filter.get()=="С проблемами" and good: continue
            if self.mode=="runs": haystack=f"{item.date} {item.counts} {item.path.parent.name} {status} {_status(status)}"
            else: haystack=str(item["case"].get("count",""))+" "+str(item["case"].get("cpu_choice",""))+" "+status
            if query and query not in haystack.casefold(): continue
            result.append((index,item))
        return result

    def render(self,reset=False):
        if reset: self.page=0
        self.visible=self.rows()
        pages=max(1,math.ceil(len(self.visible)/self.rows_per_page)); self.page=max(0,min(self.page,pages-1))
        self.table.delete(*self.table.get_children())
        headings=("Дата файла","Запуск","Кодов","Статус","","") if self.mode=="runs" else ("Кодов","CPU (факт)","Метод / PDF","Создание, с","С QA, с","Статус")
        widths=(155,220,90,150,0,0) if self.mode=="runs" else (65,110,230,100,100,140)
        for column,title,width in zip(("a","b","c","d","e","f"),headings,widths):
            self.table.heading(column,text=title); self.table.column(column,width=width,minwidth=0,stretch=width>0)
        self.table.configure(displaycolumns=("a","b","c","d") if self.mode=="runs" else ("a","b","c","d","e","f"))
        for index,item in self.visible[self.page*self.rows_per_page:(self.page+1)*self.rows_per_page]:
            if self.mode=="runs":
                status=item.status; values=(item.date,item.path.parent.name,_short(item.counts,24),_status(status),"","")
            else:
                case=item["case"]; summary=item["summary"]; status=item["status"]
                cpus=case.get("cpus",[]); number=len(cpus) if isinstance(cpus,list) else "?"
                cpu=("Ядер: " if case.get("cpu_unit")=="physical" else "Потоков: ")+str(number)
                method={"serial":"Последовательно","process":"Процессы","thread":"Потоки (GIL)"}.get(case.get("backend"),"?")
                profile="компактный" if case.get("pdf_profile")=="compact" else "обычный"
                if case.get("activity")=="minimal": profile+=" / минимум"
                values=(case["count"],cpu,method+" / "+profile,_seconds(summary.get("median_seconds")),
                        _seconds(summary.get("median_with_qa_seconds")),_status(status))
            self.table.insert("", "end",iid=str(index),values=values,tags=("good" if status in ("COMPLETE","PASS") else "bad",))
        self.page_label.set(f"{self.page+1}/{pages}")
        children=self.table.get_children()
        if children: self.table.selection_set(children[0])
        self.selected()

    def current(self):
        selected=self.table.selection()
        if not selected: return None
        index=int(selected[0])
        return self.entries[index] if self.mode=="runs" else self.run["results"][index]

    def selected(self):
        item=self.current(); detail=self.note
        if item is not None:
            detail=(item.note if self.mode=="runs" else item["reason"])+"\n"+self.note
        elif not self.visible: detail="Подходящих запусков нет. Выберите другую папку или измените фильтр.\n"+self.note
        self.details.configure(state="normal"); self.details.delete("1.0","end"); self.details.insert("1.0",detail[:300]); self.details.configure(state="disabled")
        self.update_controls()

    def update_controls(self):
        active=not self.app.busy; item=self.current(); rows=len(self.visible)
        states={"back":self.mode=="cases","cases":self.mode=="runs" and item is not None,
                "previous":self.page>0,"next":(self.page+1)*self.rows_per_page<rows,
                "report":self.target("report") is not None,"pdf":self.target("pdf") is not None,
                "folder":item is not None}
        for name,button in self.buttons.items(): button.configure(state="normal" if active and states[name] else "disabled")

    def target(self,kind):
        item=self.current()
        if item is None: return None
        path=item.path if self.mode=="runs" else self.run["path"]
        try:
            if kind=="folder": return path.resolve(strict=True).parent
            if kind=="report":
                report=artifact_path(path,"comparison.html")
                return report if report.is_file() else None
            if self.mode=="cases": return pdf_for_case(path,item["case"])
        except (OSError,ValueError): return None

    def open(self,kind):
        if self.app.busy: return
        path=self.target(kind)
        if path is None: self.app.status_var.set("Файл не найден или ссылка выходит за пределы выбранного запуска")
        else: self.app.open_path(path)

    def show_cases(self):
        item=self.current()
        if self.mode=="runs" and item is not None:
            self.launch("run",lambda:read_run(item.path,cancel=self.app.cancel))

    def turn(self,amount):
        if not self.app.busy: self.page+=amount; self.render()

    def back(self):
        if not self.app.busy: self.mode="runs"; self.render(reset=True)
