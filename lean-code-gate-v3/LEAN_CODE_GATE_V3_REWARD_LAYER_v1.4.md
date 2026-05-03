# Lean Code Gate v3 Reward Layer v1.4: Production Implementation Spec

## Executive position

Lean Code Gate v3 already has the hard part: deterministic contracts, touched-scope mutation blocking, verification accounting, changed-code quality checks, repo-local state, and symmetric Claude/Codex hook wiring. The reward layer should therefore be a thin scoring and feedback layer over the existing gate, not a second gate, not a separate daemon, not an LLM judge, and not a leaderboard carnival where agents learn to perform for stickers like caffeinated raccoons.

This v1.4 design implements the reward layer inside `.agent/lean/lean_code_gate.py` with no runtime dependencies and no new hook events. It adds:

1. A pure `compute_reward()` function that scores a completed attempt from existing gate output.
2. A `score_assigned` event appended to the existing `.agent/lean/state/events.jsonl` log.
3. An optional Stop-hook Lean Challenge branch, disabled by default, that asks for one more lean pass only after correctness already passes.
4. A read-only `leaderboard` command that summarizes agent performance from score events.
5. A tamper-evident event hash chain, implemented as a compatibility-preserving extension of `log_event()`.

The implementation target is production feedback for LLM coding agents: reward small correct diffs, reuse existing code, punish fake-green shortcuts, never trade correctness for brevity, and keep every signal deterministic.

Architectural stance: the near-term product is a **challenge layer**, not a genuine ML reward model. The challenge layer counters instruction drift after long edits by reasserting the lean-production standard at Stop time, after correctness checks pass but before the agent declares completion. A genuine ML reward layer can come later only if logged challenge outcomes prove that the deterministic score correlates with accepted, production-quality code.


v1.4 keeps the v1.1 corrections: `specific_next_action()` ranks reuse and bloat suggestions by expected leanness gain rather than fixed rule order, and event ordering treats wall-clock time as best-effort while preserving deterministic append-chain order.

v1.4 keeps the v1.2 production fixes: chained event writes must hold a file lock across `last_event_hash + append`, reward telemetry and event-chain rollout are separate toggles with non-disruptive defaults, implementation is split across staged PRs, and Stop scoring, chain verification, and leaderboard tests must use real repo fixtures/events rather than synthetic-only payloads.

v1.4 keeps the v1.3 pre-implementation guards: reward scoring is skipped when `run_quality_gate_on_stop=false`, reward history/challenge/leaderboard readers must not use the bounded `events(root, limit=200)` helper, chain-enabled writes must be rejected with an actionable platform error when no supported lock exists, and Windows `:Zone.Identifier` sidecars must stay out of the repo and release artifacts.

v1.4 tightens the implementation plan without expanding scope: quality-disabled attempts carry `quality=None` instead of a fake passing quality shape, `read_score_events()` is introduced once in PR1 and reused by PR3, PR1 line targets are pressure rather than clever-compression bait, and PR1 is restricted to policy defaults, score helpers, and Stop score logging only.

## Source-aligned facts from the attached v3 gate

This spec is aligned to the attached v3 package as inspected, not to wishful architecture diagrams humanity keeps producing as a hobby.

Current source shape:

- `.agent/lean/lean_code_gate.py` is 2,335 lines.
- `tests/test_lean_code_gate.py` is 1,249 lines.
- `.agent/lean/policy.json` is 84 lines.
- `METHODOLOGY.md` documents the current eight-layer enforcement model.
- `.claude/settings.json` and `.codex/config.toml` both call the same script subcommands.
- The current test harness passes all 53 tests with the attached package.

Current gate rails the reward layer must reuse:

| Existing rail | Exact source hook |
|---|---|
| Policy merge | `DEFAULT_POLICY`, `policy(root)` |
| Repo-local state | `STATE_DIR = ".agent/lean/state"`, `state_dir(root)` |
| Active contract | `contract(root)`, `contract_path(root)` |
| Append-only event log | `log_event(root, event)`, `events(root, limit=200)` |
| Reward-history readers | New unbounded score-event readers; do not use the bounded `events(root, limit=200)` helper for prior scores, challenge caps, or leaderboard aggregation. |
| Diff budget delta | `delta(root, current_contract)` |
| Quality gate | `run_quality_gate(repo, base_ref, fail_on_warnings)` |
| Final Stop correctness checks | `final_errors(root, current_contract, active_policy)` |
| Hook emission | `emit(value)`, `deny(event, reason)` |
| Stop-hook integration point | `stop(payload)` |
| CLI parser | `parser()` and `main()` |
| Cross-agent hook symmetry | existing `stop`, `posttool`, `pretool` calls in Claude/Codex configs |

Important correction to the previous draft:

- Stop events are **not** currently logged.
- Mutation events are **not** currently stamped with `contract_declared_at`.
- Quality outcomes are **not** currently logged unless the Stop hook blocks through its emitted message.
- Therefore the reward layer must derive legacy attempt boundaries from `contract.declared_at` and append order, not wall-clock ordering, then write an explicit `score_assigned` event stamped with the copied `contract_declared_at` value.
- The Stop hook must not run `run_quality_gate()` twice. It should cache the quality result produced in the existing Stop pass and pass that result into `compute_reward()`.
- If `run_quality_gate_on_stop=false`, reward scoring is skipped. A valid Stop remains valid, but no `score_assigned` event is written and Lean Challenge cannot fire because the quality inputs are missing.
- The current `events(root, limit=200)` reader is intentionally bounded and is not acceptable for reward history, challenge caps, or leaderboard aggregation. v1.4 adds dedicated score-event readers that scan all JSONL lines and attach `_line_no` from append order.

## Non-negotiable design constraints

1. **No LLM in the scoring path.** Scoring consumes `final_errors()`, `run_quality_gate()`, `delta()`, the active contract, and prior `score_assigned` events only.
2. **Correctness is the floor.** A final-contract failure, missing verification, quality error, fake-green escape, duplicate block, or high-confidence reuse failure yields no reward credit.
3. **Quality must be evaluated before scoring.** If `run_quality_gate_on_stop=false`, the Stop hook may still pass through the existing gate, but reward scoring and Lean Challenge are skipped for that attempt.
4. **Touched-scope only.** The reward layer scores the same diff scope the gate already inspects. No repo-wide style scoring.
5. **No new hook event.** Existing Claude/Codex hook config remains valid because `stop` still calls the same script.
6. **No new mandatory state file.** Primary state remains `events.jsonl`. The v1.4 leaderboard prints JSON to stdout only; a future explicit `--output` flag may write a derived snapshot, but that is not part of the hot path.
7. **No exposed formula in agent feedback.** The hook message may show score, verdict, delta, and mechanical critique. It must not print weights, thresholds beyond the configured challenge threshold, or subscore decomposition.
8. **No agent self-evaluation.** Agents produce code; deterministic code scores it. Somehow this still needs saying.
9. **Rollout is explicit and staged.** `reward_enabled`, `reward_chain_enabled`, and `lean_challenge_enabled` all default to `false`. Telemetry, chain integrity, leaderboard, and challenge mode land separately.
10. **Reward rollout waits behind P1-P3 calibration.** The challenge branch should remain off until sensitive-input, failure-contract, and wrapper-value findings have measured false-positive rates below the duplicate-block baseline.
11. **Policy changes stay small.** New policy fields are booleans, integers, and narrow score thresholds only.
12. **No unlocked chained writes.** If `reward_chain_enabled` is true, `log_event()` must lock around the full `last_event_hash(path) → append line` critical section. Two concurrent Stop hooks producing the same `prev_hash` is not a charming distributed-systems anecdote; it is a broken chain.
13. **No bounded reward history.** Prior scores, challenge counts, and leaderboard aggregation must read all relevant score events, not just the last 200 JSONL lines.
14. **No unsupported chain platform.** If `reward_chain_enabled=true` and the runtime has no supported file-lock implementation, the hook/CLI must reject the configuration with an actionable message before writing.
15. **No Windows sidecar artifacts.** `*:Zone.Identifier` files must be excluded from repo commits, generated artifacts, and release packages.

