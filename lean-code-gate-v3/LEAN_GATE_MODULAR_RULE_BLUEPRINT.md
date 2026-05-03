# Lean Gate Modular Rule Blueprint

## Objective

Turn Lean Code Gate into a deterministic enforcement engine while keeping the existing skills as the reasoning layer.

```text
repo-context-forge       -> target-surface intake and coverage plan
gitnexus                 -> graph impact, callers, contracts, blast radius
claude-advisor           -> read-only semantic challenge before preflight and before commit
production-preflight      -> edit-boundary reasoning
test-driven-development   -> behavior proof
production-code           -> quality standard and final judgment
lean-code-gate            -> contract storage, hook enforcement, rule reporting
```

Lean Gate should block deterministic violations. Skills should explain how to reason through the work and recover correctly.

Claude Advisor belongs in the reasoning layer, not the deterministic gate core. It can replace or supplement sub-agent delegation as a consolidated read-only challenger after Repo Context Forge and GitNexus have fixed the surface. Lean Gate may record externally supplied advisor events later, but hooks must not call Claude, GitNexus, Repo Context Forge, or any LLM-dependent process.

## Target Module Shape

```text
.agent/lean/
  lean_code_gate.py
  lean_gate/
    cli.py
    hooks.py
    contracts.py
    state.py
    repo.py
    mutation.py
    verification.py
    policy.py
    output.py
    rules/
      catalog.py
      results.py
    quality/
      runner.py
      escapes.py
      bloat.py
      duplicate.py
      reuse.py
      symbols.py
      advisory.py
```

Responsibilities:

- `lean_code_gate.py`: thin entrypoint only.
- `cli.py`: command parsing and dispatch.
- `hooks.py`: session, pretool, posttool, permission, and stop handlers.
- `contracts.py`: declare, validate, widen, and contract identity checks.
- `state.py`: repo-local state, event log, contract persistence.
- `repo.py`: root, worktree, nested repo, and global-script resolution.
- `mutation.py`: mutating-tool detection, scope checks, budget checks, hidden-write checks.
- `verification.py`: verify-command recognition and pass/fail accounting.
- `policy.py`: baseline defaults plus repo policy merge.
- `output.py`: stable human and JSON hook output.
- `rules/catalog.py`: stable rule IDs, messages, remediation, skill references, examples.
- `rules/results.py`: `RuleResult` data model and helpers.
- `quality/*`: changed-scope quality scanners.

## Rule Catalog

Every blocker and warning should come from a stable rule ID. Do not scatter one-off error strings through hook logic.

```python
RULES = {
    "contract.missing": {
        "severity": "block",
        "skill": "lean-code",
        "skillSection": "Minimal preflight for micro-fixes",
        "message": "No active Lean Change Contract.",
        "remediation": "Declare a minimal or full contract before editing.",
    },
    "proof.tdd_missing": {
        "severity": "block",
        "skill": "test-driven-development",
        "skillSection": "RED-GREEN-REFACTOR",
        "message": "Code work proof plan does not name a TDD feedback loop.",
        "remediation": "Add a failing behavior or regression test first, or declare an approved exception.",
    },
    "quality.fake_green": {
        "severity": "block",
        "skill": "production-code",
        "skillSection": "Non-Negotiable Rules",
        "message": "Changed source contains a fake-green suppression.",
        "remediation": "Remove the suppression and fix the underlying failure.",
    },
}
```

## Rule Result Shape

Use one structured result shape everywhere.

```json
{
  "ruleId": "contract.missing",
  "severity": "block",
  "phase": "PreToolUse",
  "message": "No active Lean Change Contract.",
  "skill": "lean-code",
  "skillSection": "Minimal preflight for micro-fixes",
  "remediation": "Declare a minimal or full contract before editing.",
  "exampleCommand": "python3 -B -S .agent/lean/lean_code_gate.py declare --minimal-preflight ..."
}
```

The hook output should be self-contained enough for an agent to recover immediately. The skill reference is supporting context, not the only instruction.

## Human Hook Output

Example:

```text
Lean Code Gate blocked mutation.

Rule: contract.missing
Skill: lean-code -> Minimal preflight for micro-fixes
Fix: Declare a minimal or full contract before editing.

Example:
python3 -B -S .agent/lean/lean_code_gate.py declare --minimal-preflight \
  --intent "fix exact bug" \
  --scope "src/file.py,tests/test_file.py" \
  --task-type bugfix \
  --verify "pytest tests/test_file.py"
```

