"""Read-only CPU/RAM/storage facts. Missing facts stay unknown, with a source.

No serial numbers, host names or user paths enter the report. No OS affinity,
power settings, quotas or global state are changed.
"""
import ctypes
from functools import lru_cache
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time


def worker_presets(available):
    if not isinstance(available, int) or available < 1:
        raise ValueError("Нет доступных CPU")
    values = {1, available}
    n = 2
    while n < available:
        values.add(n); n *= 2
    return tuple(sorted(values))


def cpu_model(cpus, *, allowed_ids=None, fallback_count=None, source="model", reason=""):
    if not cpus:
        return {"physical_cores": None, "logical_processors": fallback_count,
                "available_physical": None, "available_logical": fallback_count or 1,
                "smt": None, "groups": None, "source": source,
                "reason": reason or "Топология неизвестна; физические ядра не вычисляются из потоков"}
    available = [cpu for cpu in cpus if allowed_ids is None or cpu["id"] in allowed_ids]
    if not available:
        raise ValueError("ОС не сообщает доступных CPU для процесса")
    cores = {(cpu["group"], cpu["core"]) for cpu in cpus}
    return {"physical_cores": len(cores), "logical_processors": len(cpus),
            "available_physical": len({(cpu["group"], cpu["core"]) for cpu in available}),
            "available_logical": len(available), "smt": len(cpus) > len(cores),
            "groups": len({cpu["group"] for cpu in cpus}), "source": source, "reason": reason}


