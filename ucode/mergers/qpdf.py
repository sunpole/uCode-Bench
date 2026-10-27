"""qpdf adapter. Its documented @- argument stream avoids Windows argv limits.

Reference: https://qpdf.readthedocs.io/en/stable/cli.html#basic-invocation
"""
from pathlib import Path

from .base import MergeError, validate_paths
from .external import ExternalAdapter, run_engine


class QpdfAdapter(ExternalAdapter):
    name = "qpdf"
    command = "qpdf"

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        executable = self.executable()
        args = ["--empty", "--pages"]
        for source in sources:
            args.extend([str(source), "1-z"])
        args.extend(["--", str(target)])
        if any("\n" in arg or "\r" in arg for arg in args):
            raise MergeError("qpdf response arguments cannot contain line breaks")
        # Reserve the requested path exclusively; only this newly created file is written.
        with target.open("xb"):
            pass
        metrics = run_engine([executable, "@-"], stdin_bytes=("\n".join(args) + "\n").encode("utf-8"))
        if target.stat().st_size == 0:
            raise MergeError("qpdf produced an empty output")
        return metrics
