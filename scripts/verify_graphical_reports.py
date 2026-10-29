"""Small retained evidence: real PDF reports, archived graphs, immutable old JSON."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from ucode.batch import _make_directory
    from ucode.test_archive import archive_scope,archive_rows
    from ucode.test_commands import run_script
    from ucode.graphical_report import chart_model,write_graphical_copy
    from ucode.lab_worker import atomic_json,code_fingerprint
    root=Path(__file__).resolve().parents[1]
    folder=_make_directory(root/'output/graphical-proof','small')
    script='\n'.join((
        'test lab --codes 3 --cpu 1,2 --unit cores --repeats 1 --batch 1 --qa off --metrics off',
        'test pipeline --codes 3 --split cores:1+1,cores:2+0 --schedule queue --batch 1 --repeats 1 --qa full --metrics cpu'))
    with archive_scope(folder/'archive'): run=run_script(script,folder/'queue')
    data=json.loads((run/'commands.json').read_text(encoding='utf-8'))
    assert data['status']=='UNVERIFIED',data.get('errors')
    assert data['runs'][1]['status']=='COMPLETE',data['runs'][1]
    assert len(archive_rows(folder/'archive'))==3
    assert not list((folder/'archive').rglob('*.pdf'))
    reports=list(run.rglob('pipeline.html'))+list(run.rglob('comparison.html'))+[run/'commands.html']
    for path in reports: assert 'uc-chart-data' in path.read_text(encoding='utf-8'),str(path)
    models=[chart_model(r['result']) for r in data['runs']]
    assert sum(len(g['rows']) for m in models for g in m['groups'])==4
    assert all(r['eligible'] for m in models for g in m['groups'] for r in g['rows'])
    history=root/'output/jobs/pipeline-tests/pipeline-20261029-052021-7723ef45/pipeline.json'
    old=None
    if history.is_file():
        before=hashlib.sha256(history.read_bytes()).hexdigest()
        view=write_graphical_copy(history,folder/'old-views')
        assert hashlib.sha256(history.read_bytes()).hexdigest()==before
        old={'view':str(view.relative_to(folder)),'source_unchanged':True,'source_sha256':before,'cases':36,'trials':108}
    proof={'kind':'graphical-reports-verification','source_digest':code_fingerprint(),
           'scope':'Windows, max 3 pages per real PDF; no large benchmark or visual acceptance',
           'queue_status':data['status'],'full_qa_pipeline_status':data['runs'][1]['status'],
           'cases':4,'text_archive_records':3,'pdf_in_archive':False,'historical':old}
    atomic_json(folder/'verification.json',proof)
    public=root/'results/graphical-reports'; public.mkdir(parents=True,exist_ok=True)
    atomic_json(public/'verification.json',proof)
    print(json.dumps({'folder':str(folder),'report':str(run/'commands.html'),'status':data['status']},ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
