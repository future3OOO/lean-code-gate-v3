from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".agent" / "lean" / "lean_code_gate.py"


def run_gate(
    repo: Path,
    *args: str,
    payload: dict[str, object] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-B", "-S", str(GATE), *args],
        cwd=repo,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        env={**os.environ, "LEAN_CODE_GATE_REPO_ROOT": "", "LEAN_CODE_GATE_SCRIPT_PATH": "", **(env or {})},
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
        init_repo_fixture(repo)
        yield repo


def init_repo_fixture(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
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


def declare_full_with_proof_plan(repo: Path, proof_plan: str, *, task_type: str = "feature", scope: str = "src/app.py") -> None:
    result = run_gate(
        repo,
        "declare",
        "--intent",
        "adjust app behavior",
        "--scope",
        scope,
        "--task-type",
        task_type,
        "--affected-surface",
        "app behavior",
        "--authoritative-contract",
        "observable behavior remains valid",
        "--invariant",
        "callers keep expected behavior",
        "--reuse-path",
        "src/app.py add function",
        "--proof-plan",
        proof_plan,
        "--risk-check",
        "no sensitive data touched",
        "--verify",
        "pytest tests/test_app.py",
    )
    assert result.returncode == 0, result.stderr


def check_json(repo: Path, *args: str) -> tuple[int, dict[str, object]]:
    result = run_gate(repo, "check", "--repo", str(repo), "--json", *args)
    return result.returncode, json.loads(result.stdout)


def snapshot_paths(repo: Path) -> set[str]:
    return {str(path.relative_to(repo)) for path in repo.rglob("*") if ".git" not in path.relative_to(repo).parts}


def reward_events(repo: Path) -> list[dict[str, object]]:
    path = repo / ".agent" / "lean" / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [item for item in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()) if item.get("event") == "reward_telemetry"]


def load_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lean_code_gate_under_test", GATE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_p0_advisory_groups_are_empty_and_compatible() -> None:
    with repo_fixture() as repo:
        code, data = check_json(repo)
        assert code == 0
        for name in ("securityAssumptionFindings", "slopShapeFindings", "verificationShapeFindings"):
            assert data[name] == {"added": [], "resolved": [], "worsened": [], "improved": []}
        assert data["ok"] is True
        assert data["warnings"] == []
        assert all(item["passed"] for item in data["checks"])
        assert all(item["passed"] for item in data["hardRules"].values())

        text_result = run_gate(repo, "check", "--repo", str(repo))
        assert text_result.returncode == 0
        assert "Advisory findings" not in text_result.stdout

        promoted = run_gate(repo, "check", "--repo", str(repo), "--fail-on-warnings", "--json")
        promoted_data = json.loads(promoted.stdout)
        assert promoted.returncode == 0
        assert promoted_data["errors"] == []


def _advisory_added(data: dict[str, object], group: str) -> list[dict[str, object]]:
    return list(data[group]["added"])


def test_sensitive_input_source_only_is_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "secrets.py").write_text("import os\nTOKEN = os.environ['API_KEY']\n", encoding="utf-8")
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert findings[0]["evidence"] == "source=environment-read"
        assert data["warnings"] == []
        assert all(item["passed"] for item in data["checks"])


def test_sensitive_input_source_and_sink_is_stronger_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "secrets.py").write_text(
            "import os\nTOKEN = os.getenv('API_KEY')\nprint(TOKEN)\n", encoding="utf-8"
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]
        assert "API_KEY" not in findings[0]["evidence"]
        assert "API_KEY" not in findings[0]["message"]