## Evaluation strategy

The prototype should be evaluated as a behavior-shaping challenge layer before it is treated as a reward model.

### Hypothesis

Markdown standards decay during long editing loops. A deterministic Stop-time challenge should reduce sloppy final diffs by forcing one more lean pass when the code is correct but still bloated, duplicative, weakly verified, or near its declared budget.

The reasoning layer can add a second, semantic challenge signal before any true reward-model work. In the Property Partner Ops workflow, Repo Context Forge fixes the initial surface, GitNexus checks graph impact, and Claude Advisor then acts as a consolidated read-only challenger before preflight and again before commit. This can replace or supplement sub-agent delegation without making Lean Gate itself depend on another model.

### Phase 1: challenge layer

Goal: improve the final diff inside the current session.

- Keep challenge mode opt-in and repo-local.
- Challenge only after final correctness and quality gates pass.
- Emit one concrete next action, not a list of coaching advice.
- Cap challenge loops per contract.
- Allow correctness to win after the cap; preserve the low score in telemetry instead of trapping the agent.
- Keep Claude Advisor outside the hook hot path. When used, call it from the delivery workflow after GitNexus and before preflight, then again before commit for non-trivial diffs.

Success signals:

- challenged attempts usually shrink added/changed lines or remove duplicate/reuse findings on the next pass
- no increase in failed tests, missing verification, or out-of-scope edits after a challenge
- low false-positive rate from human review of challenge denials
- agents complete within the challenge cap without needing manual escape hatches

### Phase 2: reward telemetry

Goal: measure whether challenge feedback is useful before it blocks more broadly.

- Log score, verdict, critique, delta, budget usage, quality counts, and challenge count.
- Compare pre-challenge and post-challenge attempts for the same contract.
- Track whether human reviewers accepted the final diff without lean-code comments.
- Keep the score observational by default; do not rank agents operationally from early data.

Useful metrics:

- challenge improvement rate
- average added/changed-line reduction after challenge
- duplicate/reuse/bloat finding resolution rate
- verification preservation rate
- human-review agreement with the challenge outcome
- false challenge rate
- advisor agreement rate with Lean Gate and human review

### Advisor challenge signal

Claude Advisor should be modeled as an external semantic challenge event, not a deterministic rule result. It is useful because it can challenge issue interpretation, slice ownership, architecture fit, TDD proof, no-change surfaces, and reviewer coverage in ways the deterministic gate should not infer.

Example event:

```json
{
  "event": "advisor_challenge",
  "source": "claude-advisor",
  "phase": "pre-commit",
  "verdict": "fix-before-commit",
  "focus": ["minimality", "tdd", "regression-risk"],
  "codex_judgment": "accepted",
  "followup_mutation": true
}
```

Rules:

- Do not call Claude from Lean Gate hooks.
- Do not block deterministic Stop success solely because Claude is unavailable.
- Record advisor verdict, phase, focus tags, Codex judgment, and whether a follow-up mutation happened.
- Treat advisor output as evidence to validate against code, tests, GitNexus, reviewer text, and deterministic gate results.
- Use advisor agreement with later human review as an evaluation signal for future reward-model work.

### Phase 3: evaluation dataset

Goal: build a dataset that can later support model or prompt evaluation.

Each accepted/rejected attempt should be linkable to:

- prompt or task summary
- Lean Change Contract
- pre-challenge diff summary
- post-challenge diff summary when present
- verification outcomes
- gate findings and reward signal
- advisor challenge event and Codex judgment when present
- human review outcome or merge outcome when available

Do not store secrets, full environment dumps, raw remote URLs, or unnecessary command output in the reward event. If richer training data is needed, store it in an explicit offline evaluation artifact, not the Stop-hook hot path.

### Phase 4: ML reward model candidate

A genuine ML reward model is only justified after deterministic telemetry has enough reviewed examples to prove predictive value.

Use gate output as features, not as ground truth. The target label should come from accepted/rejected review outcomes, human lean-code judgments, or production-quality outcomes. The deterministic score can seed the dataset, but it must not become the only definition of quality.

Minimum bar before ML work:

- enough examples across multiple repos and task types
- measured correlation between score/challenge result and human acceptance
- known false-positive families documented and reduced
- no evidence that agents improve the score by weakening tests, over-declaring budgets, or avoiding necessary code
- stable rule IDs so model features do not shift under the dataset

## Implementation summary

### Files changed

| File | Change |
|---|---|
| `.agent/lean/lean_code_gate.py` | Add reward dataclass/helpers first, then locked event-chain helpers, then leaderboard subcommand, then challenge branch over staged PRs. |
| `.agent/lean/policy.json` | Add reward policy defaults, all disabled or observational by default. |
| `tests/test_lean_code_gate.py` | Add compact reward/event-chain tests. Recover test-line budget by replacing the explicit `TESTS = [...]` list with auto-discovery. |
| `.claude/skills/lean-code/SKILL.md` | Add short guidance: challenge feedback means reduce diff or reuse existing path; do not game the score. |
| `.agents/skills/lean-code/SKILL.md` | Same guidance as Claude skill. |
| `METHODOLOGY.md` | Add one section describing score logging and optional challenge mode. |

No `.claude/settings.json` or `.codex/config.toml` change is required for the core reward layer because both already invoke `lean_code_gate.py stop`.

### Implementation budget

Total target addition to `lean_code_gate.py` across the full rollout: **about 330-420 lines**. Do **not** ship that as one PR. The PR1 line band is pressure, not a hard compression target: a direct ~200-line telemetry patch is better than a 160-line origami sculpture nobody wants to debug. The gate is already near its core-size ceiling, and dumping scoring, hashing, leaderboard, and challenge logic into one diff would make review worse than the problem it is trying to solve.

| PR | Runtime target | Scope |
|---|---:|---|
| PR1: score telemetry only | 140-180 line pressure band; ~200 acceptable if direct | Policy defaults, `RewardSignal`, numeric score helpers, unbounded score-event reader for prior score lookup, `compute_reward()`, critique composition, and `score_assigned` payload/logging only when `reward_enabled=true` and quality was evaluated. No chain, no leaderboard, no challenge, no side quests. |
| PR2: locked hash chain | 55-85 lines | `canonical_json`, event-log lock, `last_event_hash`, `verify_event_chain`, `log_event()` chain patch. |
| PR3: read-only leaderboard | 70-100 lines | CLI parser branch, reuse PR1 score-event reader, deterministic summaries/rating, no challenge. |
| PR4: challenge mode | 35-60 lines | Stop deny branch, challenge cap, challenge-specific critique text. |

If total implementation exceeds 420 lines, cut or defer the leaderboard before touching the Stop hot path. If PR1 exceeds its pressure band but remains plain, tested, and isolated to score telemetry, keep the clarity and record the reason. A reward layer that bloats the gate has achieved satire, not engineering.

## Policy fields

Add these fields to `DEFAULT_POLICY` and `.agent/lean/policy.json`:

```json
{
  "reward_enabled": false,
  "lean_challenge_enabled": false,
  "lean_challenge_threshold_score": 72,
  "lean_challenge_max_iterations": 3,
  "reward_min_score_for_pass": 80,
  "reward_min_score_for_improved": 60,
  "reward_chain_enabled": false,
  "reward_chain_verify_on_read": false,
  "leaderboard_window_days": 30,
  "leaderboard_min_attempts_for_rating": 5
}
```

Field behavior:

