#!/usr/bin/env python3
"""Backfill merged_at / created_at into the existing pr_size_with_gate.json.

The 114-row dataset was captured before pr_size_v2.py started recording
dates. This one-shot script fetches each PR's merged_at and created_at
via gh api and adds them to the existing JSON in place.

Idempotent: rows that already have both fields are skipped.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from _gh_helpers import GH_FOR, gh_json

HERE = Path(__file__).resolve().parent
TARGET = HERE / "findings" / "pr_size_with_gate.json"


def main() -> int:
    rows = json.loads(TARGET.read_text())
    enriched = 0
    skipped = 0
    for r in rows:
        if "merged_at" in r and "created_at" in r:
            skipped += 1
            continue
        gh = GH_FOR.get(r["repo"])
        if not gh:
            continue
        detail = gh_json([f"repos/{gh}/pulls/{r['pr']}"])
        if not isinstance(detail, dict):
            continue
        r["merged_at"] = detail.get("merged_at")
        r["created_at"] = detail.get("created_at")
        enriched += 1
        time.sleep(0.5)

    TARGET.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"backfilled {enriched} rows; {skipped} already had dates; total {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
