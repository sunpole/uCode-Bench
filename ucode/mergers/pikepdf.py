"""pikepdf adapter; each source PDF is closed after its pages are copied."""
from pathlib import Path

from .base import Adapter, require_available, validate_paths


class PikepdfAdapter(Adapter):
    name = "pikepdf"
    module_name = "pikepdf"

    def merge(self, inputs: list[Path], output: Path) -> None:
        sources, target = validate_paths(inputs, output)
        require_available(self)
        import pikepdf

        with pikepdf.Pdf.new() as document:
            for source in sources:
                with pikepdf.Pdf.open(str(source)) as part:
                    document.pages.extend(part.pages)
            with target.open("xb") as stream:
                document.save(stream)
