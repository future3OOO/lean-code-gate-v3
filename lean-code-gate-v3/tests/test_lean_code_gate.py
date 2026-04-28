from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".agent" / "lean" / "lean_code_gate.py"


def run_gate(repo: Path, *args: str, payload: dict[str, object] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-B", "-S", str(GATE), *args],
        cwd=repo,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
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
        timeout=10,
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
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        (repo / "tests" / "test_app.py").write_text(
            "from src.app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        git(repo, "init")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test User")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "init")
        yield repo


def declare_valid(repo: Path, *, task_type: str = "feature", scope: str = "src/app.py,tests/test_app.py") -> None:
    result = run_gate(
        repo,
        "declare",
        "--intent",
        "adjust add behavior",
        "--scope",
        scope,
        "--task-type",
        task_type,
        "--affected-surface",
        "add function and direct unit test",
        "--authoritative-contract",
        "add returns the requested arithmetic result",
        "--invariant",
        "existing add callers remain valid",
        "--reuse-path",
        "src/app.py add function",
        "--proof-plan",
        "pytest tests/test_app.py",
        "--risk-check",
        "addition behavior regression",
        "--verify",
        "pytest tests/test_app.py",
    )
    assert result.returncode == 0, result.stderr


def declare_minimal(repo: Path) -> None:
    result = run_gate(
        repo,
        "declare",
        "--minimal-preflight",
        "--intent",
        "fix small add bug",
        "--scope",
        "src/app.py,tests/test_app.py",
        "--task-type",
        "bugfix",
        "--verify",
        "pytest tests/test_app.py",
    )
    assert result.returncode == 0, result.stderr


def check_json(repo: Path, *args: str) -> tuple[int, dict[str, object]]:
    result = run_gate(repo, "check", "--repo", str(repo), "--json", *args)
    return result.returncode, json.loads(result.stdout)


def snapshot_paths(repo: Path) -> set[str]:
    return {str(path.relative_to(repo)) for path in repo.rglob("*") if ".git" not in path.relative_to(repo).parts}


def test_declare_rejects_code_contract_without_preflight() -> None:
    with repo_fixture() as repo:
        result = run_gate(
            repo,
            "declare",
            "--intent",
            "adjust add behavior",
            "--scope",
            "src/app.py",
            "--task-type",
            "feature",
            "--verify",
            "pytest tests/test_app.py",
        )
        assert result.returncode == 2
        assert "requires --affected-surface" in result.stderr
        assert "requires --authoritative-contract" in result.stderr
        assert "requires --invariant" in result.stderr


def test_minimal_preflight_allows_micro_bugfix_without_cargo_fields() -> None:
    with repo_fixture() as repo:
        declare_minimal(repo)
        status = run_gate(repo, "status")
        contract = json.loads(status.stdout)["contract"]
        assert contract["preflight_level"] == "minimal"
        assert contract["max_added_lines"] == 30
        assert contract["max_changed_lines"] == 80


def test_unknown_task_type_is_rejected_instead_of_forcing_full_preflight() -> None:
    with repo_fixture() as repo:
        result = run_gate(repo, "declare", "--intent", "edit app", "--scope", "src/app.py", "--verify", "pytest tests/test_app.py")
        assert result.returncode == 2
        assert "explicit --task-type" in result.stderr


def test_minimal_preflight_rejects_wide_budget_and_escape_hatches() -> None:
    with repo_fixture() as repo:
        result = run_gate(
            repo,
            "declare",
            "--minimal-preflight",
            "--intent",
            "oversized micro fix",
            "--scope",
            "src/app.py",
            "--task-type",
            "bugfix",
            "--verify",
            "pytest tests/test_app.py",
            "--max-added-lines",
            "31",
            "--allow-new-files",
        )
        assert result.returncode == 2
        assert "max-added-lines" in result.stderr
        assert "cannot use --allow-new-files" in result.stderr


def test_edit_rewrite_counts_as_changed_lines() -> None:
    with repo_fixture() as repo:
        result = run_gate(
            repo,
            "declare",
            "--intent",
            "small edit",
            "--scope",
            "src/app.py",
            "--task-type",
            "feature",
            "--affected-surface",
            "add function",
            "--authoritative-contract",
            "edit stays within add behavior",
            "--invariant",
            "existing add callers remain valid",
            "--reuse-path",
            "src/app.py add function",
            "--proof-plan",
            "pytest tests/test_app.py",
            "--risk-check",
            "line rewrite risk",
            "--verify",
            "pytest tests/test_app.py",
            "--max-changed-lines",
            "5",
        )
        assert result.returncode == 0, result.stderr
        payload = {
            "cwd": str(repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(repo / "src" / "app.py"),
                "old_string": "\n".join(f"old{i}" for i in range(10)),
                "new_string": "\n".join(f"new{i}" for i in range(10)),
            },
        }
        result = run_gate(repo, "pretool", payload=payload)
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Changes about" in data["reason"]


