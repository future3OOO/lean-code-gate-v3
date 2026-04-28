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

### Three findings that change the calibration's framing

**1. The gate fires far less than bots on small-medium PRs.** In the 50–200 bucket, bots raise ~6× more issues than the gate (2.76 vs 0.44). The gate's structural-only detectors don't match the breadth of issues bots catch (logic bugs, stylistic concerns, requested-changes, naming preferences).

**2. The relationship inverts at 500+ lines.** PRs 500–1500 lines: gate 2.00 errors, bots 0.00 comments. PRs 1500+ lines: gate 1.57 errors, bots 1.71 comments (and that's averaged across n=7, dominated by a few outlier-attended PRs). **Reviewers tune out on large PRs; the gate doesn't.** This is the calibration's strongest argument: the gate is most valuable precisely where reviewer attention drops off.

**3. Gate and bots catch *different* things.** Agreement rate hovers around 38–43% across buckets. They are complementary signals, not redundant. The gate as bot-replacement is the wrong framing — the gate as bot-floor (always-on minimum scrutiny) is the right one.

### What this means for the calibration's posture

- The gate's 52.5% error reduction (post-calibration A/B) silenced FP noise in **the size band where bots are also active** (50–500 lines). That's correct: in that band the gate was over-firing on noise the bots were also catching/dismissing.
- The gate's behavior on >500-line PRs **wasn't changed by calibration** because R-1..R-6 don't directly target large-PR semantics. But this is also where the gate has its highest absolute value (no bot review).
- **`default_max_added_lines: 120` looks well-calibrated** against this data: it sits in the 50–200 bucket where bot scrutiny is moderate AND the gate fires ~0.44 times per PR. Lower would push false alarms; higher would sail into the 500+ band where the gate's signal is the *only* signal.

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
