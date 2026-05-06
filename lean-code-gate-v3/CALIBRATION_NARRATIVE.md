# Calibration narrative

How the lean-code-gate v3 policy in this repo was calibrated against real OSS PRs.

This doc covers what was measured, what changed in `policy.json`, and what the corpus said about each detector. It is the human-readable companion to the data living in [`future3OOO/lean-code-gate-calibration`](https://github.com/future3OOO/lean-code-gate-calibration). Slop-scan-related work is out of scope here; see `SLOP_SCAN_CALIBRATION_PLAN.md` for that thread.

## The harness

The calibration harness is a separate repo: `future3OOO/lean-code-gate-calibration`. It pins this gate via submodule, runs the gate against curated PRs from real OSS, and stores per-PR JSON output for later analysis.

Key artifacts:

- `pr_lists.json` — the curated PR set. Filter: ≥1 production source file changed, ≥50 added source-line count, non-bot author, no docs/translations/changelog title patterns.
- `findings/{preai,prs,own}/<repo>/pr-<N>.json` — per-PR gate output, committed for public repos, gitignored for private ones.
- `analysis/COHORT_TABLE.{md,csv}` — canonical aggregate. Per-repo, per-cohort, per-language, per-(language × cohort).
- `aggregate_by_language.py`, `count_findings.py` — aggregators that read every committed JSON and emit the tables.
- `rerun_all.sh` / `rerun_parallel.sh` — drive the gate against the curated PRs, one bg process per repo.

## Calibration loop

Each detector calibration followed the same pattern:

1. **Measure** — run the gate against the corpus, record findings per detector per repo per PR.
2. **Triage** — sample high-finding PRs, classify each as TP, FP, or "patternable FP" (a class of FPs sharing a path/marker/syntax shape).
3. **Propose** — `proposed-policy/` and `proposed-tests/` in the calibration repo. Policy diff + a pinned-behavior fixture before any gate-side change.
4. **PR on this repo** — implement the policy field, port the fixture, get bot review.
5. **Re-measure** — submodule bump in calibration → rerun → diff the cohort table against the prior run. Calibration only counts as "settled" once the re-run shows the proposed change behaved on real PRs.

The `proposed-policy/` → fixture → gate PR → re-run sequence is what the harness exists for. Any future detector should follow the same loop.

## What landed in policy.json

Every active field in `lean-code-gate-v3/.agent/lean/policy.json` came out of the corpus. Each row below cites the calibration phase that motivated it:

| Field | Default | Phase | Evidence |
|---|---|---|---|
| `excluded_path_globs` | 23 patterns | PR-5 (R-1) | aws-sdk-js fired 91 warnings on `clients/*/src/{commands,models,...}/**` smithy codegen; pydantic on `self_schema.py`; cpython on `**/python_version.py`. Glob list lifted from observed FP paths. |
| `framework_override_names` | 53 names | PR-6 (R-2/R-3) | django reuse-errors clustered on `validate`, `clean`, `save`, `get_queryset`. React/Vue clustered on `componentDidMount`, `render`, `ngOnInit`. Python dunders fired in every cohort. List built from triaged FP names. |
| `reuse_suppress_private_public_siblings` | true | PR-6 (R-3) | django and similar repos legitimately ship `_foo`/`foo` and `foo`/`Foo` pairs as private/public siblings; reuse-error fired on every one. Suppress when both halves exist in the same module. |
| `max_design_markers` / `max_design_marker_density_per_100_lines` | 4 / 3.0 | PR-7 (R-7) | Raw-count threshold catches larger files with repeated markers; density catches small files where 1–2 markers are dense. Both remain active in policy. |
| `bloat_new_file_warn_lines` / `bloat_new_file_error_lines` | 500 / 800 | PR-8 (R-4) | Distribution of new-file sizes across the 42 baseline PRs put the 90th percentile of mature-OSS new files at ~500 lines. Errors set above the 99th. |
| `bloat_total_added_warn_lines` / `bloat_total_added_error_lines` | 500 / 1000 | PR-8 (R-4) | Same distribution analysis on per-PR total added lines. |
| `bloat_add_delete_warn_ratio` / `bloat_add_delete_error_ratio` | 4 / 6 | PR-8 (R-4) | Add/delete ratio above 4:1 correlated with churn-only PRs (no real refactor). |
| `bloat_large_file_lines` / `bloat_large_file_growth_lines` | 1500 / 80 | PR-8 (R-4) | Large-file-grew threshold tuned to fire on AI-coded incremental bloat without flagging routine large-file maintenance. |
| `reuse_min_duplicate_count` | 3 | PR-8 (R-3) | Two-instance dup blocks were ~70% FP on the baseline; three-instance was ~10%. |
| `quality_max_index_files` / `quality_max_index_file_bytes` / `quality_max_index_symbols` | 4000 / 500000 / 25000 | PR-8 (perf) | Indexer caps to keep big repos (typescript, aws-sdk-js) from OOM. |
| `reuse_error_score` / `reuse_warning_score` | 90 / 45 | PR-8 (R-2) | Reuse-score histogram on the corpus showed clusters at 57, 62, ≥95. Threshold 45 captures the lower cluster as warnings; 90 promotes the high-confidence cluster to errors. |

## Corpus expansion

The first calibration loop (PRs #5–#10 on this repo) was driven by an 8-repo × 5-PR sample. That set is small enough that single PRs can move cohort headlines. Phase 2 expanded the corpus:

| Phase | Corpus | What it tested |
|---|---|---|
| Phase 1 | 8 mature OSS, 5 PRs each (~42 PRs) | Initial detector calibration (PRs #5–10). |
| A11 | + 14 mature OSS, 5 PRs each (~75 PRs) | Cross-repo generalization. Confirmed PR-8 thresholds held outside the original 8. |
| A14 | + openclaw, 15 PRs | First post-AI cohort. |
| A20 | + property-partner-ops, valua, 76 PRs | Private-own (heavily AI-assisted) baseline. |
| A21 | + gitnexus, google-workspace-mcp, 60 PRs | Wider post-AI public cohort. |
| A22 | every repo expanded to 30+ PRs (824 total) | Address sample noise; the original 5-PR samples missed several high-finding aws-sdk-js PRs that flipped per-cohort medians. |

Each expansion was paired with a re-aggregation in `analysis/COHORT_TABLE.md`. The current canonical run at the time of writing is gate commit `2ce81e6` (post-PR21 main): 824 selected, 821 parsed, 3 timeouts, 24,803 reconstructed findings.

The cohort labels rest on what the corpus actually contains, not on what we initially named them. `pre_ai` was renamed to `recent_mature_oss` after the data showed 67% of its sampled PRs are from 2026, not historical. `recent_oss` is mature 2025+ OSS, not "AI-coded." The only cohorts where authorship method genuinely differs are `post_ai_public` (3 repos, self-declared AI-built) and `private_own` (2 repos, user's own AI-assisted work).

## What the corpus said about each detector

A19 ran a parity sensitivity sweep — varying each detector's threshold across the corpus to see which detectors were doing the cohort-separating work and which were dormant. Conclusions, in plain terms:

- **R-1 (quality escape)** drives most of the cohort separation. `excluded_path_globs` was the single highest-impact policy change in the calibration. R-1 is what fires on AI-coded `as any`/suppression-marker patterns, and it is what aws-sdk-js was triggering before the codegen-paths exclusion landed.
- **R-2 (reuse) + R-3 (duplicate-block)** are concentrated in a few repos. Without `framework_override_names`, R-2 fires hard on Django/React; with it, R-2 contributes a steady but small share of total findings. R-3's three-instance threshold is at the right place — sweeping below it doubles FPs without surfacing real duplication.
- **R-4 (bloat)** is the only detector whose thresholds need active per-repo character. Default values came from the 42-PR distribution; the expanded corpus didn't move them materially.
- **R-5 (merge-conflict)** and **R-6 (temp-artifact)** essentially never fire on real PRs. 48 mc + 3 tmp findings across 824 runs. They are guard-rails, not calibration signals; cohort tables expose them in their own columns now to make that visible rather than rolling them silently into totals.

The honest read after A19 + A22: **the gate's R-1..R-6 are at the right thresholds for the patterns they target.** Threshold rebalancing won't change the cohort numbers because the detectors operate in genuinely sparse regions of the production-PR signal space. Wider cohort separation between AI-coded and mature-OSS code requires *new* detectors (placeholder comments, generic envelopes, error swallowing — see `SECURITY_ASSUMPTION_IMPROVEMENT_PLAN.md`), not new thresholds on the existing ones.

## What's still open

- **A12 — within-repo temporal split.** Pre-2023 PRs from django, react, lodash, fastapi against the same repos' 2026 PRs. The only experiment that would produce a real pre/post-AI-era contrast on the same code. Scaffolded but never run.
- **`--whole-repo` flag on the gate.** The calibration pipeline currently uses a `sed`-patched gate variant for whole-repo scoring. Promoting that to a real flag is tracked in `SLOP_SCAN_CALIBRATION_PLAN.md`.
- **A15 — hook-time integration measurement.** All current data is PR-time. Whether the gate is useful when wired into a `PostToolUse` hook on real agent edits is unmeasured.

## Cross-references

- Calibration repo: [`future3OOO/lean-code-gate-calibration`](https://github.com/future3OOO/lean-code-gate-calibration)
- Canonical cohort table: `analysis/COHORT_TABLE.md` in that repo
- Phase-1 narrative: `analysis/REPORT.md`
- Per-detector autoresearch loop: `analysis/measured-impact.md`
- Cross-repo expansion summary: `analysis/A22_EXPANDED_COHORTS.md`
- Detector parity sweep: `analysis/PARITY_ANALYSIS.md`
- Calibration handover: `HANDOVER.md`, `MAP.md`, `IMPROVEMENT_PLAN.md`
- Runtime detector follow-ups: `SECURITY_ASSUMPTION_IMPROVEMENT_PLAN.md` (this repo)
- Calibration methodology follow-ups: `SLOP_SCAN_CALIBRATION_PLAN.md` (this repo)
