"""Update center runtime/API contracts, never access the public Internet."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ucode.operator_web import OperatorHTTP, document, ASSETS, APPROVED_SHA256


class UpdateCenterTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.server=OperatorHTTP(self.folder.name)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.folder.cleanup()

    def request(self,path,body=None,authorized=True):
        payload=None if body is None else json.dumps(body).encode("utf-8")
        headers={}
        if payload is not None:
            headers={"Content-Type":"application/json"}
            if authorized:headers["X-UCode-Token"]=self.server.token
        req=Request(self.server.base+"api/"+path,data=payload,headers=headers)
        with urlopen(req,timeout=6) as r:return json.load(r)

    def test_design_is_immutable_and_extra_tab_is_loaded(self):
        raw=(ASSETS/"operator-approved.html").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),APPROVED_SHA256)
        html=document(self.server.token).decode("utf-8")
        self.assertIn("Центр обновлений",html)
        self.assertIn("uc-center-tab-",html)
        self.assertIn("ucUpTabOrder=[0,4,5,2,3,1,6,7,8]",html)
        self.assertIn("uc-update-center",html)
        self.assertIn("ucUpInstall.disabled=true",html)
        self.assertNotIn("https://cdn.jsdelivr.net/npm/qrcode",html)

    def test_read_only_status_does_not_need_network(self):
        with patch("ucode.update_check.inspect_remote",side_effect=AssertionError("No network")):
            data=self.request("update-info")
        self.assertEqual(data["installed"],"0.3.4")
        self.assertEqual(data["channel"],"stable")
        self.assertEqual(data["installer_status"],"NOT_AVAILABLE")
        self.assertEqual(data["check_mode"],"MANUAL_ONLY")

    def test_user_triggered_check_and_auth(self):
        snapshot={"installed":"0.3.4","latest":"0.3.4","status":"CURRENT",
                  "package":None,"installation":"NOT_STARTED"}
        with patch("ucode.update_check.inspect_remote",return_value=snapshot) as check:
            result=self.request("updates-check",{})
        self.assertEqual(result["status"],"CURRENT")
        check.assert_called_once_with(installed="0.3.4")
        with patch("ucode.update_check.inspect_remote") as check:
            with self.assertRaises(HTTPError) as caught:
                self.request("updates-check",{},authorized=False)
            self.assertEqual(caught.exception.code,403)
            check.assert_not_called()

    def test_open_is_only_fixed_project_page(self):
        with patch("webbrowser.open",return_value=True) as show:
            data=self.request("updates-open",{"ignored":"https://example.org"})
        self.assertTrue(data["opened"])
        show.assert_called_once_with("https://github.com/sunpole/uCode-Bench/releases")


if __name__=="__main__":
    unittest.main()
