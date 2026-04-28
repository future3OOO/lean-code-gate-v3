# Lean Code Gate v3 — Calibration Plan

Date: 2026-04-28
Owner: autonomous calibration pass per `LEAN_CODE_GATE_V3_CALIBRATION_GUIDE.md`

## Goal

Measure Lean Code Gate v3 against 8 production codebases (Django, FastAPI, Pydantic, TypeScript, Next.js, Sentry, aws-sdk-js-v3, gRPC), classify failure modes, then ship calibrated policy + tests + targeted gate code improvements as small precision PRs against `github.com/future3OOO/lean-code-gate-v3`.

## Source of truth

- `LEAN_CODE_GATE_V3_CALIBRATION_GUIDE.md` (gitignored, repo root) — calibration mission, repo list, execution protocol, expected outputs.
- `lean-code-gate-v3/.agent/lean/lean_code_gate.py` and `lean-code-gate-v3/.agent/lean/policy.json` — gate source under measurement.
- `lean-code-gate-v3/tests/test_lean_code_gate.py` — sanity baseline (23 tests must pass).
- `lean-code-gate-v3/AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md` — gate's contract discipline (dogfooded on this work).
- Reference resource: https://github.com/karpathy/autoresearch — methodology cross-reference for autonomous research loops.

## Scope in

- Phase 0: workspace + sanity test.
- Phase 1–2: measurement runs against 8 target repos.
- Phase 3: failure-mode classification.
- Phase 4: proposed calibrated policy + rationale.
- Phase 5: proposed test suite additions.
- Phase 6: final report.
- Phase 7 (extension of guide): land calibrated changes against the gate as small precision PRs.

## Scope out / non-goals

- No edits to gate source during Phase 1–4 (per guide §"Do not modify lean_code_gate.py during measurement").
- No commits to cloned target repos.
- No 9th repo. No history-based analysis (clones are `--depth 1`).
- No deploy. The gate is a measurement tool; "deployment" is just a merged PR.
- No rewriting policy.json from scratch — only diffs justified by data.

## Trusted base

- `main` at `github.com/future3OOO/lean-code-gate-v3`, currently at the initial commit `ef09de2`.

## Delivery map

| # | Branch | Type | Owns | Verification |
|---|---|---|---|---|
| PR-0 | `calibration/scaffolding` | foundation | `calibration/` skeleton + `PLAN.md` + `.gitignore` for `repos/`,`findings/raw/` | v3 23-test suite green |
| measurement | (no branch — local data, pushed under PR-1) | data | `calibration/findings/*` | All 8 JSON valid, cleanliness log all-clean |
| PR-1 | `calibration/analysis` | proof/docs | `calibration/analysis/{matrix.csv,per-detector-hit-rates.md,false-positive-classes.md,false-negative-classes.md}` + committed findings | matrix has 8 rows |
| PR-2 | `calibration/policy` | decision | `calibration/proposed-policy/policy.json` + `analysis/policy-recommendations.md` | each delta cites finding |
| PR-3 | `calibration/tests` | proof/tests | `calibration/proposed-tests/test_calibration_findings.py` | runs to completion |
| PR-4 | `calibration/report` | proof/docs | `calibration/analysis/REPORT.md` | all 6 sections present |
| PR-5 | `gate/excluded-path-globs` | runtime | `lean-code-gate-v3/.agent/lean/{lean_code_gate.py,policy.json}` + tests | 23 + new tests pass |
| PR-6 | `gate/framework-overrides` | runtime | same | 23 + new tests pass |
| PR-7 | `gate/abstraction-density` | runtime | same | 23 + new tests pass |
| PR-8 | `gate/bloat-and-go-factory` | runtime | same | 23 + new tests pass |

Stack depth: **0**. Strictly serial. Each merged before next branched.

## Commit structure

- PR-0..PR-4: single commit per PR. Title: `calibration: <slice>`.
- PR-5..PR-8: each commit pairs (a) gate code change, (b) policy default delta if any, (c) new test, (d) Lean Change Contract block in PR body. Title: `gate: <calibration name>`.

## Verification

