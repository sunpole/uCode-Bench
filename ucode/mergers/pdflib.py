"""pdf-lib via local Node.js, preserving order with a JSON path manifest.

Reference: https://pdf-lib.js.org/docs/api/classes/pdfdocument
"""
import json
from pathlib import Path

from .base import MergeError, validate_paths
from .external import ExternalAdapter, run_engine


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


class PdfLibAdapter(ExternalAdapter):
    name = "pdf-lib (Node.js)"
    command = "node"

    def _assets(self):
        root = _project_root()
        helper = root / "scripts" / "merge-pdflib.mjs"
        package_file = root / "node_modules" / "pdf-lib" / "package.json"
        if not helper.is_file() or not package_file.is_file():
            raise MergeError("Local pdf-lib package or helper is missing; run the explicit engine setup")
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MergeError(f"Cannot inspect local pdf-lib package: {exc}") from exc
        if package.get("name") != "pdf-lib" or not isinstance(package.get("version"), str):
            raise MergeError("Invalid local pdf-lib package metadata")
        return helper, package["version"]

    def probe(self) -> dict:
        try:
            helper, version = self._assets()
        except MergeError as exc:
            return {"available": False, "reason": str(exc), "version": None}
        result = super().probe()
        if result["available"]:
            result["node_version"] = result["version"]
            result.update(version=version, helper=str(helper))
        return result

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        helper, _ = self._assets()
        executable = self.executable()
        manifest = target.with_suffix(target.suffix + ".inputs.json")
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump({"inputs": list(map(str, sources)), "output": str(target)}, stream, ensure_ascii=False)
        metrics = run_engine([executable, str(helper), str(manifest)], cwd=_project_root())
        if not target.is_file() or target.stat().st_size == 0:
            raise MergeError("pdf-lib did not produce a nonempty PDF")
        metrics["engine_options"] = "copyPages; object streams enabled; Node.js startup included"
        return metrics
