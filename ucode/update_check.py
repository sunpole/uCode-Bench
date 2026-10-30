"""Read-only GitHub Release discovery.

No telemetry, no installation, no downloader and no automatic checks.
Only an explicit user command invokes the public official GitHub API.
"""
from __future__ import annotations

import json
import platform
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import __version__

API_URL = "https://api.github.com/repos/sunpole/uCode-Bench/releases/latest"
REPO_URL = "https://github.com/sunpole/uCode-Bench"
MAX_RESPONSE = 256 * 1024
VERSION = re.compile(r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.dev(0|[1-9][0-9]*))?$")


def version_key(raw):
    """Only supported canonical numeric versions; never execute remote metadata."""
    if not isinstance(raw, str):
        raise ValueError("Некорректная версия")
    match = VERSION.fullmatch(raw)
    if match is None:
        raise ValueError("Неизвестный формат версии: " + raw[:64])
    major, minor, patch, dev = match.groups()
    return (int(major), int(minor), int(patch), 0 if dev is not None else 1,
            int(dev) if dev is not None else 0)


def current_platform():
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "windows-x64"
    if sys.platform == "linux" and machine in ("amd64", "x86_64"):
        return "linux-x64"
    if sys.platform == "darwin" and machine in ("arm64", "aarch64"):
        return "macos-arm64"
    return None


def release_asset(data, version, system):
    """Return only a safe release-file URL for our exact repository and tag."""
    if system is None:
        return None
    name = "uCode-" + version + "-" + system + (".tar.gz" if system == "linux-x64" else ".zip")
    for asset in data.get("assets", ()):
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            continue
        parts = urlsplit(url)
        expected = "/sunpole/uCode-Bench/releases/download/v" + version + "/" + name
        if parts.scheme != "https" or parts.netloc != "github.com" or parts.path != expected:
            continue
        if parts.query or parts.fragment:
            continue
        size = asset.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 1000:
            continue
        return {"name": name, "url": url, "size_bytes": size}
    return None


def parse_release(raw, *, installed=__version__, system=None):
    """Pure local parser. Does not contact the Internet."""
    if not isinstance(raw, dict) or raw.get("draft") is not False or raw.get("prerelease") is not False:
        raise ValueError("GitHub не вернул опубликованный стабильный релиз")
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Недопустимый тег релиза GitHub")
    if raw.get("html_url") != REPO_URL + "/releases/tag/" + tag:
        raise ValueError("Некорректная ссылка на релиз GitHub")
    assets = raw.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Не найден список файлов релиза GitHub")
    local = version_key(installed)
    published = version_key(tag)
    status = "UPDATE_AVAILABLE" if published > local else "CURRENT" if published == local else "LOCAL_NEWER"
    version = tag[1:]
    return {"application": "uCode", "installed": installed, "latest": version,
            "status": status, "release_url": raw["html_url"],
            "platform": system, "package": release_asset(raw, version, system),
            "installation": "NOT_STARTED", "download": "NOT_STARTED",
            "note": "Только проверка. Файлы и настройки не изменялись."}


def inspect_remote(*, installed=__version__, system=None):
    """Explicit HTTPS read with response-size bound and reasonable timeout."""
    req = Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "uCode-Bench-release-check/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(req, timeout=8) as response:
        payload = response.read(MAX_RESPONSE + 1)
    if len(payload) > MAX_RESPONSE:
        raise ValueError("Ответ GitHub слишком большой")
    data = json.loads(payload.decode("utf-8"))
    return parse_release(data, installed=installed,
                         system=current_platform() if system is None else system)


def cli_main():
    try:
        result = inspect_remote()
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        print("uCode: проверка версии не выполнена: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