| Field | Behavior |
|---|---|
| `reward_enabled` | If `true`, Stop logs `score_assigned` events after a contract exists and final/quality checks were evaluated. Does not block by itself. If `run_quality_gate_on_stop=false`, scoring is skipped and no score event is written. Default `false` for non-disruptive install. |
| `lean_challenge_enabled` | If `true`, Stop may deny completion for low-scoring but otherwise correct attempts. Default `false`. |
| `lean_challenge_threshold_score` | Minimum score for challenge-free completion when challenge mode is enabled. |
| `lean_challenge_max_iterations` | Maximum low-score Stop denials per contract. After the cap, Stop allows completion if correctness passes. |
| `reward_min_score_for_pass` | Score threshold for `PASS`. Hidden from hook feedback except as verdict. |
| `reward_min_score_for_improved` | Minimum score required for `IMPROVED` when current score beats prior score. |
| `reward_chain_enabled` | Adds `prev_hash` and `event_hash` to new events. Default `false`; enabling it changes event shape and therefore ships separately from telemetry. |
| `reward_chain_verify_on_read` | Makes leaderboard and final verification reject invalid chained logs. Default `false`; enable with or after `reward_chain_enabled`. |
| `leaderboard_window_days` | Default aggregation window for leaderboard CLI. |
| `leaderboard_min_attempts_for_rating` | Minimum score events before an agent receives a stable rating. |

Default policy has no reward side effects: no score event, no hash fields, no challenge. `reward_enabled` controls telemetry only, and telemetry requires `run_quality_gate_on_stop=true`. `reward_chain_enabled` controls event shape only. `lean_challenge_enabled` controls Stop denial only. These toggles are deliberately separate because tying them together is how a harmless telemetry rollout becomes a surprise production incident.

Policy should not expose weights. The constants live in source-local helpers, not in `policy.json`, because policy is operator-facing and hook-context-adjacent. Yes, agents can read source in a repo-local install. The point is not cryptographic secrecy; it is preventing the hook feedback from becoming a score-optimization prompt.

## Event schema

### `score_assigned`

When `reward_enabled` is true and `run_quality_gate_on_stop=true`, append after Stop has evaluated final correctness and quality for a root. The event is written whether the attempt passes or fails, as long as an active contract exists. Failed attempts receive `score: 0` and `verdict: "FAIL"`.

If `run_quality_gate_on_stop=false`, do not append `score_assigned`. That attempt is unscored, not failed. Creating a score from absent quality inputs would be the kind of tidy lie that later becomes an incident review.

```json
{
  "event": "score_assigned",
  "reward_version": "1",
  "repo_id": "<repo_identity repo_id>",
  "contract_declared_at": 1760000000.0,
  "contract_id": "<12-char hash>",
  "task_id": "<12-char hash>",
  "agent_id": "claude-code|codex|cursor|aider|unknown|operator override",
  "model_id": "<payload/env model or unknown>",
  "score": 84,
  "verdict": "PASS",
  "critique": "PASS: correct and lean. All quality checks passed. Used 18/120 added lines across 2/3 files. Largest growth is src/app.py (+14); keep future changes at that boundary.",
  "challenge_issued": false,
  "challenge_count": 0,
  "final_error_count": 0,
  "quality_error_count": 0,
  "quality_warning_count": 1,
  "delta": {
    "added": 18,
    "deleted": 2,
    "changed": 20,
    "files": ["src/app.py", "tests/test_app.py"]
  },
  "budget": {
    "max_files": 3,
    "max_added_lines": 120,
    "max_changed_lines": 240
  },
  "quality_summary": {
    "changedFilesCount": 2,
    "sourceFilesCount": 1,
    "reuseFindingCount": 0,
    "topReuseScore": 0,
    "bloatTotalAdded": 18,
    "bloatTotalDeleted": 2
  }
}
```

Do not log subscore breakdown. Do not log raw full contract text in the score event; contract text already exists in the `contract_declared` event and `contract.json`. The score event should be compact and safe to aggregate.

### Contract ID

```python
def contract_id(current_contract: dict[str, object]) -> str:
    material = {
        "repo_id": str(current_contract.get("repo_id") or ""),
        "declared_at": float(current_contract.get("declared_at") or 0),
        "intent": str(current_contract.get("intent") or ""),
        "scope": sorted(str(item) for item in current_contract.get("scope") or []),
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()[:12]
```

### Task ID

Task ID groups comparable attempts across agents without reading branch names, remotes, or credentials.

```python
def task_id(current_contract: dict[str, object]) -> str:
    material = {
        "intent": re.sub(r"\s+", " ", str(current_contract.get("intent") or "").strip().lower()),
        "scope": sorted(str(item) for item in current_contract.get("scope") or []),
        "task_type": str(current_contract.get("task_type") or "unknown"),
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()[:12]
```

Do not include `repo_root`, `git_common_dir`, remote URL, username, branch, or model in `task_id`.

## Reward signal type

Add near the existing dataclasses:

```python
@dataclass(frozen=True)
class RewardSignal:
    score: int
    verdict: str
    critique: str
    challenge_issued: bool = False
```

Allowed verdicts:

| Verdict | Meaning |
|---|---|
| `FAIL` | Final correctness or quality floor failed. Score must be 0. |
| `PASS` | Score meets `reward_min_score_for_pass`. |
| `IMPROVED` | Score is better than prior score for same contract and meets `reward_min_score_for_improved`. |
| `MATCHED` | Score is within ±2 of prior best for same contract. |
| `REGRESSED` | Score is lower than prior best for same contract. |
| `LOW_PASS` | Correctness passed but score is below pass band and no prior comparison improves it. |

`LOW_PASS` matters because a correct but bloated attempt is not a failure after challenge cap. It is a successful completion with poor reward. Calling it `PASS` would let mediocrity wear a fake mustache.

## Correctness floor

The scoring function receives final errors and quality output, but only after the quality gate has actually run. Stop integration must track this explicitly.

### Quality-disabled behavior

Reward scoring requires `run_quality_gate_on_stop=true`. If the existing policy disables the quality gate on Stop:

- Stop behavior remains governed by the existing final checks.
- `maybe_log_reward()` returns no reward.
- No `score_assigned` event is appended.
- Lean Challenge is skipped even if `lean_challenge_enabled=true`.

This avoids the ugly failure mode where a valid Stop receives score `0` only because `quality.hardRules` is absent. It also avoids the opposite lie: treating missing quality analysis as evidence that quality passed. Humanity has already produced enough dashboards built from missing data.

Do **not** create a fake passing quality dict. Stop result bundles should carry `quality=None` with `quality_evaluated=False` when the quality gate did not run. This keeps the implementation lean and prevents placeholder data from drifting into scoring later, because placeholder data has a long and embarrassing career in production systems.

### Floor function

```python
REQUIRED_REWARD_HARD_RULES = ("cleanup", "anticipateConsequences", "noDuplication", "codeVolume")


def correctness_floor(final_errors: list[str], quality: dict[str, object]) -> bool:
    if final_errors:
        return False
    if not bool(quality.get("ok")):
        return False
    hard = quality.get("hardRules") if isinstance(quality.get("hardRules"), dict) else {}
    required = REQUIRED_REWARD_HARD_RULES
    return all(bool((hard.get(name) or {}).get("passed")) for name in required)
```

Notes:

- `quality.ok` is already strict when warnings are promoted.
- `hardRules` values are dicts shaped like `{"passed": bool, "checks": [...]}`, not booleans.
- Final contract errors must be included because missing verification and out-of-scope files are not represented in `run_quality_gate()`.
- `correctness_floor()` is intentionally boring; the quality-disabled decision happens before calling `compute_reward()`.

If the floor fails after quality was evaluated:

```python
RewardSignal(score=0, verdict="FAIL", critique=mechanical_fail_critique(final_errors, quality))
```

No leanness, reuse, or discipline points are computed after failure. This prevents “it was a tiny unsafe diff” from becoming a reward, because that sentence is how software incidents get postmortems.

## Scoring model

The score is a 0-100 integer. It has three internal terms in tension:

| Term | Max | Purpose |
|---|---:|---|
| Leanness | 40 | Reward staying materially under declared budget and deleting when possible. |
| Reuse | 30 | Reward reuse-path discipline and penalize reuse warnings. |
| Production discipline | 30 | Reward verification-shaped, warning-light, contract-consistent changes. |

Only the final score and verdict are emitted. Subscores are testable internally but not logged or shown in challenge feedback.

### Numeric helpers

```python
def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
```

### Leanness, 0-40

Inputs:

