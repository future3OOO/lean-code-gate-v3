# Slop Scan Calibration Plan

## Purpose

This plan covers calibration methodology only. Runtime Lean Gate detector implementations belong in `LEAN_GATE_IMPROVEMENT_PLAN.md`.

Slop Scan's benchmark suggested our flat pre/post results might be a measurement problem, not just a detector problem. The Step Zero work below confirmed that; this plan now governs the follow-up calibration work needed before porting detectors.

## Status of Step Zero

The Step Zero comparison is **complete**. Calibration repo PR #2 (`experiment/slopscan-comparison`) ships three experiments:

1. **`analysis/slopscan_comparison.md`** — slop-scan whole-repo scan vs our gate per-PR rates on 15 TS/JS repos in our regular calibration corpus. Original framing reported a near-zero cross-tool correlation (~0.07–0.19) which was withdrawn — that comparison correlated incommensurable scopes (whole-repo state vs per-PR diff).
2. **`analysis/slopscan_per_pr_comparison.md`** — slop-scan delta per PR vs our gate per PR on the corrected structured join: 207 parsed PRs, tied-rank Spearman ρ = 0.089–0.463, and Pearson r = 0.250–0.383. Pattern-overlap evidence only; not independent calibration ground truth.
3. **`analysis/lean_on_slopscan_benchmark.md`** — our gate run against slop-scan's own 18-repo pinned benchmark in whole-repo mode (using a `sed`-patched gate variant). Cohort separation: our 1.18× per-KLOC vs slop-scan's 5.39×.

All three are the canonical cross-references for any future calibration work in this area.

## What we learned

The plan's earlier `Explain flat signals` question is answered: Lean Gate's flat cohort signal has **all four** of the causes the original plan listed, in roughly this order of impact.

1. **Detector coverage gap (largest cause).** Zero rule-family overlap on the 10 highest-signal slop-scan rules. Slop Scan catches AI-idioms (placeholder comments, generic envelopes, `as any` casts, error swallowing, etc.). Our R-1..R-6 are general structural detectors. Different target sets. This is the load-bearing cause and is being tracked in `LEAN_GATE_IMPROVEMENT_PLAN.md`.

2. **Scope-of-measurement gap (PR-diff vs whole-repo).** Slop Scan accumulates findings across the whole codebase; our gate sees only what each PR touched. AI-coded repos accumulate slop across many files; PR-diff sampling sees a thin slice. The corrected per-PR join shows pattern overlap, strongest on `addedCount` (ρ = 0.463), while whole-repo per-KLOC density only weakly agrees at ρ = 0.25 because the rule sets target different patterns.

3. **Baseline contamination.** Earlier drafts called this "pre_ai cohort baseline." The label was renamed to `recent_mature_oss` after the data showed the sampled PRs are 67% from 2026, not historical. A real pre-AI baseline requires sampling PRs that pre-date Copilot's mainstream use (~2022). This is unfinished work (A12 — within-repo temporal split).

4. **Corpus language coverage.** Slop Scan is JS-family only; our cross-tool comparisons skip 12 of our 27 corpus repos (Python/Go/Rust/C++). Cohort claims that include those repos cannot be validated against slop-scan numbers.

## Cross-tool correlations as a calibration metric

The cross-tool experiments give us concrete numbers to track as detectors are ported:

- **Per-PR addedCount overlap** (`slopscan_per_pr.csv`): current ρ = 0.463, r = 0.383 on the corrected parsed-PR join. Track as detector-overlap telemetry, not as a calibration success criterion.
- **Whole-repo per-KLOC agreement** (`lean_on_slopscan_benchmark.csv`): current ρ = 0.255. Should rise as we close detector coverage gaps. A target value isn't appropriate — slop-scan's 6.9× cohort separation is on their own corpus and shouldn't be set as a goal on ours.
- **Cohort separation lift on `recent_mature_oss` vs `post_ai_public` + `private_own`** (`COHORT_TABLE.csv`): currently 1.18× per-KLOC equivalent. Should rise as language-agnostic detectors (placeholder-comments, error-swallowing) ship.

## Required calibration work

In rough priority order:

