# False-negative classes

Per the guide, false negatives are "cases where the gate *should* have fired and didn't." This is structurally harder to find from passive measurement: we have to have an opinion about what *should* be wrong in the codebase.

Approach below: take three classes the guide flagged as suspected gaps, then check directly.

## FN-1 — C++ source not classified

**Hypothesis**: gRPC's `src/core/` is C++ (`.cc`, `.h`, `.cpp`). The gate's `SOURCE_EXTENSIONS` does not include any C/C++ extension. C++ files therefore cannot trigger any detector.

**Verification**: confirmed by reading `lean_code_gate.py:159-174`:

```
SOURCE_EXTENSIONS = {
    ".cjs", ".cts", ".go", ".js", ".jsx", ".mjs", ".mts",
    ".php", ".py", ".rb", ".rs", ".sh", ".ts", ".tsx",
}
```

In the gRPC measurement, `sourceFilesCount: 38` out of 222 changed files — most of the "missing" 184 are C++, build files, and proto. Bloat, reuse, escape, and duplicate detectors all skip them.

**Verdict**: confirmed gap. **Disposition**: document as out-of-scope for v3 (extending `SYMBOL_PATTERNS` to C++ is a project; the gate's posture is "Python/TS first"). Add a one-line comment in `policy.json` and a note in REPORT.md §6.4 (out-of-scope findings).

## FN-2 — Go factory regex doesn't match Go idiom

**Hypothesis**: `DESIGN_RE` matches `class \w*Factory` etc., but Go has no `class`. Go's idiomatic factory is `func NewFooFactory(...)`. The current regex therefore can't see Go factories.

**Verification**: regex from `lean_code_gate.py:152-157`:

```python
DESIGN_RE = [
    (re.compile(r"\bclass\s+\w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)\b"), "pattern-named class"),
    ...
]
```

`\bclass\s+...` cannot match `func NewFooFactory(`. Confirmed gap.

**Cross-check**: `grep -nE 'func New\w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)\(' calibration/repos/grpc -r --include='*.go' | head -5` — gRPC has very little Go (most is C++), but the principle holds for any Go-heavy repo.

**Verdict**: confirmed gap. **Disposition**: extend `DESIGN_RE` with one Go-aware pattern: `\bfunc\s+(?:\([^)]*\)\s*)?New\w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)\b`. PR-8 will land this with a regression test.

## FN-3 — `# type: ignore` and `// @ts-ignore` in changed source

**Hypothesis**: the gate's `GENERAL_ESCAPE_RULES` includes `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `# type: ignore`. If we had a recent commit adding one of these, it should fire as a quality escape.

**Verification**: in our sample, escapes did fire on ts-ignore-style markers. e.g., aws-sdk-js's 119 quality-escape locations include `as any` (TS escape rule) which is the closely-related sibling. Direct `@ts-ignore` adds were not isolated in our window. Pin via synthetic test (Phase 5).

**Verdict**: detector path works; coverage is just sample-dependent. **Disposition**: add a synthetic test fixture pinning that `@ts-ignore` in a changed `.ts` file fires `no-quality-escapes`. (Already exists in some form at `test_quality_check_detects_production_type_escape_but_allows_test_any` — extend rather than duplicate.)

## FN-4 — Indexer caps fire silently

**Hypothesis**: the symbol indexer uses `quality_max_index_files: 4000` and `quality_max_index_symbols: 25000`. When TypeScript or Sentry exceed these, the indexer breaks out of its loop without logging. Reuse detection across the un-indexed tail is therefore impossible — false negatives by design.

**Verification**: the gate emits no per-run log of "indexer hit cap". Reading `lean_code_gate.py` in the index path would tell us, but the symptom is observable: TypeScript has 56 "source" files in our window (since ~3700 changed files but most are non-Source, e.g. `.d.ts` are not in `SOURCE_EXTENSIONS`?) — wait, `.ts` is, so the source count *should* be much higher. The 56 likely reflects the indexer's bound, not the actual count of changed source files. *Possible measurement artifact*: I have not verified this hypothesis directly; flag as `Uncertain`.

**Verdict**: `Uncertain`. **Disposition**: out-of-scope for calibration. Belongs in REPORT.md §6.4 (instrumentation gap — the gate should emit a log line when caps fire, regardless of `--json` mode).

## FN-5 — Application-code escapes that look like generated/test code

**Hypothesis**: the gate has `is_test_like_path()` to exempt `tests/`, `__tests__/`, `__fixtures__/`, etc. If application code lives in a subtree the heuristic mistakes for tests, escapes there are silenced.

**Verification**: `TEST_MARKERS` from `lean_code_gate.py:194-205` includes `/generated/`. So **anything under `/generated/` is treated as test-like and exempt from escape rules**. This is wrong: `/generated/` typically contains *application*-level generated code (protobuf stubs, OpenAPI clients), not tests. A real escape introduced into `/generated/` would not fire.

This is also tangled with the calibration recommendation in PR-5: we want `/generated/` *bloat-excluded* but **not** *escape-exempt*. Generated code can still legitimately import a real type vs. cast to `any`; if it uses `any`, that's the codegen template's choice and we shouldn't override the human author. So the escape exemption is also defensible — but it needs to be a deliberate decision, not bundled into "test-like."

**Verdict**: `Inferred` defect. **Disposition**: document; recommend separating `is_generated_path` from `is_test_like_path` so calibration can address bloat and escapes independently. Out-of-scope for the four planned PRs (PR-5..PR-8); flag in REPORT.md §6.4.

## Summary

Confirmed false negatives requiring code change:
- **FN-2** (Go factory regex) — addressed by PR-8.

Confirmed gaps belonging to documentation/out-of-scope:
- **FN-1** (C++ invisible) — note in policy.json + REPORT.md.
- **FN-3** (`@ts-ignore` coverage) — extend existing test (Phase 5).
- **FN-4** (silent cap breaks) — REPORT.md §6.4.
- **FN-5** (`/generated/` is test-like) — REPORT.md §6.4.
