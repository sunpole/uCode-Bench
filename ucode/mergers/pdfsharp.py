"""PDFsharp 6.2.4 via a project-local .NET 8 helper and JSON manifest.

Pinned 6.2.4 is the MIT release; it is deliberately not an unbounded latest
package reference. Official package: https://www.nuget.org/packages/PDFsharp/6.2.4
Engine startup and manifest handling are included in this adapter's timing.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from ..runtime import ROOT, resolve_executable
from .base import Adapter, MergeError, validate_paths
from .external import run_engine


HELPER = ROOT / "tools" / "pdfsharp" / "PdfSharpMerge.dll"


class PdfSharpAdapter(Adapter):
    name = "PDFsharp (.NET)"
    external = True

    def probe(self) -> dict:
        if not HELPER.is_file():
            return {"available": False, "reason": "Project-local PdfSharpMerge.dll has not been built", "version": None}
        executable = resolve_executable("dotnet")
        if not executable:
            return {"available": False, "reason": "dotnet was not found; .NET 8 runtime is required", "version": None}
        marker="helper-v2-exact-boxes"
        binary=HELPER.read_bytes()
        revision=marker if marker.encode("utf-16le") in binary or marker.encode() in binary else "helper revision unknown"
        return {"available": True, "reason": "", "version": "PDFsharp 6.2.4 / .NET 8 "+revision,
                "executable": executable, "helper": str(HELPER.resolve())}

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        info = self.probe()
        if not info["available"]:
            raise MergeError(info["reason"])
        manifest = target.with_name(f"{target.name}.pdfsharp-{uuid.uuid4().hex[:12]}.json")
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump({"inputs": [str(source) for source in sources], "output": str(target)}, stream,
                      ensure_ascii=False)
        metrics = run_engine([info["executable"], info["helper"], str(manifest)])
        if not target.is_file() or target.stat().st_size == 0:
            raise MergeError("PDFsharp produced no nonempty output PDF")
        return metrics
