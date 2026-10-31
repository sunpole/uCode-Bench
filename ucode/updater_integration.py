"""Bridge to the independent uCode.Updater.exe.

When packaged on Windows, GUI reads JSON from the independent native binary.
Source/developer execution uses the same read-only Python fallback.
No downloading, installing, shell commands or arbitrary executable paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .update_check import inspect_remote, version_key, REPO_URL


def native_path():
    if os.name == "nt" and getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "uCode.Updater.exe"
    return None


def parse_native_result(raw, installed):
    if not isinstance(raw, dict):
        raise ValueError("Неверный ответ самостоятельного обновлятора")
    latest = raw.get("latest")
    if not isinstance(latest, str):
        raise ValueError("В ответе отсутствует версия")
    old_key = version_key(installed)
    latest_key = version_key(latest)
    expected = ("UPDATE_AVAILABLE" if latest_key > old_key else
                "LOCAL_NEWER" if latest_key < old_key else "CURRENT")
    if raw.get("installed") != installed or raw.get("status") != expected:
        raise ValueError("Обновлятор вернул несовместимые версии")
    if raw.get("release_url") != REPO_URL + "/releases/tag/v" + latest:
        raise ValueError("Обновлятор вернул неизвестную ссылку на выпуск")
    if raw.get("platform") != "windows-x64":
        raise ValueError("Неизвестная платформа обновлятора")
    package = raw.get("package")
    if package is not None:
        expected_name = "uCode-" + latest + "-windows-x64.zip"
        if (not isinstance(package, dict) or
                package.get("name") != expected_name or
                package.get("url") != REPO_URL + "/releases/download/v" + latest + "/" + expected_name or
                type(package.get("size_bytes")) is not int or
                package["size_bytes"] <= 1000):
            raise ValueError("Неверный файл релиза")
    allowed = "AVAILABLE_WITH_CONFIRMATION" if expected == "UPDATE_AVAILABLE" and package else "NOT_APPLICABLE"
    if raw.get("installation") != allowed or raw.get("download") != "NOT_STARTED":
        raise ValueError("Недопустимое действие обновлятора")
    return {
        "application": "uCode", "installed": installed, "latest": latest,
        "status": expected, "platform": "windows-x64",
        "release_url": raw["release_url"], "package": package,
        "installation": allowed, "download": "NOT_STARTED",
        "backend": "native",
        "note": "Никаких файлов программа не изменяла.",
    }


def check_stable_release(*, installed=__version__):
    executable = native_path()
    if executable is None:
        return {**inspect_remote(installed=installed), "backend": "python-source"}
    if not executable.is_file():
        raise FileNotFoundError("Отсутствует независимый uCode.Updater.exe. Восстановите полный пакет uCode.")
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(
        [str(executable), "--check", "--installed", installed],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=12, **options)
    if completed.returncode != 0:
        message = completed.stderr.strip()[-400:] or "Неизвестная ошибка"
        raise OSError("uCode.Updater: " + message)
    try:
        return parse_native_result(json.loads(completed.stdout), installed)
    except json.JSONDecodeError as exc:
        raise ValueError("Независимый обновлятор вернул повреждённый JSON") from exc
