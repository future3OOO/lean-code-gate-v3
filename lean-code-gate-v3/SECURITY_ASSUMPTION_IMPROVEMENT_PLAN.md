# Security Assumption Improvement Plan

## Problem

PR #21 exposed a class of mistake: treating "sanitize before storing" as the first answer when the leaner answer is "do not read or carry the risky value." The gate should push agents to prove a sensitive value is necessary before they collect, hash, sanitize, log, persist, or print it.

The target is not a claim that agents never leak secrets. The target is to remove unnecessary secret-bearing data from the implementation path.

## Principle

If a sensitive value is not required for the contract, remove it from the data flow. Redaction, sanitization, and hashing are fallbacks only after necessity is proven.

## Sensitive Inputs

Treat these as sensitive by default:

- credentials, tokens, cookies, auth headers, API keys, and passwords
- git remote URLs and repository URLs that may contain credentials
- environment variables and local config that may carry credentials
- SSH paths, key paths, `.netrc`, credential helper output, and profile paths
- authentication, authorization, credential-exchange, session, webhook, or secret-manager payloads
- request or response headers carrying cookies, tokens, or authorization material

## Proposed Gate Checks

1. Sensitive input justification

   If changed code starts reading a sensitive source, the Lean Change Contract must name why the value is necessary. If the same behavior can be achieved without the value, the change should remove the input instead.

2. No persisted sensitive values

   Block or warn when changed code writes sensitive values into state files, logs, caches, telemetry, status output, error messages, or test snapshots.

3. Elimination before redaction

   Prefer deleting the data dependency. Allow sanitization only when the sensitive value is genuinely required at the boundary.

4. Hashing is not automatic safety

   Hashing a sensitive value still requires justification for reading it. Hashing converts the value into a stable per-secret identifier that can be correlated across systems, repos, runs, or users. If the value is not needed, do not hash it.

5. Security claims need evidence

   Claims such as "no secret leak" or "fully eliminates leak class" require proof that the risky value is not read or carried, or a clear explanation of the minimum place it is still required.

## Initial Implementation Shape

Start as a contract and risk-check enhancement, not a broad scanner:

- Add security keywords to contract guidance and review prompts.
- Add deterministic warnings for obvious sensitive sources and sinks in changed code.
- Keep findings narrow and explainable.
- Do not add dependency-heavy secret scanning.
- Do not block benign code unless a sensitive source and a persistence or output sink are both visible.

Concrete first pass:

1. Trigger on sensitive sources in added lines, such as `os.environ`, `git remote get-url`, home-directory config reads, `.netrc`, `*.pem`, `*.key`, `.ssh`, `.aws`, keyring access, or non-localhost network payloads.
2. Require a contract justification only when the trigger fires. If the trigger is a false positive, record that explicitly rather than requiring every contract to carry security boilerplate.
3. Warn first when a triggered source appears to flow to persistence or output, such as `write_text`, `json.dump`, `print`, logger calls, status or telemetry output, or gate state writes. Promote to hard failure only after calibration proves the signal is precise.

## What Not To Build

- Do not add a separate security gate beside the existing lean rules.
- Do not ship a broad catalog of token formats or credential regexes.
- Do not treat redaction helpers as the preferred fix when the sensitive input can be removed.
- Do not require sensitive-input fields on contracts that never touch sensitive sources.

## PR #21 Example

The original repo identity design used the origin URL as identity material, then added parsing to strip credentials. This plan would have forced the earlier question: is the origin URL necessary at all? For PR #21, repo root plus git common dir already carried the required identity, so the lean fix was to drop origin URL handling entirely.

## Slop Scan Lessons

Slop Scan's useful signal is not "AI code is bigger." Its benchmark separates cohorts through repeated local implementation habits, then normalizes by file, KLOC, and function. The best isolated rule signals are promise/default fallbacks, generic status envelopes, log-and-continue catches, stringified unknown errors, generic record casts, pass-through wrappers, and duplicated test mock setup.

