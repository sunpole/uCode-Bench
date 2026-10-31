"""Offline Windows update handoff tests: never download or install software."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from ucode.update_install import begin_stable_install, stable_install_status
from ucode.updater_integration import parse_native_result


class InstallHandoffTests(TestCase):
    def test_no_confirmation_cannot_start_install(self):
        with self.assertRaisesRegex(ValueError, "подтверждения"):
            begin_stable_install(Mock(), confirmed=False, requested_version="0.3.5")

    def test_source_python_cannot_install_even_with_confirmation(self):
        with patch("ucode.update_install.os.name", "posix"):
            with self.assertRaisesRegex(ValueError, "Windows EXE"):
                begin_stable_install(Mock(), confirmed=True, requested_version="0.3.5")

    def test_invalid_requested_version_rejected_without_network(self):
        with patch("ucode.update_install.os.name", "nt"), patch(
            "ucode.update_install.sys.frozen", True, create=True
        ):
            with self.assertRaisesRegex(ValueError, "Некорректная версия"):
                begin_stable_install(Mock(), confirmed=True, requested_version="../evil")

    def test_status_log_is_sanitized_and_stage_based(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "safe.log"
            log.write_text("STAGE:downloading-package\n", encoding="utf-8")
            service = Mock(update_process=Mock(), update_log=log)
            service.update_process.poll.return_value = None
            self.assertEqual(stable_install_status(service)["state"], "INSTALLING")
            log.write_text("STAGE:verifying-sha256\nREADY_TO_RESTART\n", encoding="utf-8")
            self.assertEqual(stable_install_status(service)["state"], "RESTART_READY")
            log.write_text("INSTALL_FAILED: InvalidDataException: checksum\n", encoding="utf-8")
            self.assertEqual(stable_install_status(service)["state"], "FAILED")

    def test_install_availability_requires_newer_version_and_exact_package(self):
        def payload(status, installation, latest):
            return dict(
                application="uCode", installed="0.3.4", latest=latest,
                status=status, platform="windows-x64",
                release_url="https://github.com/sunpole/uCode-Bench/releases/tag/v" + latest,
                package={
                    "name": f"uCode-{latest}-windows-x64.zip",
                    "url": "https://github.com/sunpole/uCode-Bench/releases/download/v" +
                           latest + f"/uCode-{latest}-windows-x64.zip",
                    "size_bytes": 31_000_000,
                },
                installation=installation, download="NOT_STARTED",
            )
        valid = payload("UPDATE_AVAILABLE", "AVAILABLE_WITH_CONFIRMATION", "0.3.5")
        self.assertEqual(parse_native_result(valid, "0.3.4")["installation"], "AVAILABLE_WITH_CONFIRMATION")
        invalid = payload("UPDATE_AVAILABLE", "NOT_APPLICABLE", "0.3.5")
        with self.assertRaisesRegex(ValueError, "Недопустимое действие"):
            parse_native_result(invalid, "0.3.4")
