"""Small integration proof; no PDF exceeds seven pages, no speed extrapolation."""
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from ucode.batch import run_batch,_make_directory
    from ucode.affinity import select_cpus,cpu_keys
    from ucode.audit import audit_job
    from ucode.execution import ExecutionOptions
    from ucode.hardware import inspect_cpu
    from ucode.print_settings import PrintSettings
    from ucode.resource_lab import LabConfig,run_lab
    from ucode.pc_search import SearchConfig,run_search
    from ucode.performance_catalog import inspect_catalog
    folder=_make_directory(ROOT/"output/core-controls-proof","small")
    cpu=inspect_cpu(); maximum=cpu.get("available_physical") or 0
    if maximum<2: raise RuntimeError("Для этой проверки нужны два доступных физических ядра")
    source=folder/"codes.txt"; source.write_text(''.join(f'{200000000000+i}\n' for i in range(7)),encoding='utf-8')
    value={"scope":"Small PDFs only; no sustained 14-core or large-workload throughput proof","production":[]}
    for n in (1,2):
        mask=tuple(select_cpus(cpu,"physical",n))
        job=run_batch(source,folder/"production",mode="multipage",settings=PrintSettings(pdf_profile="compact"),
                      execution=ExecutionOptions("process",n,1,mask,ram_mode="max"),qa_mode="deferred",activity="minimal",force_disk=True)
        m=json.loads((job/"manifest.json").read_text(encoding="utf-8"))
        assert m['status']=='UNVERIFIED' and m['seconds']['quality_checks']==0,m
        assert len(m['execution']['worker_pids'])==n,m['execution']
        assert {tuple(cpu_keys(c)) for c in m['execution']['worker_affinity'].values()}=={tuple(cpu_keys([c])) for c in mask}
        assert not list(job.rglob('cpu-samples.csv'))
        audit=audit_job(job)
        qa=json.loads((audit/'audit.json').read_text(encoding='utf-8')); assert qa['status']=='COMPLETE',qa
        value['production'].append({'cpus':n,'folder':str(job.relative_to(folder)),'qa':m['status'],'separate_audit':qa['status'],'seconds':m['seconds']})
        print('Production',n,'cores: no QA, independent audit PASS',flush=True)
    config=LabConfig(counts=(3,),cpu_counts=('1','2'),cpu_units=('physical',),backends=('process',),ram_modes=('auto',),
                     repeats=3,batch_size=1,pdf_profiles=('compact',),activity_modes=('minimal',),qa_mode='deferred',telemetry_modes=('off','cpu'))
    lab=run_lab(folder/'laboratory',config)
    data=json.loads((lab/'lab.json').read_text(encoding='utf-8'))
    assert data['status']=='UNVERIFIED',data['errors']
    assert len(data['cases'])==4 and sum(len(c['trials']) for c in data['cases'])==12
    assert len(data['telemetry_overhead_pairs'])==2
    assert all(t['seconds']['quality_checks']==0 for c in data['cases'] for t in c['trials'])
    for c in data['cases']:
        for t in c['trials']:
            assert (Path(t['runtime_code_root'])==lab/'.runtime')
            assert ('cpu_telemetry' in t['memory'])==(c['telemetry_mode']=='cpu')
    value['lab']={'folder':str(lab.relative_to(folder)),'cases':4,'trials':12,'status':data['status'],'overhead_pairs':data['telemetry_overhead_pairs']}
    print('Lab: 12/12 small trials, CPU on/off recorded',flush=True)
    config=SearchConfig(counts=(2,),repeats=1,cpu_counts=('1','2'),all_cpu_counts=False,backends=('serial',),
                        batches=(1,),pdf_profiles=('compact',),activities=('minimal',),part_counts=(2,),qa_mode='full')
    search=run_search(folder/'search',config)
    data=json.loads((search/'pc-search.json').read_text(encoding='utf-8'))
    bad=[(c['id'],c.get('merger'),c['status'],c.get('reason')) for c in data['cases'] if c['status'] not in ('PASS','SKIPPED')]
    assert data['status']=='COMPLETE' and not bad,(data['status'],data['errors'],bad)
    assert len(data['cases'])==23
    value['search']={'folder':str(search.relative_to(folder)),'status':data['status'],'cases':len(data['cases']),
                     'statuses':[(c['id'],c.get('merger','direct'),c['status']) for c in data['cases']],
                     'source_digest':data['source_digest']}
    (folder/'verification.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Search: all selected engines through frozen code PASS; evidence:',folder,flush=True)
    return 0


if __name__=='__main__': raise SystemExit(main())
