#!/usr/bin/env bash
# Print recent merged human-authored code PR numbers for a target repo.
# Usage: list_merged_prs.sh <repo-key> [count]
# Filters: excludes dependabot/pre-commit-ci/renovate; keeps PRs with
# at least 3 changed files OR >=50 added lines OR a non-trivial title.
set -uo pipefail

KEY="${1:?repo key required}"
COUNT="${2:-7}"

case "$KEY" in
  django) GH="django/django" ;;
  fastapi) GH="fastapi/fastapi" ;;
  pydantic) GH="pydantic/pydantic" ;;
  typescript) GH="microsoft/TypeScript" ;;
  nextjs) GH="vercel/next.js" ;;
  sentry) GH="getsentry/sentry" ;;
  aws-sdk-js) GH="aws/aws-sdk-js-v3" ;;
  grpc) GH="grpc/grpc" ;;
  *) echo "unknown repo key $KEY" >&2; exit 2 ;;
esac

# Search merged human PRs (latest first)
gh api "search/issues?q=repo:$GH+is:pr+is:merged+-author:app/dependabot+-author:app/pre-commit-ci+-author:app/renovate&sort=created&order=desc&per_page=50" 2>/dev/null \
  | python3 -c "
import sys, json, subprocess

data = json.load(sys.stdin)
items = data.get('items', [])
gh = '$GH'
target = $COUNT
picked = []

for it in items:
    num = it['number']
    # Cheap title filter to drop pure-docs/sponsor noise
    title = it.get('title') or ''
    tl = title.lower()
    if any(t in tl for t in ('sponsor', 'contributors', 'fastapi people', 'release notes')):
        continue
    # Fetch file count to filter trivial changes
    try:
        r = subprocess.run(['gh','api',f'repos/{gh}/pulls/{num}'], capture_output=True, text=True, timeout=20)
        if r.returncode != 0: continue
        p = json.loads(r.stdout)
    except Exception:
        continue
    if not p.get('merged'): continue
    cf = p.get('changed_files', 0)
    add = p.get('additions', 0)
    if cf < 1 or add < 5:
        continue
    print(num)
    picked.append(num)
    if len(picked) >= target:
        break
"
