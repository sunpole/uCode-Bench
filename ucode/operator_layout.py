"""Native v0.3 layout. Existing laboratories are mounted without replacement."""
import tkinter as tk
from tkinter import ttk
from .operator_widgets import CycleButton, PageStack, LaunchFrame
from .ui_layout import PDF_PROFILES, POLICIES, _resources


ACCENTS={'type':'#c6a5ef','source':'#83d4ed','path':'#a2d5e5','print':'#9cbcff',
         'resources':'#edc083','generation':'#5ce0bd','testing':'#c6a5ef','other':'#a2d5e5'}


def entry(app,parent,variable,label,*,width=12,numeric=True):
    frame=ttk.Frame(parent);frame.pack(side='left',padx=(0,12),anchor='n')
    ttk.Label(frame,text=label,style='Operator.Muted.TLabel').pack(anchor='w')
    widget=app.edit(ttk.Entry(frame,textvariable=variable,width=width));widget.pack(anchor='w')
    if numeric:app.number_entries.append((widget,variable))
    return widget


def title(parent,text):
    row=ttk.Frame(parent,height=26);row.pack(fill='x',pady=(0,6));row.pack_propagate(False)
    ttk.Label(row,text=text,style='Operator.Title.TLabel').pack(side='left')
    return row


def build_operator(app,help_text):
    from .ui_theme import apply_dark_theme
    from .brand import install
    from .operator_window import LaboratoryContext
    app.style=apply_dark_theme(app.root);app.menus=[];app.edit_controls=[];app.hints=[];app.number_entries=[]
    app.root.title('uCode 0.3.0');app.root.protocol('WM_DELETE_WINDOW',app.close)
    body=ttk.Frame(app.root,padding=(12,7));body.pack(fill='both',expand=True)
    body.columnconfigure(0,weight=1);body.rowconfigure(1,weight=1);app.operator_body=body
    header=ttk.Frame(body);header.grid(row=0,column=0,sticky='ew',pady=(0,5));header.columnconfigure(2,weight=1)
    app.menu_button=app.edit(ttk.Button(header,text='☰',width=3,command=app.show_operator_menu));app.menu_button.grid(row=0,column=0,padx=(0,7))
    brand=ttk.Frame(header);brand.grid(row=0,column=1);install(app,brand)
    ttk.Label(header,textvariable=app.filename,style='Operator.Muted.TLabel').grid(row=0,column=2,sticky='w')
    app.notebook=PageStack(app,body);app.notebook.grid(row=1,column=0,sticky='nsew')
    app.pages={}
    for key,label in (('type','Тип'),('source','База'),('path','Путь'),('print','Оформление'),('resources','Настройка'),('generation','Просмотр'),('testing','Тесты'),('other','Другое')):
        page=ttk.Frame(app.notebook.content,padding=(3,5));app.pages[key]=page
        app.notebook.add(page,text=label,accent=ACCENTS[key])
    _types(app);_source(app);_path(app);_print(app);_view(app)
    from .generation_cpu import GenerationCPU
    title(app.pages['resources'],'Настройка')
    cpu=ttk.Frame(app.pages['resources']);cpu.pack(fill='x')
    app.generation_cpu=GenerationCPU(app,cpu)
    _resources(app)
    modes=ttk.Frame(app.pages['resources']);modes.pack(fill='x',pady=4)
    app.mode_picker=CycleButton(app,modes,app.mode_var,'',(('ОДИН PDF','multipage'),('Отдельные PDF','singles'),('ОБА ВАРИАНТА','both')),command=app.remember,caption=app.output_caption);app.mode_picker.pack(side='left',padx=(0,5))
    app.qa_picker=CycleButton(app,modes,app.qa_enabled_var,'',(('БЕЗ ПРОВЕРКИ','off'),('С ПРОВЕРКОЙ','on')),command=app.apply_qa_choice);app.qa_picker.pack(side='left',padx=5)
    app.pdf_picker=CycleButton(app,modes,app.pdf_profile_var,'PDF',[(k,k) for k in PDF_PROFILES],command=app.apply_pdf_profile);app.pdf_picker.pack(side='left',padx=5);app.main_pdf_picker=app.pdf_picker
    app.main_activity_picker=CycleButton(app,modes,app.activity_var,'Расходы',(('Минимум','minimal'),('Обычные','normal')),command=app.remember);app.main_activity_picker.pack(side='left',padx=5)
    extras=ttk.Frame(app.pages['resources']);extras.pack(fill='x',pady=3)
    CycleButton(app,extras,app.telemetry_var,'Статистика',(('Подробная','cpu'),('Минимальная','off')),command=app.save_operator_preferences).pack(side='left')
    app.xy_picker=CycleButton(app,extras,app.xy_mode_var,'XY',(('Записывать','on'),('Выключен','off')),command=app.remember);app.xy_picker.pack(side='left',padx=5)
    CycleButton(app,extras,app.qa_depth_var,'Глубина QA',(('Полная','Полная'),('Структура PDF','Без растра')),command=app.apply_qa_choice).pack(side='left',padx=5)
    ttk.Label(extras,text='GPU: модуль не подключён',style='Operator.Muted.TLabel').pack(side='left',padx=8)
    app.lab_context=LaboratoryContext(app)
    _tests(app);_other(app);_commands(app,body);_footer(app,body)
    app.verification_buttons={'full':app.qa_picker,'deferred':app.qa_picker,'vector':app.qa_picker}
    app.help_button=app.menu_button
    app.notebook.bind('<<NotebookTabChanged>>',lambda event:app.page_changed() if hasattr(app,'generate') else None,add='+')
    app.notebook.select(app.pages['source'])


