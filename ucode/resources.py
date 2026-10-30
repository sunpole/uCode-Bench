"""Conservative bounds before large local jobs; no OS settings are changed."""
import ctypes
import os
from pathlib import Path
import shutil


def check_resources(directory, count, *, scientific=False,streaming=False):
    from .stream_data import positive_count
    positive_count(count)
    if scientific and count>10000: raise ValueError("Размер вне исторического научного профиля")
    ancestor = Path(directory).resolve()
    while not ancestor.exists():
        if ancestor.parent == ancestor:
            raise ValueError("Диск или папка для результатов недоступны")
        ancestor = ancestor.parent
    required_disk = max(256 * 1024**2, count * (300000 if scientific else 16000))
    free = shutil.disk_usage(ancestor).free
    if free < required_disk:
        raise ValueError(f"Недостаточно места: нужно минимум {required_disk / 1024**2:.0f} МиБ")
    available = None
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                ("total", "available", "page", "available_page", "virtual", "available_virtual", "extended")]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            available = memory.available
    elif Path("/proc/meminfo").exists():
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
                break
    required_ram = 256 * 1024**2 + (min(count,4096) if streaming else count) * (120000 if scientific else 40000)
    if streaming and available is None: raise ValueError("Не удалось определить свободную ОЗУ для потокового запуска")
    if available is not None and available < required_ram:
        raise ValueError(f"Недостаточно свободной RAM: нужно минимум {required_ram / 1024**2:.0f} МиБ")
    return {"free_disk_bytes": free, "available_ram_bytes": available,
            "required_disk_bytes": required_disk, "required_ram_bytes": required_ram}
