#!/usr/bin/env python3
"""A2-v2: PR size vs gate-error vs bot-comment.

For each PR we already have additions/comments for (pr_size_data.json),
also fetch:
- merge_commit_sha and base_sha
- run the v3.0.0 gate against that diff
- record gate error count alongside bot comment count

Output: pr_size_data_with_gate.json — adds gate_errors, gate_warnings columns.

This answers: for a given PR size, does the gate catch what reviewers
would catch? Where do they diverge?
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
IN = HERE / "findings" / "pr_size_data.json"
OUT = HERE / "findings" / "pr_size_with_gate.json"
GATE = Path("/tmp/v300_install/.agent/lean/lean_code_gate.py")
WT_BASE = HERE / "repos" / "_wt_a2v2"

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


def run_gate_on_diff(repo_key: str, base_sha: str, merge_sha: str) -> tuple[int, int, int]:
    """Returns (errors, warnings, source_files) or (-1, -1, -1) on failure."""
    target = HERE / "repos" / repo_key
    if not target.exists():
        return (-1, -1, -1)
    # Fetch SHAs (cheap if present)
    for sha in (base_sha, merge_sha):
        subprocess.run(
            ["git", "fetch", "--depth", "5", "origin", sha],
            cwd=target, capture_output=True, text=True, timeout=60,
        )
    # Worktree at merge SHA
    wt = WT_BASE / f"{repo_key}_{merge_sha[:8]}"
    if wt.exists():
        shutil.rmtree(wt)
    r = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), merge_sha],
        cwd=target, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        return (-1, -1, -1)
    # If base SHA isn't reachable from merge SHA in shallow history, fall back to first parent
    mb = subprocess.run(
        ["git", "merge-base", base_sha, "HEAD"],
        cwd=wt, capture_output=True, text=True, timeout=15,
    )
    if mb.returncode != 0:
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD^"], cwd=wt, capture_output=True, text=True, timeout=10,
        )
        if parent.returncode == 0:
            base_sha = parent.stdout.strip()
    try:
        gate = subprocess.run(
            ["python3", "-B", "-S", str(GATE), "check", "--repo", str(wt), "--base-ref", base_sha, "--json"],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        d = json.loads(gate.stdout)
        result = (len(d.get("errors", [])), len(d.get("warnings", [])), d.get("sourceFilesCount", 0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        result = (-1, -1, -1)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=target, capture_output=True, text=True, timeout=15,
        )
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
    return result


def main() -> int:
    rows = json.loads(IN.read_text())
    enriched = []
    WT_BASE.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rows, 1):
        gh = GH_FOR.get(r["repo"])
        if not gh:
            continue
        # Fetch base + merge SHAs
        detail = gh_json([f"repos/{gh}/pulls/{r['pr']}"])
        if not isinstance(detail, dict):
            continue
        if not detail.get("merged"):
            continue
        base_sha = detail.get("base", {}).get("sha", "")
        merge_sha = detail.get("merge_commit_sha", "")
        if not (base_sha and merge_sha):
            continue
        errs, warns, src = run_gate_on_diff(r["repo"], base_sha, merge_sha)
        r2 = dict(r)
        r2["gate_errors"] = errs
        r2["gate_warnings"] = warns
        r2["gate_source_files"] = src
        # Date stamps for pre-AI vs post-AI bucket research
        r2["merged_at"] = detail.get("merged_at")
        r2["created_at"] = detail.get("created_at")
        enriched.append(r2)
        if i % 5 == 0:
            print(f"  [{i}/{len(rows)}] {r['repo']}/pr-{r['pr']}: gate=({errs},{warns},{src}) bot={r['total_comments']}", flush=True)
        time.sleep(1)
    OUT.write_text(json.dumps(enriched, indent=2) + "\n")
    print(f"\nwrote {OUT}: {len(enriched)} rows")

    # Cleanup the worktree-base scratch directory
    if WT_BASE.exists():
        shutil.rmtree(WT_BASE, ignore_errors=True)

    # Summary
    valid = [r for r in enriched if r["gate_errors"] >= 0]
    print(f"valid runs: {len(valid)}/{len(enriched)}")
    print(f"\n{'bucket':<22} {'n':<4} {'avg add':<10} {'avg gate-err':<14} {'avg bot':<10} {'agree':<8}")
    print("-" * 78)
    for lo, hi in [(0, 50), (50, 200), (200, 500), (500, 1500), (1500, 100000)]:
        in_b = [r for r in valid if lo <= r["additions"] < hi]
        if not in_b:
            continue
        n = len(in_b)
        avg_add = sum(r["additions"] for r in in_b) / n
        avg_ge = sum(r["gate_errors"] for r in in_b) / n
        avg_bot = sum(r["total_comments"] for r in in_b) / n
        # "agree" = PRs where both gate and bots flagged (or both didn't)
        agree = sum(1 for r in in_b if (r["gate_errors"] > 0) == (r["total_comments"] > 0))
        print(f"{lo:>4}-{hi:<5}{'lines':<11} {n:<4} {avg_add:<10.0f} {avg_ge:<14.2f} {avg_bot:<10.2f} {agree}/{n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
