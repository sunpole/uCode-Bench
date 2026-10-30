"""Conservative per-trial benchmark artifact retention.

Only trial-owned PDF documents and *working* stream index databases are
discarded after the worker has exited and QA/metrics have been recorded.
The production path and the test report catalog are never passed here.
"""
from __future__ import annotations

import os
from pathlib import Path


_WORKING_DB_NAMES = frozenset(("data.sqlite", "pdf-index.sqlite"))


def discard_trial_pdfs(trial_directory):
    """Prune disposable artifacts inside a completed, isolated benchmark trial.

    The caller must pass the private trial folder it just created and use this
    only after the worker exits and QA is complete. Symlinks are not followed.
    SQLite is deleted only if the file is in a generated pdf-* job directory
    and under the trial's jobs subtree; archived catalog.sqlite is never
    removed. No whole directories are deleted.
    """
    root = Path(trial_directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Нужна существующая изолированная папка теста")
    count = 0
    bytes_deleted = 0
    db_count = 0
    db_bytes = 0
    errors = []
    for current, subdirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        subdirs[:] = [name for name in subdirs
                      if not (current_path / name).is_symlink()]
        # The DB is always a transient disk plan for a generated PDF job.
        # The path must be inside an isolated trial's jobs subtree.
        inside_jobs = "jobs" in current_path.relative_to(root).parts
        for name in files:
            pdf = name.lower().endswith(".pdf")
            transient_db = (name in _WORKING_DB_NAMES
                            and current_path.name.startswith("pdf-")
                            and inside_jobs)
            if not (pdf or transient_db):
                continue
            path = current_path / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                size = path.stat().st_size
                path.unlink()
                if pdf:
                    count += 1
                    bytes_deleted += size
                else:
                    db_count += 1
                    db_bytes += size
            except OSError as exc:
                errors.append(f"{path.name}: {type(exc).__name__}")
    return {"mode": "REPORT_ONLY",
            "pdf_deleted_files": count, "pdf_deleted_bytes": bytes_deleted,
            "sqlite_deleted_files": db_count, "sqlite_deleted_bytes": db_bytes,
            "status": "PASS" if not errors else "PARTIAL", "errors": errors}
