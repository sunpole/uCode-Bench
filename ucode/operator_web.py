"""Approved HTML renderer + loopback-only API. No web framework or internet required."""
from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit,parse_qs

from .operator_service import OperatorService,native_dialog
from . import __version__

ASSETS=Path(__file__).parent/'assets'
APPROVED_SHA256='b86287a4413e4e32b51a46a6ca8b8c1a7278d627b0d4b0ee97612992e9bd863a'


def document(token):
    raw=(ASSETS/'operator-approved.html').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=APPROVED_SHA256:raise ValueError('Утверждённый дизайн изменён; проверьте SHA256')
    source=raw.decode('utf-8')
    # Keep every approved style block and all layout construction. Only data and
    # actions are connected. The original immutable file is shipped byte-for-byte.
    source=re.sub(r'<script\b[^>]*\bsrc=[^>]*>\s*</script>','',source,flags=re.I)
    old="code=i=>(BigInt(state.start)+BigInt(i-1)*BigInt(state.step)).toString().padStart(12,'0')"
    replacement="code=i=>window.UCODE_RUNTIME?(window.ucodeRows?.[i]||''):(BigInt(state.start)+BigInt(i-1)*BigInt(state.step)).toString().padStart(12,'0')"
    if source.count(old)!=1:raise ValueError('Не найдена точка подключения реальных строк')
    source=source.replace(old,replacement)
    marker="activateTab(1);render();$('uc-type-qr').innerHTML="
    if source.count(marker)!=1:raise ValueError('Не найдена точка подключения интерфейса')
    bridge=(ASSETS/'operator-bridge.js').read_text(encoding='utf-8')
    source=source.replace(marker,bridge+'\n'+marker)
    source=source.replace('<script>','<script nonce="'+token+'">')
    prefix='<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>uCode 0.3.0</title><style>html,body{margin:0;background:#0b1220;color:#edf4fc}body{padding:8px;box-sizing:border-box}*{box-sizing:border-box}</style></head><body><script nonce="'+token+'">window.UCODE_RUNTIME=true;window.ucodeRows={};</script>'
    controls=(ASSETS/'operator-controls.js').read_text(encoding='utf-8')
    prefix=prefix.replace('<title>uCode 0.3.0</title>',f'<title>uCode {__version__}</title>')
    constraints=(ASSETS/'operator-window.css').read_text(encoding='utf-8')
    return (prefix+'<script nonce="'+token+'">'+controls+'</script>'+source+'<style>'+constraints+'</style></body></html>').encode('utf-8')


