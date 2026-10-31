"""Build channel label, not a trust decision.

Preview packages include an explicit generated build-info.json.
Published stable versions without that file default to stable.
Never use this cosmetic metadata to authorize a download/install.
"""
import json
from pathlib import Path
import re

ASSET = Path(__file__).parent / "assets" / "build-info.json"


def build_info():
    result = {"channel": "stable", "commit": None, "build_run": None}
    try:
        raw = json.loads(ASSET.read_text(encoding="utf-8"))
        if raw.get("channel") == "development":
            commit = raw.get("commit")
            run = raw.get("build_run")
            if isinstance(commit, str) and re.fullmatch("[a-f0-9]{40}", commit):
                result["channel"] = "development"
                result["commit"] = commit
                if isinstance(run, str) and re.fullmatch("[0-9]{1,20}", run):
                    result["build_run"] = run
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass
    return result
