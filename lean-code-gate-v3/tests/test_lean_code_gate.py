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

def parse_role(value: str) -> str:
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


def test_exact_name_reimplementation_across_files_fires() -> None:
    # Regression: symbol_is_called_nearby's `\b{name}\s*\(` pattern matched
    # the new symbol's own def line ("def parse_html_payload(...)" matches
    # `\bparse_html_payload\s*\(`). This made best_existing_match treat the
    # new def line as proof the existing symbol was already called nearby,
    # silently skipping the candidate. Net effect: exact-name reuse across
    # files was invisible to the detector. Fix excludes the new-symbol's own
    # def line from the call-detection window.
    with repo_fixture() as repo:
        (repo / "src" / "parser.py").write_text(
            "def parse_html_payload(blob):\n    return blob.decode('utf-8').strip()\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed parser")
        (repo / "src" / "parsers").mkdir(exist_ok=True)
        (repo / "src" / "parsers" / "extra.py").write_text(
            "def parse_html_payload(blob):\n"
            "    text = blob.decode('utf-8')\n"
            "    return text.strip()\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 2, data
        assert data["reuseFindings"], data
        assert any(
            f["newSymbol"] == "parse_html_payload" and f["existingSymbol"] == "parse_html_payload"
            for f in data["reuseFindings"]
        ), data["reuseFindings"]


def test_def_line_filter_is_symbol_aware_not_blanket() -> None:
    # Pins the precision form of the def-line filter: it must skip the def
    # line *for the symbol being searched*, not every def line. A blanket
    # "any def line" filter would incorrectly suppress a real call on a
    # *different* symbol's def line (e.g. default-arg call), causing false
    # reuse findings.
    #
    # Setup: existing `compute_html_signature` with its real (non-generic)
    # implementation tokens. New file defines `wrap_payload` whose default
    # arg is `fn=compute_html_signature()` — a real call. That call must
    # be visible to `symbol_is_called_nearby("compute_html_signature", ...)`
    # so the candidate is suppressed and no false reuse finding fires for
    # `wrap_payload` against `compute_html_signature`.
    with repo_fixture() as repo:
        (repo / "src" / "signature.py").write_text(
            "def compute_html_signature(blob):\n"
            "    digest = hashlib.sha256(blob).hexdigest()\n"
            "    return digest[:16]\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed signature")
        (repo / "src" / "wrapper.py").write_text(
            "from src.signature import compute_html_signature\n"
            "def wrap_payload(blob, fn=compute_html_signature()):\n"
            "    digest = hashlib.sha256(blob).hexdigest()\n"
            "    return fn or digest[:16]\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        # The new file legitimately *calls* compute_html_signature on the
        # def line. The symbol-aware filter must keep that call visible so
        # no false reuse finding lists wrap_payload as reimplementing
        # compute_html_signature.
        assert not any(
            f.get("newSymbol") == "wrap_payload"
            and f.get("existingSymbol") == "compute_html_signature"
            for f in data.get("reuseFindings", [])
        ), data.get("reuseFindings")


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
        (repo / "src" / "large.py").write_text("\n".join(f"VALUE_{i} = {i}" for i in range(1501)) + "\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "large baseline")
        with (repo / "src" / "large.py").open("a", encoding="utf-8") as handle:
            handle.write("EXTRA = 1\n")
        code, data = check_json(repo)
        assert code == 0, data
        assert any("large source file" in warning for warning in data["warnings"])


def test_large_existing_file_big_growth_fails() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "large.py").write_text("\n".join(f"VALUE_{i} = {i}" for i in range(1501)) + "\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "large baseline")
        with (repo / "src" / "large.py").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(f"EXTRA_{i} = {i}" for i in range(81)) + "\n")
        code, data = check_json(repo)
        assert code == 2
        assert data["hardRules"]["codeVolume"]["passed"] is False


_HIGH_DENSITY_TEXT = (
    "from typing import Protocol, TypeVar, Generic\n"
    "from abc import ABC\n"
    "T = TypeVar('T')\n"
    "class BaseWidget: pass\n"
    "class WidgetFactory(Generic[T]):\n"
    "    plugin = True\n"
    "    pass\n"
)


def test_min_duplicate_count_suppresses_two_instance_hit() -> None:
    with repo_fixture() as repo:
        # Two identical blocks — under default reuse_min_duplicate_count=3 this
        # MUST NOT fire; raises a calibration concern at N=2 (django pr-21152).
        block = (
            "def helper(x):\n"
            "    raw = x.strip()\n"
            "    normalized = raw.lower()\n"
            "    return normalized.replace(\" \", \"-\")\n"
        )
        (repo / "src" / "twohit.py").write_text(block + "\n" + block.replace("def helper", "def helper2"), encoding="utf-8")
        code, data = check_json(repo)
        dup_check = next(c for c in data["checks"] if c["name"] == "no-duplicate-added-blocks")
        assert dup_check["passed"] is True, data


def _load_gate_module() -> object:
    import importlib.util
    import sys as _sys
    spec = importlib.util.spec_from_file_location("gate_under_test", str(GATE))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    _sys.modules["gate_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_process_tolerates_non_utf8_output() -> None:
    # Regression: subprocess.Popen(text=True) decodes with strict utf-8 and
    # crashes on non-utf-8 bytes (surfaced by gate.py running git diff over
    # a 100-commit TypeScript window with binary patches). The fixed
    # run_process uses errors='replace' so non-utf-8 bytes become �
    # rather than raising UnicodeDecodeError.
    mod = _load_gate_module()
    with tempfile.TemporaryDirectory() as tmp:
        result = mod.run_process(
            ["python3", "-c", r"import sys; sys.stdout.buffer.write(b'hello \xc3\x28 world')"],
            Path(tmp),
        )
        assert result.returncode == 0, result.stderr
        # \xc3\x28 is invalid utf-8; with errors='replace' it becomes �
        assert "hello" in result.stdout and "world" in result.stdout


def test_high_confidence_reuse_respects_r2_r3_suppression() -> None:
    # Regression: high_confidence_reuse used to duplicate same_behavior_name's
    # name+token check and bypass R-2/R-3 suppression. Surfaced in calibration
    # A5 (langchain) where __iter__/iter and _completion_with_retry/
    # completion_with_retry were still firing despite R-3 returning (0, "").
    mod = _load_gate_module()
    mod._active_suppress_private_public_siblings = True
    mod._active_framework_override_names = frozenset({"__iter__", "__next__"})

    a = mod.SymbolDef("_completion_with_retry", "a.py", 1, "function", "python", ("completion", "with", "retry"), "untracked", 0)
    b = mod.SymbolDef("completion_with_retry", "b.py", 1, "function", "python", ("completion", "with", "retry"), "untracked", 0)
    assert mod.high_confidence_reuse(a, b) is False

    # Genuine duplicate must still trip high_confidence_reuse.
    c = mod.SymbolDef("parse_user", "a.py", 1, "function", "python", ("parse", "user"), "untracked", 0)
    d = mod.SymbolDef("parse_user", "b.py", 1, "function", "python", ("parse", "user"), "untracked", 0)
    assert mod.high_confidence_reuse(c, d) is True


def test_design_re_catches_go_factory_function() -> None:
    hits = _load_gate_module().design_hits("func NewWidgetFactory() *WidgetFactory { return nil }")
    assert "pattern-named factory function" in hits


def test_design_re_catches_rust_pub_type_alias() -> None:
    hits = _load_gate_module().design_hits("pub type ScopedFieldNameState<'scope, 'a, 'py> = ScopedSetState<...>;")
    assert "rust type-alias abstraction" in hits


def test_pretool_blocks_high_density_abstraction_in_small_file() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        result = run_gate(repo, "pretool", payload={
            "tool_name": "Edit", "tool_input": {"file_path": "src/app.py", "new_string": _HIGH_DENSITY_TEXT}
        })
        assert result.returncode == 0, result.stderr
        assert "Possible abstraction bloat" in result.stdout


def test_pretool_allows_low_density_abstraction_in_large_file() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        # 7 + 192 = 199 lines, density = 4/199*100 = 2.01/100, below the 3.0
        # threshold. Since line_count >= 100, the small-file bypass is false
        # AND density < threshold — no fire. Exercises the negative case of
        # the density branch.
        body = "\n".join(f"value_{i} = {i}" for i in range(192))
        result = run_gate(repo, "pretool", payload={
            "tool_name": "Edit", "tool_input": {"file_path": "src/app.py", "new_string": _HIGH_DENSITY_TEXT + body + "\n"}
        })
        assert "Possible abstraction bloat" not in result.stdout, result.stdout


def test_pretool_blocks_at_density_threshold_in_large_file() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        # 7 + 94 = 101 lines, density = 4/101*100 = 3.96/100, >= 3.0.
        # line_count >= 100 disables the small-file bypass, so the test
        # actually exercises the density-firing branch (greptile P1 on PR #9
        # caught that range(92) gave 99 lines and fired via line_count<100).
        body = "\n".join(f"value_{i} = {i}" for i in range(94))
        result = run_gate(repo, "pretool", payload={
            "tool_name": "Edit", "tool_input": {"file_path": "src/app.py", "new_string": _HIGH_DENSITY_TEXT + body + "\n"}
        })
        assert "Possible abstraction bloat" in result.stdout, result.stdout


def test_framework_override_names_suppress_reuse_error() -> None:
    # Use get_queryset, which is NOT in GENERIC_SYMBOLS. Without R-2 the pair
    # would score 100 (exact-name match) and fire a reuse error. With R-2 in
    # the framework_override_names allowlist, same_behavior_name returns
    # (0, "") and best_existing_match filters the candidate.
    # Original draft used `validate`, which IS in GENERIC_SYMBOLS — that test
    # passed even with R-2 inactive (greptile P1).
    with repo_fixture() as repo:
        (repo / "src" / "views1.py").write_text(
            "class V1:\n    def get_queryset(self):\n"
            "        return self.model.objects.filter(active=True)\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "v1")
        (repo / "src" / "views2.py").write_text(
            "class V2:\n    def get_queryset(self):\n"
            "        return self.model.objects.filter(active=True)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_private_public_sibling_pair_suppresses_reuse_error() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "admin.py").write_text(
            "def save_formset(formset):\n    formset.save()\n", encoding="utf-8"
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "public sibling")
        (repo / "src" / "admin.py").write_text(
            "def save_formset(formset):\n    formset.save()\n\n"
            "def _save_formset(formset):\n    formset.save()\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert data["reuseFindings"] == []


def test_excluded_path_globs_skip_generated_sdk_files() -> None:
    with repo_fixture() as repo:
        (repo / "clients" / "client-test" / "src" / "commands").mkdir(parents=True)
        big = "\n".join(f"export const CMD_{i} = {{}};" for i in range(900))
        (repo / "clients" / "client-test" / "src" / "commands" / "BigCmd.ts").write_text(big + "\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert all("clients/client-test/src/commands/BigCmd.ts" not in error for error in data["errors"])


def test_excluded_path_globs_match_first_component_path() -> None:
    # Regression: fnmatch treats ** as a single *, so "**/migrations/**" must
    # also match a path whose FIRST component is the excluded directory
    # (e.g. "migrations/0001_initial.py"), not just nested cases.
    with repo_fixture() as repo:
        (repo / "migrations").mkdir()
        big = "\n".join(f"OP_{i} = None" for i in range(900))
        (repo / "migrations" / "0001_initial.py").write_text(big + "\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert all("migrations/0001_initial.py" not in error for error in data["errors"])


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
    test_exact_name_reimplementation_across_files_fires,
    test_def_line_filter_is_symbol_aware_not_blanket,
    test_reuse_detector_suppresses_generic_same_name_false_positive,
    test_reuse_detector_suppresses_same_tokens_different_domain,
    test_reuse_detector_ignores_deleted_then_recreated_helper,
    test_reuse_detector_ignores_same_name_across_languages,
    test_large_existing_file_small_growth_warns_but_does_not_fail_by_default,
    test_large_existing_file_big_growth_fails,
    test_min_duplicate_count_suppresses_two_instance_hit,
    test_run_process_tolerates_non_utf8_output,
    test_high_confidence_reuse_respects_r2_r3_suppression,
    test_design_re_catches_go_factory_function,
    test_design_re_catches_rust_pub_type_alias,
    test_pretool_blocks_high_density_abstraction_in_small_file,
    test_pretool_allows_low_density_abstraction_in_large_file,
    test_pretool_blocks_at_density_threshold_in_large_file,
    test_framework_override_names_suppress_reuse_error,
    test_private_public_sibling_pair_suppresses_reuse_error,
    test_excluded_path_globs_skip_generated_sdk_files,
    test_excluded_path_globs_match_first_component_path,
    test_excluded_path_globs_can_be_overridden_to_empty,
    test_gate_check_creates_no_repo_artifacts,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"ok {test.__name__}")
    print(f"passed {len(TESTS)} lean-code-gate tests")