def test_sensitive_input_high_requires_same_line_or_source_identifier_flow() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "flow.py").write_text(
            "import os\n"
            "TOKEN = os.getenv('API_KEY')\n"
            "print('starting')\n"
            "status = 200\n"
            "print(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]

    with repo_fixture() as repo:
        (repo / "src" / "unrelated.py").write_text(
            "import os\n"
            "TOKEN = os.getenv('API_KEY'); print('ready')\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert "sink=" not in findings[0]["evidence"]


def test_sensitive_input_unchanged_and_broad_secret_names_do_not_hit() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "seed.py").write_text("import os\nTOKEN = os.environ['API_KEY']\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed sensitive read")
        (repo / "src" / "seed.py").write_text(
            "import os\nTOKEN = os.environ['API_KEY']\nVALUE = 1\n", encoding="utf-8"
        )
        (repo / "src" / "names.py").write_text(
            "secret_payload = load_user_setting()\n"
            "if os.environ:\n"
            "    value = 1\n",
            encoding="utf-8",
        )
        (repo / "src" / "headers.ts").write_text("const AUTH_HEADER = 'Authorization';\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "securityAssumptionFindings") == []


def test_sensitive_input_test_fixtures_do_not_hit() -> None:
    with repo_fixture() as repo:
        (repo / "tests" / "test_secrets.py").write_text(
            "import os\ndef test_fake_secret(tmp_path):\n"
            "    token = os.environ['API_KEY']\n"
            "    (tmp_path / 'out.txt').write_text(token)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "securityAssumptionFindings") == []


def test_sensitive_input_credential_paths_require_read_call() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "paths.py").write_text(
            "DEFAULT_KEY = '.ssh/id_ed25519'\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "securityAssumptionFindings") == []
        (repo / "src" / "paths.py").write_text(
            "open('.ssh/id_ed25519', 'w').write(key)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert "sink=" not in findings[0]["evidence"]
        (repo / "src" / "paths.py").write_text(
            "KEY = open('.ssh/id_ed25519').read()\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["evidence"] == "source=credential-file-read"


def test_sensitive_input_added_source_escalates_to_existing_sink() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "existing.py").write_text(
            "def load():\n"
            "    print(TOKEN)\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed sink")
        (repo / "src" / "existing.py").write_text(
            "import os\n"
            "def load():\n"
            "    TOKEN = os.getenv('API_KEY')\n"
            "    print(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]


def test_sensitive_input_indented_python_assignment_escalates_via_identifier_flow() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "indented.py").write_text(
            "import os\n"
            "def load():\n"
            "    TOKEN = os.getenv('API_KEY')\n"
            "    print('starting')\n"
            "    print(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]


def test_sensitive_input_typed_python_assignment_escalates_via_identifier_flow() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "typed.py").write_text(
            "import os\n"
            "from typing import Optional\n"
            "TOKEN: Optional[str] = os.getenv('API_KEY')\n"
            "print(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]


def test_sensitive_input_comparison_does_not_escalate() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "compare.py").write_text(
            "import os\n"
            "def check(TOKEN):\n"
            "    if TOKEN == os.getenv('API_KEY'):\n"
            "        print(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"
        assert "sink=" not in findings[0]["evidence"]


def test_sensitive_input_git_remote_subprocess_is_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "remotes.py").write_text(
            "import subprocess\n"
            "def origin():\n"
            "    return subprocess.run(['git', 'remote', 'get-url', 'origin']).stdout\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["evidence"] == "source=git-remote-url-read"


def test_sensitive_input_git_remote_node_execfile_is_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "remotes.ts").write_text(
            "import { execFile } from 'child_process';\n"
            "export const origin = () => execFile('git', ['remote', 'get-url', 'origin']);\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["evidence"] == "source=git-remote-url-read"


def test_sensitive_input_python_logger_method_call_escalates() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "logged.py").write_text(
            "import logging\n"
            "import os\n"
            "logger = logging.getLogger(__name__)\n"
            "def load():\n"
            "    TOKEN = os.getenv('API_KEY')\n"
            "    logger.error(TOKEN)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]


def test_sensitive_input_console_info_method_call_escalates() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "client.ts").write_text(
            "const TOKEN = process.env.API_KEY; console.info(TOKEN);\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        findings = _advisory_added(data, "securityAssumptionFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert "sink=log-or-console" in findings[0]["evidence"]


def test_sensitive_input_text_output_is_advisory_only() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "secrets.py").write_text("import os\nTOKEN = os.getenv('API_KEY')\n", encoding="utf-8")
        result = run_gate(repo, "check", "--repo", str(repo))
        assert result.returncode == 0
        assert "Advisory findings" in result.stdout
        assert "Warnings:\n- none" in result.stdout


def test_failure_contract_defaults_and_log_only_are_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "client.ts").write_text(
            "export const load = () => fetch('/x').catch(() => null);\n"
            "export const save = () => fetch('/y').catch(err => { console.error(err); });\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        rules = {item["rule"] for item in _advisory_added(data, "slopShapeFindings")}
        assert code == 0, data
        assert rules == {"failure-contract-cheap-default", "failure-contract-log-only"}
        assert data["warnings"] == []


def test_failure_contract_multiline_default_is_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "client.ts").write_text(
            "export async function load() {\n"
            "  try { return await fetch('/x'); }\n"
            "  catch (error) {\n"
            "    console.error(error);\n"
            "    return undefined;\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item["rule"] for item in _advisory_added(data, "slopShapeFindings")] == ["failure-contract-cheap-default"]


def test_failure_contract_stringified_unknown_is_advisory() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "client.ts").write_text(
            "export function load() { try { return read(); } catch (error) { return JSON.stringify(error); } }\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item["rule"] for item in _advisory_added(data, "slopShapeFindings")] == ["failure-contract-stringify"]


def test_failure_contract_preserved_errors_tests_and_unchanged_catches_do_not_hit() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "seed.ts").write_text("export function load() { try { return read(); } catch (error) { return null; } }\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed catch")
        (repo / "src" / "seed.ts").write_text("export function load() { try { return read(); } catch (error) { return null; } }\nexport const ok = 1;\n", encoding="utf-8")
        (repo / "src" / "safe.ts").write_text(
            "export function safe() { try { return read(); } catch (error) { throw mapDomainError(error); } }\n"
            "export const boundary = () => read().catch(error => ({ ok: false, error }));\n",
            encoding="utf-8",
        )
        (repo / "tests" / "test_client.ts").write_text(
            "test('error shape', () => { try { read(); } catch (error) { return JSON.stringify(error); } });\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "slopShapeFindings") == []


def test_failure_contract_log_only_fires_when_try_block_returns() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "client.ts").write_text(
            "export async function load() {\n"
            "  try { return await api.get(); }\n"
            "  catch (error) { logger.error(error); }\n"
            "}\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item["rule"] for item in _advisory_added(data, "slopShapeFindings")] == ["failure-contract-log-only"]


def test_failure_contract_cheap_default_skips_returns_outside_catch_body() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "validate.ts").write_text(
            "export function validate(x: unknown) {\n"
            "  try { parse(x); }\n"
            "  catch (error) { throw mapError(error); }\n"
            "  return false;\n"
            "}\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "slopShapeFindings") == []


def test_wrapper_value_detects_python_ts_and_go_forwarders() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "wrap.py").write_text("def get_user(user_id):\n    return load_user(user_id)\n", encoding="utf-8")
        (repo / "src" / "wrap.ts").write_text(
            "export const getAccount = (id: string): Promise<Account> => loadAccount(id);\n"
            "export const getMany = (...args: Request[]) => loadMany(...args);\n"
            "export function saveUser(user: User): Promise<void> { return persistUser(user); }\n",
            encoding="utf-8",
        )
        (repo / "src" / "wrap.go").write_text("package main\nfunc ReadUser(id string) User {\n    return GetUser(id)\n}\n", encoding="utf-8")
        code, data = check_json(repo)
        findings = [item for item in _advisory_added(data, "slopShapeFindings") if item["rule"] == "wrapper-value"]
        assert code == 0, data
        assert len(findings) == 5
        assert {item["path"] for item in findings} == {"src/wrap.py", "src/wrap.ts", "src/wrap.go"}


def test_wrapper_value_markers_and_framework_overrides_do_not_hit() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "compat.py").write_text(
            "# deprecated compatibility shim for old public API\n"
            "def old_user(user_id): return load_user(user_id)\n"
            "# instrumentation boundary keeps metrics stable\n"
            "def traced_user(user_id): return load_user(user_id)\n"
            "# retry adapter for external boundary\n"
            "def fetch_user(user_id): return load_user(user_id)\n"
            "def render(self): return base_render(self)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item for item in _advisory_added(data, "slopShapeFindings") if item["rule"] == "wrapper-value"] == []


def test_wrapper_value_uses_existing_marker_comments_on_tracked_files() -> None:
    with repo_fixture() as repo:
        (repo / "src" / "compat.ts").write_text(
            "// compatibility boundary for public API\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed marker")
        (repo / "src" / "compat.ts").write_text(
            "// compatibility boundary for public API\n"
            "export const getAccount = (id: string) => loadAccount(id);\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item for item in _advisory_added(data, "slopShapeFindings") if item["rule"] == "wrapper-value"] == []

    with repo_fixture() as repo:
        (repo / "src" / "users.py").write_text(
            "def get_user(user_id):\n"
            "    result = validate(user_id)\n"
            "    return load_user(result)\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed non-forwarder")
        (repo / "src" / "users.py").write_text(
            "def get_user(account_id):\n"
            "    result = validate(user_id)\n"
            "    return load_user(account_id)\n",
            encoding="utf-8",
        )
        code, data = check_json(repo)
        assert code == 0, data
        assert [item for item in _advisory_added(data, "slopShapeFindings") if item["rule"] == "wrapper-value"] == []


def test_verification_mode_missing_full_code_contract_is_advisory() -> None:
    with repo_fixture() as repo:
        declare_full_with_proof_plan(repo, "pytest tests/test_app.py")
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
        code, data = check_json(repo)
        findings = _advisory_added(data, "verificationShapeFindings")
        assert code == 0, data
        assert len(findings) == 1
        assert findings[0]["rule"] == "verification-mode"
        assert "red-green-refactor" in findings[0]["evidence"]
        assert data["warnings"] == []


def test_verification_mode_tokens_are_accepted_and_negations_rejected() -> None:
    for token in ("red-green-refactor", "green-refactor-green", "smoke-check"):
        with repo_fixture() as repo:
            declare_full_with_proof_plan(repo, f"{token}: pytest tests/test_app.py")
            (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
            code, data = check_json(repo)
            assert code == 0, data
            assert _advisory_added(data, "verificationShapeFindings") == []
    negated_plans = (
        "not doing red-green-refactor; pytest tests/test_app.py",
        "without any scheduled or planned red-green-refactor; pytest tests/test_app.py",
        "skip red-green-refactor; pytest tests/test_app.py",
        "skipping red-green-refactor; pytest tests/test_app.py",
        "avoid red-green-refactor; pytest tests/test_app.py",
        "won't run red-green-refactor; pytest tests/test_app.py",
        "wont run red-green-refactor; pytest tests/test_app.py",
        "no: red-green-refactor; pytest tests/test_app.py",
    )
    for proof_plan in negated_plans:
        with repo_fixture() as repo:
            declare_full_with_proof_plan(repo, proof_plan)
            (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
            code, data = check_json(repo)
            assert code == 0, data
            assert len(_advisory_added(data, "verificationShapeFindings")) == 1
    with repo_fixture() as repo:
        declare_full_with_proof_plan(repo, "no red-green-refactor or smoke-check; pytest tests/test_app.py")
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert len(_advisory_added(data, "verificationShapeFindings")) == 1
    with repo_fixture() as repo:
        declare_full_with_proof_plan(repo, "no smoke-check, using red-green-refactor cycle; pytest tests/test_app.py")
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "verificationShapeFindings") == []


def test_verification_mode_policy_tokens_are_configurable() -> None:
    with repo_fixture() as repo:
        policy_path = repo / ".agent" / "lean" / "policy.json"
        policy_path.write_text(json.dumps({"verification_mode_tokens": ["property-check"]}), encoding="utf-8")
        declare_full_with_proof_plan(repo, "property-check: pytest tests/test_app.py")
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
        code, gate_data = check_json(repo)
        assert code == 0, gate_data
        assert _advisory_added(gate_data, "verificationShapeFindings") == []


def test_verification_mode_exempts_minimal_and_test_only_work() -> None:
    with repo_fixture() as repo:
        declare_minimal(repo)
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\nVALUE = 1\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "verificationShapeFindings") == []

    with repo_fixture() as repo:
        declare_full_with_proof_plan(repo, "pytest tests/test_app.py", task_type="test", scope="tests/test_app.py")
        (repo / "tests" / "test_app.py").write_text("from src.app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert _advisory_added(data, "verificationShapeFindings") == []


def test_production_shaped_proof_warns_on_mock_heavy_weak_test() -> None:
    with repo_fixture() as repo:
        body = "from unittest.mock import MagicMock\n\n" + "\n".join(
            f"mock_{idx} = MagicMock()" for idx in range(16)
        ) + "\n\n# from src.app import add\n# assert mock_1 is not None\n\ndef test_fake_surface():\n    result = mock_1()\n    assert result is not None\n"
        (repo / "tests" / "test_fake_surface.py").write_text(body, encoding="utf-8")
        code, data = check_json(repo)
        findings = [item for item in _advisory_added(data, "verificationShapeFindings") if item["rule"] == "production-shaped-proof"]
        assert code == 0, data
        assert len(findings) == 1
        assert "mock_setup_lines" in findings[0]["evidence"]


def test_production_shaped_proof_pytest_fixture_name_does_not_exempt_weak_mock_test() -> None:
    with repo_fixture() as repo:
        body = "import pytest\nfrom unittest.mock import MagicMock\n\n@pytest.fixture\ndef user_fixture():\n    return object()\n" + "\n".join(
            f"mock_{idx} = MagicMock()" for idx in range(14)
        ) + "\n\ndef test_fake_surface(user_fixture):\n    result = mock_1()\n    assert result is not None\n"
        (repo / "tests" / "test_fixture_name.py").write_text(body, encoding="utf-8")
        code, data = check_json(repo)
        findings = [item for item in _advisory_added(data, "verificationShapeFindings") if item["rule"] == "production-shaped-proof"]
        assert code == 0, data
        assert len(findings) == 1


def test_production_shaped_proof_allows_entrypoint_fixture_and_assertion_rich_tests() -> None:
    with repo_fixture() as repo:
        rich = "from unittest.mock import MagicMock\n\n" + "\n".join(
            f"mock_{idx} = MagicMock()" for idx in range(10)
        ) + "\n\ndef test_mock_behavior():\n" + "\n".join(
            f"    assert mock_{idx}.call_count == 0" for idx in range(8)
        ) + "\n"
        (repo / "tests" / "test_behavior.py").write_text(rich, encoding="utf-8")
        boundary = "\n".join([
            "def test_cli_payload_fixture():",
            "    payload = {'hook': 'stop'}",
            "    # external boundary fixture keeps the protocol real",
            *[f"    mock_{idx} = object()" for idx in range(14)],
            "    result = run_gate_payload(payload)",
            "    assert result == {'ok': True}",
        ]) + "\n"
        (repo / "tests" / "test_cli_payload.py").write_text(boundary, encoding="utf-8")
        small = "def test_small():\n    fake = object()\n    assert fake is not None\n"
        (repo / "tests" / "test_small.py").write_text(small, encoding="utf-8")
        code, data = check_json(repo)
        assert code == 0, data
        assert [item for item in _advisory_added(data, "verificationShapeFindings") if item["rule"] == "production-shaped-proof"] == []


def test_delta_reporting_resolved_security_advisory() -> None:
    with repo_fixture() as repo:
        target = repo / "src" / "secrets.py"
        target.write_text("TOKEN = os.getenv('API_KEY')\n", encoding="utf-8")
        git(repo, "add", "src/secrets.py")
        git(repo, "commit", "--no-gpg-sign", "-m", "base secret")
        target.write_text("TOKEN = 'public'\n", encoding="utf-8")
        code, data = check_json(repo)
        group = data["securityAssumptionFindings"]
        assert code == 0, data
        assert len(group["resolved"]) == 1
        assert group["resolved"][0]["rule"] == "sensitive-input"


def test_delta_reporting_improved_security_advisory() -> None:
    with repo_fixture() as repo:
        target = repo / "src" / "secrets.py"
        target.write_text("TOKEN = os.getenv('API_KEY')\nKEY = open('/home/me/.ssh/id_rsa').read()\n", encoding="utf-8")
        git(repo, "add", "src/secrets.py")
        git(repo, "commit", "--no-gpg-sign", "-m", "base secrets")
        target.write_text("TOKEN = os.getenv('API_KEY')\n", encoding="utf-8")
        code, data = check_json(repo)
        improved = data["securityAssumptionFindings"]["improved"]
        assert code == 0, data
        assert len(improved) == 1
        assert improved[0]["line"] == 0
        assert improved[0]["evidence"] == "2 -> 1"


def test_delta_reporting_worsened_security_advisory() -> None:
    with repo_fixture() as repo:
        target = repo / "src" / "secrets.py"
        target.write_text("TOKEN = os.getenv('API_KEY')\n", encoding="utf-8")
        git(repo, "add", "src/secrets.py")
        git(repo, "commit", "--no-gpg-sign", "-m", "base secret")
        target.write_text("TOKEN = os.getenv('API_KEY')\nKEY = open('/home/me/.ssh/id_rsa').read()\n", encoding="utf-8")
        code, data = check_json(repo)
        group = data["securityAssumptionFindings"]
        assert code == 0, data
        assert len(group["added"]) == 1
        assert len(group["worsened"]) == 1
        assert group["worsened"][0]["line"] == 0
        assert group["worsened"][0]["evidence"] == "1 -> 2"


def test_delta_reporting_resolved_slop_shape_advisory() -> None:
    with repo_fixture() as repo:
        target = repo / "src" / "client.ts"
        target.write_text("export const load = () => fetch('/x').catch(() => null);\n", encoding="utf-8")
        git(repo, "add", "src/client.ts")
        git(repo, "commit", "--no-gpg-sign", "-m", "base failure contract")
        target.write_text("export const load = () => fetch('/x').catch(error => { throw error; });\n", encoding="utf-8")
        code, data = check_json(repo)
        resolved = data["slopShapeFindings"]["resolved"]
        assert code == 0, data
        assert len(resolved) == 1
        assert resolved[0]["rule"] == "failure-contract-cheap-default"


def test_delta_reporting_verification_shape_line_drift_is_not_resolved() -> None:
    with repo_fixture() as repo:
        target = repo / "tests" / "test_fake_surface.py"
        body = "from unittest.mock import MagicMock\n\n" + "\n".join(
            f"mock_{idx} = MagicMock()" for idx in range(16)
        ) + "\n\ndef test_fake_surface():\n    result = mock_1()\n    assert result is not None\n"
        target.write_text(body, encoding="utf-8")
        git(repo, "add", "tests/test_fake_surface.py")
        git(repo, "commit", "--no-gpg-sign", "-m", "base weak proof")
        target.write_text("extra = object()\n" + body, encoding="utf-8")
        code, data = check_json(repo)
        group = data["verificationShapeFindings"]
        assert code == 0, data
        assert group["resolved"] == []
        assert group["improved"] == []
        assert group["worsened"] == []


def test_reward_telemetry_disabled_by_default() -> None:
    with repo_fixture() as repo:
        declare_valid(repo)
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b + 0\n", encoding="utf-8")
        run_gate(repo, "posttool", payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}})
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        assert result.returncode == 0, result.stdout
        assert reward_events(repo) == []


def test_reward_telemetry_enabled_logs_aggregate_shape_only() -> None:
    with repo_fixture() as repo:
        (repo / ".agent" / "lean" / "policy.json").write_text(json.dumps({"reward_telemetry_enabled": True}), encoding="utf-8")
        git(repo, "add", ".agent/lean/policy.json")
        git(repo, "commit", "--no-gpg-sign", "-m", "enable telemetry")
        declare_valid(repo)
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b + 0\n", encoding="utf-8")
        run_gate(repo, "posttool", payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}})
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        assert result.returncode == 0, result.stdout
        events = reward_events(repo)
        assert len(events) == 1
        event = events[0]
        assert event["quality_ok"] is True
        assert event["final_error_count"] == 0
        assert event["quality_error_count"] == 0
        assert event["changed_files_count"] >= 1
        assert set(event["advisory_counts"]) == {"securityAssumptionFindings", "slopShapeFindings", "verificationShapeFindings"}
        assert not {"score", "verdict", "critique", "contract", "contract_id", "challenge", "leaderboard"} & set(event)
        assert "src/app.py" not in json.dumps(event, sort_keys=True)


def test_reward_telemetry_append_failure_does_not_break_stop() -> None:
    with repo_fixture() as repo:
        (repo / ".agent" / "lean" / "policy.json").write_text(json.dumps({"reward_telemetry_enabled": True}), encoding="utf-8")
        git(repo, "add", ".agent/lean/policy.json")
        git(repo, "commit", "--no-gpg-sign", "-m", "enable telemetry")
        declare_valid(repo)
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b + 0\n", encoding="utf-8")
        run_gate(repo, "posttool", payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}})
        event_log = repo / ".agent" / "lean" / "state" / "events.jsonl"
        event_log.chmod(0o400)
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        assert result.returncode == 0, result.stderr


