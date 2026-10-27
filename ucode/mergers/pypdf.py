"""Pure Python pypdf adapter; append preserves the supplied input order."""
from pathlib import Path

from .base import Adapter, require_available, validate_paths


class PypdfAdapter(Adapter):
    name = "pypdf"
    module_name = "pypdf"

    def merge(self, inputs: list[Path], output: Path) -> None:
        sources, target = validate_paths(inputs, output)
        require_available(self)
        from pypdf import PdfWriter

        with PdfWriter() as writer:
            for source in sources:
                writer.append(str(source), import_outline=False)
            with target.open("xb") as stream:
                writer.write(stream)
