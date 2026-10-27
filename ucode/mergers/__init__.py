"""M06: isolated merger adapters, discovered without installing anything."""
from .base import Adapter, MergeError
from .mutool import MutoolAdapter
from .pikepdf import PikepdfAdapter
from .pymupdf import PyMuPDFAdapter
from .pypdf import PypdfAdapter
from .qpdf import QpdfAdapter
from .pdfrw import PdfrwAdapter
from .pdfium import PdfiumAdapter
from .pdfcpu import PdfcpuAdapter
from .pdfbox import PdfBoxAdapter
from .pdflib import PdfLibAdapter
from .pdfsharp import PdfSharpAdapter


def available_adapters() -> list[Adapter]:
    """Return all known methods, including those whose probe will be SKIPPED."""
    return [QpdfAdapter(), MutoolAdapter(), PyMuPDFAdapter(), PikepdfAdapter(), PypdfAdapter(),
            PdfrwAdapter(), PdfiumAdapter(), PdfcpuAdapter(), PdfBoxAdapter(), PdfLibAdapter(), PdfSharpAdapter()]


__all__ = ["Adapter", "MergeError", "available_adapters"]
