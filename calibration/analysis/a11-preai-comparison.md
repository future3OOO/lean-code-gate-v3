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

## Results — first cut (4 repos, n=25)

| Set | n | Total errors | avg errs/PR |
|---|---|---|---|
| **Pre-AI / mature batch 1** | 25 | 9 | **0.36** |
| **AI-era 8-repo, code-only** | 68 | 38 | **0.56** |
| Δ per-PR rate | | | **−35%** |

This cut showed pre-AI / mature codebases firing 35% fewer errors per PR. **It was misleading.** See expanded result below.

## Results — expanded (10 repos, n=55)

After A11 batch 2 added airflow (5), cargo (5), jquery (5), react (5), eslint (5), vite (5):

| Repo | PRs | errors | warnings | reuse-error | avg errs/PR |
|---|---|---|---|---|---|
| airflow | 5 | 20 | 14 | 0 | 4.00 |
| cargo | 5 | 0 | 0 | 0 | 0.00 |
| cpython | 5 | 3 | 1 | 1 | 0.60 |
| eslint | 5 | 2 | 5 | 0 | 0.40 |
| jquery | 5 | 0 | 0 | 0 | 0.00 |
| numpy | 5 | 0 | 1 | 0 | 0.00 |
| react | 5 | 6 | 11 | 3 | 1.20 |
| svelte | 10 | 6 | 0 | 0 | 0.60 |
| vite | 5 | 3 | 2 | 0 | 0.60 |
| vue3 | 5 | 0 | 0 | 0 | 0.00 |
| **TOTAL** | **55** | **40** | **34** | **4** | **0.73** |

**The headline flips with more data.**
- 4-repo cut: 0.36 errs/PR. **Pre-AI looked 35% lower** than AI-era's 0.56.
- 10-repo cut: 0.73 errs/PR. **Pre-AI now 30% HIGHER** than AI-era.

The reversal is driven by airflow (4.0 errs/PR — single repo dominates the average across 55 PRs) and react (1.2 errs/PR). cargo, jquery, numpy, vue3 each shipped 5 PRs with zero gate findings — those are the genuinely-clean repos.

## Per-LOC normalization (the right axis)

avg-errs/PR varies wildly because PR sizes differ across repos. Compute errors per 100 added source lines (gate-source-counted, not raw additions):

| Set | PRs | errors | src lines added | errs / 100 src lines |
|---|---|---|---|---|
| Pre-AI / mature 10-repo | 55 | 40 | 11,245 | **0.356** |
| AI-era 8-repo (code-only, source-line denominator) | 29 | 15 | 5,069 | **0.296** |
| Ratio | | | | **pre-AI 1.20× AI-era (+20%)** |

(Note: AI-era set shrunk from 68 PRs to 29 because the 68 included PRs the gate found no source files in — they had `sourceFilesCount: 0` despite passing the file-extension filter. The 29 are PRs where the gate actually had source files to analyze.)

**With per-LOC normalization on like-for-like data, pre-AI / mature codebases fire ~20% MORE gate errors per source line than the AI-era 8-repo set, not fewer.**

## Critical methodological caveat: this is NOT a temporal split

**All measured PRs are 2026.** The "pre-AI" label refers to **codebase origin** (these repos predate widespread AI-assisted coding), not to **PR authorship era**. PRs in cpython today may themselves be AI-assisted. So this comparison shows:

- **What it measures:** mature, rigorous-review codebases (cpython/numpy/svelte/vue3 etc.) vs the original 8-repo set (django/fastapi/pydantic/typescript/nextjs/sentry/aws-sdk-js/grpc).
- **What it does NOT measure:** whether AI-authored code accumulates more slop than pre-AI human-only code over time. The user's hypothesis about "AI-era code = more slop" is plausible but cannot be tested without explicitly fetching pre-2023 PRs.

The +20% gap (per-LOC) is therefore a **codebase mix + measurement-method effect**, not an isolated AI-era effect.

## What this means for the slop-accumulation hypothesis

The user's premise is that "AI-generated code accumulates slop with surface area; the more lines AI writes, the more issues per LOC." This batch of data **does not support that hypothesis** in either direction:

- Pre-AI / mature codebases are NOT measurably cleaner per-LOC; they are slightly noisier (0.356 vs 0.296 per 100 source lines). 
- The signal is weak (1.2× ratio, n=55 + n=29) and dominated by airflow's 20 errors across 5 PRs.
- The dataset doesn't isolate the era variable.

The hypothesis remains **plausible but untested**. To test it cleanly, A12 needs to fetch PRs from the SAME repo at two distinct dates (pre-2022 and post-2024) and compare. Anything else conflates era with codebase character.

## What this DOES suggest

- **The gate's calibration is tuned to the AI-era 8-repo set** — that's where R-1..R-6 thresholds were derived. Running on a different repo mix (cpython, airflow, react...) produces different fire rates because those codebases have different mixes of `# type: ignore`, TODO comments, and large-file growth that don't cleanly match the calibration's defaults.
- **airflow specifically is a high-fire repo** for this gate. 4.0 errs/PR on an Apache project with rigorous review is an interesting outlier — those errors are likely real signals the calibration's defaults aren't tuned for.

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
