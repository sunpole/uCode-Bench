"""pdfcpu create-mode merge, with configuration writes disabled.

References: https://pdfcpu.io/getting_started/usage/
https://pdfcpu.io/config/config_modes/
"""
from pathlib import Path

from .base import MergeError, validate_paths
from .external import ExternalAdapter, run_engine


class PdfcpuAdapter(ExternalAdapter):
    name = "pdfcpu"
    command = "pdfcpu"
    version_args = ("version",)

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        executable = self.executable()
        # Benchmark inputs live in one folder. Basenames keep 1000 inputs below
        # Windows' argv limit without glob expansion, sorting, or staged merges.
        common_directory = sources[0].parent
        same_directory = all(source.parent == common_directory for source in sources)
        arguments = [source.name if same_directory else str(source) for source in sources]
        # Current pdfcpu refuses an existing explicit output without --force.
        # Do not use that flag: both our guard and the engine protect old data.
        metrics = run_engine([executable, "merge", "--mode", "create", "--conf", "disable",
                              str(target), *arguments], cwd=common_directory if same_directory else None)
        if not target.is_file() or target.stat().st_size == 0:
            raise MergeError("pdfcpu did not produce a nonempty PDF")
        return metrics
