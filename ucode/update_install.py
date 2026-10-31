"""Explicit Windows GUI handoff to the standalone native updater.

No shell, no arbitrary executable path, no quiet background downloads.
Only a user-confirmed request may start a stable update.
"""
from __future__ import annotations

import os
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
    if "READY_TO_RESTART" in text:
        return {"state": "RESTART_READY", "message": "Новая версия проверена. Закрываем старую программу."}
    if "INSTALL_FAILED:" in text or process.poll() not in (None, 0):
        return {"state": "FAILED", "message": "Не удалось установить обновление. Проверьте журнал обновлятора."}
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
