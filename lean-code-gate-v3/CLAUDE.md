# Lean Code Gate v3

Use `.claude/skills/lean-code/SKILL.md` before any repository mutation.

Minimal micro-fix contract:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare --minimal-preflight --intent "..." --scope "file1,file2" --task-type bugfix --verify "..."
```

Full production contract:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare --intent "..." --scope "file1,file2" --task-type bugfix --affected-surface "..." --authoritative-contract "..." --invariant "..." --reuse-path "..." --proof-plan "..." --risk-check "..." --verify "..."
```

Use `--no-reuse-reason "specific evidence"` if no existing path fits. The project hooks block mutation without a valid contract, out-of-scope edits, oversized diffs, undeclared dependency/config churn, hidden Bash writes, fake-green suppressions, duplicate added blocks, high-confidence helper reimplementation, and bloat.
