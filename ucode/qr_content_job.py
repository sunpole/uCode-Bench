"""Local vector exports for one static QR payload (and requested copies)."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

from .qr_content_codec import encode_content,decode_content
from .print_settings import PrintSettings

def qa_settings(settings):return SimpleNamespace(**asdict(settings),payload_mode=True)

def export_images(frame,root,settings):
    from PIL import Image,ImageDraw
    q=settings.quiet_modules;n=frame.size+2*q;scale=10
    def rgb(ink):
        c,m,y,k=(v/100 for v in ink);return tuple(round(255*(1-v)*(1-k)) for v in (c,m,y))
    paper=(0,0,0,0) if settings.background_mode=='transparent' else (*rgb(settings.background_ink if settings.background_mode=='color' else (0,0,0,0)),255)
    ink=rgb(settings.ink);image=Image.new('RGBA',(n*scale,n*scale),paper);draw=ImageDraw.Draw(image)
    paths=[]
    for y,row in enumerate(frame.matrix):
        for x,dark in enumerate(row):
            if dark:
                draw.rectangle(((x+q)*scale,(y+q)*scale,(x+q+1)*scale-1,(y+q+1)*scale-1),fill=(*ink,255))
                paths.append(f'M{x+q} {y+q}h1v1h-1z')
    image.save(Path(root)/'qr.png')
    background='' if settings.background_mode=='transparent' else f'<rect width="{n}" height="{n}" fill="rgb{paper[:3]}"/>'
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n*settings.module_mm}mm" height="{n*settings.module_mm}mm" shape-rendering="crispEdges">{background}<path fill="rgb{ink}" d="{"".join(paths)}"/></svg>'
    (Path(root)/'qr.svg').write_text(svg,encoding='utf-8')

def write_content_pdf(frame,path,settings,copies=1,cancel=None,progress=None):
    from reportlab.pdfgen.canvas import Canvas
    side=(frame.size+2*settings.quiet_modules)*settings.module_mm*72/25.4
    canvas=Canvas(str(path),pagesize=(side,side),pageCompression=1)
    unit=settings.module_mm*72/25.4;q=settings.quiet_modules
    for i in range(copies):
        if cancel is not None and cancel.is_set():raise InterruptedError('Создание остановлено')
        if settings.background_mode=='color':
            paper=settings.background_ink if settings.background_mode=='color' else (0,0,0,0)
            canvas.setFillColorCMYK(*(v/100 for v in paper));canvas.rect(0,0,side,side,stroke=0,fill=1)
        canvas.setFillColorCMYK(*(v/100 for v in settings.ink))
        pathdata=canvas.beginPath()
        for y,row in enumerate(reversed(frame.matrix)):
            x=0
            while x<frame.size:
                if not row[x]:x+=1;continue
                left=x
                x+=1
                if settings.pdf_profile=='compact':
                    while x<frame.size and row[x]:x+=1
                pathdata.rect((left+q)*unit,(y+q)*unit,(x-left)*unit,unit)
        canvas.drawPath(pathdata,stroke=0,fill=1);canvas.showPage()
        if progress:progress(i+1,copies)
    canvas.save()

def run_content_job(request,cancel,send):
    from .batch import _make_directory
    from .audit import qa_status
    from .quality import check_pdf
    from .order_output import publish_job
    settings=PrintSettings(**request['settings']);payload=request['payload'];copies=int(request['options']['copies_per_value'])
    if not 1<=copies<=10000:raise ValueError('Для одиночного содержимого: 1–10 000 экземпляров')
    start=time.perf_counter();frame=encode_content(payload,settings.error_correction)
    encoding=time.perf_counter()-start;mode=request['mode'];directory=_make_directory(Path(request['destination']),'content')
    from . import __version__
    files={};report={'schema_version':1,'kind':'txt-batch-pdf','software_version':__version__,'generator':'qr-content','status':'RUNNING','mode':mode,'count':copies,
        'content_kind':request['content_kind'],'payload':payload,'engine':{'name':'ReportLab static QR + vector PDF'},
        'print':{**settings.to_dict(),'version':frame.version,'ecc':frame.error,'page_mm':[(frame.size+2*settings.quiet_modules)*settings.module_mm]*2,
                 'dark_matrix_mm':frame.size*settings.module_mm,'pdf_writer':'ReportLab Canvas / variable QR',
                 'description':f'QR V{frame.version}-{frame.error} UTF-8','colorspace':'DeviceCMYK'},
        'seconds':{'code_encoding':encoding},'files':files,'qa':{},'errors':[],
        'generation':{'pdf_pages_written':0,'input_records':1,'unique_values':1,'copies_per_value':copies},
        'payload_bytes':len(payload.encode('utf-8')),'payload_sha256':hashlib.sha256(payload.encode('utf-8')).hexdigest(),
        'timing_scope':'total_including_qa: encode + PDF + selected PDF QA; auxiliary PNG/SVG/text/report exports excluded',
        'execution':{'backend':'serial','requested_workers':1,'effective_workers':1,'scope':'One static payload; CPU lab settings apply to numeric batch jobs'}}
    paths=[]
    def progress(done,total):
        if shutil.disk_usage(directory).free<256*1024**2:raise OSError('Заканчивается место; частичные результаты сохранены')
        send('progress',{'stage':'Создание PDF','done':done,'total':total,'percent':min(90,90*done/total),'elapsed':time.perf_counter()-start,'speed':0,'average_speed':0,'unit':'страниц'})
    try:
        if mode in ('singles','both'):
            folder=directory/'singles';folder.mkdir();t=time.perf_counter();digits=max(4,len(str(copies)))
            for i in range(copies):
                path=folder/f'{i+1:0{digits}d}.pdf';write_content_pdf(frame,path,settings,cancel=cancel);paths.append((path,1));progress(i+1,copies)
            report['seconds']['write_singles']=time.perf_counter()-t;files['singles']={'directory':'singles','count':copies}
        if mode in ('multipage','both'):
            path=directory/f'all-{copies}-pages.pdf';t=time.perf_counter()
            write_content_pdf(frame,path,settings,copies,cancel,progress);paths.append((path,copies))
            report['seconds']['write_multipage']=time.perf_counter()-t;files['multipage']={'name':path.name,'pages':copies,'bytes':path.stat().st_size}
        report['generation']['pdf_pages_written']=copies*(2 if mode=='both' else 1)
        report['seconds']['production_until_pdf_closed']=time.perf_counter()-start;t=time.perf_counter()
        if request['options']['qa_mode']=='deferred':report['status']='UNVERIFIED';report['qa']={'status':'NOT_RUN'}
        else:
            raster=request['options']['qa_mode']=='full' and bool(shutil.which('pdftoppm'));qa=[]
            for i,(path,count) in enumerate(paths):
                if cancel.is_set():raise InterruptedError('Проверка остановлена')
                send('progress',{'stage':'Проверка PDF','done':i,'total':len(paths),'percent':90+9*i/len(paths),'elapsed':time.perf_counter()-start,'speed':0,'average_speed':0,'unit':'файлов'})
                qa.append(check_pdf(path,[frame]*count,qa_settings(settings),render_samples=raster,cancel=cancel))
            failed=[q for q in qa if q['status']!='PASS']
            report['qa']={'content':{'status':'FAIL' if failed else 'PASS','errors':[e for q in failed for e in q['errors']],
                                    'decoded_files':len(qa),'raster':raster,'decoder':'independent QR V1–40 BCH + per-block RS + UTF-8 ECI'}}
            report['status']=qa_status(report['qa'],raster)
        report['seconds']['quality_checks']=time.perf_counter()-t
    except Exception as exc:report['status']='CANCELLED' if isinstance(exc,InterruptedError) else 'ERROR';report['errors'].append(str(exc))
    report['seconds']['total_including_qa']=time.perf_counter()-start
    (directory/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if request.get('output_name'):directory=publish_job(directory,request['output_name'])
    report=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    export_images(frame,directory,settings)
    (directory/'payload.txt').write_text(payload,encoding='utf-8',newline='')
    (directory/'ОТЧЁТ.txt').write_text(f"uCode — статический QR\nТип содержимого: {request['content_kind']}\nСтатус: {report['status']}\nВерсия: {frame.version}; коррекция: {frame.error}\nРазмер: {report['print']['page_mm'][0]:.2f} мм\nUTF-8: {report['payload_bytes']} байт\nВремя: {report['seconds']['total_including_qa']:.3f} сек\nКамера телефона не проверялась.\n",encoding='utf-8')
    from .test_archive import write_text_report,archive_test
    # Plaintext payload is kept only in the local manifest, never text archives.
    write_text_report(directory/'production.html',{k:v for k,v in report.items() if k!='payload'},'uCode — статический QR')
    archive_test(directory,Path(request['archive']))
    if report['status'] in ('COMPLETE','LIMITED','UNVERIFIED'):
        send('progress',{'stage':'PDF и отчёт сохранены','done':copies,'total':copies,'percent':100,'elapsed':time.perf_counter()-start,'speed':0,'average_speed':0,'unit':'страниц'})
    return directory

def audit_content(directory,original,render_samples=True,cancel=None):
    from .quality import check_pdf
    from .batch import _make_directory
    from .audit import qa_status
    frame=encode_content(original['payload'],original['print']['error_correction'])
    cfg={k:original['print'][k] for k in PrintSettings.__dataclass_fields__ if k in original['print']};settings=PrintSettings(**cfg)
    root=Path(directory);paths=[];files=original['files'];layout=original.get('output_layout',{})
    from .order_output import output_path
    if 'multipage' in files:paths.append((output_path(root,layout,'multipage',files['multipage']['name']),original['count']))
    if 'singles' in files:
        paths.extend((p,1) for p in sorted(output_path(root,layout,'singles',files['singles']['directory']).glob('*.pdf')))
    raster=render_samples and bool(shutil.which('pdftoppm'));results=[check_pdf(p,[frame]*count,qa_settings(settings),render_samples=raster,cancel=cancel) for p,count in paths]
    expected=(original['count'] if original['mode']=='singles' else 1 if original['mode']=='multipage' else original['count']+1)
    qa={'content':{'status':'PASS' if len(paths)==expected and all(r['status']=='PASS' for r in results) else 'FAIL',
                   'errors':[e for r in results for e in r['errors']]}}
    folder=_make_directory(root/'audits','qa');report={'kind':'pdf-audit','status':qa_status(qa,raster),'qa':qa}
    (folder/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'ОТЧЁТ.txt').write_text('Проверка статического QR: '+report['status'],encoding='utf-8');return folder
