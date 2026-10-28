"""CPU selection and verified affinity, applied only inside an isolated trial."""
import ctypes
import os
from pathlib import Path
from .hardware import inspect_cpu, _win_kernel


def select_cpus(cpu, unit, count):
    if unit not in ("logical", "physical"):
        raise ValueError("Выберите физические ядра или логические CPU")
    available = cpu.get("available_cpus")
    if not available:
        raise ValueError("ОС не предоставила идентификаторы CPU для привязки")
    available = sorted(available, key=lambda item: (item["group"], item["logical"]))
    if unit == "physical":
        cores = {}
        for item in available:
            cores.setdefault((item["group"], item["core"]), item)
        available = list(cores.values())
    text = str(count).lower().strip()
    if text == "all": number = len(available)
    elif text == "all-2": number = len(available) - 2
    elif text.isascii() and text.isdigit(): number = int(text)
    else: raise ValueError("CPU: целое число, all или all-2")
    if not 1 <= number <= len(available):
        raise ValueError(f"Недоступно {text}: доступно {len(available)} ({unit})")
    return available[:number]


def cpu_keys(cpus):
    return sorted((item["group"], item["logical"]) for item in cpus)


def apply_affinity(cpus):
    """Never call in the GUI. Child processes inherit this process restriction."""
    if not cpus: raise ValueError("Пустой набор CPU")
    before = inspect_cpu()
    if not set(cpu_keys(cpus)).issubset(set(cpu_keys(before.get("available_cpus") or []))):
        raise ValueError("Запрошенные CPU больше не доступны процессу")
    if os.name == "nt":
        from ctypes import wintypes as w
        api = _win_kernel(); process = api.GetCurrentProcess()
        n = w.USHORT(256); groups = (w.USHORT * 256)()
        if not api.GetProcessGroupAffinity(process, ctypes.byref(n), groups):
            raise ctypes.WinError(ctypes.get_last_error())
        requested_groups = {item["group"] for item in cpus}
        if n.value != 1 or requested_groups != {groups[0]}:
            raise NotImplementedError("Принудительная Windows affinity между processor groups пока не поддерживается")
        api.SetProcessAffinityMask.argtypes = (w.HANDLE, ctypes.c_size_t)
        api.SetProcessAffinityMask.restype = w.BOOL
        mask = sum(1 << item["logical"] for item in cpus)
        if not api.SetProcessAffinityMask(process, mask):
            raise ctypes.WinError(ctypes.get_last_error())
    elif hasattr(os, "sched_setaffinity"):
        selected = {item["id"] for item in cpus}
        os.sched_setaffinity(0, selected)
        # Linux affinity is per thread. Apply to any already-created own thread.
        for task in Path("/proc/self/task").iterdir():
            try: os.sched_setaffinity(int(task.name), selected)
            except ProcessLookupError: pass
    else:
        raise NotImplementedError("В этой ОС нет поддерживаемой process affinity")
    after = inspect_cpu()
    verified = after.get("available_cpus") or []
    if cpu_keys(verified) != cpu_keys(cpus):
        raise RuntimeError("ОС не подтвердила запрошенный набор CPU")
    return {"requested_cpus": cpus, "verified_cpus": verified,
            "scope": "Isolated trial process and inherited workers, not GUI/other applications",
            "other_applications_can_use_reserved_cpus": True}
