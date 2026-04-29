# Slop Scan Calibration Plan

## Purpose

This plan covers calibration methodology only. Runtime Lean Gate behavior belongs in `SECURITY_ASSUMPTION_IMPROVEMENT_PLAN.md`.

Slop Scan's benchmark suggests our flat pre/post results may be a measurement problem, not just a detector problem. It scans whole repos at fixed SHAs and normalizes by file, KLOC, and function. Lean Gate calibration currently emphasizes PR-time findings, which answers a different question.

## Required Calibration Work

1. Step Zero comparison

   Run Slop Scan against the calibration corpus's TS/JS repos at fixed SHAs and place its blended score beside Lean Gate's current PR-time rates. This should happen before porting any Slop Scan-inspired detector.

2. Separate measurement modes

   Keep PR-time measurement for "what would the gate catch in review." Add whole-repo-at-SHA measurement for "is this codebase already slop-heavy." Do not use one mode to justify policy claims for the other.

3. Pin the mature baseline

   Cohort comparisons need a pre-2025 mature-OSS baseline, or the `pre_ai` label remains contaminated by recent AI-assisted PRs. Recent mature repos can stay as a separate operational cohort, but they should not be used as the clean historical comparator.

4. Add normalized outputs

   Calibration tables should report findings/PR, findings/KLOC, findings/function, and whole-repo-at-SHA scores separately. Rule-family totals should distinguish added, resolved, worsened, and improved findings where that data exists.

5. Explain flat signals

   The TS/JS Slop Scan comparison should explain whether Lean Gate's flat cohort signal is detector weakness, PR-only measurement, baseline contamination, or corpus choice.

## Non-Goals

- Do not make calibration scripts a runtime dependency of Lean Gate.
- Do not use Slop Scan's published `6.9x` blended score as a required target on a different corpus.
- Do not port detectors before the Step Zero comparison shows what is missing.
