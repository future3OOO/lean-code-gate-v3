# Lean Code Gate v3 methodology

## Objective

Force coding agents toward senior-engineer behavior by replacing advisory Markdown with deterministic gates.

The gate optimizes for:

- smallest correct diff
- explicit affected surface for non-trivial code work
- reuse before new code
- no speculative abstractions
- no fake-green suppressions
- no hidden mutation
- verified completion

## What changed from v2

| Critique | V3 change |
|---|---|
| GitNexus references leaked into a portable package | Removed all GitNexus query emission and JSON fields |
| Reuse detector had too much authority for a heuristic | Default mode is conservative: only high-confidence matches fail; weaker signals warn |
| Reuse detector had thin tests | Added coverage for dedupe loops, generic-name false positives, same-token/different-domain cases, deleted-then-recreated helpers, and polyglot same names |
| One-line bug fixes required nine free-text fields | Added `--minimal-preflight` / `--lean` for micro-fixes with hard size and escape-hatch limits |
| `task_type=unknown` triggered confusing preflight behavior | `unknown` is now rejected for mutation contracts when explicit task type is required |
| Large-file defaults were too aggressive for drop-in repos | Large existing files may grow slightly with a warning; large growth still fails. Old must-shrink behavior is policy-controlled |
| Stop-time final checks missed manually added files | Final check now blocks new files unless `--allow-new-files` is declared |
| Verify accounting depended on loose response text | Verification exit-code extraction now walks nested hook responses before falling back to text parsing |

## What was retained from the legacy gate

The legacy gate had several high-value enforcement ideas. V3 keeps the useful deterministic parts and removes environment-specific dependencies.

| Legacy idea | V3 implementation |
|---|---|
| Production preflight | Full contract fields: `affected_surface`, `authoritative_contract`, `invariants`, `reuse_path` or `no_reuse_reason`, `proof_plan`, `risk_check` |
| Existing path / reuse discipline | Required reuse field for full production work plus changed-scope high-confidence reimplementation detector |
| Fake-green cleanup scan | Added-line and untracked-source scans for suppressions, `|| true`, broad catch/pass, empty catch, TODO/FIXME/HACK |
| Duplicate added-code scan | Rolling-window duplicate added-block detector |
| Risk-calibrated bloat | New-file, large-file-growth, per-file-growth, and additive-total thresholds |
| Temp artifact / merge-marker scan | Final quality gate checks changed scope |
| Six hard rules | Exposed as `codeVolume`, `noDuplication`, `shortestPath`, `cleanup`, `anticipateConsequences`, `simplicity` |

## What was intentionally not copied

- Repo Context Forge bootstrap paths.
- GitNexus-specific commands.
- PR quiet-window and delegated-agent governance.
- Environment-specific model defaults.

Those may be useful in one stack but are brittle as a portable baseline. V3 accepts human-written affected-surface evidence through the contract instead of depending on unavailable tools.

## Enforcement layers

1. **Skill file**: tells the agent how to work.
2. **UserPromptSubmit / SessionStart hook**: injects the gate reminder each turn.
3. **Declare command**: stores the Lean Change Contract and baseline diff.
4. **PreToolUse hook**: blocks mutation without a valid contract or outside the contract.
5. **PermissionRequest hook**: denies approval escalation for mutation without a contract.
6. **PostToolUse hook**: records mutations and successful verification commands.
7. **Stop hook**: blocks final completion if verification, scope, budget, preflight, or quality checks fail.
8. **Standalone `check` command**: lets CI/pre-commit run the same quality gate.

## Contract model

Minimal preflight binds the agent to exact intent, exact scope, explicit task type, small budgets, and focused verification. It is intended for micro-fixes only.

Full preflight additionally binds the agent to affected surface, authoritative contract, invariant, reuse path or no-reuse reason, proof plan, and risk checks.

Widening must redeclare the contract with `--widen --reason "..."`.

## Quality model

The final quality gate inspects the changed source scope and fails on:

- merge conflict markers
- temporary artifact paths
- fake-green suppressions
- broad catch/pass and empty catch blocks
- TODO/FIXME/HACK in changed source
- TypeScript `any`/double-cast shortcuts in production source
- Python `Any`/`cast` shortcuts in production source
- duplicate added code blocks
- high-confidence helper or loop reimplementation
- risk-calibrated bloat

Warnings are emitted for moderate bloat and weaker reuse signals. Projects can promote warnings to failures in `.agent/lean/policy.json`.

## Operating guidance

Recommended rollout:

1. Install the package in a repo root.
2. Trust project hooks in Codex or enable project settings in Claude Code.
3. Run `PYTHONDONTWRITEBYTECODE=1 python3 -B -S .agent/lean/lean_code_gate.py check --repo "$PWD"` locally.
4. Use default thresholds for a week.
5. Tune policy only for measured false positives.
6. Add the `check` command to CI or pre-commit for bypass resistance.

### Codex global script and target root

The default Codex config assumes the gate script is installed in the target repo at `.agent/lean/lean_code_gate.py`.

If Codex hooks call a shared/global copy instead, set `LEAN_CODE_GATE_SCRIPT_PATH` to that script path in the hook environment. Hook reminders and blocked-mutation messages will then show the configured path instead of the repo-local default.

If Codex starts from a controller folder while the target repo is nested, set `LEAN_CODE_GATE_REPO_ROOT` to the target repo path. Policy, state, diff checks, and verification status then stay anchored to that repo. Repo-local `.agent/lean/policy.json` remains optional for per-project policy overrides.

The gate stores runtime state under the resolved target repo at `.agent/lean/state/`. Contracts are stamped with a repo id derived from the repo root, git common dir, and origin URL; a contract from another repo or from an older unstamped runtime is rejected instead of being reused silently. Moving a clone, switching worktrees, or changing the origin URL intentionally requires redeclaring the active contract for that target. Runtime state and Python bytecode under `.agent/lean/` are ignored by diff and final checks, but should not be deleted during active work because they record the current contract and verification events. Use `status` to see the target repo, repo id, state path, and whether the active contract matches.

## Limits

The gate is deterministic, not omniscient. It does not prove semantic correctness or global design optimality. It prevents common failure modes that correlate with bloated agent diffs: wide scope, hidden writes, duplicate code, fake green, unverified edits, and unchecked growth. That is not magic, which is rude, but it is enforceable.
