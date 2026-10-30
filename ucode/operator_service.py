"""Local operator service. Rendering and lab/production engines are independent."""
from dataclasses import asdict,fields
import functools
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .app_settings import GenerationPreferences,load_user_preferences,save_preferences
from .operator_models import SourceIndex,SequenceSpec,JobApproval,estimate_space,parse_number
from .print_settings import PrintSettings


def native_dialog(kind,initial=''):
    options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    result=subprocess.run([sys.executable,'-m','ucode.native_dialog',kind,str(initial)],capture_output=True,
                          text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},**options)
    if result.returncode:raise OSError('Не удалось открыть Проводник: '+result.stderr[-500:])
    return json.loads(result.stdout.strip())


def config_types():
    from .resource_lab import LabConfig
    from .pipeline_plan import PipelineConfig
    from .pc_search import SearchConfig
    return {'LabConfig':LabConfig,'PipelineConfig':PipelineConfig,'SearchConfig':SearchConfig}


class OperatorService:
    def __init__(self,root):
        from .hardware import inspect_hardware
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.private=self.root/'.local-state';self.private.mkdir(exist_ok=True)
        self.output=self.root/'output';self.archive=self.output/'test-archive'
        self.preferences=self.private/'user-settings.json'
        self.hardware=inspect_hardware(self.root);self.lock=threading.RLock();self.events=queue.Queue()
        self.cancel=threading.Event();self.search_cancel=threading.Event();self.worker=None;self.host=None;self.index=None;self.busy=False
        self.status='Откройте TXT или создайте базу';self.progress=None;self.started=None;self.finished=None
        self.last_output=None;self.result=None;self.approval=JobApproval();self.estimate=None
        self.telemetry='cpu';self.ui={'theme':'dark','rowFont':8,'allowSelect':False,'statisticsOpen':True}
        self.settings,self.mode,self.options,_=load_user_preferences(self.preferences)
        if not self.preferences.exists():
            from .affinity import select_cpus
            unit='physical' if self.hardware['cpu'].get('available_physical') else 'logical'
            n=len(select_cpus(self.hardware['cpu'],unit,'all'))
            self.settings=PrintSettings(pdf_profile='compact');self.mode='multipage'
            self.options=GenerationPreferences(output_directory=str(self.output/'jobs'),execution_backend='process',workers=n,
                qa_mode='deferred',activity='minimal',cpu_choice='all',cpu_unit=unit,ram_mode='max',timeline_mode='on')
        if not self.options.output_directory:
            from dataclasses import replace
            self.options=replace(self.options,output_directory=str(self.output/'jobs'))
        self.form=asdict(self.options);self.form.update(mode=self.mode,print=asdict(self.settings),telemetry=self.telemetry,manual_cpus=[])
        self.lab_configs={name:asdict(cls()) for name,cls in config_types().items()}
        for name,filename in (('LabConfig','lab-settings.json'),('PipelineConfig','pipeline-settings.json'),('SearchConfig','pc-search-settings.json')):
            try:self.lab_configs[name]=asdict(self.valid_config(name,json.loads((self.private/filename).read_text(encoding='utf-8'))))
            except (OSError,ValueError,TypeError,KeyError):pass
        self._stop_nonce=None;self._stop_at=None;self.revision=0;self.history_paths={};self.closed=False
        self.output_name=None;self.manual_name=False;self.name_stamp=None;self.confirmed_directory=None;self.source_serial=0
        try:
            saved=json.loads((self.private/'web-ui.json').read_text(encoding='utf-8'))
            self.ui.update(saved.get('ui',{}));self.telemetry=saved.get('telemetry','cpu');self.form['telemetry']=self.telemetry
            from .order_output import normalize_name
            name=saved.get('order_name',{})
            self.manual_name=bool(name.get('manual',False));self.name_stamp=name.get('stamp')
            if self.manual_name:self.output_name=normalize_name(name['value'])
            for key,value in saved.get('lab_configs',{}).items():
                if key in config_types():self.lab_configs[key]=asdict(self.valid_config(key,value))
            source=saved.get('source');cached=saved.get('index')
            if source and cached:
                cached={**cached,'source':Path(cached['source']),'database':Path(cached['database'])}
                from .qr_payloads import PayloadSource
                candidate=PayloadSource(**cached) if 'content_kind' in cached else SourceIndex(**cached)
                cache_root=self.private/('payload-sources' if isinstance(candidate,PayloadSource) else 'source-indexes')
                if candidate.source==Path(source) and candidate.unchanged() and candidate.database.is_relative_to(cache_root) and candidate.database.is_file():
                    stat=candidate.database.stat()
                    if saved.get('index_stat')==[stat.st_size,stat.st_mtime_ns]:self.index=candidate
            if source and not self.index:self.status='Предыдущая база изменилась или кэш недоступен. Откройте TXT заново.'
        except (OSError,ValueError,TypeError,KeyError):pass

    def save(self):
        from .lab_worker import atomic_json
        save_preferences(self.preferences,self.settings,self.mode,generation=self.options)
        index=asdict(self.index) if self.index else None
        if index:index.update(source=str(self.index.source),database=str(self.index.database))
        stat=self.index.database.stat() if self.index else None
        atomic_json(self.private/'web-ui.json',{'ui':self.ui,'telemetry':self.telemetry,'lab_configs':self.lab_configs,
                    'order_name':{'value':self.result_name(),'manual':self.manual_name,'stamp':self.name_stamp},
                    'source':str(self.index.source) if self.index else None,'index':index,
                    'index_stat':[stat.st_size,stat.st_mtime_ns] if stat else None})

    def require_idle(self):
        if self.busy:raise ValueError('Операция выполняется. Сначала остановите её через подтверждение.')

    def order(self):
        return {'source':self.index.sha256 if self.index else None,'form':self.form,'output_name':self.result_name()}

    def result_name(self):
        from .order_output import suggested_name
        from datetime import datetime
        if self.name_stamp is None:self.name_stamp=datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        if self.manual_name:return self.output_name
        if self.index and hasattr(self.index,'content_kind'):
            return f'QR_{self.index.content_kind}_{self.index.sha256[-4:]}_{self.plan().total_codes}_{self.name_stamp}.pdf'
        return suggested_name(self.index.first if self.index else '0000',self.plan().total_codes if self.index else 0,self.name_stamp)

    def content_frame(self,settings=None):
        cfg=settings or self.settings
        return self.preview_frame(self.index.first,cfg.error_correction,True)

    def set_content(self,kind,values):
        from .qr_payloads import build_payload,PayloadSource
        self.require_idle();payload=build_payload(kind,values)
        self.preview_frame(payload,self.settings.error_correction,True)
        self.index=PayloadSource.create(self.private/'payload-sources',kind,payload)
        self.source_serial+=1;self.name_stamp=None;self.revision+=1;self.refresh_approval();self.save()

    def set_output_name(self,value,automatic=False):
        from .order_output import normalize_name
        self.require_idle()
        name=None if automatic else normalize_name(value)
        self.output_name=name;self.manual_name=not automatic
        self.refresh_approval();self.save()

    def refresh_approval(self):
        """Recalculate safely without requiring another folder selection."""
        self.approval.invalidate()
        if not self.index or self.confirmed_directory!=str(Path(self.options.output_directory).resolve()):return
        try:
            destination=Path(self.confirmed_directory);free=shutil.disk_usage(destination).free
            bound=max(8192,(self.estimate or {}).get('sample_page_bytes',0)*2)
            if hasattr(self.index,'content_kind'):bound=max(bound,self.content_frame().size**2*80)
            estimate=estimate_space(self.plan().total_codes,self.mode,bound,free,
                                    temp_bytes=self.plan().unique_values*4096,allocation_unit=65536)
            self.estimate={**(self.estimate or {}),**asdict(estimate),'enough':estimate.enough}
            if estimate.enough:self.approval.approve(self.order(),destination,estimate.required_bytes)
        except (OSError,ValueError):self.status='Путь недоступен. Проверьте папку ещё раз.'

    def execution(self):
        from .generation_cpu import execution_options
        from .execution import ExecutionOptions
        manual=self.form.get('manual_cpus') or []
        if manual:
            from .affinity import cpu_keys
            available=self.hardware['cpu']['available_cpus'];selected=[]
            for value in manual:
                group,logical=map(int,str(value).split(':')) if ':' in str(value) else (0,int(value))
                item=next((c for c in available if (c['group'],c['logical'])==(group,logical)),None)
                if item is None:raise ValueError('CPU недоступен: '+str(value))
                selected.append(item)
            if len(set(cpu_keys(selected)))!=len(selected):raise ValueError('В списке CPU есть повторы')
            if self.options.execution_backend!='process' or self.options.workers!=len(selected):raise ValueError('Для своего списка CPU выберите процессы и ровно столько же процессов, сколько CPU в списке')
            return ExecutionOptions('process',len(selected),self.options.batch_size,tuple(selected),'logical',self.options.ram_mode)
        return execution_options(self.options,self.hardware)

    def configure(self,value):
        self.require_idle()
        cfg=value.get('print',{});settings=PrintSettings(**cfg)
        values={f.name:value.get(f.name,getattr(self.options,f.name)) for f in fields(GenerationPreferences)}
        for key in ('copies_per_value','template_count','workers','batch_size'):values[key]=parse_number(values[key],integer=True)
        options=GenerationPreferences(**values);mode=value.get('mode',self.mode)
        if self.index and hasattr(self.index,'content_kind'):
            self.content_frame(settings)
            if options.copies_per_value>10000:raise ValueError('Для содержимого QR не больше 10 000 экземпляров')
        if not isinstance(options.output_directory,str) or not options.output_directory.strip():raise ValueError('Укажите папку сохранения во вкладке «Путь»')
        if mode not in ('singles','multipage','both'):raise ValueError('Выберите формат файлов')
        if value.get('telemetry','cpu') not in ('cpu','off'):raise ValueError('Режим статистики: cpu/off')
        previous=(self.settings,self.options,self.form,self.mode,self.telemetry)
        try:
            self.settings,self.options,self.mode,self.telemetry=settings,options,mode,value.get('telemetry','cpu')
            self.form={**asdict(options),'mode':mode,'print':asdict(settings),'telemetry':self.telemetry,'manual_cpus':value.get('manual_cpus',[])}
            self.execution()
        except Exception:
            self.settings,self.options,self.form,self.mode,self.telemetry=previous;raise
        if self.approval.signature!=JobApproval.key(self.order()):self.refresh_approval()
        self.save();self.revision+=1
        return self.state()

    def _launch(self,kind,action):
        self.require_idle();self.search_cancel.set();self.busy=True;self.started=time.monotonic();self.finished=None;self.progress=None;self.result=None
        self.cancel=threading.Event();self._stop_nonce=None;self.status='Подготовка · '+kind
        def run():
            try:
                value=action()
                self.events.put(('service_done',{'kind':kind,'value':value}))
            except Exception as exc:self.events.put(('error',f'{type(exc).__name__}: {exc}'))
        self.worker=threading.Thread(target=run,name='ucode-web-'+kind,daemon=False);self.worker.start()

    def load(self,path):
        def task():
            index=SourceIndex.build(path,self.private/'source-indexes',cancel=self.cancel,
                progress=lambda n,total:self.events.put(('status',f'Загрузка TXT · {n:,} строк'.replace(',',' '))))
            self.index=index;self.source_serial+=1;self.name_stamp=None;self.refresh_approval();self.save();return {'count':index.count}
        self._launch('База',task)

    def sequence(self,value,save_as=None,use=True):
        spec=SequenceSpec(value['start'],parse_number(value['count'],integer=True),parse_number(value['step'],integer=True))
        def task():
            path=Path(save_as) if save_as else self.output/'templates'/('sequence-'+uuid.uuid4().hex)/f'codes-{spec.count}.txt'
            path.parent.mkdir(parents=True,exist_ok=True);spec.save(path,cancel=self.cancel)
            if use:
                self.index=SourceIndex.build(path,self.private/'source-indexes',cancel=self.cancel);self.approval.invalidate();self.save()
                self.source_serial+=1;self.name_stamp=None;self.refresh_approval()
            self.ui['sequence']={'start':spec.first,'count':spec.count,'step':spec.step};self.save()
            return {'path':str(path),'count':spec.count,'use':use}
        self._launch('Создание TXT',task)

    def plan(self):
        from .generation_plan import build_plan
        if not self.index:return None
        return build_plan(self.index,copies_per_value=self.options.copies_per_value,duplicate_policy=self.options.duplicate_policy)

    def preflight(self):
        self.require_idle()
        if not self.index:raise ValueError('Сначала откройте базу')
        order=self.order();index=self.index;cfg=self.settings;mode=self.mode;destination=Path(self.options.output_directory).resolve();plan=self.plan()
        if os.name=='nt' and len(str(destination/Path(self.result_name()).stem/self.result_name()))>240:
            raise ValueError('Слишком длинный путь результата. Сократите имя или выберите папку ближе к корню диска.')
        def task():
            from .hardware import probe_directory
            from .engines import get_engine
            if not index.verify_content():raise ValueError('TXT изменился. Откройте его заново.')
            destination.mkdir(parents=True,exist_ok=True);probe=probe_directory(destination);unit=4096
            if hasattr(os,'statvfs'):unit=os.statvfs(destination).f_frsize or 4096
            else:
                import ctypes
                volume=ctypes.create_unicode_buffer(32768);values=[ctypes.c_ulong() for _ in range(4)]
                if ctypes.windll.kernel32.GetVolumePathNameW(str(destination),volume,len(volume)) and ctypes.windll.kernel32.GetDiskFreeSpaceW(volume.value,*[ctypes.byref(v) for v in values]):unit=values[0].value*values[1].value
            import tempfile
            maximum=0;engine=get_engine();cache=self.private/'calibration';cache.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=cache) as temp:
                for n in sorted({1,max(1,index.count//2),index.count}):
                    if self.cancel.is_set():raise InterruptedError('Проверка папки остановлена')
                    target=Path(temp)/f'{n}.pdf'
                    if hasattr(index,'content_kind'):
                        from .qr_content_job import write_content_pdf
                        write_content_pdf(self.content_frame(cfg),target,cfg,cancel=self.cancel)
                    else:
                        frame=get_engine(error_correction=cfg.error_correction).encode([index.row(n)]);engine.write_pdf(frame,target,cfg,cancel=self.cancel)
                    maximum=max(maximum,target.stat().st_size)
            estimate=estimate_space(plan.total_codes,mode,maximum,shutil.disk_usage(destination).free,temp_bytes=plan.unique_values*4096,allocation_unit=unit)
            self.estimate={**asdict(estimate),'sample_page_bytes':maximum,'probe':probe,'enough':estimate.enough}
            if estimate.enough and order==self.order():
                self.confirmed_directory=str(destination);self.approval.approve(order,destination,estimate.required_bytes)
            else:self.approval.invalidate()
            return self.estimate
        self._launch('Проверка папки',task)

    def start(self):
        self.require_idle()
        if not self.index or not self.index.unchanged():raise ValueError('База отсутствует или изменилась. Откройте её заново.')
        destination=Path(self.options.output_directory).resolve()
        if not self.approval.valid(self.order(),destination,shutil.disk_usage(destination).free):raise ValueError('PATH_REQUIRED: проверьте папку для текущего заказа')
        if not self.index.verify_content():self.approval.invalidate();raise ValueError('TXT изменился. Откройте его заново.')
        from .hardware import probe_directory
        probe_directory(destination)
        request={'input':str(self.index.source),'destination':str(destination),'settings':asdict(self.settings),'options':asdict(self.options),
                 'mode':self.mode,'execution':asdict(self.execution()),'telemetry':self.telemetry,'archive':str(self.archive),'output_name':self.result_name()}
        if hasattr(self.index,'content_kind'):request.update(operation='content',payload=self.index.first,content_kind=self.index.content_kind)
        self._host_start(request)

    def _host_start(self,request):
        from .operation_host import OperationHost
        self.require_idle();self.search_cancel.set();self.busy=True;self.result=None;self.progress=None;self.started=time.monotonic();self.finished=None;self._stop_nonce=None
        if request.get('operation')!='audit':self.last_audit=None
        self.status='Запуск собственного процесса…';self.host=OperationHost(self.private/'operations',request,self.events)
        try:self.host.start();self.worker=self.host.thread
        except Exception:self.busy=False;self.host=None;raise

    def pump(self):
        while True:
            try:kind,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='progress':self.progress=value;self.status=value['stage']
            elif kind=='status':self.status=str(value)
            elif kind=='done':
                folder=Path(value);self.result=self.result_data(folder)
                if self.result.get('kind')=='pdf-audit' and self.last_output:
                    original=self.result_data(self.last_output)
                    for key in ('count','files','pages','bytes'):self.result[key]=original[key]
                    self.last_audit=folder
                else:self.last_output=folder
                self.busy=False;self.host=None;self.finished=time.monotonic()
                view=self.result.get('presentation')
                self.status=(view['title']+' · '+view['detail']) if view else 'Создано без проверки' if self.result['status']=='UNVERIFIED' else 'Операция завершена · '+self.result['status']
            elif kind=='service_done':
                self.busy=False;self.finished=time.monotonic();self.status=value['kind']+' · готово';self.revision+=1
            elif kind=='error':
                self.busy=False;self.finished=time.monotonic();self.host=None;self.status=str(value);self.result={'status':'CANCELLED' if 'InterruptedError' in str(value) else 'ERROR','error':str(value)}

    def state(self):
        with self.lock:
            self.pump();index=self.index
            approved=bool(index and index.unchanged() and self.approval.signature==JobApproval.key(self.order()))
            if approved:
                try:approved=self.approval.valid(self.order(),self.options.output_directory,shutil.disk_usage(self.options.output_directory).free)
                except OSError:approved=False
            return {'busy':self.busy,'status':self.status,'revision':self.revision,'progress':self.progress,'result':self.result,
                    'content_kind':getattr(index,'content_kind',None),'matrix_size':self.content_frame().size if index and hasattr(index,'content_kind') else 21,
                    'output_name':self.result_name(),'manual_name':self.manual_name,'source_serial':self.source_serial,
                    'elapsed':max(0,(self.finished or time.monotonic())-self.started) if self.started else 0,
                    'source':{'count':index.count,'first':index.first,'last':index.last,'name':index.source.name,'digest':index.sha256} if index else None,
                    'form':self.form,'ui':self.ui,'hardware':self.hardware,'path_approved':approved,'estimate':self.estimate,
                    'plan':self.plan().to_dict() if index else None}

    def rows(self,page):
        if not self.index:return {'rows':[],'page':1}
        page=max(1,min(self.index.count,int(page)));return {'rows':self.index.rows(max(1,page-5),60),'page':page}

    def search(self,query):
        if not self.index or self.busy:return []
        with self.lock:
            self.search_cancel.set();self.search_cancel=threading.Event();cancel=self.search_cancel;index=self.index
        return index.find(query,cancel=cancel)

    @functools.lru_cache(maxsize=32)
    def preview_frame(self,value,error_correction="M",content=False):
        if content:
            from .qr_content_codec import encode_content
            return encode_content(value,error_correction)
        from .engines import get_engine
        return get_engine(error_correction=error_correction).encode([value])[0]

    def preview_svg(self,page,sample=False):
        if not sample and not self.index:raise ValueError('База не загружена')
        value='500000000000' if sample else self.index.row(max(1,min(self.index.count,int(page))))
        cfg=self.settings;frame=self.preview_frame(value,cfg.error_correction,bool(not sample and self.index and hasattr(self.index,'content_kind')));q=cfg.quiet_modules;side=frame.size+2*q
        def color(ink):
            c,m,y,k=(v/100 for v in ink);return '#'+''.join(f'{round(255*(1-v)*(1-k)):02x}' for v in (c,m,y))
        paper='' if cfg.background_mode=='transparent' else f'<rect width="{side}" height="{side}" fill="{color(cfg.background_ink) if cfg.background_mode=="color" else "#ffffff"}"/>'
        path=''.join(f'M{x+q} {y+q}h1v1h-1z' for y,row in enumerate(frame.matrix) for x,cell in enumerate(row) if cell)
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" shape-rendering="crispEdges">{paper}<path fill="{color(cfg.ink)}" d="{path}"/></svg>'

    def stop_request(self):
        if not self.busy:raise ValueError('Операция уже завершена')
        self._stop_nonce=secrets.token_urlsafe(24);self._stop_at=time.monotonic()
        return {'nonce':self._stop_nonce,'delay':3}

    def stop(self,nonce):
        if not self._stop_nonce or not secrets.compare_digest(str(nonce),self._stop_nonce) or time.monotonic()-self._stop_at<3:
            raise ValueError('Подтверждение остановки ещё недоступно')
        self.cancel.set()
        if self.host:self.host.stop(force=True)
        self.status='Остановка запрошена. Частичные файлы сохраняются.';self._stop_nonce=None

    @staticmethod
    def valid_config(name,value):
        cls=config_types()[name];known={f.name for f in fields(cls)}
        if set(value)-known:raise ValueError('Неизвестные параметры теста: '+', '.join(set(value)-known))
        defaults=asdict(cls());converted={}
        for key,original in defaults.items():
            v=value.get(key,original)
            converted[key]=tuple(v) if isinstance(original,(tuple,list)) else v
        return cls(**converted)

    def test_plan(self,name,value):
        from .test_commands import TestCommand,command_text,preview_command
        cfg=self.valid_config(name,value);kind={'LabConfig':'lab','PipelineConfig':'pipeline','SearchConfig':'search'}[name]
        command=TestCommand(kind,cfg);plan=preview_command(command,self.hardware['cpu'])
        self.lab_configs[name]=asdict(cfg);self.save();return {'plan':plan,'command':command_text(command),'config':asdict(cfg)}

    def start_test(self,operation,value):
        self.require_idle()
        if operation in config_types():
            cfg=self.valid_config(operation,value);self.lab_configs[operation]=asdict(cfg);self.save()
            payload={'operation':operation,'config':asdict(cfg)}
        elif operation=='console':
            from .test_commands import parse_script
            text=value['text'];parse_script(text);payload={'operation':'console','text':text}
        elif operation=='scientific':payload={'operation':operation,'size':value['size'],'methods':value.get('methods')}
        elif operation=='legacy':payload={'operation':operation,'count':int(value.get('count',200)),'action':value.get('action','benchmark'),'methods':value.get('methods')}
        else:raise ValueError('Неизвестный тест')
        self._host_start({**payload,'destination':str(Path(self.options.output_directory)/'tests'),'archive':str(self.archive),'options':{'ram_mode':'max'}})

    @staticmethod
    def result_data(folder):
        from .test_archive import read_test
        try:_,data=read_test(folder)
        except ValueError:
            if not (folder/'inputs.json').is_file():raise
            inputs=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
            data={'kind':'legacy-inputs','status':'COMPLETE' if inputs['qa']['status']=='PASS' else 'INVALID',
                  'count':inputs['config']['count'],'qa':inputs['qa']}
        pdfs=list(folder.glob('*.pdf'));single=folder/'singles'
        if single.exists():pdfs.extend(single.glob('*.pdf'))
        pages=data.get('generation',{}).get('pdf_pages_written')
        if pages is None and data.get('kind')=='legacy-inputs':pages=len(pdfs)
        if pages is None and isinstance(data.get('files'),dict):
            actual=[v.get('pages',v.get('count')) for k,v in data['files'].items() if k in ('multipage','singles')]
            if actual and all(type(n) is int for n in actual):pages=sum(actual)
        presentation=None
        if data.get('cases') or data.get('runs'):
            from .result_presentation import test_outcome
            presentation=test_outcome(data)
        return {'status':data.get('status','UNKNOWN'),'kind':data.get('kind'),'count':data.get('count'),
                'files':len(pdfs),'pages':pages,'bytes':sum(p.stat().st_size for p in pdfs),'seconds':data.get('seconds'),
                'elapsed_seconds':data.get('elapsed_seconds'),'qa':data.get('qa'),'runtime_statistics':data.get('runtime_statistics'),
                'data':{'kind':data.get('kind'),'case_count':len(data['cases']) if isinstance(data.get('cases'),list) else None,
                        'run_count':len(data['runs']) if isinstance(data.get('runs'),list) else None},'presentation':presentation}

    def archive_rows(self):
        from .test_archive import archive_rows
        return archive_rows(self.archive,limit=1000)

    def open_file(self,path):
        path=Path(path)
        if not path.exists():raise ValueError('Файл ещё не создан')
        if path.suffix.lower() in ('.html','.htm'):
            from .open_reports import open_html_report
            open_html_report(path)
        elif os.name=='nt':os.startfile(str(path.resolve()))
        else:
            import webbrowser
            webbrowser.open(path.resolve().as_uri())

    def result_action(self,action):
        if not self.last_output:raise ValueError('Сначала создайте результат')
        folder=self.last_output
        if action=='folder':self.open_file(folder);return
        if action in ('png','svg','payload'):
            self.open_file(folder/{'png':'qr.png','svg':'qr.svg','payload':'payload.txt'}[action]);return
        if action=='pdf':
            path=next(folder.glob('*.pdf'),None) or next(folder.glob('singles/*.pdf'),None)
            if path is None:
                # Test workers keep their PDFs under trial job folders.
                path=next(folder.rglob('all-*-pages.pdf'),None)
        else:path=next((folder/n for n in ('production.html','commands.html','pipeline.html','pc-search.html','lab.html','scientific.html','report.html','ОТЧЁТ.txt') if (folder/n).exists()),None)
        if path is None:raise ValueError('Этот результат не содержит выбранный файл')
        self.open_file(path)
