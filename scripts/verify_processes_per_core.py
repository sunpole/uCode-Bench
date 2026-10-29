"""Tiny genuine pools/QA; 14/28/70/140-process matrix is planned, never run."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from ucode.batch import _make_directory
    from ucode.pipeline_plan import PipelineConfig
    from ucode.pipeline_lab import run_pipeline_lab
    from ucode.test_archive import archive_scope,archive_rows
    from ucode.lab_worker import atomic_json,code_fingerprint
    from ucode.hardware import inspect_cpu,memory_info
    from ucode.test_commands import parse_command,preview_command
    from ucode.pipeline_memory import memory_plan
    root=Path(__file__).resolve().parents[1];folder=_make_directory(root/'output/processes-core-proof','small')
    cpu=inspect_cpu();cores=cpu['available_physical']
    allocations=('physical:1:0','physical:1:1') if cores>=2 else ('physical:1:0',)
    cfg=PipelineConfig(counts=(4,),allocations=allocations,schedules=('queue',),batches=(1,),repeats=1,
        qa_mode='full',telemetry_modes=('cpu',),processes_per_cpu=(1,2),timeline_mode='on')
    with archive_scope(folder/'archive'):run=run_pipeline_lab(folder/'runs',cfg)
    data=json.loads((run/'pipeline.json').read_text(encoding='utf-8'))
    assert data['status']=='COMPLETE',data.get('errors')
    assert len(data['cases'])==2*len(allocations)
    assert len(archive_rows(folder/'archive'))==1
    assert not list((folder/'archive').rglob('*.pdf'))
    real=[];baseline=None
    for case in data['cases']:
        trial=case['trials'][0];info=trial['manifest']['execution']
        assert trial['manifest']['qa']['multipage']['status']=='PASS'
        assert len(info['worker_pids'])==case['workers']
        real.append({'allocation':case['allocation'],'factor':case['processes_per_cpu'],'confirmed_processes':len(info['worker_pids']),
                     'used_processes':sum(v['pages']>0 for v in info['worker_tasks'].values()),'qa':'PASS'})
        if case['processes_per_cpu']==2:baseline=info['memory_startup_observation']['baseline_bytes']
    text=f'test pipeline --codes 10000 --split cores:{cores}+0 --processes-per-core 1,2,5,10 --schedule queue --batch 32 --repeats 2 --metrics cpu --ram max --pdf compact --qa off --xy on'
    plan=preview_command(parse_command(text),cpu)
    assert plan['runs']==8 and plan['skipped']==0,plan
    (folder/'commands-10000.txt').write_text(text+'\n',encoding='utf-8')
    estimates={str(f):memory_plan(10000,cores*f,32,baseline if f>1 else None) for f in (1,2,5,10)}
    atomic_json(folder/'planned-memory.json',{'scope':'Estimate from ONE startup observation, not measured multi-process peaks','available_ram':memory_info()['available_bytes'],'plans':estimates})
    proof={'kind':'processes-per-core-verification','source_digest':code_fingerprint(),'scope':'Small PDFs, max4pages/4pool-processes; no 10000/70/140-process run',
           'real':real,'planned_runs':8,'planned_processes':plan['processes'],'archive_without_pdf':True,'command':text}
    atomic_json(folder/'verification.json',proof)
    public=root/'results/processes-per-core';public.mkdir(parents=True,exist_ok=True);atomic_json(public/'verification.json',proof)
    print(json.dumps({'folder':str(folder),'report':str(run/'pipeline.html'),'command_file':str(folder/'commands-10000.txt'),'plan':plan},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
