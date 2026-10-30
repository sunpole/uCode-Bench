"""Working v0.3 native controller; legacy engines and test views stay intact."""
from __future__ import annotations
from dataclasses import asdict
import functools
import hashlib
import json
import math
from pathlib import Path
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, font as tkfont
import uuid
import webbrowser

from .batch_gui import BatchWindow
from .operator_models import SequenceSpec, SourceIndex, JobApproval, estimate_space, grouped_number, parse_number
from .print_settings import PrintSettings
from .app_settings import GenerationPreferences
from .ui_layout import POLICIES,EXECUTION_METHODS,PDF_PROFILES,QA_MODES


class LaboratoryContext:
    """Lab-owned generation settings, with the existing window's worker/events."""
    def __init__(self,owner):
        object.__setattr__(self,'owner',owner)
        root=owner.root;cfg=PrintSettings();saved={}
        try:
            saved=json.loads(owner.preferences_path.with_name('laboratory-print.json').read_text(encoding='utf-8'))
            cfg=PrintSettings(**saved['print'])
        except (OSError,ValueError,TypeError,KeyError):saved={}
        private={'print_settings':cfg,'cyclic_controls':False}
        for name,value in {'qa_mode_var':saved.get('qa','Полная'),'xy_mode_var':saved.get('xy','off'),'mode_var':saved.get('mode','multipage'),'pdf_profile_var':next(k for k,v in PDF_PROFILES.items() if v==cfg.pdf_profile),
                           'geometry_basis':'side','geometry_value':str(cfg.side_mm),'quiet_var':str(cfg.quiet_modules)}.items():
            private[name]=tk.StringVar(master=root,value=value)
        private['ink_vars']=[tk.StringVar(master=root,value=str(v)) for v in cfg.ink]
        private['geometry_summary']=tk.StringVar(master=root)
        object.__setattr__(self,'private',private)

    def __getattr__(self,name):
        if name in self.private:return self.private[name]
        return getattr(self.owner,name)
    def __setattr__(self,name,value):
        if name in self.private:self.private[name]=value
        else:setattr(self.owner,name,value)
    def remember(self):
        from .lab_worker import atomic_json
        atomic_json(self.owner.preferences_path.with_name('laboratory-print.json'),
                    {'print':asdict(self.print_settings),'qa':self.qa_mode_var.get(),'xy':self.xy_mode_var.get(),'mode':self.mode_var.get()})
        return True
    def update_geometry(self):self.geometry_summary.set(f'Тест · {self.print_settings.side_mm:g} мм')
    def apply_print(self,*_):
        try:
            self.print_settings=PrintSettings.from_total_side(parse_number(self.geometry_value.get()),parse_number(self.quiet_var.get(),integer=True),
                tuple(parse_number(v.get()) for v in self.ink_vars),pdf_profile=PDF_PROFILES[self.pdf_profile_var.get()])
            self.update_geometry();self.remember();self.owner.refresh_laboratories()
        except ValueError as exc:self.geometry_summary.set(str(exc))