class OperatorHTTP(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,root,address=('127.0.0.1',0)):
        self.service=OperatorService(root);self.token=secrets.token_urlsafe(32);self.last_seen=time.monotonic()
        super().__init__(address,Handler)
        self.origin=f'http://127.0.0.1:{self.server_port}';self.base=self.origin+'/'+self.token+'/'
        self.project_digest=hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass  # URLs contain a local capability, never log it.
    def send(self,value,status=200,content_type='application/json; charset=utf-8'):
        raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,default=str).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'nonce-"+self.server.token+"'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def authorized(self):
        parsed=urlsplit(self.path);prefix='/'+self.server.token+'/'
        if self.headers.get('Host')!=urlsplit(self.server.origin).netloc or not parsed.path.startswith(prefix):
            self.send({'error':'Недоступный адрес'},403);return None
        if self.headers.get('Origin') not in (None,self.server.origin):
            self.send({'error':'Недопустимый источник запроса'},403);return None
        self.server.last_seen=time.monotonic()
        return parsed.path[len(prefix):],parse_qs(parsed.query)
    def do_GET(self):
        target=self.authorized()
        if target is None:return
        route,args=target;s=self.server.service
        try:
            if route=='':self.send(document(self.server.token),content_type='text/html; charset=utf-8')
            elif route=='api/health':self.send({'application':'uCode','version':__version__,'project':self.server.project_digest})
            elif route=='api/state':self.send(s.state())
            elif route=='api/rows':self.send(s.rows(int(args.get('page',['1'])[0])))
            elif route=='api/search':self.send({'rows':s.search(args.get('q',[''])[0])})
            elif route=='api/preview':self.send(s.preview_svg(int(args.get('page',['1'])[0]),args.get('sample',['0'])[0]=='1').encode(),content_type='image/svg+xml')
            elif route=='api/configs':self.send(s.lab_configs)
            elif route=='api/archive':
                from .test_archive import KINDS,STATES
                self.send([{**r,'kind_title':KINDS.get(r['kind'],r['kind']),'status_title':STATES.get(r['status'],r['status'])} for r in s.archive_rows()])
            elif route=='api/history':self.send(self.history())
            elif route=='api/help':
                from .operator_help import TOPICS
                from .help_content import CONTACTS
                self.send({'topics':TOPICS,'contacts':CONTACTS})
            elif route=='api/commands-help':
                from .test_commands import parser_for
                self.send({'text':'\n\n'.join(parser_for(kind).format_help() for kind in ('lab','pipeline','search'))+'\n\ntest scientific --codes 200|1000|10000|all --mergers all|pypdf|qpdf...\n\nПолное описание: docs/TEST_COMMANDS.md'})
            else:self.send({'error':'Не найдено'},404)
        except (ValueError,KeyError,TypeError,OSError) as exc:self.send({'error':str(exc)},400)
    def do_POST(self):
        target=self.authorized()
        if target is None:return
        if self.headers.get('X-UCode-Token')!=self.server.token or self.headers.get_content_type()!='application/json':
            self.send({'error':'Нужен ключ локального интерфейса и JSON'},403);return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=1024*1024:raise ValueError('Запрос должен быть не больше 1 МиБ; TXT выбирается через Проводник')
            value=json.loads(self.rfile.read(length));route=target[0].removeprefix('api/')
            if not isinstance(value,dict):raise ValueError('Нужен объект JSON')
            with self.server.service.lock:result=self.action(route,value)
            self.send(result if result is not None else self.server.service.state())
        except (ValueError,KeyError,TypeError,OSError) as exc:self.send({'error':str(exc)},400)
        except Exception as exc:self.send({'error':type(exc).__name__+': '+str(exc)},500)
    def action(self,route,value):
        s=self.server.service
        if route not in ('stop-request','stop','ui'):s.require_idle()
        if route=='configure':return s.configure(value)
        if route=='output-name':
            s.set_output_name(value.get('name',''),value.get('automatic',False));return s.state()
        if route=='ui':
            for key in ('theme','rowFont','allowSelect','statisticsOpen'):
                if key in value:s.ui[key]=value[key]
            s.save();return {'saved':True}
        if route=='dialog':
            s.require_idle();kind=value.get('kind','source')
            def choose():
                path=native_dialog('folder' if kind in ('folder','history','import') else 'open',s.options.output_directory)
                if not path:return
                if kind=='source':
                    from .operator_models import SourceIndex
                    s.index=SourceIndex.build(path,s.private/'source-indexes',cancel=s.cancel);s.source_serial+=1;s.name_stamp=None;s.refresh_approval();s.save()
                elif kind=='folder':
                    from dataclasses import replace
                    s.options=replace(s.options,output_directory=path);s.form['output_directory']=path;s.approval.invalidate();s.save()
                elif kind=='history':s.history_root=Path(path)
                else:
                    from .test_archive import import_tests
                    return import_tests(path,s.archive,cancel=s.cancel)
            s._launch('Выбор '+kind,choose)
        elif route=='sequence':
            if value.get('save'):
                spec=dict(value)
                # The dialog is user driven; generation itself stays asynchronous.
                def save():
                    from .operator_models import SequenceSpec,parse_number
                    path=native_dialog('save',s.options.output_directory)
                    if path:SequenceSpec(spec['start'],parse_number(spec['count'],integer=True),parse_number(spec['step'],integer=True)).save(Path(path),cancel=s.cancel)
                s._launch('Сохранение TXT',save)
            else:s.sequence(value)
        elif route=='preflight':s.preflight()
        elif route=='generate':s.start()
        elif route=='stop-request':return s.stop_request()
        elif route=='stop':s.stop(value['nonce'])
        elif route=='test-plan':return s.test_plan(value['name'],value['config'])
        elif route=='test-start':s.start_test(value['name'],value.get('config',{}))
        elif route=='console-plan':
            from .test_commands import parse_script,preview_command,command_text
            commands=parse_script(value['text'])
            return {'commands':[{'kind':c.kind,'config':asdict(c.config) if hasattr(c.config,'__dataclass_fields__') else c.config,
                                 'plan':preview_command(c,s.hardware['cpu']),'text':command_text(c)} for c in commands]}
        elif route in ('console-load','console-save'):
            path=native_dialog('save' if route=='console-save' else 'open',s.root)
            if not path:return {'text':None}
            p=Path(path)
            if route=='console-save':
                if p.exists():raise ValueError('Файл уже существует. Выберите новое имя, чтобы сохранить старые команды.')
                p.write_text(value['text'],encoding='utf-8');return {'saved':True}
            if p.stat().st_size>512*1024:raise ValueError('Файл команд больше 512 КиБ')
            return {'text':p.read_text(encoding='utf-8-sig')}
        elif route=='result':
            s.require_idle()
            if value['action']=='report' and getattr(s,'last_audit',None):s.open_file(s.last_audit/'ОТЧЁТ.txt')
            else:s.result_action(value['action'])
        elif route=='archive-action':return self.archive_action(value)
        elif route=='history-action':return self.history_action(value)
        elif route=='history-own':
            if hasattr(s,'history_root'):del s.history_root
            return {'ok':True}
        elif route=='resources':
            from .hardware import inspect_hardware
            s._launch('Сведения о ПК',lambda:setattr(s,'hardware',inspect_hardware(s.root)))
        elif route=='probe':
            from .hardware import probe_directory
            p=Path(s.options.output_directory);p.mkdir(parents=True,exist_ok=True)
            result=probe_directory(p);s.status=json.dumps(result,ensure_ascii=False);return result
        elif route=='engines':
            from .mergers import available_adapters
            from .engines import available_engines
            return {'generators':[e.to_dict() for e in available_engines()], 'mergers':[{'name':a.name,**a.probe()} for a in available_adapters()]}
        elif route=='help':
            from .help_report import write_help
            from .operator_help import TOPICS
            s.open_file(write_help(s.output,s.hardware,topics=TOPICS))
        elif route=='audit':
            if s.last_output is None:raise ValueError('Сначала создайте PDF')
            s._host_start({'operation':'audit','source_job':str(s.last_output),'destination':str(s.last_output),
                           'archive':str(s.archive),'options':{'ram_mode':'max'}})
        elif route=='reset':
            from dataclasses import replace
            from .affinity import select_cpus
            s.require_idle();s.settings=__import__('ucode.print_settings',fromlist=['PrintSettings']).PrintSettings(pdf_profile='compact')
            unit='physical' if s.hardware['cpu'].get('available_physical') else 'logical'
            s.options=replace(s.options,cpu_unit=unit,cpu_choice='all',execution_backend='process',workers=len(select_cpus(s.hardware['cpu'],unit,'all')),
                              qa_mode='deferred',activity='minimal',ram_mode='max',timeline_mode='on')
            s.form={**asdict(s.options),'print':asdict(s.settings),'mode':'multipage','telemetry':'cpu','manual_cpus':[]};s.mode='multipage';s.telemetry='cpu';s.approval.invalidate();s.save()
        elif route=='shutdown':
            s.require_idle();s.closed=True
        else:raise ValueError('Неизвестное действие')
    def archive_action(self,value):
        s=self.server.service;s.require_idle();action=value['action']
        if action=='folder':s.archive.mkdir(parents=True,exist_ok=True);s.open_file(s.archive);return
        if action=='index':s.open_file(s.archive/'index.html');return
        if action=='graph-json':
            path=native_dialog('json',s.archive)
            if path:
                from .graphical_report import write_graphical_copy
                s.open_file(write_graphical_copy(path,s.output/'graphical-reports'))
            return
        row=next((r for r in s.archive_rows() if r['id']==value.get('id')),None)
        if row is None:raise ValueError('Выберите запись архива')
        path=(s.archive/row['file']).resolve()
        if not path.is_relative_to(s.archive.resolve()):raise ValueError('Неверная ссылка архива')
        if action=='graph':
            from .graphical_report import write_graphical_copy
            s.open_file(write_graphical_copy(path.with_name('report.json'),s.output/'graphical-reports'))
        else:s.open_file(path.parent if action=='entry-folder' else path)
    def history(self):
        s=self.server.service
        from .history import scan_history
        roots=[s.history_root] if hasattr(s,'history_root') else list(dict.fromkeys([Path(s.options.output_directory)/'laboratory',Path(s.options.output_directory)/'tests'/'laboratory',s.output/'jobs'/'laboratory',s.output/'jobs'/'web-tests'/'laboratory']))
        rows=[];limited=False
        for root in roots:
            scanned=scan_history(root);limited=limited or scanned['limited']
            for entry in scanned['entries']:
                ident=hashlib.sha256(str(entry.path).encode()).hexdigest();s.history_paths[ident]=entry.path
                rows.append({**asdict(entry),'id':ident,'path':entry.path.name})
        return {'entries':rows,'limited':limited,'root':', '.join(map(str,roots))}
    def history_action(self,value):
        s=self.server.service;s.require_idle();path=s.history_paths.get(value.get('id'))
        if path is None:raise ValueError('Выберите запуск истории')
        from .history import read_run,pdf_for_case
        if value['action']=='details':return read_run(path)
        if value['action']=='folder':s.open_file(path.parent)
        elif value['action']=='pdf':
            run=read_run(path);case=next((c for c in run['data']['cases'] if c.get('id')==value.get('case')),None)
            if case is None:raise ValueError('Выберите конкретный замер')
            target=pdf_for_case(path,case)
            if target is None:raise ValueError('В замере нет PDF')
            s.open_file(target)
        else:s.open_file(path.with_suffix('.html'))