def test_reward_telemetry_skips_when_quality_gate_disabled() -> None:
    with repo_fixture() as repo:
        (repo / ".agent" / "lean" / "policy.json").write_text(
            json.dumps({"reward_telemetry_enabled": True, "run_quality_gate_on_stop": False}),
            encoding="utf-8",
        )
        git(repo, "add", ".agent/lean/policy.json")
        git(repo, "commit", "--no-gpg-sign", "-m", "disable quality telemetry")
        declare_valid(repo)
        (repo / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b + 0\n", encoding="utf-8")
        run_gate(repo, "posttool", payload={"cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": "pytest tests/test_app.py"}, "tool_response": {"exit_code": 0}})
        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        assert result.returncode == 0, result.stdout
        assert reward_events(repo) == []


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


def test_global_script_path_env_updates_hook_guidance() -> None:
    with repo_fixture() as repo:
        script_path = "custom/$gate dir/`script`.py"
        quoted_script_path = shlex.quote(script_path)
        result = run_gate(
            repo,
            "session-start",
            payload={"cwd": str(repo), "hook_event_name": "SessionStart"},
            env={"LEAN_CODE_GATE_SCRIPT_PATH": script_path},
        )
        data = json.loads(result.stdout)
        assert quoted_script_path in data["hookSpecificOutput"]["additionalContext"]

        result = run_gate(
            repo,
            "pretool",
            payload={
                "cwd": str(repo),
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n*** Add File: src/new.py\n+value = 1\n*** End Patch"},
            },
            env={"LEAN_CODE_GATE_SCRIPT_PATH": script_path},
        )
        data = json.loads(result.stdout)
        assert quoted_script_path in data["reason"]