1. **A12 — within-repo temporal split.** The unfinished pre-AI baseline work. Sample pre-2023 PRs from django, react, lodash, cpython, fastapi (repos with enough history) using `expand_pr_lists.py --max-merged-at 2022-12-31`. Build a `historical_pre_ai` cohort. Run the gate. Report alongside `recent_mature_oss` to give a real pre/post-AI temporal contrast on the same repos. This is what the renamed `recent_mature_oss` cohort cannot provide.

2. **Normalized output expansion in `aggregate_by_language.py`.** Add `findings/KLOC` and `findings/function` columns alongside the existing `findings/PR`. Use the per-PR `bloat.totalAdded` as the LOC denominator (already in our JSON). Function count needs a small extractor — slop-scan uses TS-AST for theirs, but the cohort-separation utility doesn't require precision; a per-language regex over `def `/`function `/`func ` is enough for first calibration. Optional: report a geometric-mean `blended_score` across the three normalizations to match slop-scan's published shape and make cohort claims comparable.

3. **`--whole-repo` mode as a real gate flag.** The `lean_on_slopscan_benchmark.sh` script currently uses a `sed`-patched gate (`...HEAD` → `..HEAD`) plus a synthetic empty-commit base. Promote this to a real flag in `lean_code_gate.py` so the calibration pipeline can swap modes without patching. Spec: `--whole-repo` swaps three-dot for two-dot diff and accepts an empty-tree base when `--base-ref` is omitted. Single-PR change on the gate repo. Tests: pin the existing `lodash` whole-repo result (160 changed files, 113 findings).

4. **Detector-port verification loop.** When `placeholder-comments` (or any other rule from `LEAN_GATE_IMPROVEMENT_PLAN.md`) ships:
   - Re-run the calibration corpus against the new gate version.
   - Re-run the slop-scan per-PR head-to-head to measure new ρ vs `addedCount`.
   - Re-run the slop-scan-benchmark (18 repos whole-repo) to measure new cohort-separation ratio.
   - Document delta-from-baseline in a short writeup; do not silently accept a regression on existing detectors.

5. **Boundary-path allowlist research** (precondition for `generic-status-envelopes`). Before any detector ships that targets `{success, data, error}` envelopes or `Record<string, unknown>` casts, sample 20–30 instances across the corpus and classify which paths legitimately require those shapes (REST API boundaries, RPC handlers, JSON config readers). The output is an `allowed_envelope_paths` list comparable to `excluded_path_globs`. Without this work, the detector will fire on legitimate API code in every cohort.

6. **Per-rule signal sweep on the calibration corpus.** Slop Scan publishes a `rule-signal-mini` benchmark scoring each rule's separating power in isolation. Mirror that for any new rule we port: run gate-with-rule and gate-without-rule against the corpus, measure cohort-median lift per rule. Don't escalate any rule from warn → error before its isolated signal is ≥1.5× cohort separation.

## Non-Goals

- Do not make calibration scripts a runtime dependency of Lean Gate.
- Do not use Slop Scan's published `6.9x` blended score as a required target on our corpus. Different corpus, different repo selection, different baseline contamination.
- Do not port detectors before measuring isolated signal on the corpus first.
- Do not chase whole-repo cohort separation magnitude at PR-time gate. PR-time and whole-repo are different scopes; the first measures intent on a diff, the second measures accumulated state.
- Do not treat raw-count cohort comparisons as evidence of detector quality. Codebase size dominates raw counts (our 0.36× explicit-AI vs mature-OSS in the slop-scan-benchmark experiment is a size artifact, not a calibration signal).
- Do not run the per-PR head-to-head on the language subset slop-scan can't handle (Python/Go/Rust/C++) — the comparison is meaningless when only one tool produces output.

## Cross-references

- **Runtime detector plan**: `LEAN_GATE_IMPROVEMENT_PLAN.md` (this repo).
- **Step Zero experiments**: calibration repo PR #2, `experiment/slopscan-comparison` branch.
- **Calibration handover docs**: `HANDOVER.md`, `MAP.md`, `IMPROVEMENT_PLAN.md` in the calibration repo. The improvement plan there is the master pickup list; this file is the slop-scan-comparison sub-plan within it.