def _runtime_lock(path):
    stream=Path(path).open('a+b')
    try:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return stream
    except OSError:stream.close();return None


def main(root=None,open_browser=True,presenter=None):
    import webbrowser
    from urllib.request import urlopen
    project=Path(root or Path.cwd()).resolve();private=project/'.local-state';private.mkdir(parents=True,exist_ok=True)
    state_file=private/'web-runtime.json';digest=hashlib.sha256(str(project.resolve()).encode()).hexdigest()
    try:
        previous=json.loads(state_file.read_text(encoding='utf-8'));url=previous['url']
        parsed=urlsplit(url)
        if parsed.hostname=='127.0.0.1' and parsed.scheme=='http':
            with urlopen(url+'api/health',timeout=1) as response:live=json.load(response)
            if live.get('project')==digest and live.get('application')=='uCode':
                if presenter:presenter(url)
                elif open_browser:webbrowser.open(url)
                return
    except (OSError,ValueError,KeyError):pass
    lease=_runtime_lock(private/'web-runtime.lock')
    if lease is None:
        # A second double click during initialization must not create another
        # generator/session. The launcher can be retried after startup completes.
        raise RuntimeError('uCode уже запускается. Подождите несколько секунд и повторите запуск для подключения.')
    try:server=OperatorHTTP(project)
    except BaseException:lease.close();raise
    from .lab_worker import atomic_json
    atomic_json(state_file,{'url':server.base,'pid':os.getpid(),'project':digest})
    server.timeout=.5
    if presenter:
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:presenter(server.base)
        finally:
            server.service.cancel.set();server.service.search_cancel.set()
            host=server.service.host
            if host:host.stop(force=True)
            worker=server.service.worker
            if worker:worker.join(10)
            server.shutdown();thread.join(5);server.server_close();lease.close()
        return
    if open_browser:webbrowser.open(server.base)
    try:
        while not server.service.closed:
            server.handle_request();server.service.pump()
            # Closing a browser never kills a running generator. Reopening the
            # launcher reconnects to this session. An idle abandoned session exits.
            if not server.service.busy and time.monotonic()-server.last_seen>60:break
    finally:server.server_close();lease.close()


if __name__=='__main__':main()
