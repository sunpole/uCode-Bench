"""M07: isolated-process CPU and Windows OS peak working set."""
import ctypes
import os
import time
from ctypes import wintypes


def peak_rss_bytes():
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        info = Counters()
        info.cb = ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(info.PeakWorkingSetSize)
    import resource
    import sys
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def measure(action):
    before_cpu = time.process_time()
    before = time.perf_counter()
    extra = action()
    seconds = time.perf_counter() - before
    cpu_seconds = time.process_time() - before_cpu
    result = {"seconds": seconds, "cpu_seconds": cpu_seconds, "peak_rss_bytes": peak_rss_bytes(),
              "ram_scope": "OS process peak working set including imports and input loading; QA excluded",
              "cpu_scope": "method process CPU; excludes imports, input loading and QA"}
    if isinstance(extra, dict):
        result.update(extra)
        if extra.get("child_cpu_seconds") is not None:
            result["cpu_seconds"] += extra["child_cpu_seconds"]
            result["cpu_scope"] += "; includes external engine CPU"
        if extra.get("child_peak_rss_bytes") is not None:
            result["peak_rss_bytes"] += extra["child_peak_rss_bytes"]
            result["ram_scope"] += "; sum of worker/engine individual peaks (upper bound, not simultaneous RSS)"
    return result
