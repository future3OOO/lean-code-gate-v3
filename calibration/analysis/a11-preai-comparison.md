# A11: Pre-AI / mature codebase vs AI-era 8-repo set

## What was measured

Calibrated gate (with PR-D + PR-E bug fixes) run against 25 code-heavy merged PRs from 4 mature repos:

| Repo | PRs | merged_at range | Why pre-AI / mature |
|---|---|---|---|
| cpython | 5 | 2026-04-26 to 2026-04-27 | Born 1991, reference Python implementation, rigorous PEP review |
| numpy | 5 | 2026-04-14 to 2026-04-23 | Born 2006, foundational scientific Python |
| svelte | 10 | 2026-02-12 to 2026-04-15 | Born 2016 (pre-Copilot core), TS/JS compiler |
| vue3 | 5 | 2026-04-21 to 2026-04-27 | Born 2020 (~3 years pre-Copilot), TS framework |

PR selection: filtered through `list_merged_prs.sh` for ≥1 production source file and ≥50 added source lines. All 25 PRs are real code changes (bug fixes, perf optimizations, refactors).

## Results

| Set | n | Total errors | avg errs/PR | Total warnings | Total reuse-error | PRs that errored |
|---|---|---|---|---|---|---|
| **Pre-AI / mature (this batch)** | 25 | 9 | **0.36** | 2 | 1 | 7 (28%) |
| **AI-era 8-repo, code-only** | 68 | 38 | **0.56** | (n/a) | (n/a) | 26 (38%) |
| Δ per-PR rate | | | **−35%** | | | **−10pp** |

The pre-AI / mature codebase set fires **35% fewer gate errors per PR** than the AI-era set. PR-level FP rate is also 10 percentage points lower (28% vs 38%).

## Critical methodological caveat: this is NOT a temporal split

**All measured PRs are 2026.** The "pre-AI" label refers to **codebase origin** (these repos predate widespread AI-assisted coding), not to **PR authorship era**. PRs in cpython today may themselves be AI-assisted. So this comparison shows:

- **What it measures:** mature, rigorous-review codebases (cpython/numpy/svelte/vue3) vs the original 8-repo set (django/fastapi/pydantic/typescript/nextjs/sentry/aws-sdk-js/grpc).
- **What it does NOT measure:** whether AI-authored code accumulates more slop than pre-AI human-only code over time. The user's hypothesis about "AI-era code = more slop" is plausible but cannot be tested without explicitly fetching pre-2023 PRs.

The 35% reduction in pre-AI/mature data is therefore a **codebase-quality + review-culture effect**, not an isolated AI-era effect.

## What's needed for a real pre-AI vs post-AI split

Same repos, two cohorts:
- **Cohort A (pre-AI era PRs):** merged_at < 2022-06-01 (before Copilot GA).
- **Cohort B (post-AI era PRs):** merged_at >= 2024-01-01 (well into widespread agent-coding).

If Cohort A produces fewer gate errors per LOC than Cohort B *in the same repo*, that isolates the era effect. Tracked as A12 follow-up.

## Side findings (worth noting)

- **0 reuse-error-tier hits across cpython/numpy/vue3 (24 PRs).** Only 1 in svelte. This is consistent with PR-D's gate-bug-2 fix landing — under the bug, R-2/R-3 didn't propagate to `high_confidence_reuse`, so similar pairs would have fired. With the fix, very few make it through.
- **2 warnings total across 25 PRs** — mature codebases ship clean. Compare to aws-sdk-js's 91 warnings on 50-commit window: a mature human-reviewed codebase produces dramatically less warning-tier noise.
- **0 errors on numpy and vue3.** Both repos shipped 5 PRs with zero gate findings. cpython and svelte each shipped a few escape-tier hits (TODO/`# type: ignore` patterns) — those are the gate's most reliable signal.

## Caveats stacked

- n=25 (cpython/numpy/svelte/vue3) vs n=68 (8 AI-era repos). Sample size still modest.
- The pre-AI cohort is heavily Python (cpython + numpy = 10 PRs) and TS (svelte + vue3 = 15 PRs). Other languages (Rust, Go) are missing because tokio/cargo/prometheus didn't return PRs from the rate-limited filter pass. A retry batch (tracked) will add them.
- Comparison is across repos with very different review cultures, languages, and characters of contribution. The 35% gap is plausibly a mature-codebase signal as much as a "less slop" signal.

## Next cycle

- **Backfill remaining 9 pre-AI repos** (airflow, tokio, cargo, prometheus, jquery, react, lodash, eslint, vite, ts-eslint) once rate-limit recovers, to broaden the comparison.
- **A12 — temporal split:** fetch PRs from same repos at pre-2022 vs post-2024 dates. Run gate. Isolate the era effect cleanly.
- **A13 — per-LOC normalization:** report errors per added source line, not per PR. Different repos have very different PR sizes.
