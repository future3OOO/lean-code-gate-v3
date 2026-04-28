#!/usr/bin/env python3
"""A6: Recompute every claimed metric on the production-code-only subset.

The original dataset (114 PRs) is 40% non-code (dependabot bumps,
translations, CI yaml, docs). Filtering by gate_source_files >= 1
excludes those. Result: how do the headline numbers shift?

Comparisons:
- A2-v2 PR-size buckets: full vs code-only.
- PR-level FP rate (PRs that errored / PRs total): full vs code-only.
- Per-LOC rate: full vs code-only.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / "findings" / "pr_size_with_gate.json").read_text())


def bucketize(rows: list[dict]) -> list[tuple[str, int, float, float, float, float, float]]:
    out = []
    for lo, hi in [(0, 50), (50, 200), (200, 500), (500, 1500), (1500, 100000)]:
        in_b = [r for r in rows if lo <= r.get("additions", 0) < hi]
        if not in_b:
            continue
        n = len(in_b)
        sum_add = sum(r["additions"] for r in in_b)
        avg_add = sum_add / n
        sum_ge = sum(r["gate_errors"] for r in in_b if r.get("gate_errors", 0) >= 0)
        avg_ge = sum_ge / n
        rate_ge = (sum_ge / max(1, sum_add)) * 100
        sum_bot = sum(r["total_comments"] for r in in_b)
        avg_bot = sum_bot / n
        rate_bot = (sum_bot / max(1, sum_add)) * 100
        out.append((f"{lo}-{hi}", n, avg_add, avg_ge, rate_ge, avg_bot, rate_bot))
    return out


def fp_rate(rows: list[dict]) -> tuple[int, int, float]:
    n = len(rows)
    errored = sum(1 for r in rows if r.get("gate_errors", 0) > 0)
    return errored, n, (100 * errored / n if n else 0)


def main() -> None:
    full = DATA
    code_only = [r for r in DATA if r.get("gate_source_files", 0) >= 1]

    print(f"Full dataset:      n={len(full)}")
    print(f"Code-only subset:  n={len(code_only)} ({100*len(code_only)/len(full):.1f}%)")
    print()

    print("PR-level error rate (PRs that produced gate errors / total PRs):")
    e_full, n_full, r_full = fp_rate(full)
    e_co, n_co, r_co = fp_rate(code_only)
    print(f"  full:      {e_full:>3}/{n_full} = {r_full:.1f}%")
    print(f"  code-only: {e_co:>3}/{n_co} = {r_co:.1f}%")
    print()

    print("PR-size buckets — FULL dataset:")
    print(f"  {'bucket':<12} {'n':<4} {'avg-add':<8} {'avg-err':<8} {'err/100L':<10} {'avg-bot':<8} {'bot/100L':<8}")
    for row in bucketize(full):
        print(f"  {row[0]:<12} {row[1]:<4} {row[2]:<8.0f} {row[3]:<8.2f} {row[4]:<10.4f} {row[5]:<8.2f} {row[6]:<8.4f}")
    print()
    print("PR-size buckets — CODE-ONLY subset:")
    print(f"  {'bucket':<12} {'n':<4} {'avg-add':<8} {'avg-err':<8} {'err/100L':<10} {'avg-bot':<8} {'bot/100L':<8}")
    for row in bucketize(code_only):
        print(f"  {row[0]:<12} {row[1]:<4} {row[2]:<8.0f} {row[3]:<8.2f} {row[4]:<10.4f} {row[5]:<8.2f} {row[6]:<8.4f}")
    print()

    # Per-repo FP rate
    print("Per-repo FP rate (full vs code-only):")
    print(f"  {'repo':<12} {'full':<10} {'code-only':<14}")
    for repo in sorted({r["repo"] for r in full}):
        in_full = [r for r in full if r["repo"] == repo]
        in_co = [r for r in in_full if r.get("gate_source_files", 0) >= 1]
        ef, nf, rf = fp_rate(in_full)
        ec, nc, rc = fp_rate(in_co)
        co_str = f"{ec}/{nc} = {rc:.1f}%" if nc else "no code-only PRs"
        print(f"  {repo:<12} {ef}/{nf}={rf:>4.1f}%   {co_str}")


if __name__ == "__main__":
    main()
