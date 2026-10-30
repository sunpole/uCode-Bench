"""Offline contract tests for the independent updater bridge."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from ucode import updater_integration as integration


def native_payload():
    return {
        "application": "uCode",
        "installed": "0.3.4", "latest": "0.3.4",
        "platform": "windows-x64", "status": "CURRENT",
        "release_url": "https://github.com/sunpole/uCode-Bench/releases/tag/v0.3.4",
        "package": {
            "name": "uCode-0.3.4-windows-x64.zip",
            "url": "https://github.com/sunpole/uCode-Bench/releases/download/v0.3.4/uCode-0.3.4-windows-x64.zip",
            "size_bytes": 31091021,
        },
        "installation": "NOT_IMPLEMENTED",
        "download": "NOT_STARTED",
    }


class NativeIntegrationTests(unittest.TestCase):
    def test_normal_native_status(self):
        status=integration.parse_native_result(native_payload(),"0.3.4")
        self.assertEqual(status["backend"],"native")
        self.assertEqual(status["status"],"CURRENT")
        self.assertEqual(status["installation"],"NOT_STARTED")

    def test_reject_inconsistent_status_and_bad_links(self):
        data=native_payload()
        data["status"]="UPDATE_AVAILABLE"
        with self.assertRaises(ValueError):
            integration.parse_native_result(data,"0.3.4")
        data=native_payload()
        data["package"]["url"]="https://evil.invalid/app.zip"
        with self.assertRaises(ValueError):
            integration.parse_native_result(data,"0.3.4")
        data=native_payload()
        data["download"]="COMPLETE"
        with self.assertRaises(ValueError):
            integration.parse_native_result(data,"0.3.4")

    def test_unpacked_native_child_is_used_not_python(self):
        payload=native_payload()
        completed=subprocess.CompletedProcess(
            args=["updater"],returncode=0,stdout=json.dumps(payload),stderr="")
        with patch.object(integration,"native_path",return_value=Path(__file__)), \
             patch.object(integration.subprocess,"run",return_value=completed) as run, \
             patch.object(integration,"inspect_remote",side_effect=AssertionError("Unexpected Python fallback")):
            found=integration.check_stable_release(installed="0.3.4")
        self.assertEqual(found["backend"],"native")
        self.assertIn("--installed",run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["timeout"],12)

    def test_no_silent_python_fallback_if_frozen_native_missing(self):
        with patch.object(integration,"native_path",return_value=Path("missing-ucode-updater.exe")):
            with self.assertRaises(FileNotFoundError):
                integration.check_stable_release()

    def test_source_mode_is_explicit_python_fallback(self):
        with patch.object(integration,"native_path",return_value=None), \
             patch.object(integration,"inspect_remote",return_value={"status":"CURRENT"}) as fallback:
            result=integration.check_stable_release()
        self.assertEqual(result["backend"],"python-source")
        fallback.assert_called_once()


if __name__=="__main__":
    unittest.main()