def _types(app):
    page=app.pages['type'];title(page,'Тип')
    cards=ttk.Frame(page);cards.pack(fill='both',expand=True)
    rows=[('QR Code','qr','Текущий профиль: 12 цифр','QR V1-M · 21 × 21 модуль · поле от 4 модулей'),('Code 128','code128','Буквы и цифры','Линейный код · будущий модуль'),('EAN-13','ean13','13 цифр с контрольной','Товарный номер · будущий модуль'),('Data Matrix','datamatrix','Длина зависит от профиля','Двумерный код · будущий модуль')]
    for index,(name,key,inputs,description) in enumerate(rows):
        cards.columnconfigure(index,weight=1,uniform='cards')
        frame=ttk.Frame(cards,padding=7);frame.grid(row=0,column=index,sticky='nsew',padx=3)
        canvas=tk.Canvas(frame,width=150,height=95,background='white',highlightthickness=0);canvas.pack(fill='x')
        app.type_canvases.append((canvas,key))
        ttk.Label(frame,text=name,style='Operator.Title.TLabel').pack(anchor='w',pady=(7,3))
        ttk.Label(frame,text=inputs,wraplength=185,style='Operator.Muted.TLabel').pack(anchor='w')
        button=app.edit(ttk.Button(frame,text='Выбрать QR Code' if key=='qr' else 'В разработке',command=lambda:app.notebook.select(app.pages['source'])))
        button.pack(fill='x',pady=6)
        if key!='qr':button.configure(state='disabled');app.edit_controls[-1]=(button,'disabled')
        ttk.Label(frame,text=description,wraplength=185,style='Operator.Muted.TLabel').pack(anchor='w')