- `delta.added`
- `delta.deleted`
- `delta.changed`
- `len(delta.files)`
- `contract.max_added_lines`
- `contract.max_changed_lines`
- `contract.max_files`
- `quality.bloat.totalAdded`
- `quality.bloat.totalDeleted`

Scoring:

```python
def leanness_points(delta_value: dict[str, object], current_contract: dict[str, object], quality: dict[str, object]) -> int:
    added = safe_int(delta_value.get("added"))
    deleted = safe_int(delta_value.get("deleted"))
    changed = safe_int(delta_value.get("changed"))
    files = len(delta_value.get("files") or [])

    max_added = max(1, safe_int(current_contract.get("max_added_lines"), 1))
    max_changed = max(1, safe_int(current_contract.get("max_changed_lines"), 1))
    max_files = max(1, safe_int(current_contract.get("max_files"), 1))

    added_use = added / max_added
    changed_use = changed / max_changed
    file_use = files / max_files
    add_heavy = added / max(1, deleted + 1)

    points = 40.0
    points -= 14.0 * clamp((added_use - 0.35) / 0.65)
    points -= 8.0 * clamp((changed_use - 0.50) / 0.50)
    points -= 8.0 * clamp((file_use - 0.50) / 0.50)
    points -= 8.0 * clamp((add_heavy - 2.0) / 6.0)

    bloat = quality.get("bloat") if isinstance(quality.get("bloat"), dict) else {}
    if safe_int(bloat.get("totalDeleted")) > safe_int(bloat.get("totalAdded")):
        points += 4.0

    return max(0, min(40, round(points)))
```

Rationale:

- The reward starts penalizing before the contract limit is hit. The hard gate already blocks exceeding the contract; reward should shape better behavior inside the limit.
- `changed` matters because a huge rewrite with equal added/deleted lines is still expensive.
- Net shrink gets a small bonus, but not enough to reward deleting useful code.

### Reuse, 0-30

Inputs:

- `quality.reuseFindings[]`
- `contract.reuse_path`
- `contract.no_reuse_reason`
- `contract.task_type`

Scoring:

```python
def reuse_points(quality: dict[str, object], current_contract: dict[str, object]) -> int:
    findings = quality.get("reuseFindings") if isinstance(quality.get("reuseFindings"), list) else []
    errors = [item for item in findings if isinstance(item, dict) and item.get("severity") == "error"]
    warnings = [item for item in findings if isinstance(item, dict) and item.get("severity") == "warning"]

    if errors:
        return 0

    points = 22
    points -= min(18, 6 * len(warnings))

    task_type = str(current_contract.get("task_type") or "unknown")
    if task_type in {"bugfix", "feature", "refactor"}:
        if meaningful(current_contract.get("reuse_path")):
            points += 8
        elif meaningful(current_contract.get("no_reuse_reason")):
            points += 4
    else:
        points += 4

    return max(0, min(30, points))
```

Rationale:

- A high-confidence reuse error already fails the quality floor, but keeping the hard zero here makes direct unit tests obvious.
- Weaker reuse warnings reduce score without blocking.
- Full code work already requires `reuse_path` or `no_reuse_reason`; reward reinforces that leading behavior.

### Production discipline, 0-30

Inputs:

- `quality.warnings[]`
- `quality.checks[]`
- `delta`
- contract flags and verification declarations
- prior `verify_passed` event after `declared_at`

Scoring:

```python
def discipline_points(
    root: Path,
    quality: dict[str, object],
    current_contract: dict[str, object],
    delta_value: dict[str, object],
    prior_events: list[dict[str, object]],
) -> int:
    warnings = quality.get("warnings") if isinstance(quality.get("warnings"), list) else []
    points = 30
    points -= min(15, 5 * len(warnings))

    changed = safe_int(delta_value.get("changed"))
    max_changed = max(1, safe_int(current_contract.get("max_changed_lines"), 1))
    if changed >= int(max_changed * 0.90):
        points -= 5

    files = [str(path) for path in delta_value.get("files") or []]
    new_files = sorted(path for path in added_file_paths(root) if path in files)
    if new_files and not current_contract.get("allow_new_files"):
        points -= 10

    declared_at = float(current_contract.get("declared_at") or 0)
    wanted = [re.sub(r"\s+", " ", str(cmd).strip()) for cmd in current_contract.get("verify") or []]
    passed = [
        re.sub(r"\s+", " ", str(event.get("command", "")).strip())
        for event in prior_events
        if event.get("event") == "verify_passed" and float(event.get("time", 0)) >= declared_at
    ]
    if wanted and any(want in got or got in want for want in wanted for got in passed):
        points += 4

    if minimal_preflight(current_contract) and safe_int(delta_value.get("added")) <= 20:
        points += 3

    return max(0, min(30, points))
```

Rationale:

- Warning count matters because warnings are exactly the calibrated “not a hard fail, but still suspicious” channel.
- Near-budget usage is penalized even if technically allowed.
- Verification passing gets a small bonus, not a substitute for final correctness.
- Minimal micro-fixes receive a small bonus when they stay genuinely micro.

## Reward-history readers and verdict calculation

Prior score comparison is scoped to the same contract, not merely the same task. Do **not** use `events(root)` here. The current helper reads only the tail of the log by default (`limit=200`), which is fine for lightweight context but wrong for reward history, challenge caps, and leaderboard queries. A long coding session should not erase the cap just because humans invented pagination and then forgot it existed.

### Score-event readers

Use dedicated readers that scan every line and attach append-order metadata:

```python
def read_score_events(root: Path) -> list[dict[str, object]]:
    path = events_path(root)
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("event") != "score_assigned":
            continue
        row = dict(item)
        row["_line_no"] = line_no
        out.append(row)
    return out


def score_events_for_contract(root: Path, current_contract: dict[str, object]) -> list[dict[str, object]]:
    wanted_contract_id = contract_id(current_contract)
    declared_at = float(current_contract.get("declared_at") or 0)
    rows = []
    for event in read_score_events(root):
        if str(event.get("contract_id") or "") == wanted_contract_id:
            rows.append(event)
            continue
        # Compatibility fallback for early score events before contract_id existed.
        if not event.get("contract_id") and float(event.get("contract_declared_at") or 0) == declared_at:
            rows.append(event)
    return rows
```

Float equality is acceptable only as the compatibility fallback because `contract_declared_at` is copied from the same contract object. New score events should carry `contract_id` so the normal path is string equality.

### Prior scores

```python
def prior_scores_for_contract(contract_score_events: list[dict[str, object]]) -> list[int]:
    return [
        safe_int(event.get("score"))
        for event in contract_score_events
        if isinstance(event.get("score"), int)
    ]
```

Verdict logic:

```python
def reward_verdict(score: int, previous: list[int], active_policy: dict[str, object]) -> str:
    pass_min = safe_int(active_policy.get("reward_min_score_for_pass"), 80)
    improved_min = safe_int(active_policy.get("reward_min_score_for_improved"), 60)

    if score >= pass_min:
        return "PASS"
    if not previous:
        return "LOW_PASS"

    best = max(previous)
    if score > best + 2 and score >= improved_min:
        return "IMPROVED"
    if abs(score - best) <= 2:
        return "MATCHED"
    return "REGRESSED"
```

## Mechanical critique

Critique text is deterministic and composed only from gate outputs. No LLM call. No free-form “coach.” Nobody needs a second robot hallucinating therapy into a Stop hook.

Critique format:

```text
{VERDICT}: {score}.
{quality_sentence} Used {added}/{max_added_lines} added lines and {changed}/{max_changed_lines} changed lines across {files}/{max_files} files.
{specific_suggestion}
```

Suggestion priority:

1. First final error, if any.
2. First quality error, if any.
3. Build lean-action candidates from reuse warnings and bloat files, then choose the candidate with the largest expected leanness gain. Do not surface reuse before bloat by rule order; a large net-growth file should beat a mild reuse warning.
4. Otherwise, “No specific lean issue detected.”

