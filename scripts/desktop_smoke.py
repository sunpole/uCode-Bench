"""Small real WebView smoke, no screenshots or large benchmark. Run from project root."""
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
import uuid
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import webview
from ucode.operator_desktop import main,api

folder=Path('output/desktop-smoke')/uuid.uuid4().hex
folder.mkdir(parents=True)
result={'scope':'real WebView2, 3 codes, geometry only; not visual/DPI acceptance'}
original_start=webview.start


def run():
    window=webview.windows[0]
    try:
        deadline=time.monotonic()+30
        while not window.events.loaded.is_set():
            if time.monotonic()>deadline:raise TimeoutError('WebView did not load')
            time.sleep(.1)
        url=window.get_current_url()
        result['health']=api(url,'health')
        duplicate=subprocess.run([sys.executable,'-c',
            'from ucode.operator_desktop import main; main(root='+repr(str(folder.resolve()))+')'],
            capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result['duplicate_exit']=duplicate.returncode
        api(url,'sequence',{'start':'500000000000','count':3,'step':1})
        def wait():
            end=time.monotonic()+20
            while time.monotonic()<end:
                state=api(url,'state')
                if not state['busy']:return state
                time.sleep(.05)
            raise TimeoutError('Small operation timeout')
        state=wait();form=state['form']
        form.update(qa_mode='vector',execution_backend='process',workers=1,cpu_choice='1',cpu_unit='logical',telemetry='off')
        api(url,'configure',form);api(url,'preflight',{});wait()
        api(url,'generate',{});result['pdf']=wait()['result']
        result['geometry']=[]
        for width,height in ((1200,800),(1000,700),(900,560),(1200,800)):
            window.resize(width,height);time.sleep(.4)
            metrics=window.evaluate_js("""(()=>{const root=document.querySelector('#ucode-layout');return {
              viewport:[innerWidth,innerHeight],root:[root.clientWidth,root.clientHeight],
              horizontal:document.documentElement.scrollWidth>innerWidth,
              bottom:root.getBoundingClientRect().bottom,
              preview:!!document.querySelector('#uc-qr img')}})()""")
            result['geometry'].append(metrics)
        result['tabs']=[]
        for i in range(8):
            window.evaluate_js(f"document.querySelectorAll('.uc-tabstrip button')[{i}].click()")
            time.sleep(.15)
            result['tabs'].append(window.evaluate_js("""(()=>{const r=document.querySelector('#ucode-layout');const stage=document.querySelector('.uc-stage');return {
              horizontal:document.documentElement.scrollWidth>innerWidth,
              bottom:r.getBoundingClientRect().bottom,height:innerHeight,
              stageHeight:stage.clientHeight}})()"""))
        result['ok']=(duplicate.returncode==0 and result['pdf']['count']==3 and result['pdf']['status']=='LIMITED'
                      and all(not m['horizontal'] and m['bottom']<=m['viewport'][1] for m in result['geometry'])
                      and all(not m['horizontal'] and m['bottom']<=m['height'] and m['stageHeight']>50 for m in result['tabs']))
    except Exception as exc:
        result['error']=repr(exc);result['ok']=False
        if isinstance(exc,HTTPError):result['error_body']=exc.read().decode('utf-8')
    finally:
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        window.destroy()


def start(*args,**kwargs):
    return original_start(run,*args,**kwargs)


if __name__=='__main__':
    webview.start=start
    main(root=folder)
    try:
        url=json.loads((folder/'.local-state/web-runtime.json').read_text())['url']
        api(url,'health');result['session_closed']=False
    except OSError:result['session_closed']=True
    result['ok']=result.get('ok',False) and result['session_closed']
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(folder/'result.json')
    raise SystemExit(0 if result.get('ok') else 1)
