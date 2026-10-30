"""Useful-data RAM budgets and sampled RSS of this trial's own process tree."""
import ctypes
import os
from pathlib import Path
import threading
import time

from .hardware import memory_info

MIB = 1024**2
GIB = 1024**3


def ram_budget(mode, available):
    if available is None or available <= 0:
        raise ValueError("Неизвестна доступная RAM")
    reserve = max(GIB, available // 10)
    safe = max(0, available - reserve)
    fractions = {"auto": .8, "50%": .5, "80%": .8, "max": 1}
    if mode in fractions:
        budget = int(safe * fractions[mode])
    elif isinstance(mode, str) and mode.endswith("MiB") and mode[:-3].isdigit():
        budget = int(mode[:-3]) * MIB
        if budget > safe: raise ValueError("RAM budget больше доступного безопасного бюджета")
    else:
        raise ValueError("RAM: auto, 50%, 80%, max или число с MiB")
    if budget < 256 * MIB:
        raise ValueError("RAM budget меньше 256 МиБ после резерва ОС")
    return {"mode": mode, "available_at_start_bytes": available, "reserve_bytes": reserve,
            "budget_bytes": budget, "force_allocation": False,
            "scope": "Useful QR/PDF data only; no artificial RAM fill"}


def create_owned_job(limit,process_handle=None):
    """Windows nested job: own trial + inherited children, no global changes.

    Retain returned handle until process exit. Closing it kills this job's tree.
    Linux uses its own session/process group + sampled memory guard instead.
    """
    if os.name != "nt": return None
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", w.DWORD), ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
    class Limits(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = (ctypes.c_void_p, w.LPCWSTR); api.CreateJobObjectW.restype = w.HANDLE
    api.SetInformationJobObject.argtypes = (w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD)
    api.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
    api.GetCurrentProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = (w.HANDLE,)
    handle = api.CreateJobObjectW(None, None)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    limits = Limits(); limits.basic.flags = 0x2000 | 0x200; limits.job_memory = limit
    if not api.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        api.CloseHandle(handle); raise ctypes.WinError(ctypes.get_last_error())
    if not api.AssignProcessToJobObject(handle, process_handle if process_handle is not None else api.GetCurrentProcess()):
        api.CloseHandle(handle); raise ctypes.WinError(ctypes.get_last_error())
    return handle


def close_owned_job(handle):
    if handle is not None and os.name=='nt':
        from ctypes import wintypes as w
        api=ctypes.WinDLL('kernel32',use_last_error=True);api.CloseHandle.argtypes=(w.HANDLE,)
        if not api.CloseHandle(handle):raise ctypes.WinError(ctypes.get_last_error())


def _windows_processes():
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD), ("heap", ctypes.c_size_t),
                    ("module", w.DWORD), ("threads", w.DWORD), ("parent", w.DWORD),
                    ("priority", w.LONG), ("flags", w.DWORD), ("name", w.WCHAR * 260)]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = (w.DWORD, w.DWORD); api.CreateToolhelp32Snapshot.restype = w.HANDLE
    api.Process32FirstW.argtypes = api.Process32NextW.argtypes = (w.HANDLE, ctypes.POINTER(Entry))
    api.CloseHandle.argtypes = (w.HANDLE,)
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value: raise OSError("Process snapshot недоступен")
    mapping = {}
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        ok = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            mapping[entry.pid] = entry.parent
            ok = api.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    return mapping


def _windows_stats(pid):
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("faults", w.DWORD)] + [(name, ctypes.c_size_t) for name in
                    ("peak", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD); api.OpenProcess.restype = w.HANDLE
    api.GetProcessTimes.argtypes = (w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4))
    api.CloseHandle.argtypes = (w.HANDLE,)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = (w.HANDLE, ctypes.POINTER(Counters), w.DWORD)
    handle = api.OpenProcess(0x410, False, pid)
    if not handle: raise OSError("Process metrics недоступны")
    try:
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb): raise OSError("Process RSS недоступен")
        values = [w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)): raise OSError("Process CPU time недоступно")
        ticks = [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in values]
        return {"rss": counters.rss, "private": counters.private, "identity": (pid, ticks[0]), "cpu_seconds": (ticks[2] + ticks[3]) / 10000000}
    finally:
        api.CloseHandle(handle)


