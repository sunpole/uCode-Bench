"""Compact topic-based help within the existing Tk window."""
import tkinter as tk
from tkinter import ttk
from .help_content import TOPICS, BY_ID, CONTEXT
from .ui_theme import COLORS


class HelpView:
    def __init__(self, app):
        self.app=app; self.topic='start'; self.part=tk.IntVar(master=app.root,value=0)
        page=app.pages['help']; self.caption=tk.StringVar(master=app.root)
        row=ttk.Frame(page); row.pack(fill='x')
        self.picker=ttk.Menubutton(row,textvariable=self.caption)
        self.picker.pack(side='left'); menu=tk.Menu(self.picker,tearoff=False); self.picker.configure(menu=menu)
        for topic in TOPICS:menu.add_command(label=topic['title'],command=lambda key=topic['id']:self.show(key))
        ttk.Button(row,text='Назад',command=lambda:self.move(-1)).pack(side='left',padx=3)
        ttk.Button(row,text='Далее',command=lambda:self.move(1)).pack(side='left')
        self.browser_button=ttk.Button(row,text='Полная справка в браузере',command=self.browser)
        self.browser_button.pack(side='right')
        self.short=tk.StringVar(master=app.root)
        ttk.Label(page,textvariable=self.short,style='Accent.TLabel',wraplength=850).pack(anchor='w')
        row=ttk.Frame(page); row.pack(anchor='w',pady=1)
        for i,label in enumerate(('Как работает','Что выбрать','Важно')):
            ttk.Radiobutton(row,text=label,variable=self.part,value=i,style='Choice.TRadiobutton',command=self.render).pack(side='left',padx=(0,4))
        app.help_text=tk.Text(page,height=4,width=80,wrap='word',borderwidth=0,relief='flat',
                              background=COLORS['background'],foreground=COLORS['text'],font=('Segoe UI',8),takefocus=True)
        app.help_text.pack(fill='x')
        self.canvas=tk.Canvas(page,height=36,width=650,highlightthickness=0,background=COLORS['background'])
        self.canvas.pack(fill='x',expand=True)
        self.canvas.bind('<Configure>',lambda event:self.draw())
        self.jump_button=ttk.Button(page,command=self.jump); self.jump_button.pack(anchor='w')
        app.root.bind('<F1>',self.context,add='+')
        self.show('start')

    def context(self,event=None):
        selected=self.app.notebook.select()
        key=next((k for k,p in self.app.pages.items() if str(p)==selected),'help')
        self.app.show_help(CONTEXT.get(key,self.topic));return 'break'

    def show(self,topic):
        self.topic=topic if topic in BY_ID else 'start'; self.part.set(0);self.render()

    def move(self,delta):
        keys=list(BY_ID); self.show(keys[(keys.index(self.topic)+delta)%len(keys)])

    def render(self):
        topic=BY_ID[self.topic]; self.caption.set('Тема: '+topic['title']+' ▾'); self.short.set(topic['short'])
        self.app.help_text.configure(state='normal');self.app.help_text.delete('1.0','end')
        self.app.help_text.insert('1.0',topic['paragraphs'][self.part.get()]);self.app.help_text.configure(state='disabled')
        self.jump_button.configure(text=topic['action'] or 'Контакты и сведения в браузере')
        self.draw()

    def jump(self):
        page=BY_ID[self.topic]['page']
        if page:self.app.notebook.select(self.app.pages[page]);self.app.update_buttons()
        else:self.browser()

    def browser(self):
        from .help_report import write_help
        try:self.app.open_path(write_help(self.app.output_root,self.app.hardware),anchor=self.topic)
        except (OSError,ValueError) as exc:self.app.status_var.set('Справка: '+str(exc))

    def draw(self):
        c=self.canvas;c.delete('all'); w=max(300,c.winfo_width());kind=BY_ID[self.topic]['diagram']
        if kind=='qr':
            c.create_rectangle(12,1,46,35,fill='white',outline=COLORS['accent'])
            c.create_rectangle(18,7,40,29,fill=COLORS['raised'],outline=COLORS['raised'])
            c.create_text(64,9,text='Белое поле ≥ 4 модуля · модуль = клетка QR',anchor='w',fill=COLORS['accent'],font=('Segoe UI',8))
            c.create_text(64,27,text='(21 + 2 × 4) × 0,5 мм = 14,5 мм · схема областей',anchor='w',fill=COLORS['text'],font=('Segoe UI',8))
            return
        labels={'flow':('База TXT','QR','Страницы PDF','Готовые файлы'),
                'cpu':('Ядра CPU','Процессы QR','Подготовка PDF','Сборка файла'),
                'queue':('Очередь кодов','Порция → процесс','Следующая порция','Сборка PDF'),
                'quality':('Создание PDF','Выбранная QA','Статус качества','Отчёт'),
                'tests':('Количество','Варианты × повторы','Измерения','Сравнение')}[kind]
        step=min(210,(w-12)/4); box=step-18
        for i,label in enumerate(labels):
            x=8+i*step;c.create_rectangle(x,2,x+box,34,fill=COLORS['surface'],outline=COLORS['border'])
            c.create_text(x+box/2,18,text=label,fill=COLORS['text'],font=('Segoe UI',8),width=box-4)
            if i<3:c.create_line(x+box+2,18,x+step-3,18,arrow='last',fill=COLORS['accent'])

