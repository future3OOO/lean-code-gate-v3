"""Calibration findings — proposed test suite extension for Lean Code Gate v3.

Each test pins a *current* gate behavior (pass or fail) observed during the
v3 calibration program (see calibration/PLAN.md). Tests that pin a behavior
the calibration recommends changing are decorated with @unittest.skip and
reference the policy recommendation. They are intended to flip from
expect-fail to expect-pass when the corresponding gate change ships.

Usage:
  python3 calibration/proposed-tests/test_calibration_findings.py

The tests reuse the v3 fixture style. Imports point at the v3 test helper
file via sys.path injection so the calibration tests stay one self-
contained file.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2] / "lean-code-gate-v3"
GATE = ROOT / ".agent" / "lean" / "lean_code_gate.py"


def run_gate(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-B", "-S", str(GATE), *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_EDITOR": "true",
        "GIT_PAGER": "cat",
    }
    result = subprocess.run(
        ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
        env=env,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


@contextmanager
def repo_fixture() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".agent" / "lean").mkdir(parents=True)
        shutil.copy2(GATE, repo / ".agent" / "lean" / "lean_code_gate.py")
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "app.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
        )
        git(repo, "init")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test User")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "init")
        yield repo


def check_json(repo: Path, *args: str) -> tuple[int, dict[str, object]]:
    result = run_gate(repo, "check", "--repo", str(repo), "--json", *args)
    return result.returncode, json.loads(result.stdout)


class CalibrationFindings(unittest.TestCase):
    """Pin behavior observed in the v3 calibration program."""

    @unittest.skip("documents v3 limitation; calibration R-3 (private/public siblings)")
    def test_django_admin_private_public_sibling_does_not_trigger_reuse(self) -> None:
        # Cite: django/contrib/admin/options.py defines both save_formset (line ~1300)
        # and _save_formset (line ~2044). v3 flags this pair as reuse-error score 100
        # because token-tuples after split_name_tokens collapse "_save_formset" to
        # ("save","formset"), identical to "save_formset". Reviewers shipped the code.
        with repo_fixture() as repo:
            (repo / "src" / "admin.py").write_text(
                "def save_formset(formset):\n    formset.save()\n", encoding="utf-8"
            )
            git(repo, "add", ".")
            git(repo, "commit", "--no-gpg-sign", "-m", "public sibling")
            (repo / "src" / "admin.py").write_text(
                "def save_formset(formset):\n    formset.save()\n\n"
                "def _save_formset(formset):\n    formset.save()  # private helper\n",
                encoding="utf-8",
            )
            code, data = check_json(repo)
            # Calibrated behavior: code == 0 (private/public sibling suppressed).
            self.assertEqual(code, 0, data)
            self.assertEqual(data["reuseFindings"], [])

    @unittest.skip("documents v3 limitation; calibration R-2 (framework override allowlist)")
    def test_framework_validate_method_does_not_trigger_reuse(self) -> None:
        # Cite: sentry/src/sentry/explore/endpoints/serializers.py defines validate(),
        # which is a Django REST Framework Serializer.validate() override. The gate
        # currently flags it against any other validate() in the repo. Reviewers
        # shipped the code; calibrated gate must allow framework-mandated names.
        with repo_fixture() as repo:
            (repo / "src" / "ser1.py").write_text(
                "class S1:\n    def validate(self, attrs):\n        return attrs\n",
                encoding="utf-8",
            )
            git(repo, "add", ".")
            git(repo, "commit", "--no-gpg-sign", "-m", "ser1")
            (repo / "src" / "ser2.py").write_text(
                "class S2:\n    def validate(self, attrs):\n        return attrs\n",
                encoding="utf-8",
            )
            code, data = check_json(repo)
            self.assertEqual(code, 0, data)
            self.assertEqual(data["reuseFindings"], [])

    @unittest.skip("documents v3 limitation; calibration R-1 (excluded_path_globs for generated/)")
    def test_generated_path_excluded_from_bloat(self) -> None:
        # Cite: pydantic-core/src/self_schema.py +6852 (auto-generated, file header
        # explicitly says "DO NOT edit manually"). v3 flags it as bloat error.
        # Calibrated gate must exclude **/generated/** and similar paths.
        with repo_fixture() as repo:
            (repo / "src" / "generated").mkdir()
            big = "\n".join(f"VAR_{i} = {i}" for i in range(900))
            (repo / "src" / "generated" / "schema.py").write_text(big + "\n", encoding="utf-8")
            code, data = check_json(repo)
            # Calibrated behavior: no bloat error from generated path.
            bloat_errors = [e for e in data.get("errors", []) if "source file" in e or "additive" in e]
            self.assertEqual(bloat_errors, [], data)

    @unittest.skip("documents v3 limitation; calibration R-1 (excluded_path_globs for generated SDK)")
    def test_aws_sdk_generated_clients_path_excluded(self) -> None:
        # Cite: aws-sdk-js-v3 clients/client-bedrock-agentcore/src/models/models_0.ts
        # grew by 1630 lines (auto-generated from Smithy). Reviewers shipped 4 of 5
        # measured PRs into this surface despite gate firing.
        with repo_fixture() as repo:
            (repo / "clients" / "client-test" / "src" / "commands").mkdir(parents=True)
            big = "\n".join(f"export const CMD_{i} = {{}};" for i in range(900))
            (repo / "clients" / "client-test" / "src" / "commands" / "BigCmd.ts").write_text(
                big + "\n", encoding="utf-8"
            )
            code, data = check_json(repo)
            new_file_bloat = [e for e in data.get("errors", []) if "new source file" in e]
            self.assertEqual(new_file_bloat, [], data)

    @unittest.skip("documents v3 limitation; calibration R-1 (excluded_path_globs for migrations)")
    def test_migration_path_excluded_from_bloat(self) -> None:
        # Cite: getsentry/sentry src/sentry/migrations/. The 50-commit window did not
        # show migration churn, but the guide flagged this and reviewer practice
        # treats migrations as untouchable artifacts.
        with repo_fixture() as repo:
            (repo / "src" / "migrations").mkdir()
            big = "\n".join(f"OP_{i} = None" for i in range(900))
            (repo / "src" / "migrations" / "0001_initial.py").write_text(big + "\n", encoding="utf-8")
            code, data = check_json(repo)
            new_file_bloat = [e for e in data.get("errors", []) if "new source file" in e]
            self.assertEqual(new_file_bloat, [], data)

    def test_check_creates_no_artifacts_invariant_holds(self) -> None:
        # Pins the cleanliness invariant verified across 8 production repos +
        # 42 merged-PR worktrees during v3 calibration. No gate change required;
        # this is the regression guard.
        with repo_fixture() as repo:
            before = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
            ).stdout
            check_json(repo)
            after = subprocess.run(
                ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
            ).stdout
            self.assertEqual(before, after, "gate `check` must not modify the repo tree")

    @unittest.skip("documents v3 limitation; FN-2 (Go factory regex)")
    def test_go_factory_function_triggers_design_marker(self) -> None:
        # Cite: false-negative-classes.md FN-2. v3's DESIGN_RE only matches
        # `class \w*Factory` etc. Go's idiom is `func NewFooFactory(...)`. The
        # current regex cannot see Go factories.
        with repo_fixture() as repo:
            (repo / "src" / "factory.go").write_text(
                "package src\n\nfunc NewWidgetFactory() *WidgetFactory { return nil }\n"
                "func NewWidgetBuilder() *WidgetBuilder { return nil }\n"
                "func NewWidgetManager() *WidgetManager { return nil }\n"
                "func NewWidgetRegistry() *WidgetRegistry { return nil }\n",
                encoding="utf-8",
            )
            # If/when the calibrated DESIGN_RE catches Go, this becomes a real check.
            # For now we cannot exercise abstraction-sniff via `check` alone (only
            # via `declare`); this test stays as documentation until the path lands.
            code, data = check_json(repo)
            self.assertIn(code, (0, 2))  # reserved for calibrated behavior

    def test_two_instance_duplicate_currently_fires(self) -> None:
        # Cite: django pr-21152 (UniqueConstraint adjustment). v3 fires
        # no-duplicate-added-blocks at N=2. Reviewers shipped the PR.
        # Pins current behavior; will need to flip when R-4 (min count = 3) lands.
        # Fixture mirrors v3's test_quality_check_detects_duplicate_added_blocks:
        # two distinct functions in one file with identical body lines.
        with repo_fixture() as repo:
            duplicate = (
                "def parse_user(value: str) -> str:\n"
                "    raw = value.strip()\n"
                "    normalized = raw.lower()\n"
                "    return normalized.replace(\" \", \"-\")\n"
                "\n"
                "def parse_group(value: str) -> str:\n"
                "    raw = value.strip()\n"
                "    normalized = raw.lower()\n"
                "    return normalized.replace(\" \", \"-\")\n"
            )
            (repo / "src" / "duplicate.py").write_text(duplicate, encoding="utf-8")
            code, data = check_json(repo)
            # Pin v3 behavior: the no-duplicate-added-blocks check FAILS at N=2.
            # R-4 (reuse_min_duplicate_count=3) will flip this when it ships.
            dup_check = next(c for c in data["checks"] if c["name"] == "no-duplicate-added-blocks")
            self.assertEqual(code, 2, data)
            self.assertFalse(dup_check["passed"], data)


if __name__ == "__main__":
    # Print a concise summary instead of unittest's default verbose output.
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(CalibrationFindings)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