## Skill Routing

Map failures to the skill that tells the agent how to recover:

| Failure | Rule Example | Skill |
|---|---|---|
| Missing contract | `contract.missing` | `lean-code` |
| Missing affected surface, contract, risk, or reuse path | `contract.preflight_field_missing` | `production-preflight` |
| Missing TDD loop or failed verification | `proof.tdd_missing`, `verification.failed` | `test-driven-development` |
| Fake green, TODO, duplicate helper, bloat, type escape | `quality.*` | `production-code` |
| Out-of-scope mutation or oversized diff | `mutation.*` | `production-preflight` plus `lean-code` |

## Preflight To Contract Bridge

A compact `production-preflight` output can map directly to a Lean contract.

Preflight:

```md
`scope`: src/search.ts, tests/search.test.ts
`contract`: path-like searches return real clickable file results
`approach`: extend existing path parser, no new search backend
`proof`: red-green-refactor: npm test -- search.test.ts
`touchpoints`: src/search.ts, tests/search.test.ts
`risksAndQuestions`: none
```

Generated Lean declaration:

```bash
python3 -B -S .agent/lean/lean_code_gate.py declare \
  --intent "fix path search for clickable file results" \
  --scope "src/search.ts,tests/search.test.ts" \
  --task-type bugfix \
  --affected-surface "path search and result opening flow" \
  --authoritative-contract "path-like searches return real clickable files" \
  --invariant "normal filename search still works" \
  --reuse-path "existing path parser/search adapter" \
  --proof-plan "red-green-refactor: npm test -- search.test.ts" \
  --risk-check "avoid introducing a second search path" \
  --verify "npm test -- search.test.ts"
```

## Failure Examples

Out-of-scope edit:

```json
{
  "ruleId": "mutation.out_of_scope",
  "skill": "production-preflight",
  "message": "Edit touches src/newSearch.ts outside declared scope.",
  "remediation": "Keep the change inside scope or redeclare with --widen and a concrete reason."
}
```

Missing verification:

```json
{
  "ruleId": "verification.missing_after_mutation",
  "skill": "test-driven-development",
  "message": "Mutation occurred but the declared verify command has not passed.",
  "remediation": "Run the declared verification command and fix failures before completion."
}
```

Fake green:

```json
{
  "ruleId": "quality.fake_green",
  "skill": "production-code",
  "message": "Changed source contains '|| true'.",
  "remediation": "Remove the bypass and make the command fail honestly."
}
```

## Policy Layers

Policy should resolve in this order:

1. Baseline defaults.
2. Repo-local `.agent/lean/policy.json`.
3. Branch or CI policy overrides.
4. Declared contract exceptions with evidence.

Exceptions should require a reason and should stay visible in the active contract.

## Hard Fail Discipline

Keep hard blocks for deterministic issues:

- missing or invalid contract
- out-of-scope mutation
- hidden file-changing Bash without declaration
- missing or failed declared verification
- fake-green suppressions
- new files or dependency changes without declaration
- oversized diff beyond contract budget
- merge conflict markers and temporary artifacts

Keep heuristic detectors as warnings unless confidence is high enough to be deterministic in changed scope.

## Stop Report Shape

Final stop output should group issues by:

- contract errors
- scope and budget errors
- verification errors
- quality errors
- warnings

This makes the recovery path obvious and avoids one long mixed error string.

## Install Modes

Support two explicit modes:

- Repo-local install: script and state live under the target repo at `.agent/lean/`.
- Global script install: shared script path, repo-local state under the target repo.

Avoid mixed modes that make root and state resolution ambiguous. Do not hard-code a global `LEAN_CODE_GATE_REPO_ROOT` unless the runtime cannot provide a working directory.

## Implementation Order

1. Extract `rules/catalog.py` and route existing blocker/warning strings through rule IDs.
2. Add `RuleResult` and centralized `output.py`.
3. Split contract, state, repo, and hook logic without changing behavior.
4. Split quality checks into `quality/*`.
5. Add tests asserting each blocker emits the correct `ruleId`, skill, remediation, and example.
6. Add the preflight-to-contract helper after extraction is stable.

## Design Constraint

Lean Gate must stay deterministic. Skill references explain recovery, but hard blocks should not depend on LLM judgment.

Advisor output is evidence for Codex to validate, not a rule result. If future telemetry records advisor verdicts, store them as separate challenge events and keep deterministic rule failures independent of advisor availability, auth state, model output, or network state.