def _linux_stats(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    parts = text[text.rfind(")") + 2:].split()
    return {"rss": int(parts[21]) * os.sysconf("SC_PAGE_SIZE"), "private": None,
            "identity": (pid, int(parts[19])), "cpu_seconds": (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")}


def tree_stats(root):
    if os.name == "nt":
        mapping = _windows_processes(); pids = {root}
        while True:
            expanded = pids | {pid for pid, parent in mapping.items() if parent in pids}
            if pids == expanded: break
            pids = expanded
        reader = _windows_stats
    else:
        pids = {root}; pending = [root]
        while pending:
            pid = pending.pop()
            try:
                for task in Path(f"/proc/{pid}/task").glob("*/children"):
                    for child in map(int, task.read_text().split()):
                        if child not in pids: pids.add(child); pending.append(child)
            except (OSError, ValueError): pass
        reader = _linux_stats
    result = []
    for pid in pids:
        try: result.append(reader(pid))
        except (OSError, ValueError, IndexError): pass
    return result


class TreeMonitor:
    def __init__(self, cancel, budget, interval=.05,telemetry=None):
        self.cancel = cancel; self.budget = budget; self.interval = interval
        self.stop = threading.Event(); self.peaks = {}; self.reason = ""
        self.telemetry=telemetry
        self.data = {"peak_tree_rss_bytes": 0, "samples": 0, "max_observed_processes": 0,
                     "peak_tree_private_bytes": None,
                     "sample_interval_seconds": interval,
                     "scope": "Sampled simultaneous sum of own tree RSS; shared pages can be counted more than once; short peaks may be missed",
                     "cpu_scope": "Observed per-process CPU maxima; exited processes between samples may be missed"}

    def sample(self):
        stats = tree_stats(os.getpid())
        if not stats: return
        if self.telemetry:
            try: self.telemetry.sample(stats)
            except (OSError,ValueError) as exc:
                if len(self.telemetry.errors)<10: self.telemetry.errors.append(str(exc))
        rss = sum(item["rss"] for item in stats)
        if all(item["private"] is not None for item in stats):
            self.data["peak_tree_private_bytes"] = max(self.data["peak_tree_private_bytes"] or 0, sum(item["private"] for item in stats))
        self.data["peak_tree_rss_bytes"] = max(self.data["peak_tree_rss_bytes"], rss)
        self.data['current_tree_rss_bytes']=rss
        self.data["samples"] += 1
        self.data["max_observed_processes"] = max(self.data["max_observed_processes"], len(stats))
        for item in stats: self.peaks[item["identity"]] = max(self.peaks.get(item["identity"], 0), item["cpu_seconds"])
        free = memory_info()["available_bytes"]
        if rss > self.budget["budget_bytes"] or (free is not None and free < self.budget["reserve_bytes"]):
            self.reason = "Превышен RAM budget дерева теста или исчерпан резерв ОС"
            self.cancel.set()

    def start(self):
        self.sample()
        def observe():
            while not self.stop.wait(self.interval):
                try: self.sample()
                except (OSError, ValueError): pass
        self.thread = threading.Thread(target=observe, name="ucode-ram-monitor", daemon=True)
        self.thread.start()
        return self

    def finish(self):
        self.stop.set(); self.thread.join(2); self.sample()
        if self.telemetry: self.data["cpu_telemetry"]=self.telemetry.finish()
        self.data["observed_cpu_seconds"] = sum(self.peaks.values())
        self.data["limit_reason"] = self.reason
        return self.data
