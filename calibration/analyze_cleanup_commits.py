#!/usr/bin/env python3
"""Analyze cleanup/follow-up commits across measured merged PRs.

For each PR in calibration/findings/prs/<repo>/pr-N.json, fetch its commit
list from GitHub and identify cleanup-style commits via message regex.
A "cleanup commit" is one whose first message line matches a heuristic
indicating the PR wasn't merge-ready from the first push.

Output: calibration/findings/cleanup_commits.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from glob import glob
from pathlib import Path

PRS_DIR = Path("/home/prop_/projects/lean code/calibration/findings/prs")
OUT = Path("/home/prop_/projects/lean code/calibration/findings/cleanup_commits.json")

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

CLEANUP_RE = re.compile(
    r"\b("
    r"address(?:\s+(?:review|comments?|feedback))?|"
    r"apply\s+suggestions?|"
    r"cr\s+feedback|nit|nits|"
    r"fix\s+(?:typo|tests?|lint|ci|build|formatting|formatter|style|spelling)|"
    r"lint(?:\s+fix)?|format(?:ting)?|prettier|"
    r"cleanup|tidy|polish|"
    r"oops|whoops|oversight|"
    r"revert|undo|"
    r"pr\s+feedback|"
    r"per\s+(?:review|comments?|cr)|"
    r"as\s+per\s+(?:review|comments?)|"
    r"requested\s+changes?|"
    r"regen(?:erate)?(?:\s+(?:snapshots?|fixtures?|generated))?|"
    r"update\s+snapshots?"
    r")\b",
    re.I,
)


def commits_for_pr(gh: str, pr: int) -> list[dict] | None:
    out: list[dict] = []
    page = 1
    while True:
        try:
            r = subprocess.run(
                ["gh", "api", f"repos/{gh}/pulls/{pr}/commits?per_page=100&page={page}"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return None
        try:
            arr = json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
        if not arr:
            break
        out.extend(arr)
        if len(arr) < 100:
            break
        page += 1
    return out


def main() -> int:
    results: dict[str, list[dict]] = {}
    total_prs = 0
    total_with_cleanup = 0
    total_cleanup_commits = 0

    for repo in sorted(os.listdir(PRS_DIR)):
        gh = GH_FOR.get(repo)
        if not gh:
            continue
        repo_results: list[dict] = []
        for jf in sorted(glob(str(PRS_DIR / repo / "pr-*.json"))):
            pr = int(Path(jf).stem.replace("pr-", ""))
            total_prs += 1
            commits = commits_for_pr(gh, pr)
            if commits is None:
                repo_results.append({"pr": pr, "error": "fetch_failed"})
                continue
            cleanup: list[dict] = []
            # Only count NON-FIRST commits as cleanup signal: the first commit
            # is the proposal; later commits matching the cleanup regex are the
            # follow-ups indicating the proposal wasn't merge-ready.
            for c in commits[1:]:
                msg = (c.get("commit") or {}).get("message") or ""
                first_line = msg.splitlines()[0] if msg else ""
                if CLEANUP_RE.search(first_line):
                    cleanup.append({
                        "sha": c["sha"][:8],
                        "msg": first_line[:120],
                        "author": (c.get("author") or {}).get("login") or "?",
                    })
            if cleanup:
                total_with_cleanup += 1
                total_cleanup_commits += len(cleanup)
            repo_results.append({
                "pr": pr,
                "total_commits": len(commits),
                "cleanup_count": len(cleanup),
                "cleanup_commits": cleanup,
            })
        results[repo] = repo_results

    summary = {
        "totals": {
            "prs_analyzed": total_prs,
            "prs_with_cleanup": total_with_cleanup,
            "cleanup_commits_total": total_cleanup_commits,
            "cleanup_pct": round(100.0 * total_with_cleanup / max(1, total_prs), 1),
        },
        "by_repo": results,
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary["totals"], indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
