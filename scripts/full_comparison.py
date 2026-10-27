"""Authorized finite pipeline: local setup -> tests -> 200/1000 -> public copy.

Publication is opt-in through --publish OWNER/NAME. It refuses an existing
remote repository and never force-pushes, resets, cleans or removes local data.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.install_engines import PYTHON, install_all, local_environment


def command(argv, *, capture=False, timeout=600):
    print("PIPELINE:", " ".join(map(str, argv)), flush=True)
    output = {"capture_output": True} if capture else {"stdout": sys.stdout, "stderr": sys.stderr}
    return subprocess.run(list(map(str, argv)), cwd=ROOT, env=local_environment(), text=True,
                          **output, check=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def public_text(text, suite):
    # Preserve exact raw evidence locally. Public copy removes workstation paths.
    replacements = [(str(suite), "."), (suite.as_posix(), "."),
                    (str(ROOT), "<project>"), (ROOT.as_posix(), "<project>"),
                    (str(Path.home()), "<user-home>"), (Path.home().as_posix(), "<user-home>")]
    for source, target in replacements:
        text = text.replace(source, target).replace(source.replace("\\", "\\\\"), target)
    return text


def export_results(suite, job_directory):
    """Portable archive contains every PDF/control/TXT plus sanitized reports."""
    destination = ROOT / "results" / suite.name
    destination.mkdir(parents=True, exist_ok=False)
    exports = ROOT / "output" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    archive = exports / f"{suite.name}-all-files.zip"
    text_extensions = {".json", ".csv", ".html", ".txt", ".log"}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(suite.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(suite)
            if path.suffix.lower() in text_extensions:
                text = public_text(path.read_text(encoding="utf-8-sig"), suite)
                zipped.writestr(relative.as_posix(), text.encode("utf-8"))
                if path.name.startswith("comparison.") or path.name.startswith("report.") or path.name == "numbers.txt":
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("x", encoding="utf-8") as stream:
                        stream.write(text)
            else:
                zipped.write(path, relative.as_posix())
        for name in ("installation.json", "requirements-lock.txt"):
            path = ROOT / "tools" / name
            if path.is_file():
                sanitized = public_text(path.read_text(encoding="utf-8"), suite)
                zipped.writestr("setup/" + name, sanitized)
                (destination / name).write_text(sanitized, encoding="utf-8")
        for name in ("tests.log", "environment.json", "source-manifest.json"):
            path = job_directory / name
            if path.is_file():
                sanitized = public_text(path.read_text(encoding="utf-8"), suite)
                zipped.writestr("verification/" + name, sanitized)
                (destination / name).write_text(sanitized, encoding="utf-8")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "archive.json").write_text(json.dumps({"file": archive.name, "sha256": digest,
           "bytes": archive.stat().st_size, "contents": "all PDF trials, all input PDF sets, TXT, QR matrices, raster controls, raw timing requests, sanitized full reports"}, indent=2), encoding="utf-8")
    (destination / "README.md").write_text(
        "# Measured uCode results\n\nThree trials per method and size; QA decides validity. "
        "Generation and merging have separate rankings.\n\n"
        "- [Comparison table](comparison.csv)\n- [Full comparison data](comparison.json)\n"
        "- HTML and per-size reports are saved here.\n\n"
        "Download the ZIP attached to the matching GitHub Release to obtain **all PDF files**. "
        "Extract it and open comparison.html; its local PDF links then work. "
        "This repository stores report copies; binaries, installed dependencies and workstation paths are excluded.\n",
        encoding="utf-8")
    return destination, archive


def record_result(suite, comparison, archive):
    rows = ["\n## Expanded comparison " + comparison["created_at"][:10], "",
            f"Local report: `{suite.relative_to(ROOT).as_posix()}/comparison.html`.",
            f"Local complete archive: `{archive.relative_to(ROOT).as_posix()}`.",
            "", "| Method | 200 median, s | QA | 1000 median, s | QA |",
            "| --- | ---: | --- | ---: | --- |"]
    for method in comparison["methods"]:
        metrics = method["results"]
        def seconds(count):
            value = metrics[count]["median_seconds"]
            return f"{value:.6f}" if value is not None else "not measured"
        rows.append(f"| {method['name']} | {seconds('200')} | {metrics['200']['status']} | {seconds('1000')} | {metrics['1000']['status']} |")
    rows.extend(["", "These are measured values from preserved local reports. Missing or failed methods are not extrapolated.",
                 "CPU/RAM/file sizes and all repeats are in the JSON/CSV. Full suite status: " + comparison["status"] + ".", ""])
    with (ROOT / "docs/WORK_LOG.md").open("a", encoding="utf-8") as stream:
        stream.write("\n".join(rows))
    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    marker = "## Расширенное сравнение: текущая работа 27.10.2026"
    summary = (f"## Сохранённые результаты расширенного сравнения\n\n"
               f"Статус серии: **{comparison['status']}**. "
               f"[Свежая таблица CSV](results/{suite.name}/comparison.csv) · "
               f"[Полные сводные данные JSON](results/{suite.name}/comparison.json) · "
               f"[Файлы и архив](results/{suite.name}/README.md). "
               "Точные замеры и QA по обоим размерам приведены в этих файлах; "
               "предыдущие записи о подготовке ниже сохранены как история.\n\n")
    if marker in content:
        readme.write_text(content.replace(marker, summary + marker, 1), encoding="utf-8")


def publish(repository, export, archive, job_directory):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name")
    owner, name = repository.split("/")
    identity = json.loads(command(["gh", "api", "user"], capture=True).stdout)
    if identity["login"].lower() != owner.lower():
        raise ValueError("GitHub CLI identity does not match authorized repository owner")
    existing = subprocess.run(["gh", "repo", "view", repository, "--json", "nameWithOwner"], cwd=ROOT,
                              env=local_environment(), text=True, capture_output=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if existing.returncode == 0:
        raise FileExistsError("Remote already exists; preserving it: " + repository)
    if "not resolve" not in existing.stderr.lower() and "not found" not in existing.stderr.lower():
        raise RuntimeError("Cannot verify repository absence: " + existing.stderr[-1000:])
    tag = "results-" + export.name.removeprefix("suite-")
    release_url = f"https://github.com/{repository}/releases/tag/{tag}"
    with (export / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n[Download all local-result files]({release_url})\n")
    # The source copy uses an allowlist; local runtime caches and raw output are never staged.
    if (ROOT / ".git").exists():
        raise FileExistsError("A Git repository appeared during work; automatic initial publication stopped")
    command(["git", "init", "-b", "main"])
    command(["git", "config", "user.name", identity["login"]])
    command(["git", "config", "user.email", f"{identity['id']}+{identity['login']}@users.noreply.github.com"])
    allowed = [".gitignore", "AGENTS.md", "README.md", "pyproject.toml", "package.json", "package-lock.json",
               "requirements-engines.txt", "Start-uCode.cmd", "Benchmark-200.cmd", "Benchmark-All.cmd",
               "ucode", "scripts", "tests", "docs", "results"]
    command(["git", "add", "--", *[p for p in allowed if (ROOT / p).exists()]])
    staged = command(["git", "diff", "--cached", "--name-only"], capture=True).stdout.splitlines()
    for filename in staged:
        path = ROOT / filename
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Unexpected large staged file: " + filename)
        if any(part in filename.split("/") for part in (".venv", "tools", "output", "node_modules", ".local-state", ".nuget", "obj", "bin")):
            raise ValueError("Runtime/cache file accidentally staged: " + filename)
        data = path.read_bytes()
        # Fail closed on recognizable credential formats or private key blocks.
        if re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)", data):
            raise ValueError("Credential-shaped text found in staged file: " + filename)
    command(["git", "diff", "--cached", "--check"])
    command(["git", "commit", "-m", "Add modular uCode QR/PDF lab and measured 200/1000 comparison"])
    commit = command(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    command(["gh", "repo", "create", repository, "--public", "--source", ".", "--remote", "origin",
             "--description", "Local vector CMYK QR/PDF laboratory: measured multi-engine merge comparison at 200 and 1000 pages"])
    command(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", "push", "-u", "origin", "main"])
    notes = job_directory / "release-notes.md"
    notes.write_text("Measured 200/1000 QR/PDF comparison with three trials and strict QA.\n\n"
                     "The attached archive contains all local PDFs, inputs, TXT, rendered controls and portable HTML/CSV/JSON. "
                     "Installed tools and environment caches are excluded.\n", encoding="utf-8")
    command(["gh", "release", "create", tag, str(archive), "--repo", repository, "--target", commit,
             "--title", "uCode: measured 200 + 1000 QR/PDF comparison", "--notes-file", notes])
    metadata = json.loads(command(["gh", "repo", "view", repository, "--json", "url,visibility,defaultBranchRef"], capture=True).stdout)
    remote_commit = command(["gh", "api", f"repos/{repository}/commits/main", "--jq", ".sha"], capture=True).stdout.strip()
    if metadata["visibility"] != "PUBLIC" or remote_commit != commit:
        raise RuntimeError("Public remote verification failed")
    release = json.loads(command(["gh", "release", "view", tag, "--repo", repository, "--json", "url,assets"], capture=True).stdout)
    if not any(asset["name"] == archive.name and asset["size"] == archive.stat().st_size for asset in release["assets"]):
        raise RuntimeError("Published release archive is missing")
    return {"repository": metadata["url"], "commit": commit, "release": release["url"], "visibility": metadata["visibility"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", action="store_true")
    parser.add_argument("--publish", help="Explicit user-authorized new public OWNER/NAME")
    args = parser.parse_args()
    if not args.prepared:
        install_all()
        argv = [PYTHON, Path(__file__).resolve(), "--prepared"]
        if args.publish:
            argv += ["--publish", args.publish]
        return command(argv, timeout=3600).returncode
    stamp = datetime.now(timezone(timedelta(hours=3))).strftime("%Y%m%d-%H%M%S")
    job_directory = ROOT / ".local-state" / f"comparison-{stamp}-{uuid.uuid4().hex[:8]}"
    job_directory.mkdir(parents=True)
    status = {"status": "RUNNING", "publication": None}
    try:
        from ucode.environment import inspect_environment
        environment = inspect_environment()
        (job_directory / "environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
        files = list((ROOT / "ucode").rglob("*.py"))
        suffixes = {".py", ".java", ".mjs", ".cs", ".csproj", ".json"}
        files += [p for p in (ROOT / "scripts").rglob("*") if p.is_file() and p.suffix in suffixes
                  and not any(part in ("obj", "bin", "__pycache__") for part in p.relative_to(ROOT).parts)]
        files += [ROOT / name for name in ("pyproject.toml", "requirements-engines.txt", "package.json", "package-lock.json") if (ROOT / name).is_file()]
        files = sorted(set(files))
        (job_directory / "source-manifest.json").write_text(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2), encoding="utf-8")
        with (job_directory / "tests.log").open("x", encoding="utf-8") as stream:
            tested = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT,
                                    env=local_environment(), stdout=stream, stderr=subprocess.STDOUT, timeout=120,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print((job_directory / "tests.log").read_text(encoding="utf-8"), flush=True)
        if tested.returncode:
            raise RuntimeError("Integrated tests failed; tests.log preserved, no publication performed")
        from ucode.suite import run_suite
        suite = run_suite(ROOT / "output/comparisons", progress=lambda message: print(message, flush=True))
        comparison = json.loads((suite / "comparison.json").read_text(encoding="utf-8"))
        export, archive = export_results(suite, job_directory)
        record_result(suite, comparison, archive)
        status.update(status=comparison["status"], suite=str(suite), archive=str(archive), public_reports=str(export))
        if args.publish:
            if comparison["status"] != "COMPLETE":
                raise RuntimeError("Both 200 and 1000 must complete before publishing the result release; local partial files preserved")
            status["publication"] = publish(args.publish, export, archive, job_directory)
        print("FINAL_RESULT " + json.dumps(status, ensure_ascii=False), flush=True)
        for method in comparison["methods"]:
            print(method["name"], json.dumps({count: {k: method["results"][count][k] for k in ("status", "median_seconds", "output_bytes")} for count in ("200", "1000")}), flush=True)
        return 0 if comparison["status"] == "COMPLETE" else 1
    except Exception as exc:
        status.update(status="ERROR", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        print(status["traceback"], flush=True)
        return 1
    finally:
        (job_directory / "final-status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
