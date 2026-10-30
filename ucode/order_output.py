"""Portable output names and collision-safe publication of a completed job."""
from datetime import datetime
import json
from pathlib import Path
import re


def normalize_name(value):
    name=str(value).strip()
    if not name:raise ValueError('Введите имя результата')
    name=re.sub(r'(?:\.pdf)+$','',name,flags=re.I)
    if not name or name.endswith(('.', ' ')) or len(name)>160 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name):
        raise ValueError('Недопустимое имя файла: уберите служебные символы и точки в конце')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('Это имя зарезервировано Windows')
    return name+'.pdf'


def suggested_name(first,count,stamp):
    return normalize_name(f'QR_{first[-4:]}_{count}_{stamp}')


def reserve_folder(root,name):
    stem=Path(normalize_name(name)).stem
    for n in range(10000):
        folder=Path(root)/(stem if n==0 else f'{stem}_{n+1}')
        try:folder.mkdir();return folder
        except FileExistsError:continue
    raise ValueError('Слишком много результатов с одинаковым именем')


def publish_job(folder,name):
    """Keep historical generation/QA unchanged, then publish into a fresh folder.

    Partial or failed jobs retain their original layout for diagnosis.
    """
    folder=Path(folder);report=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if report['status'] not in ('COMPLETE','LIMITED','UNVERIFIED'):return folder
    target=reserve_folder(folder.parent,name)
    for path in folder.iterdir():path.rename(target/path.name)
    folder.rmdir()
    mode=report['mode'];layout={'numbered':True,'singles':'.' if mode=='singles' else 'singles'}
    if mode in ('both','multipage'):
        old=target/report['files']['multipage']['name'];new=target/(target.name+'.pdf');old.rename(new)
        report['files']['multipage']['name']=new.name;layout['multipage']=new.name
    if mode in ('both','singles'):
        files=sorted((target/'singles').glob('*.pdf'));digits=max(4,len(str(report['count'])))
        destination=target if mode=='singles' else target/'singles'
        for i,path in enumerate(files,1):path.rename(destination/f'{i:0{digits}d}.pdf')
        if mode=='singles':(target/'singles').rmdir()
        report['files']['singles']['directory']=layout['singles']
    report['output_layout']=layout;report['requested_name']=normalize_name(name)
    (target/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return target


def output_path(root,layout,key,default):
    value=(layout or {}).get(key,default)
    if value!='.' and (Path(value).name!=value or '\\' in value):raise ValueError('Недопустимый путь в manifest')
    return Path(root)/value
