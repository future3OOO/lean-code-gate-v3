#!/usr/bin/env bash
# Run gate against the latest N merged human-authored PRs for one repo.
# Usage: run_repo_pr_batch.sh <repo-key> [count]
set -uo pipefail

KEY="${1:?repo key required}"
COUNT="${2:-5}"

CAL_DIR="$(cd "$(dirname "$0")" && pwd)"
PRS=$(bash "$CAL_DIR/list_merged_prs.sh" "$KEY" "$COUNT")
echo "[$KEY] PRs to measure: $(echo $PRS | tr '\n' ' ')"
for pr in $PRS; do
  bash "$CAL_DIR/run_pr_measurement.sh" "$KEY" "$pr" || true
done
