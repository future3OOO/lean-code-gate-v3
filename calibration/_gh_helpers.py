"""Shared `gh api` helpers and repo→GH-slug map.

Used by pr_size_analysis.py, pr_size_v2.py, backfill_pr_dates.py,
self_benchmark.py. Single source of truth so a new repo entry only
has to be added in one place.
"""
from __future__ import annotations

import json
import subprocess

GH_FOR = {
    "django": "django/django",
    "fastapi": "fastapi/fastapi",
    "pydantic": "pydantic/pydantic",
    "typescript": "microsoft/TypeScript",
    "nextjs": "vercel/next.js",
    "sentry": "getsentry/sentry",
    "aws-sdk-js": "aws/aws-sdk-js-v3",
    "grpc": "grpc/grpc",
    # A10 pre-AI / mature benchmark set
    "cpython": "python/cpython",
    "numpy": "numpy/numpy",
    "airflow": "apache/airflow",
    "tokio": "tokio-rs/tokio",
    "cargo": "rust-lang/cargo",
    "prometheus": "prometheus/prometheus",
    "jquery": "jquery/jquery",
    "react": "facebook/react",
    "lodash": "lodash/lodash",
    "eslint": "eslint/eslint",
    "svelte": "sveltejs/svelte",
    "vue3": "vuejs/core",
    "vite": "vitejs/vite",
    "ts-eslint": "typescript-eslint/typescript-eslint",
}


def gh_json(args: list[str]) -> object:
    """Run `gh api <args>` and return parsed JSON, or None on any error."""
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
