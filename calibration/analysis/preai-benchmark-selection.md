# A10: Pre-AI / mature production codebase selection

## Why this matters

Per user feedback, the original 8-repo dataset was contaminated:
- 40% of measured PRs were non-code (dependabot, translations, CI yaml, docs).
- fastapi (17/17) and grpc (3/3) contributed zero code-PR data.
- The repos skewed toward modern web frameworks where AI-assisted contributions are now common, mixing eras.

To establish a real "what production-quality code looks like" baseline, we need **codebases where the dominant authorship predates widespread AI assistance** (~late 2022 / early 2023). Those codebases reflect what survived decades of human-only review pressure and represent the conventions that work.

## Selection criteria

A candidate repo qualifies when:

1. **Born before 2020** so the bulk of code predates GitHub Copilot's GA (June 2021) and ChatGPT (Nov 2022).
2. **Active in 2024–2026** so we can pull recent merged PRs with a real diff.
3. **Uses GitHub PRs** (excludes `golang/go` which migrated to Gerrit).
4. **Language coverage compatible with the gate**: Python, JS/TS, Go, Rust, Ruby, PHP, Shell. Excludes pure-C codebases (Linux, Postgres, Redis, SQLite, curl, nginx, Vim) until the gate adds C support — see action item below.
5. **Rigorous review culture**: long-established maintainer review process, not a project where any contributor's PR merges easily.
6. **Code-dominant PRs available** when filtered through `list_merged_prs.sh` (≥3 source files, ≥50 added source lines).

## Candidate audit

I queried `repos/<gh>/pulls?state=closed&per_page=30` for each candidate and counted PRs with `merged_at` non-null:

| Repo | Lang | Born | Merged PRs (last 30 closed) | Verdict |
|---|---|---|---|---|
| `python/cpython` | Python (+ C internals the gate skips) | 1991 | 23 | ✅ qualified |
| `golang/go` | Go | 2009 | 0 (uses Gerrit, not GH PRs) | ❌ skip |
| `numpy/numpy` | Python (+ C wrappers) | 2006 | 23 | ✅ qualified |
| `apache/airflow` | Python | 2014 | 25 | ✅ qualified |
| `tokio-rs/tokio` | Rust | 2017 | 24 | ✅ qualified |
| `rust-lang/cargo` | Rust | 2014 | 28 | ✅ qualified |
| `prometheus/prometheus` | Go | 2012 | 24 | ✅ qualified |

## Final pre-AI benchmark set (11 repos, 4 languages)

User feedback: JS/TS was missing — that's what most web devs work in. Added 5 mature JS/TS repos.

### Backend / systems / data (6)

| Key | Repo | Lang | Born | Why |
|---|---|---|---|---|
| `cpython` | `python/cpython` | Python | 1991 | The reference Python implementation. Stable for decades. Rigorous PEP-driven review. |
| `numpy` | `numpy/numpy` | Python | 2006 | Foundational scientific Python; mature contributor base; stable conventions. |
| `airflow` | `apache/airflow` | Python | 2014 | Pre-AI Python infrastructure project under Apache governance. |
| `tokio` | `tokio-rs/tokio` | Rust | 2017 | Pre-AI Rust runtime; review-heavy due to memory-safety stakes. |
| `cargo` | `rust-lang/cargo` | Rust | 2014 | Rust's package manager; rust-lang core team review. |
| `prometheus` | `prometheus/prometheus` | Go | 2012 | Mature Go monitoring infrastructure. |

### Web / JS+TS (5)

| Key | Repo | Lang | Born | Why |
|---|---|---|---|---|
| `jquery` | `jquery/jquery` | JS | 2006 | Foundational JS library, mostly pre-2018 codebase, slow-changing core. |
| `react` | `facebook/react` | JS | 2013 | Heavily reviewed, dominant pre-AI core (the Hooks era 2018 is pre-Copilot). |
| `lodash` | `lodash/lodash` | JS | 2012 | Mature utility library, stable conventions, rigorous review. |
| `eslint` | `eslint/eslint` | JS | 2013 | Linter for the language; review-heavy contributor culture. |
| `svelte` | `sveltejs/svelte` | TS+JS | 2016 | Compiler-and-framework core predates Copilot; uses TypeScript. |

### Audited as not-suitable

| Repo | Reason |
|---|---|
| `golang/go` | Uses Gerrit, not GitHub PRs |
| `vuejs/vue` (Vue 2) | LTS only; 0 merged PRs in last 30 closed |
| `vuejs/core` (Vue 3) | Born 2020 — too AI-era |
| `vitejs/vite` | Born 2020 — borderline AI-era |

`list_merged_prs.sh` has all 11 aliased.

## What this benchmark will show

Once we run the calibrated gate on code-heavy PRs from these repos and on the original 8-repo set:
- **Pre-AI-era gate-error rate per LOC** — what mature, human-authored code triggers in the gate.
- **Compared to AI-era / mixed-era rate** (the original 8 repos restricted to recent code-heavy PRs) — does the gate fire more often per LOC on AI-era code?
- **Compared to LangChain-style fully-AI-era projects** — does the gap widen further?

If the pre-AI rate is meaningfully lower than the AI-era rate at the same PR size, that's evidence the user's slop-accumulation hypothesis is real. If the rates are comparable, the hypothesis isn't supported by the gate's structural detectors (which leaves it open as a question for richer detectors or human review).

## Action items

1. **A11**: Run the gate against 5 code-heavy merged PRs from each pre-AI repo (using the now-filtered `list_merged_prs.sh`). Build a comparison matrix vs the original 8-repo set's code-only subset.
2. **A12 (new)**: Extend `SOURCE_EXTENSIONS` to include `.c`, `.cpp`, `.cxx`, `.h`, `.hpp` and add a minimal C `SYMBOL_PATTERNS`. This unlocks Linux/Postgres/Redis/SQLite/curl/nginx/Vim as benchmark candidates and is the strongest pre-AI dataset available. Estimated effort: 2-3 hours for basic support; days for full parity. Track separately.
3. **Cross-language coverage gap**: even with the 6 selected repos, we have Python (3), Rust (2), Go (1) — no JS/TS pre-AI representative. Could add `vuejs/vue` (Vue 2 era, 2014–2020) or `jquery/jquery` (2006). Defer to A11 follow-up.

## Honest caveats

- "Pre-AI" is a continuous variable, not a step function. cpython, numpy, etc. all accept contributions from people who use AI assistance today. The baseline is "the codebase was largely written before AI assistance was viable, so the bulk of the surviving code is human-authored."
- A 2024 PR to cpython may itself have been AI-assisted. Filtering by author age in the project would tighten this, but the data is at the per-PR level — we'd be sampling "current contributors to a mature project," which is the cleanest filter we can apply without burning a week.
- Pre-AI vs AI-era is a hypothesis worth testing, not a settled fact. The gate's structural detectors may or may not detect any difference. A null result would itself be informative.
