"""Pasteable test commands, dry run, GUI round trip and one owned worker queue."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .test_commands import parse_script,preview_command,command_text,run_script


class ConsoleView:
    def __init__(self,app):
        self.app=app; self.valid=False; self.last_stage=None
        page=app.pages["console"]
        self.plan=tk.StringVar(master=app.root,value="Вставьте команды или перенесите сюда настройки кнопками «В консоль».")
        row=ttk.Frame(page); row.pack(anchor="w",pady=1)
        for text,action in (("Проверить",self.preview),("Показать кнопками",self.apply),("Вставить",self.paste),("Очистить",lambda:self.set_text("")),("Справка команд",self.help)):
            app.edit(ttk.Button(row,text=text,command=action)).pack(side="left",padx=(0,5))
        file_button=app.edit(ttk.Menubutton(row,text="Файл ▾")); file_button.pack(side="left")
        menu=tk.Menu(file_button,tearoff=False); file_button.configure(menu=menu)
        menu.add_command(label="Загрузить команды…",command=self.load_file)
        menu.add_command(label="Сохранить команды…",command=self.save_file)
        self.input=app.edit(tk.Text(page,height=3,width=90,wrap="word",font=("Consolas",8),background="#142033",foreground="#edf4fc",insertbackground="#5ce0bd",undo=True))
        self.input.pack(fill="both",expand=True,pady=2)
        self.input.bind("<<Modified>>",self.modified)
        self.input.bind("<Control-Return>",lambda event:self.start())
        ttk.Label(page,textvariable=self.plan,style="Accent.TLabel",wraplength=900).pack(anchor="w",pady=1)
        self.log=tk.Text(page,height=2,width=90,wrap="word",font=("Segoe UI",8),background="#0b1220",foreground="#a5b7ce",state="disabled",relief="flat")
        self.log.pack(fill="x")
        self.saved=app.preferences_path.with_name("console-commands.txt")
        try: self.set_text(self.saved.read_text(encoding="utf-8"))
        except (OSError,UnicodeError): pass

    def text(self): return self.input.get("1.0","end-1c")
    def modified(self,event=None):
        if self.input.edit_modified():
            self.input.edit_modified(False); self.preview()
    def set_text(self,text):
        if self.app.busy: return
        self.input.delete("1.0","end"); self.input.insert("1.0",text); self.preview()
    def paste(self):
        try: self.set_text(self.app.root.clipboard_get())
        except tk.TclError: self.plan.set("В буфере обмена нет текста")
    def load_file(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.app.root,title="Команды тестов",filetypes=[("Команды TXT","*.txt"),("Все файлы","*.*")])
        if path:
            try:
                source=Path(path)
                if source.stat().st_size>512*1024: raise ValueError("Файл команд больше512 КиБ")
                self.set_text(source.read_text(encoding="utf-8-sig"))
            except (OSError,ValueError) as exc: self.plan.set(str(exc))
    def save_file(self):
        from tkinter import filedialog
        path=filedialog.asksaveasfilename(parent=self.app.root,title="Сохранить команды",defaultextension=".txt",filetypes=[("Команды TXT","*.txt")])
        if path:
            try: Path(path).write_text(self.text()+"\n",encoding="utf-8")
            except OSError as exc: self.plan.set(str(exc))
    def append(self,text):
        self.log.configure(state="normal"); self.log.insert("end",str(text)+"\n")
        if int(self.log.index("end-1c").split(".")[0])>200: self.log.delete("1.0","101.0")
        self.log.see("end"); self.log.configure(state="disabled")
    def observe(self,value):
        stage=value.get("stage")
        if stage!=self.last_stage:
            self.append(f"{stage} · {value.get('done',0)} / {value.get('total',0)}"); self.last_stage=stage
    def preview(self):
        self.valid=False
        try:
            commands=parse_script(self.text()); plans=[preview_command(c,self.app.hardware["cpu"]) for c in commands]
            parts=[]
            for i,p in enumerate(plans,1):
                runs="по допуску" if p["runs"] is None else ("до " if not p["exact"] else "")+str(p["runs"])
                parts.append(f"{i}. {p['kind']}: {runs} запусков"+(f", пропущено {p['skipped']}" if p["skipped"] else ""))
            self.plan.set("Очередь: "+"; ".join(parts))
            self.valid=all(p["variants"] is None or p["variants"]>0 for p in plans)
            if not self.valid: self.plan.set(self.plan.get()+" · нет доступных вариантов")
        except (ValueError,TypeError,KeyError) as exc: self.plan.set(str(exc))
        if hasattr(self.app,"generate"): self.app.update_buttons()
    def apply(self):
        try:
            commands=parse_script(self.text())
            if len(commands)!=1: raise ValueError("Для показа переключателями оставьте одну команду")
            from .test_navigation import apply_to_controls
            apply_to_controls(self.app,commands[0])
        except (ValueError,KeyError) as exc: self.plan.set(str(exc))
    def help(self):
        import html
        source=Path(__file__).resolve().parents[1]/"docs/TEST_COMMANDS.md"
        folder=self.app.output_root/"help"; folder.mkdir(parents=True,exist_ok=True)
        target=folder/"test-commands.html"
        target.write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>uCode — команды тестов</title><style>body{font:16px Segoe UI;margin:24px;max-width:1100px}pre{white-space:pre-wrap;line-height:1.5}</style><pre>'+html.escape(source.read_text(encoding="utf-8"))+'</pre></html>',encoding="utf-8")
        self.app.open_path(target)
    def start(self):
        if self.app.busy: return
        self.preview()
        if not self.valid: return
        text=self.text(); self.last_stage=None; self.append("Запуск очереди. Все параметры проверены.")
        try:
            self.saved.parent.mkdir(parents=True,exist_ok=True); self.saved.write_text(text+"\n",encoding="utf-8")
        except OSError as exc: self.plan.set("Команды не сохранены: "+str(exc)); return
        self.app.begin()
        root=Path(self.app.destination_var.get() or self.app.output_root/"jobs")/"console-tests"
        self.app.launch(lambda:run_script(text,root,cancel=self.app.cancel,events=lambda value:self.app.events.put(("progress",value))))


def copy_current(app):
    try:
        from .test_navigation import from_controls
        selected=app.notebook.select()
        kind=next((kind for kind,key in (("lab","lab"),("pipeline","pipeline"),("search","search"),("scientific","tests")) if selected==str(app.pages[key])),None)
        if kind is None: raise ValueError("Сначала откройте параметры CPU, конвейера, подбора или научного теста")
        app.console_view.set_text(command_text(from_controls(app,kind)))
        app.notebook.select(app.pages["console"])
    except (ValueError,KeyError) as exc: app.status_var.set(str(exc))
