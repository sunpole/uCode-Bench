"""Append-only local text archives, after timing; portable reports, no PDF/TXT data."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
from functools import wraps
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import uuid

ROOT=ContextVar("ucode_test_archive",default=None)
DEPTH=ContextVar("ucode_archive_depth",default=0)
PENDING=ContextVar("ucode_archive_pending",default=None)
REPORTS=("commands.json","pipeline.json","pc-search.json","lab.json","scientific.json","comparison.json","report.json","manifest.json")
MAX_JSON=64*1024**2
DROP={"payload","matrix","frames","first_code","last_code","first","last","decoded_samples","source_txt","input_filename",
      "username","hostname","python_executable","runtime_code_root","asset_root","runtime_root","pid","worker_pids","worker_affinity"}
KINDS={"resource-lab":"CPU / RAM","cpu-pipeline-lab":"Конвейер","pc-performance-search":"Подбор ПК","scientific-3-repeat":"Научный тест","comparison":"200 → 1000","report":"Научный этап","test-command-queue":"Консоль","txt-batch-pdf":"Создание PDF"}
STATES={"COMPLETE":"Завершён","PASS":"QA PASS","UNVERIFIED":"Без проверки","LIMITED":"Частичная проверка","CANCELLED":"Остановлен","ERROR":"Ошибка","INVALID":"Ошибка проверки","PARTIAL":"Не все варианты","SKIPPED":"Пропущен","RUNNING":"Выполняется"}


def test_counts(data):
    numbers=set()
    if data.get('kind')=='txt-batch-pdf' and type(data.get('count')) is int:numbers.add(data['count'])
    cfg=data.get("config",{})
    for n in [*cfg.get("counts",[]),cfg.get("count")]:
        if type(n) is int and n>0: numbers.add(n)
    for c in data.get("cases",[]):
        if type(c.get("count")) is int and c["count"]>0: numbers.add(c["count"])
    for run in data.get("runs",[]):
        if type(run.get("count")) is int and run["count"]>0: numbers.add(run["count"])
        numbers.update(test_counts(run.get("result",{})))
    return sorted(numbers)


def result_rows(data,prefix=""):
    if data.get('kind')=='txt-batch-pdf':
        execution=data.get('execution',{})
        yield (prefix+'Создание PDF',data.get('count'),str(execution.get('backend','?')),
               STATES.get(data.get('status'),data.get('status')),data.get('seconds',{}).get('launcher_wall'),
               'Один производственный запуск',1)
    for c in data.get("cases",[]):
        s=c.get("summary",{}); seconds=s.get("median_launcher_wall_seconds")
        cpu=c.get("allocation",str(c.get("cpu_choice","?"))+" "+("ядер" if c.get("cpu_unit")=="physical" else "CPU"))
        if 'processes_per_cpu' in c: cpu=str(cpu)+f" · {c['processes_per_cpu']} процессов/CPU · всего {c.get('workers','?')}"
        state=STATES.get(c.get("status"),c.get("status"))
        from .result_presentation import test_outcome
        if test_outcome({'status':c.get('status'),'cases':[c]})['resource_only']:state='Ограничение ОЗУ'
        yield (prefix+str(c.get("id","")),c.get("count"),cpu,state,seconds,"Весь запуск",len(c.get("trials",[])))
    for method in data.get("methods",[]):
        yield (prefix+method.get("name","Метод"),data.get("config",{}).get("count"),"—",STATES.get(method.get("status"),method.get("status")),method.get("median_seconds"),"Метод, без QA",len(method.get("trials",[])))
    for i,run in enumerate(data.get("runs",[]),1):
        nested=run.get("result") or {"config":{"count":run.get("count")},"methods":run.get("methods",[])}
        yield from result_rows(nested,prefix+f"{i}. ")


@contextmanager
def archive_scope(root):
    token=ROOT.set(Path(root).resolve())
    try: yield
    finally: ROOT.reset(token)


def read_test(folder,*,with_bytes=False):
    folder=Path(folder)
    for name in REPORTS:
        path=folder/name
        if not path.is_file(): continue
        with path.open("rb") as stream: raw=stream.read(MAX_JSON+1)
        if len(raw)>MAX_JSON: raise ValueError("Отчёт больше 64 МиБ; сохраните его отдельно")
        value=json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value,dict): raise ValueError("Неверный формат отчёта")
        return (path,value,raw) if with_bytes else (path,value)
    raise ValueError("В папке нет поддерживаемого результата теста")


def sanitize(value,key=""):
    if isinstance(value,dict):
        return {str(k):sanitize(v,str(k)) for k,v in value.items() if str(k).lower() not in DROP and not any(word in str(k).lower() for word in ("password","secret","token","credential","authorization"))}
    if isinstance(value,list): return [sanitize(v,key) for v in value]
    if isinstance(value,tuple): return [sanitize(v,key) for v in value]
    if isinstance(value,str):
        value=re.sub(r"(?i)(?:[a-z]:[\\/]|file:///|\\\\)[^\r\n<>\"']*","[local-path]",value)
        value=re.sub(r"(?<![:\w/])/(?:[^/\s\"'<>]+/)+[^\s\"'<>]*","[local-path]",value)
        if key.lower() in ("path","folder","directory","executable","root","cwd") and value.startswith("/"): value="[local-path]"
        value=re.sub(r"\b\d{12}\b","[code]",value)
        value=re.sub(r"(https?://)[^/\s@]+@",r"\1[credentials]@",value)
    return value


def write_text_report(path,data,title):
    """Self-contained escaped text; no links to absent PDFs or executable scripts."""
    raw=json.dumps(data,ensure_ascii=False,indent=2)
    document='<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+html.escape(title)+'</title><style>body{font:16px Segoe UI,Arial;background:#0b1220;color:#edf4fc;margin:24px}a{color:#5ce0bd}pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse}td,th{border:1px solid #31445e;padding:6px}</style><h1>'+html.escape(title)+'</h1><p>Статус: '+html.escape(str(data.get("status","?")))+'</p>'
    if data.get('cases') or data.get('runs'):
        from .result_presentation import test_outcome
        view=test_outcome(data)
        document+='<aside style="padding:16px;border:1px solid #31445e;border-radius:12px"><h2>'+html.escape(view['title'])+'</h2><p>'+html.escape(view['detail'])+'</p>'
        if view['reason']:document+='<p>'+html.escape(view['reason'])+'</p>'
        document+='</aside>'
    if data.get("commands"): document+='<h2>Команды</h2><pre>'+html.escape('\n'.join(data['commands']))+'</pre>'
    if data.get("runs") and data.get("kind")=="test-command-queue":
        document+='<h2>Запуски</h2><ol>'+''.join('<li>'+html.escape(str(r.get("status")))+' · '+html.escape(str(r.get("command")))+'</li>' for r in data['runs'])+'</ol>'
    rows=list(result_rows(data))
    if rows:
        document+='<h2>Варианты</h2><div style="overflow:auto;max-width:100%"><table><tr><th>Вариант</th><th>Кодов</th><th>CPU</th><th>Статус</th><th>Медиана, с</th><th>Что измерено</th><th>Повторов</th></tr>'
        for row in rows:
            document+='<tr>'+''.join('<td>'+html.escape(f"{v:.4f}" if isinstance(v,float) else str(v) if v is not None else "—")+'</td>' for v in row)+'</tr>'
        document+='</table></div>'
    document+='<details><summary>Все сохранённые параметры и измерения · JSON</summary><pre>'+html.escape(raw)+'</pre></details></html>'
    from .graphical_report import embed_graphs
    Path(path).write_text(embed_graphs(document,data),encoding="utf-8")


def _database(root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/"catalog.sqlite",timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, source_key TEXT UNIQUE, created TEXT, kind TEXT, status TEXT, cpu TEXT, counts TEXT, file TEXT)")
    db.commit(); return db


def archive_rows(root,limit=1000):
    root=Path(root)
    if not (root/"catalog.sqlite").is_file(): return []
    db=_database(root)
    try:
        return [dict(zip(("id","created","kind","status","cpu","counts","file"),row)) for row in db.execute("SELECT id,created,kind,status,cpu,counts,file FROM runs ORDER BY created DESC,id DESC LIMIT ?",(limit,))]
    finally: db.close()


def _index(root,db):
    rows=db.execute("SELECT created,kind,status,cpu,counts,file FROM runs ORDER BY created DESC,id DESC").fetchall()
    doc='<!doctype html><html lang="ru"><meta charset="utf-8"><title>uCode — архив тестов</title><style>body{font:16px Segoe UI;background:#0b1220;color:#edf4fc;margin:24px}a{color:#5ce0bd}td,th{padding:7px;border:1px solid #31445e}table{border-collapse:collapse}</style><h1>Архив тестов</h1><p>Только текстовые результаты и данные ПК; PDF и исходные TXT не включены.</p><table><tr><th>UTC</th><th>Вид</th><th>Статус</th><th>CPU</th><th>Тиражи</th><th>Отчёт</th></tr>'
    for created,kind,status,cpu,counts,file in rows:
        cells=(created,KINDS.get(kind,kind),STATES.get(status,status),cpu,counts)
        doc+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'<td><a href="'+html.escape(file,quote=True)+'">Открыть</a></td></tr>'
    doc+='</table></html>'
    from .lab_worker import atomic_json
    temporary=Path(root)/(".index-"+uuid.uuid4().hex+".html"); temporary.write_text(doc,encoding="utf-8"); temporary.replace(Path(root)/"index.html")


def store_test(folder,root):
    from .lab_worker import atomic_json
    source,data,raw=read_test(folder,with_bytes=True); root=Path(root).resolve()
    key=hashlib.sha256((str(source.resolve())+"\0").encode()+raw).hexdigest()
    db=_database(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("SELECT id,file FROM runs WHERE source_key=?",(key,)).fetchone()
        if old: return {"status":"SAVED","id":old[0],"report":str(root/old[1]),"archive":str(root),"duplicate":True}
        ident=uuid.uuid4().hex; directory=root/"runs"/ident; directory.mkdir(parents=True,exist_ok=False)
        clean=sanitize(data)
        hardware=clean.get("hardware") or clean.get("environment",{}).get("hardware") or {}
        if not hardware:
            from .hardware import inspect_hardware
            hardware=sanitize(inspect_hardware(folder))
            clean["hardware"]=hardware
        cpu=hardware.get("cpu",{})
        cpu=cpu.get("name","CPU неизвестен") if isinstance(cpu,dict) else str(cpu)
        counts=", ".join(f"{n:,}".replace(","," ") for n in test_counts(clean)) or "по допуску / не указано"
        created=datetime.now(timezone.utc).isoformat(timespec="microseconds")
        envelope={"archive_schema":1,"id":ident,"created_utc":created,"kind":clean.get("kind",source.stem),"status":clean.get("status","UNKNOWN"),
                  "hardware":hardware,"data":clean,"contains_pdf":False,"contains_input_txt":False}
        import platform
        from importlib.metadata import version,PackageNotFoundError
        versions={}
        for package in ("reportlab","pypdf","Pillow"):
            try: versions[package]=version(package)
            except PackageNotFoundError: versions[package]=None
        envelope["archive_environment"]={"os":platform.platform(),"python":platform.python_version(),"packages":versions,
            "scope":"Machine/runtime creating the text snapshot; original test runtime remains in data when available"}
        atomic_json(directory/"report.json",envelope)
        write_text_report(directory/"report.html",{**clean,"archive_environment":envelope["archive_environment"]},"uCode — сохранённый тест")
        (directory/"ОТЧЁТ.txt").write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        relative=(directory/"report.html").relative_to(root).as_posix()
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",(ident,key,created,envelope["kind"],envelope["status"],cpu,str(counts),relative))
        _index(root,db); db.commit()
        return {"status":"SAVED","id":ident,"report":str(directory/"report.html"),"archive":str(root),"duplicate":False}
    finally: db.close()


def archive_test(folder,root=None,*,write_receipt=True):
    """Archive errors never rewrite scientific status or timing; receipt is explicit."""
    from .lab_worker import atomic_json
    folder=Path(folder); root=Path(root or ROOT.get() or folder.parent/"_test_archive")
    try: receipt=store_test(folder,root)
    except Exception as exc: receipt={"status":"ERROR","error":type(exc).__name__+": "+str(exc),"archive":str(root)}
    try:
        if write_receipt: atomic_json(folder/"archive-status.json",receipt)
    except OSError:
        # Read-only historical imports can still be archived. The caller gets
        # the receipt; an archive failure never changes the measured result.
        pass
    return receipt


def archived_test(function):
    @wraps(function)
    def call(*args,**kwargs):
        outer=DEPTH.get()==0; queue_token=PENDING.set([]) if outer else None
        depth_token=DEPTH.set(DEPTH.get()+1); final=[]; event=kwargs.get("events")
        if outer and event:
            def notify(value):
                if value.get("percent")==100: final.append(value)
                else: event(value)
            kwargs={**kwargs,"events":notify}
        try:
            folder=function(*args,**kwargs); PENDING.get().append(Path(folder)); return folder
        finally:
            DEPTH.reset(depth_token)
            if outer:
                try:
                    for folder in dict.fromkeys(PENDING.get()): archive_test(folder)
                    for value in final: event(value)
                finally: PENDING.reset(queue_token)
    return call


def import_tests(source,root,*,cancel=None):
    """Read prior results, add text snapshots; skip own archive and runtime folders."""
    source=Path(source).resolve(); root=Path(root).resolve(); files=[]
    import os
    for directory,names,children in os.walk(source):
        base=Path(directory).resolve()
        if (base/"catalog.sqlite").is_file(): names[:]=[]; continue
        names[:]=[n for n in names if n not in (".runtime",".venv","node_modules","tools","runs") or n=="runs" and not base.is_relative_to(root)]
        names[:]=[n for n in names if not (base/n).is_relative_to(root)]
        if cancel is not None and cancel.is_set(): raise InterruptedError("Импорт остановлен")
        if any(name in children for name in REPORTS): files.append(base)
        if len(files)>10000: raise ValueError("Найдено больше10000 папок; выберите более точную папку")
    receipts=[]
    for folder in files:
        if cancel is not None and cancel.is_set(): raise InterruptedError("Импорт остановлен")
        receipts.append(archive_test(folder,root,write_receipt=False))
    return receipts
