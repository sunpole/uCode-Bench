"""Offline-only tests for opt-in GitHub release discovery."""
import io
import json
import unittest
from unittest.mock import patch

from ucode import update_check as check


def release(tag="v0.3.4", *, draft=False, prerelease=False, url=None):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": check.REPO_URL + "/releases/tag/" + tag,
        "assets": [
            {"name": "uCode-0.3.4-windows-x64.zip",
             "browser_download_url": url or check.REPO_URL +
                "/releases/download/v0.3.4/uCode-0.3.4-windows-x64.zip",
             "size": 31091021},
            {"name": "SHA256SUMS.txt",
             "browser_download_url": check.REPO_URL +
                "/releases/download/v0.3.4/SHA256SUMS.txt",
             "size": 283},
        ],
    }


class UpdateCheckTests(unittest.TestCase):
    def test_just_published_release_is_current(self):
        status = check.parse_release(release(), installed="0.3.4",
                                     system="windows-x64")
        self.assertEqual(status["status"], "CURRENT")
        self.assertEqual(status["latest"], "0.3.4")
        self.assertEqual(status["package"]["name"],
                         "uCode-0.3.4-windows-x64.zip")
        self.assertEqual(status["download"], "NOT_STARTED")
        self.assertEqual(status["installation"], "NOT_STARTED")

    def test_release_upgrade_and_development_versions(self):
        self.assertEqual(check.parse_release(release(), installed="0.3.0")["status"],
                         "UPDATE_AVAILABLE")
        self.assertEqual(check.parse_release(release(), installed="0.3.5.dev0")["status"],
                         "LOCAL_NEWER")
        self.assertLess(check.version_key("0.3.4.dev0"),
                        check.version_key("v0.3.4"))

    def test_foreign_or_modified_asset_urls_are_never_recommended(self):
        wrong = release(url="https://example.com/malicious.zip")
        found = check.parse_release(wrong, system="windows-x64")
        self.assertIsNone(found["package"])
        strange = release(url=check.REPO_URL +
                          "/releases/download/v0.3.4/uCode-0.3.4-windows-x64.zip?tracking=1")
        self.assertIsNone(check.parse_release(strange, system="windows-x64")["package"])

    def test_draft_and_prerelease_are_not_stable(self):
        with self.assertRaises(ValueError):
            check.parse_release(release(draft=True))
        with self.assertRaises(ValueError):
            check.parse_release(release(prerelease=True))

    def test_invalid_version_and_wrong_repo_rejected(self):
        with self.assertRaises(ValueError):
            check.version_key("0.3.4a/b")
        with self.assertRaises(ValueError):
            check.parse_release(release(tag="v0.3.4-rc1"))
        wrong=release()
        wrong["html_url"]="https://another.example.com/release"
        with self.assertRaises(ValueError):
            check.parse_release(wrong)

    def test_network_only_with_explicit_invocation_bounded_read(self):
        payload=json.dumps(release()).encode("utf-8")
        with patch.object(check,"urlopen",return_value=io.BytesIO(payload)) as fetch:
            status=check.inspect_remote(installed="0.3.4",system="windows-x64")
        self.assertEqual(status["status"],"CURRENT")
        self.assertEqual(fetch.call_args.kwargs["timeout"],8)

    def test_oversized_response_rejected(self):
        with patch.object(check,"urlopen",
                          return_value=io.BytesIO(b"x"*(check.MAX_RESPONSE+1))):
            with self.assertRaisesRegex(ValueError,"большой"):
                check.inspect_remote()

    def test_unsupported_platform_has_no_package(self):
        status=check.parse_release(release(),system=None)
        self.assertIsNone(status["package"])


if __name__ == "__main__":
    unittest.main()
