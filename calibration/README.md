# Calibration workspace

Measurement output for `LEAN_CODE_GATE_V3_CALIBRATION_GUIDE.md`. Governing artifact: `PLAN.md` (this directory).

## Layout

```
calibration/
├── PLAN.md                # governing plan (mutable)
├── README.md              # this file
├── repos/                 # gitignored: shallow clones of target repos
├── findings/              # per-repo gate output (committed)
│   ├── <repo>.json
│   ├── <repo>.stderr.log
│   ├── <repo>.meta
│   ├── <repo>.largest-files.txt
│   └── cleanliness.log
├── analysis/              # measurement analysis (committed)
├── proposed-policy/       # calibrated policy.json + rationale
└── proposed-tests/        # tests pinning observed behavior
```

## Key finding from setup

The v3 gate's `check` subcommand evaluates **changed files** (working tree diff or last-commit diff via `HEAD~1`). On a `--depth 1` clone with no edits, `HEAD~1` does not exist, so the gate reports an empty change set. To produce meaningful measurement, this calibration uses `--depth 2` and lets the gate diff `HEAD~1..HEAD` (the most recent upstream commit). This is documented in `analysis/per-detector-hit-rates.md` as a guide-vs-implementation gap.
