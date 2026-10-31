"""Development update contracts: offline, no downloads or disk installs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from ucode import update_install


SHA = "a" * 40
OLD = "b" * 40
BASE = "https://github.com/sunpole/uCode-Bench"


def payload(sha=SHA):
    name = "uCode-dev-" + sha[:12] + "-windows-x64.zip"
    return {
        "application": "uCode",
        "channel": "development",
        "installed_commit": OLD,
        "latest_commit": sha,
        "status": "UPDATE_AVAILABLE",
        "platform": "windows-x64",
        "release_url": BASE + "/releases/tag/dev-" + sha,
        "package": {
            "name": name,
            "url": BASE + "/releases/download/dev-" + sha + "/" + name,
            "size_bytes": 32000000,
        },
        "installation": "AVAILABLE_WITH_CONFIRMATION",
    }


class DevelopmentUpdateTests(unittest.TestCase):
    def test_never_install_without_confirm(self):
        with self.assertRaisesRegex(ValueError, "подтверждения"):
            update_install.begin_development_install(
                Mock(), confirmed=False, requested_commit=SHA
            )

    def test_no_source_mode_dev_install(self):
        with patch.object(update_install.os, "name", "posix"):
            with self.assertRaisesRegex(ValueError, "Windows EXE"):
                update_install.begin_development_install(
                    Mock(), confirmed=True, requested_commit=SHA
                )

    def test_path_traversal_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "SHA"):
            update_install.begin_development_install(
                Mock(), confirmed=True, requested_commit="../bad"
            )

    def test_current_sha_defaults_to_zeros_for_stable_to_dev(self):
        with patch("ucode.build_info.build_info", return_value={"channel": "stable", "commit": SHA}):
            self.assertEqual(update_install.installed_development_sha(), "0"*40)

    def test_real_preview_commit_is_read(self):
        with patch("ucode.build_info.build_info", return_value={"channel": "development", "commit": OLD}):
            self.assertEqual(update_install.installed_development_sha(), OLD)

    def test_dev_check_accepts_exact_official_urls(self):
        with patch.object(update_install.os, "name", "nt"), \
             patch.object(update_install.sys, "frozen", True, create=True), \
             patch.object(update_install, "native_path", return_value=Path(__file__)), \
             patch.object(update_install, "installed_development_sha", return_value=OLD), \
             patch.object(update_install.subprocess, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0,
                              stdout=json.dumps(payload()), stderr="")) as native:
            result = update_install.check_development_release()
        self.assertEqual(result["latest_commit"], SHA)
        self.assertEqual(result["backend"], "native")
        self.assertEqual(native.call_args.args[0][1:3], ["--check-dev", "--current-sha"])

    def test_dev_check_rejects_untrusted_release_url(self):
        bad = payload()
        bad["release_url"] = "https://example.com/install.exe"
        with patch.object(update_install.os, "name", "nt"), \
             patch.object(update_install.sys, "frozen", True, create=True), \
             patch.object(update_install, "native_path", return_value=Path(__file__)), \
             patch.object(update_install, "installed_development_sha", return_value=OLD), \
             patch.object(update_install.subprocess, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0,
                              stdout=json.dumps(bad), stderr="")):
            with self.assertRaisesRegex(ValueError, "ссылка"):
                update_install.check_development_release()

    def test_dev_check_rejects_disguised_zip(self):
        bad = payload()
        bad["package"]["url"] = "https://malicious.invalid/uCode.zip"
        with patch.object(update_install.os, "name", "nt"), \
             patch.object(update_install.sys, "frozen", True, create=True), \
             patch.object(update_install, "native_path", return_value=Path(__file__)), \
             patch.object(update_install, "installed_development_sha", return_value=OLD), \
             patch.object(update_install.subprocess, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0,
                              stdout=json.dumps(bad), stderr="")):
            with self.assertRaisesRegex(ValueError, "файл"):
                update_install.check_development_release()


if __name__ == "__main__":
    unittest.main()
