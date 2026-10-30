"""Frozen executable: dispatch workers before importing GUI; guard spawn pools."""
import multiprocessing
multiprocessing.freeze_support()
import os
from pathlib import Path
import runpy
import sys

def main():
    from ucode.distribution import MODULES,user_root
    if sys.argv[1:2]==['--ucode-worker']:
        module=sys.argv[2]
        if module not in MODULES:raise ValueError('Unknown internal worker')
        sys.argv=[module]+sys.argv[3:];runpy.run_module(module,run_name='__main__',alter_sys=True);return 0
    root=user_root();root.mkdir(parents=True,exist_ok=True)
    os.chdir(root)
    if sys.argv[1:2]==['--system-check']:
        from ucode.system_check import main as check
        return check(sys.argv[2:])
    if sys.argv[1:2]==['--smoke']:
        from ucode.distribution_smoke import main as smoke
        return smoke(root)
    if sys.argv[1:2]==['--version']:
        from ucode import __version__
        print(__version__);return 0
    if os.name=='nt' and (len(sys.argv)==1 or sys.argv[1]=='gui'):
        import ctypes
        hwnd=ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:ctypes.windll.user32.ShowWindow(hwnd,0)
    from ucode.__main__ import main as app
    return app()

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        import traceback
        from ucode.distribution import user_root
        root=user_root();root.mkdir(parents=True,exist_ok=True)
        (root/'startup-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        # A modal dialog can block headless CI and command-line users forever.
        # Show it only when the user explicitly started the graphical app.
        graphical=len(sys.argv)==1 or sys.argv[1] in ('gui','batch','gui-legacy','gui-browser')
        if os.name=='nt' and graphical:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(exc)+'\n'+str(root/'startup-error.txt'),'uCode',0x10)
        else:
            import traceback
            traceback.print_exc()
        raise
