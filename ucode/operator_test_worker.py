"""Existing lab contracts, executed under the same owned process host as production."""
from pathlib import Path


def run(request,cancel,send):
    from .test_archive import archive_scope
    root=Path(request['destination']);operation=request['operation']
    events=lambda value:send('progress',value)
    with archive_scope(request['archive']):
        if operation in ('LabConfig','PipelineConfig','SearchConfig'):
            from .operator_service import OperatorService
            cfg=OperatorService.valid_config(operation,request['config'])
            if operation=='LabConfig':
                from .resource_lab import run_lab
                folder=run_lab(root/'laboratory',cfg,cancel=cancel,events=events,progress=lambda s:send('status',s),report_only=True)
            elif operation=='PipelineConfig':
                from .pipeline_lab import run_pipeline_lab
                folder=run_pipeline_lab(root/'pipeline',cfg,cancel=cancel,events=events,report_only=True)
            else:
                from .pc_search import run_search
                folder=run_search(root/'search',cfg,cancel=cancel,events=events,report_only=True)
        elif operation=='console':
            from .test_commands import run_script
            folder=run_script(request['text'],root/'console',cancel=cancel,events=events)
        elif operation=='scientific':
            from .scientific import run_scientific
            folder=run_scientific(root/'scientific',request['size'],methods=request.get('methods'),cancel=cancel,events=events,progress=lambda s:send('status',s))
        elif operation=='audit':
            from .audit import audit_job
            from .test_archive import archive_test
            import json
            from .lab_worker import atomic_json
            folder=audit_job(request['source_job'],cancel=cancel,events=events,progress=lambda s:send('status',s))
            data=json.loads((folder/'audit.json').read_text(encoding='utf-8'))
            original=json.loads((Path(request['source_job'])/'manifest.json').read_text(encoding='utf-8'))
            data['count']=original['count'];atomic_json(folder/'audit.json',data)
            archive_test(folder)
        elif operation=='legacy':
            from .benchmark import create_inputs,run_experiment
            from .config import Experiment
            from .test_archive import archive_test
            count=request['count']
            if count not in (2,200,1000):raise ValueError('Исходная лаборатория: 200 или 1000')
            methods=request.get('methods')
            if count==1000:
                from .benchmark import load_qualifying_methods
                candidates=sorted(root.glob('legacy/*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)
                methods=None
                for path in candidates:
                    try:methods=load_qualifying_methods(path)
                    except (ValueError,OSError,KeyError,TypeError):continue
                    if methods:break
                if not methods:raise ValueError('Сначала требуется QA PASS и допуск после 200')
            kwargs={'cancel':cancel,'progress':lambda s:send('status',s)}
            if request.get('action')=='create':folder=create_inputs(root/'legacy',Experiment(count=count),**kwargs)
            else:
                folder=run_experiment(root/'legacy',Experiment(count=count),allowed_methods=methods,events=events,**kwargs)
                archive_test(folder)
        else:raise ValueError('Неизвестная операция теста')
    send('done',str(folder));return 0
