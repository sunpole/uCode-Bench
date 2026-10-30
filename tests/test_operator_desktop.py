import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from ucode.operator_desktop import DesktopLifecycle,DesktopBridge,api
from ucode.operator_web import OperatorHTTP,main,_runtime_lock


class DesktopTests(unittest.TestCase):
    def test_bridge_never_exposes_native_object_graph(self):
        controller=Mock();bridge=DesktopBridge(controller)
        self.assertEqual([name for name in dir(bridge) if not name.startswith('_')],['finish_close'])
        bridge.finish_close();controller.finish_close.assert_called_once()

    def test_close_idle_releases_session_and_busy_close_requires_existing_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            server=OperatorHTTP(folder)
            thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                controller=DesktopLifecycle(server.base);controller.window=Mock()
                server.service.busy=True
                self.assertFalse(controller.closing())
                controller.window.evaluate_js.assert_called_once()
                self.assertFalse(server.service.cancel.is_set())
                self.assertFalse(server.service.closed)
                server.service.busy=False
                controller.finish_close()
                self.assertTrue(server.service.closed)
                controller.window.destroy.assert_called_once()
            finally:server.shutdown();thread.join(5);server.server_close()

    def test_failed_connection_does_not_claim_worker_stopped(self):
        controller=DesktopLifecycle('unused');controller.window=Mock()
        with patch('ucode.operator_desktop.api',side_effect=OSError):
            self.assertFalse(controller.closing())
        controller.window.destroy.assert_not_called()

    def test_real_presenter_session_has_api_and_releases_port_and_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            seen=[]
            def present(url):
                seen.append(url);self.assertEqual(api(url,'health')['application'],'uCode')
                self.assertFalse(api(url,'state')['busy'])
                api(url,'shutdown',{})
            main(root=folder,open_browser=False,presenter=present)
            lease=_runtime_lock(Path(folder)/'.local-state/web-runtime.lock')
            self.assertIsNotNone(lease);lease.close()
            with self.assertRaises(OSError):api(seen[0],'health')
