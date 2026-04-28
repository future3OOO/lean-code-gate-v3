#!/usr/bin/env python3
"""A2: PR size vs review-finding-count tipping point analysis.

For each previously-measured merged PR (42 entries) plus an extended set
of merged PRs from the same repos, fetch:
- additions / deletions / changed_files (size)
- review-comment count (reviewer scrutiny)

Plot bot-comment count vs PR size, look for an inflection.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(__file__).parent / "findings" / "pr_size_data.json"

GH_FOR = {
    "django": "django/django",
    "fastapi": "fastapi/fastapi",
    "pydantic": "pydantic/pydantic",
    "typescript": "microsoft/TypeScript",
    "nextjs": "vercel/next.js",
    "sentry": "getsentry/sentry",
    "aws-sdk-js": "aws/aws-sdk-js-v3",
    "grpc": "grpc/grpc",
}


def gh_json(args: list[str]) -> object:
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    rows = []
    for repo_key, gh in GH_FOR.items():
        # Pull last ~30 merged PRs (mix of bot + human)
        prs = gh_json([f"repos/{gh}/pulls?state=closed&per_page=30"])
        if not isinstance(prs, list):
            continue
        merged = [p for p in prs if p.get("merged_at")]
        for p in merged[:20]:  # cap at 20 per repo
            pr_num = p.get("number")
            if not pr_num:
                continue
            # List endpoint doesn't include additions/changed_files; need detail
            detail = gh_json([f"repos/{gh}/pulls/{pr_num}"])
            if not isinstance(detail, dict):
                continue
            rows.append({
                "repo": repo_key,
                "pr": pr_num,
                "additions": detail.get("additions", 0),
                "deletions": detail.get("deletions", 0),
                "changed_files": detail.get("changed_files", 0),
                "issue_comments": detail.get("comments", 0),
                "review_comments": detail.get("review_comments", 0),
                "total_comments": detail.get("comments", 0) + detail.get("review_comments", 0),
            })
        time.sleep(2)  # gentle pacing — search API has tighter limits

    OUT.write_text(json.dumps(rows, indent=2) + "\n")

    print(f"\nCollected {len(rows)} PRs across {len(GH_FOR)} repos")
    print(f"\n{'bucket':<20} {'n':<5} {'avg add':<10} {'avg comments':<14} {'rate (c/100lines)':<20}")
    print("-" * 75)

    buckets = [(0, 50), (50, 200), (200, 500), (500, 1500), (1500, 5000), (5000, 100000)]
    for lo, hi in buckets:
        in_b = [r for r in rows if lo <= r["additions"] < hi]
        if not in_b:
            continue
        n = len(in_b)
        avg_add = sum(r["additions"] for r in in_b) / n
        avg_c = sum(r["total_comments"] for r in in_b) / n
        rate = (sum(r["total_comments"] for r in in_b) / max(1, sum(r["additions"] for r in in_b))) * 100
        print(f"{lo:>4}-{hi:<5}{'lines':<10} {n:<5} {avg_add:<10.0f} {avg_c:<14.2f} {rate:<20.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
