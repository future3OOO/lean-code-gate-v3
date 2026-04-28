#!/usr/bin/env python3
"""Self-benchmark: how does our own calibration repo behave?

For every PR we opened (#1-11), pull:
- additions / changed_files (PR size)
- bot review comment count (greptile, devin, coderabbitai)
- author commit count (round-1 push vs round-2 fixes)
- distinct issue count after dedup (multiple bots flagging same line = 1)

Output: calibration/findings/self_benchmark.json + a small summary.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = "future3OOO/lean-code-gate-v3"
OUT = Path(__file__).parent / "findings" / "self_benchmark.json"

BOT_USERS = {"greptile-apps[bot]", "devin-ai-integration[bot]", "coderabbitai[bot]"}


def gh(args: list[str]) -> dict | list:
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def main() -> int:
    rows = []
    for pr_num in range(1, 12):
        pr = gh([f"repos/{REPO}/pulls/{pr_num}"])
        if not pr:
            continue
        comments = gh([f"repos/{REPO}/pulls/{pr_num}/comments?per_page=100"])
        bot_comments = [c for c in comments if c.get("user", {}).get("login") in BOT_USERS] if isinstance(comments, list) else []

        # Distinct issues = unique (path, line, bot, body[:80]) tuples after deduping bots flagging the same line
        seen = set()
        distinct_issues = 0
        for c in bot_comments:
            body = (c.get("body") or "")[:120]
            # Skip "addressed" / "resolved" follow-ups
            if "addressed" in body.lower() or "resolved" in body.lower():
                continue
            # Skip walkthrough-summary auto-comments without specific findings
            if any(t in body for t in ("Walkthrough", "Summary", "<!-- This is an auto-generated", "review_comment_addressed")):
                continue
            key = (c.get("path"), c.get("line") or c.get("original_line"), body[:60])
            if key in seen:
                continue
            seen.add(key)
            distinct_issues += 1

        # Per-bot breakdown
        per_bot: dict[str, int] = defaultdict(int)
        for c in bot_comments:
            user = c.get("user", {}).get("login", "?")
            per_bot[user] += 1

        rows.append({
            "pr": pr_num,
            "title": pr.get("title", "")[:80],
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
            "commit_count": pr.get("commits", 0),
            "bot_comment_count_total": len(bot_comments),
            "distinct_issues": distinct_issues,
            "per_bot": dict(per_bot),
        })

    OUT.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"{'pr':<4} {'add':<6} {'del':<5} {'files':<6} {'commits':<8} {'bot_comments':<13} {'distinct':<9} title")
    print("-" * 100)
    for r in rows:
        print(f"#{r['pr']:<3} {r['additions']:<6} {r['deletions']:<5} {r['changed_files']:<6} {r['commit_count']:<8} {r['bot_comment_count_total']:<13} {r['distinct_issues']:<9} {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
