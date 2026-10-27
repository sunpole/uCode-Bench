"""Read-only environment inventory; never installs dependencies."""
import ctypes
import importlib.metadata
import importlib.util
import os
import platform
import shutil
import sys


def inspect_environment():
    dependencies = {}
    for package, module in [("reportlab", "reportlab"), ("pypdf", "pypdf"), ("Pillow", "PIL"),
                            ("segno", "segno"), ("PyMuPDF", "pymupdf"), ("pikepdf", "pikepdf"),
                            ("pdfrw", "pdfrw"), ("pypdfium2", "pypdfium2")]:
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    result = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
              "logical_processors": os.cpu_count(), "cpu": platform.processor(), "dependencies": dependencies,
              "pdftoppm": shutil.which("pdftoppm"), "tkinter": importlib.util.find_spec("tkinter") is not None}
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            result["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total_physical", "available_physical", "total_page", "available_page",
                                                 "total_virtual", "available_virtual", "extended")]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result["physical_memory_bytes"] = memory.total_physical
            result["available_memory_bytes"] = memory.available_physical
    from .mergers import available_adapters
    result["adapters"] = [{"name": a.name, **a.probe()} for a in available_adapters()]
    result["core_ready"] = all(dependencies[p] for p in ("reportlab", "pypdf", "Pillow")) and bool(result["pdftoppm"])
    return result
