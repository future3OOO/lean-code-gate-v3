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

Evidence-backed observations from the Slop Scan repo:

- The full benchmark separates explicit-AI repos from mature OSS by normalized ratios, not raw counts: median blended score is about `6.9x`, score/file about `8.8x`, and score/KLOC about `7.4x`.
- The per-rule benchmark is the better guide for Lean Gate. `defensive.promise-default-fallbacks` ranks first in isolation; `api.generic-status-envelopes`, `defensive.error-swallowing`, and `defensive.stringified-unknown-errors` follow.
- High-volume rules are not automatically first-class gate rules. Empty catches, pass-through wrappers, and error-obscuring also appear in mature OSS, so they need contract context, boundary exemptions, and delta/touched-line scoping before any hard failure.
- Slop Scan's repo-wide view catches accumulated habits. Lean Gate works at edit time, so its first integration should be touched-surface warnings and contract prompts, not whole-repo shape scoring.

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

5. Calibrate by rule family and touched surface

   The current calibration can look flat when it reports findings per PR and mixes rule families. The next pass should report rule-family hits per touched file, touched function, and KLOC, and distinguish added, resolved, worsened, and improved findings. Slop Scan's delta identity model is the useful lesson here, not its full scanner.

Recommended integration order:

1. Contract prompts first: failure contract, boundary shape, wrapper value, and input validation/narrowing.
2. Narrow added-line warnings second: promise/default fallbacks, log-and-continue catches, stringified unknown errors, generic envelopes, and vague record casts.
3. Delta reporting third: added/resolved/worsened/improved counts by rule family on touched files.
4. Policy escalation last: hard failures only after calibration shows low false-positive rates on touched code.

## Slop Rules Not To Build First

- Do not add directory fanout, barrel-density, or over-fragmentation rules until lower-noise slices are measured.
- Do not add a broad AST framework or dependency-heavy scanner for this plan.
- Do not create a separate "slop gate"; these checks belong in the Lean Change Contract and existing quality pass.
- Do not treat high full-repo frequency as proof a pattern should be a hard PR-time blocker.

## Future Placement

This file is a planning artifact. If the rule is implemented, the core principle should move into `METHODOLOGY.md` beside the other gate rules, while implementation notes can stay in a plan or issue. The security rule should not become conceptually separate from the rest of the Lean Change Contract.

## Acceptance Criteria

- Agents are prompted to ask "can this value be removed?" before sanitizing it.
- Agents are prompted to ask "should this wrapper, fallback, or generic envelope exist?" before implementing it.
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
