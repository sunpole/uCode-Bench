"""PyMuPDF adapter. The modern pymupdf module avoids unrelated fitz packages."""
from pathlib import Path

from .base import Adapter, require_available, validate_paths


class PyMuPDFAdapter(Adapter):
    name = "PyMuPDF"
    module_name = "pymupdf"
    distribution_name = "PyMuPDF"

    def merge(self, inputs: list[Path], output: Path) -> None:
        sources, target = validate_paths(inputs, output)
        require_available(self)
        import pymupdf

        with pymupdf.open() as document:
            for source in sources:
                with pymupdf.open(str(source)) as part:
                    document.insert_pdf(part)
            with target.open("xb"):
                pass
            document.save(str(target))