def test_pretool_blocks_out_of_scope_patch() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        payload = {
            "cwd": str(repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: package.json\n+{}\n*** End Patch"},
        }
        result = run_gate(repo, "pretool", payload=payload)
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Outside scope" in data["reason"]


def test_pretool_blocks_fake_green_before_edit() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        payload = {
            "cwd": str(repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(repo / "src" / "app.py"),
                "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                "new_string": "def add(a: int, b: int) -> int:\n    # type: ignore\n    return a + b\n",
            },
        }
        result = run_gate(repo, "pretool", payload=payload)
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "quality escapes" in data["reason"]


def test_stop_blocks_quality_escape_in_changed_source() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        marker = "TO" + "DO"
        (repo / "src" / "app.py").write_text(
            f"def add(a: int, b: int) -> int:\n    # {marker} fake future work\n    return a + b\n",
            encoding="utf-8",
        )
        run_gate(
            repo,
            "posttool",
            payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}},
        )
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "quality escapes" in data["reason"]


def test_stop_blocks_dirty_repo_without_contract() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "no Lean Change Contract" in data["reason"]


def test_stop_hook_active_reports_without_looping() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop", "stop_hook_active": True})
        data = json.loads(result.stdout)
        assert "systemMessage" in data
        assert "decision" not in data


def test_stop_blocks_new_file_without_allow_new_files() -> None:
    with repo_fixture() as repo:
        declare_valid(repo, task_type="feature", scope="src/new.py")
        (repo / "src" / "new.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
        run_gate(repo, "posttool", payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}})
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "New files require --allow-new-files" in data["reason"]


def test_failed_verify_does_not_satisfy_stop_gate() -> None:
    with repo_fixture() as repo:
        declare_valid(repo, task_type="feature", scope="src/app.py")
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        run_gate(
            repo,
            "posttool",
            payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"result": {"exit_code": 1}}},
        )
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "Declared verification has not passed" in data["reason"]


def test_quality_check_detects_duplicate_added_blocks() -> None:
    with repo_fixture() as repo:
        duplicate = """
def parse_user(value: str) -> str:
    raw = value.strip()
    normalized = raw.lower()
    return normalized.replace(" ", "-")

def parse_group(value: str) -> str:
    raw = value.strip()
    normalized = raw.lower()
    return normalized.replace(" ", "-")
"""
        (repo / "src" / "duplicate.py").write_text(duplicate, encoding="utf-8")
        code, data = check_json(repo)
        assert code == 2
        assert any("duplicate added code blocks" in error for error in data["errors"])


