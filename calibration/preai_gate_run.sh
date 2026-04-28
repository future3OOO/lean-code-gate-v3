#!/usr/bin/env bash
# A11: Run the calibrated gate against code-heavy merged PRs from pre-AI
# benchmark repos. Output: calibration/findings/preai/<repo>/pr-<n>.json
#
# Usage: bash preai_gate_run.sh <repo-key> <pr-count>
#
# For each PR returned by list_merged_prs.sh:
# 1. Shallow-clone the target repo if not already present.
# 2. Fetch base+merge SHAs (depth 5 each).
# 3. git worktree add the merge commit.
# 4. Run the calibrated gate with --base-ref <BASE_SHA>.
# 5. Tear down worktree, write findings/preai/<repo>/pr-<n>.json + .meta.
set -uo pipefail

KEY="${1:?repo key required}"
COUNT="${2:-5}"
# If $3+ are present, treat them as explicit PR numbers (skip the filter call).
shift 2 2>/dev/null || true
EXPLICIT_PRS="$*"

CAL_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$CAL_DIR/.." && pwd)"
GATE_PY="$ROOT/lean-code-gate-v3/.agent/lean/lean_code_gate.py"
TARGET_BASE="$CAL_DIR/repos/_preai"
PR_OUT="$CAL_DIR/findings/preai/$KEY"

mkdir -p "$TARGET_BASE" "$PR_OUT"

case "$KEY" in
  cpython) GH="python/cpython" ;;
  numpy) GH="numpy/numpy" ;;
  airflow) GH="apache/airflow" ;;
  tokio) GH="tokio-rs/tokio" ;;
  cargo) GH="rust-lang/cargo" ;;
  prometheus) GH="prometheus/prometheus" ;;
  jquery) GH="jquery/jquery" ;;
  react) GH="facebook/react" ;;
  lodash) GH="lodash/lodash" ;;
  eslint) GH="eslint/eslint" ;;
  svelte) GH="sveltejs/svelte" ;;
  vue3) GH="vuejs/core" ;;
  vite) GH="vitejs/vite" ;;
  ts-eslint) GH="typescript-eslint/typescript-eslint" ;;
  *) echo "unknown pre-AI repo key $KEY" >&2; exit 2 ;;
esac

TARGET="$TARGET_BASE/$KEY"
if [ ! -d "$TARGET/.git" ]; then
  echo "[$KEY] cloning depth=2 from $GH"
  git clone --depth 2 "https://github.com/$GH.git" "$TARGET" 2>&1 | tail -2 || {
    echo "CLONE_FAILED: $KEY"; exit 3;
  }
fi

# Use explicit PR list if provided, else call the filter
if [ -n "$EXPLICIT_PRS" ]; then
  PRS="$EXPLICIT_PRS"
else
  PRS=$(bash "$CAL_DIR/list_merged_prs.sh" "$KEY" "$COUNT")
fi
if [ -z "$PRS" ]; then
  echo "[$KEY] no code-heavy PRs available; skipping"
  exit 0
fi

for PR in $PRS; do
  META_JSON=$(gh api "repos/$GH/pulls/$PR" 2>/dev/null) || continue
  MERGED=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("merged"))')
  [ "$MERGED" = "True" ] || continue
  BASE_SHA=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["base"]["sha"])')
  MERGE_SHA=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["merge_commit_sha"])')
  MERGED_AT=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("merged_at",""))')
  TITLE=$(printf '%s' "$META_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["title"][:120])')

  # Fetch SHAs and worktree-add
  ( cd "$TARGET" && git fetch --depth 5 origin "$BASE_SHA" 2>/dev/null
    cd "$TARGET" && git fetch --depth 5 origin "$MERGE_SHA" 2>/dev/null ) || true
  WORKTREE="$CAL_DIR/repos/_preai_wt/${KEY}_pr${PR}"
  rm -rf "$WORKTREE"
  ( cd "$TARGET" && git worktree add --detach "$WORKTREE" "$MERGE_SHA" 2>/dev/null ) || {
    echo "[$KEY pr=$PR] WORKTREE_FAILED"
    continue
  }
  # Fall back to first parent if base not reachable
  if ! ( cd "$WORKTREE" && git merge-base "$BASE_SHA" HEAD >/dev/null 2>&1 ); then
    PARENT=$(cd "$WORKTREE" && git rev-parse HEAD^ 2>/dev/null || echo "")
    [ -n "$PARENT" ] && BASE_SHA="$PARENT"
  fi

  START=$(date +%s)
  PYTHONDONTWRITEBYTECODE=1 timeout 180 python3 -B -S "$GATE_PY" check \
    --repo "$WORKTREE" --base-ref "$BASE_SHA" --json \
    > "$PR_OUT/pr-$PR.json" 2> "$PR_OUT/pr-$PR.stderr.log"
  EXIT=$?
  END=$(date +%s); DUR=$((END-START))

  cat > "$PR_OUT/pr-$PR.meta" <<META
repo: $KEY
github: $GH
pr_number: $PR
title: $TITLE
base_sha: $BASE_SHA
merge_sha: $MERGE_SHA
merged_at: $MERGED_AT
exit_code: $EXIT
duration_seconds: $DUR
META

  ( cd "$TARGET" && git worktree remove --force "$WORKTREE" 2>/dev/null ) || rm -rf "$WORKTREE"

  echo "[$KEY pr=$PR] exit=$EXIT dur=${DUR}s ${TITLE:0:60}"
done

# Cleanup any leftover worktree dirs
rm -rf "$CAL_DIR/repos/_preai_wt"
