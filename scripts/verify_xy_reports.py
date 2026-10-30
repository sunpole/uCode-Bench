"""Small retained XY proof; no large workloads, no screenshots."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from ucode.batch import _make_directory,run_batch
    from ucode.test_commands import run_script
    from ucode.test_archive import archive_scope,archive_rows,write_text_report
    from ucode.graphical_report import chart_model,write_graphical_copy
    from ucode.print_settings import PrintSettings
    from ucode.lab_worker import code_fingerprint,atomic_json
    root=Path(__file__).resolve().parents[1];folder=_make_directory(root/'output/xy-proof','small')
    source=folder/'codes.txt';source.write_text('200000000000\n200000000001\n200000000002\n',encoding='utf-8')
    jobs=[]
    for mode in ('off','on'):
        jobs.append(run_batch(source,folder/mode,mode='multipage',qa_mode='full',settings=PrintSettings(pdf_profile='compact'),force_disk=True,timeline_mode=mode))
    manifests=[json.loads((p/'manifest.json').read_text(encoding='utf-8')) for p in jobs]
    assert all(m['status']=='COMPLETE' for m in manifests),[m['status'] for m in manifests]
    assert next(jobs[0].glob('all-*.pdf')).read_bytes()==next(jobs[1].glob('all-*.pdf')).read_bytes()
    script='test lab --codes 3 --cpu 1 --repeats 1 --qa off --xy on\ntest pipeline --codes 3 --split cores:1+0 --schedule queue --repeats 1 --qa full --metrics off --xy on'
    with archive_scope(folder/'archive'):queue=run_script(script,folder/'queue')
    data=json.loads((queue/'commands.json').read_text(encoding='utf-8'))
    assert data['status']=='UNVERIFIED',data.get('errors')
    assert data['runs'][1]['status']=='COMPLETE'
    assert len(chart_model(data)['timelines'])>=3
    assert len(archive_rows(folder/'archive'))==3
    assert not list((folder/'archive').rglob('*.pdf'))
    # Independent oracle, clearly a control fixture, not a production measurement.
    control={'kind':'xy-control-fixture','status':'CONTROL_ONLY','timeline':{'schema':1,'segments':[{
        'stage':'Контрольный ряд, не производственный тест','counter_kind':'written_pages','target':500,
        'points':[[0,0,None,0],[1,100,100,1],[3,500,200,2],[4,500,0,1]],
        'stats':{'min':0,'mean':125,'max':200},'observations':4,'compactions':0}]}}
    write_text_report(folder/'control.html',control,'Контроль геометрии XY — не результат производительности')
    previous=root/'output/jobs/search/pc-20261029-060734-d5b0b445/pc-search.json'
    historical=None
    if previous.is_file():
        before=hashlib.sha256(previous.read_bytes()).hexdigest()
        old=json.loads(previous.read_text(encoding='utf-8'))
        assert not chart_model(old)['timelines']
        assert hashlib.sha256(previous.read_bytes()).hexdigest()==before
        historical={'source_sha256':before,'source_unchanged':True,'no_historical_series':True,'cases':len(old['cases'])}
    proof={'kind':'xy-verification','source_digest':code_fingerprint(),'scope':'Windows, max 3 real pages; not a throughput measurement',
        'on_off_pdf_identical':True,'production_full_qa':['COMPLETE','COMPLETE'],'queue_status':data['status'],
        'pipeline_full_qa':data['runs'][1]['status'],'archive_records':3,'historical':historical}
    atomic_json(folder/'verification.json',proof)
    public=root/'results/xy-reports';public.mkdir(parents=True,exist_ok=True);atomic_json(public/'verification.json',proof)
    print(json.dumps({'folder':str(folder),'production':str(jobs[1]/'production.html'),'queue':str(queue/'commands.html'),'control':str(folder/'control.html')},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
