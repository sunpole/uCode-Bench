"""Bounded, shell-free CLI execution with Windows child resource accounting."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
from ..runtime import resolve_executable

from .base import Adapter, MergeError


def creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def process_metrics(process: subprocess.Popen) -> dict:
    if os.name != "nt":
        return {"child_cpu_seconds": None, "child_peak_rss_bytes": None,
                "resource_note": "Child resource counters are only implemented on Windows"}
    try:
        handle = wintypes.HANDLE(int(process._handle))
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_times = kernel32.GetProcessTimes
        get_times.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        get_times.restype = wintypes.BOOL
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not get_times(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        memory.restype = wintypes.BOOL
        if not memory(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        ticks = sum((item.dwHighDateTime << 32) | item.dwLowDateTime for item in (kernel, user))
        return {"child_cpu_seconds": ticks / 10_000_000,
                "child_peak_rss_bytes": int(counters.PeakWorkingSetSize)}
    except Exception as exc:
        return {"child_cpu_seconds": None, "child_peak_rss_bytes": None,
                "resource_note": f"Windows child resource query failed: {exc}"}


def run_engine(argv: list[str], *, stdin_bytes: bytes | None = None, timeout: float = 120, cwd=None) -> dict:
    """Run one foreground engine, killing and reaping it on timeout."""
    if os.name == "nt" and len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2 >= 30_000:
        raise MergeError("Windows command line is too long for this adapter; no shell or partial merge was used")
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                   creationflags=creation_flags(), cwd=cwd)
    except OSError as exc:
        raise MergeError(f"Cannot launch {Path(argv[0]).name}: {exc}") from exc
    try:
        stdout, stderr = process.communicate(input=stdin_bytes, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise MergeError(f"{Path(argv[0]).name} exceeded {timeout:g} seconds and was terminated") from exc
    metrics = process_metrics(process)
    if process.returncode != 0:
        diagnostic = (stderr or stdout).decode("utf-8", errors="replace").strip()[-2000:]
        raise MergeError(f"{Path(argv[0]).name} exited with code {process.returncode}: {diagnostic}")
    return metrics


class ExternalAdapter(Adapter):
    external = True
    command = ""
    version_args: tuple[str, ...] = ("--version",)

    def probe(self) -> dict:
        executable = resolve_executable(self.command)
        if not executable:
            return {"available": False, "reason": f"{self.command} was not found on PATH", "version": None}
        try:
            completed = subprocess.run([executable, *self.version_args], capture_output=True, timeout=5,
                                       shell=False, creationflags=creation_flags())
            if completed.returncode != 0:
                return {"available": False, "reason": f"Version probe exited with code {completed.returncode}", "version": None,
                        "executable": executable}
            version = (completed.stdout or completed.stderr).decode("utf-8", errors="replace").strip().splitlines()
            return {"available": True, "reason": "", "version": version[0] if version else "unknown",
                    "executable": executable}
        except Exception as exc:
            return {"available": False, "reason": f"Version probe failed: {exc}", "version": None,
                    "executable": executable}

    def executable(self) -> str:
        executable = resolve_executable(self.command)
        if not executable:
            raise MergeError(f"{self.command} was not found on PATH")
        return executable