def test_quality_check_detects_production_type_escape_but_allows_test_any() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "unsafe.ts").write_text("export function parse(value: any) { return value }\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 2
        assert any("quality escapes" in error for error in data["errors"])
        (repo / "src" / "unsafe.ts").unlink()
        (repo / "tests" / "fake.ts").write_text("const fake: any = {}\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data


def test_quality_check_detects_reimplemented_existing_helper_name() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "ids.py").write_text("def normalize_user_id(value: str) -> str:\n    return value.strip().lower()\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "helper")
        (repo / "src" / "users.py").write_text("def normalize_user_id(value: str) -> str:\n    return value.strip().lower()\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 2
        assert "gitnexusQueries" not in data
        assert not data["hardRules"]["noDuplication"]["passed"]
        assert data["reuseFindings"][0]["existingFile"] == "src/ids.py"


def test_reimplemented_dedupe_loop_fails_as_high_confidence_reuse() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "collections.py").write_text(
            "def dedupe_items(items: list[str]) -> list[str]:\n"
            "    seen = set()\n"
            "    out = []\n"
            "    for item in items:\n"
            "        if item not in seen:\n"
            "            seen.add(item)\n"
            "            out.append(item)\n"
            "    return out\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "dedupe helper")
        (repo / "src" / "importer.py").write_text(
            "def import_items(items: list[str]) -> list[str]:\n"
            "    seen = set()\n"
            "    result = []\n"
            "    for item in items:\n"
            "        if item not in seen:\n"
            "            seen.add(item)\n"
            "            result.append(item)\n"
            "    return result\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 2
        assert any(item["existingSymbol"] == "dedupe_items" for item in data["reuseFindings"])


def test_reuse_detector_suppresses_generic_same_name_false_positive() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "task_a.py").write_text("def run() -> str:\n    return 'a'\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "generic helper")
        (repo / "src" / "task_b.py").write_text("def run() -> str:\n    return 'b'\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_reuse_detector_suppresses_same_tokens_different_domain() -> None:
    with repo_fixture() as repo:
        (repo / "api").mkdir()
        (repo / "workers").mkdir()
        (repo / "api" / "contracts.py").write_text("def parse_limit(value: str) -> int:\n    return int(value)\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "api parse")
        (repo / "workers" / "cli.py").write_text("def parse_limit(value: str) -> str:\n    return value.split(':')[0]\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_reuse_detector_ignores_deleted_then_recreated_helper() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "ids.py").write_text("def normalize_user_id(value: str) -> str:\n    return value.strip().lower()\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "helper")
        (repo / "src" / "ids.py").unlink()
        (repo / "src" / "users.py").write_text("def normalize_user_id(value: str) -> str:\n    return value.strip().lower()\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_reuse_detector_ignores_same_name_across_languages() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "ids.py").write_text("def normalize_user_id(value: str) -> str:\n    return value.strip().lower()\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "python helper")
        (repo / "src" / "ids.ts").write_text("export function normalize_user_id(value: string) { return value.trim().toLowerCase() }\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_large_existing_file_small_growth_warns_but_does_not_fail_by_default() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "large.py").write_text("\n".join(f"VALUE_{i} = {i}" for i in range(1201)) + "\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "large baseline")
        with (repo / "src" / "large.py").open("a", encoding="utf-8") as handle:
            handle.write("EXTRA = 1\n")
        code, data = check_json(repo)
        assert code == 0, data
        assert any("large source file" in warning for warning in data["warnings"])


def test_large_existing_file_big_growth_fails() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "large.py").write_text("\n".join(f"VALUE_{i} = {i}" for i in range(1201)) + "\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "large baseline")
        with (repo / "src" / "large.py").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(f"EXTRA_{i} = {i}" for i in range(81)) + "\n")
        code, data = check_json(repo)
        assert code == 2
        assert data["hardRules"]["codeVolume"]["passed"] is False


def test_excluded_path_globs_skip_generated_sdk_files() -> None:
    with repo_fixture() as repo:
        (repo / "clients" / "client-test" / "src" / "commands").mkdir(parents=True)
        big = "\n".join(f"export const CMD_{i} = {{}};" for i in range(900))
        (repo / "clients" / "client-test" / "src" / "commands" / "BigCmd.ts").write_text(big + "\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert all("clients/client-test/src/commands/BigCmd.ts" not in error for error in data["errors"])


def test_excluded_path_globs_can_be_overridden_to_empty() -> None:
    with repo_fixture() as repo:
        (repo / ".agent" / "lean" / "policy.json").write_text(
            json.dumps({"excluded_path_globs": []}), encoding="utf-8"
        )
        (repo / "clients" / "client-test" / "src" / "commands").mkdir(parents=True)
        big = "\n".join(f"export const CMD_{i} = {{}};" for i in range(900))
        (repo / "clients" / "client-test" / "src" / "commands" / "BigCmd.ts").write_text(big + "\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 2, data
        assert any("clients/client-test/src/commands/BigCmd.ts" in error for error in data["errors"])


def test_gate_check_creates_no_repo_artifacts() -> None:
    with repo_fixture() as repo:
        before = snapshot_paths(repo)
        code, data = check_json(repo)
        after = snapshot_paths(repo)
        assert code == 0
        assert data["ok"] is True
        assert after == before


TESTS = [
    test_declare_rejects_code_contract_without_preflight,
    test_minimal_preflight_allows_micro_bugfix_without_cargo_fields,
    test_unknown_task_type_is_rejected_instead_of_forcing_full_preflight,
    test_minimal_preflight_rejects_wide_budget_and_escape_hatches,
    test_edit_rewrite_counts_as_changed_lines,
    test_pretool_blocks_out_of_scope_patch,
    test_pretool_blocks_fake_green_before_edit,
    test_stop_blocks_quality_escape_in_changed_source,
    test_stop_blocks_dirty_repo_without_contract,
    test_stop_hook_active_reports_without_looping,
    test_stop_blocks_new_file_without_allow_new_files,
    test_failed_verify_does_not_satisfy_stop_gate,
    test_quality_check_detects_duplicate_added_blocks,
    test_quality_check_detects_production_type_escape_but_allows_test_any,
    test_quality_check_detects_reimplemented_existing_helper_name,
    test_reimplemented_dedupe_loop_fails_as_high_confidence_reuse,
    test_reuse_detector_suppresses_generic_same_name_false_positive,
    test_reuse_detector_suppresses_same_tokens_different_domain,
    test_reuse_detector_ignores_deleted_then_recreated_helper,
    test_reuse_detector_ignores_same_name_across_languages,
    test_large_existing_file_small_growth_warns_but_does_not_fail_by_default,
    test_large_existing_file_big_growth_fails,
    test_excluded_path_globs_skip_generated_sdk_files,
    test_excluded_path_globs_can_be_overridden_to_empty,
    test_gate_check_creates_no_repo_artifacts,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"ok {test.__name__}")
    print(f"passed {len(TESTS)} lean-code-gate tests")
