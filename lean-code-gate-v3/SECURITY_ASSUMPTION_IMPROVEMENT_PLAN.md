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

Slop Scan's strongest benchmark separation came from direct implementation habits, not broad size metrics: promise/default fallbacks, generic status envelopes, swallowed or obscured errors, stringified unknown errors, pass-through wrappers, generic record casts, and duplicated test mock setup. Lean Gate should not port that scanner wholesale. It should use those signals to improve pre-writing pressure before code is added.

Low-bloat slices:

1. Preserve failure information

   Contract guidance should challenge changed code that catches, rejects, or logs an error and then returns a default value. The first question is whether the caller should see the failure instead. A narrow later warning can target added `catch` or promise-rejection branches that return `null`, `undefined`, empty collections, `false`, or generic success values.

2. Require wrapper value

   Pass-through wrappers should be justified by behavior, normalization, instrumentation, or a stable compatibility boundary. If a wrapper only renames a call, the lean fix is to remove it or call the existing function directly.

3. Keep result envelopes contractual

   Generic `{ success, data, error, message }` envelopes should exist only when an API boundary or established local contract requires that shape. Internal code should prefer the existing domain result, exception, or typed error path.

4. Share test setup only after real duplication

   Duplicated mock setup is a useful slop signal, but the Lean Gate rule stays narrow: if changed tests repeat the same mock wiring, prefer the existing fixture or add a helper only when there are at least two current call sites. Do not introduce speculative test factories.

5. Calibrate with touched-surface metrics

   The next calibration pass should report rule-family hits per touched file, touched function, and KLOC, not only findings per PR. Slop Scan's repo-wide ratios explain why broad pre/post averages can look flat when the real signal sits in specific rule families.

## Slop Rules Not To Build First

- Do not add directory fanout, barrel-density, or over-fragmentation rules until lower-noise slices are measured.
- Do not add a broad AST framework or dependency-heavy scanner for this plan.
- Do not create a separate "slop gate"; these checks belong in the Lean Change Contract and existing quality pass.

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
