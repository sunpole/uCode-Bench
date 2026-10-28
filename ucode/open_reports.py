"""Open HTML using the web browser, independently of Windows HTML editors."""
import ctypes
from pathlib import Path
import subprocess
import sys
import webbrowser


def _windows_browser_executable():
    from ctypes import wintypes as w
    query=ctypes.WinDLL("shlwapi").AssocQueryStringW
    query.argtypes=(w.DWORD,w.DWORD,w.LPCWSTR,w.LPCWSTR,w.LPWSTR,ctypes.POINTER(w.DWORD))
    query.restype=w.LONG
    # ASSOCF_IS_PROTOCOL, ASSOCSTR_EXECUTABLE. Query HTTPS/HTTP, never .html.
    for protocol in ("https","http"):
        size=w.DWORD()
        query(0x1000,2,protocol,"open",None,ctypes.byref(size))
        if not 1<size.value<32768: continue
        value=ctypes.create_unicode_buffer(size.value)
        if query(0x1000,2,protocol,"open",value,ctypes.byref(size))==0:
            executable=Path(value.value)
            if executable.is_file(): return executable
    raise OSError("Не найден браузер по умолчанию для HTTPS/HTTP. Назначьте браузер в настройках Windows.")


def open_html_report(path):
    path=Path(path).resolve()
    if not path.is_file(): raise FileNotFoundError("Отчёт ещё не создан: "+str(path))
    if path.suffix.lower() not in (".html",".htm"): raise ValueError("Ожидается HTML-отчёт")
    if sys.platform=="win32":
        executable=_windows_browser_executable()
        subprocess.Popen([str(executable),path.as_uri()],creationflags=0x08000000,close_fds=True)
    elif not webbrowser.open_new_tab(path.as_uri()):
        raise OSError("Не удалось открыть браузер. Откройте отчёт вручную в браузере.")