Implementation rule for `specific_next_action()`: final and quality errors outrank leanness because they affect correctness. After correctness is clear, rank reuse and bloat candidates by expected gain, then use deterministic tie-breakers: higher severity, higher raw reuse score or larger `netGrowth`, then lexical path/name. This prevents a large diff from being pointed at a cute little reuse nit while the real bloat sits there eating the furniture.

Example:

```text
LOW_PASS: 66.
All hard quality checks passed, but 2 warning(s) remain. Used 92/120 added lines and 140/240 changed lines across 3/3 files.
Largest growth is src/importer.py (+71); reduce that boundary or extend an existing helper before adding more surface.
```

The challenge message wraps this critique but does not reveal formula internals:

```text
Lean Challenge 1/3: LOW_PASS: 66.
All hard quality checks passed, but 2 warning(s) remain. Used 92/120 added lines and 140/240 changed lines across 3/3 files.
Largest growth is src/importer.py (+71); reduce that boundary or extend an existing helper before adding more surface.
```

Do not include “you can stop here if you disagree” in a `deny()` message. `deny()` blocks Stop, so that sentence would be a lie wearing a customer-success hoodie. Autonomy comes from the policy flag being off by default and the challenge cap.

## `compute_reward()` signature

```python
def compute_reward(
    root: Path,
    current_contract: dict[str, object],
    quality: dict[str, object],
    delta_value: dict[str, object],
    final_error_values: list[str],
    prior_events: list[dict[str, object]],
    contract_score_events: list[dict[str, object]],
    active_policy: dict[str, object],
) -> RewardSignal:
    if not correctness_floor(final_error_values, quality):
        return RewardSignal(0, "FAIL", fail_critique(final_error_values, quality, delta_value, current_contract))

    score = (
        leanness_points(delta_value, current_contract, quality)
        + reuse_points(quality, current_contract)
        + discipline_points(root, quality, current_contract, delta_value, prior_events)
    )
    score = max(0, min(100, int(score)))
    verdict = reward_verdict(score, prior_scores_for_contract(contract_score_events), active_policy)
    return RewardSignal(score, verdict, reward_critique(verdict, score, quality, delta_value, current_contract))
```

The function is pure except for receiving `root` only because `discipline_points()` currently needs `added_file_paths(root)`. If the implementation wants stricter purity, compute `new_files` once in Stop and pass it in. That is cleaner but adds a tiny adapter object. Pick the smaller patch after coding.

`contract_score_events` must come from `score_events_for_contract(root, current_contract)`, not `events(root)`. This is the difference between a real cap and a cap that vanishes after 200 log lines, which would be funny only if you enjoy debugging reward systems in production.

## Stop-hook integration

The current `stop(payload)` loops roots, runs `final_errors()`, optionally runs `run_quality_gate()`, and denies if any errors exist. The reward layer should restructure that loop without changing existing behavior when reward is disabled.

### Stop result bundle

Use a small local dict or dataclass. A dataclass is cleaner but costs lines; a dict is fine.

Fields:

```python
{
  "root": root,
  "contract": current_contract,
  "policy": active_policy,
  "final_errors": errors_before_quality,
  "quality": quality_or_none,
  "quality_evaluated": bool,
  "delta": delta_value,
  "contract_score_events": list[dict],
  "reward": RewardSignal | None,
  "score_event": dict | None
}
```

### Stop pseudocode

```python
def stop(payload: dict[str, object]) -> None:
    roots = stop_roots(payload)
    if not roots:
        return

    if payload.get("stop_hook_active"):
        # Existing continuation behavior remains unchanged. Do not score here.
        ...
        return

    results = []
    all_errors = []

    for root in roots:
        current_contract = contract(root)
        active_policy = policy(root)
        errors = final_errors(root, current_contract, active_policy)
        quality: dict[str, object] | None = None
        quality_evaluated = False

        if active_policy["run_quality_gate_on_stop"]:
            fail_warnings = bool(active_policy["fail_on_quality_warnings"]) and not (current_contract or {}).get("allow_quality_warnings")
            quality = run_quality_gate(root, str((current_contract or {}).get("base_ref") or "") or None, fail_warnings)
            quality_evaluated = True
            if not quality["ok"]:
                errors.extend(["Quality gate failed: " + error for error in quality["errors"]])

        delta_value = delta(root, current_contract) if current_contract else {"files": [], "added": 0, "deleted": 0, "changed": 0}
        contract_scores = score_events_for_contract(root, current_contract) if current_contract else []
        results.append({
            "root": root,
            "contract": current_contract,
            "policy": active_policy,
            "errors": errors,
            "quality": quality,
            "quality_evaluated": quality_evaluated,
            "delta": delta_value,
            "contract_score_events": contract_scores,
        })
        all_errors.extend(f"{root}: {error}" if len(roots) > 1 else error for error in errors)

    # Existing failure behavior wins. Score can still be logged for active contracts
    # only when the quality gate actually ran. If quality was disabled, the attempt
    # is unscored rather than failed.
    for item in results:
        maybe_log_reward(payload, item, force_fail=bool(item["errors"]))

    if all_errors:
        deny("Stop", existing_final_failure_message(all_errors))
        return

    challenges = []
    for item in results:
        challenge = maybe_issue_challenge(payload, item)
        if challenge:
            challenges.append(challenge)

    if challenges:
        deny("Stop", "\n\n".join(challenges[:3]))
```

In actual implementation, combine `maybe_log_reward()` and `maybe_issue_challenge()` so the event is logged exactly once with the final `challenge_issued` boolean.

`maybe_log_reward()` must short-circuit when `item["quality_evaluated"]` is false. Do not write a zero score, do not write a low-pass score, and do not issue a challenge. Missing quality input is not evidence of failure or success; it is just missing input, a concept dashboards keep pretending not to understand.

### Challenge decision

```python
def challenge_count(contract_score_events: list[dict[str, object]]) -> int:
    return sum(1 for event in contract_score_events if bool(event.get("challenge_issued")))
```

Decision:

```python
prior_challenges = challenge_count(item["contract_score_events"])
threshold = safe_int(active_policy.get("lean_challenge_threshold_score"), 72)
max_challenges = safe_int(active_policy.get("lean_challenge_max_iterations"), 3)
should_challenge = (
    bool(active_policy.get("lean_challenge_enabled"))
    and reward.score < threshold
    and reward.verdict != "FAIL"
    and prior_challenges < max_challenges
)
```

If `should_challenge` is true, log the score event with:

```json
"challenge_issued": true,
"challenge_count": prior_challenges + 1
```

Then deny Stop with the mechanical critique.

If false, log with `challenge_issued: false` and allow Stop if there are no existing errors.

## Event hash chain

### Goal

Make tampering with `events.jsonl` visible before leaderboard aggregation and before final verification events are trusted, without adding secrets, daemons, HMAC keys, or other ritual objects humans use to make simple systems impossible to maintain.

### Compatibility rule

Old unchained events remain readable. The chain starts at the first event written by a chain-enabled runtime.

### Event ordering and timestamps

Canonical event order is JSONL append order plus the `prev_hash` chain. Wall-clock `time` is retained for human display and approximate window filtering only; it must not be used as the source of truth for chain order or pairwise rating order. NTP adjustments, container clock drift, and local clock changes can make wall time move oddly, because apparently even clocks require adult supervision.

Each new event should also include `monotonic_ns = time.monotonic_ns()`. Use it only as a same-runtime diagnostic hint; across process restarts and machines, append line number remains the deterministic sequence.

### Canonical JSON

```python
def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

### Last hash

```python
def last_event_hash(path: Path) -> str:
    if not path.exists():
        return ""
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("event_hash"), str):
            return str(item["event_hash"])
    return ""
```

### Required file lock

Chained writes require a lock around the entire critical section:

```text
read last event_hash → build event with prev_hash → compute event_hash → append line
```

Locking only the append is not enough. Two concurrent Stop hooks can both read the same previous hash, compute different next events, and append two lines with the same `prev_hash`. The JSONL file would look append-only while the chain is already forked. Delightful, in the same way a cracked foundation is delightful.

Use a state-local lock file, no dependency:

```python
@contextlib.contextmanager
def event_log_lock(root: Path):
    lock_path = state_dir(root) / "events.jsonl.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        if os.name != "posix":
            raise RuntimeError("reward event chaining requires a file lock on this platform")
        import fcntl
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

