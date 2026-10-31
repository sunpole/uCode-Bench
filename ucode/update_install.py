"""Explicit Windows GUI handoff to the standalone native updater.

No shell, no arbitrary executable path, no quiet background downloads.
Only a user-confirmed request may start a stable update.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

from . import __version__
from .distribution import user_root
from .updater_integration import native_path, check_stable_release


def begin_stable_install(service, *, confirmed: bool, requested_version: str) -> dict:
    if not confirmed:
        raise ValueError("Установка требует явного подтверждения пользователя.")
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise ValueError("Установка из интерфейса доступна только в Windows EXE.")
    if not isinstance(requested_version, str) or not re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", requested_version
    ):
        raise ValueError("Некорректная версия релиза.")
    exe = native_path()
    if exe is None or not exe.is_file():
        raise ValueError("Не найден независимый uCode.Updater.exe.")
    if getattr(service, "update_process", None) is not None:
        if service.update_process.poll() is None:
            raise ValueError("Установка уже запущена.")
    # Check again; never trust the version or arbitrary URL sent from JavaScript.
    release = check_stable_release(installed=__version__)
    if (
        release.get("status") != "UPDATE_AVAILABLE"
        or release.get("latest") != requested_version
        or not release.get("package")
        or release.get("backend") != "native"
    ):
        raise ValueError("Подтверждённая версия больше недоступна как новый stable-релиз.")
    folder = user_root() / "updates" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    logfile = folder / ("updater-" + uuid.uuid4().hex + ".log")
    flags = subprocess.CREATE_NO_WINDOW
    # Log stays in private user data outside installed binaries; never deleted by updater.
    stream = logfile.open("x", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                str(exe),
                "--install", "--installed", __version__, "--accept",
                "--wait-pid", str(os.getpid()),
            ],
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    finally:
        stream.close()
    service.update_process = process
    service.update_log = logfile
    return {"started": True, "state": "INSTALLING", "message": "Запущена проверяемая установка."}



DEV_PLACEHOLDER_SHA = "0" * 40


def installed_development_sha() -> str:
    from .build_info import build_info
    info = build_info()
    sha = info.get("commit") if info.get("channel") == "development" else None
    return sha if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) else DEV_PLACEHOLDER_SHA


def check_development_release() -> dict:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise ValueError("Development-обновление доступно только в Windows EXE.")
    exe = native_path()
    if exe is None or not exe.is_file():
        raise FileNotFoundError("Независимый обновлятор отсутствует.")
    current = installed_development_sha()
    p = subprocess.run(
        [str(exe), "--check-dev", "--current-sha", current],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=16, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if p.returncode:
        raise OSError("Проверка Development-релиза не выполнена.")
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Неверный JSON от обновлятора.") from exc
    latest = data.get("latest_commit")
    if latest is not None and (
        not isinstance(latest, str) or re.fullmatch(r"[a-f0-9]{40}", latest) is None
    ):
        raise ValueError("Недопустимый SHA Development-релиза.")
    status = "NO_PUBLISHED_BUILD" if latest is None else "CURRENT" if latest == current else "UPDATE_AVAILABLE"
    if data.get("application") != "uCode" or data.get("channel") != "development" or (
        data.get("installed_commit") != current or data.get("status") != status
        or data.get("platform") != "windows-x64"
    ):
        raise ValueError("Неверные сведения Development-релиза.")
    from .update_check import REPO_URL
    expected = None if latest is None else REPO_URL + "/releases/tag/dev-" + latest
    if data.get("release_url") != expected:
        raise ValueError("Недействительная ссылка на Development-релиз.")
    package = data.get("package")
    if latest is not None:
        name = "uCode-dev-" + latest[:12] + "-windows-x64.zip"
        if not isinstance(package, dict) or (
            package.get("name") != name or
            package.get("url") != REPO_URL + "/releases/download/dev-" + latest + "/" + name or
            type(package.get("size_bytes")) is not int or package["size_bytes"] < 1024
        ):
            raise ValueError("Недействительный файл Development-релиза.")
    elif package is not None:
        raise ValueError("Пакет без релиза запрещён.")
    return {**data, "backend": "native", "latest": latest[:12] if latest else None}


def begin_development_install(service, *, confirmed: bool, requested_commit: str) -> dict:
    if not confirmed:
        raise ValueError("Установка требует явного подтверждения.")
    if not isinstance(requested_commit, str) or not re.fullmatch(r"[a-f0-9]{40}", requested_commit):
        raise ValueError("Некорректный SHA Development-релиза.")
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise ValueError("Установка поддерживается только в Windows EXE.")
    exe = native_path()
    if exe is None or not exe.is_file():
        raise FileNotFoundError("Нет uCode.Updater.exe.")
    if getattr(service, "update_process", None) is not None and service.update_process.poll() is None:
        raise ValueError("Установка уже запущена.")
    verified = check_development_release()
    if verified.get("status") != "UPDATE_AVAILABLE" or verified.get("latest_commit") != requested_commit:
        raise ValueError("Подтверждённая Development-сборка больше не актуальна.")
    folder = user_root() / "updates" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    logfile = folder / ("dev-updater-" + uuid.uuid4().hex + ".log")
    stream = logfile.open("x", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                str(exe), "--install-dev", "--current-sha", installed_development_sha(),
                "--accept", "--wait-pid", str(os.getpid()),
            ],
            cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    finally:
        stream.close()
    service.update_process = process
    service.update_log = logfile
    return {"started": True, "state": "INSTALLING", "channel": "development"}

def stable_install_status(service) -> dict:
    process = getattr(service, "update_process", None)
    logfile = getattr(service, "update_log", None)
    if process is None or logfile is None:
        return {"state": "IDLE", "message": "Установка не запускалась."}
    try:
        with Path(logfile).open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 12_000))
            text = stream.read(12_000).decode("utf-8", errors="replace")
    except OSError:
        text = ""
    if "INSTALL_FAILED:" in text or process.poll() not in (None, 0):
        return {"state": "FAILED", "message": "Не удалось установить обновление. Проверьте журнал обновлятора."}
    if "READY_TO_RESTART" in text:
        return {"state": "RESTART_READY", "message": "Новая версия проверена. Закрываем старую программу."}
    stages = {
        "checking-release": "Проверка стабильного релиза…",
        "downloading-checksums": "Получение контрольных сумм…",
        "downloading-package": "Скачивание новой версии…",
        "verifying-sha256": "Проверка SHA-256…",
        "extracting": "Распаковка в отдельную папку…",
        "smoke-test": "Проверка запуска и PDF новой версии…",
        "installed": "Подготовка перезапуска…",
    }
    markers = re.findall(r"STAGE:([a-z0-9-]+)", text)
    last = markers[-1] if markers else None
    if process.poll() == 0:
        return {"state": "FINISHED", "message": "Обновлятор завершил работу."}
    return {"state": "INSTALLING", "message": stages.get(last, "Подготовка установки…")}
