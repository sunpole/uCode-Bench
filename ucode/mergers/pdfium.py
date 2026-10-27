"""PDFium page-import adapter via pypdfium2, without rendering pages.

API reference: https://pypdfium2.readthedocs.io/en/stable/python_api.html
PdfDocument.new(), import_pages(..., index=None), save(binary_stream).
"""
from pathlib import Path

from .base import Adapter, require_available, validate_paths


class PdfiumAdapter(Adapter):
    name = "PDFium (pypdfium2)"
    module_name = "pypdfium2"
    distribution_name = "pypdfium2"

    def merge(self, inputs: list[Path], output: Path) -> None:
        sources, target = validate_paths(inputs, output)
        require_available(self)
        import pypdfium2

        with pypdfium2.PdfDocument.new() as document:
            for source in sources:
                with pypdfium2.PdfDocument(str(source)) as part:
                    # The default index appends all source pages in their
                    # original order; no bitmap or page-object regeneration.
                    document.import_pages(part)
            with target.open("xb") as stream:
                document.save(stream)
