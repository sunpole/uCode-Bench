"""Apache PDFBox via a locally compiled Java 8 helper and an official app jar.

Reference: https://pdfbox.apache.org/3.0/migration.html
"""
import os
from pathlib import Path

from .base import MergeError, validate_paths
from .external import ExternalAdapter, run_engine


def _project_root() -> Path:
    from ..runtime import ROOT
    return ROOT


class PdfBoxAdapter(ExternalAdapter):
    name = "Apache PDFBox"
    command = "java"
    version_args = ("-version",)
    pdfbox_version = "3.0.8"

    def _assets(self):
        home = _project_root() / "tools" / "pdfbox"
        jar = home / f"pdfbox-app-{self.pdfbox_version}.jar"
        classes = home / "classes"
        if not jar.is_file():
            raise MergeError(f"PDFBox app jar was not found: {jar}")
        if not (classes / "PdfBoxMerge.class").is_file():
            raise MergeError("PDFBox Java helper has not been compiled; run the explicit engine setup")
        return jar, classes

    def probe(self) -> dict:
        try:
            jar, classes = self._assets()
        except MergeError as exc:
            return {"available": False, "reason": str(exc), "version": None}
        result = super().probe()
        if result["available"]:
            result["java_version"] = result["version"]
            result.update(version=self.pdfbox_version, jar=str(jar), classes=str(classes))
        return result

    def merge(self, inputs: list[Path], output: Path) -> dict:
        sources, target = validate_paths(inputs, output)
        jar, classes = self._assets()
        executable = self.executable()
        if any("\n" in str(source) or "\r" in str(source) for source in sources):
            raise MergeError("PDFBox newline manifest cannot represent a path containing line breaks")
        manifest = target.with_suffix(target.suffix + ".inputs.txt")
        with manifest.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(map(str, sources)) + "\n")
        # ScratchFile uses java.io.tmpdir; keep it under this trial directory.
        scratch = target.parent / f".{target.stem}.pdfbox-temp"
        scratch.mkdir(exist_ok=False)
        classpath = os.pathsep.join((str(classes), str(jar)))
        metrics = run_engine([executable, f"-Djava.io.tmpdir={scratch}", "-cp", classpath,
                              "PdfBoxMerge", str(manifest), str(target)], cwd=_project_root())
        if not target.is_file() or target.stat().st_size == 0:
            raise MergeError("PDFBox did not produce a nonempty PDF")
        metrics["engine_options"] = "PDFBOX_LEGACY_MODE; temp-file-only stream cache; Java startup included"
        return metrics
