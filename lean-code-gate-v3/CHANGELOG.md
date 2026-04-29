# Changelog

All notable behavior, policy, schema, and tooling changes to the Lean Code Gate v3 since the initial commit.

This file captures changes made by an AI agent (Claude / Codex) while calibrating the gate against the corpus at [`future3OOO/lean-code-gate-calibration`](https://github.com/future3OOO/lean-code-gate-calibration). Every change is a real PR or commit on this repo's `main`. The intent is to give the gate's original author a single chronological view to review against the canonical design, before any of these changes are considered "blessed."

Format follows a loose [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) shape: grouped by **Detector behavior**, **Policy / config surface**, **JSON output schema**, **Tests**, **Build / Repo**, **Bugfixes**, and **Docs** under each release point. PRs are linked by number; the merged-`main` SHA in parentheses is the squash commit.

---

## [Unreleased] — 2026-04-29

### Detector behavior
- **Reuse detector self-match fix.** `symbol_is_called_nearby` previously matched the new symbol's own def line as a "call" (the regex `\b{name}\s*\(` matches both `def foo(...)` and `foo(args)`). Net effect: when a PR introduced a function whose name already existed in the codebase — the most obvious reuse pattern — the candidate was silently suppressed and no finding fired.

  The fix is symbol-aware: only skip a line if it is *the def of the searched symbol itself*. Default-arg call sites on a different symbol's def line, e.g. `def wrap(x, fn=foo()):`, stay visible as real calls. The implementation reuses `SYMBOL_PATTERNS` directly rather than maintaining a parallel regex table — adding a new language to `SYMBOL_PATTERNS` automatically extends the def-line filter, with no drift risk. (PR [#15](https://github.com/future3OOO/lean-code-gate-v3/pull/15) — `98a4e59`)

  Coverage: Python `def`/`class`, Ruby `def`, JS/TS `function` (with `export`/`export default`/`async`), Go `func` (including receiver methods `func (r *Repo) Name(...)`), Rust `fn`/`pub fn` plus tuple-struct/enum/trait names extracted by `SYMBOL_PATTERNS["rust"]`, shell `name() { ... }` and `function name() { ... }`, PHP `function` with optional `public`/`private`/`protected`/`static`.

  Calibration impact: not yet measured — needs a corpus re-run on the 823-PR dataset to quantify the new findings/PR shift across cohorts. Expected to fire most on AI-coded repos where same-name reimplementation is common.

### JSON output schema
- **Added** two additive top-level keys to `check --json` output (PR [#17](https://github.com/future3OOO/lean-code-gate-v3/pull/17) — `4636b46`):
  - `qualityEscapeLocations` — full list of QE hits (was capped at 10 inside `checks[].sample`).
  - `duplicateBlockCandidates` — pre-threshold dup groups with per-group counts. Useful for calibration sweeps that want to see what's *almost* duplicate.

  Schema-additive only. Existing consumers reading `ok` / `errors[]` / `checks[]` are unaffected.

### Build / Repo
- **`__pycache__/` and `.agent/lean/state/` gitignored** at the gate-repo root (`9e7ab76`). Both are local runtime artifacts that the gate's own preflight stop hook was flagging as untracked changes without a contract.
- **Internal Lean runtime files filtered from changed-file scope.** `.agent/lean/state/**`, `.agent/lean/__pycache__/**`, and `.agent/lean/**/*.pyc` are ignored by the quality gate even if they appear as untracked or committed diff files. This prevents the gate's own runtime state and bytecode cache from requiring a Lean Change Contract. (PR [#21](https://github.com/future3OOO/lean-code-gate-v3/pull/21) — `2ce81e6`)
- **Docs-only:** `scan_quality_escapes` now carries an in-source comment explaining why R-1 uses `is_source_path` while R-2..R-4 use `is_production_source_path`. The asymmetry is intentional — language-agnostic markers like `# type: ignore`, `# noqa`, `eslint-disable`, `|| true` should fire even in test files. Citation: Wen et al. FSE 2025 ("50.8% of suppressions are useless"). (PR [#16](https://github.com/future3OOO/lean-code-gate-v3/pull/16) — `71585f8`)
- **Removed:** the pre-A9 `calibration/` harness (45 tracked files, 5,547 lines deleted) that had been superseded by the standalone `lean-code-gate-calibration` repo. (PR [#18](https://github.com/future3OOO/lean-code-gate-v3/pull/18) — `fd50f77`)

### Codex / global-install support
- **Added** two environment variables for Codex global installs and controller-folder workflows (PR [#19](https://github.com/future3OOO/lean-code-gate-v3/pull/19) + hardening commit `027c528`):
  - `LEAN_CODE_GATE_SCRIPT_PATH` — gate script path used in hook reminders and blocked-mutation messages. Default: repo-local `.agent/lean/lean_code_gate.py`.
  - `LEAN_CODE_GATE_REPO_ROOT` — fallback target repo root for hook runtimes that cannot provide target `workdir`/`cwd`.

  Hardening: `LEAN_CODE_GATE_REPO_ROOT` fails closed when set — exits non-zero on missing path or non-git directory. Command hints use `shlex.quote` (not `json.dumps`) so paths containing `$`, backticks, or spaces don't produce shell-unsafe copy-paste hints. Tests clear both env vars by default to isolate from ambient environment.

- **Repo identity stamped into runtime state.** Lean Change Contracts now record a short `repo_id` derived from the resolved repo root and Git common dir, plus the resolved repo paths. Hook-time mutation checks reject contracts from another repo and reject old unstamped contracts with an explicit redeclare hint. This fixes controller-folder and nested-upstream cases where one `.agent/lean/state` directory could be mistaken for another. (PR [#21](https://github.com/future3OOO/lean-code-gate-v3/pull/21) — `2ce81e6`)

  Security hardening: repo identity no longer reads or persists the `origin` URL. Credential-bearing remotes, SSH-vs-HTTPS switches, and origin URL changes do not affect `repo_id` and cannot leak through `contract.json`, `status`, or `events.jsonl`.

- **Controller-folder hook resolution hardened.** Hooks now prefer tool-supplied `workdir`/`cwd` and support Codex `cmd` payloads as well as Claude `command` payloads. When the hook runtime omits the tool cwd, mutating file operations can infer the nested target repo from changed paths; pathless mutating commands fail closed instead of silently using the controller repo. Stop and verification events are scoped to the remembered target repo(s), so dirty sibling repos under the same controller folder do not cause false final failures. (PR [#23](https://github.com/future3OOO/lean-code-gate-v3/pull/23) — `74f70c8`)

### Tests
- **Added** focused regression tests for the reuse self-match fix that use real tracked diffs (commit a placeholder, modify, `git add` — so the def line lands in `ctx.added_lines`):
  - `test_python_exact_name_duplicate_across_files_fires_on_tracked_diff`
  - `test_go_receiver_method_duplicate_fires_on_tracked_diff`
  - `test_shell_function_duplicate_fires_on_tracked_diff`
  - `test_rust_tuple_struct_duplicate_fires_on_tracked_diff`
  - `test_default_arg_call_on_def_line_does_not_falsely_suppress_reuse` — uses names with shared tokens (`format_currency_amount` vs `format_currency_label`) so `same_behavior_name > 0` and the candidate genuinely reaches `symbol_is_called_nearby`. Carries an explicit `assert score > 0` precondition so the test cannot go vacuous in the future.
- **Added** negative tests for `LEAN_CODE_GATE_REPO_ROOT` fail-closed behavior:
  - `test_repo_root_env_rejects_missing_target_repo`
  - `test_repo_root_env_rejects_non_git_target_repo`
- **Added** repo-identity and runtime-artifact regressions:
  - controller-folder declarations keep state in the target repo and stamp matching `repo_id`
  - credential-bearing origin URLs are not persisted or used for identity
  - copied contracts from another repo are rejected before mutation
  - old unstamped contracts are rejected with a redeclare hint
  - internal `.agent/lean/state` and `__pycache__` artifacts are ignored without a contract, including committed diff cases

  Verified by reverting the reuse self-match fix in-place: the buggy version fails on `test_python_exact_name_duplicate...`. With PR #21 merged, all 49 tests pass. Tests are not vacuous.
- **Added** controller-folder hook regressions for PR #23:
  - nested target repo inference from changed file paths when the hook payload has no tool `workdir`/`cwd`
  - fail-closed behavior for ambiguous pathless mutating commands from a controller folder
  - stop-hook checks scoped to remembered target repos, ignoring dirty unrelated nested repos

---

## [calibration baseline] — 2026-04-28

This is the set of changes the agent landed against the original gate, before the broader 27-repo / 823-PR calibration began. Each detector here was driven by a measured pattern in the original 8-repo / 5-PR-each measurement.

### Detector behavior
- **R-1 (quality escape):** added `excluded_path_globs` config field — paths matching any glob skip detection entirely. Calibrated against generated-code false-positives (smithy/aws-sdk codegen, protobuf, migrations). (PR [#7](https://github.com/future3OOO/lean-code-gate-v3/pull/7) — `a0d84a8`)
- **R-2 (reuse) + R-3 (duplicate-block):** added `framework_override_names` allowlist (39 names: Django `save`/`clean`/`get_queryset`, React `render`/`componentDidMount`, Python dunders `__init__`/`__call__`, etc.) and private/public sibling suppression. Cuts a large class of framework-idiom false positives. (PR [#8](https://github.com/future3OOO/lean-code-gate-v3/pull/8) — landed via squash; `99da321` on `main`)
- **R-7 (abstraction marker density):** added `max_design_marker_density_per_100_lines` policy (default 3.0) and raised the raw-marker threshold to 4. Stops over-firing on small files with one or two abstraction markers. (PR [#9](https://github.com/future3OOO/lean-code-gate-v3/pull/9) — `7500936`)
- **R-4 (bloat):** new bloat thresholds (`bloat_total_added_warn_lines`, `bloat_new_file_warn_lines`, `bloat_add_delete_warn_ratio`, `bloat_large_file_lines`, etc.) calibrated against the actual PR-size distribution. Plus Go/Rust factory regex coverage and `reuse_min_duplicate_count` raised from 2 to 3. (PR [#10](https://github.com/future3OOO/lean-code-gate-v3/pull/10) — `18900ce`)
- **R-2 (reuse) consistency fix:** `high_confidence_reuse` now defers to `same_behavior_name` — if R-2 (framework_override_names) or R-3 (private/public siblings) returns 0, the pair is not promoted to high-confidence reuse either. Previously a generic-name pair could be suppressed by `same_behavior_name` but still fire as high-confidence reuse via a separate code path. (PR [#13](https://github.com/future3OOO/lean-code-gate-v3/pull/13) — squash-merged; `8020582` on `main`)

### Bugfixes
- **`run_process` UTF-8 tolerance.** `subprocess.Popen(text=True)` decodes with strict UTF-8 and crashes when `git diff` output contains non-UTF-8 bytes (binary patches in long multi-commit windows). Switched to `encoding="utf-8", errors="replace"` so non-UTF-8 bytes become `�` instead of raising `UnicodeDecodeError`. Surfaced by the gate running `git diff` over a 100-commit TypeScript window. (PR [#14](https://github.com/future3OOO/lean-code-gate-v3/pull/14) — `9a1872e`)

### Policy / config surface
The merged-PR set above introduced these `policy.json` fields. None existed pre-calibration:
- `excluded_path_globs` (list[str], 24 default entries — codegen, migrations, generated TS/JS, protobuf, smithy)
- `framework_override_names` (list[str], 39 default entries)
- `reuse_min_duplicate_count` (int, default 3 — was 2 implicit)
- `reuse_suppress_private_public_siblings` (bool, default true)
- `max_design_marker_density_per_100_lines` (float, default 3.0)
- `bloat_*` family: `bloat_new_file_warn_lines` (500), `bloat_new_file_error_lines` (800), `bloat_total_added_warn_lines` (500), `bloat_total_added_error_lines` (1000), `bloat_file_growth_lines` (250), `bloat_large_file_lines` (1500), `bloat_large_file_growth_lines` (80), `bloat_add_delete_warn_ratio` (4), `bloat_add_delete_error_ratio` (6), `bloat_large_file_must_shrink` (false)
- `quality_max_index_files` (4000), `quality_max_index_file_bytes` (500000), `quality_max_index_symbols` (25000)
- `reuse_error_score` (90), `reuse_warning_score` (45)

### Tests
- The original `tests/test_lean_code_gate.py` grew from the initial-commit suite to 41 tests on `main` (+5 in the unreleased PR #15 suite, total 43 with the fix landed). New tests pin every detector-behavior change with concrete fixtures rather than mocked symbol stubs. Several rounds of bot review pushed the agent to fix vacuous tests — most notably PR-8's R-2 test using `validate` (which is in `GENERIC_SYMBOLS` and short-circuits the score), PR-9's density test that didn't actually exercise the density branch, and PR-15's first-attempt default-arg test where the chosen names had 0 token overlap and would have passed under any version of the filter.

### Docs
- `METHODOLOGY.md` gained a section on "Codex global script and target root" (`LEAN_CODE_GATE_SCRIPT_PATH` + `LEAN_CODE_GATE_REPO_ROOT`) — see Codex section above.
- `METHODOLOGY.md` and `.agents/skills/lean-code/SKILL.md` now document repo-local runtime state, repo-identity checks, and the one-time redeclare required for older unstamped contracts after upgrade.
- `.agents/skills/lean-code/SKILL.md` carries a one-paragraph note explaining when to set each env var.
- Commit comments inside `lean_code_gate.py` document several intentional asymmetries that bot reviewers initially flagged as bugs: R-1's `is_source_path` vs others' `is_production_source_path`, the Rust pub-type pattern, defense-in-depth role of guards, R-3 framework-override behavior tradeoff.

---

## [initial release] — `ef09de2` (pre-calibration)

The gate as the original author shipped it: R-1..R-6 detectors, a 23-test suite, hook-shaped declare/check/pretool/stop CLI surface, and the original `policy.json`. Nothing in this changelog modifies the *core architecture* — every change is calibration-driven within the existing detector framework.

---

## Reading this changelog

For an architectural review:

1. **Start with PR [#15](https://github.com/future3OOO/lean-code-gate-v3/pull/15) (reuse self-match fix).** It's the only behavior change in `[Unreleased]` that is likely to shift findings on existing repos. The fix is small and well-tested, but the calibration corpus has not yet been re-run against it.
2. **Then look at PR [#10](https://github.com/future3OOO/lean-code-gate-v3/pull/10) (bloat thresholds).** That's where the most policy values changed at once and where the gate's "what counts as bloat" judgement is most calibrated to the corpus.
3. **PR [#7](https://github.com/future3OOO/lean-code-gate-v3/pull/7) and PR [#8](https://github.com/future3OOO/lean-code-gate-v3/pull/8)** define `excluded_path_globs` and `framework_override_names` — both maintained allowlists the agent has shown a tendency to grow. Worth reviewing whether the entries are principled or whether some belong in a more general detector (see open question below).
4. **PR [#19](https://github.com/future3OOO/lean-code-gate-v3/pull/19), PR [#21](https://github.com/future3OOO/lean-code-gate-v3/pull/21), and PR [#23](https://github.com/future3OOO/lean-code-gate-v3/pull/23)** — Codex/controller env-var support, repo-bound runtime state, and hook target-root resolution. Independent of detector calibration; review for whether fallback `LEAN_CODE_GATE_REPO_ROOT`, `repo_id`, and controller-folder semantics fit the rest of the project's idioms.

For a calibration data review, see the `lean-code-gate-calibration` repo's [`HANDOVER.md`](https://github.com/future3OOO/lean-code-gate-calibration/blob/main/HANDOVER.md), [`MAP.md`](https://github.com/future3OOO/lean-code-gate-calibration/blob/main/MAP.md), and [`IMPROVEMENT_PLAN.md`](https://github.com/future3OOO/lean-code-gate-calibration/blob/main/IMPROVEMENT_PLAN.md). Those are the agent's record of what was measured, what was learned, and what's still open.

## Open questions for the original author

Things the agent landed but that should arguably be re-decided by the original designer:

- **Generated-code detection as a first-class detector.** The `excluded_path_globs` list now has 24 default entries and is the dominant FP-suppression mechanism for codegen-heavy repos (aws-sdk-js still emits 12,830 findings in 30 PRs because its smithy directories slipped past the list). A small heuristic detector — license-header pattern match, declaration-to-logic ratio, `eslint-disable-all` sentinel — would let the gate skip these files automatically without manual glob maintenance. **Not implemented.** Would require new detector surface.
- **Per-language threshold tiers.** Rust fires 1.48 findings/PR vs TypeScript 58/PR (15.27 stripping aws-sdk-js) on the calibration corpus. Suspect the same global thresholds applied to languages with different idiom density. The agent did not add per-language `policy.*.json` overlays. Worth thinking about whether the design supports this without breaking the single-source-of-truth shape.
- **R-5 / R-6 surfacing.** Merge-conflict files and temp-artifact files essentially never fire on real PRs (0 hits across 824 corpus runs except one case). They're useful guard rails but inflate the "findings" denominator. A future schema change could move them out of headline counts into a separate `guards: { ... }` block.
- **Reuse-score histogram thresholds.** Original calibration claimed bimodal distribution at 57/62 and ≥95. The expanded 823-PR corpus shows multi-modal clusters at 57, 62, 75, 78, ≥95. The earlier "raise `reuse_warning_score` from 45 to 55 for free" recommendation is no longer free — would lose 10 of 76 reuse warnings on the post-AI cohort. The threshold has not been changed; the recommendation was rolled back.
- **Hook-time integration.** The gate was designed for PR-time. The agent has not measured what happens when the gate is wired into Claude Code / Codex `PostToolUse` hooks against real agent edits. PR-time runtime is fine (p50 = 1s, p95 = 25s on the corpus, 1 timeout in 824 runs), but partial-diff hook-time behavior is unmeasured. See `IMPROVEMENT_PLAN.md` task A15 in the calibration repo.

---

*Maintained by an AI agent. Every entry corresponds to a real commit/PR on this repo. Where the agent made mistakes that needed multiple rounds of bot review, those rounds are folded into the squash commit; the round-by-round detail lives in the PR comment threads.*
