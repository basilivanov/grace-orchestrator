# ############################################################################
# AI_HEADER: checker
# ROLE: GraceLint core — importable linter with 14+ canon rules.
#       Used by scripts/grace_lint.py (thin CLI wrapper) and
#       by POST /api/tools/grace-lint/run (API endpoint).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Check Python source files for GRACE canon compliance.
#          Rules GRC001–GRC108 cover AI_HEADER, contracts, env/subprocess
#          usage, file/function size, and architectural constraints.
# inputs: file path(s), optional allowlist dict, optional skip flags.
# returns: list[Violation] — never raises.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises; returns Violation on unreadable file.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: Violation
#   - function: lint_file
#   - function: lint_text
#   - function: load_allowlist
#   - function: _check_env
#   - function: _check_subprocess
#   - function: _check_prefect_grace
#   - function: _check_state_mutation
#   - function: _check_hardcoded_tmp
#   - function: _check_hardcoded_branch
#   - function: _check_blocks
#   - constant: DEFAULT_RULES
# END_MODULE_MAP

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


# START_BLOCK_DTO
@dataclass
class Violation:
    code: str
    message: str
    file: str
    line: int = 1
# END_BLOCK_DTO


def _top_level_count(content: str) -> int:
    try:
        tree = ast.parse(content)
        return sum(
            1 for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                ast.AsyncFunctionDef, ast.ClassDef, ast.Assign))
        )
    except SyntaxError:
        return 0


def _physical_lines(content: str) -> int:
    return len([line for line in content.split("\n") if line.strip()])


# START_FUNCTION_CONTRACT
# name: load_allowlist
# purpose: Load the configured GraceLint rule exemptions.
# inputs: path — optional allowlist path; defaults to .grace/lint_allowlist.yaml.
# returns: Parsed allowlist mapping with a rules list.
# side_effects: Reads the allowlist file when it exists.
# emitted_logs: None.
# error_behavior: Missing or malformed files return an empty allowlist.
# END_FUNCTION_CONTRACT
def load_allowlist(path: Path | None = None) -> dict[str, list[dict]]:
    """Load the lint allowlist from .grace/lint_allowlist.yaml (or path)."""
    cfg = path or Path(".grace/lint_allowlist.yaml")
    if not cfg.exists():
        return {"rules": []}
    try:
        raw = yaml.safe_load(cfg.read_text()) or {}
        return {"rules": list(raw.get("rules") or [])}
    except Exception:
        return {"rules": []}


def _is_allowed(violation_code: str, filepath: str, allowlist: dict) -> bool:
    for entry in allowlist.get("rules") or []:
        if entry.get("rule") == violation_code:
            if entry.get("path") in filepath:
                return True
    return False


