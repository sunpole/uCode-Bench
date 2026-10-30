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
        def until_js(expression):
            end=time.monotonic()+10
            while time.monotonic()<end:
                if window.evaluate_js(expression):return
                time.sleep(.1)
            raise TimeoutError(expression)
        if '--order-flow' in sys.argv:
            until_js("!!document.querySelector('#uc-output-name')?.value")
            until_js("window.ucodeReady===true")
            if window.evaluate_js("document.querySelector('#uc-center-tab-0').getAttribute('aria-selected')")!='true':
                raise AssertionError('Startup must always show Types, including restored databases')
            window.evaluate_js("document.querySelector('#uc-center-panel-0 .uc-type button').click()")
            until_js("document.querySelector('#uc-center-tab-4').getAttribute('aria-selected')==='true'")
        api(url,'sequence',{'start':'500000000000','count':3,'step':1})
        def wait():
            end=time.monotonic()+20
            while time.monotonic()<end:
                state=api(url,'state')
                if not state['busy']:return state
                time.sleep(.05)
            raise TimeoutError('Small operation timeout')
        state=wait()
        if '--order-flow' in sys.argv:
            until_js("document.querySelector('#uc-center-tab-5').getAttribute('aria-selected')==='true'")
            window.evaluate_js("(()=>{const n=document.querySelector('#uc-output-name');n.value='Custom.PDF.pdf';n.dispatchEvent(new Event('input',{bubbles:true}));})()")
            until_js("document.querySelector('#uc-output-name').value==='Custom.pdf'")
            window.evaluate_js("[...document.querySelectorAll('#uc-center-panel-5 button')].find(b=>b.textContent==='Подтвердить').click()")
            until_js("document.querySelector('#uc-center-tab-2').getAttribute('aria-selected')==='true'")
            until_js("document.querySelector('.uc-style-preview-split img').complete && document.querySelector('.uc-style-preview-split img').naturalWidth>0")
            result['order_flow']='PASS: type/base/path/style; manual name; actual style preview'
            if '--ecc' in sys.argv:
                for level in 'LMQH':
                    window.evaluate_js("document.querySelector('[data-ecc="+level+"]').click()")
                    until_js("document.querySelector('[data-ecc="+level+"]').getAttribute('aria-pressed')==='true'")
                    deadline=time.monotonic()+10
                    while api(url,'state')['form']['print'].get('error_correction')!=level:
                        if time.monotonic()>deadline:raise TimeoutError('Correction was not applied')
                        time.sleep(.1)
                result['ecc_controls']='PASS: L/M/Q/H; final PDF H'

        if '--content' in sys.argv:
            window.evaluate_js("document.querySelector('#uc-center-tab-4').click();document.querySelector('#uc-mode-content').click();document.querySelector('#uc-content-text').value='Привет из uCode!';document.querySelector('#uc-use-content').click()")
            until_js("document.querySelector('#uc-center-tab-5').getAttribute('aria-selected')==='true' && document.querySelector('#uc-payload-view').value==='Привет из uCode!'")
            assert api(url,'state')['content_kind']=='text'
            result['content']='PASS: native content form + Cyrillic; PDF1'
        form=api(url,'state')['form']
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
        result['ok']=(duplicate.returncode==0 and result['pdf']['count']==(1 if '--content' in sys.argv else 3) and result['pdf']['status']=='LIMITED'
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
    if '--restored-source' in sys.argv:
        from ucode.operator_service import OperatorService
        service=OperatorService(folder);service.sequence({'start':'500000000000','count':3,'step':1})
        while service.busy:service.pump();time.sleep(.05)
        if service.index is None:raise RuntimeError('Fixture source was not saved')
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
