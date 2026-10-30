"""Private worker entry point. Only OperationHost creates its request and go files."""
import json
import os
from pathlib import Path
import sys
import threading
import time


def main(argv=None):
    from .batch import run_batch
    from .print_settings import PrintSettings,human_report
    from .execution import ExecutionOptions
    from .hardware import inspect_cpu,memory_info
    from .resource_monitor import TreeMonitor,ram_budget
    from .cpu_telemetry import CPUTrace
    from .test_archive import write_text_report,archive_test
    from .lab_worker import atomic_json
    args=sys.argv[1:] if argv is None else argv
    request_path=Path(args[0]).resolve();folder=request_path.parent
    deadline=time.monotonic()+15
    while not (folder/'go').exists():
        if time.monotonic()>deadline:raise RuntimeError('Worker start was not authorized by its host')
        time.sleep(.02)
    request=json.loads(request_path.read_text(encoding='utf-8'));options=request['options']
    lock=threading.Lock()
    def send(kind,value):
        with lock:print(json.dumps({'kind':kind,'value':value},ensure_ascii=False),flush=True)
    cancel=threading.Event();watch_stop=threading.Event()
    def watch():
        while not watch_stop.wait(.1):
            if (folder/'cancel').exists():cancel.set();return
    watcher=threading.Thread(target=watch,name='ucode-cancel-file',daemon=True);watcher.start()
    if request.get('operation')=='content':
        from .qr_content_job import run_content_job
        try:
            result=run_content_job(request,cancel,send);send('done',str(result));return 0
        finally:watch_stop.set();watcher.join(1)
    if request.get('operation','generate')!='generate':
        from .operator_test_worker import run
        try:return run(request,cancel,send)
        finally:watch_stop.set();watcher.join(1)
    execution=ExecutionOptions(**{**request['execution'],'cpus':tuple(request['execution'].get('cpus',()))})
    settings=PrintSettings(**request['settings']);monitor=None;trace=None;last_event=None;telemetry=None;last_disk_check=0
    if request.get('telemetry','cpu')=='cpu':
        cpus=list(execution.cpus) or inspect_cpu()['available_cpus'][:execution.workers]
        trace=CPUTrace(cpus,folder/'cpu-samples.csv',interval=.5)
        monitor=TreeMonitor(cancel,ram_budget(options.get('ram_mode','max'),memory_info()['available_bytes']),interval=.5,telemetry=trace).start()
    def observe(event):
        nonlocal last_event,last_disk_check
        if time.monotonic()-last_disk_check>=1:
            import shutil
            last_disk_check=time.monotonic()
            if shutil.disk_usage(request['destination']).free<256*1024**2:
                raise OSError('На диске осталось меньше 256 МиБ. Запись остановлена; частичные файлы сохранены.')
        if trace:trace.set_phase(event['stage'])
        if monitor:
            event={**event,'live_resources':dict(monitor.data)}
            if trace:
                with trace.lock:
                    group=trace.groups.get('Вся операция')
                    event['live_resources']['cpu_load_pct']=group['load'].data() if group else None
        if event.get('percent')==100:last_event=event
        else:send('progress',event)
    def execution_seen(value):
        if trace:trace.bind(value)
    try:
        result=run_batch(Path(request['input']),Path(request['destination']),mode=request['mode'],settings=settings,cancel=cancel,
            execution=execution,qa_mode=options['qa_mode'],activity=options['activity'],timeline_mode=options['timeline_mode'],
            copies_per_value=options['copies_per_value'],duplicate_policy=options['duplicate_policy'],
            events=observe,progress=lambda text:send('status',text),execution_observer=execution_seen)
        if request.get('output_name'):
            from .order_output import publish_job
            result=publish_job(result,request['output_name'])
        if monitor:telemetry=monitor.finish();monitor=None
        manifest=json.loads((result/'manifest.json').read_text(encoding='utf-8'))
        manifest['seconds']['launcher_wall']=time.perf_counter()-request['launcher_started']
        manifest['timing_scope']='launcher_wall: host launch through completed generation, selected QA and resource monitor; final HTML/archive serialization excluded'
        manifest['runtime_statistics']=telemetry or {'status':'DISABLED','scope':'Detailed resource sampling disabled by the operator'}
        atomic_json(result/'manifest.json',manifest)
        atomic_json(result/'runtime-statistics.json',manifest['runtime_statistics'])
        if trace:
            import shutil
            shutil.copyfile(folder/'cpu-samples.csv',result/'cpu-samples.csv')
        (result/'ОТЧЁТ.txt').write_text(human_report(manifest),encoding='utf-8')
        write_text_report(result/'production.html',manifest,'uCode — создание PDF и подробная статистика')
        archive_test(result,Path(request['archive']))
        if last_event:send('progress',last_event)
        send('done',str(result));return 0
    finally:
        watch_stop.set();watcher.join(1)
        if monitor:monitor.finish()


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'kind':'error','value':f'{type(exc).__name__}: {exc}'},ensure_ascii=False),flush=True)
        raise
