"""Retained small real command/QA/archive evidence; never a large benchmark."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from ucode.batch import _make_directory
    from ucode.test_archive import archive_scope,archive_rows
    from ucode.test_commands import run_script
    from ucode.lab_worker import atomic_json,code_fingerprint
    from ucode.hardware import inspect_cpu
    root=Path(__file__).resolve().parents[1]
    if (inspect_cpu().get('available_physical') or 0)<2: raise SystemExit('Small proof needs two physical cores')
    folder=_make_directory(root/'output/test-hub-proof','small'); events=[]
    text='\n'.join((
        'test lab --codes 3 --cpu 1,2 --unit cores --repeats 1 --batch 1 --qa off --metrics off',
        'test pipeline --codes 5 --split cores:1+1,cores:2+0 --schedule equal,queue --batch 1 --repeats 1 --qa full --metrics cpu --module .75 --quiet 5 --ink 10,0,0,100',
        'test search --codes 3 --unit cores --cpu 1 --backend serial --parts 2 --part-mode parallel --mergers pypdf --repeats 1 --qa off --metrics off'))
    with archive_scope(folder/'archive'): result=run_script(text,folder/'queue',events=events.append)
    data=json.loads((result/'commands.json').read_text(encoding='utf-8'))
    assert data['status']=='UNVERIFIED',data['errors']
    assert len(data['runs'])==3
    assert data['runs'][1]['status']=='COMPLETE'
    assert len(archive_rows(folder/'archive'))==4
    assert not list((folder/'archive').rglob('*.pdf'))
    assert not list((folder/'archive').rglob('codes.txt'))
    assert events[-1]['percent']==100 and all(e['percent']<100 for e in events[:-1])
    proof={'kind':'test-hub-verification','source_digest':code_fingerprint(),'scope':'Windows small integration; max five pages per real PDF; no throughput claim',
           'queue_status':data['status'],'commands':data['commands'],'individual_runs':len(data['runs']),'text_archive_records':len(archive_rows(folder/'archive')),
           'pdf_in_archive':False,'cases':[{'kind':r['result'].get('kind'),'status':r['status'],'cases':[{'id':c['id'],'count':c['count'],'status':c['status'],'qa_mode':c.get('qa_mode',r['result']['config'].get('qa_mode'))} for c in r['result'].get('cases',[])]} for r in data['runs']]}
    atomic_json(folder/'verification.json',proof)
    public=root/'results/test-hub'; public.mkdir(parents=True,exist_ok=True); atomic_json(public/'verification.json',proof)
    print(json.dumps({'folder':str(folder),'queue':str(result),'archive':str(folder/'archive/index.html'),'status':data['status'],'records':4},ensure_ascii=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
