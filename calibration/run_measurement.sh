#!/usr/bin/env bash
# Measurement runner for one calibration target.
# Usage: run_measurement.sh <repo-key> <git-url>
# Output to calibration/findings/<repo-key>.{json,stderr.log,meta,largest-files.txt}
# Updates calibration/findings/cleanliness.log
#
# Strategy: clone with --depth 50 so the gate can diff HEAD~N..HEAD as a
# representative recent change set. The gate's check subcommand evaluates
# the diff between HEAD~1 and HEAD by default; we override with --base-ref
# to widen the window and produce a meaningful workload.
set -uo pipefail

KEY="${1:?repo key required}"
URL="${2:?git url required}"
DEPTH="${DEPTH:-50}"
BASE_OFFSET="${BASE_OFFSET:-49}"  # diff HEAD~$BASE_OFFSET..HEAD

CAL_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$CAL_DIR/.." && pwd)"
GATE_PY="$ROOT/lean-code-gate-v3/.agent/lean/lean_code_gate.py"
TARGET="$CAL_DIR/repos/$KEY"
FIND="$CAL_DIR/findings"

mkdir -p "$FIND"

if [ ! -d "$TARGET/.git" ]; then
  echo "[$KEY] cloning depth=$DEPTH from $URL"
  if ! git clone --depth "$DEPTH" "$URL" "$TARGET" 2>&1 | tail -3; then
    echo "CLONE_FAILED: $KEY ($URL)" >> "$FIND/cleanliness.log"
    exit 2
  fi
fi

# Find the deepest available commit to diff against
cd "$TARGET"
ACTUAL_DEPTH=$(git rev-list --count HEAD 2>/dev/null || echo 1)
USE_OFFSET=$BASE_OFFSET
if [ "$ACTUAL_DEPTH" -le "$BASE_OFFSET" ]; then
  USE_OFFSET=$((ACTUAL_DEPTH - 1))
fi
if [ "$USE_OFFSET" -lt 1 ]; then
  USE_OFFSET=1
fi
BASE_REF="HEAD~$USE_OFFSET"
cd - > /dev/null

PRE_STATUS=$(cd "$TARGET" && git status --porcelain | sha256sum | awk '{print $1}')

START=$(date +%s)
PYTHONDONTWRITEBYTECODE=1 timeout 600 python3 -B -S "$GATE_PY" check \
  --repo "$TARGET" --base-ref "$BASE_REF" --json \
  > "$FIND/$KEY.json" 2> "$FIND/$KEY.stderr.log"
EXIT=$?
END=$(date +%s)
DUR=$((END-START))

POST_STATUS=$(cd "$TARGET" && git status --porcelain | sha256sum | awk '{print $1}')

if [ "$PRE_STATUS" = "$POST_STATUS" ]; then
  echo "clean: $KEY" >> "$FIND/cleanliness.log"
else
  echo "DIRTY: $KEY" >> "$FIND/cleanliness.log"
fi

cat > "$FIND/$KEY.meta" <<META
repo: $KEY
url: $URL
exit_code: $EXIT
duration_seconds: $DUR
clone_depth: $DEPTH
actual_depth: $ACTUAL_DEPTH
base_ref: $BASE_REF
gate_version: $(python3 -c "import re; m=re.search(r'VERSION = \"([^\"]+)\"', open('$GATE_PY').read()); print(m.group(1) if m else 'unknown')")
META

find "$TARGET" \( -path "*/.git" -o -path "*/node_modules" \) -prune -o \
  \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' -o -name '*.go' -o -name '*.rs' -o -name '*.rb' -o -name '*.cc' -o -name '*.h' \) -type f -print 2>/dev/null \
  | xargs -d '\n' wc -l 2>/dev/null | sort -rn | head -50 > "$FIND/$KEY.largest-files.txt"

echo "[$KEY] exit=$EXIT duration=${DUR}s base=$BASE_REF actual_depth=$ACTUAL_DEPTH"
exit 0
