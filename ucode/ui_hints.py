"""Keyboard/hover hints; timers and popup are owned by the originating widget."""
import tkinter as tk
from .ui_theme import COLORS

HINTS = {
    'ОЗУ':'Полезный бюджет памяти с резервом для системы. Заполнять RAM искусственно программа не будет.',
    'RAM':'Полезный бюджет памяти с резервом для системы. Заполнять RAM искусственно программа не будет.',
    'Процессов на ядро':'Сколько процессов делят каждый выбранный CPU. Больше процессов не означает больше ядер.',
    'Кодов за шаг':'Сколько кодов получает процесс за одно задание. Размер порции не обязан быть кратным 2, 3, 5 или 8.',
    'Порция':'Сколько кодов получает процесс за одно задание. Малые порции чаще передаются между процессами.',
    'Прогрев':'Пробные PDF перед замерами. 0 выключает прогрев; пробные запуски не входят в медиану.',
    'Замеры CPU':'Наблюдение собственного дерева процессов. Сравнивайте скорость при одинаковом режиме диагностики.',
    'XY':'Записывает реальный ход работы для графика в отчёте. Это не живой график в главном окне.',
    'Доп. данные':'Объём служебных данных. Проверка PDF выбирается отдельными кнопками у запуска.',
    'PDF':'Обычный или компактный способ записи PDF. Размер страницы и цвет задаются отдельно.',
}


class Hint:
    def __init__(self,widget,text):
        self.widget=widget;self.text=text;self.timer=None;self.popup=None
        for event in ('<Enter>','<FocusIn>'):widget.bind(event,self.schedule,add='+')
        for event in ('<Leave>','<FocusOut>','<ButtonPress>','<Destroy>','<Escape>'):widget.bind(event,self.hide,add='+')

    def schedule(self,event=None):
        self.hide();self.timer=self.widget.after(650,self.show)

    def show(self):
        self.timer=None
        if not self.widget.winfo_exists() or not self.widget.winfo_viewable():return
        self.popup=tk.Toplevel(self.widget);self.popup.withdraw();self.popup.overrideredirect(True)
        tk.Label(self.popup,text=self.text() if callable(self.text) else self.text,wraplength=330,justify='left',padx=9,pady=7,
                 background=COLORS['raised'],foreground=COLORS['text'],font=('Segoe UI',9)).pack()
        self.popup.update_idletasks();w=self.popup.winfo_reqwidth();h=self.popup.winfo_reqheight()
        x=min(self.widget.winfo_rootx(),self.widget.winfo_screenwidth()-w-8)
        y=min(self.widget.winfo_rooty()+self.widget.winfo_height()+5,self.widget.winfo_screenheight()-h-8)
        self.popup.geometry(f'+{max(0,x)}+{max(0,y)}');self.popup.deiconify()

    def hide(self,event=None):
        if self.timer is not None:
            try:self.widget.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
        if self.popup is not None:
            try:self.popup.destroy()
            except tk.TclError:pass
            self.popup=None