def _source(app):
    page=app.pages['source'];title(page,'База')
    columns=ttk.Frame(page);columns.pack(fill='both',expand=True)
    left=ttk.Frame(columns);left.pack(side='left',fill='both',expand=True,padx=(0,20))
    right=ttk.Frame(columns);right.pack(side='left',fill='both',expand=True)
    ttk.Label(left,text='Открыть файл',style='Operator.Title.TLabel').pack(anchor='w')
    app.edit(ttk.Button(left,text='Открыть TXT…',command=app.choose)).pack(anchor='w',pady=8)
    ttk.Label(left,textvariable=app.file_count,wraplength=430,style='Operator.Muted.TLabel').pack(anchor='w')
    CycleButton(app,left,app.duplicates_var,'Повторы TXT',[(key,key) for key in POLICIES],command=app.remember).pack(anchor='w',pady=10)
    ttk.Label(right,text='Создать TXT',style='Operator.Title.TLabel').pack(anchor='w')
    row=ttk.Frame(right);row.pack(anchor='w',pady=5)
    app.custom_start_entry=entry(app,row,app.template_start_var,'Начальный номер',width=21)
    row=ttk.Frame(right);row.pack(anchor='w',pady=5)
    app.custom_count_entry=entry(app,row,app.custom_count_var,'Количество строк',width=16)
    entry(app,row,app.template_step_var,'Шаг',width=9)
    ttk.Label(right,textvariable=app.template_preview_var,style='Operator.Muted.TLabel').pack(anchor='w',pady=5)
    buttons=ttk.Frame(right);buttons.pack(anchor='w',pady=5)
    app.edit(ttk.Button(buttons,text='Использовать',command=app.use_sequence)).pack(side='left')
    app.edit(ttk.Button(buttons,text='Сохранить TXT…',command=app.save_sequence)).pack(side='left',padx=7)


def _path(app):
    page=app.pages['path'];title(page,'Путь')
    row=ttk.Frame(page);row.pack(fill='x')
    widget=app.edit(ttk.Entry(row,textvariable=app.destination_var));widget.pack(side='left',fill='x',expand=True)
    app.edit(ttk.Button(row,text='Выбрать папку…',command=app.choose_destination)).pack(side='left',padx=7)
    app.path_check_button=app.edit(ttk.Button(page,text='Проверить папку и запас места',command=app.check_destination));app.path_check_button.pack(anchor='w',pady=9)
    ttk.Label(page,textvariable=app.path_status_var,wraplength=920,style='Operator.Muted.TLabel').pack(anchor='w')
    ttk.Label(page,text='Запас: 4 × (PDF + временные данные + отчёты) + резерв ОС/диска.\nОценка основана на малых настоящих PDF; свободное место повторно проверяется перед запуском и во время записи.',wraplength=920,style='Operator.Muted.TLabel').pack(anchor='w',pady=8)


def _print(app):
    page=app.pages['print'];title(page,'Оформление')
    row=ttk.Frame(page);row.pack(fill='x',pady=3)
    CycleButton(app,row,app.geometry_basis,'Размер',(('Страница','side'),('Модуль','module')),command=app.change_geometry_basis).pack(side='left',padx=(0,8))
    app.geometry_entry=app.edit(ttk.Spinbox(row,textvariable=app.geometry_value,width=9,from_=.25,to=122,increment=.05));app.geometry_entry.pack(side='left');app.number_entries.append((app.geometry_entry,app.geometry_value))
    ttk.Label(row,text=' мм · поле, модулей ',style='Operator.Muted.TLabel').pack(side='left')
    q=app.edit(ttk.Entry(row,textvariable=app.quiet_var,width=5));q.pack(side='left');app.number_entries.append((q,app.quiet_var))
    copies=ttk.Frame(page);copies.pack(fill='x',pady=3);entry(app,copies,app.copies_var,'Экземпляров каждого',width=10)
    columns=ttk.Frame(page);columns.pack(fill='x',pady=4)
    for side,variables,label in (('left',app.ink_vars,'Код · CMYK, %'),('right',app.background_vars,'Подложка · CMYK, %')):
        frame=ttk.Frame(columns);frame.pack(side=side,fill='x',expand=True)
        ttk.Label(frame,text=label,style='Operator.Title.TLabel').pack(anchor='w')
        fields=ttk.Frame(frame);fields.pack(anchor='w',pady=4)
        for name,var in zip('CMYK',variables):entry(app,fields,var,name,width=5)
        if side=='left':app.edit(ttk.Button(frame,text='K100',command=app.use_k100)).pack(anchor='w',pady=4)
        else:CycleButton(app,frame,app.background_mode_var,'Фон',(('Белый','white'),('Цветной','color'),('Прозрачный','transparent')),command=app.preview_print).pack(anchor='w',pady=4)
    ttk.Label(page,textvariable=app.print_preview,wraplength=900,style='Operator.Muted.TLabel').pack(anchor='w',pady=4)
    ttk.Label(page,textvariable=app.color_note_var,wraplength=900,style='Operator.Muted.TLabel').pack(anchor='w')