# START_FUNCTION_CONTRACT
# name: lint_text
# purpose: Lint a single source string (for IDE / API use).
# inputs: content (str), path (str, shown in violations), allowlist (dict),
#         skip_function_contracts (bool).
# returns: list[Violation].
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def lint_text(
    content: str,
    path: str = "<string>",
    allowlist: dict | None = None,
    skip_function_contracts: bool = False,
    rules_enabled: list[str] | None = None,
) -> list[Violation]:
    """Lint a single source string."""
    violations: list[Violation] = []
    al = allowlist or {"rules": []}
    lines = content.split("\n")

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        v = Violation("GRC000", f"syntax error: {e}", path, e.lineno or 1)
        if not _is_allowed(v.code, path, al):
            return [v]
        return []

    if path.endswith("__init__.py") and not content.strip():
        return []

    # GRC001
    if _rule_enabled("GRC001", rules_enabled) and not re.search(r'# AI_HEADER:', content):
        v = Violation("GRC001", "missing # AI_HEADER:", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)

    # GRC020 / GRC002
    has_start_mc = "# START_MODULE_CONTRACT" in content
    has_end_mc = "# END_MODULE_CONTRACT" in content
    if _rule_enabled("GRC020", rules_enabled) and not has_start_mc and not has_end_mc:
        v = Violation("GRC020", "missing MODULE_CONTRACT", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)
    if has_start_mc != has_end_mc:
        which = "START without END" if has_start_mc else "END without START"
        v = Violation("GRC002", f"MODULE_CONTRACT pairing: {which}", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)

    # GRC021 / GRC003
    has_start_mm = "# START_MODULE_MAP" in content
    has_end_mm = "# END_MODULE_MAP" in content
    if _rule_enabled("GRC021", rules_enabled) and not has_start_mm and not has_end_mm:
        v = Violation("GRC021", "missing MODULE_MAP", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)
    if has_start_mm != has_end_mm:
        which = "START without END" if has_start_mm else "END without START"
        v = Violation("GRC003", f"MODULE_MAP pairing: {which}", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)

    # GRC004
    starts = re.findall(r'# START_BLOCK_(\w+)', content)
    ends = re.findall(r'# END_BLOCK_(\w+)', content)
    if _rule_enabled("GRC004", rules_enabled) and len(starts) != len(ends):
        v = Violation("GRC004", f"BLOCK mismatch: {len(starts)} starts, {len(ends)} ends", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)
    else:
        for s, e in zip(starts, ends, strict=False):
            if s != e:
                v = Violation("GRC004", f"mismatched BLOCK: START_{s} vs END_{e}", path, 1)
                if not _is_allowed(v.code, path, al):
                    violations.append(v)
                break

    # GRC005
    if _rule_enabled("GRC005", rules_enabled) and len(lines) > 1000:
        v = Violation("GRC005", f"file too large: {len(lines)} lines (max 1000)", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)

    # GRC010/GRC011/GRC012
    violations += _check_functions(
        content, lines, tree, path, al, rules_enabled,
        skip_function_contracts=skip_function_contracts,
    )

    # GRC100
    if _rule_enabled("GRC100", rules_enabled):
        violations += _check_env(content, path, al)

    # GRC101
    if _rule_enabled("GRC101", rules_enabled):
        violations += _check_subprocess(content, path, al)

    # GRC102
    if _rule_enabled("GRC102", rules_enabled):
        violations += _check_prefect_grace(content, path, al)

    # GRC103
    if _rule_enabled("GRC103", rules_enabled):
        violations += _check_state_mutation(content, path, al)

    # GRC104
    if _rule_enabled("GRC104", rules_enabled):
        violations += _check_router_db_loops(content, path, al)

    # GRC105
    if _rule_enabled("GRC105", rules_enabled):
        violations += _check_hardcoded_tmp(content, path, al)

    # GRC106
    if _rule_enabled("GRC106", rules_enabled):
        violations += _check_hardcoded_branch(content, path, al)

    # GRC108
    if _rule_enabled("GRC108", rules_enabled):
        violations += _check_blocks(content, lines, path, al)

    # GRC109
    if _rule_enabled("GRC109", rules_enabled):
        violations += _check_hardcoded_cli_agent(content, path, al)

    # GRC030: compressed file
    tls = _top_level_count(content)
    phys = _physical_lines(content)
    if _rule_enabled("GRC030", rules_enabled) and tls > 5 and phys < 5:
        v = Violation("GRC030", f"suspicious compressed file: {tls} top-level stmts on {phys} lines", path, 1)
        if not _is_allowed(v.code, path, al):
            violations.append(v)

    return violations


# START_FUNCTION_CONTRACT
# name: lint_file
# purpose: Lint a file on disk. Same as lint_text but reads the file.
# inputs: filepath (Path), allowlist (dict), skip_function_contracts (bool).
# returns: list[Violation].
# side_effects: Reads filesystem.
# emitted_logs: None.
# error_behavior: Returns Violation if file is unreadable.
# END_FUNCTION_CONTRACT
def lint_file(
    filepath: Path,
    allowlist: dict | None = None,
    skip_function_contracts: bool = False,
    rules_enabled: list[str] | None = None,
) -> list[Violation]:
    try:
        content = filepath.read_text()
    except Exception as e:
        v = Violation("GRC000", f"cannot read file: {e}", str(filepath), 1)
        return [v]
    return lint_text(content, str(filepath), allowlist, skip_function_contracts, rules_enabled)


