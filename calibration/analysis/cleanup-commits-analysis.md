# Cleanup-commit reference dataset

Per the user's tip: a merged PR's commits are themselves a calibration signal. **First commit** of a PR is the proposal; **non-first commits** that match cleanup/follow-up patterns indicate the proposal wasn't merge-ready. If our calibrated gate would have caught the issue at first-push time, that's positive validation. If not, it's a calibration gap.

## Method

`calibration/analyze_cleanup_commits.py`:
1. For every measured merged PR (42 PRs across 8 repos, see `calibration/findings/prs/`), fetch its commit list via `gh api repos/<o>/<r>/pulls/<n>/commits`.
2. Drop the first commit (the proposal).
3. Match remaining commit messages against a cleanup regex covering: `address (review|comments?|feedback)`, `apply suggestions`, `cr feedback`, `nit(s)?`, `fix (typo|tests?|lint|ci|build|formatting|style|spelling)`, `lint`, `format`, `prettier`, `cleanup`, `tidy`, `polish`, `oops`, `whoops`, `oversight`, `revert`, `pr feedback`, `per (review|comments?|cr)`, `as per (review|comments?)`, `requested changes?`, `regen(erate)?`, `update snapshots?`.

Output: `calibration/findings/cleanup_commits.json`.

## Results

| Metric | Value |
|---|---|
| PRs analyzed | 42 |
| PRs with at least one non-first cleanup commit | 5 |
| Cleanup commits total | 6 |
| Cleanup-PR rate | **11.9 %** |

5 PRs flagged:

| Repo | PR | Total commits | Cleanup | Notes |
|---|---|---|---|---|
| fastapi | 15165 | 5 | 1 | bot-pushed `🎨 Auto format` after merge of translation update |
| fastapi | 15172 | 6 | 1 | bot-pushed `🎨 Auto format` after merge of translation update |
| fastapi | 15316 | 31 | 1 | author-pushed `Revert "Introduce issue to test zizmor"` (intentional probe removal) |
| nextjs | 93285 | 3 | 2 | author-pushed `tweaks from PR feedback` and `check tag existence before cleanup` |
| pydantic | 13081 | 2 | 1 | author-pushed `tidy up accessor type aliases` (Rust type-alias trim, -19 lines) |

## Per-PR diff inspection

### fastapi pr-15165 / 15172 — bot auto-format

The cleanup commit is mechanical: a CI bot ran a formatter and pushed the result. **Calibration relevance: minor.** The gate's `no-quality-escapes` and `risk-calibrated-bloat` detectors don't measure formatting drift; this is the formatter's job, not the gate's. Out of scope.

### fastapi pr-15316 — author-revert during security-tooling integration

Author intentionally added a probe issue (`zizmor`-test artifact) and reverted it before the final state. **Not a calibration target** — this is iterative authoring, not response to review.

### nextjs pr-93285 — author-pushed PR feedback

Cleanup commit `b7bcd9c7` titled `tweaks from PR feedback`. Inspecting the diff via `gh api repos/vercel/next.js/commits/b7bcd9c7`:

- `scripts/release-github-api.js`: converted positional args → object destructuring (`createTreeFromLocalCommit({ token, baseSha, localReleaseSha })`).
- `scripts/start-release.js`: replaced `stdio: 'pipe'` + manual `child.stdout?.pipe(process.stdout)` with `stdio: 'inherit'`.

**Calibration relevance: zero.** Both changes are stylistic preference. The gate is not designed to surface "use object destructuring instead of positional args" or "use inherit stdio." These are the kind of feedback that humans give that the gate's posture explicitly avoids prescribing — see CLAUDE.md operating principle "Match existing style, even if you'd do it differently."

### pydantic pr-13081 — author self-tidy of Rust type aliases

Cleanup commit `f20a472e` titled `tidy up accessor type aliases`. Diff: removed two `pub type ScopedFieldNameState<...>` and `ScopedDataState<...>` declarations in `validation_state.rs`. Net -19 lines.

**Calibration relevance: high.** This is exactly the abstraction-sniff target shape — a type alias introduced for "extension" or "abstraction" reasons that the author later realized was unnecessary. **However:** the gate's existing `DESIGN_RE` only matches `class \w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)` — Rust type aliases don't match. Same blind spot as **FN-2 (Go factory regex)** but for Rust.

This adds a recommendation:

**FN-6 — Rust type-alias abstraction blind spot.** Extend `DESIGN_RE` with `\bpub\s+type\s+\w*(State|Manager|Strategy|Adapter|Provider|Factory|Builder|Registry|Context|Scope|Mode|Config|Options|Settings)\b` for Rust. (And the equivalent Go `type Foo<X>` pattern.) Defer to the same PR that fixes FN-2.

## What the calibration gate would have caught vs. not

Across the 6 cleanup commits in 5 PRs:

| # | Source | What the cleanup did | Caught by calibrated gate? |
|---|---|---|---|
| 1 | fastapi 15165 / 15172 | format-only bot push | No — outside gate scope |
| 2 | fastapi 15316 | self-revert of test probe | No — iterative authoring |
| 3 | nextjs 93285 stdio | stylistic simplification | No — stylistic |
| 4 | nextjs 93285 args | positional → destructuring | No — stylistic |
| 5 | nextjs 93285 tag check | added tag-existence guard | No — defensive logic the author added |
| 6 | pydantic 13081 type aliases | removed unnecessary type aliases | **Would catch** with FN-2/FN-6 fix in PR-8 (Rust extension to DESIGN_RE) |

**Headline:** of the 5 cleanup-flagged PRs across 8 production repos, 1 cleanup commit (16.7%) maps to a calibration target the proposed PR-8 would address (Rust type-alias abstraction sniffing). The other 4 are formatter/stylistic/defensive — explicitly outside the gate's design scope.

## Bias / scope notes

- **Sample size**: 42 PRs is small. The 11.9% cleanup-PR rate may not generalize.
- **Bot-author noise**: Dependabot/translation-bot PRs distort the denominator by inflating the "single-commit PR" share. Filtering bot-authored PRs as we did during measurement reduces but doesn't eliminate this.
- **Regex limitations**: cleanup commits without standardized message wording (e.g., the author silently fixes a typo and commits with `change xxx`) are missed. The 11.9% is therefore a **lower bound**, not a precise estimate.
- **No reviewer-comment correlation**: this analysis only looks at commit messages. A richer pass would correlate cleanup commits to GitHub review comments via `repos/<o>/<r>/issues/<n>/comments` and check whether the review thread mentions the symptom. Out of scope for this iteration.

## Recommendation summary

1. **Add FN-6 to PR-8 scope**: extend `DESIGN_RE` with Rust `pub type X = ...` patterns, alongside Go's `func NewXFactory(...)` (FN-2). One regex addition; one new test.
2. **The cleanup-commit dataset confirms the calibration's posture**: most cleanup is style/iteration, which is correctly outside the gate's design. The gate's job is to catch the calibrated FP/FN classes, not to mediate stylistic preference.
3. **Future calibration cycles** can integrate the cleanup-commit signal as an automatic feedback loop: after each gate change, re-run the analysis, and any new cleanup-commit class that appears (e.g., reviewers asking for a pattern the gate missed) becomes the next calibration target. This is the autonomous-loop spirit of `karpathy/autoresearch`.
