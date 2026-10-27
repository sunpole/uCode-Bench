"""Common adapter contract; dependencies stay local to each implementation."""
from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path


class MergeError(RuntimeError):
    """An engine was unavailable or could not produce the requested output."""


class Adapter:
    name = "abstract"
    module_name: str | None = None
    distribution_name: str | None = None
    external = False

    def probe(self) -> dict:
        if self.module_name is None:
            return {"available": False, "reason": "No engine configured", "version": None}
        try:
            if importlib.util.find_spec(self.module_name) is None:
                return {"available": False, "reason": f"Python module {self.module_name} is not installed", "version": None}
            try:
                version = importlib.metadata.version(self.distribution_name or self.module_name)
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
            return {"available": True, "reason": "", "version": version}
        except Exception as exc:
            return {"available": False, "reason": f"Probe failed: {exc}", "version": None}

    def merge(self, inputs: list[Path], output: Path) -> dict | None:
        raise NotImplementedError


def validate_paths(inputs: list[Path], output: Path) -> tuple[list[Path], Path]:
    """Reject ambiguous inputs before creating any output; preserve given order."""
    if not inputs:
        raise MergeError("At least one input PDF is required")
    sources = [Path(path).resolve() for path in inputs]
    target = Path(output).resolve()
    if target.exists():
        raise FileExistsError(f"Output already exists: {target}")
    if not target.parent.is_dir():
        raise MergeError(f"Output directory does not exist: {target.parent}")
    for path in sources:
        if not path.is_file():
            raise MergeError(f"Input PDF does not exist: {path}")
        if path == target:
            raise MergeError("Output must differ from every input")
    return sources, target


def require_available(adapter: Adapter) -> None:
    info = adapter.probe()
    if not info["available"]:
        raise MergeError(info["reason"])
