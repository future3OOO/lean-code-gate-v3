#!/usr/bin/env bash
# Print recent merged human-authored code PR numbers for a target repo,
# filtered to require >=3 production-source files AND >=50 added source lines.
# This filter excludes dependabot bumps, translation updates, CI yaml,
# README/docs PRs and similar non-code content.
#
# Usage: list_merged_prs.sh <repo-key> [count]
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
  redis) GH="redis/redis" ;;
  postgres) GH="postgres/postgres" ;;
  pandas) GH="pandas-dev/pandas" ;;
  scikit-learn) GH="scikit-learn/scikit-learn" ;;
  cargo) GH="rust-lang/cargo" ;;
  spark) GH="apache/spark" ;;
  vue) GH="vuejs/core" ;;
  jest) GH="jestjs/jest" ;;
  zed) GH="zed-industries/zed" ;;
  # A10 pre-AI / mature benchmark set
  cpython) GH="python/cpython" ;;
  numpy) GH="numpy/numpy" ;;
  airflow) GH="apache/airflow" ;;
  tokio) GH="tokio-rs/tokio" ;;
  prometheus) GH="prometheus/prometheus" ;;
  # Pre-AI JS/TS additions
  jquery) GH="jquery/jquery" ;;
  react) GH="facebook/react" ;;
  lodash) GH="lodash/lodash" ;;
  eslint) GH="eslint/eslint" ;;
  svelte) GH="sveltejs/svelte" ;;
  # 2019-2020 TypeScript-heavy projects (pre-Copilot dominant codebase)
  vue3) GH="vuejs/core" ;;
  vite) GH="vitejs/vite" ;;
  ts-eslint) GH="typescript-eslint/typescript-eslint" ;;
  *) echo "unknown repo key $KEY" >&2; exit 2 ;;
esac

gh api "search/issues?q=repo:$GH+is:pr+is:merged+-author:app/dependabot+-author:app/pre-commit-ci+-author:app/renovate&sort=created&order=desc&per_page=50" 2>/dev/null \
  | python3 -c "
import sys, json, subprocess
from pathlib import Path

# Production source extensions match the gate's SOURCE_EXTENSIONS
# minus test/docs paths. We approximate the gate's
# is_production_source_path here without importing the gate module.
SOURCE_EXTENSIONS = {
    '.cjs', '.cts', '.go', '.js', '.jsx', '.mjs', '.mts',
    '.php', '.py', '.rb', '.rs', '.sh', '.ts', '.tsx',
    '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.scala', '.java', '.kt',
}
TEST_MARKERS = (
    '/__fixtures__/', '/__mocks__/', '/__snapshots__/', '/__tests__/',
    '/fixture/', '/fixtures/', '/generated/', '/snapshots/',
    '/test/', '/tests/',
)

def is_production_source(path: str) -> bool:
    p = path.lower()
    if Path(p).suffix not in SOURCE_EXTENSIONS:
        return False
    if any(m in '/' + p for m in TEST_MARKERS):
        return False
    if '.test.' in p or '.spec.' in p or 'test_' in Path(p).name:
        return False
    return True

data = json.load(sys.stdin)
items = data.get('items', [])
gh = '$GH'
target = $COUNT
picked = []

for it in items:
    num = it['number']
    title = it.get('title') or ''
    tl = title.lower()
    if any(t in tl for t in ('sponsor', 'contributors', 'fastapi people', 'release notes',
                              'translations', 'translation', 'bump', 'docs:', '📝', '🌐',
                              '⬆', 'changelog', 'chore(deps)')):
        continue
    # Fetch the PR's file list (paginated; cap at one page = 30 files)
    try:
        r = subprocess.run(['gh','api',f'repos/{gh}/pulls/{num}/files?per_page=100'],
                          capture_output=True, text=True, timeout=20)
        if r.returncode != 0: continue
        files = json.loads(r.stdout)
    except Exception:
        continue
    if not isinstance(files, list):
        continue
    src_files = [f for f in files if is_production_source(f.get('filename', ''))]
    if len(src_files) < 3:
        continue
    src_added = sum(int(f.get('additions', 0)) for f in src_files)
    if src_added < 50:
        continue
    print(num)
    picked.append(num)
    if len(picked) >= target:
        break
"
