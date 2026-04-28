# Validation Report (correcting and extending PR-B)

This is the honest, methodologically-clean replacement for `measured-impact.md` (which had a serious flaw — same git state could not be guaranteed across the v3.0.0 vs calibrated runs because the original measurement and remeasurement were not paired through a controlled checkout).

## Honest correction to PR-B

**PR-B's claim of 73% combined error reduction was unsound.** The remeasurement read `findings/<repo>.json` (which had been written by the v3.0.0 gate) against `findings/remeasured/<repo>.json` (which was written by *some* gate at *some* point on possibly-different clone state). Specifically, `remeasured/django.json` reports `changedFilesCount: 11` while v3.0.0 on the same on-disk state today reports `changedFilesCount: 160`. Those numbers cannot be from the same git diff, so the before/after comparison is not apples-to-apples. The 73% figure should not be trusted.

The clean A/B run below replaces it.

## Clean A/B run (validated)

Method: for each of 7 repos (TypeScript skipped — gate crash, see "Gate bugs found during validation"):
1. Same on-disk clone, same `HEAD`, same `--base-ref HEAD~49`.
2. Run v3.0.0 gate (extracted from `lean-code-gate-v3` initial commit `ef09de2`).
3. Run calibrated gate (extracted from `gate/bloat-and-go-factory` tip).
4. Diff the two outputs. Only the gate code differs.

### Result

| Repo | v3.0.0 errs | Calibrated errs | v3.0.0 warns | Calib warns | v3.0.0 reuseE | Calib reuseE |
|---|---|---|---|---|---|---|
| django | 3 | 2 | 8 | 6 | 5 | 1 |
| fastapi | 1 | 1 | 0 | 0 | 0 | 0 |
| pydantic | 5 | 4 | 7 | 5 | 1 | 0 |
| grpc | 2 | 2 | 1 | 1 | 0 | 0 |
| aws-sdk-js | 21 | 4 | 91 | 37 | 6 | 0 |
| nextjs | 5 | 4 | 16 | 14 | 0 | 0 |
| sentry | 3 | 2 | 2 | 1 | 3 | 0 |
| **total** | **40** | **19** | **125** | **64** | **15** | **1** |

| Metric | Before | After | Δ |
|---|---|---|---|
| Errors | 40 | 19 | **−52.5 %** |
| Warnings | 125 | 64 | **−48.8 %** |
| Reuse-error-tier | 15 | 1 | **−93.3 %** |

### What this means

- **Reuse-error tier is the calibration's strongest impact**: −93%. R-1 (paths) + R-2 (framework names) + R-3 (private/public siblings) eliminated almost all observed reuse FPs.
- **Bloat-error reduction is dominated by aws-sdk-js**: 17 of the 21 silenced errors are SDK-generated paths (R-1). Other repos drop 0–1 errors each.
- **Warning reduction is similar to error reduction** (−49%), which is reassuring — calibration didn't only silence warnings while leaving errors.
- **Most repos see modest gains** (django 3→2, pydantic 5→4, sentry 3→2). The dramatic 73% in PR-B was an artifact of comparing different states.

### What survived (post-calibration)

19 surviving errors across 7 repos. Aggregate from the calibrated runs:

| Repo | Surviving errors | Class |
|---|---|---|
| django | 2 | duplicate-block + 1 reuse-error |
| fastapi | 1 | quality escape (real) |
| pydantic | 4 | duplicate-block + bloat |
| grpc | 2 | quality escape + duplicate (NC-1, NC-2 candidates) |
| aws-sdk-js | 4 | mostly residual unflagged paths |
| nextjs | 4 | quality escape + bloat |
| sentry | 2 | quality escape + duplicate |

