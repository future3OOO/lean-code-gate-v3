#!/usr/bin/env bash
# Re-run gate against the same 42 merged PRs that informed the calibration.
# Output: calibration/findings/remeasured/prs/<repo>/pr-<n>.json
set -uo pipefail

CAL_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$CAL_DIR/.." && pwd)"
GATE_PY="$ROOT/lean-code-gate-v3/.agent/lean/lean_code_gate.py"
PR_OUT="$CAL_DIR/findings/remeasured/prs"
mkdir -p "$PR_OUT"

declare -A GH_FOR
GH_FOR[django]="django/django"
GH_FOR[fastapi]="fastapi/fastapi"
GH_FOR[pydantic]="pydantic/pydantic"
GH_FOR[typescript]="microsoft/TypeScript"
GH_FOR[nextjs]="vercel/next.js"
GH_FOR[sentry]="getsentry/sentry"
GH_FOR[aws-sdk-js]="aws/aws-sdk-js-v3"
GH_FOR[grpc]="grpc/grpc"

# Iterate every previously-measured PR (read from existing findings).
for repo_dir in "$CAL_DIR/findings/prs/"*/; do
  KEY=$(basename "$repo_dir")
  GH="${GH_FOR[$KEY]:-}"
  [ -z "$GH" ] && continue
  TARGET="$CAL_DIR/repos/$KEY"
  mkdir -p "$PR_OUT/$KEY"
  for jf in "$repo_dir"pr-*.json; do
    [ -f "$jf" ] || continue
    PR=$(basename "$jf" | sed 's/pr-\(.*\)\.json/\1/')
    META="$repo_dir/pr-$PR.meta"
    [ -f "$META" ] || { echo "[$KEY pr=$PR] missing meta"; continue; }
    BASE_SHA=$(grep '^base_sha:' "$META" | sed 's/^base_sha: //')
    MERGE_SHA=$(grep '^merge_sha:' "$META" | sed 's/^merge_sha: //')
    WORKTREE="$CAL_DIR/repos/_wt_${KEY}_pr${PR}_2"

    # Fetch SHAs (cheap if already present)
    ( cd "$TARGET" && git fetch --depth 5 origin "$BASE_SHA" 2>/dev/null
      cd "$TARGET" && git fetch --depth 5 origin "$MERGE_SHA" 2>/dev/null ) || true
    rm -rf "$WORKTREE"
    ( cd "$TARGET" && git worktree add --detach "$WORKTREE" "$MERGE_SHA" 2>/dev/null ) || continue

    # Verify base reachable; fall back to first parent if not
    if ! ( cd "$WORKTREE" && git merge-base "$BASE_SHA" HEAD >/dev/null 2>&1 ); then
      BASE_SHA=$(cd "$WORKTREE" && git rev-parse HEAD^ 2>/dev/null || echo "$BASE_SHA")
    fi

    PYTHONDONTWRITEBYTECODE=1 timeout 120 python3 -B -S "$GATE_PY" check \
      --repo "$WORKTREE" --base-ref "$BASE_SHA" --json \
      > "$PR_OUT/$KEY/pr-$PR.json" 2>/dev/null
    EXIT=$?
    echo "[$KEY pr=$PR] exit=$EXIT"

    ( cd "$TARGET" && git worktree remove --force "$WORKTREE" 2>/dev/null ) || rm -rf "$WORKTREE"
  done
done