def _view(app):
    page=app.pages['generation'];heading=title(page,'Просмотр')
    ttk.Label(heading,text='Предпросмотр · QR Code',style='Operator.Muted.TLabel').pack(side='right')
    work=ttk.Frame(page);work.pack(fill='both',expand=True);work.columnconfigure(0,weight=3);work.columnconfigure(1,weight=2);work.rowconfigure(0,weight=1)
    left=ttk.Frame(work);left.grid(row=0,column=0,sticky='nsew',padx=(0,20));left.columnconfigure(0,weight=1);left.rowconfigure(0,weight=1)
    app.source_table=ttk.Treeview(left,columns=('row','code'),show='headings',height=9,style='Source.Treeview',selectmode='browse')
    app.source_table.heading('row',text='Строка');app.source_table.heading('code',text='Код')
    app.source_table.column('row',width=90,stretch=False);app.source_table.column('code',width=250)
    app.source_table.grid(row=0,column=0,sticky='nsew')
    scrollbar=ttk.Scrollbar(left,orient='vertical',command=app.scroll_source);scrollbar.grid(row=0,column=1,sticky='ns');app.source_scrollbar=scrollbar
    app.source_table.bind('<<TreeviewSelect>>',app.source_selected);app.source_table.bind('<MouseWheel>',app.source_wheel)
    app.preview_canvas=tk.Canvas(work,width=280,height=220,highlightthickness=0,background='#0b1220');app.preview_canvas.grid(row=0,column=1,sticky='nsew')
    app.preview_canvas.bind('<Configure>',lambda event:app.paint_preview())


def _tests(app):
    ctx=app.lab_context;page=app.pages['testing'];bar=ttk.Frame(page);bar.pack(fill='x')
    CycleButton(app,bar,ctx.qa_mode_var,'QA',(('Полная','Полная'),('Без проверки','Отложена'),('Структура','Без растра'))).pack(side='left')
    app.test_run=app.edit(ttk.Button(bar,text='Запустить тест',command=lambda:app.generate.invoke()));app.test_run.pack(side='right')
    app.test_notebook=app.notebook.test_hub(page)
    for key,label in (('lab','CPU / RAM'),('pipeline','Конвейер'),('search','Подбор ПК'),('tests','Научный'),('console','Консоль'),('archive','Архив'),('history','История'),('lab_print','PDF теста')):
        frame=ttk.Frame(app.test_notebook,padding=(5,3));app.test_notebook.add(frame,text=label);app.pages[key]=frame
    from .lab_ui import build_lab
    from .pipeline_ui import PipelineView
    from .search_ui import SearchView
    from .test_console_ui import ConsoleView,copy_current
    from .archive_ui import ArchiveView
    from .history_ui import HistoryView
    build_lab(ctx);app.pipeline_view=PipelineView(ctx);app.search_view=SearchView(ctx);app.console_view=ConsoleView(ctx)
    app.archive_view=ArchiveView(ctx);app.history_view=HistoryView(ctx)
    app.edit(ttk.Button(bar,text='В консоль →',command=lambda:copy_current(ctx))).pack(side='right',padx=6)
    frame=app.pages['tests'];app.scientific_size=tk.StringVar(master=app.root,value='200')
    ttk.Label(frame,text='Научный профиль · 3 повтора · QR V1-M · K100 · полная QA',style='Muted.TLabel').pack(anchor='w')
    CycleButton(app,frame,app.scientific_size,'Масштаб',(('200','200'),('200 → 1 000','1000'),('200 → 1 000 → 10 000','10000'),('Полный','all'))).pack(anchor='w',pady=5)
    app.engine_options_frame=ttk.Frame(frame);app.engine_options_frame.pack(fill='both',expand=True)
    app.edit(ttk.Button(frame,text='Выбрать движки',command=app.performance_dialog)).pack(anchor='w')
    frame=app.pages['lab_print'];title(frame,'PDF теста · независимо от рабочего заказа')
    row=ttk.Frame(frame);row.pack(anchor='w')
    entry(app,row,ctx.geometry_value,'Сторона PDF, мм',width=12);entry(app,row,ctx.quiet_var,'Поле, модулей',width=8)
    for name,var in zip('CMYK',ctx.ink_vars):entry(app,row,var,name+' %',width=6)
    row=ttk.Frame(frame);row.pack(anchor='w',pady=8)
    CycleButton(app,row,ctx.mode_var,'Файлы',(('Один PDF','multipage'),('Отдельные PDF','singles'),('Оба варианта','both')),command=ctx.remember).pack(side='left')
    CycleButton(app,row,ctx.pdf_profile_var,'PDF',[(v,v) for v in PDF_PROFILES],command=ctx.apply_print).pack(side='left',padx=6)
    CycleButton(app,row,ctx.xy_mode_var,'XY',(('Записывать','on'),('Выключен','off')),command=ctx.remember).pack(side='left')
    app.edit(ttk.Button(frame,text='Применить к тестам',command=ctx.apply_print)).pack(anchor='w')
    ttk.Label(frame,textvariable=ctx.geometry_summary,style='Operator.Muted.TLabel').pack(anchor='w',pady=7)
    ttk.Label(frame,text='Научный профиль всегда использует исторические QR V1-M / 0,5 мм / 4 модуля / K100 и три повтора.',wraplength=900,style='Operator.Muted.TLabel').pack(anchor='w')


