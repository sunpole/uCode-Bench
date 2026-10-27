"""MuPDF CLI adapter; oversized Windows argument lists fail explicitly.

Reference: https://mupdf.readthedocs.io/en/latest/tools/mutool-merge.html
"""
from pathlib import Path

from .base import MergeError, validate_paths
from .external import ExternalAdapter, run_engine


class MutoolAdapter(ExternalAdapter):
    name = "MuPDF (mutool)"
    command = "mutool"
    version_args = ("-v",)

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        executable = self.executable()
        with target.open("xb"):
            pass
        directory = sources[0].parent
        local_names = all(source.parent == directory for source in sources)
        names = [p.name for p in sources] if local_names else list(map(str, sources))
        metrics = run_engine([executable, "merge", "-o", str(target), *names], cwd=directory if local_names else None)
        if target.stat().st_size == 0:
            raise MergeError("mutool produced an empty output")
        return metrics
