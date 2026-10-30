"""Conservative per-trial benchmark artifact retention.

Only trial-owned PDF documents are discarded. No production or user-selected
PDF output directories are ever supplied to this function. Timings, manifests,
QA results, metrics and TXT reports remain intact.
"""
from __future__ import annotations

import os
from pathlib import Path


def discard_trial_pdfs(trial_directory):
    """Delete regular .pdf files *beneath* a completed isolated trial.

    A caller must provide the private trial directory it just created and
    must invoke this only *after* the child exited and QA/metrics were recorded.
    Never use this for arbitrary user-supplied paths or production jobs.
    Symlinks (including directory symlinks) are not traversed or removed.
    """
    root = Path(trial_directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Нужна существующая изолированная папка теста")
    count = 0
    bytes_deleted = 0
    errors = []
    for current, subdirs, files in os.walk(root, topdown=True, followlinks=False):
        subdirs[:] = [name for name in subdirs
                      if not (Path(current) / name).is_symlink()]
        for name in files:
            if not name.lower().endswith(".pdf"):
                continue
            path = Path(current) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                path.unlink()
                count += 1
                bytes_deleted += size
            except OSError as exc:
                errors.append(f"{path.name}: {type(exc).__name__}")
    return {"mode": "REPORT_ONLY", "pdf_deleted_files": count,
            "pdf_deleted_bytes": bytes_deleted,
            "status": "PASS" if not errors else "PARTIAL",
            "errors": errors}
