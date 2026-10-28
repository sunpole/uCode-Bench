"""Resolve project-local tools without changing system PATH or registry."""
import json
from pathlib import Path
import shutil
import os

ROOT = Path(os.environ.get("UCODE_ASSET_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def resolve_executable(command):
    manifest = ROOT / "tools" / "engines.json"
    if manifest.is_file():
        mapping = json.loads(manifest.read_text(encoding="utf-8"))
        entry = mapping.get(command)
        if entry:
            candidate = ROOT / entry
            if candidate.is_file() and candidate.resolve().is_relative_to((ROOT / "tools").resolve()):
                return str(candidate.resolve())
    return shutil.which(command)
