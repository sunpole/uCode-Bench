"""Shared source/frozen process invocation and writable application data."""
import os
from pathlib import Path
import sys

MODULES={'ucode.operation_worker','ucode.lab_worker','ucode.worker','ucode.native_dialog'}

def module_command(module,*args):
    if module not in MODULES:raise ValueError('Unknown internal worker')
    prefix=[sys.executable,'--ucode-worker',module] if getattr(sys,'frozen',False) else [sys.executable,'-m',module]
    return prefix+list(map(str,args))

def user_root():
    if os.environ.get('UCODE_DATA_HOME'):return Path(os.environ['UCODE_DATA_HOME']).expanduser().resolve()
    if not getattr(sys,'frozen',False):return Path.cwd()
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'uBrand/uCode'
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/uCode'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'ucode'