If Windows support is required, PR2 may add a small stdlib `msvcrt` branch. Do not ship chain-enabled writes on a platform where the lock helper is a no-op. PR1 may log unchained `score_assigned` events without this lock because it does not read a previous hash.

### Unsupported-platform policy

Chain support must be rejected before a write path reaches `log_event()`:

```python
def event_log_lock_supported() -> bool:
    if os.name == "posix":
        return True
    # Optional PR2 extension may return True for a real stdlib msvcrt lock.
    return False


def reward_chain_platform_error(active_policy: dict[str, object]) -> str:
    if active_policy.get("reward_chain_enabled") and not event_log_lock_supported():
        return (
            "reward_chain_enabled=true requires a supported file lock. "
            "Disable reward_chain_enabled on this platform or implement the stdlib msvcrt lock branch."
        )
    return ""
```

Hook and CLI write paths must check this once after policy load. For Stop, reject with `deny("Stop", reason)` before appending any event. For CLI commands that write, return JSON/text error with nonzero exit. `event_log_lock()` may keep the same message as a defensive assertion, but the normal production path must not discover platform support by crashing halfway through `log_event()`. That is not validation; that is archaeology with stack traces.

### `log_event()` patch

Replace current `log_event()` with a chain-aware implementation that only locks when chain mode is enabled:

```python
def _append_event_line(path: Path, item: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, sort_keys=True) + "\n")


def log_event(root: Path, event: dict[str, object]) -> None:
    path = events_path(root)
    active_policy = policy(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    if active_policy.get("reward_chain_enabled", False):
        with event_log_lock(root):
            item = {"time": time.time(), "monotonic_ns": time.monotonic_ns(), **event}
            item["prev_hash"] = last_event_hash(path)
            core = canonical_json(item)
            item["event_hash"] = hashlib.sha256(core.encode("utf-8")).hexdigest()
            _append_event_line(path, item)
        return

    item = {"time": time.time(), "monotonic_ns": time.monotonic_ns(), **event}
    _append_event_line(path, item)
```

Once `reward_chain_enabled` is turned on for a repo, do not turn it off casually. Verification treats unchained events after chain start as invalid. Legacy unchained events before the first hashed event remain valid.

### Chain verification

```python
def verify_event_chain(root: Path) -> tuple[bool, str]:
    path = events_path(root)
    if not path.exists():
        return True, ""
    previous = ""
    chain_started = False
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return False, f"events.jsonl line {line_no} is not valid JSON"
        if not isinstance(item, dict):
            return False, f"events.jsonl line {line_no} is not an object"
        has_hash = isinstance(item.get("event_hash"), str)
        if not has_hash and not chain_started:
            continue
        if not has_hash:
            return False, f"events.jsonl line {line_no} is missing event_hash after chain start"
        chain_started = True
        core = dict(item)
        event_hash = str(core.pop("event_hash"))
        expected_prev = previous
        actual_prev = str(core.get("prev_hash") or "")
        if actual_prev != expected_prev:
            return False, f"events.jsonl line {line_no} prev_hash mismatch"
        expected = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
        if event_hash != expected:
            return False, f"events.jsonl line {line_no} event_hash mismatch"
        previous = event_hash
    return True, ""
```

Implementation detail: copy before `pop()` if the parsed event is reused. Shared mutable dicts are not clever; they are just future archaeology.

### Where verification runs

- `leaderboard` verifies when `reward_chain_verify_on_read` is true or `--verify-chain` is passed.
- `final_errors()` verifies before trusting `verify_passed` events only when `reward_chain_verify_on_read` is true and chained events exist.
- `events(root, limit)` remains a permissive reader by default to avoid breaking old flows.

For `final_errors()`, add a small guard before collecting verification events:

```python
if active_policy.get("reward_chain_verify_on_read"):
    ok, reason = verify_event_chain(root)
    if not ok:
        errors.append("Lean event log failed integrity check: " + reason)
        return errors
```

This makes forged verification events detectable once the chain is active.

## Agent and model identity

### Agent ID resolution

```python
def resolve_agent_id(payload: dict[str, object]) -> str:
    override = os.environ.get("LEAN_CODE_GATE_AGENT_ID")
    if override:
        return re.sub(r"[^A-Za-z0-9_.:-]+", "-", override.strip())[:80] or "unknown"
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude-code"
    if os.environ.get("CODEX_SANDBOX") or os.environ.get("CODEX_ENV_PWD"):
        return "codex"
    if os.environ.get("CURSOR_AGENT") == "1":
        return "cursor"
    if "aider" in str(os.environ.get("_") or "").lower():
        return "aider"
    return "unknown"
```

Do not walk parent process trees. It is not portable and is not worth the lines. The override exists for CI and wrappers.

### Model ID resolution

```python
def resolve_model_id(payload: dict[str, object]) -> str:
    for key in ("model", "model_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"[^A-Za-z0-9_.:/@+-]+", "-", value.strip())[:120]
    for env_key in ("LEAN_CODE_GATE_MODEL", "ANTHROPIC_MODEL", "OPENAI_MODEL", "CODEX_MODEL"):
        value = os.environ.get(env_key)
        if value:
            return re.sub(r"[^A-Za-z0-9_.:/@+-]+", "-", value.strip())[:120]
    return "unknown"
```

This is attribution, not authentication. Leaderboards using self-reported IDs should be treated as local telemetry, not a notarized horse race.

## Leaderboard command

Add CLI:

```bash
python3 -B -S .agent/lean/lean_code_gate.py leaderboard --repo "$PWD" --window-days 30 --json
```

Default behavior prints JSON to stdout and writes nothing. A future explicit `--output` flag may be added after PR3 if operators want snapshots, but v1.4 does not need it.

### Parser

```python
leaderboard_parser = sub.add_parser("leaderboard")
leaderboard_parser.add_argument("--repo", default=os.getcwd())
leaderboard_parser.add_argument("--window-days", type=int, default=0)
leaderboard_parser.add_argument("--json", action="store_true")
leaderboard_parser.add_argument("--verify-chain", action="store_true")
```

In `main()`:

```python
elif args.cmd == "leaderboard":
    return leaderboard_command(args)
```

### Aggregation inputs

Use only `score_assigned` events read by `read_score_events(root)`, which scans the full JSONL file. Do not call `events(root)` here; the default tail limit silently drops older attempts and makes leaderboards lie with a straight face.

Filter:

- event is valid JSON object
- parser attaches `_line_no` from JSONL append order before aggregation
- `event == "score_assigned"`
- `score` is int or numeric
- within window if requested, using wall-clock `time` as best-effort filtering only
- `agent_id` exists, fallback `unknown`
- `task_type` can be inferred from event `task_id`; if absent in early events, group under `unknown`

### Output schema

```json
{
  "ok": true,
  "repo": "/path/to/repo",
  "windowDays": 30,
  "events": 42,
  "generatedAt": 1760000000.0,
  "agents": [
    {
      "agentId": "claude-code",
      "attempts": 16,
      "contracts": 9,
      "medianScore": 81,
      "p10Score": 63,
      "p90Score": 94,
      "passRate": 0.69,
      "challengeRate": 0.19,
      "failRate": 0.06,
      "medianAddedLines": 24,
      "medianChangedLines": 36,
      "medianFiles": 2,
      "attemptsPerContract": 1.33,
      "rating": 1028,
      "ratingStatus": "rated"
    }
  ]
}
```

### Rating algorithm

Keep it dependency-free and stable. Full Bradley-Terry and IRT can wait until enough data exists; jamming a statistics thesis into a hook-adjacent script is how lean tools become obese.

Use deterministic pairwise task comparisons:

