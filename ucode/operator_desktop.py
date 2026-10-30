"""One native window; the approved page and loopback API remain unchanged."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def api(url, route, value=None):
    token=url.rstrip('/').rsplit('/',1)[-1]
    request=Request(url+'api/'+route,
                    data=None if value is None else json.dumps(value).encode(),
                    headers={'Content-Type':'application/json','X-UCode-Token':token})
    with urlopen(request,timeout=10) as response:return json.load(response)


def activate(pid):
    """Focus only the window owned by the locked desktop process."""
    if os.name!='nt':return
    import ctypes
    from ctypes import wintypes
    user=ctypes.windll.user32
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(hwnd,_):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            user.ShowWindow(hwnd,9);user.SetForegroundWindow(hwnd);return False
        return True
    user.EnumWindows(visit,0)


class DesktopLifecycle:
    def __init__(self,url):self.url=url;self.window=None;self._approved=False

    def closing(self):
        if self._approved:return True
        try:
            if api(self.url,'state')['busy']:
                self.window.evaluate_js('window.ucodeRequestClose && window.ucodeRequestClose()')
                return False
            # Atomically rejects a close racing a newly started operation.
            api(self.url,'shutdown',{})
            self._approved=True
            return True
        except Exception:
            # A connection error is not proof that the generator has stopped.
            return False

    def finish_close(self):
        if self.closing():self.window.destroy()


class DesktopBridge:
    # pywebview recursively exposes public attributes. Never expose a native
    # window, lock or controller graph to its JS binding/introspection.
    def __init__(self,controller):self._controller=controller
    def finish_close(self):self._controller.finish_close()


def main(root=None):
    if os.name=='nt':
        # Before creating any window. Per-monitor V2 preserves Windows scaling;
        # older Windows gets per-monitor awareness where available.
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except AttributeError:pass
    try:import webview
    except ImportError as exc:
        raise RuntimeError('Нужна проектная установка: Setup-Desktop.cmd. Запасной запуск: Start-uCode-Browser.cmd.') from exc
    from .operator_web import main as serve,_runtime_lock
    project=Path(root or Path.cwd()).resolve();private=project/'.local-state';private.mkdir(exist_ok=True)
    lease=_runtime_lock(private/'desktop.lock')
    record=private/'desktop-window.json'
    if lease is None:
        try:activate(int(json.loads(record.read_text())['pid']))
        except (OSError,ValueError,KeyError):pass
        return
    try:
        record.write_text(json.dumps({'pid':os.getpid()}),encoding='utf-8')
        def present(url):
            controller=DesktopLifecycle(url)
            webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=True
            window=webview.create_window('uCode',url=url,js_api=DesktopBridge(controller),
                width=1200,height=800,min_size=(900,560),background_color='#0b1220',
                text_select=True,zoomable=False)
            controller.window=window
            window.events.closing+=controller.closing
            # No silent fallback to the obsolete IE renderer on Windows.
            webview.start(gui='edgechromium' if os.name=='nt' else None,debug=False,
                          private_mode=True,storage_path=str(private/'webview-profile'))
        serve(root=project,open_browser=False,presenter=present)
    finally:lease.close()


if __name__=='__main__':main()