def test_repo_root_env_keeps_state_in_target_repo_from_controller_cwd() -> None:
    with repo_fixture() as repo:
        with tempfile.TemporaryDirectory(prefix="gate-controller-", dir=str(repo.parent)) as ctrl:
            controller = Path(ctrl)
            result = run_gate(
                controller,
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
                env={"LEAN_CODE_GATE_REPO_ROOT": str(repo)},
            )
            assert result.returncode == 0, result.stderr
            contract = json.loads((repo / ".agent" / "lean" / "state" / "contract.json").read_text(encoding="utf-8"))
            assert contract["intent"] == "fix small add bug"
            assert contract["repo_root"] == str(repo.resolve())
            assert contract["repo_id"]
            assert not (controller / ".agent" / "lean" / "state" / "contract.json").exists()

            result = run_gate(
                controller,
                "status",
                env={"LEAN_CODE_GATE_REPO_ROOT": str(repo)},
            )
            status = json.loads(result.stdout)
            assert status["contract"]["intent"] == "fix small add bug"
            assert status["runtime"]["repo_id"] == contract["repo_id"]
            assert status["runtime"]["contract_matches_repo"] is True

            result = run_gate(
                controller,
                "pretool",
                payload={
                    "cwd": str(controller),
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-def add(a: int, b: int) -> int:\n+def add(a: int, b: int) -> int:\n*** End Patch"
                    },
                },
                env={"LEAN_CODE_GATE_REPO_ROOT": str(repo)},
            )
            assert result.returncode == 0
            assert result.stdout == ""


