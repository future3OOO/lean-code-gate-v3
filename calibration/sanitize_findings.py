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

PRS_DIR = Path(__file__).parent / "findings" / "prs"
WT_RE = re.compile(r"_wt_(?P<key>[\w-]+)_pr(?P<pr>\d+)$")


def sanitize_one(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    repo = data.get("repo")
    if not isinstance(repo, str) or not repo.startswith("/"):
        return False
    m = WT_RE.search(repo)
    if not m:
        # Fallback: derive from path.parts
        parts = path.parts
        repo_key = parts[-2] if len(parts) >= 2 else "unknown"
        pr_num = path.stem.replace("pr-", "")
        replacement = f"{repo_key}/_wt_pr{pr_num}"
    else:
        replacement = f"{m.group('key')}/_wt_pr{m.group('pr')}"
    data["repo"] = replacement
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def main() -> int:
    changed = 0
    total = 0
    for path in sorted(PRS_DIR.rglob("pr-*.json")):
        total += 1
        if sanitize_one(path):
            changed += 1
    print(f"sanitized {changed}/{total} findings JSON files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