Lean Gate should not port that scanner wholesale. It should extract the structural habits that fit a pre-writing tool and use them to pressure the contract before code is added.

Evidence-backed observations from the Slop Scan repo and our own head-to-head experiments (`lean-code-gate-calibration` PR #2):

- Slop Scan's full benchmark separates explicit-AI from mature OSS by normalized ratios, not raw counts: median blended score `6.9x`, score/file `8.8x`, score/KLOC `7.4x`.
- We re-ran our gate against slop-scan's own 18-repo pinned benchmark (whole-repo mode). Our cohort separation came out at **1.18x per find/KLOC vs their 5.39x**. Our gate fires fewer raw findings on AI-coded repos than mature OSS in this set because the AI repos are smaller; the size correlation dominates.
- Per-PR head-to-head on the same 458 TS/JS PRs in our regular calibration corpus: cross-tool Spearman `0.40–0.63`, Pearson `0.66–0.94` against slop's `addedCount`. Where the scope matches, the tools agree on volume. Where it doesn't (whole-repo per-KLOC), they only weakly agree because the rule sets target different patterns.
- **Zero rule-family overlap on the 10 highest-signal slop-scan rules.** R-1..R-6 are general structural detectors. Slop Scan catches AI-idiom patterns (placeholder comments, generic envelopes, `as any` casts, error swallowing, etc.). The detector-coverage gap, not threshold calibration, is the load-bearing cause of the cohort-separation gap.
- Per-rule signal in slop-scan's own published benchmark: `defensive.promise-default-fallbacks` ranks first in isolation, then `api.generic-status-envelopes`, `defensive.error-swallowing`, `defensive.stringified-unknown-errors`. In our 18-repo run, the actual top per-repo firers were `tests.duplicate-mock-setup` (25 hits in openusage) and `comments.placeholder-comments` (consistently fires on every explicit-AI repo, near-zero on mature-oss).
- `comments.placeholder-comments` is missing from earlier integration drafts and is the cheapest-to-port, highest-specificity, lowest-FP-risk rule available. It should ship first.
- High-volume rules are not automatically first-class gate rules. Empty catches, pass-through wrappers, and error-obscuring also appear in mature OSS, so they need contract context, boundary exemptions, and delta/touched-line scoping before any hard failure.
- Slop Scan's repo-wide view catches accumulated habits. Lean Gate works at edit time, so PR-time integration should be touched-surface warnings and contract prompts, not whole-repo shape scoring. Don't try to match slop-scan's whole-repo cohort separation at PR-time gate; that's a scope-of-measurement difference, not a detector-quality goal.

Language scope:

Earlier drafts treated this whole bundle as "TS/JS only." That was over-narrow. The honest split:

- **Language-agnostic** (universal AI-tic patterns, per-language regex tier sufficient):
  - `comments.placeholder-comments` — natural-language phrases in any comment style (`//`, `#`, `--`, docstrings).
  - `defensive.empty-catch` — empty exception handlers across languages (JS empty catch block, Python bare-except with no body, Go `if err != nil` block with no body, Rust `if let Err(_)` empty arm, Ruby `rescue` with no body).
  - `defensive.error-swallowing` — catch-and-only-log (per-language conventions).
  - `defensive.error-obscuring` — catch-and-return-generic-default (per-language conventions).
  - `structure.pass-through-wrappers` — single-call forwarding functions (per-language regex/AST tier).
- **TS/JS only** (genuinely language-specific syntax):
  - `defensive.promise-default-fallbacks` — `.catch(() => null|[])` is JS Promise syntax.
  - `defensive.stringified-unknown-errors` — `String(error)` after `unknown` catch is a TS-idiom (Python's `str(e)` is normal usage).
  - `structure.generic-record-casts` — `as any`, `as Record<string, unknown>` are TS syntax.
  - `tests.duplicate-mock-setup` — `vi.mock()`/`jest.mock()` are JS framework idioms.
- **Higher-FP-risk in dynamic langs** (defer):
  - `api.generic-status-envelopes` — the `{success, data, error}` shape is heavily used in legitimate API/RPC code; needs careful boundary exemption logic per language.

First implementation can therefore start with two language-agnostic rules (placeholder-comments first, error-swallowing/empty-catch pair second) and one TS/JS pack (promise-default-fallbacks, generic-record-casts) without taking a TypeScript runtime dependency. Multi-language regex tier is the right shape; AST parsing is out of scope until calibration proves the simpler path is insufficient.

Fundamental takeaways:

1. Preserve failure information

   The strongest shared pattern is information erasure: caught or rejected failures become `null`, `undefined`, empty collections, `false`, generic success values, generic replacement errors, or plain strings. Contract guidance should ask what failure contract the caller needs before any fallback is written.

   Low-bloat detector slice: warn on added promise `.catch(...)` or `catch` branches that only log, return a cheap default, or stringify an unknown error. Hard-fail only after calibration proves the added-line signal is precise.

2. Keep boundary shapes domain-specific

   Generic `{ success, data, error, message }` envelopes and `Record<string, unknown>` casts both flatten domain meaning into shallow bags. They are not always wrong, but the contract should name the boundary that requires them. Internal code should prefer existing domain results, typed error variants, or explicit validation/narrowing.

   Low-bloat detector slice: warn when added code introduces a boolean status envelope or vague `Record<string, unknown>` cast outside an existing API/config boundary.

3. Require wrapper value

   Pass-through wrappers, async pass-throughs, and barrel-only files create call-graph weight without behavior. They also have legitimate boundary and compatibility uses, so the Lean contract should require the value: validation, normalization, instrumentation, retry, compatibility, or external integration boundary.

   Low-bloat detector slice: warn only on newly added one-line forwarding functions with no nearby compatibility comment and no known boundary target. Do not start with directory fanout or barrel-density scoring.

4. Share repeated scaffolding only after real duplication

   Duplicated mock setup and near-identical helper shapes are useful accumulated-slop signals. For Lean Gate, the edit-time rule is narrower: if changed tests repeat existing mock wiring, use the existing fixture; add a new helper only when there are at least two current call sites. Do not introduce speculative factories.

5. Track added findings by rule family

   The runtime lesson from Slop Scan's delta model is to report whether a touched change added, resolved, worsened, or improved a finding. The calibration-specific table and cohort work belongs in `SLOP_SCAN_CALIBRATION_PLAN.md`.

Recommended integration order:

1. **Contract prompts first**: failure contract, boundary shape, wrapper value, and input validation/narrowing. No new detector code; just contract-text checks.
2. **Placeholder-comments second** (language-agnostic, lowest FP risk). One regex helper in `quality_checks(...)`. Single PR. Calibrate against the corpus, expect near-zero firing on `recent_mature_oss` and consistent firing on `post_ai_public` and `private_own`.
3. **Universal failure-contract pair third**: empty-catch + error-swallowing across the languages we already extract symbols from (Python, JS/TS, Go, Rust, Ruby, PHP, shell). Per-language regex tier driven by `language_for_path(...)`. Calibrate before any hard failure.
4. **TS/JS pack fourth**: promise-default-fallbacks, generic-record-casts, stringified-unknown-errors. JS-syntax-specific; cannot generalize.
5. **Wrapper-value warning fifth** (universal with per-language regex). Higher FP risk than the failure-contract pair; defer until that pair shows calibrated behavior.
6. **Touched-change delta reporting** alongside step 5: added/resolved/worsened/improved counts by rule family in `run_quality_gate(...)` JSON output.
7. **Policy escalation last**: hard failures only after calibration shows low false-positive rates on touched code. Generic status envelopes deferred indefinitely until boundary-path allowlist work is done.

## Implementation Mapping

These changes should land in `lean_code_gate.py` by extending existing contract and quality surfaces, not by adding a parallel gate.

| Plan item | Language scope | Script surface | First implementation |
|---|---|---|---|
| Sensitive input justification | universal | `check_change(...)`, `run_quality_gate(...)`, new small helpers called from `GateContext.added_lines` | Detect added sensitive-source tokens and persistence/output sinks. Emit warnings first unless the same added line path clearly writes a sensitive value to gate state, logs, status, or snapshots. Use existing `risk_check` text as the justification surface before adding a new CLI field. |
| Eliminate before redact/hash | universal | `check_change(...)` for proposed text, `scan_quality_escapes(...)`-style changed-line scan for final checks | Warn when added code both reads sensitive input and adds sanitizer/redaction/hash plumbing. Message should ask whether the input can be removed from the data flow. Do not add credential-format regexes. |
| Placeholder comments | **language-agnostic** (highest priority, ship first) | new `placeholder_comment_warnings(ctx)` helper called from `quality_checks(...)` | Regex match against AI-tic phrases ("add more validation," "implement here," "extend this function," "future enhancement," "customize this", etc.) in `//`, `#`, `--`, and docstring comments across all `is_source_path` files. Lift slop-scan's `PLACEHOLDER_PATTERNS` list verbatim. Near-zero FP risk on mature OSS. |
| Failure-contract / fallback pressure (universal) | language-agnostic with per-language regex tier | `run_quality_gate(...)`, `quality_checks(...)`, additive JSON warning fields | Warn on newly added empty exception handlers, catch-and-only-log, and catch-and-return-generic-default. Per-language regex tier: JS `catch \(.*\) {\s*}`, Python `except[^:]*:\s*pass`, Go `if err != nil \{\s*\}`, Rust `if let Err\(_\) = .*\{\s*\}`. Match by file extension via `language_for_path(...)`. |
| Failure-contract / fallback pressure (TS/JS) | TS/JS only | same surface | Warn on Promise default-fallbacks (`.catch(() => null|[]|{}|false)`) and stringified-unknown-error patterns (`String(error)`, `${err}`). Both are JS-syntax-specific so cannot be language-agnostic. |
| Generic record casts | TS/JS only | `proposed_quality_hits(...)` / sibling helper | Warn on newly added `as any`, `as Record<string, unknown>`, or `as unknown as ...` outside existing API/config/boundary paths. Genuine TS syntax — no language-agnostic equivalent because Python's `Dict[str, Any]` is idiomatic. |
| Generic status envelopes | defer (high FP risk in every language) | not implemented in first wave | The `{ success, data, error }` shape is legitimate at API/RPC boundaries in JS, Python (FastAPI), Go (HTTP handlers). Needs explicit boundary-path allowlist before warning. Do not implement until placeholder-comments + error-swallowing calibrate cleanly. |
| Wrapper value (pass-through) | language-agnostic with per-language regex tier | `check_change(...)` for fast proposed-patch feedback, `detect_reuse_issues(...)` or a sibling final warning helper | Warn on newly added one-line forwarding functions: JS `function name(args) { return other(args); }`, Python `def name(...): return other(...)`, Go `func name(args) { return other(args) }`. Per-language match. Do not scan directory fanout first. |
| Verification mode | `contract_errors(...)`, possibly `parser()`/`declare(...)` only after calibration | First pass: require `proof_plan` prose to name `red-green-refactor`, `green-refactor-green`, or `smoke-check` for non-minimal code work. Later pass, if stable, add `--verification-mode` and store it in `declare(...)`. |
| Production-shaped proof | `final_errors(...)`, `run_quality_gate(...)` warning helper over changed test files | For bugfixes and behavior changes, warn when tests changed but no added test line appears to call a production entrypoint, CLI/hook command, local server, parser, or production-shaped fixture. Keep as warning because language-specific precision varies. |
| Wasteful test bulk | `run_quality_gate(...)`, new `test_shape_warnings(ctx)` helper, `quality_checks(...)` | Warn only on high-confidence combinations: large added test block, high mock/setup token ratio, weak assertion count, and no visible production entrypoint call. Avoid line-count-only failures. |
| Behavioral contracts and out-of-scope boundaries | `contract_errors(...)` over existing `authoritative_contract`, `affected_surface`, `invariants`, and `risk_check` | Add lightweight text checks for procedural placeholders only after reviewing real contracts. Do not reject file paths categorically; reject contracts that only say "edit file X/line Y" without desired behavior or acceptance criteria. |
| Deterministic helpers and debug probes | Existing temp-artifact and quality-escape checks plus a small added-line warning helper | Warn on new scripts/harnesses/debug markers unless referenced by `verify`, named in `risk_check`, or clearly temporary and removed before final. Continue relying on final quality gate to catch lingering temp artifacts. |
| Delta reporting | `run_quality_gate(...)` JSON result | Add additive fields such as `securityAssumptionFindings`, `slopShapeFindings`, and `verificationShapeFindings`, each grouped by `added`, `resolved`, `worsened`, and `improved` when baseline comparison is available. Existing consumers of `ok`, `errors`, `warnings`, and `checks` remain compatible. |

## Verification Shape Lessons

The useful lesson from `future3OOO/skills` is that proof quality is part of code quality. The gate should pressure agents to describe the shape of the feedback loop before they write code, without forcing one workflow onto every task.

Low-bloat additions:

1. Name the verification mode

   The `proof_plan` should say whether the work is `red-green-refactor`, `green-refactor-green`, or `smoke-check`. Bug fixes and behavior changes should prefer red-green-refactor: reproduce the failure, make the smallest fix, rerun the same proof, then keep only the regression surface that proves the behavior. Refactors should establish green first, change one behavior-preserving slice, and rerun the same proof. Docs, config, and hook-runtime smoke checks can use smoke-check when a failing test would be artificial.

2. Test through the public interface

   Tests should verify observable behavior through the interface that callers use. Avoid tests that only assert private methods, internal call order, or internal collaborator calls. If a real bug cannot be tested through a correct interface, that is architecture evidence to record in `risk_check`, not a reason to add a shallow fake-green test.

3. Mock only real boundaries

   Mock external systems, time, randomness, filesystem, or network boundaries when needed. Do not mock owned internal modules just to make a test easier. Repeated mock wiring should reuse an existing fixture; add a helper only when at least two current call sites need it.

4. Use production-shaped proof

   Prefer tests or smoke checks that run the underlying production code in a realistic setup: real CLI commands, real hook payloads, real config/state paths, real parsers, real HTTP requests against a local server, or production-shaped fixtures. Avoid large tests that mostly assemble mocks, synthetic objects, or invented payloads without proving the changed behavior on the path users actually run.

5. Keep slices vertical

   Prefer one behavior-level test or runnable check, then the minimum implementation for that behavior, then the next behavior. Bulk-writing all tests first encourages imagined interfaces and wide diffs. For larger work, contract guidance should ask for thin end-to-end slices instead of layer-by-layer implementation batches.

6. Warn on wasteful test bulk

   A future narrow warning can flag added tests that are large, mock-heavy, and assertion-light while never invoking the changed production entrypoint. The warning should point to the missing production-shaped proof, not reward deleting useful regression coverage. Calibrate before blocking.

7. Treat shallow interfaces as risk evidence

   Pass-through wrappers, one-adapter seams, and modules whose tests need to reach past the interface are signs that the interface may not be earning its keep. The lean response is not an architecture scanner first; it is a contract prompt asking what value the wrapper, seam, or interface adds now.

8. Keep contracts behavioral

   Contract fields should describe current behavior, desired behavior, key interfaces, acceptance criteria, and explicit out-of-scope boundaries. Avoid procedural instructions tied to file paths, line numbers, or "edit this function" steps; those go stale and encourage agents to follow instructions instead of rechecking the code.

9. Make helpers and probes earn their place

   Add helper scripts only for deterministic, repeated, or error-prone operations that would otherwise be regenerated. Temporary debug logs, probes, and harnesses should be tagged or isolated so they can be removed before completion.

## Slop Rules Not To Build First

- Do not add directory fanout, barrel-density, or over-fragmentation rules until lower-noise slices are measured.
- Do not add a broad AST framework or dependency-heavy scanner for this plan.
- Do not create a separate "slop gate"; these checks belong in the Lean Change Contract and existing quality pass.
- Do not treat high full-repo frequency as proof a pattern should be a hard PR-time blocker.
- Do not chase slop-scan's whole-repo cohort-separation magnitude (5–7×) at PR-time gate. PR-time and whole-repo are different scopes; the first measures intent on a diff, the second measures accumulated state. Don't conflate them.
- Do not implement the generic-status-envelope detector before the rest of the pack calibrates. The shape is too common in legitimate API/RPC code in every language; needs an explicit boundary-path allowlist first.
- Do not add a TypeScript runtime dependency to the gate unless regex/string warnings fail calibration and the deployment cost is explicitly accepted.
- Do not add a broad test-smell scanner first. Verification-shape problems should start as `proof_plan` and `risk_check` prompts; deterministic warnings can follow only for narrow, high-confidence patterns.
- Do not reward tests by volume. A small production-shaped repro is better than a long mock scaffold that does not exercise the changed code path.
- Do not assume a rule is TS/JS-only because slop-scan implements it as TS/JS. Re-evaluate per the language-scope split in "Slop Scan Lessons" — placeholder-comments, error-swallowing, empty-catch, error-obscuring, and pass-through wrappers all generalize.

## Future Placement

This file is a planning artifact. If the rule is implemented, the core principle should move into `METHODOLOGY.md` beside the other gate rules, while implementation notes can stay in a plan or issue. The security rule should not become conceptually separate from the rest of the Lean Change Contract.

## Acceptance Criteria

- Agents are prompted to ask "can this value be removed?" before sanitizing it.
- Agents are prompted to ask "should this wrapper, fallback, or generic envelope exist?" before implementing it.
- Agents are prompted to name the verification mode and use red-green-refactor for bug fixes and behavior changes when a real failing proof is available.
- Contracts describe behavior, key interfaces, acceptance criteria, and out-of-scope boundaries rather than brittle implementation steps.
- Tests added under the plan verify public-interface behavior and avoid mocks of owned internal modules unless the contract explains the seam.
- Test additions use production-shaped payloads or setups where practical, and any mock-heavy test must explain the real boundary it replaces.
- Reviewer comments about secret exposure are resolved by eliminating unnecessary inputs when possible.
- Runtime state, logs, and status output avoid raw sensitive values.
- Any Slop Scan-inspired detector starts narrow, explainable, and tied to touched code.
- False positives remain low enough that developers do not bypass the gate.

## Open Questions

- Should this be a hard failure only for changed code that writes to persistent state, logs, or status output?
- Which sensitive source patterns are high confidence enough for deterministic blocking?
- Should contracts get a `--sensitive-input` field, or should this stay inside `--risk-check`?
- Should the rule be policy-overridable for repos that legitimately handle credential-bearing inputs, or hardcoded?
- Should wrapper/fallback/envelope checks stay inside `--risk-check`, or become structured contract prompts after calibration?
- Should verification mode stay as `proof_plan` prose, or become a structured field after enough real contracts show the categories are stable?
- Which wasteful-test signals are precise enough to warn on: added test size, mock/setup ratio, missing production entrypoint call, weak assertions, or repeated fixture wiring?
- Should placeholder-comments fire on documentation files (`*.md`, `*.rst`) or only on source-code comments? The slop-scan rule fires on source comments only; mature OSS docs frequently use phrases like "for future enhancement" without it being a defect signal.
- Which languages should the universal error-swallowing detector cover at first ship? The minimum-viable set is the languages we already extract symbols from (Python, JS/TS, Go, Rust, Ruby, PHP, shell). Adding more later is incremental.
- Should the calibration corpus be re-run with the new detectors enabled to measure cohort-separation lift? If so, target metrics are: explicit-AI vs mature-OSS per-PR finding rate ratio, and Spearman ρ vs slop-scan addedCount on the per-PR head-to-head.
- Should generic-status-envelopes ever ship, or is the FP risk too high in practice? The slop-scan TS/JS calibration suggests it can work with boundary exemptions; replicating that across languages is more research than the rest of this plan.
