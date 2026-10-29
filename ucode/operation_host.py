"""Owned production process and child-tree containment; GUI never runs the encoder."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid


class OperationHost:
    def __init__(self,root,request,events):
        self.folder=Path(root)/('operation-'+uuid.uuid4().hex);self.folder.mkdir(parents=True)
        self.request=request;self.events=events;self.process=None;self.thread=None
        self.job=None;self.lock=threading.Lock();self.stopped=False;self.stderr=None
        self.cancel_path=self.folder/'cancel';self.go_path=self.folder/'go'

    def start(self):
        from .hardware import memory_info
        from .resource_monitor import ram_budget,create_owned_job
        budget=ram_budget(self.request['options'].get('ram_mode','max'),memory_info()['available_bytes'])
        self.request['launcher_started']=time.perf_counter()
        request=self.folder/'request.json';request.write_text(json.dumps(self.request,ensure_ascii=False),encoding='utf-8')
        env={**os.environ,'PYTHONUTF8':'1','PYTHONUNBUFFERED':'1'}
        self.stderr=(self.folder/'stderr.log').open('xb')
        options={'stdout':subprocess.PIPE,'stderr':self.stderr,'stdin':subprocess.DEVNULL,
                 'text':True,'encoding':'utf-8','errors':'replace','env':env}
        if os.name=='nt':options['creationflags']=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP
        else:options['start_new_session']=True
        try:
            self.process=subprocess.Popen([sys.executable,'-m','ucode.operation_worker',str(request)],**options)
            if os.name=='nt':self.job=create_owned_job(budget['budget_bytes'],process_handle=int(self.process._handle))
            self.go_path.touch(exist_ok=False)
        except BaseException:
            if self.process and self.process.poll() is None:self.process.terminate();self.process.wait(5)
            self.stderr.close();raise
        self.thread=threading.Thread(target=self.observe,name='ucode-operation-host',daemon=False);self.thread.start()

    def _close_job(self):
        from .resource_monitor import close_owned_job
        with self.lock:handle,self.job=self.job,None
        if handle is not None:close_owned_job(handle)

    def observe(self):
        result=None
        try:
            for line in self.process.stdout:
                if len(line)>256*1024:continue
                try:message=json.loads(line)
                except ValueError:continue
                kind=message.get('kind');value=message.get('value')
                if kind in ('status','progress'):self.events.put((kind,value))
                elif kind=='done':result=value
                elif kind=='error':self.events.put(('status',value))
            code=self.process.wait()
            if result and code==0:
                destination=Path(self.request['destination']).resolve();folder=Path(result).resolve()
                if not folder.is_relative_to(destination):raise ValueError('Worker returned an unexpected output folder')
                self.events.put(('done',folder))
            elif self.stopped:self.events.put(('error','InterruptedError: операция принудительно остановлена; частичные файлы сохранены'))
            else:
                tail=(self.folder/'stderr.log').read_text(encoding='utf-8',errors='replace')[-2000:]
                self.events.put(('error',f'Процесс генерации завершился с кодом {code}: {tail}'))
        except Exception as exc:self.events.put(('error',f'{type(exc).__name__}: {exc}'))
        finally:
            self.process.stdout.close();self.stderr.close();self._close_job()

    def stop(self,*,force=False):
        self.stopped=True;self.cancel_path.touch(exist_ok=True)
        if not force or not self.process or self.process.poll() is not None:return
        if os.name=='nt':self._close_job()
        else:
            try:
                if os.getpgid(self.process.pid)==self.process.pid:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