def _other(app):
    hub=app.notebook.other_hub(app.pages['other'])
    for key,label in (('help','Справка'),('contacts','Контакты'),('legacy','Объединение / прежняя лаборатория')):
        page=ttk.Frame(hub,padding=5);app.pages[key]=page;hub.add(page,text=label)
    from .help_ui import HelpView
    app.help_view=HelpView(app)
    from .help_content import CONTACTS
    frame=app.pages['contacts']
    app.edit(ttk.Button(frame,text='← Назад',command=app.go_back)).pack(anchor='w')
    ttk.Label(frame,text='uCode · Антон Магомедов · uBrand',style='Operator.Title.TLabel').pack(anchor='w',pady=9)
    for label,url in CONTACTS:
        app.edit(ttk.Button(frame,text=label,command=lambda address=url:app.open_url(address),style='Flat.Operator.TButton')).pack(anchor='w')
    ttk.Label(frame,text='Лицензия программы пока не оформлена. Сторонние библиотеки имеют собственные условия.',style='Operator.Muted.TLabel',wraplength=800).pack(anchor='w',pady=8)
    app.edit(ttk.Button(app.pages['legacy'],text='Открыть исходную лабораторию объединения',command=app.open_legacy)).pack(anchor='w')
    app.edit(ttk.Button(app.pages['legacy'],text='Восстановить настройки',command=app.restore_defaults)).pack(anchor='w',pady=9)


