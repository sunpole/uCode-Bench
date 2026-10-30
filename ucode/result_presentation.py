"""Human-facing test outcomes; never change saved quality statuses or timings."""
GOOD = {'COMPLETE','PASS','LIMITED','UNVERIFIED'}


def test_outcome(data):
    cases=[]
    def visit(node,depth=0):
        if depth>8:return
        repeats=node.get('config',{}).get('repeats',1)
        for case in node.get('cases',[]):cases.append((case,repeats))
        for run in node.get('runs',[]):visit(run.get('result') or {},depth+1)
    visit(data)
    complete=planned=limits=failures=0
    for case,repeats in cases:
        if case.get('status')=='SKIPPED':continue
        planned+=repeats
        trials=[t for t in case.get('trials',[]) if not t.get('warmup')]
        if case.get('status') in {'INVALID','ERROR'} and not trials:failures+=1
        complete+=sum(t.get('status') in GOOD and not t.get('errors') for t in trials)
        limits+=sum(t.get('status')=='RESOURCE_LIMIT' for t in trials)
        failures+=sum(t.get('status') not in GOOD|{'RESOURCE_LIMIT','SKIPPED','CANCELLED'} or
                      (bool(t.get('errors')) and t.get('status') in GOOD) for t in trials)
    state=data.get('status','ERROR')
    wrapper_only=all(str(e).startswith('Команда завершилась со статусом PARTIAL;') for e in data.get('errors',[]))
    resource_only=limits>0 and failures==0 and wrapper_only and not any(c.get('status')=='ERROR' for c,_ in cases) and state in {'ERROR','PARTIAL','INVALID','RESOURCE_LIMIT'}
    title=('НЕ ВСЕ ТЕСТЫ ВЫПОЛНЕНЫ · ОЗУ' if resource_only else
           {'COMPLETE':'ТЕСТЫ ЗАВЕРШЕНЫ','PASS':'ТЕСТЫ ЗАВЕРШЕНЫ','UNVERIFIED':'ТЕСТЫ ЗАВЕРШЕНЫ · БЕЗ ПРОВЕРКИ (UNVERIFIED)',
            'LIMITED':'ТЕСТЫ ЗАВЕРШЕНЫ · ЧАСТИЧНАЯ ПРОВЕРКА','CANCELLED':'ТЕСТЫ ОСТАНОВЛЕНЫ',
            'PARTIAL':'НЕ ВСЕ ТЕСТЫ ВЫПОЛНЕНЫ','INVALID':'ЕСТЬ НЕКОРРЕКТНЫЕ РЕЗУЛЬТАТЫ','ERROR':'ОШИБКА ТЕСТА'}.get(state,'ТЕСТ: '+state))
    detail=f'Готовых повторов: {complete} / {planned}' if planned else 'Результаты сохранены в отчёте'
    if limits:detail+=f' · отказов по ОЗУ: {limits}'
    if resource_only:detail+=' · сократите процессы или порцию'
    elif failures:detail+=f' · ошибок: {failures}; причины в отчёте'
    reason=next((str(e) for c,_ in cases for t in c.get('trials',[]) if t.get('status')=='RESOURCE_LIMIT' for e in t.get('errors',[])),None)
    return {'title':title,'detail':detail,'complete':complete,'planned':planned,'resource_only':resource_only,
            'reason':reason,'tone':'warning' if resource_only or state in {'PARTIAL','LIMITED','UNVERIFIED','CANCELLED'} else 'danger' if state in {'ERROR','INVALID'} else 'success',
            'status':state}