def test_hook_resolves_nested_repo_from_changed_path_without_workdir() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        nested = controller / "gate"
        init_repo_fixture(nested)
        declare_minimal(nested)

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: gate/src/app.py\n@@\n-def add(a: int, b: int) -> int:\n+def add(a: int, b: int) -> int:\n*** End Patch"
                },
            },
        )

        assert result.returncode == 0, result.stdout
        assert (nested / ".agent" / "lean" / "state" / "events.jsonl").exists()
        assert not (controller / ".agent" / "lean" / "state" / "events.jsonl").exists()


def test_hook_fails_closed_when_controller_target_is_ambiguous() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        nested = controller / "gate"
        init_repo_fixture(nested)
        declare_minimal(nested)

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"cmd": "git checkout -b test-branch"},
            },
        )

        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "cannot resolve a unique target repo" in data["reason"]
        assert "tool workdir/cwd" in data["reason"]
        assert "No active Lean Change Contract" not in data["reason"]


def test_pathless_bash_uses_remembered_target_and_still_blocks_hidden_write() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        (controller / ".gitignore").write_text(".agent/\nnested/\n", encoding="utf-8")
        (controller / "README.md").write_text("outer repo\n", encoding="utf-8")
        git(controller, "add", ".")
        git(controller, "commit", "--no-gpg-sign", "-m", "init")
        nested = controller / "nested"
        init_repo_fixture(nested)
        declare_minimal(nested)

        result = run_gate(
            controller,
            "session-start",
            payload={"cwd": str(controller), "hook_event_name": "SessionStart", "session_id": "s1", "turn_id": "t1"},
        )
        assert result.returncode == 0
        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(nested / "src" / "app.py"),
                    "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                    "new_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
        )
        assert result.returncode == 0
        assert result.stdout == ""

        result = run_gate(
            controller,
            "user-prompt",
            payload={"cwd": str(controller), "hook_event_name": "UserPromptSubmit", "session_id": "s1", "turn_id": "t2", "prompt": "next"},
        )
        assert result.returncode == 0
        result = run_gate(
            controller,
            "session-start",
            payload={"cwd": str(controller), "hook_event_name": "SessionStart", "session_id": "s1", "turn_id": "t3"},
        )
        assert result.returncode == 0

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"cmd": "cp src/app.py src/app2.py"},
            },
        )

        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "Hidden file-changing Bash blocked" in data["reason"]
        assert "cannot resolve a unique target repo" not in data["reason"]


def test_pathless_bash_ignores_stale_remembered_target() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp) / "controller"
        controller.mkdir()
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        nested = controller / "nested"
        stale = Path(tmp) / "outside"
        init_repo_fixture(nested)
        init_repo_fixture(stale)
        active = controller / ".agent" / "lean" / "state" / "active.json"
        active.parent.mkdir(parents=True)
        active.write_text(json.dumps({"session_id": "s1", "target_root": str(stale)}), encoding="utf-8")

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"cmd": "cp src/app.py src/app2.py"},
            },
        )

        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "cannot resolve a unique target repo" in data["reason"]


def test_path_bearing_edit_uses_actual_nested_repo_over_remembered_target() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        first = controller / "first"
        second = controller / "second"
        init_repo_fixture(first)
        init_repo_fixture(second)
        declare_minimal(first)
        declare_minimal(second)

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(first / "src" / "app.py"),
                    "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                    "new_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
        )
        assert result.returncode == 0

        before_first_events = (first / ".agent" / "lean" / "state" / "events.jsonl").read_text(encoding="utf-8")
        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(second / "src" / "app.py"),
                    "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                    "new_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
        )

        assert result.returncode == 0
        assert result.stdout == ""
        assert (first / ".agent" / "lean" / "state" / "events.jsonl").read_text(encoding="utf-8") == before_first_events
        assert (second / ".agent" / "lean" / "state" / "events.jsonl").exists()