1. Group score events by `task_id`.
2. For every task with at least two agents, compare each pair’s best score on that task.
3. A wins if `score_a >= score_b + 5`; ties are ignored.
4. Rating starts at 1000.
5. For each pairwise win, update with a simple Elo step using `k = 16`, sorted by `(task_id, _line_no, agent_id)` for determinism. Do not sort by wall-clock `time`.
6. Agents with fewer than `leaderboard_min_attempts_for_rating` attempts get `ratingStatus: "insufficient-data"` and rating `null`.

This is not mathematically perfect. It is comprehensible, testable, and 50 lines. That wins for v3. Add Bradley-Terry later only if calibration shows the simple rating hides real differences.

## Tests to add

The current test file is already at the soft ceiling. Add reward tests compactly and reclaim lines by replacing the explicit `TESTS = [...]` block with auto-discovery:

```python
TESTS = [
    value for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
]
```

This recovers roughly one screen of boilerplate and lets reward tests land without pretending line budgets are decorative confetti.

Testing rule: pure scoring helpers may use direct synthetic dictionaries. Stop scoring, chain verification, and leaderboard must use real repo fixtures/events. Synthetic-only tests for those paths are not enough, because the bugs will live in subprocess wiring, state files, append order, and CLI parsing, as bugs traditionally do while smirking.

Add tests by PR:

### PR1 tests: reward telemetry only

1. `test_reward_correctness_floor_zero`
   - Direct unit test.
   - Build `quality={"ok": False, ...}` and `final_errors=[...]`.
   - Assert score `0`, verdict `FAIL`.

2. `test_reward_reuse_warning_reduces_score_without_failure`
   - Direct unit test of `reuse_points()` or `compute_reward()` with a synthetic warning finding.
   - Assert lower score than clean quality but verdict not `FAIL` when correctness floor passes.

3. `test_reward_small_verified_diff_passes`
   - Use `repo_fixture()`.
   - Declare a real contract.
   - Make a small production-shaped change plus verification event.
   - Build quality via `run_quality_gate()`.
   - Assert `compute_reward().score >= reward_min_score_for_pass` and verdict `PASS`.

4. `test_stop_logs_score_event_when_reward_enabled`
   - Full subprocess Stop path, not a helper-only test.
   - Enable `reward_enabled` in repo policy.
   - Declare contract, make small verified change, run `stop`.
   - Assert `events.jsonl` contains one `score_assigned` event with repo id, score, verdict, delta, and no raw full contract.

5. `test_stop_does_not_log_score_when_reward_disabled`
   - Full subprocess Stop path.
   - Leave default policy with `reward_enabled: false`.
   - Assert Stop behavior and event shape match pre-reward expectations.

6. `test_stop_skips_score_when_quality_gate_disabled`
   - Full subprocess Stop path.
   - Enable `reward_enabled: true` but set `run_quality_gate_on_stop: false`.
   - Assert Stop can pass existing final checks but no `score_assigned` event is written and no challenge is attempted.

### PR2 tests: locked chain

7. `test_event_chain_detects_tampering`
   - Use `repo_fixture()` and real `log_event()` writes with `reward_chain_enabled: true`.
   - Write two events.
   - Modify the first line’s event payload.
   - Assert `verify_event_chain()` returns false with mismatch reason.

8. `test_event_chain_locked_append_preserves_order`
   - Use real `log_event()` writes with chain enabled.
   - Exercise two concurrent append attempts with multiprocessing if feasible; otherwise simulate contention by holding the lock while a second writer waits in a subprocess.
   - Assert the final chain verifies and no two adjacent hashed events share a stale `prev_hash`.

9. `test_chain_enabled_rejects_unsupported_lock_platform`
   - Unit-test the platform guard with the lock-support probe forced false.
   - Assert `reward_chain_enabled=true` returns the actionable configuration error before any event write is attempted.

### PR3 tests: leaderboard

10. `test_leaderboard_summarizes_score_events`
   - Use `repo_fixture()` and real `log_event()` score events for two agents and two tasks.
   - Run `leaderboard --json` through the CLI.
   - Assert both agents appear and insufficient/rated status follows policy.

11. `test_leaderboard_rejects_tampered_chain_when_verify_enabled`
   - Use real chained events.
   - Tamper with one line.
   - Run `leaderboard --verify-chain --json`.
   - Assert nonzero exit or `ok: false` with integrity reason.

12. `test_leaderboard_reads_all_score_events_not_tail_200`
   - Write more than 200 real `score_assigned` events.
   - Run `leaderboard --json`.
   - Assert early score events still contribute to attempt counts and agent summaries.

### PR4 tests: challenge mode

13. `test_lean_challenge_denies_low_score_when_enabled`
    - Repo policy sets `reward_enabled: true` and `lean_challenge_enabled: true`.
    - Prefer a small decision helper for threshold math, but cover at least one Stop-shaped fixture so the deny branch is wired.
    - Assert challenge true below threshold and false above.

14. `test_lean_challenge_stops_after_max_iterations`
    - Write prior real `score_assigned` events with `challenge_issued: true` for the same contract.
    - Assert no new challenge after the configured cap.

The minimum useful set is fourteen tests across four PRs because the feature touches pure scoring, Stop behavior, event integrity, concurrent append safety, and aggregation. Fewer tests would be more “lean” in the way skipping brakes makes a car lighter.

## Rollout and PR order

Ship this as four small PRs. Each PR must be revertable without forcing the next one to exist. The order is not decorative.

### PR1: score telemetry only

Add only:

- policy fields with defaults off,
- `RewardSignal`, scoring helpers, `compute_reward()`, and mechanical critique,
- unbounded `read_score_events()` plus `score_events_for_contract()` for prior score lookup, introduced here so PR3 reuses them instead of reimplementing them,
- `score_event_payload()`,
- Stop logging of `score_assigned` only when `reward_enabled=true` and `quality_evaluated=true`.

Do not add chain helpers, leaderboard parser/command code, challenge decision code, derived output files, config rewrites, or compatibility scaffolding for later PRs. PR1 is telemetry, not a variety show.

Defaults:

```json
"reward_enabled": false,
"reward_chain_enabled": false,
"lean_challenge_enabled": false
```

Acceptance:

- Existing 53 tests pass.
- PR1 reward tests pass.
- `check --repo "$PWD" --json` still creates no repo artifacts.
- Stop behavior is unchanged when `reward_enabled=false`.
- Stop writes no score and issues no challenge when `run_quality_gate_on_stop=false`.
- PR1 must not add `leaderboard` parser/command code.
- PR1 must not add Lean Challenge deny code.
- PR1 must not add event hash fields, lock helpers, or chain verification.
- PR1 must not add code used only by PR2, PR3, or PR4, except the score-event reader that PR1 itself needs for prior score comparison and PR3 later reuses.

That last cluster is important. “Just adding the parser while I’m here” is how one PR becomes a suitcase full of raccoons.

### PR2: event hash chain with locking

Add:

- `canonical_json()`,
- `event_log_lock()`,
- `last_event_hash()`,
- `verify_event_chain()`,
- chain-aware `log_event()` path behind `reward_chain_enabled`.

Acceptance:

- Chain writes hold a file lock across `last_event_hash + append`.
- Chain disabled means no event-shape change.
- Existing legacy logs remain readable until the first hashed event.
- Unchained events after chain start are rejected by verification.
- Chain tests use real `log_event()` writes and repo fixtures.
- `reward_chain_enabled=true` on an unsupported locking platform returns an actionable configuration error before writing.

### PR3: read-only leaderboard

Add:

- `leaderboard` parser branch,
- reuse PR1 `read_score_events()` and add leaderboard-specific filters,
- deterministic aggregation and simple rating,
- optional `--verify-chain`.

Acceptance:

- No writes unless an explicit future `--output` flag is added; v1.4 may stdout only.
- Chain verification failure returns nonzero or `ok:false`.
- Agents with insufficient data are labeled, not ranked as if the sample size fairy blessed them.
- Leaderboard tests use real event logs, not synthetic-only payloads.
- Leaderboard uses the unbounded score-event reader introduced in PR1, not `events(root, limit=200)`.