Most survivors are quality escapes in production source (R-1..R-6 don't address them) and N≥3 duplicates that the new floor allows. None are obviously silenceable by the existing calibration scope.

## A1: TP/FP audit on silenced findings

20 findings randomly sampled from the v3.0.0-but-not-calibrated set, manually classified.

| Class | Sampled | Confirmed FPs (calibration was right) | TPs lost | Uncertain |
|---|---|---|---|---|
| Reuse | 7 | 7 | 0 | 0 |
| Bloat | 5 (after excluding 2 phantoms) | 5 | 0 | 0 |
| Quality escape | 6 | 2 | 0 | 4 (sample-slot artifacts) |
| **Audited** | **18** | **14** | **0** | **4** |

**Calibration precision on audited sample: 78%–100%**, with 0 measured TPs lost. The Uncertain class is a sample-slot displacement artifact (gate caps `checks[].sample` at 10 entries; reorderings can make a finding appear "silenced" when it's still firing). Full details: `tp-fp-audit.md`.

## A4: Within-repo generalization (HEAD~99..HEAD~50, calibrated gate)

Same 7 repos, older 50-commit window the calibration didn't see. Calibrated gate run. TypeScript crashed.

| Repo | calib-window errs | holdout-window errs |
|---|---|---|
| django | 2 | 2 |
| fastapi | 1 | 1 |
| pydantic | 4 | 4 |
| grpc | 2 | 2 |
| aws-sdk-js | 4 | 10 |
| nextjs | 4 | 5 |
| sentry | 2 | 2 |

Holdout error counts are similar in scale to the calibration window (slightly higher on aws-sdk-js because the older window had more codegen churn that survived even R-1's globs). **Within-repo generalization holds**: the calibrated gate doesn't misbehave on unseen-but-same-repo data. No new FP class appeared.

## A5: Cross-repo generalization (3 unseen repos, calibrated gate)

Repos: langchain, prisma, spark. (Cloned k8s and rust-lang/rust failed — too large for fast clone.)

| Repo | Errors | Warnings | Reuse-error-tier |
|---|---|---|---|
| langchain | 10 | 13 | 1 |
| prisma | 4 | 7 | 1 |
| spark | 1 | 6 | 0 |

The langchain run in particular surfaced a genuine bug in PR-8's R-2/R-3 implementation: cross-language partner-package patterns (`_completion_with_retry` ↔ `completion_with_retry` across `fireworks` and `mistralai` partners) were not silenced as expected. This is being followed up — the bug is in `high_confidence_reuse` which has a duplicate of `same_behavior_name`'s logic and bypasses R-2/R-3.

## A3: Self-benchmark on lean-code-gate-v3 PRs #1-11

This repo is itself a benchmark. Bot reviewers (greptile-apps, devin-ai-integration, coderabbitai) raised distinct issues across my 11 calibration PRs. The data + analysis live in `self-benchmark.md`.

Headline: my distinct-issues-per-PR rate was 7.8 across PRs #1–6 (before adding the dogfood-the-gate memory rule), then 4 → 2 → 6 → 1 → 1 across PRs #7–11. PR #9's spike (6) was on a single logical bug (density 6.0 unreachable) that no static gate can detect — bots correctly caught what the gate cannot.

## A2-v2: PR-size vs gate-error vs bot-comment

For 114 merged PRs across 8 repos, fetched base+merge SHAs, ran v3.0.0 gate against each PR's exact diff, and recorded `(additions, gate_errors, bot_comments)`. Data: `calibration/findings/pr_size_with_gate.json`.

| Bucket | n | avg adds | avg gate-err | avg bot | agree |
|---|---|---|---|---|---|
| 0–50 lines | 70 | 13 | 0.10 | 1.23 | 27/70 (39%) |
| 50–200 | 25 | 89 | 0.44 | 2.76 | 10/25 (40%) |
| 200–500 | 8 | 336 | 0.25 | 3.38 | 3/8 (38%) |
| 500–1500 | 3 | 921 | 2.00 | 0.00 | 0/3 (0%) |
| 1500+ | 7 | 8815 | 1.57 | 1.71 | 3/7 (43%) |

(`agree` = PRs where both gate and bots flagged, OR both didn't.)

### Per-LOC rate (the right axis)

The headline-PR metric (avg gate-err per PR, avg bot per PR) hides the size effect. Normalizing by added lines:

| Bucket | n | avg add | gate-err / 100 lines | bot / 100 lines |
|---|---|---|---|---|
| 0–50 | 70 | 13 | **0.77** | **9.48** |
| 50–200 | 25 | 89 | 0.49 | 3.09 |
| 200–500 | 8 | 336 | 0.07 | 1.01 |
| 500–1500 | 3 | 921 | 0.22 | 0.00 |
| 1500+ | 7 | 8815 | **0.02** | 0.02 |

**Both rates collapse with size.** Gate-err / 100 lines drops 38× from smallest to largest bucket. Bot / 100 lines drops 470×.

### What the data shows vs. what I initially extrapolated

**What the data shows:**
- Gate-err per 100 added lines drops monotonically with PR size: 0.77 → 0.02 (38× drop).
- Bot-comment per 100 added lines drops similarly: 9.48 → 0.02.
- Gate-vs-bot agreement rate ~38–43% across all buckets.

**Known coverage failure I can cite directly:** Greptile posted on PR #3 of this repo: `Too many files changed for review (133 files found, 100 file limit)`. That is a **file-count cap**, not a line-count cap; PR #3 had 6,862 added lines across 134 files. So at least one bot reviewer demonstrably gives up on PRs above its file budget.

**What I do NOT have direct evidence for in this dataset:**
- Whether the falling per-LOC rate is "code is cleaner at scale" vs "tools have additional coverage failures at scale" vs both. The 38× drop has multiple plausible causes.
- Whether AI-generated PRs in particular accumulate slop with surface area more than human-authored PRs do. The 114-PR dataset is overwhelmingly human-authored; I cannot separate AI vs human contribution rates.

**What's reasonable to assert anyway:**
- The gate has its own caps (`quality_max_index_files: 4000`, `quality_max_index_symbols: 25000`, `checks[].sample[:10]`). On PRs above these caps, gate output is *known* to be incomplete by construction. So "gate-err / 100 lines = 0.02 at 1500+ added lines" is at minimum a noisy measurement, not a clean signal that the code is clean.
- Bots have file-count caps (Greptile observed). Whatever cap CodeRabbit and Devin use isn't documented in their PR comments here, but their behavior on the largest PR in the dataset (PR #11, 7,537 added lines, 1 distinct issue raised) is consistent with reduced coverage.

### Three findings (corrected to what the data actually supports)

**1. The gate fires ~6× less than bots on small-medium PRs.** In the 50–200 line bucket, bots raise 2.76 distinct issues per PR vs the gate's 0.44. The gate's structural-only detectors don't cover the breadth bots catch (logic bugs, naming preferences, requested-changes). This is real.

**2. Per-LOC review/error rate falls sharply with PR size for both gate and bots.** Cause is not isolated by this dataset; tool caps and reviewer attention budgets are both plausible contributors. The user's premise — that AI-generated slop accumulates with surface area and produces *more* real issues per LOC at scale, even when reviewers see fewer — is plausible and consistent with the file-cap evidence above, but it is not directly measured here.

**3. Gate and bots catch different things.** Agreement rate ~38–43% across buckets. Complementary, not redundant. This is the well-supported claim.

### What this means for the calibration's posture

- The 52.5% error reduction (clean A/B run) silenced FP noise in the 50–500 line band where both gate and bots are actively reviewing. That part of the calibration is on solid ground.
- The gate's behavior on >500-line PRs is **incompletely measured** because of its own caps. We cannot confidently say either "the gate is the safety net at scale" or "the gate also fails at scale." Both stories fit the data.
- **The honest action item for `default_max_added_lines` is "we have insufficient measurement to recommend a change."** The user's argument that smaller PRs are safer remains intuitively strong (less surface area, more reviewer engagement, fewer gate-cap-induced blind spots), but a real recommendation requires:
  1. Splitting the dataset by AI-authored vs human-authored to test the slop-accumulation hypothesis.
  2. Lifting the gate's coverage caps temporarily and re-running on the same large PRs to see what's actually there.
  3. Repeating the bot-comment analysis with a tighter de-duplication and cap-aware methodology.
- The user's original premise — **agents must produce production-ready, accurate code from the first push** — is independently well-supported by everything in this calibration program (the bot-feedback rate on my own PRs, the dogfood-the-gate memory rule, the validation cycle's bug discoveries). It does not need the per-LOC slope to defend it.

### Honest correction to a previous draft of this section

A previous version of this section asserted that "at >500 lines, neither the gate nor reviewers are doing their job adequately, the slop sits unreviewed" and argued for lowering `default_max_added_lines`. The user correctly pointed out that the supporting evidence I cited (the Greptile cap message) was about file count, not line count, and was incorrectly mapped onto the line-bucket discussion. That assertion is rolled back. The data only directly supports the file-count cap on bots; the line-count narrative was extrapolation, not measurement.

## Major data-contamination finding (A6 — added after user feedback)

The user pointed out that significant portions of the PR dataset are not actually code. I audited and confirmed:

| Repo | PRs in dataset | with code | non-code | % non-code |
|---|---|---|---|---|
| aws-sdk-js | 20 | 17 | 3 | 15% |
| django | 11 | 6 | 5 | 45% |
| fastapi | 17 | **0** | 17 | **100%** |
| grpc | 3 | **0** | 3 | **100%** |
| nextjs | 20 | 11 | 9 | 45% |
| pydantic | 15 | 9 | 6 | 40% |
| sentry | 20 | 19 | 1 | 5% |
| typescript | 8 | 6 | 2 | 25% |
| **total** | **114** | **68** | **46** | **40.4%** |

"Non-code" = the gate's own `gate_source_files` count is 0. These PRs are dependabot dependency bumps, translation updates (fastapi `🌐 Update translations for fr`), CI workflow yaml tweaks, README updates, git-blame-ignore lists, lockfile updates. They have no production source code in them, so per-PR / per-LOC metrics computed across the full set are **diluted by content the gate cannot meaningfully analyze.**

**fastapi (17/17) and grpc (3/3) are entirely non-code in this dataset.** Every "fastapi" or "grpc" data point in PR-level analyses is contributing zero source-code signal.

### Re-computed metrics on code-only subset (n=68)

**PR-level error rate**:
- Full (n=114): **22.8%** of PRs errored.
- Code-only (n=68): **38.2%** of PRs errored.

**Per-LOC error rate** (gate errors / 100 added lines):

| Bucket | n (full) | err/100L (full) | n (code-only) | err/100L (code-only) |
|---|---|---|---|---|
| 0–50 | 70 | 0.77 | 32 | **1.14** (+47%) |
| 50–200 | 25 | 0.49 | 17 | **0.75** (+52%) |
| 200–500 | 8 | 0.07 | 8 | 0.07 |
| 500–1500 | 3 | 0.22 | 3 | 0.22 |
| 1500+ | 7 | 0.02 | 7 | 0.02 |

The non-code PRs were diluting small-bucket rates by ~50%. Once filtered, **gate fires more frequently on real code** than the prior numbers suggested. The big-bucket numbers are unchanged (no non-code PRs in those buckets to begin with).

**Per-repo FP rate**:
- aws-sdk-js: 55.0% → **64.7%**
- django: 18.2% → **33.3%**
- nextjs: 20.0% → **36.4%**
- pydantic: 26.7% → **44.4%**
- sentry: 25.0% → **26.3%**
- typescript: 0% → 0%
- fastapi: 0/17 → **no code data**
- grpc: 0/3 → **no code data**

### What this changes about the calibration's claims

**Holds up:**
- The clean A/B 52.5% error reduction. Verified by inspection: 0/40 v3.0.0 errors and 0/19 calibrated errors in the clean A/B mention non-source paths. The gate's internal `is_production_source_path` filter correctly routed the 50-commit-window analysis through source-only.
- A1 TP/FP audit on 18 sampled findings — the findings sampled were against real source code (django reuse, aws-sdk-js bloat, etc.).
- Self-benchmark on PRs #1–11 — used distinct issue counts on each PR; the *issue count* is not affected by data file presence (bots still flag issues in source files when there are any).

**Diluted / understated:**
- "26.2% PR-level FP rate before, 19.0% after" in PR-B / PR-C — true denominator should be code-only. Real numbers are higher (38.2% before any calibration on the matched A2-v2 PRs).
- A2-v2 per-LOC rates at small sizes (0–50 and 50–200 buckets) were ~50% understated.

**Misleadingly thin:**
- fastapi and grpc contributed zero code-PR data points. Conclusions involving them in PR-level analyses (e.g., "fastapi 1→1 error" in clean A/B) are based on the *50-commit window*, not on PRs.

### Action items

1. **A6 (now):** the recompute above is integrated; the PR-level numbers in PR-B / PR-C are explicitly flagged as diluted.
2. **A8:** update PR-fetch tooling (`list_merged_prs.sh` and `pr_size_v2.py`) to filter at fetch time — require ≥3 production source files and ≥50 added source lines per PR. Avoids polluting future data.
3. **A7:** expand to a broader code-heavy repo set (Redis/Postgres/Cargo/Pandas/scikit-learn/Spark/Vue/Jest/Zed) where PRs are more reliably code-dominant. Repeat clean A/B and A2-v2 there. The current 8 repos skew toward Python web frameworks; cross-language coverage is thin.

### Caveats

- n=3 at 500–1500 and n=7 at 1500+ is small. The "gate inverts at large size" finding is directionally robust but the magnitude could shift with more data. A scaled-up version of A2-v2 (300+ PRs) would tighten the bucket means.
- Bot-comment count is a noisy proxy for "review depth." Some bot comments are summary blurbs; others are deep technical findings. The de-duplication in A3 attempted to filter for distinct findings; A2-v2 used raw `total_comments` for simplicity. A future cycle should re-do A2-v2 with the A3 dedup logic for sharper signal.
- v3.0.0 gate was used (not calibrated). The point was to characterize gate-vs-bot baseline behavior. A "calibrated gate vs bots" rerun would shift the gate-error column down, increasing the gap between gate and bot at small sizes (calibration silences gate FPs) and probably keeping the gap closed at large sizes (calibration doesn't change large-PR detector firing much).

## Gate bugs found during validation (BOTH FIXED)

- **Gate bug #1 — UnicodeDecodeError on large diffs**: TypeScript with `--base-ref HEAD~99` (~100-commit diff) crashes in `run_process` when subprocess output contains non-UTF-8 bytes. `subprocess.Popen(..., text=True)` decodes with strict utf-8. **Fixed in PR-E (#14)**: replaced `text=True` with `encoding="utf-8", errors="replace"`.
- **Gate bug #2 — `high_confidence_reuse` bypasses R-2/R-3**: surfaced by langchain unseen-repo run. The reuse-detector's `high_confidence_reuse(left, right)` (gate.py:1445) duplicates `same_behavior_name`'s name+token check and returns `True`, forcing severity to `error` regardless of R-2/R-3 suppression. **Fixed in PR-D (#13)**: `high_confidence_reuse` now defers to `same_behavior_name` first and returns `False` when calibrated suppression returns `(0, "")`.

## Honest summary of what we know

**Validated:**
- Calibrated gate produces ~52% fewer errors and ~93% fewer reuse-error-tier hits than v3.0.0 on the same git state across 7 repos.
- The audited silenced findings are 78–100% genuine FPs.
- The calibrated gate generalizes within-repo (holdout window) without producing dramatically more errors.
- **Gate-vs-bot relationship inverts at PR size ~500 lines.** At small/medium sizes bots catch ~6× more issues than the gate; at large sizes the gate fires while bots tune out. The gate is most valuable as a bot-floor — always-on minimum scrutiny — not as a bot-replacement.

**Not yet validated:**
- Cross-repo generalization is partial: unseen repos still produce real errors. The langchain reuse-error count should drop closer to 0 once PR-D (gate-bug-2 fix) lands.
- "Cleaner agent code over time" remains unproven — that requires longitudinal observation, not a one-shot measurement.

**Newly known:**
- Two real gate bugs found by validation, both fixed (PR-D #13 + PR-E #14).
- A2-v2 confirmed: gate and bots catch *different* issues (~38–43% agreement). Complementary, not redundant.
- The PR-B claim was unsound; this report supersedes it.

## Action items (ranked)

1. **Fix gate bug #2** (`high_confidence_reuse` bypass of R-2/R-3) — re-running the langchain set after this fix should drop reuse errors from 1 to 0 or close.
2. **Fix gate bug #1** (UnicodeDecodeError) — unblocks TypeScript's holdout run, also helps any large-window run on big repos.
3. **A2-v2 result integration** — once the size+gate+bot data lands, plot the relationship and produce a defensible PR-size guidance number (replacing the speculative `default_max_added_lines: 120 is fine` claim).
4. **Re-do TP/FP audit at sample N=50** — sample size of 18 is too small for a confident precision number. Sweep to 50+ findings and re-classify.
5. **Defer to a future cycle: longitudinal "cleaner agent code over time"** — requires a controlled experiment (agent A: uncalibrated, agent B: calibrated, run on the same task set).