def test_stop_from_controller_checks_nested_repo_without_tool_workdir() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        nested = controller / "calibration"
        init_repo_fixture(nested)
        declare_minimal(nested)

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(nested / "src" / "app.py"),
                    "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                    "new_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
        )
        assert result.returncode == 0
        assert result.stdout == ""

        result = run_gate(controller, "stop", payload={"cwd": str(controller), "hook_event_name": "Stop"})

        assert result.returncode == 0
        assert result.stdout == ""


def test_stop_from_git_controller_prefers_remembered_nested_target() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        git(controller, "init")
        git(controller, "config", "user.email", "test@example.com")
        git(controller, "config", "user.name", "Test User")
        (controller / ".gitignore").write_text(".agent/\nnested/\n", encoding="utf-8")
        (controller / "README.md").write_text("outer repo\n", encoding="utf-8")
        git(controller, "add", ".")
        git(controller, "commit", "--no-gpg-sign", "-m", "init")
        nested = controller / "nested"
        init_repo_fixture(nested)
        declare_minimal(nested)

        result = run_gate(
            controller,
            "pretool",
            payload={
                "cwd": str(controller),
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(nested / "src" / "app.py"),
                    "old_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                    "new_string": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
        )
        assert result.returncode == 0
        assert result.stdout == ""

        (nested / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a - b\n", encoding="utf-8")
        result = run_gate(controller, "stop", payload={"cwd": str(controller), "hook_event_name": "Stop"})

        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "Declared verification has not passed" in data["reason"]


def test_stop_from_controller_ignores_untargeted_dirty_nested_repo() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        nested = controller / "calibration-slopscan"
        init_repo_fixture(nested)
        declare_minimal(nested)
        (nested / "analysis").mkdir()
        (nested / "analysis" / "slopscan_comparison.csv").write_text("repo,score\nx,1\n", encoding="utf-8")

        result = run_gate(controller, "stop", payload={"cwd": str(controller), "hook_event_name": "Stop"})

        assert result.returncode == 0
        assert result.stdout == ""


def test_stop_roots_non_git_controller_does_not_scan_nested_repos() -> None:
    with tempfile.TemporaryDirectory(prefix="gate-controller-") as tmp:
        controller = Path(tmp)
        init_repo_fixture(controller / "nested")
        gate = load_gate_module()

        def fail_scan(root: Path) -> list[Path]:
            raise AssertionError(f"unexpected nested repo scan under {root}")

        gate.nested_git_roots = fail_scan

        assert gate.stop_roots({"cwd": str(controller)}) == []


def test_repo_root_env_rejects_missing_target_repo() -> None:
    with repo_fixture() as repo:
        missing = repo.parent / "missing-target"
        result = run_gate(
            repo,
            "status",
            env={"LEAN_CODE_GATE_REPO_ROOT": str(missing)},
        )
        assert result.returncode != 0
        assert "LEAN_CODE_GATE_REPO_ROOT does not exist" in result.stderr
        assert str(missing) in result.stderr


def test_repo_root_env_rejects_non_git_target_repo() -> None:
    with repo_fixture() as repo:
        with tempfile.TemporaryDirectory(prefix="not-a-repo-", dir=str(repo.parent)) as other:
            result = run_gate(
                repo,
                "status",
                env={"LEAN_CODE_GATE_REPO_ROOT": other},
            )
        assert result.returncode != 0
        assert "LEAN_CODE_GATE_REPO_ROOT is not a git repository" in result.stderr


def test_repo_identity_does_not_persist_origin_url_credentials() -> None:
    with repo_fixture() as repo:
        git(repo, "remote", "add", "origin", "https://user:old-token@example.com/org/repo.git?token=old-token")
        declare_minimal(repo)
        path = repo / ".agent" / "lean" / "state" / "contract.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        assert "origin_url" not in contract
        assert "old-token" not in path.read_text(encoding="utf-8")

        git(repo, "remote", "set-url", "origin", "https://user:new-token@example.com/org/repo.git?token=new-token")
        status = json.loads(run_gate(repo, "status").stdout)
        assert "origin_url" not in status["runtime"]
        assert "new-token" not in json.dumps(status)
        assert status["runtime"]["repo_id"] == contract["repo_id"]
        assert status["runtime"]["contract_matches_repo"] is True

        events = (repo / ".agent" / "lean" / "state" / "events.jsonl").read_text(encoding="utf-8")
        assert "old-token" not in events
        assert "new-token" not in events


def test_contract_for_different_repo_is_rejected() -> None:
    with repo_fixture() as repo_a:
        declare_minimal(repo_a)
        with repo_fixture() as repo_b:
            state = repo_b / ".agent" / "lean" / "state"
            state.mkdir(parents=True)
            shutil.copy2(repo_a / ".agent" / "lean" / "state" / "contract.json", state / "contract.json")

            result = run_gate(
                repo_b,
                "pretool",
                payload={
                    "cwd": str(repo_b),
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-def add(a: int, b: int) -> int:\n+def add(a: int, b: int) -> int:\n*** End Patch"
                    },
                },
            )
            data = json.loads(result.stdout)
            assert data["decision"] == "block"
            assert "belongs to repo_id" in data["reason"]
            assert str(repo_b.resolve()) in data["reason"]
            assert "declare ..." in data["reason"]


def test_unstamped_contract_is_rejected_with_redeclare_hint() -> None:
    with repo_fixture() as repo:
        declare_minimal(repo)
        path = repo / ".agent" / "lean" / "state" / "contract.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract.pop("repo_id")
        path.write_text(json.dumps(contract), encoding="utf-8")

        result = run_gate(
            repo,
            "pretool",
            payload={
                "cwd": str(repo),
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-def add(a: int, b: int) -> int:\n+def add(a: int, b: int) -> int:\n*** End Patch"
                },
            },
        )
        data = json.loads(result.stdout)
        assert data["decision"] == "block"
        assert "missing repo_id" in data["reason"]
        assert "declare ..." in data["reason"]


