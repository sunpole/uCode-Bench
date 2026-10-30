"""Freeze only this project's code for one user-started experiment, not tools/data."""
from pathlib import Path
from .lab_worker import code_fingerprint


def snapshot_runtime(folder):
    source=Path(__file__).resolve().parents[1]
    target=Path(folder).resolve()/".runtime"; target.mkdir(exist_ok=False)
    digest=code_fingerprint()
    files=list((source/"ucode").rglob("*.py"))
    files += [source/"scripts"/name for name in ("merge-pdflib.mjs","PdfBoxMerge.java","pdfsharp/Program.cs","pdfsharp/PdfSharpMerge.csproj")]
    for path in files:
        if not path.is_file(): continue
        if not path.resolve().is_relative_to(source): raise ValueError("Исходник находится вне проекта")
        copy=target/path.relative_to(source); copy.parent.mkdir(exist_ok=True,parents=True)
        copy.write_bytes(path.read_bytes())
    if code_fingerprint()!=digest or code_fingerprint(target/"ucode")!=digest:
        raise RuntimeError("Код изменился при сохранении копии для теста; запустите заново после обновления")
    from .runtime import ROOT
    return {"runtime_root":str(target),"asset_root":str(ROOT),"source_digest":digest}


def assert_trial_integrity(trial):
    if any("Исходники изменились" in str(value) or "Сборка изменилась" in str(value) or "Версия движка изменилась" in str(value) for value in trial.get("errors",[])):
        raise RuntimeError("Нарушена целостность сборки/движка; серия остановлена. Предыдущие файлы сохранены.")
