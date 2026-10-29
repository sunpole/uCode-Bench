"""Small UI/help proof; no benchmark or screenshots. Optional saved JSON input."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);args=parser.parse_args()
    from ucode.batch import _make_directory
    from ucode.batch_gui import BatchWindow
    from ucode.brand import ASSETS,SVG_SHA256
    from ucode.help_content import TOPICS
    from ucode.help_report import write_help
    from ucode.hardware import inspect_hardware
    from ucode.lab_worker import code_fingerprint,atomic_json
    from ucode.result_presentation import test_outcome
    from ucode.test_archive import write_text_report
    project=Path(__file__).resolve().parents[1];folder=_make_directory(project/'output/ui-help-proof','small')
    assert hashlib.sha256((ASSETS/'ubrand.svg').read_bytes()).hexdigest()==SVG_SHA256
    report=write_help(folder,inspect_hardware(folder));sizes=[]
    saved=None;source_hash=None
    if args.source:
        source_hash=hashlib.sha256(args.source.read_bytes()).hexdigest()
        saved=json.loads(args.source.read_text(encoding='utf-8'))
        write_text_report(folder/'saved-result-view.html',saved,'Сохранённый тест · понятная сводка')
    for scale in (96/72,120/72,144/72):
        root=tk.Tk();root.withdraw();root.tk.call('tk','scaling',scale)
        app=BatchWindow(root,folder/f'dpi-{scale:g}'/'out');max_w=max_h=0
        try:
            app.show_help()
            for topic in TOPICS:
                app.help_view.show(topic['id'])
                for part in range(3):
                    app.help_view.part.set(part);app.help_view.render();root.update_idletasks()
                    max_w=max(max_w,root.winfo_reqwidth());max_h=max(max_h,root.winfo_reqheight())
            if saved:
                app.present_test(saved);root.update_idletasks()
                max_w=max(max_w,root.winfo_reqwidth());max_h=max(max_h,root.winfo_reqheight())
            assert max_w<=1326 and max_h<=668,(scale,max_w,max_h)
            sizes.append({'scale':scale,'max_width':max_w,'max_height':max_h})
        finally:root.destroy();del app,root;gc.collect()
    if args.source:assert hashlib.sha256(args.source.read_bytes()).hexdigest()==source_hash
    proof={'kind':'ui-help-ubrand-verification','source_digest':code_fingerprint(),'svg_sha256':SVG_SHA256,
           'topics':len(TOPICS),'native_geometry':sizes,'saved_result':test_outcome(saved) if saved else None,
           'saved_json_unchanged':True if saved else None,'benchmark':'NOT_RUN','visual_acceptance':'USER-CHECK'}
    atomic_json(folder/'verification.json',proof)
    public=project/'results/ui-help';public.mkdir(parents=True,exist_ok=True);atomic_json(public/'verification.json',proof)
    (project/'output/ui-help-current-path.txt').write_text(str(report.resolve()),encoding='utf-8')
    print(json.dumps({'folder':str(folder),'help':str(report),'saved_view':str(folder/'saved-result-view.html') if saved else None,'proof':proof},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
