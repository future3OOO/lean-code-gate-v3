# Lean Code Gate v3

For code, test, config, build, dependency, generated-source, or production-doc changes, use the `lean-code` skill before editing.

Micro-fix contract:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare --minimal-preflight --intent "..." --scope "file1,file2" --task-type bugfix --verify "..."
```

Full production contract:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare --intent "..." --scope "file1,file2" --task-type bugfix --affected-surface "..." --authoritative-contract "..." --invariant "..." --reuse-path "..." --proof-plan "red-green-refactor: ..." --risk-check "..." --verify "..."
```

Use `--no-reuse-reason "specific evidence"` when no existing path fits. Do not use `unknown` as a task type for mutation work.

The hooks enforce scope, budget, reuse discipline, verification, no hidden Bash writes, no dependency churn, no fake-green suppressions, duplicate-code checks, high-confidence helper-reimplementation checks, and risk-calibrated bloat checks.
