#!/usr/bin/env bash
# Per-merged-PR measurement runner.
# Usage: run_pr_measurement.sh <repo-key> <pr-number>
# Output: calibration/findings/prs/<repo-key>/pr-<n>.{json,meta,stderr.log}
#
# Strategy: fetch the PR's base.sha and merge_commit_sha into a worktree
# at the merge commit, then run the gate with --base-ref <base.sha>.
# This evaluates exactly the code change a human-approved merged PR
# introduced, giving us "presumed-correct" baseline data.
set -uo pipefail

KEY="${1:?repo key required}"
PR="${2:?PR number required}"

CAL_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$CAL_DIR/.." && pwd)"
GATE_PY="$ROOT/lean-code-gate-v3/.agent/lean/lean_code_gate.py"
TARGET="$CAL_DIR/repos/$KEY"
PR_OUT="$CAL_DIR/findings/prs/$KEY"
WORKTREE="$CAL_DIR/repos/_wt_${KEY}_pr${PR}"

mkdir -p "$PR_OUT"

# Map repo key -> github org/repo
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

# Fetch PR metadata
META_JSON=$(gh api "repos/$GH/pulls/$PR" 2>/dev/null) || {
  echo "GH_API_FAILED: $KEY pr=$PR" >> "$PR_OUT/_failures.log"
  exit 3
}
MERGED=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("merged"))')
if [ "$MERGED" != "True" ]; then
  echo "NOT_MERGED: $KEY pr=$PR" >> "$PR_OUT/_failures.log"
  exit 4
fi
BASE_SHA=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["base"]["sha"])')
MERGE_SHA=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["merge_commit_sha"])')
TITLE=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["title"][:120])')

# Fetch deep enough that base and merge share visible history.
# Squash/rebase merges: merge_sha's first parent IS base_sha. Linear merge:
# merge_sha has 2 parents, one is base_sha. Either way, depth 5 from each
# should let git find a merge-base.
( cd "$TARGET" && git fetch --depth 5 origin "$BASE_SHA" 2>/dev/null
  cd "$TARGET" && git fetch --depth 5 origin "$MERGE_SHA" 2>/dev/null ) || true

# Worktree at merge commit
rm -rf "$WORKTREE"
( cd "$TARGET" && git worktree add --detach "$WORKTREE" "$MERGE_SHA" 2>/dev/null ) || {
  echo "WORKTREE_FAILED: $KEY pr=$PR base=$BASE_SHA merge=$MERGE_SHA" >> "$PR_OUT/_failures.log"
  exit 5
}

# Verify merge-base resolves; if not, fall back to a direct two-dot diff
# baseline (set base ref to first parent of merge commit).
if ! ( cd "$WORKTREE" && git merge-base "$BASE_SHA" HEAD >/dev/null 2>&1 ); then
  PARENT=$(cd "$WORKTREE" && git rev-parse HEAD^ 2>/dev/null || echo "")
  if [ -n "$PARENT" ]; then
    BASE_SHA="$PARENT"
  fi
fi

PRE_STATUS=$(cd "$WORKTREE" && git status --porcelain | sha256sum | awk '{print $1}')

START=$(date +%s)
PYTHONDONTWRITEBYTECODE=1 timeout 300 python3 -B -S "$GATE_PY" check \
  --repo "$WORKTREE" --base-ref "$BASE_SHA" --json \
  > "$PR_OUT/pr-$PR.json" 2> "$PR_OUT/pr-$PR.stderr.log"
EXIT=$?
END=$(date +%s)
DUR=$((END-START))

POST_STATUS=$(cd "$WORKTREE" && git status --porcelain | sha256sum | awk '{print $1}')
CLEAN="clean"
[ "$PRE_STATUS" = "$POST_STATUS" ] || CLEAN="DIRTY"

cat > "$PR_OUT/pr-$PR.meta" <<META
repo: $KEY
github: $GH
pr_number: $PR
title: $TITLE
base_sha: $BASE_SHA
merge_sha: $MERGE_SHA
exit_code: $EXIT
duration_seconds: $DUR
cleanliness: $CLEAN
META

# Cleanup worktree (keep findings)
( cd "$TARGET" && git worktree remove --force "$WORKTREE" 2>/dev/null ) || rm -rf "$WORKTREE"

echo "[$KEY pr=$PR] exit=$EXIT dur=${DUR}s clean=$CLEAN title=\"$TITLE\""
