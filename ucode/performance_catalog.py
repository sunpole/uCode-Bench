"""Installed does not mean integrated, and a scheduler does not imply speedup."""
import importlib.util
import platform
import sys
from concurrent.futures import ThreadPoolExecutor

from .engines import available_engines
from .mergers import available_adapters

SOURCES={
    "python":"https://docs.python.org/3.14/library/concurrent.futures.html",
    "joblib":"https://joblib.readthedocs.io/en/latest/parallel.html",
    "pymupdf":"https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html",
    "zxingcpp":"https://github.com/zxing-cpp/zxing-cpp",
    "segno":"https://segno.readthedocs.io/en/latest/",
}


def inspect_catalog():
    def probe(adapter):
        families={"qpdf":("qpdf","C++"),"pikepdf":("qpdf","Python → C++"),"MuPDF (mutool)":("MuPDF","C"),
                  "PyMuPDF":("MuPDF","Python → C"),"PDFium (pypdfium2)":("PDFium","Python → C++"),
                  "pypdf":("pypdf","Python"),"pdfrw":("pdfrw","Python"),"pdfcpu":("pdfcpu","Go"),
                  "Apache PDFBox":("PDFBox","Java"),"pdf-lib (Node.js)":("pdf-lib","JavaScript"),"PDFsharp (.NET)":("PDFsharp","C# / .NET")}
        family,language=families.get(adapter.name,(adapter.name,"Не определён"))
        return {"name":adapter.name,"family":family,"language":language,"role":"PDF merge",**adapter.probe()}
    with ThreadPoolExecutor(max_workers=3) as pool:
        mergers=list(pool.map(probe,available_adapters()))
    candidates=[]
    for module,name,reason in (
        ("joblib","Joblib/loky","Другой планировщик процессов; адаптер не подключён, ускорение не измерено"),
        ("segno","Segno","Другой QR encoder; адаптер не подключён"),
        ("qrcode","python-qrcode","Другой QR encoder; адаптер не подключён"),
        ("zxingcpp","ZXing-C++","Нативный QR encoder; адаптер/параметры V1-M ещё не подключены")):
        candidates.append({"name":name,"installed":importlib.util.find_spec(module) is not None,"integrated":False,"reason":reason})
    return {"python":platform.python_version(),"python_executable":sys.executable,"gil_enabled":getattr(sys,"_is_gil_enabled",lambda:True)(),
        "encoders":[info.to_dict() for info in available_engines()],"backends":["serial","process","thread"],
        "mergers":mergers,"candidates":candidates,
        "interpreters":{"runtime_available":sys.version_info>=(3,14),"integrated":False,
            "reason":"InterpreterPoolExecutor требует Python3.14+ и проверки совместимости"},"sources":SOURCES,
        "scope":"Only integrated backends and selected registered PDF mergers are measured; not all possible implementations"}