# START_FUNCTION_CONTRACT
# name: _rule_enabled
# purpose: Check if a rule is enabled (all rules enabled when rules_enabled is None).
# END_FUNCTION_CONTRACT
def _rule_enabled(rule: str, rules_enabled: list[str] | None) -> bool:
    return rules_enabled is None or rule in rules_enabled


# START_BLOCK_FUNCTION_CHECKS
def _check_functions(
    content, lines, tree, path, al, rules_enabled, *, skip_function_contracts=False,
):
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_line = node.lineno
            func_lines = lines[node.lineno - 1:node.end_lineno] if node.end_lineno else []
            est_tokens = len("\n".join(func_lines)) // 4
            if _rule_enabled("GRC012", rules_enabled) and est_tokens > 4000:
                v = Violation("GRC012", f"function '{node.name}' too large: ~{est_tokens} tokens (max 4000)", path, func_line)
                if not _is_allowed(v.code, path, al):
                    violations.append(v)
            if skip_function_contracts or node.name.startswith("_"):
                continue
            before = "\n".join(lines[:func_line])
            has_contract = bool(re.search(r'# START_FUNCTION_CONTRACT\s*\n', before))
            last_end = before.rfind("# END_FUNCTION_CONTRACT")
            last_start = before.rfind("# START_FUNCTION_CONTRACT")
            if not has_contract:
                v = Violation("GRC010", f"public function '{node.name}' missing FUNCTION_CONTRACT", path, func_line)
                if not _is_allowed(v.code, path, al):
                    violations.append(v)
            elif last_end > last_start:
                match = re.search(r'# START_FUNCTION_CONTRACT\s*\n(.*?)# END_FUNCTION_CONTRACT', "\n".join(lines), re.DOTALL)
                if match:
                    contract = match.group(1)
                    req_fields = ["name", "purpose", "inputs", "returns", "side_effects"]
                    missing = [f for f in req_fields if f"{f}:" not in contract]
                    if missing:
                        v = Violation("GRC011", f"function '{node.name}' contract missing: {', '.join(missing)}", path, func_line)
                        if not _is_allowed(v.code, path, al):
                            violations.append(v)
    return violations
# END_BLOCK_FUNCTION_CHECKS


# START_BLOCK_RULES_100
ALLOWED_ENV = {"config/", "tests/", "scripts/", "tools/", "services/agent_env_builder.py"}


