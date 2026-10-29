"""Small native controls for the v0.3 operator shell. No browser dependency."""
import tkinter as tk
from tkinter import ttk


class CycleButton(ttk.Button):
    def __init__(self,app,parent,variable,label,options,*,command=None,caption=None):
        self.app=app;self.variable=variable;self.label=label;self.options=tuple(options)
        self.callback=command;self.caption=caption;self.button=self
        super().__init__(parent,command=self.cycle,takefocus=True)
        app.edit(self)
        self.trace=variable.trace_add('write',self.sync)
        self.sync()
        from .ui_hints import Hint
        self.hint=Hint(self,self.explanation)
        self.bind('<Destroy>',self.destroy_trace,add='+')

    def destroy_trace(self,event):
        if event.widget==self:
            try:self.variable.trace_remove('write',self.trace)
            except tk.TclError:pass

    def explanation(self):
        values=[value for _,value in self.options]
        index=values.index(self.variable.get()) if self.variable.get() in values else -1
        return f'{self.label}. Нажатие: {self.options[(index+1)%len(values)][0]}' if values else self.label

    def sync(self,*_):
        if not self.winfo_exists():return
        names=dict((value,text) for text,value in self.options)
        text=self.caption() if self.caption else names.get(self.variable.get(),self.variable.get())
        self.configure(text=(self.label+': ' if self.label and not self.caption else '')+str(text))

    def set_options(self,options):self.options=tuple(options);self.sync()
    def cycle(self):
        if self.app.busy or not self.options:return
        values=[value for _,value in self.options]
        index=values.index(self.variable.get()) if self.variable.get() in values else -1
        self.variable.set(values[(index+1)%len(values)])
        if self.callback:self.callback()


class PageStack(ttk.Frame):
    """Notebook-compatible routes with independently colored native tab buttons."""
    def __init__(self,app,parent):
        super().__init__(parent);self.app=app;self.routes={};self.buttons={};self.selected_page=''
        self.tests=None;self.test_container=None;self.other=None;self.other_container=None
        self.columnconfigure(0,weight=1);self.rowconfigure(1,weight=1)
        self.navigation=ttk.Frame(self);self.navigation.grid(row=0,column=0,sticky='ew',pady=(0,5))
        self.content=ttk.Frame(self,height=310);self.content.grid(row=1,column=0,sticky='nsew')
        self.content.grid_propagate(False);self.content.columnconfigure(0,weight=1);self.content.rowconfigure(0,weight=1)

    def add(self,page,*,text,accent='#5ce0bd'):
        key=str(page);self.routes[key]={'page':page,'text':text,'accent':accent}
        button=tk.Button(self.navigation,text=text,command=lambda:self.select(page),relief='flat',
                         borderwidth=1,font=('Segoe UI',9),padx=10,pady=3,takefocus=True)
        button.pack(side='left',padx=(0,5));self.buttons[key]=button;self.app.edit(button)
        button.bind('<Enter>',lambda event,k=key:self.hover(k,True))
        button.bind('<Leave>',lambda event,k=key:self.hover(k,False))
        if not self.selected_page:self.select(page)

    def hover(self,key,on):
        route=self.routes[key];palette=getattr(self.app,'palette',{})
        self.buttons[key].configure(background=palette.get('raised','#21344d') if on or key==self.selected_page else palette.get('surface','#131f32'),foreground=route['accent'],activeforeground=route['accent'],activebackground=palette.get('raised','#21344d'))

    def tabs(self):return tuple(self.routes)
    def tab(self,page,option=None,**kwargs):
        key=str(page)
        if kwargs:
            self.routes[key].update(kwargs)
            if 'text' in kwargs:self.buttons[key].configure(text=kwargs['text'])
            if 'state' in kwargs:self.buttons[key].configure(state=kwargs['state'])
        return self.routes[key].get(option) if option else self.routes[key]

    def test_hub(self,container):
        self.test_container=container;self.tests=ttk.Notebook(container,style='Tests.TNotebook')
        self.tests.pack(fill='both',expand=True);self.tests.bind('<<NotebookTabChanged>>',lambda event:self.event_generate('<<NotebookTabChanged>>'),add='+')
        return self.tests

    def other_hub(self,container):
        self.other_container=container;self.other=ttk.Notebook(container,style='Tests.TNotebook')
        self.other.pack(fill='both',expand=True);self.other.bind('<<NotebookTabChanged>>',lambda event:self.event_generate('<<NotebookTabChanged>>'),add='+')
        return self.other

    def select(self,page=None):
        if page is None:
            if self.tests and self.selected_page==str(self.test_container):return self.tests.select()
            if self.other and self.selected_page==str(self.other_container):return self.other.select()
            return self.selected_page
        key=str(page)
        for notebook,container in ((self.tests,self.test_container),(self.other,self.other_container)):
            if notebook and key in notebook.tabs():
                self._show(str(container));notebook.select(page);return
        self._show(key)

    def _show(self,key):
        if key not in self.routes:raise tk.TclError('Unknown operator page '+key)
        if self.app.busy and self.selected_page and key!=self.selected_page:return
        if self.selected_page:self.routes[self.selected_page]['page'].grid_remove()
        self.selected_page=key;self.routes[key]['page'].grid(row=0,column=0,sticky='nsew')
        for name in self.buttons:self.hover(name,False)
        self.event_generate('<<NotebookTabChanged>>')


class LaunchFrame(tk.Canvas):
    def __init__(self,parent,*,background='#0b1220',accent='#5ce0bd'):
        super().__init__(parent,width=88,height=88,highlightthickness=0,background=background)
        self.accent=accent;self.timer=None;self.offset=0
        self.edge=self.create_rectangle(3,3,85,85,outline=accent,width=2,state='hidden',dash=(14,34))
        self.bind('<Destroy>',self.disposed,add='+')
    def running(self,active):
        if self.timer:
            self.after_cancel(self.timer);self.timer=None
        self.itemconfigure(self.edge,state='normal' if active else 'hidden')
        if active:self.animate()
    def animate(self):
        self.offset=(self.offset+3)%48;self.itemconfigure(self.edge,dashoffset=self.offset)
        self.timer=self.after(80,self.animate)
    def disposed(self,event):
        if event.widget==self and self.timer:
            try:self.after_cancel(self.timer)
            except tk.TclError:pass
            self.timer=None
