"""Read-only recipient compatibility check; no global installs or changes."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import sys

def webview_version():
    if sys.platform!='win32':return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive,r'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',0,winreg.KEY_READ|view) as key:
                    value=winreg.QueryValueEx(key,'pv')[0]
                    if value and value!='0.0.0.0':return value
            except OSError:pass
    return None

def inspect():
    issues=[];desktop=[]
    if sys.platform not in ('win32','linux','darwin'):issues.append('Поддерживаются Windows, Linux и macOS')
    if struct.calcsize('P')!=8:issues.append('Нужна 64-битная система и сборка')
    if sys.version_info<(3,10):issues.append('Нужен Python 3.10+ (в готовой сборке он включён)')
    for name in ('reportlab','pypdf','PIL','tkinter'):
        if importlib.util.find_spec(name) is None:issues.append('Нет компонента: '+name)
    if importlib.util.find_spec('webview') is None:desktop.append('Нет pywebview: запустите Setup')
    runtime=webview_version()
    if sys.platform=='win32':
        if sys.getwindowsversion().major<10:desktop.append('Нужна Windows 10/11')
        if not runtime:desktop.append('Нет WebView2 Runtime: https://developer.microsoft.com/microsoft-edge/webview2/')
    elif sys.platform=='linux':
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):desktop.append('Нет графического сеанса DISPLAY/Wayland')
        if importlib.util.find_spec('PySide6') is None:desktop.append('Нет Qt/PySide6: запустите Setup')
    elif sys.platform=='darwin' and int(platform.mac_ver()[0].split('.')[0] or 0)<12:desktop.append('Для готовой сборки рекомендуется macOS 12+; используйте подходящий релиз для вашей ОС')
    from . import __version__
    return {'version':__version__,'platform':sys.platform,'architecture':platform.machine(),'python':platform.python_version(),
            'frozen':bool(getattr(sys,'frozen',False)),'core_ready':not issues,'desktop_ready':not issues and not desktop,
            'issues':issues,'desktop_issues':desktop,'webview2':runtime,'raster_qa_available':bool(shutil.which('pdftoppm')),
            'optional_engines':'Дополнительные движки не обязательны; недоступные адаптеры видны в программе'}

def main(argv=None):
    result=inspect();print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['desktop_ready'] else 2

if __name__=='__main__':raise SystemExit(main())