def test_internal_lean_runtime_files_are_ignored_without_contract() -> None:
    with repo_fixture() as repo:
        state = repo / ".agent" / "lean" / "state"
        cache = repo / ".agent" / "lean" / "__pycache__"
        state.mkdir(parents=True)
        cache.mkdir(parents=True)
        (state / "contract.json").write_text("{not json", encoding="utf-8")
        (cache / "lean_code_gate.cpython-312.pyc").write_bytes(b"runtime")

        result = run_gate(repo, "stop", payload={"cwd": str(repo), "hook_event_name": "Stop"})
        assert result.returncode == 0
        assert result.stdout == ""

        code, data = check_json(repo)
        assert code == 0
        assert data["changedFilesCount"] == 0
        assert all(not str(path).startswith(".agent/lean/") for path in data["changedFilesSample"])

        git(repo, "add", ".agent/lean/state/contract.json", ".agent/lean/__pycache__/lean_code_gate.cpython-312.pyc")
        git(repo, "commit", "--no-gpg-sign", "-m", "runtime state")

        for args in (("--base-ref", "HEAD~1"), ()):
            code, data = check_json(repo, *args)
            assert code == 0
            assert data["changedFilesCount"] == 0
            assert all(not str(path).startswith(".agent/lean/") for path in data["changedFilesSample"])


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


