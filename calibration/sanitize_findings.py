#!/usr/bin/env python3
"""Sanitize machine-specific absolute paths in findings JSON artifacts.

The gate writes its `repo` field as the absolute path it was invoked with
(e.g. `/home/prop_/projects/lean code/calibration/repos/_wt_django_pr21150`).
That leaks workstation context. This script replaces those with a stable
logical identifier `<repo>/_wt_pr<N>` derived from the file's location.

Idempotent: re-running on already-sanitized files is a no-op.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FINDINGS_DIR = Path(__file__).parent / "findings"
WT_RE = re.compile(r"_wt_(?P<key>[\w-]+)_pr(?P<pr>\d+)(?:_\d+)?$")


def sanitize_one(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # File is not JSON (e.g. captured a Python traceback when the gate
        # crashed). Skip — nothing to sanitize.
        return False
    if not isinstance(data, dict):
        return False
    repo = data.get("repo")
    if not isinstance(repo, str) or not repo.startswith("/"):
        return False
    m = WT_RE.search(repo)
    if m:
        replacement = f"{m.group('key')}/_wt_pr{m.group('pr')}"
    elif path.stem.startswith("pr-"):
        replacement = f"{path.parts[-2]}/_wt_pr{path.stem[3:]}"
    else:
        replacement = f"{path.stem}/_50commit_window"
    data["repo"] = replacement
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def main() -> int:
    changed = 0
    total = 0
    for path in sorted(FINDINGS_DIR.rglob("*.json")):
        # Skip the cleanup_commits.json analysis aggregate (no `repo` field)
        if path.name == "cleanup_commits.json":
            continue
        total += 1
        if sanitize_one(path):
            changed += 1
    print(f"sanitized {changed}/{total} findings JSON files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
