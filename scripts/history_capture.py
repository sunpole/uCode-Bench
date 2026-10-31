#!/usr/bin/env python3
"""Capture verifiable screenshots of a historical uCode browser UI.

Read-only UI navigation: never generates PDFs, changes a release, or publishes data.
A local ephemeral project directory prevents changes to the operator's working files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def save_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def file_info(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(PNG_HEADER) or len(data) < 1500:
        raise RuntimeError("Capture is empty or is not a valid PNG")
    return {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_health(base: str) -> dict:
    with urlopen(base + "api/health", timeout=3) as result:
        return json.load(result)


def wait_for_server(project: Path, process: subprocess.Popen, timeout: float = 75) -> tuple[str, dict]:
    runtime = project / ".local-state" / "web-runtime.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Historical uCode server exited before reporting ready")
        try:
            record = json.loads(runtime.read_text(encoding="utf-8"))
            base = record["url"]
            if not re.fullmatch(r"http://127\.0\.0\.1:\d+/[A-Za-z0-9_-]+/", base):
                raise RuntimeError("Unexpected server URL; refusing to contact it")
            response = read_health(base)
            if response.get("application") == "uCode":
                return base, response
        except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError, ValueError):
            pass
        time.sleep(0.35)
    raise RuntimeError("Timeout waiting for the local historical uCode server")


def shutdown(base: str | None, process: subprocess.Popen | None) -> None:
    if not process:
        return
    if base and process.poll() is None:
        try:
            token = base.rstrip("/").rsplit("/", 1)[-1]
            request = Request(
                base + "api/shutdown",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-UCode-Token": token},
                method="POST",
            )
            with urlopen(request, timeout=3):
                pass
        except (OSError, ValueError):
            pass
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def capture(source_root: Path, output: Path, expected_version: str, source_ref: str, commit: str) -> dict:
    from playwright.sync_api import sync_playwright
    import ucode

    source_root = source_root.resolve()
    actual_module = Path(ucode.__file__).resolve()
    if not actual_module.is_relative_to(source_root):
        raise RuntimeError("The installed uCode package does not belong to the checked-out historical source")
    if ucode.__version__ != expected_version:
        raise RuntimeError("Historical package version does not match the selected release")

    output.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "schema": 1,
        "project": "uCode",
        "version": expected_version,
        "source_ref": source_ref,
        "source_commit": commit,
        "mode": "real-browser-loopback",
        "os": platform.system(),
        "viewport": {"width": 1440, "height": 900, "scale": 1},
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "status": "STARTED",
        "screenshots": [],
    }
    save_json(output / "manifest.json", manifest)
    base = None
    process = None

    try:
        with tempfile.TemporaryDirectory(prefix="ucode-history-") as temp:
            project = Path(temp)
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            script = "import sys; from ucode.operator_web import main; main(root=sys.argv[1],open_browser=False)"
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(project)],
                cwd=str(source_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            base, health = wait_for_server(project, process)
            if health.get("version") != expected_version:
                raise RuntimeError("Running server version does not match the historical release")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 900},
                        device_scale_factor=1,
                        locale="ru-RU",
                        color_scheme="dark",
                        reduced_motion="reduce",
                    )
                    # No third-party requests; the real local UI and API are all that is needed.
                    def route_request(route):
                        url = route.request.url
                        if url.startswith(base) or url.startswith("data:"):
                            route.continue_()
                        else:
                            route.abort()
                    context.route("**/*", route_request)
                    page = context.new_page()
                    page.goto(base, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_function("window.ucodeReady === true", timeout=60000)
                    page.locator("#ucode-layout").wait_for(state="visible", timeout=15000)
                    tabs = page.get_by_role("tab")
                    number_of_tabs = tabs.count()
                    if number_of_tabs < 4:
                        raise RuntimeError("Expected uCode navigation tabs were not detected")
                    for index in range(number_of_tabs):
                        tab = page.get_by_role("tab").nth(index)
                        title = tab.inner_text().strip()
                        tab.click(timeout=15000)
                        page.wait_for_function(
                            "i => { const el=document.querySelectorAll('[role=tab]')[i]; return !!el && el.getAttribute('aria-selected')==='true' }",
                            arg=index,
                            timeout=15000,
                        )
                        page.wait_for_timeout(250)
                        filename = f"{index + 1:02d}-tab.png"
                        image = output / filename
                        page.screenshot(path=str(image), full_page=True, animations="disabled")
                        manifest["screenshots"].append({
                            **file_info(image), "tab_index": index, "tab_title": title
                        })
                        save_json(output / "manifest.json", manifest)
                    context.close()
                finally:
                    browser.close()

        manifest["status"] = "PASS"
        manifest["count"] = len(manifest["screenshots"])
        save_json(output / "manifest.json", manifest)
        return manifest
    except Exception as exc:
        # Never print the capability token, local directory or personal data.
        manifest["status"] = "FAILED"
        manifest["error_type"] = type(exc).__name__
        manifest["count"] = len(manifest["screenshots"])
        save_json(output / "manifest.json", manifest)
        raise RuntimeError("History capture failed; see manifest status and CI steps") from None
    finally:
        shutdown(base, process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture historical uCode UI screenshots")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = capture(
        args.source_root, args.output, args.expected_version, args.source_ref, args.source_commit
    )
    print(f"uCode History Capture: {result['status']}; screenshots: {result['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
