"""Russian button menus; legacy CSV values stay an internal persistence format."""
import tkinter as tk
from tkinter import ttk


class ChoiceMenu:
    def __init__(self,app,parent,variable,label,options,*,multiple=False,command=None,aliases=None):
        self.app=app; self.variable=variable; self.label=label; self.multiple=multiple; self.command=command
        self.aliases=dict(aliases or {})
        self.options=(); self.values={}; self.flags={}
        self.single_value=tk.StringVar(master=app.root)
        self.button=app.edit(ttk.Menubutton(parent))
        self.menu=tk.Menu(self.button,tearoff=False); self.button.configure(menu=self.menu)
        self.set_options(options)
        variable.trace_add("write",lambda *_:self.sync())

    def selected(self):
        raw=self.variable.get().split(",") if self.multiple else [self.variable.get()]
        aliases={**self.aliases,**{text:value for text,value in self.options}}
        return list(dict.fromkeys(aliases.get(part.strip(),part.strip()) for part in raw if part.strip()))

    def set_options(self,options):
        unique={}
        for text,value in options: unique.setdefault(str(value),str(text))
        options=tuple((text,value) for value,text in unique.items())
        if options!=self.options:
            self.options=options
            self.sync()

    def sync(self):
        selected=self.selected(); self.menu.delete(0,"end"); self.flags={}; self.values={}
        self.single_value.set(selected[0] if selected else "")
        options=list(self.options); known={value for _,value in options}
        options.extend(("Недоступно: "+value,value) for value in selected if value not in known)
        for text,value in options:
            index=len(self.values); self.values[value]=index
            if self.multiple:
                flag=tk.BooleanVar(master=self.app.root,value=value in selected); self.flags[value]=flag
                self.menu.add_checkbutton(label=text,variable=flag,command=lambda key=value:self.toggle(key))
            else:
                self.menu.add_radiobutton(label=text,variable=self.single_value,value=value,command=lambda key=value:self.choose(key))
        if self.multiple:
            self.menu.add_separator()
            self.menu.add_command(label="Выбрать все",command=lambda:(self.variable.set(",".join(value for _,value in self.options)),self.changed()))
            self.menu.add_command(label="Снять все",command=lambda:(self.variable.set(""),self.changed()))
        names={value:text for text,value in options}
        caption=names.get(selected[0],"Выбрать") if len(selected)==1 else f"выбрано {len(selected)}" if selected else "выбрать…"
        self.button.configure(text=f"{self.label}: {caption} ▾")

    def toggle(self,value):
        selected=self.selected()
        if value in selected: selected.remove(value)
        else: selected.append(value)
        self.variable.set(",".join(selected)); self.changed()

    def choose(self,value):
        # The menu's own variable changes before Tk invokes its command. Keep
        # it separate so a model trace cannot delete that command prematurely.
        self.variable.set(value); self.changed()

    def changed(self):
        if self.command: self.command()


class NumericChoiceMenu(ChoiceMenu):
    """Compact menu with a custom-number button, no permanent extra field."""
    def __init__(self,*args,minimum=1,maximum=1000,suffix="",**kwargs):
        self.minimum=minimum; self.maximum=maximum; self.suffix=suffix
        super().__init__(*args,**kwargs)
    def sync(self):
        known={v for _,v in self.options}
        for token in self.selected():
            raw=token[:-len(self.suffix)] if self.suffix and token.endswith(self.suffix) else token if not self.suffix else ""
            if raw.isdigit() and self.minimum<=int(raw)<=self.maximum and token not in known:
                self.options+=((token,token),); known.add(token)
        super().sync()
        self.menu.add_separator(); self.menu.add_command(label="Своё число…",command=self.custom)
    def add_value(self,value):
        if type(value) is not int or not self.minimum<=value<=self.maximum: raise ValueError(f"Число: {self.minimum}–{self.maximum}")
        token=str(value)+self.suffix; self.set_options(self.options+((token,token),))
        if self.multiple:
            self.variable.set(",".join(dict.fromkeys(self.selected()+[token]))); self.changed()
        else: self.choose(token)
    def custom(self):
        from tkinter.simpledialog import askinteger
        value=askinteger(self.label,"Укажите своё число"+(", "+self.suffix if self.suffix else ""),parent=self.app.root,minvalue=self.minimum,maxvalue=self.maximum)
        if value is not None: self.add_value(value)


class NumberSet:
    """Add custom numeric values by a button, never by entering CSV syntax."""
    def __init__(self,app,parent,variable,label,*,minimum=1,maximum=10000,default="200",suffix="",factor=1,options=(),menu_parent=None):
        self.variable=variable; self.factor=factor; self.suffix=suffix; self.options=tuple(options)
        self.minimum=minimum; self.maximum=maximum; self.lock=False; self.app=app
        self.input=tk.StringVar(master=app.root,value=default)
        menu_parent=menu_parent or parent
        self.picker=ChoiceMenu(app,menu_parent,variable,label,options,multiple=True)
        self.spin=app.edit(ttk.Spinbox(parent,textvariable=self.input,from_=minimum,to=maximum if maximum is not None else 1e300,width=8,
                                     increment=.25 if factor!=1 else 1))
        self.add_button=app.edit(ttk.Button(menu_parent,text="Добавить",command=self.add))
        variable.trace_add("write",lambda *_:self.sync()); self.sync()

    def sync(self):
        values=[part.strip() for part in self.variable.get().split(",") if part.strip()]
        extra=[]; first=None
        for value in values:
            if self.suffix and not value.endswith(self.suffix): continue
            try: number=float(value[:-len(self.suffix)])/self.factor if self.suffix else int(value.replace(" ",""))
            except ValueError: continue
            text=(f"{number:g} ГиБ" if self.factor!=1 else str(number))
            extra.append((text,value))
            if first is None: first=f"{number:g}" if self.factor!=1 else str(number)
        self.picker.set_options(self.options+tuple(extra))
        if first is not None:
            self.lock=True
            try: self.input.set(first)
            finally: self.lock=False
        if hasattr(self,"after_sync"): self.after_sync()

    def add(self):
        try:
            raw=self.input.get().replace(" ","")
            number=int(raw) if self.factor==1 else float(raw.replace(",","."))
            if number<self.minimum or (self.maximum is not None and number>self.maximum): raise ValueError()
            token=str(number if self.factor==1 else round(number*self.factor))+self.suffix
            values=self.picker.selected()
            if token not in values: values.append(token)
            entered=self.input.get()
            self.variable.set(",".join(values))
            self.lock=True
            try: self.input.set(entered)
            finally: self.lock=False
        except (ValueError,OverflowError):
            self.app.status_var.set(f"Укажите число от {self.minimum:g}"+(f" до {self.maximum:g}" if self.maximum is not None else " (целое)"))
