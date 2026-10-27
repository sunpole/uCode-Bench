"""Explicit, local-only setup. Never invoked by GUI/doctor automatically."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
NATIVES = [
    {"name": "qpdf", "command": "qpdf", "exe": "qpdf.exe", "version": "12.4.2",
     "url": "https://github.com/qpdf/qpdf/releases/download/v12.4.2/qpdf-12.4.2-msvc64.zip",
     "sha256": "db87077e683630c1217e0e8f9a20a9749d952ab676e881c3689187763a5de25d"},
    {"name": "mutool", "command": "mutool", "exe": "mutool.exe", "version": "1.28.5",
     "url": "https://github.com/ArtifexSoftware/mupdf-downloads/releases/download/1.28.5/mupdf-1.28.5-windows.zip",
     "sha256": "13476a53e84f5527983158acb6442c7853b3cdc022f3b24880780dcfba1fcc99"},
    {"name": "pdfcpu", "command": "pdfcpu", "exe": "pdfcpu.exe", "version": "0.16.3",
     "url": "https://github.com/pdfcpu/pdfcpu/releases/download/v0.16.3/pdfcpu_0.16.3_Windows_x86_64.zip",
     "sha256": "282cb436b6904895fe17cf13e10e8397fcf3ba222084986ac1382340761d3d55"},
]


def local_environment():
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PIP_CACHE_DIR=str(ROOT / ".pip-cache"),
               NPM_CONFIG_CACHE=str(ROOT / ".npm-cache"), DOTNET_CLI_TELEMETRY_OPTOUT="1",
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_NOLOGO="1",
               DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="false",
               DOTNET_SYSTEM_NET_DISABLEIPV6="1",
               DOTNET_CLI_HOME=str(ROOT / ".local-state" / "dotnet"),
               NUGET_PACKAGES=str(ROOT / ".nuget" / "packages"),
               NUGET_HTTP_CACHE_PATH=str(ROOT / ".nuget" / "http-cache"))
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --dns-result-order=ipv4first").strip()
    poppler = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin"
    if poppler.is_dir():
        env["PATH"] = str(poppler) + os.pathsep + env.get("PATH", "")
    return env


def run(argv, *, timeout=600):
    print("SETUP:", " ".join(map(str, argv)), flush=True)
    command = list(map(str, argv))
    subprocess.run(command, cwd=ROOT, env=local_environment(), check=True, timeout=timeout,
                   stdout=sys.stdout, stderr=sys.stderr,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def download(url, destination, expected, algorithm="sha256"):
    if destination.exists():
        if hashlib.new(algorithm, destination.read_bytes()).hexdigest() != expected.lower():
            raise ValueError(f"Existing download has wrong {algorithm}: {destination.name}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex[:8])
    started = last = time.monotonic()
    digest = hashlib.new(algorithm)
    curl = shutil.which("curl.exe")
    if curl:
        subprocess.run([curl, "--fail", "--location", "--connect-timeout", "20", "--max-time", "600",
                        "--retry", "1", "--output", str(temporary), url], check=True, timeout=650,
                       stdout=sys.stdout, stderr=sys.stderr,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if hashlib.new(algorithm, temporary.read_bytes()).hexdigest() != expected.lower():
            raise ValueError(f"Download checksum mismatch: {destination.name}; partial preserved")
        temporary.rename(destination)
        print(f"VERIFIED {destination.name}: {destination.stat().st_size} bytes, {algorithm}={expected}", flush=True)
        return destination
    request = urllib.request.Request(url, headers={"User-Agent": "uCode-Bench/0.2"})
    with urllib.request.urlopen(request, timeout=40) as response, temporary.open("xb") as stream:
        total = int(response.headers.get("Content-Length", 0))
        received = 0
        while True:
            if time.monotonic() - started > 600:
                raise TimeoutError("Download exceeded 600 seconds; partial file preserved")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            now = time.monotonic()
            if now - last >= 2:
                elapsed = max(now - started, 0.001)
                percent = f"{100 * received / total:.1f}%" if total else "unknown %"
                print(f"DOWNLOAD {destination.name}: {received}/{total} bytes {percent}, "
                      f"{received / elapsed / 1048576:.2f} MiB/s, {elapsed:.1f}s", flush=True)
                last = now
    if digest.hexdigest() != expected.lower():
        raise ValueError(f"Download checksum mismatch: {destination.name}; partial preserved")
    temporary.rename(destination)
    print(f"VERIFIED {destination.name}: {received} bytes, {algorithm}={expected}", flush=True)
    return destination


def extract_verified(archive, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (directory / member.filename).resolve()
            if not target.is_relative_to(directory.resolve()):
                raise ValueError("Archive path escapes its tool directory")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = zipped.read(member)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
                    raise FileExistsError(f"Existing tool file differs: {target}")
            else:
                with target.open("xb") as stream:
                    stream.write(data)


def install_all():
    if os.name != "nt":
        raise RuntimeError("This installer is for the authorized Windows workstation")
    TOOLS.mkdir(exist_ok=True)
    state = {"python": {}, "native": [], "extras": {}, "scope": "project local; no global installs or registry writes"}
    mapping = {}
    def save():
        (TOOLS / "installation.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        (TOOLS / "engines.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    if not PYTHON.exists():
        run([sys.executable, "-m", "venv", ROOT / ".venv"])
    specifications = (ROOT / "requirements-engines.txt").read_text().splitlines()
    for spec in specifications:
        if not spec or spec.startswith("#"):
            continue
        try:
            run([PYTHON, ROOT / "scripts/pip_ipv4.py", "install", "--disable-pip-version-check", "--timeout", "20", "--retries", "1", "--only-binary=:all:", spec])
            state["python"][spec] = "INSTALLED"
        except Exception as exc:
            state["python"][spec] = f"ERROR: {exc}"
            if spec.split("==")[0] in ("reportlab", "pypdf", "Pillow"):
                save()
                raise
        save()
    for native in NATIVES:
        row = dict(native)
        try:
            archive = download(native["url"], TOOLS / "downloads" / native["url"].rsplit("/", 1)[1], native["sha256"])
            target = TOOLS / native["name"]
            extract_verified(archive, target)
            candidates = list(target.rglob(native["exe"]))
            if len(candidates) != 1:
                raise ValueError(f"Expected one {native['exe']}, found {len(candidates)}")
            mapping[native["command"]] = candidates[0].relative_to(ROOT).as_posix()
            row["status"] = "INSTALLED"
        except Exception as exc:
            row.update(status="ERROR", error=str(exc))
        state["native"].append(row)
        save()
    try:
        url = "https://downloads.apache.org/pdfbox/3.0.8/pdfbox-app-3.0.8.jar"
        # Verified against the official .sha512 sidecar before this setup was authored.
        sidecar = "768847238f683568507bf73570a2b6fedcbe58b25c7b4f97fba536ba110b290fe96ba065aed58629d41fb94857d76bc1978c2f31d294b553c69f287f71ee9600"
        if len(sidecar) != 128 or any(c not in "0123456789abcdefABCDEF" for c in sidecar):
            raise ValueError("Invalid official PDFBox SHA512 sidecar")
        jar = download(url, TOOLS / "pdfbox" / "pdfbox-app-3.0.8.jar", sidecar, "sha512")
        compiler = shutil.which("javac")
        if not compiler:
            raise RuntimeError("Existing javac was not found")
        classes = TOOLS / "pdfbox" / "classes"
        classes.mkdir(exist_ok=True)
        run([compiler, "--release", "8", "-cp", jar, "-d", classes, ROOT / "scripts" / "PdfBoxMerge.java"])
        state["extras"]["PDFBox"] = {"status": "INSTALLED", "url": url, "sha512": sidecar}
    except Exception as exc:
        state["extras"]["PDFBox"] = {"status": "ERROR", "error": str(exc)}
    save()
    try:
        npm = shutil.which("npm.cmd")
        node = shutil.which("node")
        npm_script = Path(npm).parent / "node_modules/npm/bin/npm-cli.js" if npm else None
        if not node or not npm_script or not npm_script.is_file():
            raise RuntimeError("Existing Node/npm CLI was not found")
        run([node, npm_script, "install", "--ignore-scripts", "--no-audit", "--no-fund"])
        state["extras"]["pdf-lib"] = {"status": "INSTALLED"}
    except Exception as exc:
        state["extras"]["pdf-lib"] = {"status": "ERROR", "error": str(exc)}
    save()
    try:
        dotnet = shutil.which("dotnet")
        if not dotnet:
            raise RuntimeError("Existing .NET SDK was not found")
        run([dotnet, "build", ROOT / "scripts/pdfsharp/PdfSharpMerge.csproj", "--configuration", "Release",
             "--output", TOOLS / "pdfsharp", "--nologo"])
        state["extras"]["PDFsharp"] = {"status": "INSTALLED", "version": "6.2.4"}
    except Exception as exc:
        state["extras"]["PDFsharp"] = {"status": "ERROR", "error": str(exc)}
    save()
    freeze = subprocess.check_output([str(PYTHON), "-m", "pip", "freeze"], env=local_environment(), text=True)
    (TOOLS / "requirements-lock.txt").write_text(freeze, encoding="utf-8")
    print(json.dumps(state, indent=2), flush=True)
    return state


if __name__ == "__main__":
    install_all()
