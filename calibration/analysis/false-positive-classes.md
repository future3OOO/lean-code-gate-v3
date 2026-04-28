# False-positive classes

Source: `findings/<repo>.json` + manual inspection per `per-detector-hit-rates.md`.

Each row: a category, the repo+files where it was observed, and the probable fix in the gate. "Count" is conservative — only findings I inspected and classified `False` or `Inferred but human would not flag`.

| # | Category | Observed in | Count | Probable fix |
|---|---|---|---|---|
| FP-1 | Private/public sibling pair (`_foo` next to `foo`) flagged as duplicate-helper | django (`_save_formset` + `_walk_items` + `_as_sql`/`as_sql`); sentry (`_get_cache_key` + `validate`); pydantic (`__next__` ↔ `next`) | 8 across 3 repos | Augment reuse detector: when stems differ only by leading/trailing underscore prefix, treat as private/public sibling and either suppress OR require additional similarity signal (token overlap on body, not name). |
| FP-2 | Framework-mandated method names (`validate`, `save_model`, `get_queryset`, `clean_*`, `as_sql`, `__set__`, `__next__`) | sentry (`validate` per DRF); django (`as_sql` per QuerySet API); pydantic (`__next__` per Python iterator protocol) | 5 | Add `framework_override_names` policy list. Suppress reuse error tier when both symbols match an entry. |
| FP-3 | Generated TypeScript SDK code | aws-sdk-js (`clients/client-*/src/{commands,models,schemas}/*.ts`) | 18 bloat errors + ~91 bloat warnings | Add `excluded_path_globs` policy default like `clients/*/src/commands/**`, `clients/*/src/models/**`, `clients/*/src/schemas/**`. |
| FP-4 | Auto-generated Python | pydantic (`pydantic-core/src/self_schema.py`, file header explicit "DO NOT edit manually") | 2 errors | Same `excluded_path_globs` mechanism; default glob `**/self_schema.py` is too narrow — better to honor a banner regex or include `**/_generated/**`, `**/generated/**`, `**/__generated__/**` and document `// @generated`/`# @generated` banner detection as a follow-up. |
| FP-5 | TypeScript `*.generated.d.ts` | typescript (`src/lib/dom.generated.d.ts`, `webworker.generated.d.ts`) | 2 errors | `**/*.generated.*` glob default. |
| FP-6 | Per-package version constants duplicated by design | grpc (14 copies of `python_version.py`) | 1 group of 14 dup-block hits | Two options: (a) `excluded_path_globs` for `**/python_version.py` and similar; (b) same-basename clustering — when ≥3 duplicates share an exact basename, treat as deliberate cross-package coordination and demote severity. Option (b) is more surgical but more invasive. |
| FP-7 | Generic identifier collision in tooling subtrees | django (`scripts/pr_quality/check_pr.py format`/`Message` matched against unrelated django source) | 2 | Either exclude `scripts/**` for the reuse detector when the *new* file is in scripts but the *existing* match is in non-scripts (asymmetric reuse), or add `scripts/**` to ignored prefixes for reuse cross-matches. |
| FP-8 | `\|\| true` in CI shell scripts | grpc (`tools/run_tests/artifacts/*.sh`) | 5 | `\.sh` files in `/tools/` or `/scripts/` should be allowed `\|\|\s*true` (canonical CI-resilience). Either drop `\|\| true` from shell-script escape rules or add a path-based allowlist. |
| FP-9 | Self-bootstrapping language implementation source | typescript (`src/compiler/checker.ts`) | 1 | Document as out-of-scope: the gate is for application code, not language implementations. No code change. Add a note in policy.json comments. |
| FP-10 | C++/`.cc`/`.h` files invisible to gate | grpc (most of `src/core/` is C++) | (silent) | Either extend `SOURCE_EXTENSIONS` with `.cc, .cpp, .cxx, .h, .hpp` plus a `c++` entry in `SYMBOL_PATTERNS`, or document that the gate does not measure C++. Recommend the latter; SYMBOL_PATTERNS for C++ is a project of its own. |

## Patterns not observed but checked

- **Migrations bloat**: the guide flagged Sentry's `src/sentry/migrations/` as a likely bloat-source. Our 50-commit window did not include large migration churn — Sentry only has 0 bloat errors. The migrations gap is *theoretical* under our window but plausible under a wider window. Recommend `**/migrations/**` in `excluded_path_globs` defaults regardless, because the gap is well-known.

- **`# type: ignore` / `// @ts-ignore` not surfacing**: not observed in our sample. The `GENERAL_ESCAPE_RULES` regexes for these exist; they would fire if a 50-commit window included one. Phase 5 has a test that pins this behavior on a synthetic fixture (recommended).

- **`if quality_max_index_files: 4000` cap actually being hit**: TypeScript almost certainly tripped it, but the gate emits no log when caps fire (silent break). Phase 6 lists this as an out-of-scope finding (instrumentation gap, not a calibration gap).
