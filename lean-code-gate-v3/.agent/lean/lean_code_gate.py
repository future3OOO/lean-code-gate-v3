#!/usr/bin/env python3
"""Lean Code Gate v3.

Deterministic contract, scope, verification, and changed-code quality gates for
coding agents. The script is intentionally dependency-free so hooks can run in a
fresh repository without importing project packages.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import signal
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

VERSION = "3.0.0"
STATE_DIR = ".agent/lean/state"
POLICY_FILE = ".agent/lean/policy.json"

DEFAULT_POLICY: dict[str, object] = {
    "default_max_files": 3,
    "default_max_added_lines": 120,
    "default_max_changed_lines": 240,
    "require_verify_after_mutation": True,
    "require_bugfix_test_change": True,
    "require_explicit_task_type": True,
    "require_preflight_for_code": True,
    "require_reuse_path_for_code": True,
    "allow_minimal_preflight": True,
    "minimal_preflight_max_files": 2,
    "minimal_preflight_max_added_lines": 30,
    "minimal_preflight_max_changed_lines": 80,
    "minimal_preflight_task_types": ["bugfix", "test", "docs", "config"],
    "block_broad_scope": True,
    "block_dependency_changes_without_flag": True,
    "block_config_changes_without_flag": False,
    "block_hidden_bash_writes": True,
    "run_quality_gate_on_stop": True,
    "fail_on_quality_warnings": False,
    # max_design_markers: 4 (was 2): requires all 4 DESIGN_RE categories to
    # match. Calibrated against Pydantic's _generate_schema.py (2922 lines,
    # density 1.4/100, was firing as FP). Combined with density gating >= 3.0
    # for files >= 100 lines, allows typing-heavy frameworks while still
    # flagging gratuitous abstraction in small surfaces (4 markers in 7 lines
    # = 57/100 density still trips the small-file branch).
    "max_design_markers": 4,
    "max_design_marker_density_per_100_lines": 3.0,
    "allowed_broad_globs": ["src/**", "lib/**", "app/**", "tests/**", "test/**"],
    "bloat_new_file_warn_lines": 500,
    "bloat_new_file_error_lines": 800,
    "bloat_large_file_lines": 1500,
    "bloat_large_file_must_shrink": False,
    "bloat_large_file_growth_lines": 80,
    "bloat_file_growth_lines": 250,
    "bloat_total_added_warn_lines": 500,
    "bloat_total_added_error_lines": 1000,
    "bloat_add_delete_warn_ratio": 4,
    "bloat_add_delete_error_ratio": 6,
    "quality_max_index_files": 4000,
    "quality_max_index_file_bytes": 500000,
    "quality_max_index_symbols": 25000,
    "reuse_detector_mode": "conservative",
    "reuse_error_score": 90,
    "reuse_warning_score": 45,
    "reuse_min_duplicate_count": 3,
    "reuse_suppress_private_public_siblings": True,
    "framework_override_names": [
        "validate", "clean", "save", "save_model", "save_formset",
        "get_queryset", "get_form", "get_form_kwargs", "get_context_data",
        "get_object", "get_serializer", "get_serializer_class",
        "as_sql", "as_dict", "as_view",
        "to_python", "to_internal_value", "to_representation",
        "form_valid", "form_invalid",
        "__init__", "__call__", "__enter__", "__exit__",
        "__iter__", "__next__", "__len__", "__contains__",
        "__getitem__", "__setitem__", "__delitem__",
        "__set__", "__get__", "__delete__", "__set_name__",
        "__hash__", "__eq__", "__lt__", "__gt__", "__le__", "__ge__",
        "__repr__", "__str__", "__bool__",
        "componentDidMount", "componentDidUpdate", "componentWillUnmount",
        "render", "shouldComponentUpdate", "getDerivedStateFromProps",
        "ngOnInit", "ngOnDestroy", "ngOnChanges",
    ],
    "excluded_path_globs": [
        "**/migrations/**",
        "**/generated/**",
        "**/__generated__/**",
        "**/_generated/**",
        "**/*.pb.go",
        "**/*.pb.cc",
        "**/*.pb.h",
        "**/*.pb.py",
        "**/*_pb2.py",
        "**/*_pb2_grpc.py",
        "**/*.generated.*",
        "**/dist-cjs/**",
        "**/dist-es/**",
        "**/dist-types/**",
        "clients/*/src/commands/**",
        "clients/*/src/models/**",
        "clients/*/src/schemas/**",
        "clients/*/src/protocols/**",
        "clients/*/src/waiters/**",
        "**/admin/static/admin/**",
        "**/static/admin/**",
        "docs_src/**",
        "**/python_version.py",
    ],
}

MUTATING_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch", "ApplyPatch"}
DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "bun.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
}
CONFIG_GLOBS = [
    ".github/workflows/*",
    "*.config.js",
    "*.config.ts",
    "*.config.mjs",
    "*.config.cjs",
    "tsconfig*.json",
    "vite.config.*",
    "webpack.config.*",
    "jest.config.*",
    "vitest.config.*",
    "eslint.config.*",
    ".eslintrc*",
    ".prettierrc*",
    "mypy.ini",
    "ruff.toml",
    ".ruff.toml",
    "pytest.ini",
    "tox.ini",
]
TEST_GLOBS = [
    "tests/**",
    "test/**",
    "**/*_test.*",
    "**/*.test.*",
    "**/*.spec.*",
    "**/test_*.py",
    "**/__tests__/**",
]
BROAD_SCOPE = {"*", "**", "**/*", ".", "./", "./**", "./**/*", "src", "lib", "app"}
PLACEHOLDER_TEXT = {"", "n/a", "na", "none", "unknown", "tbd", "todo", "placeholder", "same", "existing"}
VERIFY_HINTS = (
    "test",
    "pytest",
    "vitest",
    "jest",
    "mocha",
    "go test",
    "cargo test",
    "mvn test",
    "gradle test",
    "ruff",
    "eslint",
    "tsc",
    "mypy",
    "black --check",
    "prettier --check",
    "npm run lint",
    "pnpm lint",
    "yarn lint",
    "lean_code_gate.py check",
)
HIDDEN_WRITE_RE = re.compile(
    r"(^|[;&|]\s*)(cat\s+>\s|tee\s|printf\s+.*>\s|echo\s+.*>\s)|"
    r"\b(sed\s+-i|perl\s+-pi|rm|mv|cp|mkdir|touch|chmod|chown)\b|"
    r"\bgit\s+(checkout|reset|clean|apply|am|rm|mv|add|commit|rebase|merge)\b|"
    r"\b(npm\s+(install|i|add)|pnpm\s+add|yarn\s+add|bun\s+add|pip\s+install|poetry\s+add|uv\s+add|go\s+get|cargo\s+add)\b|"
    r"\b(write_text|write_bytes|open\(.{0,80},\s*['\"]w|fs\.writeFile|fs\.appendFile)\b",
    re.S,
)
DESIGN_RE = [
    (re.compile(r"\bclass\s+\w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)\b"), "pattern-named class"),
    (re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?New\w*(Factory|Builder|Manager|Registry|Strategy|Adapter|Provider)\b"), "pattern-named factory function"),
    # Rust pattern intentionally broader than Python/JS (State/Context/Scope
    # added). Rust's type-alias system is commonly used for abstraction
    # layering (e.g., pub type ParserState, pub type RequestContext) in ways
    # the Python/JS class pattern isn't. Asymmetry is calibrated, not a bug.
    (re.compile(r"\bpub\s+type\s+\w*(State|Manager|Strategy|Adapter|Provider|Factory|Builder|Registry|Context|Scope)\b"), "rust type-alias abstraction"),
    (re.compile(r"\b(Abstract[A-Z]\w*|Base[A-Z]\w*)\b"), "abstract/base type"),
    (re.compile(r"\b(Protocol|ABC|abc\.ABC|TypeVar|Generic\[)\b"), "generic typing abstraction"),
    (re.compile(r"\b(plugin|middleware|strategy|extensible|extension point|feature[_ -]?flag)\b", re.I), "extension machinery"),
]

SOURCE_EXTENSIONS = {
    ".cjs",
    ".cts",
    ".go",
    ".js",
    ".jsx",
    ".mjs",
    ".mts",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
}
EXCLUDE_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "venv",
}
TEST_MARKERS = (
    "/__fixtures__/",
    "/__mocks__/",
    "/__snapshots__/",
    "/__tests__/",
    "/fixture/",
    "/fixtures/",
    "/generated/",
    "/snapshots/",
    "/test/",
    "/tests/",
)
BINARY_EXTENSIONS = {
    ".avif",
    ".bin",
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lock",
    ".map",
    ".pdf",
    ".png",
    ".snap",
    ".svg",
    ".webp",
    ".zip",
}
GENERAL_ESCAPE_RULES = [
    re.compile(r"\b(?:" + "|".join(["TO" + "DO", "FIX" + "ME", "HA" + "CK"]) + r")\b", re.I),
    re.compile("@ts" + r"-ignore\b"),
    re.compile("@ts" + r"-expect-error\b"),
    re.compile("eslint" + r"-disable\b"),
    re.compile(r"#\s*type:\s*" + "ignore" + r"\b", re.I),
    re.compile(r"#\s*" + "no" + r"qa\b", re.I),
    re.compile(r"\|\|\s*true\b"),
]
PYTHON_ESCAPE_RULES = [
    re.compile(r"\btyping\." + "An" + "y" + r"\b"),
    re.compile(r":\s*" + "An" + "y" + r"\b"),
    re.compile(r"\b" + "ca" + "st" + r"\s*\("),
    re.compile(r"^\s*except\s*:\s*$"),
    re.compile(r"^\s*except\s+Exception\s*:\s*pass\s*$"),
]
TS_ESCAPE_RULES = [
    re.compile(r":\s*any\b"),
    re.compile(r"<\s*any\s*>"),
    re.compile(r"\bas\s+any\b"),
    re.compile(r"\bas\s+unknown\s+as\b"),
]
EMPTY_CATCH_RULES = [
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}", re.S),
    re.compile(r"\bcatch\s*\{\s*\}", re.S),
    re.compile(r"\.catch\s*\(\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{\s*\}\s*\)", re.S),
    re.compile(r"except\s+Exception\s*:\s*\n\s*pass\b", re.S),
    re.compile(r"except\s*:\s*\n\s*pass\b", re.S),
]
GENERIC_SYMBOLS = {
    "app",
    "config",
    "create",
    "delete",
    "get",
    "handler",
    "index",
    "init",
    "load",
    "main",
    "post",
    "put",
    "render",
    "run",
    "save",
    "setup",
    "start",
    "stop",
    "update",
}
REUSE_ACTION_TOKENS = {
    "build",
    "dedupe",
    "deduplicate",
    "fetch",
    "filter",
    "format",
    "load",
    "map",
    "normalize",
    "parse",
    "read",
    "resolve",
    "retry",
    "sanitize",
    "sync",
    "validate",
    "walk",
    "write",
}
GENERIC_MATCH_TOKENS = {
    "and",
    "code",
    "content",
    "data",
    "for",
    "get",
    "handle",
    "has",
    "is",
    "load",
    "parse",
    "read",
    "request",
    "response",
    "result",
    "results",
    "signal",
    "state",
    "text",
    "url",
    "value",
    "wait",
    "with",
}
RISKY_BLOCK_RULE = re.compile(
    r"\b(?:for|while|map|filter|reduce|retry|fetch|read|write|parse|normalize|validate|format|resolve|dedupe|deduplicate)\b",
    re.I,
)
SYMBOL_PATTERNS = {
    "python": [
        ("function", re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\s*(?:\(|:)")),
    ],
    "javascript": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b")),
        (
            "function",
            re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
            ),
        ),
    ],
    "go": [("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\("))],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][\w]*)\s*\(")),
        ("type", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][\w]*)\b")),
    ],
    "shell": [("function", re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)"))],
    "php": [
        ("function", re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+([A-Za-z_][\w]*)\s*\(")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][\w]*)\b")),
    ],
    "ruby": [
        ("function", re.compile(r"^\s*def\s+([A-Za-z_][\w!?=]*)\b")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][\w:]*)\b")),
    ],
}


@dataclass(frozen=True)
class Numstat:
    added: int
    deleted: int
    path: str


@dataclass(frozen=True)
class SymbolDef:
    name: str
    path: str
    line: int
    kind: str
    language: str
    tokens: tuple[str, ...]
    source: str
    context_boost: int = 0


@dataclass(frozen=True)
class ReuseFinding:
    severity: str
    score: int
    new_symbol: str
    new_file: str
    new_line: int
    existing_symbol: str
    existing_file: str
    existing_line: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "score": self.score,
            "newSymbol": self.new_symbol,
            "newFile": self.new_file,
            "newLine": self.new_line,
            "existingSymbol": self.existing_symbol,
            "existingFile": self.existing_file,
            "existingLine": self.existing_line,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GateContext:
    repo: Path
    changed_files: set[str]
    untracked: set[str]
    raw_diff: str
    base_for_file: str
    numstats: list[Numstat]
    added_lines: dict[str, list[tuple[int, str]]]

    def added_lines_with_untracked(self, *, production_only: bool) -> dict[str, list[tuple[int, str]]]:
        out = {path: list(lines) for path, lines in self.added_lines.items()}
        predicate = is_production_source_path if production_only else is_source_path
        for rel_path in sorted(self.untracked):
            if predicate(rel_path):
                text = read_file(self.repo / rel_path)
                if text is not None:
                    out.setdefault(rel_path, []).extend((idx, line) for idx, line in enumerate(text.splitlines(), 1))
        return out


def run_process(cmd: list[str], cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        # text=True implies strict utf-8 decoding which crashes when git diff
        # output contains non-utf-8 bytes (e.g. binary patches in long
        # multi-commit windows). Use encoding+errors='replace' instead so
        # the gate can keep running and just lose offending bytes.
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name != "nt"),
        )
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", "process group did not terminate cleanly"
        return subprocess.CompletedProcess(cmd, 124, stdout, stderr or "command timed out")


def sh(cmd: list[str], cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return run_process(cmd, cwd, timeout)


def git_toplevel(start: Path) -> Path | None:
    result = sh(["git", "rev-parse", "--show-toplevel"], start if start.is_dir() else start.parent)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return None


def repo_root(cwd: str | None = None) -> Path:
    configured = os.environ.get("LEAN_CODE_GATE_REPO_ROOT")
    if cwd:
        payload_start = Path(cwd).expanduser()
        if payload_start.exists():
            payload_root = git_toplevel(payload_start.resolve())
            if payload_root is not None:
                return payload_root

    start = Path(configured or cwd or os.getcwd()).expanduser()
    if configured and not start.exists():
        raise SystemExit(f"LEAN_CODE_GATE_REPO_ROOT does not exist: {start}")
    if not configured and not start.exists():
        start = Path(os.getcwd())
    start = start.resolve()
    configured_root = git_toplevel(start)
    if configured_root is not None:
        return configured_root
    if configured:
        raise SystemExit(f"LEAN_CODE_GATE_REPO_ROOT is not a git repository: {start}")
    return start


def tool_command(tool_input: dict[str, object]) -> str:
    return str(tool_input.get("command") or tool_input.get("cmd") or "")


def has_nested_git_repo(root: Path) -> bool:
    return any(path.exists() for path in root.glob("*/.git"))


def nested_git_roots(root: Path) -> list[Path]:
    return sorted(path.parent.resolve() for path in root.glob("*/.git") if path.exists())


def checked_hook_root(event: str | None, payload: dict[str, object], tool: str, tool_input: dict[str, object], *, require_unambiguous: bool = False) -> Path | None:
    try:
        return hook_root(payload, tool, tool_input, require_unambiguous=require_unambiguous)
    except ValueError as error:
        if event:
            deny(event, str(error))
        return None


def hook_root(payload: dict[str, object], tool: str, tool_input: dict[str, object], *, require_unambiguous: bool = False) -> Path:
    tool_cwd = str(tool_input.get("workdir") or tool_input.get("cwd") or "") or None
    if tool_cwd:
        return repo_root(tool_cwd)

    root = repo_root(str(payload.get("cwd") or "") or None)
    is_mutating = mutating(tool, tool_input)
    if not is_mutating and not require_unambiguous:
        return root

    if is_mutating:
        path_roots: set[Path] = set()
        for value in facts(root, tool, tool_input).get("paths", []):
            if isinstance(value, str):
                path = (root / value).resolve()
                found = git_toplevel(path if path.is_dir() else path.parent)
                if found is not None and found != root and root in found.parents:
                    path_roots.add(found)
        if len(path_roots) == 1:
            return next(iter(path_roots))
        if len(path_roots) > 1:
            raise ValueError("Lean Code Gate could not choose between nested target repos: " + ", ".join(str(path) for path in sorted(path_roots)))

    if has_nested_git_repo(root):
        raise ValueError(
            "Lean Code Gate cannot resolve a unique target repo from controller folder "
            f"{root}. Hook payload did not include tool workdir/cwd. Start the session "
            "inside the target repo, set LEAN_CODE_GATE_REPO_ROOT as a fallback, or use a hook runtime that passes tool workdir."
        )

    return root


def stop_roots(payload: dict[str, object]) -> list[Path]:
    root = repo_root(str(payload.get("cwd") or "") or None)
    nested = nested_git_roots(root)
    if not nested:
        return [root]
    targets = active_state(root).get("target_roots")
    if isinstance(targets, list):
        roots = []
        for target in targets:
            if isinstance(target, str):
                found = git_toplevel(Path(target).expanduser().resolve())
                if found is not None and found != root and root in found.parents:
                    roots.append(found)
        if roots:
            return sorted(set(roots))
    return [root] if git_toplevel(root) == root else []


def remember_target_root(payload: dict[str, object], root: Path) -> None:
    controller = repo_root(str(payload.get("cwd") or "") or None)
    if controller == root or not has_nested_git_repo(controller):
        return
    active = active_state(controller)
    existing = active.get("target_roots")
    roots = {str(root.resolve())}
    if isinstance(existing, list):
        roots.update(str(value) for value in existing if isinstance(value, str))
    active["target_roots"] = sorted(roots)
    write_json(active_path(controller), active)


def git_common_dir(root: Path) -> Path:
    result = sh(["git", "rev-parse", "--git-common-dir"], root, timeout=10)
    if result.returncode != 0 or not result.stdout.strip():
        return (root / ".git").resolve()
    value = Path(result.stdout.strip())
    return (value if value.is_absolute() else root / value).resolve()


def repo_identity(root: Path) -> dict[str, str]:
    resolved_root = root.resolve()
    common_dir = git_common_dir(resolved_root)
    material = "\0".join((str(resolved_root), str(common_dir)))
    return {
        "repo_id": hashlib.sha256(material.encode("utf-8")).hexdigest()[:12],
        "repo_root": str(resolved_root),
        "git_common_dir": str(common_dir),
        "state_dir": str(resolved_root / STATE_DIR),
    }


def state_dir(root: Path) -> Path:
    path = root / STATE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def policy(root: Path) -> dict[str, object]:
    merged = dict(DEFAULT_POLICY)
    loaded = read_json(root / POLICY_FILE, {})
    if isinstance(loaded, dict):
        merged.update(loaded)
    return merged


def active_path(root: Path) -> Path:
    return state_dir(root) / "active.json"


def active_state(root: Path) -> dict[str, object]:
    loaded = read_json(active_path(root), {})
    return loaded if isinstance(loaded, dict) else {}


def contract_path(root: Path) -> Path:
    return state_dir(root) / "contract.json"


def events_path(root: Path) -> Path:
    return state_dir(root) / "events.jsonl"


def contract(root: Path) -> dict[str, object]:
    loaded = read_json(contract_path(root), {})
    return loaded if isinstance(loaded, dict) else {}


def log_event(root: Path, event: dict[str, object]) -> None:
    item = {"time": time.time(), **event}
    with events_path(root).open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, sort_keys=True) + "\n")


def events(root: Path, limit: int = 200) -> list[dict[str, object]]:
    path = events_path(root)
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def hook_input() -> dict[str, object]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, separators=(",", ":")))


def deny(event: str, reason: str) -> None:
    if event == "PreToolUse":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
                "decision": "block",
                "reason": reason,
            }
        )
    elif event == "PermissionRequest":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "deny", "message": reason},
                }
            }
        )
    else:
        emit({"decision": "block", "reason": reason})


def command_hint(root: Path | None = None) -> str:
    script = os.environ.get("LEAN_CODE_GATE_SCRIPT_PATH") or ".agent/lean/lean_code_gate.py"
    command = f"PYTHONDONTWRITEBYTECODE=1 python3 -B -S {shlex.quote(script)}"
    if root is not None and os.environ.get("LEAN_CODE_GATE_REPO_ROOT"):
        return f"LEAN_CODE_GATE_REPO_ROOT={shlex.quote(str(root))} {command}"
    return command


def context(event: str) -> None:
    message = (
        "Lean Code Gate v3 active. Inspect first, then declare the smallest Lean Change Contract before mutating files. "
        f"Micro-fix form: `{command_hint()} declare "
        "--minimal-preflight --intent \"...\" --scope \"file1,file2\" --task-type bugfix --verify \"pytest path/to/test.py\"`. "
        "Full production form adds --affected-surface, --authoritative-contract, --invariant, --reuse-path or --no-reuse-reason, "
        "--proof-plan, and --risk-check. Stop runs the quality gate: no fake-green suppressions, duplicate blocks, "
        "high-confidence helper reimplementation, temp artifacts, or bloat."
    )
    emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}})


def norm_path(value: str) -> str:
    return value.strip().replace(os.sep, "/").removeprefix("./")


def norm_list(csv: str | None) -> list[str]:
    return [norm_path(item) for item in (csv or "").split(",") if item.strip()]


def rel(root: Path, raw: str) -> str | None:
    if not raw:
        return None
    value = raw.strip().strip("'\"")
    if value in {"/dev/null", "dev/null"}:
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    try:
        path = Path(value)
        resolved = (path if path.is_absolute() else root / path).resolve()
        return resolved.relative_to(root).as_posix()
    except Exception:
        return None


def match(path: str, globs: list[str]) -> bool:
    return any(path == glob or fnmatch.fnmatch(path, glob) or ("/" not in glob and Path(path).name == glob) for glob in globs)


def internal_gate_path(path: str) -> bool:
    normalized = norm_path(path)
    return (
        normalized == STATE_DIR
        or normalized.startswith(STATE_DIR + "/")
        or normalized == ".agent/lean/__pycache__"
        or normalized.startswith(".agent/lean/__pycache__/")
        or (normalized.startswith(".agent/lean/") and normalized.endswith(".pyc"))
    )


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return run_process(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args], repo, timeout=15)


def git_text(repo: Path, args: list[str]) -> str:
    result = run_git(repo, args)
    return result.stdout if result.returncode == 0 else ""


def git_ok(repo: Path, args: list[str]) -> bool:
    return run_git(repo, args).returncode == 0


def read_git_file(repo: Path, ref: str, rel_path: str) -> str | None:
    if not ref:
        return None
    result = run_git(repo, ["show", f"{ref}:{rel_path}"])
    return result.stdout if result.returncode == 0 else None


def parse_name_status(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out[norm_path(parts[-1])] = parts[0]
    return out


def parse_status_paths(raw: str) -> tuple[dict[str, str], set[str]]:
    changed: dict[str, str] = {}
    untracked: set[str] = set()
    records = [item for item in raw.split("\0") if item]
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4:
            index += 1
            continue
        xy = record[:2]
        path = norm_path(record[3:])
        changed[path] = xy
        if xy == "??":
            untracked.add(path)
        if xy[0] in {"R", "C"} and index + 1 < len(records):
            changed[norm_path(records[index + 1])] = xy
            index += 1
        index += 1
    return changed, untracked


def parse_numstat(raw: str) -> list[Numstat]:
    records: list[Numstat] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            added = int(parts[0])
            deleted = int(parts[1])
        except ValueError:
            added = 10000
            deleted = 10000
        records.append(Numstat(added=added, deleted=deleted, path=norm_path("\t".join(parts[2:]))))
    return records


def parse_name_only(raw: str) -> set[str]:
    return {norm_path(line) for line in raw.splitlines() if norm_path(line)}


def added_file_paths(root: Path) -> set[str]:
    status, untracked = parse_status_paths(git_text(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]))
    added = set(untracked)
    for path, state in status.items():
        if internal_gate_path(path):
            continue
        if state == "??" or "A" in state or "C" in state:
            added.add(path)
    return {path for path in added if not internal_gate_path(path)}


def merge_numstats(records: Iterable[Numstat]) -> dict[str, Numstat]:
    merged: dict[str, Numstat] = {}
    for record in records:
        previous = merged.get(record.path)
        if previous is None:
            merged[record.path] = record
        else:
            merged[record.path] = Numstat(previous.added + record.added, previous.deleted + record.deleted, record.path)
    return merged


def status_snapshot(root: Path) -> dict[str, object]:
    status, untracked = parse_status_paths(git_text(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]))
    status = {path: state for path, state in status.items() if not internal_gate_path(path)}
    untracked = {path for path in untracked if not internal_gate_path(path)}
    numstats = merge_numstats(record for record in parse_numstat(git_text(root, ["diff", "HEAD", "--numstat"])) if not internal_gate_path(record.path))
    untracked_lines = {}
    for path in untracked:
        text = read_file(root / path)
        if text is not None:
            untracked_lines[path] = len(text.splitlines())
    return {
        "status": status,
        "numstat": {path: [stat.added, stat.deleted] for path, stat in numstats.items()},
        "untrackedLines": untracked_lines,
        "at": time.time(),
    }


def baseline(root: Path) -> dict[str, object]:
    return status_snapshot(root)


def delta(root: Path, current_contract: dict[str, object]) -> dict[str, object]:
    base = current_contract.get("baseline") or {}
    now = status_snapshot(root)
    base_status = base.get("status") if isinstance(base.get("status"), dict) else {}
    base_numstat = base.get("numstat") if isinstance(base.get("numstat"), dict) else {}
    base_untracked = base.get("untrackedLines") if isinstance(base.get("untrackedLines"), dict) else {}
    now_status = now.get("status") if isinstance(now.get("status"), dict) else {}
    now_numstat = now.get("numstat") if isinstance(now.get("numstat"), dict) else {}
    now_untracked = now.get("untrackedLines") if isinstance(now.get("untrackedLines"), dict) else {}

    files: set[str] = set()
    for path, value in now_status.items():
        if value != base_status.get(path):
            files.add(path)
    for path, value in now_numstat.items():
        if list(value) != list(base_numstat.get(path, [])):
            files.add(path)
    for path, value in now_untracked.items():
        if int(value) != int(base_untracked.get(path, -1)):
            files.add(path)

    added = 0
    deleted = 0
    for path in files:
        current_added, current_deleted = _numstat_pair(now_numstat.get(path))
        base_added, base_deleted = _numstat_pair(base_numstat.get(path))
        added += max(0, current_added - base_added)
        deleted += max(0, current_deleted - base_deleted)
        if path in now_untracked and path not in base_untracked:
            added += int(now_untracked.get(path) or 0)
    return {"files": sorted(files), "added": added, "deleted": deleted, "changed": added + deleted}


def _numstat_pair(value: object) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0] or 0), int(value[1] or 0)
    return 0, 0


def collect_added_lines(raw_diff: str) -> dict[str, list[tuple[int, str]]]:
    added: dict[str, list[tuple[int, str]]] = {}
    current = ""
    new_line = 0
    for line in raw_diff.splitlines():
        if line.startswith("diff --git "):
            current = ""
            new_line = 0
            continue
        if line.startswith("+++ b/"):
            current = norm_path(line[len("+++ b/") :])
            continue
        if line.startswith("@@ "):
            found = re.search(r"\+(\d+)(?:,\d+)?", line)
            new_line = int(found.group(1)) if found else 0
            continue
        if not current or not new_line:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append((new_line, line[1:]))
            new_line += 1
        elif line.startswith(" ") and not line.startswith("+++"):
            new_line += 1
    return added


def collect_scope(repo: Path, base_ref: str | None) -> GateContext:
    status_changed, untracked = parse_status_paths(git_text(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]))
    changed = {path for path in status_changed if not internal_gate_path(path)}
    raw_diffs: list[str] = []
    numstats: list[Numstat] = []
    base_for_file = "HEAD"

    if base_ref:
        if git_ok(repo, ["rev-parse", "--verify", base_ref]):
            changed |= parse_name_only(git_text(repo, ["diff", "--name-only", f"{base_ref}...HEAD"]))
            for args in (
                ["diff", "--unified=0", "--no-color", f"{base_ref}...HEAD"],
                ["diff", "--cached", "--unified=0", "--no-color"],
                ["diff", "--unified=0", "--no-color"],
            ):
                raw_diffs.append(git_text(repo, args))
            for args in (
                ["diff", "--numstat", f"{base_ref}...HEAD"],
                ["diff", "--cached", "--numstat"],
                ["diff", "--numstat"],
            ):
                numstats.extend(parse_numstat(git_text(repo, args)))
            base_for_file = base_ref
    else:
        raw_diffs.append(git_text(repo, ["diff", "HEAD", "--unified=0", "--no-color"]))
        numstats.extend(parse_numstat(git_text(repo, ["diff", "HEAD", "--numstat"])))
        if not changed and git_ok(repo, ["rev-parse", "--verify", "HEAD~1"]):
            changed = parse_name_only(git_text(repo, ["diff", "--name-only", "HEAD~1..HEAD"]))
            raw_diffs = [git_text(repo, ["diff", "--unified=0", "--no-color", "HEAD~1..HEAD"])]
            numstats = parse_numstat(git_text(repo, ["diff", "--numstat", "HEAD~1..HEAD"]))
            base_for_file = "HEAD~1"
    changed |= {path for path in untracked if not internal_gate_path(path)}
    changed = {path for path in changed if not internal_gate_path(path)}
    untracked = {path for path in untracked if not internal_gate_path(path)}
    numstats = [record for record in numstats if not internal_gate_path(record.path)]
    raw_diff = "\n".join(part for part in raw_diffs if part)
    return GateContext(repo, changed, untracked, raw_diff, base_for_file, numstats, collect_added_lines(raw_diff))


def parse_patch(root: Path, text: str) -> dict[str, object]:
    paths: set[str] = set()
    added = 0
    deleted = 0
    add_text: list[str] = []
    add_file = False
    delete_file = False
    for line in text.splitlines():
        if line.startswith(("*** Update File:", "*** Add File:", "*** Delete File:")):
            path = rel(root, line.split(":", 1)[1].strip())
            if path:
                paths.add(path)
            add_file = add_file or line.startswith("*** Add File:")
            delete_file = delete_file or line.startswith("*** Delete File:")
        elif line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = rel(root, parts[3])
                if path:
                    paths.add(path)
        elif line.startswith(("+++ ", "--- ")):
            bits = line.split(maxsplit=1)
            if len(bits) == 2:
                path = rel(root, bits[1])
                if path:
                    paths.add(path)
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
            add_text.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1
    return {"paths": sorted(paths), "added": added, "deleted": deleted, "text": "\n".join(add_text), "add_file": add_file, "delete_file": delete_file, "patch_like": True}


def facts(root: Path, tool: str, tool_input: dict[str, object]) -> dict[str, object]:
    if tool in {"apply_patch", "ApplyPatch"}:
        return parse_patch(root, str(tool_input.get("command") or tool_input.get("patch") or ""))
    if tool == "Bash":
        command = tool_command(tool_input)
        if "apply_patch" in command or "*** Begin Patch" in command or "diff --git" in command:
            return parse_patch(root, command)
        return {"paths": [], "added": 0, "deleted": 0, "text": "", "add_file": False, "delete_file": False, "patch_like": False}
    if tool == "Write":
        path = rel(root, str(tool_input.get("file_path") or tool_input.get("path") or ""))
        text = str(tool_input.get("content") or "")
        return {"paths": [path] if path else [], "added": len(text.splitlines()), "deleted": 0, "text": text, "add_file": bool(path and not (root / path).exists()), "delete_file": False, "patch_like": False}
    if tool in {"Edit", "MultiEdit", "NotebookEdit"}:
        path = rel(root, str(tool_input.get("file_path") or tool_input.get("path") or ""))
        edits = tool_input.get("edits") if tool == "MultiEdit" else [tool_input]
        added = 0
        deleted = 0
        chunks: list[str] = []
        for edit in edits or []:
            if not isinstance(edit, dict):
                continue
            new = str(edit.get("new_string") or "")
            old = str(edit.get("old_string") or "")
            new_lines = len(new.splitlines())
            old_lines = len(old.splitlines())
            # Count replacement text as touched content, not just net growth.
            # Otherwise a 400-line rewrite with the same line count looks like zero work.
            added += new_lines
            deleted += old_lines
            chunks.append(new)
        return {"paths": [path] if path else [], "added": added, "deleted": deleted, "text": "\n".join(chunks), "add_file": False, "delete_file": False, "patch_like": False}
    return {"paths": [], "added": 0, "deleted": 0, "text": "", "add_file": False, "delete_file": False, "patch_like": False}


def guard_command(command: str) -> bool:
    return "lean_code_gate.py" in command and re.search(r"\b(declare|status|reset|check)\b", command) is not None


def mutating(tool: str, tool_input: dict[str, object]) -> bool:
    if tool in MUTATING_TOOLS:
        return True
    command = tool_command(tool_input)
    return tool == "Bash" and not guard_command(command) and not ("apply_patch" in command or "*** Begin Patch" in command or "diff --git" in command) and bool(HIDDEN_WRITE_RE.search(command))


def verify_cmd(command: str) -> bool:
    value = re.sub(r"\s+", " ", command.strip().lower())
    return any(hint in value for hint in VERIFY_HINTS)


def response_exit_code(value: object) -> int | None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in {"exit_code", "exitcode", "returncode", "return_code", "status_code"}:
                try:
                    return int(item)
                except (TypeError, ValueError):
                    pass
        for item in value.values():
            found = response_exit_code(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = response_exit_code(item)
            if found is not None:
                return found
    elif isinstance(value, str):
        found = re.search(r"\b(?:exit code|exit_code|returncode|return code|status)\D+(-?\d+)\b", value, re.I)
        if found:
            return int(found.group(1))
    return None


def path_type(path: str) -> str:
    if Path(path).name in DEPENDENCY_FILES:
        return "dependency"
    if match(path, CONFIG_GLOBS):
        return "config"
    if match(path, TEST_GLOBS):
        return "test"
    return "prod"


def design_hits(text: str) -> list[str]:
    return [name for pattern, name in DESIGN_RE if pattern.search(text)]


def is_binary_path(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


_active_excluded_globs: tuple[str, ...] = ()
_active_framework_override_names: frozenset[str] = frozenset()
_active_suppress_private_public_siblings: bool = False
_active_min_duplicate_count: int = 2


def is_excluded_path(path: str) -> bool:
    parts = [part.lower() for part in norm_path(path).split("/") if part]
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    lowered = f"/{norm_path(path).lower()}"
    if any(marker in lowered for marker in ("/.codex/quality/logs/", "/.agent/lean/", "/logs/")):
        return True
    if not _active_excluded_globs:
        return False
    normalized = norm_path(path).lower()
    # fnmatch treats ** as a single * (no multi-segment semantics). To match
    # globs like "**/migrations/**" against first-component paths like
    # "migrations/0001.py", check both the bare path and a /-prefixed variant.
    candidates = (normalized, "/" + normalized)
    return any(
        fnmatch.fnmatch(c, glob.lower()) for glob in _active_excluded_globs for c in candidates
    )


def is_test_like_path(path: str) -> bool:
    lowered = f"/{norm_path(path).lower()}"
    if any(marker in lowered for marker in TEST_MARKERS):
        return True
    name = Path(path).name.lower()
    return bool(re.search(r"\.(?:test|spec)\.", name)) or name.endswith(".schema.json")


def is_source_path(path: str) -> bool:
    return bool(path) and not is_excluded_path(path) and not is_binary_path(path) and Path(path).suffix.lower() in SOURCE_EXTENSIONS


def is_production_source_path(path: str) -> bool:
    return is_source_path(path) and not is_test_like_path(path)


def language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}:
        return "javascript"
    return {".go": "go", ".rs": "rust", ".sh": "shell", ".php": "php", ".rb": "ruby"}.get(suffix, suffix.lstrip(".") or "source")


def is_temp_artifact(path: str) -> bool:
    lowered = norm_path(path).lower()
    if not lowered:
        return False
    return bool(re.search(r"(^|/)(?:\.tmp|tmp|temp)(/|$)", lowered)) or lowered.endswith((".bak", ".orig", ".rej", ".tmp"))


def physical_lines(text: str | None) -> int:
    return len(text.splitlines()) if text else 0


def rules_for_path(path: str) -> list[re.Pattern[str]]:
    suffix = Path(path).suffix.lower()
    rules = list(GENERAL_ESCAPE_RULES)
    if suffix == ".py" and is_production_source_path(path):
        rules.extend(PYTHON_ESCAPE_RULES)
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"} and is_production_source_path(path):
        rules.extend(TS_ESCAPE_RULES)
    return rules


def line_hits(path: str, lines: list[tuple[int, str]], rules: list[re.Pattern[str]]) -> list[str]:
    hits = []
    for line_no, text in lines:
        if any(rule.search(text) for rule in rules):
            hits.append(f"{path}:{line_no}")
    return hits


def multiline_hits(path: str, text: str) -> list[str]:
    return [f"{path}:{text[: match.start()].count(chr(10)) + 1}" for rule in EMPTY_CATCH_RULES for match in rule.finditer(text)]


def scan_quality_escapes(ctx: GateContext) -> list[str]:
    # Path filter is is_source_path (not is_production_source_path) by design.
    # Reuse/duplicate/bloat detectors filter to is_production_source_path
    # because their findings are scoped to the new code's relationship to
    # the production codebase. Quality-escape's path filter is broader so
    # GENERAL_ESCAPE_RULES (TODO/FIXME, # type: ignore, @ts-ignore,
    # eslint-disable, # noqa, || true) catches escapes in test/fixture
    # paths too — those locations are particularly prone to vestigial
    # suppressions (Wen et al. FSE 2025: 50.8% of suppressions are useless).
    # Language-typed rules (PYTHON_ESCAPE_RULES, TS_ESCAPE_RULES — `: Any`,
    # `as any`, bare `except:`) DO restrict to production via
    # is_production_source_path inside rules_for_path; mocks in tests
    # legitimately use `as any` and shouldn't trip this layer.
    hits: list[str] = []
    for rel_path, lines in ctx.added_lines.items():
        if is_source_path(rel_path):
            hits.extend(line_hits(rel_path, lines, rules_for_path(rel_path)))
    for rel_path in sorted(ctx.untracked):
        if not is_source_path(rel_path):
            continue
        text = read_file(ctx.repo / rel_path)
        if text is None:
            continue
        hits.extend(line_hits(rel_path, list(enumerate(text.splitlines(), 1)), rules_for_path(rel_path)))
        hits.extend(multiline_hits(rel_path, text))
    hits.extend(multiline_added_hits(ctx.added_lines))
    return sorted(set(hits))


def multiline_added_hits(added_by_file: dict[str, list[tuple[int, str]]]) -> list[str]:
    hits: list[str] = []
    for path, values in added_by_file.items():
        joined = "\n".join(text for _, text in values)
        for rule in EMPTY_CATCH_RULES:
            for match_obj in rule.finditer(joined):
                line_offset = joined[: match_obj.start()].count("\n")
                line_no = values[min(line_offset, len(values) - 1)][0] if values else 1
                hits.append(f"{path}:{line_no}")
    return hits


def duplicate_added_blocks(ctx: GateContext) -> list[dict[str, object]]:
    return _duplicate_added_blocks_at_count(ctx, _active_min_duplicate_count)


def duplicate_added_blocks_all(ctx: GateContext) -> list[dict[str, object]]:
    """All raw duplicate windows (count>=2), no threshold filter. For telemetry."""
    return _duplicate_added_blocks_at_count(ctx, 2)


def _duplicate_added_blocks_at_count(ctx: GateContext, min_count: int) -> list[dict[str, object]]:
    windows: dict[str, dict[str, object]] = {}
    added_by_file = ctx.added_lines_with_untracked(production_only=True)
    for rel_path, lines in added_by_file.items():
        if not is_production_source_path(rel_path):
            continue
        normalized = duplicate_candidate_lines(lines)
        for index in range(0, max(0, len(normalized) - 2)):
            key = duplicate_window_key(normalized, index)
            if len(key) < 80:
                continue
            item = windows.setdefault(key, {"count": 0, "files": set(), "sample": key[:180]})
            item["count"] = int(item["count"]) + 1
            files = item["files"]
            if isinstance(files, set):
                files.add(rel_path)
    return collapse_duplicate_findings(
        [
            {"count": item["count"], "files": sorted(item["files"]), "sample": item["sample"]}
            for item in windows.values()
            if int(item["count"]) >= min_count and isinstance(item["files"], set)
        ]
    )


def duplicate_candidate_lines(lines: list[tuple[int, str]]) -> list[str]:
    normalized = [
        re.sub(r"\s+", " ", text.strip()).rstrip(";,")
        for _, text in lines
        if text.strip() and not text.strip().startswith(("//", "#", "*"))
    ]
    return [
        line
        for line in normalized
        if line not in {"{", "}"} and not re.match(r"^(?:export\s+)?(?:async\s+)?function\s+\w+\(", line)
    ]


def duplicate_window_key(lines: list[str], index: int) -> str:
    chunk = lines[index : index + 3]
    if index and lines[index - 1] == lines[index]:
        return ""
    if index + 3 < len(lines) and lines[index + 2] == lines[index + 3]:
        return ""
    if any("wait_for_timeout" in line for line in chunk) and index >= 2:
        chunk = lines[max(0, index - 2) : index + 3]
    return " | ".join(chunk)


def collapse_duplicate_findings(items: list[dict[str, object]]) -> list[dict[str, object]]:
    collapsed: list[dict[str, object]] = []
    for item in sorted(items, key=lambda value: (str(value["files"]), str(value["sample"]))):
        duplicate = next((existing for existing in collapsed if same_duplicate_family(existing, item)), None)
        if duplicate is None:
            collapsed.append(item)
        else:
            duplicate["count"] = int(duplicate["count"]) + int(item["count"])
    return collapsed


def same_duplicate_family(left: dict[str, object], right: dict[str, object]) -> bool:
    if left["files"] != right["files"]:
        return False
    left_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]+", str(left["sample"])))
    right_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]+", str(right["sample"])))
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) >= 0.6


def evaluate_bloat(ctx: GateContext, active_policy: dict[str, object]) -> tuple[list[str], list[str], dict[str, object]]:
    errors: list[str] = []
    warnings: list[str] = []
    details, total_added, total_deleted, shrink_by_dir = bloat_file_details(ctx)
    for detail in details:
        errors.extend(bloat_errors_for_file(detail, shrink_by_dir, active_policy))
        warnings.extend(bloat_warnings_for_file(detail, active_policy))
    if total_added >= int(active_policy["bloat_total_added_error_lines"]) and total_added > max(1, total_deleted) * int(active_policy["bloat_add_delete_error_ratio"]):
        errors.append(f"changed source diff is heavily additive: added={total_added} deleted={total_deleted}")
    elif total_added >= int(active_policy["bloat_total_added_warn_lines"]) and total_added > max(1, total_deleted) * int(active_policy["bloat_add_delete_warn_ratio"]):
        warnings.append(f"changed source diff is additive: added={total_added} deleted={total_deleted}")
    return errors, warnings, {"totalAdded": total_added, "totalDeleted": total_deleted, "files": details[:50]}


def bloat_file_details(ctx: GateContext) -> tuple[list[dict[str, object]], int, int, dict[str, int]]:
    numstat = merge_numstats(ctx.numstats)
    details: list[dict[str, object]] = []
    total_added = 0
    total_deleted = 0
    shrink_by_dir: dict[str, int] = {}
    for rel_path in sorted(ctx.changed_files):
        if not is_production_source_path(rel_path):
            continue
        current_text = read_file(ctx.repo / rel_path)
        if current_text is None:
            continue
        base_text = read_git_file(ctx.repo, ctx.base_for_file, rel_path)
        baseline_lines = physical_lines(base_text) if base_text is not None else None
        current_lines = physical_lines(current_text)
        record = numstat.get(rel_path)
        added = record.added if record else (current_lines if baseline_lines is None else 0)
        deleted = record.deleted if record else 0
        total_added += added
        total_deleted += deleted
        parent = str(Path(rel_path).parent).replace(os.sep, "/")
        if deleted > added:
            shrink_by_dir[parent] = shrink_by_dir.get(parent, 0) + deleted - added
        details.append(
            {
                "file": rel_path,
                "added": added,
                "deleted": deleted,
                "currentLines": current_lines,
                "baselineLines": baseline_lines,
                "netGrowth": max(0, added - deleted),
            }
        )
    return details, total_added, total_deleted, shrink_by_dir


def bloat_errors_for_file(detail: dict[str, object], shrink_by_dir: dict[str, int], active_policy: dict[str, object]) -> list[str]:
    rel_path = str(detail["file"])
    current_lines = int(detail["currentLines"])
    baseline_lines = detail["baselineLines"]
    net_growth = int(detail["netGrowth"])
    available_shrink = shrink_by_dir.get(str(Path(rel_path).parent).replace(os.sep, "/"), 0)
    if baseline_lines is None:
        threshold = int(active_policy["bloat_new_file_error_lines"])
        return [f"new source file {rel_path} has {current_lines} lines (>{threshold})"] if current_lines > threshold else []
    baseline_value = int(baseline_lines)
    large_file = baseline_value > int(active_policy["bloat_large_file_lines"])
    if large_file and bool(active_policy.get("bloat_large_file_must_shrink")) and current_lines >= baseline_value:
        return [f"large source file {rel_path} must shrink when touched ({current_lines} >= {baseline_value})"]
    if net_growth > int(active_policy["bloat_file_growth_lines"]) and available_shrink < net_growth:
        return [f"source file {rel_path} grew by {net_growth} lines without same-directory shrink"]
    if large_file and net_growth > int(active_policy["bloat_large_file_growth_lines"]) and available_shrink < net_growth:
        return [f"large source file {rel_path} grew by {net_growth} lines without same-directory shrink"]
    return []


def bloat_warnings_for_file(detail: dict[str, object], active_policy: dict[str, object]) -> list[str]:
    threshold = int(active_policy["bloat_new_file_warn_lines"])
    if detail["baselineLines"] is None and int(detail["currentLines"]) > threshold:
        return [f"new source file {detail['file']} has {detail['currentLines']} lines (>{threshold})"]
    baseline_lines = detail["baselineLines"]
    net_growth = int(detail["netGrowth"])
    if baseline_lines is not None and int(baseline_lines) > int(active_policy["bloat_large_file_lines"]) and net_growth > 0:
        return [f"large source file {detail['file']} grew by {net_growth} lines"]
    return []


def split_name_tokens(name: str) -> tuple[str, ...]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    expanded = re.sub(r"[^A-Za-z0-9]+", " ", expanded)
    tokens = tuple(token.lower() for token in expanded.split() if len(token) > 1)
    return tokens or (name.lower(),)


def extract_symbols(path: str, text: str, source: str, context_boost: int = 0) -> list[SymbolDef]:
    language = language_for_path(path)
    symbols: list[SymbolDef] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for kind, pattern in SYMBOL_PATTERNS.get(language, []):
            found = pattern.search(line)
            if found:
                name = found.group(1)
                symbols.append(SymbolDef(name, path, line_no, kind, language, split_name_tokens(name), source, context_boost))
                break
    return symbols


def subtree_score(path_a: str, path_b: str) -> int:
    parts_a = norm_path(path_a).split("/")[:-1]
    parts_b = norm_path(path_b).split("/")[:-1]
    if not parts_a or not parts_b:
        return 0
    if parts_a == parts_b:
        return 10
    shared = 0
    for left, right in zip(parts_a, parts_b):
        if left != right:
            break
        shared += 1
    return 10 if shared >= 2 else 5 if shared == 1 else 0


def token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    return len(left_set & right_set) / max(len(left_set), len(right_set)) if left_set and right_set else 0.0


def same_behavior_name(left: SymbolDef, right: SymbolDef) -> tuple[int, str]:
    if _active_framework_override_names and left.name in _active_framework_override_names and right.name in _active_framework_override_names:
        return 0, ""
    # R-3 (private/public sibling): suppress at the candidate-evaluation
    # stage. Structural blind spot — caller's `if base_score <= 0: continue`
    # means body-similarity scoring is not reached for any _foo/foo pair,
    # even genuine identical implementations. Calibrated tradeoff: prefer FN
    # over FP given the observed FP rate in the 50-commit Django window.
    if _active_suppress_private_public_siblings and left.tokens == right.tokens and left.tokens and left.name.strip("_") == right.name.strip("_") and left.name != right.name:
        return 0, ""
    if left.name == right.name:
        return (35, "generic same symbol name") if left.name.lower() in GENERIC_SYMBOLS else (100, "same symbol name")
    if left.tokens == right.tokens and left.tokens:
        return (35, "generic matching name tokens") if set(left.tokens) <= GENERIC_SYMBOLS else (90, "same name tokens")
    overlap = token_overlap(left.tokens, right.tokens)
    if overlap < 0.66:
        return 0, ""
    shared = sorted(set(left.tokens) & set(right.tokens))
    if set(shared) & REUSE_ACTION_TOKENS:
        return 52, f"matching behavior tokens: {', '.join(shared)}"
    return 45, f"matching name tokens: {', '.join(shared)}"


def detect_reuse_issues(ctx: GateContext, active_policy: dict[str, object]) -> list[ReuseFinding]:
    mode = str(active_policy.get("reuse_detector_mode") or "conservative").lower()
    if mode == "off":
        return []
    candidates = new_symbols(ctx) + risky_added_blocks(ctx)
    if not candidates:
        return []
    existing = existing_symbol_index(ctx, candidates, active_policy)
    if not existing:
        return []
    findings = score_reuse_candidates(candidates, existing, ctx.added_lines, deleted_definition_names(ctx.raw_diff), active_policy)
    return findings[:30]


def existing_symbol_index(ctx: GateContext, candidates: list[SymbolDef], active_policy: dict[str, object]) -> list[SymbolDef]:
    symbols: list[SymbolDef] = []
    indexed = 0
    tracked = [norm_path(line) for line in git_text(ctx.repo, ["ls-files"]).splitlines() if norm_path(line)]
    candidate_languages = {item.language for item in candidates}
    candidate_roots = {top_dir(item.path) for item in candidates}
    max_files = int(active_policy["quality_max_index_files"])
    max_bytes = int(active_policy["quality_max_index_file_bytes"])
    max_symbols = int(active_policy["quality_max_index_symbols"])
    for rel_path in tracked:
        if indexed >= max_files or len(symbols) >= max_symbols:
            break
        if rel_path in ctx.untracked or not is_production_source_path(rel_path):
            continue
        if language_for_path(rel_path) not in candidate_languages or top_dir(rel_path) not in candidate_roots:
            continue
        text = read_git_file(ctx.repo, ctx.base_for_file, rel_path) if rel_path in ctx.changed_files else read_file(ctx.repo / rel_path)
        if text is None or len(text.encode("utf-8", errors="ignore")) > max_bytes:
            continue
        indexed += 1
        for symbol in extract_symbols(rel_path, text, "baseline"):
            symbols.append(symbol)
            if len(symbols) >= max_symbols:
                break
    return symbols


def new_symbols(ctx: GateContext) -> list[SymbolDef]:
    symbols: list[SymbolDef] = []
    for rel_path, lines in ctx.added_lines.items():
        if not is_production_source_path(rel_path):
            continue
        for line_no, text in lines:
            for symbol in extract_symbols(rel_path, text, "added"):
                symbols.append(SymbolDef(symbol.name, rel_path, line_no, symbol.kind, symbol.language, symbol.tokens, symbol.source))
    for rel_path in sorted(ctx.untracked):
        if is_production_source_path(rel_path):
            text = read_file(ctx.repo / rel_path)
            if text is not None:
                symbols.extend(extract_symbols(rel_path, text, "untracked"))
    return symbols


def risky_added_blocks(ctx: GateContext) -> list[SymbolDef]:
    blocks: list[SymbolDef] = []
    for rel_path, lines in ctx.added_lines_with_untracked(production_only=True).items():
        if not is_production_source_path(rel_path):
            continue
        for line_no, text in lines:
            dedupe_shape = bool(re.search(r"\bseen\s*=\s*set\s*\(|\bnot\s+in\s+seen\b", text))
            if not RISKY_BLOCK_RULE.search(text) and not dedupe_shape:
                continue
            tokens = [token for token in split_name_tokens(text) if token in REUSE_ACTION_TOKENS]
            if dedupe_shape:
                tokens.append("dedupe")
            if dedupe_shape or len(set(tokens)) >= 2:
                blocks.append(SymbolDef("+".join(tokens[:3]), rel_path, line_no, "block", language_for_path(rel_path), tuple(tokens[:3]), "added"))
    return blocks


def deleted_definition_names(raw_diff: str) -> set[str]:
    deleted: set[str] = set()
    current = ""
    for line in raw_diff.splitlines():
        if line.startswith("diff --git "):
            current = ""
        elif line.startswith("--- a/"):
            current = norm_path(line[len("--- a/") :])
        elif current and is_production_source_path(current) and line.startswith("-") and not line.startswith("---"):
            deleted.update(symbol.name for symbol in extract_symbols(current, line[1:], "deleted"))
    return deleted


def score_reuse_candidates(candidates: list[SymbolDef], existing: list[SymbolDef], added_by_file: dict[str, list[tuple[int, str]]], moved_or_deleted: set[str], active_policy: dict[str, object]) -> list[ReuseFinding]:
    findings: list[ReuseFinding] = []
    for new_item in candidates:
        if new_item.name in moved_or_deleted or new_item.name.lower() in moved_or_deleted:
            continue
        best = best_existing_match(new_item, existing, added_by_file)
        if best is None:
            continue
        score, reason, existing_item = best
        error_score = int(active_policy.get("reuse_error_score", 90))
        warning_score = int(active_policy.get("reuse_warning_score", 45))
        high_confidence = high_confidence_reuse(new_item, existing_item)
        severity = "error" if high_confidence or score >= error_score else "warning" if score >= warning_score else ""
        if severity == "warning" and not warning_is_actionable(new_item, existing_item):
            continue
        if severity:
            findings.append(ReuseFinding(severity, score, new_item.name, new_item.path, new_item.line, existing_item.name, existing_item.path, existing_item.line, reason))
    findings.sort(key=lambda item: (item.severity != "error", -item.score, item.new_file, item.new_line))
    return findings


def high_confidence_reuse(new_item: SymbolDef, existing_item: SymbolDef) -> bool:
    if new_item.kind == "block":
        return "dedupe" in set(new_item.tokens) and "dedupe" in set(existing_item.tokens) and same_reuse_neighborhood(new_item.path, existing_item.path, existing_item.context_boost)
    # Defer to the calibrated suppression in same_behavior_name: when R-2
    # (framework_override_names) or R-3 (private/public siblings) returns 0,
    # the pair should not be promoted to high-confidence reuse either.
    # In the production call path (score_reuse_candidates →
    # best_existing_match), pairs with same_behavior_name == 0 are already
    # filtered by the `if base_score <= 0: continue` guard, so this check
    # is unreachable from there. Kept as defense-in-depth and to enforce
    # the function's contract for direct callers (unit tests, future code).
    if same_behavior_name(new_item, existing_item)[0] == 0:
        return False
    if new_item.name == existing_item.name and new_item.name.lower() not in GENERIC_SYMBOLS:
        return True
    return new_item.tokens == existing_item.tokens and bool(new_item.tokens) and not set(new_item.tokens) <= GENERIC_SYMBOLS


def best_existing_match(new_item: SymbolDef, existing: list[SymbolDef], added_by_file: dict[str, list[tuple[int, str]]]) -> tuple[int, str, SymbolDef] | None:
    best: tuple[int, str, SymbolDef] | None = None
    for existing_item in existing:
        if existing_item.path == new_item.path and existing_item.name == new_item.name:
            continue
        if existing_item.language != new_item.language and new_item.kind != "block":
            continue
        if symbol_is_called_nearby(existing_item.name, added_by_file.get(new_item.path, []), new_item.line, new_item.language):
            continue
        base_score, reason = same_behavior_name(new_item, existing_item)
        if new_item.kind == "block":
            overlap = token_overlap(new_item.tokens, existing_item.tokens)
            if overlap < 0.5:
                continue
            base_score = 55 + int(overlap * 20)
            reason = f"new loop/helper block overlaps existing behavior tokens: {', '.join(set(new_item.tokens) & set(existing_item.tokens))}"
        if base_score <= 0:
            continue
        if new_item.kind == "block" and not same_reuse_neighborhood(new_item.path, existing_item.path, existing_item.context_boost):
            continue
        score = min(100, base_score + subtree_score(new_item.path, existing_item.path) + existing_item.context_boost)
        if existing_item.context_boost and base_score >= 52:
            score = min(100, score + 10)
        if best is None or score > best[0]:
            best = (score, reason, existing_item)
    return best


def line_defines_symbol(language: str, text: str, symbol: str) -> bool:
    # SYMBOL_PATTERNS is the source of truth for what counts as a definition
    # in each supported language. Reusing it here keeps the def-line filter
    # in lockstep with extraction; adding a new language to SYMBOL_PATTERNS
    # automatically extends this filter without a parallel regex table.
    return any(
        (found := pattern.search(text)) is not None and found.group(1) == symbol
        for _, pattern in SYMBOL_PATTERNS.get(language, [])
    )


def symbol_is_called_nearby(symbol: str, lines: list[tuple[int, str]], new_line: int, language: str) -> bool:
    # Skip lines that *define* the searched symbol so its own def isn't
    # read as a call to itself. Lines that define a *different* symbol but
    # call this one stay visible: `def wrap(x, fn=parse_html_payload()):`
    # is wrap's def line and a real call site for parse_html_payload.
    call_pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(")
    return any(
        not line_defines_symbol(language, text, symbol)
        and max(0, new_line - 8) <= line_no <= new_line + 20
        and call_pattern.search(text)
        for line_no, text in lines
    )


def warning_is_actionable(new_item: SymbolDef, existing_item: SymbolDef) -> bool:
    shared = set(new_item.tokens) & set(existing_item.tokens)
    discriminating = shared - GENERIC_MATCH_TOKENS
    has_shared_action = bool(discriminating & REUSE_ACTION_TOKENS)
    return has_shared_action and len(discriminating) >= 2 and same_reuse_neighborhood(new_item.path, existing_item.path, existing_item.context_boost)


def same_reuse_neighborhood(path_a: str, path_b: str, context_boost: int) -> bool:
    return context_boost > 0 or top_dir(path_a) == top_dir(path_b)


def top_dir(path: str) -> str:
    return norm_path(path).split("/", 1)[0]


def changed_file_failures(repo: Path, changed_files: set[str]) -> tuple[list[str], list[str]]:
    conflict_files: list[str] = []
    temp_files: list[str] = []
    for rel_path in sorted(changed_files):
        if is_temp_artifact(rel_path) and (repo / rel_path).exists():
            temp_files.append(rel_path)
        text = read_file(repo / rel_path)
        if text is not None and not is_binary_path(rel_path) and re.search(r"^<{7} |^={7}$|^>{7} ", text, re.M):
            conflict_files.append(rel_path)
    return conflict_files, temp_files


def apply_active_policy(active_policy: dict[str, object]) -> None:
    global _active_excluded_globs, _active_framework_override_names, _active_suppress_private_public_siblings, _active_min_duplicate_count
    raw_globs = active_policy.get("excluded_path_globs")
    _active_excluded_globs = tuple(g for g in raw_globs if isinstance(g, str)) if isinstance(raw_globs, list) else ()
    raw_names = active_policy.get("framework_override_names")
    _active_framework_override_names = frozenset(n for n in raw_names if isinstance(n, str)) if isinstance(raw_names, list) else frozenset()
    _active_suppress_private_public_siblings = bool(active_policy.get("reuse_suppress_private_public_siblings"))
    _active_min_duplicate_count = max(2, int(active_policy.get("reuse_min_duplicate_count") or 2))


def run_quality_gate(repo: Path, base_ref: str | None, fail_on_warnings: bool) -> dict[str, object]:
    active_policy = policy(repo)
    apply_active_policy(active_policy)
    ctx = collect_scope(repo, base_ref)
    changed_files = set(ctx.changed_files)
    errors: list[str] = []
    warnings: list[str] = []
    conflict_files, temp_files = changed_file_failures(repo, changed_files)
    quality_escapes = scan_quality_escapes(ctx)
    duplicates = duplicate_added_blocks(ctx)
    duplicates_all = duplicate_added_blocks_all(ctx)
    bloat_errors, bloat_warnings, bloat_details = evaluate_bloat(ctx, active_policy)
    reuse_findings = detect_reuse_issues(ctx, active_policy)
    reuse_errors = [finding for finding in reuse_findings if finding.severity == "error"]
    reuse_warnings = [finding for finding in reuse_findings if finding.severity == "warning"]

    if conflict_files:
        errors.append(f"merge conflict markers found in {len(conflict_files)} file(s)")
    if temp_files:
        errors.append(f"temporary artifact paths detected in {len(temp_files)} changed file(s)")
    if quality_escapes:
        errors.append(f"quality escapes detected in {len(quality_escapes)} changed location(s)")
    if duplicates:
        errors.append(f"duplicate added code blocks detected: {len(duplicates)}")
    if reuse_errors:
        errors.append(f"new code appears to reimplement existing helpers or loops: {len(reuse_errors)}")
    errors.extend(bloat_errors)
    warnings.extend(bloat_warnings)
    warnings.extend(reuse_warning_messages(reuse_warnings))
    if fail_on_warnings and warnings:
        errors.extend(f"warning promoted to failure: {warning}" for warning in warnings)

    checks = quality_checks(conflict_files, temp_files, quality_escapes, duplicates, reuse_errors, reuse_warnings, bloat_errors, bloat_warnings)
    return {
        "ok": not errors,
        "version": VERSION,
        "repo": str(repo),
        "changedFilesCount": len(changed_files),
        "changedFilesSample": sorted(changed_files)[:30],
        "sourceFilesCount": len([path for path in changed_files if is_production_source_path(path)]),
        "checks": checks,
        "hardRules": hard_rules(checks),
        "errors": errors,
        "warnings": warnings,
        "bloat": bloat_details,
        "reuseFindings": [finding.as_dict() for finding in reuse_findings],
        "qualityEscapeLocations": list(quality_escapes),
        "duplicateBlockCandidates": [{"count": int(d["count"]), "files": list(d["files"])} for d in duplicates_all],
    }


def reuse_warning_messages(reuse_warnings: list[ReuseFinding]) -> list[str]:
    return [
        f"possible reusable existing path for {finding.new_file}:{finding.new_line} -> {finding.existing_file}:{finding.existing_line} {finding.existing_symbol} ({finding.reason})"
        for finding in reuse_warnings
    ]


def quality_checks(
    conflict_files: list[str],
    temp_files: list[str],
    quality_escapes: list[str],
    duplicates: list[dict[str, object]],
    reuse_errors: list[ReuseFinding],
    reuse_warnings: list[ReuseFinding],
    bloat_errors: list[str],
    bloat_warnings: list[str],
) -> list[dict[str, object]]:
    return [
        {"name": "no-merge-conflict-markers", "passed": not conflict_files, "sample": conflict_files[:10]},
        {"name": "no-temp-artifacts", "passed": not temp_files, "sample": temp_files[:10]},
        {"name": "no-quality-escapes", "passed": not quality_escapes, "sample": quality_escapes[:10]},
        {"name": "no-duplicate-added-blocks", "passed": not duplicates, "sample": duplicates[:4]},
        {
            "name": "reuse-existing-helpers",
            "passed": not reuse_errors,
            "warnings": [finding.as_dict() for finding in reuse_warnings[:10]],
            "sample": [finding.as_dict() for finding in reuse_errors[:10]],
        },
        {"name": "risk-calibrated-bloat", "passed": not bloat_errors, "warnings": bloat_warnings[:10]},
    ]


def hard_rules(checks: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    passed = {str(item["name"]): bool(item["passed"]) for item in checks}
    no_duplication = passed["no-duplicate-added-blocks"] and passed["reuse-existing-helpers"]
    shortest_path = passed["risk-calibrated-bloat"] and no_duplication
    return {
        "codeVolume": {"passed": passed["risk-calibrated-bloat"], "checks": ["risk-calibrated-bloat"]},
        "noDuplication": {"passed": no_duplication, "checks": ["no-duplicate-added-blocks", "reuse-existing-helpers"]},
        "shortestPath": {"passed": shortest_path, "checks": ["risk-calibrated-bloat", "no-duplicate-added-blocks", "reuse-existing-helpers"]},
        "cleanup": {"passed": passed["no-quality-escapes"] and passed["no-temp-artifacts"], "checks": ["no-quality-escapes", "no-temp-artifacts"]},
        "anticipateConsequences": {"passed": passed["no-merge-conflict-markers"], "checks": ["no-merge-conflict-markers"]},
        "simplicity": {"passed": shortest_path, "checks": ["risk-calibrated-bloat", "no-duplicate-added-blocks", "reuse-existing-helpers"]},
    }


def format_quality_text(result: dict[str, object]) -> str:
    lines = [
        "Lean Code Quality Gate",
        f"verdict: {'pass' if result['ok'] else 'fail'}",
        f"changedFilesCount: {result['changedFilesCount']}",
        f"sourceFilesCount: {result['sourceFilesCount']}",
        "",
        "Checks:",
    ]
    for item in result["checks"]:
        lines.append(f"- {item['name']}: {'pass' if item['passed'] else 'fail'}")
    lines.append("")
    lines.append("Errors:")
    lines.extend([f"- {error}" for error in result["errors"]] if result["errors"] else ["- none"])
    lines.append("")
    lines.append("Warnings:")
    lines.extend([f"- {warning}" for warning in result["warnings"]] if result["warnings"] else ["- none"])
    return "\n".join(lines)


def meaningful(values: object) -> bool:
    if isinstance(values, str):
        items = [values]
    elif isinstance(values, list):
        items = [str(item) for item in values]
    else:
        return False
    return any(item.strip().lower() not in PLACEHOLDER_TEXT for item in items)


def code_task(task_type: str) -> bool:
    return task_type in {"bugfix", "feature", "refactor", "config"}


def minimal_preflight(current_contract: dict[str, object]) -> bool:
    return str(current_contract.get("preflight_level") or "full") == "minimal"


def minimal_preflight_errors(current_contract: dict[str, object], active_policy: dict[str, object]) -> list[str]:
    errors: list[str] = []
    task_type = str(current_contract.get("task_type") or "unknown")
    allowed = set(str(item) for item in active_policy.get("minimal_preflight_task_types", []))
    if not active_policy.get("allow_minimal_preflight"):
        errors.append("Minimal preflight is disabled by policy.")
    if task_type not in allowed:
        errors.append("Minimal preflight is limited to: " + ", ".join(sorted(allowed)))
    if int(current_contract.get("max_files") or 0) > int(active_policy["minimal_preflight_max_files"]):
        errors.append(f"Minimal preflight max-files cannot exceed {active_policy['minimal_preflight_max_files']}.")
    if int(current_contract.get("max_added_lines") or 0) > int(active_policy["minimal_preflight_max_added_lines"]):
        errors.append(f"Minimal preflight max-added-lines cannot exceed {active_policy['minimal_preflight_max_added_lines']}.")
    if int(current_contract.get("max_changed_lines") or 0) > int(active_policy["minimal_preflight_max_changed_lines"]):
        errors.append(f"Minimal preflight max-changed-lines cannot exceed {active_policy['minimal_preflight_max_changed_lines']}.")
    for flag in ("allow_new_files", "allow_dependency_changes", "allow_bash_writes", "allow_abstractions", "allow_broad_scope"):
        if current_contract.get(flag):
            errors.append(f"Minimal preflight cannot use --{flag.replace('_', '-')}.")
    return errors


def contract_identity_errors(root: Path, current_contract: dict[str, object]) -> list[str]:
    if not current_contract:
        return []
    identity = repo_identity(root)
    stored_id = str(current_contract.get("repo_id") or "")
    if not stored_id:
        return [
            "Lean Change Contract is missing repo_id. "
            f"Redeclare for target repo_id {identity['repo_id']} at {identity['repo_root']}. "
            f"State path: {contract_path(root)}. "
            f"Run `{command_hint(root)} declare ...` to redeclare for the current repo."
        ]
    if stored_id != identity["repo_id"]:
        stored_root = str(current_contract.get("repo_root") or "unknown")
        return [
            "Lean Change Contract belongs to "
            f"repo_id {stored_id} at {stored_root}, but current target is "
            f"repo_id {identity['repo_id']} at {identity['repo_root']}. "
            f"State path: {contract_path(root)}. "
            f"Run `{command_hint(root)} declare ...` to redeclare for the current repo."
        ]
    return []


def contract_errors(current_contract: dict[str, object], active_policy: dict[str, object], root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not current_contract:
        target = f" Target repo: {root.resolve()}. State path: {contract_path(root)}." if root is not None else ""
        return [f"No active Lean Change Contract.{target} Run `{command_hint(root)} declare ...` before editing."]
    if root is not None:
        errors.extend(contract_identity_errors(root, current_contract))
    if not meaningful(current_contract.get("intent")):
        errors.append("Missing or placeholder intent.")
    scope = current_contract.get("scope") or []
    if not scope:
        errors.append("Missing scope.")
    broad = [glob for glob in scope if glob in BROAD_SCOPE or (str(glob).endswith("/**") and glob not in active_policy["allowed_broad_globs"])]
    if broad and active_policy["block_broad_scope"] and not current_contract.get("allow_broad_scope"):
        errors.append("Scope too broad: " + ", ".join(map(str, broad)) + ". Name exact files or narrow globs.")
    if not current_contract.get("verify") and not current_contract.get("no_tests_reason"):
        errors.append("Declare at least one verify command, or provide --no-tests-reason.")
    task_type = str(current_contract.get("task_type") or "unknown")
    if active_policy.get("require_explicit_task_type") and task_type == "unknown":
        errors.append("Declare an explicit --task-type; unknown is not accepted for mutation contracts.")
    if minimal_preflight(current_contract):
        errors.extend(minimal_preflight_errors(current_contract, active_policy))
        return errors
    if active_policy["require_preflight_for_code"] and code_task(task_type):
        required_fields = (
            ("affected_surface", "--affected-surface"),
            ("authoritative_contract", "--authoritative-contract"),
            ("invariants", "--invariant"),
            ("proof_plan", "--proof-plan"),
            ("risk_check", "--risk-check"),
        )
        for field, flag in required_fields:
            if not meaningful(current_contract.get(field)):
                errors.append(f"Code work requires {flag}.")
    if active_policy["require_reuse_path_for_code"] and task_type in {"bugfix", "feature", "refactor"}:
        if not meaningful(current_contract.get("reuse_path")) and not meaningful(current_contract.get("no_reuse_reason")):
            errors.append("Code work requires --reuse-path naming the existing path to extend, or --no-reuse-reason with evidence.")
    return errors


def check_change(change_facts: dict[str, object], current_contract: dict[str, object], active_policy: dict[str, object], tool: str) -> list[str]:
    errors: list[str] = []
    paths = list(change_facts["paths"])
    scope = list(current_contract.get("scope") or [])
    outside = [path for path in paths if not match(path, scope)]
    if outside:
        errors.append("Outside scope: " + ", ".join(outside) + ". Widen with a reason first.")
    if len(paths) > int(current_contract["max_files"]):
        errors.append(f"Touches {len(paths)} files, max is {current_contract['max_files']}.")
    if int(change_facts["added"]) > int(current_contract["max_added_lines"]):
        errors.append(f"Adds about {change_facts['added']} lines, max is {current_contract['max_added_lines']}.")
    if int(change_facts["added"]) + int(change_facts["deleted"]) > int(current_contract["max_changed_lines"]):
        errors.append(f"Changes about {int(change_facts['added']) + int(change_facts['deleted'])} lines, max is {current_contract['max_changed_lines']}.")
    if change_facts.get("add_file") and not current_contract.get("allow_new_files"):
        errors.append("New file requires --allow-new-files.")
    deps = [path for path in paths if path_type(path) == "dependency"]
    if deps and active_policy["block_dependency_changes_without_flag"] and not current_contract.get("allow_dependency_changes"):
        errors.append("Undeclared dependency change: " + ", ".join(deps))
    configs = [path for path in paths if path_type(path) == "config"]
    if configs and active_policy["block_config_changes_without_flag"] and not current_contract.get("allow_config_changes"):
        errors.append("Undeclared config change: " + ", ".join(configs))
    text = str(change_facts.get("text") or "")
    hits = design_hits(text)
    if len(hits) >= int(active_policy["max_design_markers"]) and not current_contract.get("allow_abstractions"):
        line_count = len(text.splitlines())
        density_threshold = float(active_policy.get("max_design_marker_density_per_100_lines") or 0.0)
        density = (len(hits) / line_count * 100) if line_count else 0.0
        if line_count < 100 or density_threshold <= 0 or density >= density_threshold:
            errors.append("Possible abstraction bloat: " + ", ".join(sorted(set(hits))) + ". Prefer direct code or redeclare with --allow-abstractions --reason.")
    quality_hits = proposed_quality_hits(str(change_facts.get("text") or ""), paths)
    if quality_hits:
        errors.append("Proposed change contains quality escapes: " + ", ".join(quality_hits[:6]))
    if tool == "Bash" and paths and not change_facts.get("patch_like") and active_policy["block_hidden_bash_writes"] and not current_contract.get("allow_bash_writes"):
        errors.append("File-changing Bash is blocked; use Edit/apply_patch or declare --allow-bash-writes.")
    return errors


def proposed_quality_hits(text: str, paths: list[str]) -> list[str]:
    if not text:
        return []
    target = next((path for path in paths if is_source_path(path)), "proposed-change")
    rules = rules_for_path(target)
    lines = list(enumerate(text.splitlines(), 1))
    hits = line_hits(target, lines, rules)
    hits.extend(multiline_hits(target, text))
    return sorted(set(hits))


def final_errors(root: Path, current_contract: dict[str, object], active_policy: dict[str, object]) -> list[str]:
    if not current_contract:
        snapshot = status_snapshot(root)
        changed = sorted(
            set(snapshot.get("status", {}))
            | set(snapshot.get("numstat", {}))
            | set(snapshot.get("untrackedLines", {}))
        )
        return ["Files changed but no Lean Change Contract exists: " + ", ".join(changed[:20])] if changed else []
    current_delta = delta(root, current_contract)
    errors = contract_errors(current_contract, active_policy, root)
    files = list(current_delta["files"])
    new_files = sorted(path for path in added_file_paths(root) if path in files)
    if new_files and not current_contract.get("allow_new_files"):
        errors.append("New files require --allow-new-files: " + ", ".join(new_files[:20]))
    scope = list(current_contract.get("scope") or [])
    outside = [path for path in files if not match(path, scope)]
    if outside:
        errors.append("Final diff outside scope: " + ", ".join(outside))
    if len(files) > int(current_contract["max_files"]):
        errors.append(f"Final diff touches {len(files)} files, max is {current_contract['max_files']}.")
    if int(current_delta["added"]) > int(current_contract["max_added_lines"]):
        errors.append(f"Final diff adds {current_delta['added']} lines, max is {current_contract['max_added_lines']}.")
    if int(current_delta["changed"]) > int(current_contract["max_changed_lines"]):
        errors.append(f"Final diff changes {current_delta['changed']} lines, max is {current_contract['max_changed_lines']}.")
    deps = [path for path in files if path_type(path) == "dependency"]
    if deps and active_policy["block_dependency_changes_without_flag"] and not current_contract.get("allow_dependency_changes"):
        errors.append("Undeclared dependency changes: " + ", ".join(deps))
    configs = [path for path in files if path_type(path) == "config"]
    if configs and active_policy["block_config_changes_without_flag"] and not current_contract.get("allow_config_changes"):
        errors.append("Undeclared config changes: " + ", ".join(configs))
    prod_files = [path for path in files if path_type(path) == "prod"]
    if current_contract.get("task_type") == "bugfix" and active_policy["require_bugfix_test_change"] and prod_files and not any(path_type(path) == "test" for path in files) and not current_contract.get("no_tests_reason"):
        errors.append("Bugfix changed production code without a test change or --no-tests-reason.")
    if prod_files and active_policy["require_preflight_for_code"] and not minimal_preflight(current_contract):
        for field, flag in (("affected_surface", "--affected-surface"), ("authoritative_contract", "--authoritative-contract"), ("invariants", "--invariant"), ("proof_plan", "--proof-plan"), ("risk_check", "--risk-check")):
            if not meaningful(current_contract.get(field)):
                errors.append(f"Production diff requires {flag} in the contract.")
    if prod_files and active_policy["require_reuse_path_for_code"] and not minimal_preflight(current_contract):
        if not meaningful(current_contract.get("reuse_path")) and not meaningful(current_contract.get("no_reuse_reason")):
            errors.append("Production diff requires --reuse-path naming the reused path or --no-reuse-reason with evidence.")
    if active_policy["require_verify_after_mutation"] and files and not current_contract.get("no_tests_reason"):
        wanted = [re.sub(r"\s+", " ", command.strip()) for command in current_contract.get("verify") or []]
        passed = [
            re.sub(r"\s+", " ", str(event.get("command", "")).strip())
            for event in events(root)
            if event.get("event") == "verify_passed" and float(event.get("time", 0)) >= float(current_contract.get("declared_at", 0))
        ]
        if wanted and not any(want in got or got in want for want in wanted for got in passed):
            errors.append("Declared verification has not passed after mutation: " + " | ".join(wanted))
    return errors


def user_prompt(payload: dict[str, object]) -> None:
    root = repo_root(str(payload.get("cwd") or "") or None)
    prompt_hash = hashlib.sha256(str(payload.get("prompt") or "").encode()).hexdigest()[:16]
    old = contract(root)
    write_json(active_path(root), {"session_id": payload.get("session_id"), "turn_id": payload.get("turn_id"), "prompt_hash": prompt_hash, "at": time.time()})
    if old and old.get("prompt_hash") != prompt_hash:
        write_json(state_dir(root) / "previous_contract.json", old)
        contract_path(root).unlink(missing_ok=True)
    context(str(payload.get("hook_event_name") or "UserPromptSubmit"))


def session_start(payload: dict[str, object]) -> None:
    root = repo_root(str(payload.get("cwd") or "") or None)
    write_json(active_path(root), {"session_id": payload.get("session_id"), "turn_id": payload.get("turn_id"), "at": time.time()})
    context(str(payload.get("hook_event_name") or "SessionStart"))


def declare(args: argparse.Namespace) -> None:
    root = repo_root(args.cwd)
    active_policy = policy(root)
    active = read_json(active_path(root), {})
    old = contract(root) if args.widen else {}
    if args.widen and not args.reason:
        print("Widening requires --reason.", file=sys.stderr)
        raise SystemExit(2)
    preflight_level = "minimal" if args.minimal_preflight else "full"
    default_max_files = active_policy["minimal_preflight_max_files"] if args.minimal_preflight else active_policy["default_max_files"]
    default_max_added = active_policy["minimal_preflight_max_added_lines"] if args.minimal_preflight else active_policy["default_max_added_lines"]
    default_max_changed = active_policy["minimal_preflight_max_changed_lines"] if args.minimal_preflight else active_policy["default_max_changed_lines"]
    identity = repo_identity(root)
    current_contract = {
        "version": VERSION,
        **identity,
        "intent": args.intent,
        "scope": norm_list(args.scope),
        "task_type": args.task_type,
        "assumptions": args.assumption or [],
        "affected_surface": args.affected_surface or [],
        "authoritative_contract": args.authoritative_contract or [],
        "invariants": args.invariant or [],
        "proof_plan": args.proof_plan or [],
        "reuse_path": args.reuse_path,
        "no_reuse_reason": args.no_reuse_reason,
        "preflight_level": preflight_level,
        "chosen_approach": args.chosen_approach,
        "rejected_alternatives": args.rejected_alternative or [],
        "touchpoints": args.touchpoint or [],
        "risk_check": args.risk_check or [],
        "update": args.update or [],
        "verify": args.verify or [],
        "no_tests_reason": args.no_tests_reason,
        "max_files": args.max_files or default_max_files,
        "max_added_lines": args.max_added_lines or default_max_added,
        "max_changed_lines": args.max_changed_lines or default_max_changed,
        "base_ref": args.base_ref,
        "allow_new_files": args.allow_new_files,
        "allow_dependency_changes": args.allow_dependency_changes,
        "allow_config_changes": args.allow_config_changes,
        "allow_bash_writes": args.allow_bash_writes,
        "allow_abstractions": args.allow_abstractions,
        "allow_broad_scope": args.allow_broad_scope,
        "allow_quality_warnings": args.allow_quality_warnings,
        "reason": args.reason,
        "declared_at": time.time(),
        "prompt_hash": active.get("prompt_hash") if isinstance(active, dict) else None,
        "baseline": baseline(root),
        "widened_from": old or None,
    }
    errors = contract_errors(current_contract, active_policy, root)
    if errors:
        print("Lean Change Contract rejected:\n- " + "\n- ".join(errors), file=sys.stderr)
        raise SystemExit(2)
    write_json(contract_path(root), current_contract)
    log_event(root, {"event": "contract_declared", "contract": current_contract})
    print(json.dumps({"ok": True, "contract": current_contract}, indent=2, sort_keys=True))


def pretool(payload: dict[str, object]) -> None:
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    root = checked_hook_root("PreToolUse", payload, tool, tool_input)
    if root is None:
        return
    if not mutating(tool, tool_input):
        return
    current_contract = contract(root)
    active_policy = policy(root)
    apply_active_policy(active_policy)
    errors = contract_errors(current_contract, active_policy, root)
    if errors:
        deny("PreToolUse", "Lean Code Gate blocked mutation before contract:\n- " + "\n- ".join(errors))
        return
    command = tool_command(tool_input)
    if tool == "Bash" and active_policy["block_hidden_bash_writes"] and not ("apply_patch" in command or "*** Begin Patch" in command or "diff --git" in command) and not current_contract.get("allow_bash_writes"):
        deny("PreToolUse", "Hidden file-changing Bash blocked. Use Edit/apply_patch or redeclare --allow-bash-writes with a reason.")
        return
    change_facts = facts(root, tool, tool_input)
    errors = check_change(change_facts, current_contract, active_policy, tool)
    if errors:
        deny("PreToolUse", "Lean Code Gate blocked over-broad or low-quality mutation:\n- " + "\n- ".join(errors))
        return
    remember_target_root(payload, root)
    log_event(root, {"event": "mutation_allowed", "tool": tool, **{key: change_facts[key] for key in ("paths", "added", "deleted")}})


def permission_request(payload: dict[str, object]) -> None:
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    root = checked_hook_root("PermissionRequest", payload, tool, tool_input)
    if root is None:
        return
    if mutating(tool, tool_input):
        errors = contract_errors(contract(root), policy(root), root)
        if errors:
            deny("PermissionRequest", "Mutation approval denied:\n- " + "\n- ".join(errors))


def posttool(payload: dict[str, object], failed: bool = False) -> None:
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    root = checked_hook_root(None, payload, tool, tool_input)
    if root is None:
        return
    if mutating(tool, tool_input):
        log_event(root, {"event": "mutation_failed" if failed else "mutation_finished", "tool": tool, **facts(root, tool, tool_input)})
    command = tool_command(tool_input)
    if tool == "Bash" and verify_cmd(command):
        response = payload.get("tool_response")
        exit_code = response_exit_code(response)
        command_failed = failed or (exit_code is not None and exit_code != 0)
        log_event(root, {"event": "verify_failed" if command_failed else "verify_passed", "command": command, "exit_code": exit_code})


def stop(payload: dict[str, object]) -> None:
    roots = stop_roots(payload)
    if not roots:
        return
    all_errors: list[str] = []
    if payload.get("stop_hook_active"):
        for root in roots:
            issues = final_errors(root, contract(root), policy(root))
            all_errors.extend(f"{root}: {issue}" if len(roots) > 1 else issue for issue in issues)
        issues = all_errors
        if issues:
            emit({"systemMessage": "Lean Code Gate still has unresolved issues after a Stop continuation: " + " | ".join(issues[:8])})
        return
    for root in roots:
        current_contract = contract(root)
        active_policy = policy(root)
        errors = final_errors(root, current_contract, active_policy)
        if active_policy["run_quality_gate_on_stop"]:
            fail_warnings = bool(active_policy["fail_on_quality_warnings"]) and not (current_contract or {}).get("allow_quality_warnings")
            quality = run_quality_gate(root, str((current_contract or {}).get("base_ref") or "") or None, fail_warnings)
            if not quality["ok"]:
                errors.extend(["Quality gate failed: " + error for error in quality["errors"]])
        all_errors.extend(f"{root}: {error}" if len(roots) > 1 else error for error in errors)
    if all_errors:
        deny(
            "Stop",
            "Lean Code Gate final check failed:\n- "
            + "\n- ".join(all_errors)
            + "\nReduce the diff, remove bloat/escapes/duplication, run verification, or widen with a concrete reason.",
        )


def status(args: argparse.Namespace) -> None:
    root = repo_root(args.cwd)
    current_contract = contract(root)
    identity = repo_identity(root)
    runtime = {
        "cwd": os.getcwd(),
        "env_repo_root": os.environ.get("LEAN_CODE_GATE_REPO_ROOT") or "",
        "contract_path": str(contract_path(root)),
        "contract_repo_id": str(current_contract.get("repo_id") or "") if current_contract else "",
        "contract_matches_repo": not contract_identity_errors(root, current_contract) if current_contract else False,
        **identity,
    }
    print(json.dumps({"runtime": runtime, "contract": current_contract, "delta": delta(root, current_contract) if current_contract else {}, "policy": policy(root)}, indent=2, sort_keys=True))


def reset(args: argparse.Namespace) -> None:
    root = repo_root(args.cwd)
    for name in ("active.json", "contract.json", "previous_contract.json", "events.jsonl"):
        (state_dir(root) / name).unlink(missing_ok=True)
    print("Lean Code Gate state reset.")


def check_command(args: argparse.Namespace) -> int:
    root = repo_root(args.repo)
    if not git_ok(root, ["rev-parse", "--show-toplevel"]):
        print(f"ERROR: not a git repository: {root}", file=sys.stderr)
        return 1
    result = run_quality_gate(root, args.base_ref or None, args.fail_on_warnings)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_quality_text(result))
        print("")
        print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


def parser() -> argparse.ArgumentParser:
    root_parser = argparse.ArgumentParser(description="Lean Code Gate v3 hook + contract + quality CLI")
    sub = root_parser.add_subparsers(dest="cmd", required=True)
    for name in ["user-prompt", "session-start", "pretool", "permission-request", "posttool", "posttool-failure", "stop"]:
        sub.add_parser(name)
    declare_parser = sub.add_parser("declare")
    declare_parser.add_argument("--cwd")
    declare_parser.add_argument("--intent", required=True)
    declare_parser.add_argument("--scope", required=True)
    declare_parser.add_argument("--task-type", choices=["bugfix", "feature", "refactor", "test", "docs", "config", "unknown"], default="unknown")
    declare_parser.add_argument("--minimal-preflight", "--lean", dest="minimal_preflight", action="store_true")
    declare_parser.add_argument("--assumption", action="append", default=[])
    declare_parser.add_argument("--affected-surface", action="append", default=[])
    declare_parser.add_argument("--authoritative-contract", action="append", default=[])
    declare_parser.add_argument("--invariant", action="append", default=[])
    declare_parser.add_argument("--proof-plan", action="append", default=[])
    declare_parser.add_argument("--reuse-path", default="")
    declare_parser.add_argument("--no-reuse-reason", default="")
    declare_parser.add_argument("--chosen-approach", default="")
    declare_parser.add_argument("--rejected-alternative", action="append", default=[])
    declare_parser.add_argument("--touchpoint", action="append", default=[])
    declare_parser.add_argument("--risk-check", action="append", default=[])
    declare_parser.add_argument("--update", action="append", default=[])
    declare_parser.add_argument("--verify", action="append", default=[])
    declare_parser.add_argument("--max-files", type=int)
    declare_parser.add_argument("--max-added-lines", type=int)
    declare_parser.add_argument("--max-changed-lines", type=int)
    declare_parser.add_argument("--no-tests-reason", default="")
    declare_parser.add_argument("--reason", default="")
    declare_parser.add_argument("--base-ref", default="")
    declare_parser.add_argument("--widen", action="store_true")
    for flag in [
        "allow-new-files",
        "allow-dependency-changes",
        "allow-config-changes",
        "allow-bash-writes",
        "allow-abstractions",
        "allow-broad-scope",
        "allow-quality-warnings",
    ]:
        declare_parser.add_argument("--" + flag, action="store_true")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--cwd")
    reset_parser = sub.add_parser("reset")
    reset_parser.add_argument("--cwd")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--repo", default=os.getcwd())
    check_parser.add_argument("--base-ref", default="")
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--fail-on-warnings", action="store_true")
    return root_parser


def main() -> int:
    args = parser().parse_args()
    if args.cmd == "declare":
        declare(args)
    elif args.cmd == "status":
        status(args)
    elif args.cmd == "reset":
        reset(args)
    elif args.cmd == "check":
        return check_command(args)
    else:
        payload = hook_input()
        dispatch = {
            "user-prompt": user_prompt,
            "session-start": session_start,
            "pretool": pretool,
            "permission-request": permission_request,
            "posttool": posttool,
            "posttool-failure": lambda value: posttool(value, True),
            "stop": stop,
        }
        dispatch[args.cmd](payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