### PR4: challenge mode behind flag

Add:

- Stop deny branch,
- challenge cap,
- challenge-issued event fields,
- challenge-specific mechanical critique text.

Enable only after observational score distributions show the threshold is sane and P1-P3 calibration gates are satisfied.

Acceptance:

- Challenge only fires after final correctness and quality pass.
- Challenge logs exactly one `score_assigned` event per Stop attempt.
- Challenge cap prevents loops.
- `stop_hook_active` continuation path never scores or challenges.
- Challenge tests include at least one Stop-shaped fixture.
- Challenge is skipped when quality was not evaluated.

### Documentation pass

Update skills and methodology with a short note:

- A low-score challenge means the code is correct but not lean enough.
- The agent should reduce diff surface, reuse an existing path, or remove unnecessary wrapper/abstraction code.
- The agent should not add tests, comments, or scaffolding merely to look busy. Civilization has enough paperwork.

## File hygiene

Do not commit or package Windows alternate data stream sidecars such as `LEAN_CODE_GATE_V3_REWARD_LAYER*.md:Zone.Identifier`. They are not documentation, not state, not evidence, and not even interesting trash.

Required hygiene:

- Add `*:Zone.Identifier` to ignore rules if the repo does not already exclude it.
- Strip sidecars from generated release bundles.
- Do not mention sidecar files in implementation patch lists except as excluded artifacts.

## Acceptance bar

Shared merge bar for every PR:

- Existing tests pass unchanged except intentional test harness line-budget cleanup.
- New tests are production-shaped for Stop, chain, and leaderboard paths.
- Reward scoring and challenge are skipped when `run_quality_gate_on_stop=false`.
- Prior score, challenge cap, and leaderboard logic use unbounded score-event readers, not `events(root, limit=200)`.
- No new dependency is imported.
- No source reads git remotes, home config, `.ssh`, `.aws`, `.netrc`, keyring, or non-localhost network.
- No reward event stores raw full contract text, remote URLs, command output, secrets, or environment dumps.
- No hook feedback exposes subscore weights.
- No `*:Zone.Identifier` sidecars are committed, copied into release artifacts, or referenced by implementation docs.
- Multi-root Stop either logs per-root scores or suppresses challenge unless every root is clean; it must never allow one clean root’s score to hide another root’s final error.

PR-specific merge bars:

| PR | Required acceptance |
|---|---|
| PR1 score telemetry | `reward_enabled=false` by default; Stop behavior unchanged when disabled; exactly one score event per enabled Stop attempt when quality was evaluated; no score when `run_quality_gate_on_stop=false`; only policy defaults, score helpers, prior score reader, and Stop score logging; no leaderboard code; no challenge code; no chain or lock code. |
| PR2 locked chain | `reward_chain_enabled=false` by default; chain writes locked across read-hash-and-append; unsupported lock platforms rejected before write; legacy logs compatible; tampering detected; no leaderboard/challenge code required. |
| PR3 leaderboard | Read-only stdout JSON; reads full score history; verifies chain when requested/policy-enabled; no Stop behavior changes; no challenge code. |
| PR4 challenge | `lean_challenge_enabled=false` by default; challenge only after correctness and quality pass; cap enforced from unbounded score history; no formula/subscore leakage. |

Default policy in both `DEFAULT_POLICY` and `.agent/lean/policy.json` must keep these false until explicitly enabled:

```json
"reward_enabled": false,
"reward_chain_enabled": false,
"lean_challenge_enabled": false
```

## Anti-Goodhart controls

| Risk | Control |
|---|---|
| Agent optimizes brevity over correctness | Correctness floor returns score 0 before leanness points. |
| Agent spams tiny wrappers | Reuse and discipline terms penalize reuse warnings and near-budget churn; P3 wrapper detector should be active before challenge rollout. |
| Agent over-declares huge budgets | Leanness penalizes percentage of declared budget but also file/changed/add-heavy shape; future calibration can add over-budget-declaration pressure if needed. |
| Agent edits event log | Locked hash chain detects historical mutation after chain start and prevents concurrent writers from forking `prev_hash`. |
| Tail-limited history hides prior attempts | Reward history and leaderboard use unbounded score-event readers with `_line_no` append order. |
| Agent forges verification event | `final_errors()` verifies chain before trusting events when policy is enabled. |
| Agent learns formula from feedback | Hook critique shows verdict, score, delta, and one suggestion only. No subscore breakdown. |
| Operator ranks agents on one number | Leaderboard surfaces score distribution, pass/fail/challenge rates, cost proxy, and rating status. |
| Challenge loop traps agent | Challenge disabled by default and capped per contract. |
| Reward layer bloats core gate | Leaderboard is cut first if implementation exceeds the line budget. |

## What not to implement

Do **not** add:

- A second Python script.
- A daemon.
- A background service.
- Network calls.
- LLM-generated critiques.
- LLM-generated “lean reference” solutions.
- CrystalBLEU, CodeBERTScore, embeddings, AST frameworks, or TypeScript runtime dependencies.
- Per-developer scores.
- Badges, streaks, achievements, or any other gamified nonsense that makes professionals behave like apps are raising them.
- New hook event names.
- A separate `.leaderboard/` state tree.
- HMAC key management.
- A contract field for reward opt-out in the first release.
- `*:Zone.Identifier` files in commits, release zips, or generated spec artifacts.
- Chain-enabled event writes without a file lock.
- Leaderboard or challenge code in PR1.

## Minimal code map

Add helpers in the PR that needs them, not before. Dead scaffolding is still bloat, just wearing a planning badge.

### PR1 helpers

```text
RewardSignal
clamp
safe_int
contract_id
task_id
resolve_agent_id
resolve_model_id
correctness_floor
read_score_events        introduced in PR1; reused by PR3
score_events_for_contract
prior_scores_for_contract
leanness_points
reuse_points
discipline_points
reward_verdict
fail_critique
reward_critique
compute_reward
score_event_payload
```

Patch existing functions in PR1:

```text
DEFAULT_POLICY       add reward fields, all disabled by default
stop                 cache quality result, compute/log reward only when reward_enabled=true and quality was evaluated
```

### PR2 helpers

```text
canonical_json
event_log_lock_supported
reward_chain_platform_error
event_log_lock
last_event_hash
verify_event_chain
_append_event_line
```

Patch existing functions in PR2:

```text
log_event            add optional locked hash chain after platform guard
final_errors         optionally verify event chain before trusting verify_passed events
```

### PR3 helpers

```text
score_events_for_leaderboard  reuses PR1 read_score_events
leaderboard_summary
leaderboard_command
```

Patch existing functions in PR3:

```text
parser               add leaderboard subcommand
main                 dispatch leaderboard
```

### PR4 helpers

```text
challenge_count
should_issue_challenge
challenge_message
```

Patch existing functions in PR4:

```text
stop                 add challenge deny branch behind lean_challenge_enabled
```

No other functions should need to change.

## Final implementation target

The production behavior after all four PRs land and the relevant policy toggles are enabled:

1. Agent declares a Lean Change Contract.
2. Existing PreToolUse blocks out-of-contract or bloated edits.
3. Existing PostToolUse records mutations and verification.
4. Stop runs existing final and quality gates.
5. If correctness fails, Stop denies exactly as v3 already does and logs a zero score only when reward logging is enabled and quality was evaluated.
6. If correctness passes and quality was evaluated, Stop computes a deterministic reward score.
7. Stop writes one compact `score_assigned` event when telemetry is enabled and quality was evaluated.
8. If challenge mode is enabled and the score is below threshold, Stop denies up to the configured cap with a mechanical critique.
9. After the cap, correctness wins and Stop allows completion, while the low score remains visible in telemetry.
10. `leaderboard` reads the event log, verifies the chain when requested or policy-enabled, and prints local agent-performance summaries.

This gives the gate the missing closed loop: not just “did the agent stay inside the contract,” but “how lean, reuse-aware, and production-shaped was the passing attempt.” It does that without making the gate depend on model judgment, external services, or metric theatre. A rare mercy.