def _commands(app,body):
    app.command_band=ttk.Frame(body,padding=(0,5));app.command_band.grid(row=2,column=0,sticky='ew');app.command_band.columnconfigure(2,weight=1)
    cluster=ttk.Frame(app.command_band);cluster.grid(row=0,column=0,rowspan=2,padx=(0,12))
    app.launch_frame=LaunchFrame(cluster);app.launch_frame.pack(side='left')
    app.generate=ttk.Button(app.launch_frame,text='Создать\nPDF',style='Primary.TButton',command=app.start)
    app.launch_frame.create_window(44,44,width=76,height=76,window=app.generate)
    app.stop=ttk.Button(cluster,text='СТОП',style='Force.Operator.TButton',command=app.request_cancel);app.stop.pack(side='left',fill='y',padx=7)
    nav=ttk.Frame(app.command_band);nav.grid(row=0,column=1,sticky='w')
    for label,action in (('⇤',lambda:app.goto_row(1)),('‹',lambda:app.goto_row(app.current_row-1))):app.edit(ttk.Button(nav,text=label,width=2,command=action,style='Compact.Operator.TButton')).pack(side='left',padx=1)
    rowfield=app.edit(ttk.Entry(nav,textvariable=app.row_var,width=9));rowfield.pack(side='left',padx=3);app.number_entries.append((rowfield,app.row_var))
    ttk.Label(nav,textvariable=app.row_total_var,style='Operator.Muted.TLabel').pack(side='left')
    for label,action in (('›',lambda:app.goto_row(app.current_row+1)),('⇥',lambda:app.goto_row(len(app.source_index) if app.source_index else 1))):app.edit(ttk.Button(nav,text=label,width=2,command=action,style='Compact.Operator.TButton')).pack(side='left',padx=1)
    search=ttk.Frame(app.command_band);search.grid(row=0,column=2,sticky='w',padx=8)
    app.search_entry=app.edit(ttk.Entry(search,textvariable=app.search_var,width=21));app.search_entry.pack(side='left')
    from .ui_hints import Hint
    app.hints.append(Hint(app.search_entry,'Поиск по всей базе при вводе. До трёх совпадений; выбор сразу открывает строку.'))
    app.search_popup=None
    density=ttk.Frame(app.command_band);density.grid(row=0,column=3,sticky='e')
    ttk.Label(density,text='Шрифт строк',style='Operator.Muted.TLabel').pack(side='left')
    app.density=app.edit(ttk.Scale(density,from_=8,to=32,variable=app.row_font_var,length=110,command=app.density_changed));app.density.pack(side='left',padx=5)
    ttk.Label(density,textvariable=app.row_font_text,style='Operator.Muted.TLabel').pack(side='left')
    ttk.Label(app.command_band,textvariable=app.source_position_var,style='Operator.Muted.TLabel').grid(row=1,column=1,columnspan=3,sticky='w')


def _footer(app,body):
    footer=ttk.Frame(body,padding=(0,4));footer.grid(row=3,column=0,sticky='ew');app.footer=footer
    app.statistics_toggle=ttk.Button(footer,text='Статистика ▴',command=app.toggle_statistics,style='Flat.Operator.TButton');app.statistics_toggle.pack(anchor='center')
    app.phase_label=ttk.Label(footer,textvariable=app.status_var,style='Operator.Muted.TLabel',wraplength=1000);app.phase_label.pack(fill='x')
    app.progress=ttk.Progressbar(footer,mode='determinate',maximum=100);app.progress.pack(fill='x',pady=3)
    app.statistics_frame=ttk.Frame(footer);app.statistics_frame.pack(fill='x')
    row=ttk.Frame(app.statistics_frame);row.pack(fill='x')
    ttk.Label(row,textvariable=app.elapsed_var,style='Operator.Muted.TLabel').pack(side='left')
    ttk.Label(row,textvariable=app.speed_var,style='Operator.Muted.TLabel').pack(side='right')
    ttk.Label(app.statistics_frame,textvariable=app.plan_var,style='Operator.Muted.TLabel').pack(anchor='w')
    ttk.Label(app.statistics_frame,textvariable=app.geometry_summary,style='Operator.Muted.TLabel').pack(anchor='w')
    app.result_label=ttk.Label(app.statistics_frame,textvariable=app.result_var,style='Result.TLabel',wraplength=1000);app.result_label.pack(anchor='w')
    ttk.Label(app.statistics_frame,textvariable=app.result_details,style='Operator.Muted.TLabel',wraplength=1000).pack(anchor='w')
    actions=ttk.Frame(app.statistics_frame);actions.pack(fill='x',pady=2)
    app.open=ttk.Button(actions,text='Открыть PDF',command=app.open_pdf);app.open.pack(side='left')
    app.folder_button=ttk.Button(actions,text='Папка',command=app.open_result);app.folder_button.pack(side='left',padx=5)
    app.report_button=ttk.Button(actions,text='Отчёт',command=app.open_report);app.report_button.pack(side='left',padx=5)
    app.audit_button=ttk.Button(actions,text='Проверить PDF',command=app.start_audit);app.audit_button.pack(side='left',padx=5)
    credits=ttk.Frame(footer);credits.pack(fill='x',pady=(3,0))
    ttk.Label(credits,text='© 2026 · uCode · uBrand',style='Operator.Muted.TLabel').pack(side='left')
    for label in ('Контакты','Лицензия'):
        app.edit(ttk.Button(credits,text=label,style='Flat.Operator.TButton',command=app.show_contacts)).pack(side='right',padx=6)
