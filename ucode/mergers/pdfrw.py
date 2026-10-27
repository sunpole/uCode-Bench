"""pdfrw object-copy adapter, without rasterization or page reordering.

API reference: https://github.com/pmaupin/pdfrw#43-usage
Reader input bytes keep lazy object resolution independent of open handles.
"""
from pathlib import Path

from .base import Adapter, MergeError, require_available, validate_paths


class PdfrwAdapter(Adapter):
    name = "pdfrw"
    module_name = "pdfrw"

    def merge(self, inputs: list[Path], output: Path) -> None:
        sources, target = validate_paths(inputs, output)
        require_available(self)
        from pdfrw import PdfReader, PdfWriter

        writer = PdfWriter()
        for source in sources:
            # PdfReader keeps its byte buffer for lazy PDF objects. Reading the
            # file explicitly also guarantees that no input descriptor leaks.
            part = PdfReader(fdata=source.read_bytes())
            if part.Encrypt:
                raise MergeError(f"pdfrw adapter does not accept encrypted PDF: {source.name}")
            writer.addpages(part.pages)
        with target.open("xb") as stream:
            writer.write(stream)