class OperatorWindow(BatchWindow):
    def __init__(self,root,output_root=None):
        self.ready=False;self.cyclic_controls=True;self.palette={};self.type_canvases=[]
        self.source_index=None;self.current_row=1;self.table_start=1;self.approval=JobApproval();self.path_estimate=None
        self.path_order=None;self.history_pages=[];self.previous_page=None;self.operation_kind=None
        self._preview_after=None;self._search_after=None;self.search_cancel=threading.Event();self.search_thread=None
        self.operation_host=None;self.stop_dialog=None;self._stop_after=None;self.close_after_stop=False
        self._formatting=False;self._loading_source=None;self.ui_file=None
        self.template_start_var=tk.StringVar(master=root,value='200000000000');self.template_step_var=tk.StringVar(master=root,value='1')
        self.template_preview_var=tk.StringVar(master=root);self.path_status_var=tk.StringVar(master=root,value='Выберите базу и проверьте папку.')
        self.background_mode_var=tk.StringVar(master=root,value='white');self.background_vars=[tk.StringVar(master=root,value='0') for _ in range(4)]
        self.color_note_var=tk.StringVar(master=root);self.row_var=tk.StringVar(master=root,value='1');self.row_total_var=tk.StringVar(master=root,value='/ —')
        self.search_var=tk.StringVar(master=root);self.source_position_var=tk.StringVar(master=root,value='База не загружена')
        self.row_font_var=tk.DoubleVar(master=root,value=12);self.row_font_text=tk.StringVar(master=root,value='12 px')
        self.theme_var=tk.StringVar(master=root,value='dark');self.select_text_var=tk.BooleanVar(master=root,value=False)
        self.telemetry_var=tk.StringVar(master=root,value='cpu');self.stats_visible=True
        self.qa_enabled_var=tk.StringVar(master=root,value='off');self.qa_depth_var=tk.StringVar(master=root,value='Полная')
        from .operator_layout import build_operator
        super().__init__(root,output_root,layout_builder=build_operator)
        self.ui_file=self.preferences_path.with_name('operator-ui.json')
        self.background_mode_var.set(self.print_settings.background_mode)
        for var,value in zip(self.background_vars,self.print_settings.background_ink):var.set(str(value))
        try:
            ui=json.loads(self.ui_file.read_text(encoding='utf-8'))
            self.theme_var.set(ui.get('theme','dark'));self.row_font_var.set(ui.get('row_font',12));self.telemetry_var.set(ui.get('telemetry','cpu'))
            self.select_text_var.set(bool(ui.get('select_text',False)));self.stats_visible=bool(ui.get('statistics_open',True))
        except (OSError,ValueError,TypeError):pass
        if not self.preferences_path.exists():
            self.qa_mode_var.set('Отложена');self.pdf_profile_var.set('Компактный');self.activity_var.set('minimal');self.xy_mode_var.set('on')
            self.generation_cpu.unit.set('physical' if self.hardware['cpu'].get('available_physical') else 'logical')
            self.generation_cpu.choice.set('all');self.generation_cpu.ram.set('max');self.generation_cpu.select(save=False)
        for var in (self.template_start_var,self.template_step_var,self.custom_count_var):var.trace_add('write',self.sequence_preview)
        for var in (*self.background_vars,self.background_mode_var):var.trace_add('write',self.preview_print)
        for var in (self.input_var,self.destination_var,self.mode_var,self.telemetry_var,self.xy_mode_var):var.trace_add('write',self.order_changed)
        self.row_var.trace_add('write',self.row_edited);self.search_var.trace_add('write',self.schedule_search)
        self.lab_context.qa_mode_var.trace_add('write',lambda *_:self.refresh_laboratories())
        self.bind_numeric_entries();self.ready=True
        self.install_interaction_guard()
        self.apply_theme();self.verification_changed();self.preview_print();self.sequence_preview();self.density_changed();self.draw_type_examples()
        if not self.stats_visible:self.statistics_frame.pack_forget()
        self.root.bind('<Escape>',self.escape,add='+');self.root.bind('<Alt-F4>',lambda event:(self.close(),'break')[1])
        self.root.bind_all('<KeyPress>',self.busy_key,add='+');self.root.bind_all('<Button-1>',self.dismiss_popups,add='+')
        self.notebook.select(self.pages['source']);self.page_changed();self.remember()

    def read_generation_options(self):
        number=lambda variable:parse_number(variable.get(),integer=True)
        control=getattr(self,'generation_cpu',None)
        return GenerationPreferences(number(self.copies_var),POLICIES.get(self.duplicates_var.get(),''),number(self.custom_count_var),
            self.destination_var.get(),EXECUTION_METHODS.get(self.backend_var.get(),''),number(self.workers_var),number(self.batch_size_var),
            QA_MODES.get(self.qa_mode_var.get(),''),self.activity_var.get(),control.choice.get() if control else 'legacy',
            control.unit.get() if control else 'physical',control.ram.get() if control else 'auto',self.xy_mode_var.get())

    def verification_changed(self,*args):
        if self.ready:
            self.qa_enabled_var.set('off' if self.qa_mode_var.get()=='Отложена' else 'on')
            if self.qa_mode_var.get()!='Отложена':self.qa_depth_var.set(self.qa_mode_var.get())
        super().verification_changed(*args)

    def apply_qa_choice(self):
        self.qa_mode_var.set('Отложена' if self.qa_enabled_var.get()=='off' else self.qa_depth_var.get())
        self.remember();self.apply_accent()

    def fit_window(self):
        width=min(1160,self.root.winfo_screenwidth()-40);height=min(700,self.root.winfo_screenheight()-90)
        self.root.minsize(min(960,width),min(540,height));self.root.geometry(f'{width}x{height}')

    def remember(self):
        result=super().remember()
        if self.ready:self.save_operator_preferences()
        return result

    def save_operator_preferences(self):
        if not self.ready or not self.ui_file:return
        from .lab_worker import atomic_json
        try:atomic_json(self.ui_file,{'theme':self.theme_var.get(),'row_font':round(self.row_font_var.get()),'telemetry':self.telemetry_var.get(),
                                     'statistics_open':self.stats_visible,'select_text':self.select_text_var.get()})
        except OSError as exc:self.status_var.set('Настройки интерфейса не сохранены: '+str(exc))

    def bind_numeric_entries(self):
        for widget,variable in self.number_entries:
            def format_field(event=None,w=widget,v=variable):
                if self._formatting or self.busy:return
                raw=v.get();formatted=grouped_number(raw)
                if raw==formatted:return
                self._formatting=True
                try:
                    position=w.index('insert');digits=len(''.join(raw[:position].split()))
                    v.set(formatted);cursor=0;seen=0
                    while cursor<len(formatted) and seen<digits:
                        if not formatted[cursor].isspace():seen+=1
                        cursor+=1
                    w.icursor(cursor)
                finally:self._formatting=False
            widget.bind('<KeyRelease>',format_field,add='+')

    def preview_print(self,*_):
        if not self.ready:return super().preview_print()
        try:
            value=parse_number(self.geometry_value.get());quiet=parse_number(self.quiet_var.get(),integer=True)
            ink=tuple(parse_number(v.get()) for v in self.ink_vars);background=tuple(parse_number(v.get()) for v in self.background_vars)
            kw={'pdf_profile':PDF_PROFILES[self.pdf_profile_var.get()],'background_mode':self.background_mode_var.get(),'background_ink':background}
            cfg=PrintSettings(value,quiet,ink,**kw) if self.geometry_basis.get()=='module' else PrintSettings.from_total_side(value,quiet,ink,**kw)
            self.print_settings=cfg;self.print_valid=True
            self.print_preview.set(f'PDF {cfg.side_mm:.3f} × {cfg.side_mm:.3f} мм · модуль {cfg.module_mm:.3f} мм · поле {cfg.quiet_modules} модулей')
            notes=[]
            if sum(v>0 for v in ink)>1:notes.append('Несколько красок: размер PDF может увеличиться.')
            if cfg.background_mode!='white':notes.append('Фон и инверсию нужно проверить декодированием; прозрачность проверяется на белой подложке просмотрщика.')
            self.color_note_var.set(' '.join(notes));self.update_geometry();self.order_changed();self.schedule_preview()
            return cfg
        except (ValueError,KeyError) as exc:
            self.print_valid=False;self.print_preview.set(str(exc));self.order_changed();return None

    def refresh_plan(self,*args):
        super().refresh_plan(*args)
        if self.ready:self.order_changed()

    def order_payload(self):
        options=self.read_generation_options()
        return {'source':self.source_index.sha256 if self.source_index else None,'source_path':self.input_var.get(),'count':len(self.source_index) if self.source_index else 0,
                'print':asdict(self.print_settings),'generation':asdict(options),'mode':self.mode_var.get(),'telemetry':self.telemetry_var.get()}

    def order_changed(self,*_):
        if not self.ready:return
        try:valid=self.approval.signature==JobApproval.key(self.order_payload()) and self.source_index and self.source_index.unchanged()
        except ValueError:valid=False
        if not valid:
            self.approval.invalidate();self.path_status_var.set('Проверка места не выполнена или устарела. Перейдите в «Путь».')
        self.update_buttons()

    def update_buttons(self):
        if not self.ready or not hasattr(self,'test_controls'):return
        super().update_buttons()
        selected=self.notebook.select();production=selected==str(self.pages['generation'])
        if selected==str(self.pages['tests']):self.generate.configure(state='disabled' if self.busy else 'normal',command=lambda:self.start_test('all' if self.scientific_size.get()=='all' else int(self.scientific_size.get())))
        if selected==str(self.pages['lab']):self.generate.configure(text='Запустить тесты',command=self.test_controls.start)
        if production:
            self.generate.configure(text='Создание\nPDF…' if self.busy else 'Создать\nPDF',command=self.start,
                state='disabled' if self.busy or not self.input_valid or not getattr(self,'print_valid',True) else 'normal',
                style='Primary.TButton' if self.approval.signature else 'Pending.Operator.TButton')
        self.test_run.configure(text=self.generate.cget('text').replace('\n',' '),state=self.generate.cget('state'))
        if selected==str(self.pages['lab_print']):self.test_run.configure(text='Выберите вид теста',state='disabled')
        self.launch_frame.running(self.busy);self.stop.pack(side='left',fill='y',padx=7) if self.busy else self.stop.pack_forget()
        if self.busy:self.stop.configure(state='normal')
        if str(self.pages['testing'])==self.notebook.selected_page and self.qa_mode_var.get()=='Отложена':
            self.test_run.configure(text='Запустить тест · '+self.lab_context.qa_mode_var.get())
        from . import __version__
        self.root.title('uCode '+__version__+' · '+{'Полная':'С ПРОВЕРКОЙ','Отложена':'БЕЗ ПРОВЕРКИ','Без растра':'СТРУКТУРА PDF'}.get(self.qa_mode_var.get(),''))
        self.mode_picker.sync();self.apply_accent()

    def page_changed(self):
        if not self.ready:return
        selected=self.notebook.select()
        if selected!=self.previous_page:
            if self.previous_page:self.history_pages.append(self.previous_page)
            self.previous_page=selected
        if selected==str(self.pages['generation']):self.command_band.grid();self.populate_rows();self.schedule_preview()
        else:self.command_band.grid_remove()
        self.update_buttons();self.apply_accent()

    def go_back(self):
        if self.busy:return
        if self.history_pages:self.notebook.select(self.history_pages.pop())
        else:self.notebook.select(self.pages['generation'])

    def show_contacts(self):self.notebook.select(self.pages['contacts'])
    def open_url(self,url):
        if not self.busy:webbrowser.open(url)
    def open_legacy(self):
        if not self.busy:
            from .gui import Application
            Application(tk.Toplevel(self.root),self.output_root)

    def refresh_laboratories(self):
        for name in ('lab_refresh',):
            if hasattr(self,name):getattr(self,name)()
        for name in ('pipeline_view','search_view','console_view'):
            view=getattr(self,name,None)
            if view:(getattr(view,'refresh',None) or view.preview)()

    def start_test(self,count):
        if self.busy:return
        self.operation_kind='test';self.begin();self.status_var.set('Научный профиль: проверка ресурсов и допуска…')
        def task():
            from .scientific import run_scientific
            return run_scientific(self.output_root/'benchmarks',count,cancel=self.cancel,events=lambda e:self.events.put(('progress',e)),
                                 progress=lambda s:self.events.put(('status',s)),methods=self.selected_engines)
        self.launch(task)

    def output_caption(self):
        total=self.current_plan.total_codes if self.current_plan else None
        return 'ОДИН PDF' if self.mode_var.get()=='multipage' else 'ОБА ВАРИАНТА' if self.mode_var.get()=='both' else f'{total:,} PDF'.replace(',',' ') if total else 'Отдельные PDF'

    def sequence_spec(self):
        return SequenceSpec(self.template_start_var.get(),parse_number(self.custom_count_var.get(),integer=True),parse_number(self.template_step_var.get(),integer=True))
    def sequence_preview(self,*_):
        try:
            spec=self.sequence_spec();self.template_preview_var.set(f'Первый: {spec.first}\nВторой: {spec.value(2) if spec.count>1 else "—"}\nПоследний: {spec.last}')
        except ValueError as exc:self.template_preview_var.set(str(exc))

    def _background(self,kind,action):
        if self.busy:return
        self.operation_kind=kind;self.begin()
        def work():
            try:self.events.put((kind+'_ready',action()))
            except Exception as exc:self.events.put(('error',f'{type(exc).__name__}: {exc}'))
        self.worker=threading.Thread(target=work,name='ucode-'+kind,daemon=False);self.worker.start()

    def use_sequence(self):
        try:
            spec=self.sequence_spec();folder=self.output_root/'templates'/('sequence-'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
            path=folder/f'codes-{spec.count}.txt'
            self._background('sequence',lambda:spec.save(path,cancel=self.cancel))
        except (ValueError,OSError) as exc:self.status_var.set(str(exc))

    def save_sequence(self):
        try:
            spec=self.sequence_spec()
            path=filedialog.asksaveasfilename(parent=self.root,title='Сохранить TXT',defaultextension='.txt',filetypes=[('TXT UTF-8','*.txt')],initialfile=f'codes-{spec.count}.txt')
            if path:self._background('sequence_save',lambda:spec.save(Path(path),cancel=self.cancel))
        except (ValueError,OSError) as exc:self.status_var.set(str(exc))

    def template_custom(self):self.use_sequence()
    def choose(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.root,title='Открыть базу кодов',filetypes=[('TXT UTF-8','*.txt'),('Все файлы','*.*')])
        if path:self.load_source(Path(path))

    def load_source(self,path):
        if self.busy:return
        self.input_valid=False;self.approval.invalidate();self.input_var.set(str(path));self.filename.set(Path(path).name)
        self.status_var.set('Чтение и проверка базы…');self._loading_source=Path(path)
        self._background('source',lambda:SourceIndex.build(path,self.preferences_path.parent/'source-indexes',cancel=self.cancel,
                        progress=lambda count,_:self.events.put(('status',f'Загрузка TXT · проверено {count:,} строк'.replace(',',' ')))))

    def inspect_input(self):
        # Programmatic compatibility. The visible chooser uses load_source's worker.
        if self.source_index and Path(self.input_var.get()).resolve()==self.source_index.source and self.source_index.unchanged():return self.source_index
        try:
            index=SourceIndex.build(self.input_var.get(),self.preferences_path.parent/'source-indexes',cancel=self.cancel)
            self.accept_source(index);return index
        except (OSError,ValueError) as exc:
            self.input_valid=False;self.file_count.set('Ошибка TXT: '+str(exc));self.update_buttons();return None

    def accept_source(self,index):
        self.source_index=index;self.source_values=index;self.input_var.set(str(index.source));self.input_valid=True;self.current_row=1;self.table_start=1
        self.filename.set(index.source.name);self.file_count.set(f'Проверка пройдена · {index.count:,} кодов · Первый: {index.first} · Последний: {index.last}'.replace(',',' '))
        self.row_total_var.set('/ '+grouped_number(index.count));self.row_var.set('1');self.refresh_plan();self.populate_rows();self.schedule_preview()
        self.notebook.select(self.pages['generation']);self.status_var.set('База загружена. Настройте заказ и проверьте «Путь».')

    def goto_row(self,number):
        if self.busy or not self.source_index:return
        number=max(1,min(len(self.source_index),int(number)));self.current_row=number
        if parse_number(self.row_var.get() or '0',integer=True)!=number:self.row_var.set(grouped_number(number))
        if not self.table_start<=number<self.table_start+60:self.table_start=max(1,number-5);self.populate_rows()
        key=str(number)
        if self.source_table.exists(key):self.source_table.selection_set(key);self.source_table.see(key)
        self.schedule_preview()

    def row_edited(self,*_):
        if not self.ready or self.busy:return
        try:
            number=parse_number(self.row_var.get(),integer=True)
            if self.source_index and 1<=number<=len(self.source_index) and number!=self.current_row:self.goto_row(number)
        except ValueError:pass

    def populate_rows(self):
        if not self.ready or not self.source_index:return
        items=self.source_table.get_children()
        if items:self.source_table.delete(*items)
        rows=self.source_index.rows(self.table_start,60)
        for number,value in rows:self.source_table.insert('','end',iid=str(number),values=(grouped_number(number),value))
        if self.source_table.exists(str(self.current_row)):self.source_table.selection_set(str(self.current_row));self.source_table.see(str(self.current_row))
        self.source_scrollbar.set((self.table_start-1)/len(self.source_index),min(1,(self.table_start+len(rows)-1)/len(self.source_index)))
        self.source_position_var.set(f'Строки {grouped_number(self.table_start)}–{grouped_number(self.table_start+len(rows)-1)} из {grouped_number(len(self.source_index))} · UTF-8 · 12 цифр')

    def source_selected(self,event=None):
        if self.busy:return
        selected=self.source_table.selection()
        if selected:
            number=int(selected[0])
            if number!=self.current_row:self.current_row=number;self.row_var.set(grouped_number(number));self.schedule_preview()

    def scroll_source(self,kind,value,*rest):
        if self.busy or not self.source_index:return
        if kind=='moveto':start=1+round(float(value)*(len(self.source_index)-1))
        else:start=self.table_start+int(value)*(30 if rest and rest[0]=='pages' else 3)
        self.table_start=max(1,min(len(self.source_index),start));self.populate_rows()
    def source_wheel(self,event):
        self.scroll_source('scroll',str(-3 if event.delta>0 else 3),'units');return 'break'

    @staticmethod
    @functools.lru_cache(maxsize=32)
    def encoded_frame(value):
        from .engines import get_engine
        return get_engine().encode([value])[0]

    def schedule_preview(self):
        if not self.ready:return
        if self._preview_after:self.root.after_cancel(self._preview_after)
        self._preview_after=self.root.after(45,self.paint_preview)

    @staticmethod
    def rgb(ink):
        c,m,y,k=(v/100 for v in ink)
        return '#'+''.join(f'{round(255*(1-v)*(1-k)):02x}' for v in (c,m,y))

    def paint_preview(self):
        self._preview_after=None
        if not self.ready or not hasattr(self,'preview_canvas'):return
        canvas=self.preview_canvas;canvas.delete('all');canvas.configure(background=self.palette.get('background','#0b1220'))
        if not self.source_index:
            canvas.create_text(max(140,canvas.winfo_width()/2),80,text='Откройте или создайте базу',fill=self.palette.get('muted','#a5b7ce'));return
        try:frame=self.encoded_frame(self.source_index.row(self.current_row))
        except (ValueError,OSError,IndexError) as exc:self.status_var.set(str(exc));return
        cfg=self.print_settings;cells=21+2*cfg.quiet_modules
        size=max(90,min(220,canvas.winfo_width()-40,canvas.winfo_height()-60));unit=size/cells
        x=(canvas.winfo_width()-size)/2;y=max(15,(canvas.winfo_height()-size-35)/2)
        canvas.create_rectangle(x-10,y-10,x+size+10,y+size+10,outline=self.palette.get('border','#31445e'))
        paper=self.rgb(cfg.background_ink) if cfg.background_mode=='color' else 'white'
        if cfg.background_mode=='transparent':
            for row in range(math.ceil(size/12)):
                for col in range(math.ceil(size/12)):
                    canvas.create_rectangle(x+col*12,y+row*12,min(x+size,x+(col+1)*12),min(y+size,y+(row+1)*12),fill='#dddddd' if (row+col)%2 else '#aaaaaa',outline='')
        else:canvas.create_rectangle(x,y,x+size,y+size,fill=paper,outline='')
        color=self.rgb(cfg.ink)
        for row,values in enumerate(frame.matrix):
            for col,on in enumerate(values):
                if on:canvas.create_rectangle(x+(cfg.quiet_modules+col)*unit,y+(cfg.quiet_modules+row)*unit,x+(cfg.quiet_modules+col+1)*unit,y+(cfg.quiet_modules+row+1)*unit,fill=color,outline='')
        text=f'{cfg.side_mm:.2f} × {cfg.side_mm:.2f} мм · поле {cfg.quiet_modules}\n{frame.payload}'
        canvas.create_text(canvas.winfo_width()/2,y+size+25,text=text,fill=self.palette.get('muted','#a5b7ce'),font=('Segoe UI',8))

    def draw_type_examples(self):
        import xml.etree.ElementTree as ET
        from reportlab.graphics.barcode import createBarcodeDrawing
        for canvas,key in self.type_canvases:
            canvas.delete('all')
            if key=='qr':
                frame=self.encoded_frame('200000000001');unit=3
                for row,values in enumerate(frame.matrix):
                    for col,on in enumerate(values):
                        if on:canvas.create_rectangle(35+col*unit,12+row*unit,35+(col+1)*unit,12+(row+1)*unit,fill='black',outline='')
                continue
            name={'code128':'Code128','ean13':'EAN13','datamatrix':'ECC200DataMatrix'}[key]
            drawing=createBarcodeDrawing(name,value='590123412345' if key=='ean13' else 'ABC123456')
            svg=ET.fromstring(drawing.asString('svg'));rectangles=[]
            for rect in svg.iter('{http://www.w3.org/2000/svg}rect'):
                if rect.get('fill') in ('white','#ffffff'):continue
                rectangles.append(tuple(float(rect.get(field,'0')) for field in ('x','y','width','height')))
            if not rectangles:continue
            x0=min(v[0] for v in rectangles);y0=min(v[1] for v in rectangles);w=max(v[0]+v[2] for v in rectangles)-x0;h=max(v[1]+v[3] for v in rectangles)-y0
            scale=min(130/max(1,w),75/max(1,h))
            for x,y,rw,rh in rectangles:canvas.create_rectangle(10+(x-x0)*scale,8+(y-y0)*scale,10+(x+rw-x0)*scale,8+(y+rh-y0)*scale,fill='black',outline='')

    def density_changed(self,*_):
        if not self.ready:return
        size=max(8,min(32,round(self.row_font_var.get())));self.row_font_text.set(f'{size} px')
        self.source_font=tkfont.Font(root=self.root,family='Consolas',size=-size)
        self.style.configure('Source.Treeview',font=self.source_font,rowheight=size+6)
        self.source_table.column('row',width=max(55,self.source_font.measure(grouped_number(len(self.source_index) if self.source_index else 1000000))+20))
        self.save_operator_preferences()

    def schedule_search(self,*_):
        if not self.ready or self.busy:return
        self.search_cancel.set();self.search_cancel=threading.Event()
        if self._search_after:self.root.after_cancel(self._search_after)
        self._search_after=self.root.after(160,self.search_now)

    def search_now(self):
        self._search_after=None;query=self.search_var.get();index=self.source_index;cancel=self.search_cancel
        if not query or not index:self.hide_search();return
        def work():
            try:
                rows=index.find(query,cancel=cancel)
                if not cancel.is_set():self.events.put(('search_ready',(query,rows)))
            except (OSError,ValueError) as exc:self.events.put(('status','Поиск: '+str(exc)))
        self.search_thread=threading.Thread(target=work,name='ucode-source-search',daemon=True);self.search_thread.start()

    def show_search(self,query,rows):
        if query!=self.search_var.get() or self.busy:return
        self.hide_search();popup=tk.Toplevel(self.root);self.search_popup=popup;popup.overrideredirect(True);popup.configure(background=self.palette['surface'])
        popup.geometry(f'+{self.search_entry.winfo_rootx()}+{self.search_entry.winfo_rooty()-max(30,len(rows)*28)}')
        if not rows:ttk.Label(popup,text='Совпадений нет').pack(padx=8,pady=4)
        for number,value in rows:
            ttk.Button(popup,text=f'{value} · строка {grouped_number(number)}',command=lambda n=number:(self.goto_row(n),self.hide_search())).pack(fill='x')

    def hide_search(self):
        if self.search_popup:
            try:self.search_popup.destroy()
            except tk.TclError:pass
            self.search_popup=None

    def dismiss_popups(self,event):
        if self.search_popup and event.widget.winfo_toplevel()!=self.search_popup and event.widget!=self.search_entry:self.hide_search()

    def choose_destination(self):
        if self.busy:return
        path=filedialog.askdirectory(parent=self.root,title='Папка готовых PDF',initialdir=self.destination_var.get() or str(self.output_root))
        if path:self.destination_var.set(path);self.remember()

    def check_destination(self):
        if self.busy:return
        if not self.source_index:self.status_var.set('Сначала загрузите базу');self.notebook.select(self.pages['source']);return
        if self.preview_print() is None:return
        try:options=self.read_generation_options();payload=self.order_payload();cfg=self.print_settings;plan=self.current_plan
        except ValueError as exc:self.status_var.set(str(exc));return
        if not plan:self.status_var.set('Исправьте параметры тиража');return
        path=Path(options.output_directory).resolve();index=self.source_index;mode=self.mode_var.get()
        self.status_var.set('Проверка папки и калибровка настоящих PDF…')
        def calibrate():
            from .hardware import probe_directory
            from .engines import get_engine
            if not index.verify_content():raise ValueError('TXT изменился; загрузите его заново')
            path.mkdir(parents=True,exist_ok=True);probe=probe_directory(path)
            unit=4096
            if hasattr(__import__('os'),'statvfs'):
                import os
                unit=os.statvfs(path).f_frsize or 4096
            else:
                import ctypes
                volume=ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetVolumePathNameW(str(path),volume,len(volume)):
                    values=[ctypes.c_ulong() for _ in range(4)]
                    if ctypes.windll.kernel32.GetDiskFreeSpaceW(volume.value,*[ctypes.byref(v) for v in values]):unit=values[0].value*values[1].value
            engine=get_engine();samples=[index.row(n) for n in sorted({1,max(1,index.count//2),index.count})]
            frames=engine.encode(samples);maximum=0
            cache=self.preferences_path.parent/'calibration';cache.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='measure-',dir=cache) as temp:
                for n,frame in enumerate(frames):
                    if self.cancel.is_set():raise InterruptedError('Проверка папки остановлена')
                    target=Path(temp)/f'{n}.pdf';engine.write_pdf([frame],target,cfg,cancel=self.cancel);maximum=max(maximum,target.stat().st_size)
            free=shutil.disk_usage(path).free
            estimate=estimate_space(plan.total_codes,mode,maximum,free,temp_bytes=plan.unique_values*4096,allocation_unit=unit)
            return payload,path,estimate,maximum,probe
        self._background('preflight',calibrate)

    def poll(self):
        pending=[]
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='search_ready':self.show_search(*value)
                elif kind in ('source_ready','sequence_ready','sequence_save_ready','preflight_ready'):
                    self.busy=False;self.started=None
                    if self.stop_dialog:self.dismiss_stop()
                    if kind=='source_ready':self.accept_source(value)
                    elif kind=='sequence_ready':self.load_source(value)
                    elif kind=='sequence_save_ready':self.status_var.set('TXT сохранён: '+str(value))
                    else:
                        payload,path,estimate,maximum,probe=value;self.path_estimate=estimate
                        text=f'Свободно: {estimate.free_bytes/1024**3:.2f} ГиБ · PDF ≈ {estimate.pdf_bytes/1024**2:.1f} МиБ\nНужно с запасом: {estimate.required_bytes/1024**3:.2f} ГиБ · резерв: {estimate.reserve_bytes/1024**3:.2f} ГиБ\nПроверка записи: {probe["bytes"]} байт, flush + fsync. Калибровка: до трёх настоящих страниц.'
                        self.path_status_var.set(text)
                        if estimate.enough and payload==self.order_payload():
                            self.approval.approve(payload,path,estimate.required_bytes);self.status_var.set('Папка проверена для текущего заказа. Можно создавать PDF.')
                        else:self.approval.invalidate();self.status_var.set('Недостаточно места или параметры изменились. Запуск запрещён.')
                    self.update_buttons()
                else:pending.append((kind,value))
        except queue.Empty:pass
        for event in pending:self.events.put(event)
        super().poll()

    def apply_theme(self):
        from .ui_theme import COLORS,apply_dark_theme
        dark=self.theme_var.get()!='light'
        self.palette={'background':'#0b1220','surface':'#131f32','raised':'#21344d','border':'#31445e','text':'#edf4fc','muted':'#a5b7ce','accent':'#5ce0bd','accent_text':'#08271e','danger':'#f28a8a'} if dark else {
            'background':'#f7f9fc','surface':'#ffffff','raised':'#e4edf5','border':'#c5d1de','text':'#182c40','muted':'#506379','accent':'#146957','accent_text':'#ffffff','danger':'#b42332'}
        COLORS.update(self.palette);self.style=apply_dark_theme(self.root);p=self.palette
        self.style.configure('Operator.Muted.TLabel',font=('Segoe UI',8),foreground=p['muted'])
        self.style.configure('Operator.Title.TLabel',font=('Segoe UI',10,'bold'))
        self.style.configure('Flat.Operator.TButton',background=p['background'],foreground=p['muted'],borderwidth=0,padding=(5,1))
        self.style.map('Flat.Operator.TButton',background=[('active',p['background'])],foreground=[('active',p['text'])])
        self.style.configure('Force.Operator.TButton',background='#b42332',foreground='white',padding=(10,10),font=('Segoe UI',10,'bold'))
        self.style.map('Force.Operator.TButton',background=[('active','#8e1722'),('!disabled','#b42332')],foreground=[('!disabled','white')])
        self.style.configure('Pending.Operator.TButton',background=p['raised'],foreground=p['muted'],font=('Segoe UI',10,'bold'),padding=(8,5))
        self.style.configure('Compact.Operator.TButton',font=('Segoe UI',8),padding=(3,0))
        self.style.configure('Source.Treeview',background=p['surface'],fieldbackground=p['surface'],foreground=p['text'])
        self.style.configure('Source.Treeview.Heading',font=('Segoe UI',8),background=p['surface'],foreground=p['muted'])
        self.style.map('Source.Treeview',background=[('selected',p['raised'])],foreground=[('selected',p['text'])])
        light={'type':'#7341a5','source':'#12677b','path':'#28637a','print':'#365fc0','resources':'#795021','generation':'#146957','testing':'#7341a5','other':'#28637a'}
        from .operator_layout import ACCENTS
        for key,route in self.notebook.routes.items():
            name=next((name for name,widget in self.pages.items() if str(widget)==key),'generation')
            route['accent']=(ACCENTS if dark else light).get(name,p['accent']);self.notebook.hover(key,False)
        self.launch_frame.configure(background=p['background']);self.launch_frame.itemconfigure(self.launch_frame.edge,outline=p['accent'])
        self.apply_accent();self.density_changed();self.schedule_preview();self.save_operator_preferences()

    def apply_accent(self):
        if not self.ready:return
        route=self.notebook.routes.get(self.notebook.selected_page,{})
        accent=route.get('accent',self.palette.get('accent','#5ce0bd'));p=self.palette
        self.style.map('TButton',background=[('disabled',p['surface']),('active',p['raised'])],foreground=[('disabled',p['muted']),('active',accent),('!disabled',p['text'])],bordercolor=[('active',accent)])
        self.style.map('TMenubutton',background=[('active',p['raised'])],foreground=[('active',accent)])
        self.style.map('Primary.TButton',background=[('disabled',p['raised']),('active',accent)],foreground=[('disabled',p['muted']),('active','#ffffff' if self.theme_var.get()=='light' else '#102030')])
        self.style.map('Pending.Operator.TButton',background=[('active',p['raised'])],foreground=[('active',accent)])
        self.style.configure('Operator.Title.TLabel',foreground=accent)
        self.style.map('TEntry',bordercolor=[('focus',accent)]);self.style.map('TSpinbox',bordercolor=[('focus',accent)])
        self.style.map('Tests.TNotebook.Tab',foreground=[('selected',accent)])
        self.style.configure('Enabled.Operator.TButton',background=p['raised'],foreground=accent,bordercolor=accent,borderwidth=2)
        self.style.map('Enabled.Operator.TButton',background=[('active',p['raised'])],foreground=[('active',accent)])
        self.qa_picker.configure(style='Enabled.Operator.TButton' if self.qa_enabled_var.get()=='on' else 'TButton')

    def toggle_statistics(self):
        if self.busy:return
        self.stats_visible=not self.stats_visible
        if self.stats_visible:self.statistics_frame.pack(fill='x',before=self.footer.winfo_children()[-1])
        else:self.statistics_frame.pack_forget()
        self.statistics_toggle.configure(text='Статистика ▴' if self.stats_visible else 'Статистика ▾');self.save_operator_preferences()

    def show_operator_menu(self):
        if self.busy:return
        p=self.palette;menu=tk.Menu(self.root,tearoff=False,background=p['surface'],foreground=p['text'],activebackground=p['raised'])
        menu.add_command(label='Создать TXT…',command=lambda:self.notebook.select(self.pages['source']))
        menu.add_command(label='Тесты',command=self.show_lab);menu.add_command(label='Результаты',command=self.show_history)
        menu.add_checkbutton(label='ВЫДЕЛЯТЬ текст',variable=self.select_text_var,command=self.save_operator_preferences)
        menu.add_command(label='Тема: '+('Тёмная' if self.theme_var.get()=='dark' else 'Светлая'),command=lambda:(self.theme_var.set('light' if self.theme_var.get()=='dark' else 'dark'),self.apply_theme()))
        menu.add_command(label='Справка · F1',command=self.help_view.context);menu.add_command(label='Контакты и лицензия',command=self.show_contacts)
        try:menu.tk_popup(self.menu_button.winfo_rootx(),self.menu_button.winfo_rooty()+self.menu_button.winfo_height())
        finally:menu.grab_release()

    def escape(self,event=None):
        if self.busy:self.request_cancel()
        else:self.hide_search()
        return 'break'

    def busy_key(self,event):
        if not self.busy:return
        if self.stop_dialog and event.widget.winfo_toplevel()==self.stop_dialog:
            return None if event.keysym in ('Tab','ISO_Left_Tab','Return','space') else 'break'
        if event.keysym in ('Escape','F4') or ((event.state&0x4) and event.keysym.lower()=='w'):
            self.request_cancel();return 'break'
        if event.widget==self.stop and event.keysym in ('Return','space'):return
        return 'break'

    def install_interaction_guard(self):
        # A first bindtag runs before widget/class bindings (including Treeview,
        # notebook navigation and shortcuts). bind_all alone runs too late.
        tag='OperatorGuard'+str(id(self))
        def guard(event):
            if self.busy and event.widget!=self.stop:
                if str(event.type)=='2':return self.busy_key(event)
                return 'break'
            if not self.select_text_var.get() and event.widget.winfo_class()=='Text':
                try:readonly=str(event.widget.cget('state'))=='disabled'
                except tk.TclError:readonly=False
                if readonly and str(event.type) in ('2','4','6'):return 'break'
        for sequence in ('<ButtonPress>','<ButtonRelease>','<B1-Motion>','<KeyPress>','<MouseWheel>'):
            self.root.bind_class(tag,sequence,guard)
        def visit(widget):
            widget.bindtags((tag,*widget.bindtags()))
            for child in widget.winfo_children():visit(child)
        visit(self.root)

    def request_cancel(self):
        if not self.busy:return
        if self.stop_dialog:
            self.stop_dialog.lift();return
        window=tk.Toplevel(self.root);self.stop_dialog=window;window.title('Остановить генерацию?');window.transient(self.root);window.resizable(False,False)
        frame=ttk.Frame(window,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Остановить принудительно?',style='Operator.Title.TLabel').pack(anchor='w')
        ttk.Label(frame,text='Частичные результаты сохраняются. Незавершённый PDF может быть непригоден.',wraplength=430).pack(anchor='w',pady=8)
        countdown=tk.StringVar(master=window,value='Подтверждение через 3 секунды');ttk.Label(frame,textvariable=countdown).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=(12,0))
        yes=ttk.Button(row,text='Остановить',style='Force.Operator.TButton',state='disabled',command=self.confirm_stop);yes.pack(side='left')
        no=ttk.Button(row,text='Продолжить',state='disabled',command=self.continue_operation);no.pack(side='left',padx=10)
        remaining=[3]
        def step():
            self._stop_after=None
            if not self.stop_dialog:return
            remaining[0]-=1;countdown.set(f'Подтверждение через {remaining[0]} сек' if remaining[0] else 'Выберите действие')
            if remaining[0]:self._stop_after=self.root.after(1000,step)
            else:yes.configure(state='normal');no.configure(state='normal');no.focus_set()
        window.protocol('WM_DELETE_WINDOW',lambda:self.continue_operation() if remaining[0]==0 else None)
        window.bind('<Escape>',lambda event:'break');window.grab_set();self._stop_after=self.root.after(1000,step)

    def dismiss_stop(self):
        if self._stop_after:
            self.root.after_cancel(self._stop_after);self._stop_after=None
        if self.stop_dialog:
            window=self.stop_dialog;self.stop_dialog=None
            try:window.grab_release();window.destroy()
            except tk.TclError:pass

    def continue_operation(self):
        self.close_after_stop=False;self.dismiss_stop()

    def confirm_stop(self):
        self.dismiss_stop();self.cancel.set()
        if self.operation_host:self.operation_host.stop(force=True)
        self.status_var.set('Принудительная остановка запрошена. Частичные файлы сохраняются.')
        if self.close_after_stop:self.closing=True

    def close(self):
        if self.busy or (self.worker is not None and self.worker.is_alive()):
            self.close_after_stop=True;self.request_cancel();return
        self.search_cancel.set();self.hide_search();self.save_operator_preferences()
        for timer in (self._search_after,self._preview_after):
            if timer:
                try:self.root.after_cancel(timer)
                except tk.TclError:pass
        self.remember();self.root.destroy()

    def complete(self,folder):
        self.operation_host=None;self.dismiss_stop();super().complete(folder)
        manifest=Path(folder)/'manifest.json'
        if manifest.exists():
            data=json.loads(manifest.read_text(encoding='utf-8'));status=data.get('status')
            measured=data.get('seconds',{}).get('launcher_wall')
            if measured:
                from .batch_gui import clock_text
                self.elapsed_var.set('Весь запуск: '+clock_text(measured))
                self.speed_var.set(f'Весь запуск: {data["count"]/measured:.1f} кодов/сек'.replace('.',','))
            if (Path(folder)/'production.html').is_file():self.last_report=Path(folder)/'production.html'
            if status in ('INVALID','ERROR'):self.result_label.configure(style='Danger.Result.TLabel')
            elif status in ('UNVERIFIED','LIMITED','CANCELLED'):self.result_label.configure(style='Warning.Result.TLabel')

    def restore_defaults(self):
        super().restore_defaults()
        self.background_mode_var.set('white')
        for variable in self.background_vars:variable.set('0')
        self.qa_mode_var.set('Отложена');self.pdf_profile_var.set('Компактный');self.activity_var.set('minimal');self.xy_mode_var.set('on')
        self.generation_cpu.choice.set('all');self.generation_cpu.ram.set('max');self.generation_cpu.select()
        self.preview_print();self.remember()

    def start(self):
        if self.busy:return
        if not self.source_index or not self.source_index.unchanged():
            self.status_var.set('База отсутствует или изменилась. Откройте её заново.');self.notebook.select(self.pages['source']);return
        if self.preview_print() is None:return
        try:
            options=self.read_generation_options();directory=Path(options.output_directory).resolve();payload=self.order_payload()
            free=shutil.disk_usage(directory).free
            if not self.approval.valid(payload,directory,free):
                self.approval.invalidate();self.notebook.select(self.pages['path']);self.status_var.set('Проверьте место для текущего заказа во вкладке «Путь».');return
            if not self.source_index.verify_content():raise ValueError('TXT изменился; загрузите его заново')
            from .generation_cpu import execution_options
            request={'input':str(self.source_index.source),'destination':str(directory),'settings':asdict(self.print_settings),'options':asdict(options),
                     'mode':self.mode_var.get(),'execution':asdict(execution_options(options,self.hardware)),
                     'telemetry':self.telemetry_var.get(),'archive':str(self.archive_root)}
            self.remember();self.operation_kind='generation';self.begin()
            from .operation_host import OperationHost
            self.operation_host=OperationHost(self.preferences_path.parent/'operations',request,self.events)
            self.operation_host.start();self.worker=self.operation_host.thread
        except (ValueError,OSError) as exc:
            self.busy=False;self.status_var.set(str(exc));self.update_buttons()


def main():
    root=tk.Tk();root.withdraw();app=OperatorWindow(root);root.deiconify();root.mainloop();del app