def _seed_then_modify(repo: Path, rel_path: str, seed: str, modified: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(seed, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--no-gpg-sign", "-m", f"seed {rel_path}")
    target.write_text(modified, encoding="utf-8")
    git(repo, "add", rel_path)


def test_python_exact_name_duplicate_across_files_fires_on_tracked_diff() -> None:
    # New symbol with same name as an existing one in another file. The
    # tracked diff puts the def line into ctx.added_lines, where the bug
    # used to suppress reuse via self-call detection. With the
    # SYMBOL_PATTERNS-based filter, the def line is recognised as the
    # searched symbol's own def and skipped, so the candidate stays alive.
    with repo_fixture() as repo:
        (repo / "src" / "parser.py").write_text(
            "def parse_html_payload(blob):\n    return blob.decode('utf-8').strip()\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed parser")
        _seed_then_modify(
            repo,
            "src/parsers.py",
            "# placeholder\n",
            "# placeholder\n"
            "def parse_html_payload(blob):\n"
            "    text = blob.decode('utf-8')\n"
            "    return text.strip()\n",
        )
        code, data = check_json(repo)
        assert code == 2, data
        assert any(
            f["newSymbol"] == "parse_html_payload" and f["existingSymbol"] == "parse_html_payload"
            for f in data["reuseFindings"]
        ), data["reuseFindings"]


def test_go_receiver_method_duplicate_fires_on_tracked_diff() -> None:
    # Same-name receiver methods across two .go files; SYMBOL_PATTERNS["go"]
    # extracts the method name even when a `(r *Repo)` receiver sits between
    # `func` and the name, so line_defines_symbol matches and the def line
    # is skipped — the candidate fires.
    with repo_fixture() as repo:
        (repo / "src" / "parser.go").write_text(
            "package main\n\ntype Repo struct{}\n\n"
            "func (r *Repo) ParseHTMLPayload(blob []byte) string {\n"
            "    return string(blob)\n"
            "}\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed go parser")
        _seed_then_modify(
            repo,
            "src/extra.go",
            "package main\n\ntype Other struct{}\n",
            "package main\n\ntype Other struct{}\n\n"
            "func (o *Other) ParseHTMLPayload(blob []byte) string {\n"
            "    txt := string(blob)\n"
            "    return txt\n"
            "}\n",
        )
        code, data = check_json(repo)
        assert code == 2, data
        assert any(
            f.get("newSymbol") == "ParseHTMLPayload"
            and f.get("existingSymbol") == "ParseHTMLPayload"
            for f in data.get("reuseFindings", [])
        ), data.get("reuseFindings")


def test_shell_function_duplicate_fires_on_tracked_diff() -> None:
    # SYMBOL_PATTERNS["shell"] extracts both `function name() {` and bare
    # `name() {`. Earlier hand-rolled def regex required `def|function|...`
    # keywords and silently missed bare shell defs, so a duplicate shell
    # function across files passed through the gate as ok=true.
    with repo_fixture() as repo:
        (repo / "scripts").mkdir()
        (repo / "scripts" / "userlib.sh").write_text(
            "normalize_user_id() {\n    local id=$1\n    echo \"${id,,}\"\n}\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed shell lib")
        _seed_then_modify(
            repo,
            "scripts/extra.sh",
            "# placeholder\n",
            "# placeholder\n"
            "normalize_user_id() {\n"
            "    local raw=$1\n"
            "    echo \"$(echo \"$raw\" | tr 'A-Z' 'a-z')\"\n"
            "}\n",
        )
        code, data = check_json(repo)
        assert code == 2, data
        assert any(
            f.get("newSymbol") == "normalize_user_id"
            and f.get("existingSymbol") == "normalize_user_id"
            for f in data.get("reuseFindings", [])
        ), data.get("reuseFindings")


def test_rust_tuple_struct_duplicate_fires_on_tracked_diff() -> None:
    # SYMBOL_PATTERNS["rust"] extracts struct/enum/trait names, and a tuple
    # struct definition `pub struct Name(T);` self-matches the call regex
    # `\bName\s*\(` on its own def line. Reusing SYMBOL_PATTERNS in
    # line_defines_symbol covers this for free.
    with repo_fixture() as repo:
        (repo / "src" / "lib.rs").write_text(
            "pub struct ParseHTMLPayload(pub Vec<u8>);\n\nimpl ParseHTMLPayload {\n    pub fn raw(&self) -> &[u8] { &self.0 }\n}\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed rust lib")
        _seed_then_modify(
            repo,
            "src/extra.rs",
            "// placeholder\n",
            "// placeholder\n"
            "pub struct ParseHTMLPayload(pub String);\n\n"
            "impl ParseHTMLPayload {\n"
            "    pub fn text(&self) -> &str { &self.0 }\n"
            "}\n",
        )
        code, data = check_json(repo)
        assert code == 2, data
        assert any(
            f.get("newSymbol") == "ParseHTMLPayload"
            and f.get("existingSymbol") == "ParseHTMLPayload"
            for f in data.get("reuseFindings", [])
        ), data.get("reuseFindings")


def test_default_arg_call_on_def_line_does_not_falsely_suppress_reuse() -> None:
    # Precision: a def line for symbol B that calls existing symbol A in a
    # default arg must not be treated as a "self def" of A. The filter
    # skips only the def of the searched symbol.
    #
    # Names share tokens so same_behavior_name returns nonzero — making
    # the candidate eligible to reach symbol_is_called_nearby's decision.
    # If the def-line filter were blanket ("any def line skipped"), the
    # default-arg call to format_currency_amount would be hidden; the
    # detector would then see no call, treat it as reuse, and fire a false
    # finding for format_currency_label vs format_currency_amount.
    mod = _load_gate_module()
    score, _reason = mod.same_behavior_name(
        mod.SymbolDef(name="format_currency_label", path="src/wrapper.py", line=1, kind="function", language="python", tokens=mod.split_name_tokens("format_currency_label"), source="added"),
        mod.SymbolDef(name="format_currency_amount", path="src/format.py", line=1, kind="function", language="python", tokens=mod.split_name_tokens("format_currency_amount"), source="baseline"),
    )
    assert score > 0, f"test precondition failed: same_behavior_name returned {score}; choose names with more shared tokens"

    with repo_fixture() as repo:
        (repo / "src" / "format.py").write_text(
            "def format_currency_amount(amount):\n"
            "    return f\"${amount:.2f}\"\n",
            encoding="utf-8",
        )
        git(repo, "add", ".")
        git(repo, "commit", "--no-gpg-sign", "-m", "seed format")
        _seed_then_modify(
            repo,
            "src/wrapper.py",
            "# placeholder\n",
            "# placeholder\n"
            "from src.format import format_currency_amount\n"
            "def format_currency_label(amount, prefix=format_currency_amount()):\n"
            "    return f\"Total: {prefix}\"\n",
        )
        code, data = check_json(repo)
        assert code in (0, 2), data
        assert not any(
            f.get("newSymbol") == "format_currency_label"
            and f.get("existingSymbol") == "format_currency_amount"
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
    test_p0_advisory_groups_are_empty_and_compatible,
    test_sensitive_input_source_only_is_advisory,
    test_sensitive_input_source_and_sink_is_stronger_advisory,
    test_sensitive_input_high_requires_same_line_or_source_identifier_flow,
    test_sensitive_input_unchanged_and_broad_secret_names_do_not_hit,
    test_sensitive_input_test_fixtures_do_not_hit,
    test_sensitive_input_credential_paths_require_read_call,
    test_sensitive_input_added_source_escalates_to_existing_sink,
    test_sensitive_input_indented_python_assignment_escalates_via_identifier_flow,
    test_sensitive_input_typed_python_assignment_escalates_via_identifier_flow,
    test_sensitive_input_comparison_does_not_escalate,
    test_sensitive_input_git_remote_subprocess_is_advisory,
    test_sensitive_input_git_remote_node_execfile_is_advisory,
    test_sensitive_input_python_logger_method_call_escalates,
    test_sensitive_input_console_info_method_call_escalates,
    test_sensitive_input_text_output_is_advisory_only,
    test_failure_contract_defaults_and_log_only_are_advisory,
    test_failure_contract_multiline_default_is_advisory,
    test_failure_contract_stringified_unknown_is_advisory,
    test_failure_contract_preserved_errors_tests_and_unchanged_catches_do_not_hit,
    test_failure_contract_log_only_fires_when_try_block_returns,
    test_failure_contract_cheap_default_skips_returns_outside_catch_body,
    test_wrapper_value_detects_python_ts_and_go_forwarders,
    test_wrapper_value_markers_and_framework_overrides_do_not_hit,
    test_wrapper_value_uses_existing_marker_comments_on_tracked_files,
    test_verification_mode_missing_full_code_contract_is_advisory,
    test_verification_mode_tokens_are_accepted_and_negations_rejected,
    test_verification_mode_policy_tokens_are_configurable,
    test_verification_mode_exempts_minimal_and_test_only_work,
    test_production_shaped_proof_warns_on_mock_heavy_weak_test,
    test_production_shaped_proof_pytest_fixture_name_does_not_exempt_weak_mock_test,
    test_production_shaped_proof_allows_entrypoint_fixture_and_assertion_rich_tests,
    test_delta_reporting_resolved_security_advisory,
    test_delta_reporting_improved_security_advisory,
    test_delta_reporting_worsened_security_advisory,
    test_delta_reporting_resolved_slop_shape_advisory,
    test_delta_reporting_verification_shape_line_drift_is_not_resolved,
    test_reward_telemetry_disabled_by_default,
    test_reward_telemetry_enabled_logs_aggregate_shape_only,
    test_reward_telemetry_append_failure_does_not_break_stop,
    test_reward_telemetry_skips_when_quality_gate_disabled,
    test_declare_rejects_code_contract_without_preflight,
    test_minimal_preflight_allows_micro_bugfix_without_cargo_fields,
    test_unknown_task_type_is_rejected_instead_of_forcing_full_preflight,
    test_global_script_path_env_updates_hook_guidance,
    test_repo_root_env_keeps_state_in_target_repo_from_controller_cwd,
    test_hook_resolves_nested_repo_from_changed_path_without_workdir,
    test_hook_fails_closed_when_controller_target_is_ambiguous,
    test_pathless_bash_uses_remembered_target_and_still_blocks_hidden_write,
    test_pathless_bash_ignores_stale_remembered_target,
    test_path_bearing_edit_uses_actual_nested_repo_over_remembered_target,
    test_stop_from_controller_checks_nested_repo_without_tool_workdir,
    test_stop_from_git_controller_prefers_remembered_nested_target,
    test_stop_from_controller_ignores_untargeted_dirty_nested_repo,
    test_stop_roots_non_git_controller_does_not_scan_nested_repos,
    test_repo_root_env_rejects_missing_target_repo,
    test_repo_root_env_rejects_non_git_target_repo,
    test_repo_identity_does_not_persist_origin_url_credentials,
    test_contract_for_different_repo_is_rejected,
    test_unstamped_contract_is_rejected_with_redeclare_hint,
    test_internal_lean_runtime_files_are_ignored_without_contract,
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
    test_python_exact_name_duplicate_across_files_fires_on_tracked_diff,
    test_go_receiver_method_duplicate_fires_on_tracked_diff,
    test_shell_function_duplicate_fires_on_tracked_diff,
    test_rust_tuple_struct_duplicate_fires_on_tracked_diff,
    test_default_arg_call_on_def_line_does_not_falsely_suppress_reuse,
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