def _win_kernel():
    from ctypes import wintypes as w
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetCurrentProcess.restype = w.HANDLE
    api.GetSystemCpuSetInformation.argtypes = (ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG), w.HANDLE, w.ULONG)
    api.GetSystemCpuSetInformation.restype = w.BOOL
    api.GetProcessDefaultCpuSets.argtypes = (w.HANDLE, ctypes.POINTER(w.ULONG), w.ULONG, ctypes.POINTER(w.ULONG))
    api.GetProcessDefaultCpuSets.restype = w.BOOL
    api.GetProcessAffinityMask.argtypes = (w.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
    api.GetProcessAffinityMask.restype = w.BOOL
    api.GetProcessGroupAffinity.argtypes = (w.HANDLE, ctypes.POINTER(w.USHORT), ctypes.POINTER(w.USHORT))
    api.GetProcessGroupAffinity.restype = w.BOOL
    return api


def _windows_cpu():
    from ctypes import wintypes as w
    api = _win_kernel(); process = api.GetCurrentProcess(); required = w.ULONG()
    api.GetSystemCpuSetInformation(None, 0, ctypes.byref(required), process, 0)
    if not required.value or required.value > 16 * 1024**2:
        raise OSError("CPU Sets API не вернул топологию")
    buf = ctypes.create_string_buffer(required.value)
    if not api.GetSystemCpuSetInformation(buf, len(buf), ctypes.byref(required), process, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    records = []; reserved = set(); offset = 0
    while offset < required.value:
        size, kind = struct.unpack_from("<II", buf, offset)
        if size < 8 or offset + size > required.value:
            raise ValueError("Повреждён CPU Sets ответ")
        if kind == 0 and size >= 32:
            ident, group, logical, core = struct.unpack_from("<IHBB", buf, offset + 8)
            flags = buf.raw[offset + 19]
            records.append({"id": ident, "group": group, "logical": logical, "core": core})
            if flags & 2 and not flags & 4:
                reserved.add(ident)
        offset += size
    count = w.ULONG()
    api.GetProcessDefaultCpuSets(process, None, 0, ctypes.byref(count))
    defaults = None
    if count.value:
        ids = (w.ULONG * count.value)()
        if not api.GetProcessDefaultCpuSets(process, ids, count.value, ctypes.byref(count)):
            raise ctypes.WinError(ctypes.get_last_error())
        defaults = set(ids)
    allowed = {cpu["id"] for cpu in records if cpu["id"] not in reserved and
               (defaults is None or cpu["id"] in defaults)}
    # A DWORD_PTR affinity mask describes one group, not the whole >64 machine.
    n_groups = w.USHORT(256); groups = (w.USHORT * 256)()
    if not api.GetProcessGroupAffinity(process, ctypes.byref(n_groups), groups):
        raise ctypes.WinError(ctypes.get_last_error())
    if n_groups.value == 1:
        mask, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not api.GetProcessAffinityMask(process, ctypes.byref(mask), ctypes.byref(system)):
            raise ctypes.WinError(ctypes.get_last_error())
        allowed &= {cpu["id"] for cpu in records if cpu["group"] == groups[0] and mask.value & (1 << cpu["logical"])}
    model = cpu_model(records, allowed_ids=allowed, source="Windows CPU Sets + process affinity")
    if n_groups.value > 1:
        model["reason"] = "Несколько processor groups; групповые маски потоков не задаются этим патчем"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            model["name"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            model["vendor"] = winreg.QueryValueEx(key, "VendorIdentifier")[0]
            model["source"] += " + registry CPU name/vendor"
    except OSError:
        model.update(name=None, vendor=None)
    return model


def _linux_cpu():
    allowed = set(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    records = []
    for cpu in Path("/sys/devices/system/cpu").glob("cpu[0-9]*"):
        online = cpu / "online"
        if online.exists() and online.read_text().strip() == "0":
            continue
        topo = cpu / "topology"
        records.append({"id": int(cpu.name[3:]), "logical": int(cpu.name[3:]),
                        "group": int((topo / "physical_package_id").read_text()),
                        "core": int((topo / "core_id").read_text())})
    if any(cpu["core"] < 0 or cpu["group"] < 0 for cpu in records):
        raise ValueError("Ядра/package не определены sysfs")
    result = cpu_model(records, allowed_ids=allowed, fallback_count=os.cpu_count(), source="Linux sysfs + sched_getaffinity")
    data = Path("/proc/cpuinfo").read_text()
    fields = dict(line.split(":", 1) for line in data.splitlines() if ":" in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    result.update(name=fields.get("model name"), vendor=fields.get("vendor_id"))
    result["reason"] = "CPU affinity учтена; квоты CPU контейнера не равны числу доступных CPU"
    return result


def inspect_cpu():
    try:
        result = _windows_cpu() if os.name == "nt" else _linux_cpu()
    except (OSError, ValueError, AttributeError, struct.error) as exc:
        count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
        result = cpu_model([], fallback_count=count, source="OS logical count fallback", reason=type(exc).__name__ + ": топология/полные ограничения недоступны")
        result.update(name=None, vendor=None)
    result["presets"] = worker_presets(result["available_logical"])
    if result.get("available_physical"):
        result["presets"] = tuple(sorted(set(result["presets"]) | {result["available_physical"]}))
    result["scope"] = "Текущий процесс; OS/job CPU quotas и индивидуальная thread affinity могут дополнительно ограничивать исполнение"
    return result


def memory_info():
    total = available = None
    try:
        if os.name == "nt":
            class Memory(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                            ("total", "available", "page", "available_page", "virtual", "available_virtual", "extended")]
            value = Memory(); value.length = ctypes.sizeof(value)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
                raise OSError("GlobalMemoryStatusEx")
            total, available = value.total, value.available
            source = "GlobalMemoryStatusEx"
        else:
            values = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) >= 2}
            total, available = values.get("MemTotal"), values.get("MemAvailable")
            source = "/proc/meminfo"
            # cgroup v2 bounds when the process runs inside a container.
            for entry in Path("/proc/self/cgroup").read_text().splitlines():
                if entry.startswith("0::"):
                    relative = entry[3:].lstrip("/")
                    group = Path("/sys/fs/cgroup") / relative
                    for parent in (group, *group.parents):
                        if parent == Path("/sys/fs"):
                            break
                        limit = parent / "memory.max"; current = parent / "memory.current"
                        if limit.exists() and current.exists() and limit.read_text().strip() != "max":
                            cap, used = int(limit.read_text()), int(current.read_text())
                            total, available = min(total, cap), min(available, max(0, cap-used))
                            source += " + cgroup v2"
        return {"total_bytes": total, "available_bytes": available, "source": source,
                "reason": "Снимок ОС/cgroup v2; Windows job memory limits и cgroup v1 отдельно не запрашиваются"}
    except (OSError, ValueError, TypeError):
        return {"total_bytes": total, "available_bytes": available, "source": "unknown", "reason": "RAM/ограничение контейнера не удалось определить полностью"}


def _existing_directory(directory):
    path = Path(directory).resolve()
    while not path.exists():
        if path.parent == path:
            raise ValueError("Диск назначения недоступен")
        path = path.parent
    return path


@lru_cache(maxsize=16)
def _windows_storage(drive):
    from ctypes import wintypes as w
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE)
    api.CreateFileW.restype = w.HANDLE
    api.DeviceIoControl.argtypes = (w.HANDLE, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p)
    api.CloseHandle.argtypes = (w.HANDLE,)
    handle = api.CreateFileW("\\\\.\\" + drive, 0, 3, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Не открыт read-only volume handle")
    def query(prop):
        request = ctypes.create_string_buffer(struct.pack("<III", prop, 0, 0))
        output = ctypes.create_string_buffer(4096); returned = w.DWORD()
        if not api.DeviceIoControl(handle, 0x2D1400, request, 12, output, len(output), ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return output.raw[:returned.value]
    try:
        descriptor = query(0)
        if len(descriptor) < 36: raise ValueError("Короткий storage descriptor")
        bus_id = struct.unpack_from("<I", descriptor, 28)[0]
        bus = {7: "USB", 8: "RAID", 11: "SATA", 17: "NVMe"}.get(bus_id)
        media = None
        try:
            seek = query(7)
            if len(seek) >= 9: media = "seek penalty (HDD)" if seek[8] else "no seek penalty (SSD/virtual)"
        except OSError:
            pass
        return {"bus": bus, "media": media, "source": "IOCTL_STORAGE_QUERY_PROPERTY", "reason": "" if bus else "Тип шины не определён драйвером"}
    finally:
        api.CloseHandle(handle)


def disk_info(directory):
    path = _existing_directory(directory)
    usage = shutil.disk_usage(path)
    details = {"bus": None, "media": None, "source": "disk_usage", "reason": "Тип носителя/шина неизвестны; скорость не измерялась"}
    try:
        if os.name == "nt" and len(path.drive) == 2:
            details = dict(_windows_storage(path.drive))
        elif os.name != "nt":
            mounts = []
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                fields = line.split(); mount = fields[4].replace("\\040", " ")
                if path.is_relative_to(mount): mounts.append((len(mount), fields[2]))
            device = Path("/sys/dev/block") / max(mounts)[1]
            resolved = device.resolve(strict=True)
            for item in (resolved, *resolved.parents):
                rotational = item / "queue/rotational"
                if rotational.exists():
                    media = "HDD / rotational" if rotational.read_text().strip() == "1" else "SSD / non-rotational"
                    bus = "NVMe" if item.name.startswith("nvme") else None
                    details = {"bus": bus, "media": media, "source": "Linux sysfs block queue", "reason": "" if bus else "Шина неизвестна; RAID/virtual может скрывать физический носитель"}
                    break
    except (OSError, ValueError, IndexError):
        pass
    return {**details, "free_bytes": usage.free, "total_bytes": usage.total, "speed_measured": False}


def probe_directory(directory):
    """Explicit 32 KiB write/fsync check, not a disk speed benchmark."""
    path = Path(directory)
    if not path.is_dir():
        raise ValueError("Для проверки выберите существующую папку")
    started = time.perf_counter()
    with tempfile.TemporaryFile(prefix="ucode-write-probe-", dir=path) as stream:
        stream.write(b"\0" * 32768); stream.flush(); os.fsync(stream.fileno())
    return {"writable": True, "bytes": 32768, "seconds": time.perf_counter()-started,
            "speed_benchmark": False, "flush": "flush + fsync"}


def inspect_hardware(directory):
    return {"schema_version": 1, "cpu": inspect_cpu(), "ram": memory_info(), "disk": disk_info(directory)}
