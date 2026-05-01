---
name: lean-code
description: Enforce minimal, surgical, verified production code changes. Use whenever writing, editing, fixing, refactoring, reviewing, or testing code to prevent overengineering, broad diffs, duplicate helpers, fake-green suppressions, dependency churn, and unverified changes.
---

# Lean Code Gate v3

Use this skill for every task that may modify code, tests, build files, config, generated source, scripts, dependency metadata, or docs generated from code.

The goal is the smallest correct production diff. The gate script is authoritative; the prose is just here because apparently agents still need a bedtime story before not ruining a repository.

For global installs, set `LEAN_CODE_GATE_SCRIPT_PATH` to the gate script path shown by the hook reminder and call that script directly from the hook command. Do not set `LEAN_CODE_GATE_REPO_ROOT` in the normal global hook template; use it only as a fallback for hooks or runtimes that cannot provide the target working directory. The runtime prefers hook-supplied `workdir`/`cwd` when available, including Codex `cmd`/`workdir` and Claude `command`/`cwd` payloads.

The gate keeps runtime state in the target repo at `.agent/lean/state/`. That state is intentionally repo-local, stamped with a repo id, ignored by gate diff checks, and should not be deleted during active work. Run `status` when root selection is unclear; it prints the resolved repo root, repo id, state path, and whether the active contract matches.

After upgrading to repo-id state, older unstamped contracts must be redeclared once.

## Required order

1. Inspect before editing.
2. Choose the smallest viable contract: minimal preflight for micro-fixes, full preflight for larger production work.
3. Declare the Lean Change Contract before the first mutating tool call.
4. Edit only files inside the declared scope.
5. Stay inside file and line budgets.
6. Run the declared verification command after mutation.
7. Let the final stop hook run the quality gate before completion.

## Minimal preflight for micro-fixes

Use this only for small, obvious edits: default budget is at most 2 files, 30 added lines, and 80 changed lines. It cannot use broad scope, new files, dependency changes, Bash writes, or abstraction escape hatches.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare \
  --minimal-preflight \
  --intent "one sentence describing the exact micro-fix" \
  --scope "src/exact_file.py,tests/test_exact_file.py" \
  --task-type bugfix \
  --verify "pytest tests/test_exact_file.py"
```

Minimal preflight is not a loophole. If the final diff exceeds the micro budget, widen with evidence or redeclare full preflight.

## Full production preflight

Use full preflight for features, refactors, multi-file bug fixes, new behavior, or any task with unclear blast radius.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare \
  --intent "one sentence describing the exact requested outcome" \
  --scope "src/exact_file.py,tests/test_exact_file.py" \
  --task-type bugfix \
  --affected-surface "changed boundary plus adjacent callers/no-change surfaces" \
  --authoritative-contract "observable invariant, API contract, or external requirement" \
  --invariant "observable condition proving the contract" \
  --reuse-path "existing helper/module/pattern to extend" \
  --proof-plan "focused regression test plus adjacent invariant check" \
  --risk-check "specific regression or failure mode being guarded" \
  --max-files 2 \
  --max-added-lines 80 \
  --max-changed-lines 160 \
  --verify "pytest tests/test_exact_file.py"
```

When no existing path fits, use `--no-reuse-reason "specific evidence"` instead of inventing a fake reuse path.

## Contract rules

- `--task-type` is mandatory in practice. `unknown` is rejected for mutation contracts.
- `--scope` must name exact files or narrow globs.
- `--verify` is required unless `--no-tests-reason` gives a concrete reason.
- Full production work requires affected surface, authoritative contract, invariant, proof plan, risk check, and reuse path or no-reuse reason.
- Placeholder values like `none`, `n/a`, `unknown`, and `tbd` do not satisfy required fields.

Allowed task types: `bugfix`, `feature`, `refactor`, `test`, `docs`, `config`, `unknown`.

## Widening

Only widen after inspection proves the original contract is wrong or incomplete.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py declare \
  --widen \
  --reason "new evidence requiring wider scope or budget" \
  --intent "..." \
  --scope "exact/file/a.ts,exact/file/b.ts,tests/exact.test.ts" \
  --task-type bugfix \
  --affected-surface "..." \
  --authoritative-contract "..." \
  --invariant "..." \
  --reuse-path "..." \
  --proof-plan "..." \
  --risk-check "..." \
  --verify "pnpm test exact.test.ts"
```

Escape hatches need evidence:

- `--allow-new-files`: user requested a new file or no existing file is appropriate.
- `--allow-dependency-changes`: user explicitly requested dependency work or correctness requires it.
- `--allow-config-changes`: config files are the target.
- `--allow-abstractions`: at least two current call sites need the abstraction now.
- `--allow-bash-writes`: Edit/apply_patch cannot express the change safely.
- `--allow-quality-warnings`: the warning is understood and accepted.
- `--no-tests-reason "..."`: only for changes that cannot reasonably be verified by tests.

## Implementation rules

- Minimum code that solves the requested behavior.
- Extend existing implementation before adding a parallel one.
- No single-use factories, managers, registries, adapters, strategies, plugins, feature flags, or configuration knobs.
- No new package if standard library or an existing package solves the problem cleanly.
- No second package manager or second lockfile.
- No broad error handling for impossible scenarios.
- Treat reads from environment, credential files, keyrings, auth/cookie headers, private keys, or git remote URLs as sensitive input; name the risk in `--risk-check` and never log, serialize, cache, snapshot, or emit the values.
- No fake-green patterns: `|| true`, blanket suppressions, broad catch/pass, empty catch, `eslint-disable`, `@ts-ignore`, `@ts-expect-error`, `# type: ignore`, `# noqa`.
- No `TODO`, `FIXME`, `HACK`, placeholders, dummy adapters, temporary bypasses, or unfinished stubs in changed source.
- Delete only orphans created by your own change.
- Do not clean unrelated legacy debt unless the user asked.

## Verification rules

For bug fixes:

1. Add or update the smallest test that reproduces the bug.
2. Make it pass with the smallest production change.
3. Run the declared focused verification.
4. Run broader checks only when the affected surface requires them.

For refactors:

1. Establish current behavior with a relevant check when practical.
2. Make the smallest behavior-preserving change.
3. Run the same check after.
4. Do not add behavior.

Before final completion, the stop hook runs the built-in gate. CI/pre-commit can run the same gate directly:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py check --repo "$PWD"
```

The quality gate fails on changed-scope evidence of merge conflict markers, temp artifacts, fake-green suppressions, duplicate added blocks, high-confidence helper reimplementation, and risk-calibrated bloat. Lower-confidence reuse and moderate large-file growth are warnings by default.

## Final response shape

Report only:

- Contract: intent, files, budget used.
- Changed: concise file-by-file summary.
- Verified: commands run and result.
- Not done: explicit gaps, if any.

Do not include speculative future improvements unless the user asked for them.