- PR-0: `python3 lean-code-gate-v3/tests/test_lean_code_gate.py` → 23 passed.
- measurement: every `findings/<repo>.json` parses; `findings/cleanliness.log` shows `clean:` for every repo measured.
- PR-1: `matrix.csv` 8 rows × ≥10 columns; each `.md` cites repo + file paths.
- PR-2: every JSON delta has a row in `policy-recommendations.md` with current → proposed, finding count, risk.
- PR-3: tests run to completion; skipped tests counted (per guide §5), not erroring.
- PR-5..PR-8: `python3 lean-code-gate-v3/tests/test_lean_code_gate.py` green; new tests added pass; running gate `check` on `lean-code-gate-v3/` itself stays clean.

## Affected surface

- **Mutable in PR-0..PR-4:** `calibration/**` only.
- **Mutable in PR-5..PR-8:** `lean-code-gate-v3/.agent/lean/lean_code_gate.py`, `lean-code-gate-v3/.agent/lean/policy.json`, `lean-code-gate-v3/tests/test_lean_code_gate.py`.
- **Reference-only at all times:** `LEAN_CODE_GATE_V3_CALIBRATION_GUIDE.md` (also gitignored), all `calibration/repos/<target>/**` clones, `lean-code-gate-v3/AGENTS.md/CLAUDE.md/METHODOLOGY.md`.
- **No-change proof surfaces:** existing 23-test suite must remain green across PR-5..PR-8.

## Authoritative contract

The gate's `check` subcommand is the contract under measurement. Its output schema (errors[], warnings[], reuseFindings[], hardRules.*, sourceFilesCount, changedFilesCount) drives the matrix in PR-1. Calibration must not change the schema; it can extend (new fields acceptable) but not break consumers.

## Invariants

1. Cloned target repos are never committed, modified, or pushed.
2. The gate's `check` subcommand creates no repo artifacts (verified per repo via cleanliness check; this is also a v3 test, so any regression is a bug, not just a finding).
3. Existing 23-test suite stays green across every gate PR.
4. Each gate PR ships with at least one new test pinning the calibrated behavior.
5. `policy.json` default values change only when justified by a counted finding.

## Proof plan

- Per-repo: `python3 .agent/lean/lean_code_gate.py check --repo "$PWD" --json` → JSON; `git status --porcelain` empty after.
- Aggregate: `matrix.csv` populated from JSON; counts by detector tabulated.
- Gate PRs: `python3 lean-code-gate-v3/tests/test_lean_code_gate.py` before edit (baseline) and after edit (regression check) + new tests added per PR.

## Checklist

- [x] Initial git repo + push to `github.com/future3OOO/lean-code-gate-v3`.
- [~] PR-0: scaffolding + sanity test.
- [ ] Measurement: clone 8 repos, run gate, capture JSON/meta/stderr/largest-files.
- [ ] PR-1: analysis docs + matrix.csv.
- [ ] PR-2: proposed-policy/policy.json + policy-recommendations.md.
- [ ] PR-3: proposed-tests/test_calibration_findings.py.
- [ ] PR-4: analysis/REPORT.md.
- [ ] PR-5: gate `excluded_path_globs` field.
- [ ] PR-6: gate `framework_override_names` allowlist.
- [ ] PR-7: gate abstraction-marker density.
- [ ] PR-8: gate bloat threshold + Go factory regex.

## Risks / blockers

- **R1 — clone failure / disk:** 8 large clones may fill WSL disk. Mitigation: shallow `--depth 1`, measure each, then `rm -rf calibration/repos/<repo>/` after findings captured. Repos directory is gitignored; only findings are committed.
- **R2 — gate crash on a target repo:** per guide §2.2, capture stderr and stop on that repo. Continue with remaining 7 if isolated; consolidate findings if widespread.
- **R3 — measurement time:** Sentry / TypeScript / Next.js may take 60–300s each. Total measurement budget ~30 min serial. Acceptable.
- **R4 — drift between guide promise and gate behavior:** if the v3 23-test suite fails on initial sanity check, the copy is corrupted. Stop measurement; investigate.
- **R5 — autonomous mandate vs. guide stop conditions:** user instructed not to ask questions; guide instructs to stop on certain conditions. Resolution: document the gap, reroute, continue. Never silently fabricate data.

## Execution handoff

This artifact governs execution. **Do not create a new plan. Do not re-plan.**

- Reference-only paths: `LEAN_CODE_GATE_V3_CALIBRATION_GUIDE.md`, `calibration/repos/**`.
- Mutable paths gated by checklist position.
- Re-walk affected surface before each PR edit and before each PR push.
- Use Claude Code skills `repo-large-implementation`, `production-preflight`, `production-code` per gate PR.
- Mirror this checklist in TaskCreate; keep both in sync.