def _check_env(content: str, path: str, al: dict) -> list[Violation]:
    """GRC100: no os.environ outside config/tests/scripts."""
    violations = []
    if "os.environ" not in content:
        return violations
    if any(a in path for a in ALLOWED_ENV):
        return violations
    if _is_allowed("GRC100", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        if "os.environ" in line:
            violations.append(Violation("GRC100", f"os.environ outside config/tests/scripts: {line.strip()[:60]}", path, i))
    return violations


ALLOWED_SUBPROCESS = {"services/git_service.py", "services/worktree_cleanup_service.py", "services/process_supervisor.py", "core/llm_runner.py", "scripts/", "tests/"}


def _check_subprocess(content: str, path: str, al: dict) -> list[Violation]:
    """GRC101: no direct subprocess outside GitService/scripts/tests."""
    violations = []
    if "subprocess" not in content:
        return violations
    if any(a in path for a in ALLOWED_SUBPROCESS):
        return violations
    if _is_allowed("GRC101", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        if "subprocess" in line:
            violations.append(Violation("GRC101", f"subprocess outside allowed paths: {line.strip()[:60]}", path, i))
    return violations


def _check_prefect_grace(content: str, path: str, al: dict) -> list[Violation]:
    """GRC102: no prefect_grace in src/grace_control/."""
    violations = []
    if "prefect_grace" not in content:
        return violations
    if "src/grace_control/" not in path and "src\\grace_control" not in path:
        return violations
    if _is_allowed("GRC102", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        if "prefect_grace" in line:
            violations.append(Violation("GRC102", f"prefect_grace import: {line.strip()[:60]}", path, i))
    return violations


def _check_state_mutation(content: str, path: str, al: dict) -> list[Violation]:
    """GRC103: no Packet.state mutation outside PacketService/wave_gate/db/tests."""
    violations = []
    if ".state" not in content and "state=" not in content and "['state']" not in content:
        return violations
    allowed = {"services/packet_service.py", "core/wave_gate.py", "db/", "tests/", "scripts/"}
    if any(a in path for a in allowed):
        return violations
    if _is_allowed("GRC103", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        if ".state" in line or "state=" in line:
            if "state_machine" in line or "PacketState" in line:
                continue
            violations.append(Violation("GRC103", f"Packet.state mutation outside service: {line.strip()[:60]}", path, i))
    return violations


def _check_hardcoded_tmp(content: str, path: str, al: dict) -> list[Violation]:
    """GRC105: no hardcoded /tmp grace paths outside tests/scripts."""
    violations = []
    if "/tmp" not in content:
        return violations
    if any(a in path for a in ("tests/", "scripts/")):
        return violations
    if _is_allowed("GRC105", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        if "/tmp" in line and "grace" in line.lower():
            violations.append(Violation("GRC105", f"hardcoded /tmp path: {line.strip()[:60]}", path, i))
    return violations


def _check_hardcoded_branch(content: str, path: str, al: dict) -> list[Violation]:
    """GRC106: no hardcoded branch/remote outside config/tests."""
    violations = []
    allowed = {"config/", "tests/", "scripts/", "legacy_"}
    if any(a in path for a in allowed):
        return violations
    if _is_allowed("GRC106", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        s = line.strip()
        if ('"main"' in s or "'main'" in s or '"origin"' in s or "'origin'" in s) and "base_branch" not in s:
            violations.append(Violation("GRC106", f"hardcoded branch/remote: {s[:60]}", path, i))
    return violations


def _check_blocks(content: str, lines: list[str], path: str, al: dict) -> list[Violation]:
    """GRC108: modules over 300 lines must have logical START_BLOCK sections."""
    violations = []
    if len(lines) <= 300:
        return violations
    if _is_allowed("GRC108", path, al):
        return violations
    start_blocks = re.findall(r'# START_BLOCK_\w+', content)
    if len(start_blocks) == 0:
        violations.append(Violation("GRC108", f"module is {len(lines)} lines but has no START_BLOCK sections", path, 1))
    return violations


def _check_router_db_loops(content: str, path: str, al: dict) -> list[Violation]:
    """GRC104: routers must not contain heavy DB aggregation loops (for/db.query)."""
    violations = []
    if "routers/" not in path:
        return violations
    if _is_allowed("GRC104", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        s = line.strip()
        if "for " in s and ("db.query" in s or "self._db" in s):
            violations.append(Violation("GRC104", f"router contains DB loop: {s[:60]}", path, i))
    return violations


_KNOWN_CLI_AGENTS = {"opencode", "codex", "agy", "gemini", "claude"}


def _check_hardcoded_cli_agent(content: str, path: str, al: dict) -> list[Violation]:
    """GRC109: no hardcoded CLI agent command names in runtime execution code."""
    violations = []
    if any(a in path for a in ("config/", "tests/", "docs/")):
        return violations
    if _is_allowed("GRC109", path, al):
        return violations
    for i, line in enumerate(content.split("\n"), 1):
        for name in _KNOWN_CLI_AGENTS:
            if name in line:
                violations.append(Violation("GRC109", f"hardcoded CLI agent '{name}': {line.strip()[:60]}", path, i))
                break
    return violations


# END_BLOCK_RULES_100


DEFAULT_RULES: list[str] = [
    "GRC001", "GRC002", "GRC003", "GRC004", "GRC005",
    "GRC010", "GRC011", "GRC012",
    "GRC020", "GRC021", "GRC030",
    "GRC100", "GRC101", "GRC102", "GRC103",
    "GRC104",
    "GRC105", "GRC106", "GRC108", "GRC109",
]
