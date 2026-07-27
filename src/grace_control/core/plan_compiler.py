# ############################################################################
# AI_HEADER: plan_compiler
# ROLE: Deterministic preflight validator — compiles architect plan before
#        coder execution, rejecting invalid packets before runtime.
# ############################################################################

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from grace_control.core.contracts import SUPPORTED_EVIDENCE_KINDS
from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_compiler")


# ── Source split intent models ──────────────────────────────────────────
@dataclass
class SourceSplitIntent:
    source_path: str
    old_import_path: str | None = None
    new_package_prefix: str | None = None
    operation: str = "split"  # split, extract, move, refactor
    requires_source_modification: bool = True
    requires_import_migration: bool = False
    allows_shim: bool = True


@dataclass
class RepoReference:
    path: str
    line: int
    text: str


class CompileError(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    packet_title: str | None = None
    field_path: str
    message: str
    suggestion: str | None = None
    details: dict | None = None

    model_config = {"frozen": False}


class CompileResult(BaseModel):
    ok: bool
    errors: list[CompileError] = []
    warnings: list[CompileError] = []
    normalized_plan: dict | None = None

    model_config = {"frozen": False}


# ── Grep pattern with unquoted spaces ──────────────────────────────────
_GREP_SPACE_PATTERN = re.compile(
    r'\bgrep\s+(?:-[A-Za-z]+\s+)*([^-\'\"][\w\s]+?)\s+\S+'
)


# ── Invalid Python one-liner patterns ─────────────────────────────────
_INVALID_PY_PATTERNS = [
    # for/while at end of line with colon (no body possible)
    re.compile(r'\bfor\s+\w+\s+in\s+[^:]+:\s*$'),
    re.compile(r'\bwhile\s+[^:]+:\s*$'),
    re.compile(r'\bif\s+[^:]+:\s*$'),
    # class/def at end of file (no body possible)
    re.compile(r'\b(class|def)\s+\w+[^(]*:\s*$'),
]


# ── Bash-only syntax patterns ──────────────────────────────────────────
_BASH_ONLY_PATTERNS = [
    (re.compile(r'\bsource\s'), "source", "use . (dot) instead of source"),
    (re.compile(r'\[\[\s+'), "[[", "use [ instead of [[ for POSIX sh"),
    (re.compile(r'\$\{(\w+)[/#]'), "${VAR//x/y}", "bash-only parameter expansion, use sed/tr instead"),
]


def _contains_unquoted_shell_word(command: str, word: str) -> bool:
    """Return whether *word* occurs outside single/double quoted data.

    Plan verification often greps for forbidden source text.  A quoted grep
    pattern containing ``source`` is data, not the bash ``source`` builtin,
    and must not be rejected under ``/bin/sh``.
    """
    quote: str | None = None
    escaped = False
    unquoted: list[str] = []
    for char in command:
        if escaped:
            escaped = False
            unquoted.append(" ")
            continue
        if quote is not None:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"':
                escaped = True
            unquoted.append(" ")
            continue
        if char in {"'", '"'}:
            quote = char
            unquoted.append(" ")
            continue
        if char == "\\":
            escaped = True
            unquoted.append(" ")
            continue
        unquoted.append(char)
    return re.search(rf"\b{re.escape(word)}\b", "".join(unquoted)) is not None


# ── Shell operators in argv list (require shell=True) ──────────────────
_SHELL_OPS_IN_CMDS = re.compile(r'&&|\|\||[;|><]|\$\(|2>&1')

_COMMAND_SEPARATORS = frozenset({"&&", "||", ";", "|"})
_SCRIPT_SUFFIXES = (".py", ".sh")
_SYSTEM_ABSOLUTE_PATHS = frozenset({"/bin/sh", "/bin/bash", "/usr/bin/env", "/dev/null"})
_SEARCH_PROGRAMS = frozenset({"grep", "egrep", "rg"})


def _command_segments(command: str) -> list[list[str]]:
    """Split a command into simple invocations without interpreting shell syntax."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _first_program_index(tokens: list[str]) -> int | None:
    """Return the executable index after shell negation and NAME=value prefixes."""
    index = 0
    while index < len(tokens) and tokens[index] == "!":
        index += 1
    while index < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
        index += 1
    return index if index < len(tokens) else None


def _negative_search_test_targets(command: str) -> list[str]:
    """Return test paths scanned by a shell-negated text search.

    An absence assertion that scans tests commonly matches the regression test's
    own forbidden literal, so it cannot distinguish product code from proof of
    the requirement.  Keep the check conservative and only flag explicit
    repository test paths after the search pattern.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    if len(tokens) < 4 or tokens[0] != "!" or Path(tokens[1]).name not in _SEARCH_PROGRAMS:
        return []

    pattern_seen = False
    targets: list[str] = []
    for token in tokens[2:]:
        if token.startswith("-"):
            continue
        if not pattern_seen:
            pattern_seen = True
            continue
        normalized = token.removeprefix("./").rstrip("/")
        if normalized in {"test", "tests"} or normalized.startswith(("test/", "tests/")):
            targets.append(token)
    return targets


def _relative_command_path(value: str, target_repo_root: Path | None) -> str | None:
    """Normalize a command path to target-repository-relative form when possible."""
    path = Path(value)
    if path.is_absolute():
        if target_repo_root is None:
            return None
        try:
            return path.relative_to(target_repo_root.resolve()).as_posix()
        except ValueError:
            return None
    if ".." in path.parts:
        return None
    normalized = path.as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def _known_script_paths(env: ExecutionEnvironment) -> set[str]:
    """Extract script paths from discovered files and optional verification overrides."""
    known = set(env.executable_scripts)
    for entrypoint in env.verification_entrypoints:
        if entrypoint.endswith(_SCRIPT_SUFFIXES):
            known.add(entrypoint)
            continue
        try:
            tokens = shlex.split(entrypoint, posix=True)
        except ValueError:
            continue
        known.update(token for token in tokens if token.endswith(_SCRIPT_SUFFIXES))
    return known


def _python_module_exists(
    module: str,
    python_program: str,
    target_repo_root: Path | None,
) -> bool:
    """Check repository and venv module paths without executing target code."""
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
        return False
    root = (target_repo_root or Path.cwd()).resolve()
    module_path = Path(*module.split("."))
    if module.split(".", 1)[0] in sys.stdlib_module_names:
        return True
    for base in (root, root / "src"):
        if (base / module_path).with_suffix(".py").is_file():
            return True
        if (base / module_path / "__init__.py").is_file():
            return True
    for site_packages in root.glob(".venv/lib/python*/site-packages"):
        if (site_packages / module_path).with_suffix(".py").is_file():
            return True
        if (site_packages / module_path / "__init__.py").is_file():
            return True

    # Bare interpreter names occur only in explicitly constructed legacy
    # environments. Runtime discovery never invents them for a target repo.
    if "/" not in python_program:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, AttributeError, ValueError):
            return False
    return False


def _add_error(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
    details: dict | None = None,
) -> None:
    result.errors.append(
        CompileError(
            code=code,
            severity="error",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
            details=details,
        )
    )
    result.ok = False


def _add_warning(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
) -> None:
    result.warnings.append(
        CompileError(
            code=code,
            severity="warning",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
        )
    )


# ── Source split / import migration helpers ────────────────────────────

_SOURCE_SPLIT_KEYWORDS = [
    "split", "break up", "extract", "move", "refactor",
    "decompose", "modularize", "shim", "legacy module", "old import",
    # Russian
    "разбить", "разделить", "вынести", "распилить",
    "декомпозировать", "разнести", "рефактор", "перенести",
    "разбиение", "разделение",
]

_SOURCE_SPLIT_PATH_PATTERN = re.compile(
    r'(apps/api/\S+\.py|packages/\S+\.py|src/\S+\.py|grace/\S+\.py)'
)

_OLD_IMPORT_PATTERN = re.compile(
    r'(app\.\w+(?:\.\w+)+)'  # e.g. app.services.llm_service
)


def _import_path_to_source_path(import_path: str) -> str:
    """Convert app.services.llm_service → apps/api/app/services/llm_service.py."""
    parts = import_path.split(".")
    if parts[0] == "app":
        # app.services.llm_service → apps/api/app/services/llm_service.py
        return "apps/api/" + "/".join(parts) + ".py"
    if parts[0] in ("src", "packages", "scripts"):
        return "/".join(parts) + ".py"
    return import_path


def detect_source_split_intents(feature_description: str, plan: dict, env: ExecutionEnvironment) -> list[SourceSplitIntent]:
    """Analyze feature description + plan for split/refactor patterns."""
    intents: list[SourceSplitIntent] = []
    all_text = feature_description.lower()

    # Check if it's a split/refactor task
    is_split = any(kw in all_text for kw in _SOURCE_SPLIT_KEYWORDS)
    if not is_split:
        return intents

    # Find source file paths in description
    paths = _SOURCE_SPLIT_PATH_PATTERN.findall(feature_description)
    import_candidates = _OLD_IMPORT_PATTERN.findall(feature_description)

    # Also scan T0/T1/T2 for old import references
    for wave in plan.get("waves", []):
        for pkt in wave.get("packets", []):
            for v_key in ("t0", "t1", "t2"):
                for cmd in pkt.get("verification", {}).get(v_key, []):
                    cmd_str = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
                    imps = _OLD_IMPORT_PATTERN.findall(cmd_str)
                    import_candidates.extend(imps)

    unique_paths = set(paths)
    unique_imports = set(import_candidates)

    for path in unique_paths:
        parent = str(Path(path).parent)
        intents.append(SourceSplitIntent(
            source_path=path,
            new_package_prefix=parent + "/" if parent else None,
            operation="split",
        ))

    for imp in unique_imports:
        source = _import_path_to_source_path(imp)
        # Always create a refactor intent for import migration checks,
        # even if the source path was also detected from feature description.
        intents.append(SourceSplitIntent(
            source_path=source,
            old_import_path=imp,
            operation="refactor",
            requires_import_migration=True,
        ))

    return intents


def collect_repo_references(target_root: Path, import_path: str) -> list[RepoReference]:
    """Scan active code dirs for old import path references."""
    if not target_root or not target_root.exists():
        return []
    refs: list[RepoReference] = []
    search_dirs = ["apps/", "src/", "tests/", "packages/", "scripts/"]
    exclude_dirs = {".git", ".grace", "node_modules", ".venv", "dist", "build", "coverage", "__pycache__", "archive"}

    for rel_dir in search_dirs:
        search_root = target_root / rel_dir
        if not search_root.exists():
            continue
        for fpath in sorted(search_root.rglob("*.py")):
            # Check if in excluded dir
            parts = fpath.relative_to(target_root).parts
            if any(ex in parts for ex in exclude_dirs):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if import_path in line:
                    refs.append(RepoReference(
                        path=str(fpath.relative_to(target_root)),
                        line=lineno,
                        text=line.strip()[:300],
                    ))
                    if len(refs) >= 100:
                        return refs
    return refs


class PlanCompiler:

    _VALID_EXPECTATIONS = frozenset({
        "exists", "created", "modified", "deleted", "absent",
        "diff_contains", "test_output", "import_absent", "import_updated",
    })

    def compile_plan(
        self,
        plan: dict,
        env: ExecutionEnvironment | None = None,
        *,
        feature_description: str = "",
        target_repo_root: Path | None = None,
    ) -> CompileResult:
        if env is None:
            from grace_control.core.execution_environment import probe_execution_environment
            env = probe_execution_environment(target_repo_root=target_repo_root)

        result = CompileResult(ok=True)

        waves = plan.get("waves", [])
        if not waves:
            return result  # Empty plan is valid (nothing to do)

        # Enforce a feature-declared per-packet Python-file limit. This keeps
        # the compiler generic while making an explicit business constraint
        # executable instead of trusting a contradictory plan assertion.
        limit_text = feature_description + "\n" + str(plan.get("constraints", {}))
        python_file_limit: int | None = None
        limit_match = re.search(
            r"(?:at\s+most|no\s+more\s+than|maximum(?:\s+of)?|<=|≤)\s*"
            r"(\d+)\s+(?:tracked\s+)?(?:python[- ]?)?files?",
            limit_text,
            re.IGNORECASE,
        )
        if limit_match:
            python_file_limit = int(limit_match.group(1))

        # A first-wave bootstrap packet may create a project-level venv that
        # does not exist yet at planning time.  Permit later packets to refer
        # to that environment when the plan explicitly scopes it OR declares
        # it as a generated bootstrap side effect. Generated/ignored venvs do
        # not always belong in a packet's tracked repository write scope.
        plan_bootstraps_venv = False
        for wave in waves:
            if not isinstance(wave, dict):
                continue
            for packet in wave.get("packets", []) or []:
                if not isinstance(packet, dict):
                    continue
                scope_entries = packet.get("scope", [])
                if not isinstance(scope_entries, list):
                    continue
                has_venv_scope = any(
                    isinstance(scope_entry, str) and ".venv" in scope_entry
                    for scope_entry in scope_entries
                )
                packet_text = " ".join(
                    str(packet.get(key, ""))
                    for key in ("title", "description", "coder_instructions")
                )
                declares_venv_bootstrap = (
                    ".venv" in packet_text
                    and re.search(r"\b(bootstrap|create)\b", packet_text, re.IGNORECASE)
                )
                if (has_venv_scope or declares_venv_bootstrap) and re.search(
                    r"\b(bootstrap|create)\b", packet_text, re.IGNORECASE
                ):
                    plan_bootstraps_venv = True
                    break
            if plan_bootstraps_venv:
                break

        # ── 0. Source-split preflight (before per-packet checks) ─────
        self._validate_source_split(result, plan, env, feature_description, target_repo_root)

        for wi, wave in enumerate(waves):
            for pi, packet in enumerate(wave.get("packets", [])):
                title = packet.get("title", f"wave-{wi}-pkt-{pi}")
                scope = packet.get("scope", [])
                role = packet.get("role", "coder")

                # ── W02: Fail-closed scope type validation ──────────────
                # Scope MUST be a list. A string scope is truthy but iterates
                # as characters (e.g. "src/foo/" → ["s","r","c","/","f","o","o","/"]),
                # producing misleading per-character errors. Reject early.
                if scope is not None and not isinstance(scope, list):
                    _add_error(
                        result, "E_SCOPE_NOT_LIST",
                        f"waves[{wi}].packets[{pi}].scope",
                        f"scope must be a list of strings, got {type(scope).__name__} — "
                        f"string scope iterates as characters instead of file paths",
                        title,
                        "use a list of strings: ['path/to/file.py', 'path/to/dir/']",
                    )
                    # Reset to empty list to avoid iterating non-list
                    scope = []

                # ── W02: Fail-closed scope validation ────────────────
                # Coder packets MUST have explicit, non-empty scope.
                # Missing/empty scope = compiler error, not a default fallback.
                if role == "coder" and not scope:
                    _add_error(
                        result, "E_CODER_EMPTY_SCOPE",
                        f"waves[{wi}].packets[{pi}].scope",
                        f"coder packet '{title}' has no write scope — "
                        f"every coder packet must specify explicit repo-relative scope",
                        title,
                        "add target files/directories to scope (e.g. ['src/grace_control/services/'])",
                    )

                # W02: Validate each scope path
                for si, sp in enumerate(scope):
                    if not isinstance(sp, str):
                        _add_error(
                            result, "E_SCOPE_PATH_NOT_STRING",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope entry must be a string, got {type(sp).__name__}",
                            title,
                        )
                        continue

                    # W02: Reject absolute paths (not silently stripped)
                    if sp.startswith("/"):
                        _add_error(
                            result, "E_SCOPE_ABSOLUTE_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' is absolute — scope must be repo-relative",
                            title,
                            f"remove leading '/': '{sp.lstrip("/")}'",
                        )

                    # W02: Reject parent paths (..)
                    if ".." in Path(sp).parts:
                        _add_error(
                            result, "E_SCOPE_PARENT_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' contains '..' — scope must be within repo",
                            title,
                            "use repo-relative path without parent references",
                        )

                    # W02: Reject Python import paths (dot-separated, no /)
                    # Exclude filenames with common extensions (e.g. "file.py", "config.yaml")
                    # which are valid filesystem paths, not Python imports.
                    _FILE_EXTENSIONS = (
                        ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md",
                        ".cfg", ".ini", ".sh", ".bash", ".sql", ".html", ".css",
                        ".js", ".ts", ".tsx", ".jsx", ".rs", ".go",
                    )
                    if "." in sp and "/" not in sp and not sp.startswith(".") and not sp.endswith(_FILE_EXTENSIONS):
                        _add_error(
                            result, "E_SCOPE_PYTHON_IMPORT_PATH",
                            f"waves[{wi}].packets[{pi}].scope[{si}]",
                            f"scope path '{sp}' looks like a Python import path — "
                            f"scope must be filesystem paths (e.g. 'src/grace_control/services/')",
                            title,
                            f"convert to filesystem path: replace dots with '/' and add '.py' or '/'",
                        )

                    # A repo-root app/ directory is a valid project topology.
                    # Import-style paths such as app.services.foo are rejected
                    # by E_SCOPE_PYTHON_IMPORT_PATH above; filesystem paths must
                    # not be rewritten to one particular monorepo layout.

                if role == "coder" and python_file_limit and target_repo_root:
                    scoped_python_files: set[str] = set()
                    for scope_entry in scope:
                        if not isinstance(scope_entry, str):
                            continue
                        normalized_entry = scope_entry.rstrip("/")
                        if normalized_entry.endswith(".py"):
                            scoped_python_files.add(normalized_entry)
                            continue
                        scope_path = target_repo_root / normalized_entry
                        try:
                            if scope_path.is_dir():
                                scoped_python_files.update(
                                    str(path.relative_to(target_repo_root))
                                    for path in scope_path.rglob("*.py")
                                    if path.is_file()
                                )
                            elif any(char in normalized_entry for char in "*?["):
                                scoped_python_files.update(
                                    str(path.relative_to(target_repo_root))
                                    for path in target_repo_root.glob(normalized_entry)
                                    if path.is_file() and path.suffix == ".py"
                                )
                        except OSError:
                            continue
                    if len(scoped_python_files) > python_file_limit:
                        _add_error(
                            result,
                            "E_SCOPE_PYTHON_FILE_LIMIT",
                            f"waves[{wi}].packets[{pi}].scope",
                            f"scope expands to {len(scoped_python_files)} Python files, "
                            f"exceeding the feature-declared limit of {python_file_limit}",
                            title,
                            "split the coder work into bounded dependent packets or "
                            "make the broad final sweep verification-only",
                            details={
                                "python_file_count": len(scoped_python_files),
                                "python_file_limit": python_file_limit,
                                "sample_paths": sorted(scoped_python_files)[:20],
                            },
                        )

                # W02: Reject scope/frozen_scope overlap (not silently strip)
                frozen = packet.get("frozen_scope", []) or []
                if scope and frozen:
                    overlap = set(scope) & set(frozen)
                    if overlap:
                        _add_error(
                            result, "E_SCOPE_FROZEN_OVERLAP",
                            f"waves[{wi}].packets[{pi}].scope",
                            f"scope and frozen_scope overlap: {sorted(overlap)} — "
                            f"a file cannot be both writable and frozen",
                            title,
                            f"remove overlapping paths from either scope or frozen_scope",
                        )

                # W02: Reject root constraints.frozen_scope overlap with packet scope.
                # Root frozen_scope is applied during materialization AFTER compiler
                # validation — so a packet with scope overlapping root frozen_scope
                # would silently become a READY packet that violates scope contract.
                root_constraints = plan.get("constraints", {})
                root_frozen = root_constraints.get("frozen_scope", []) or []
                if scope and root_frozen:
                    root_overlap = set(scope) & set(root_frozen)
                    if root_overlap:
                        _add_error(
                            result, "E_ROOT_FROZEN_SCOPE_OVERLAP",
                            f"waves[{wi}].packets[{pi}].scope",
                            f"scope overlaps with root constraints.frozen_scope: "
                            f"{sorted(root_overlap)} — root frozen paths are applied "
                            f"during materialization and cannot be writable",
                            title,
                            "remove overlapping paths from packet scope or root constraints.frozen_scope",
                        )

                verification = packet.get("verification", {})
                evidence = packet.get("expected_evidence", [])
                role = packet.get("role", "coder")
                description = packet.get("description", "")
                acceptance = packet.get("acceptance_criteria", [])
                coder_instructions = packet.get("coder_instructions", [])

                if isinstance(verification, dict):
                    t0 = verification.get("t0", [])
                    t1 = verification.get("t1", [])
                    t2 = verification.get("t2", [])
                elif isinstance(verification, list):
                    # Compatibility for old predefined-plan API callers.  The
                    # canonical architect schema remains an object with t0/t1/t2;
                    # a legacy flat list is validated as targeted T1 commands.
                    t0 = []
                    t1 = verification
                    t2 = []
                    _add_warning(
                        result,
                        "W_VERIFICATION_LEGACY_LIST",
                        f"waves[{wi}].packets[{pi}].verification",
                        "verification is a legacy command list; canonical packets use an object with t0/t1/t2 arrays",
                        title,
                        "use verification: {t0: [], t1: [...], t2: []}",
                    )
                else:
                    t0 = []
                    t1 = []
                    t2 = []
                    _add_error(
                        result,
                        "E_VERIFICATION_INVALID_TYPE",
                        f"waves[{wi}].packets[{pi}].verification",
                        f"verification must be an object or legacy list, got {type(verification).__name__}",
                        title,
                        "use verification: {t0: [], t1: [], t2: []}",
                    )

                # ── 1. Command syntax validation ──────────────────
                all_cmds = [(t0, "t0"), (t1, "t1"), (t2, "t2")]
                for cmds, stage_name in all_cmds:
                    for ci, cmd in enumerate(cmds):
                        if isinstance(cmd, str):
                            self._validate_cmd(
                                result, cmd, env, title,
                                f"verification.{stage_name}[{ci}]",
                                allow_planned_venv=plan_bootstraps_venv,
                                target_repo_root=target_repo_root,
                            )

                # ── 2. Scope vs acceptance ────────────────────────
                self._validate_scope_acceptance(
                    result, title, scope, t1, acceptance, coder_instructions, role,
                    target_repo_root,
                )

                # ── 3. Evidence contract ──────────────────────────
                self._validate_evidence(
                    result, title, evidence, role, description, scope, verification
                )

                # ── 3b. Evidence–instruction contradiction ──────
                self._validate_evidence_contradiction(
                    result, title, evidence, coder_instructions,
                    description, packet.get("validation_hint", ""),
                )

                # ── 4. Role/scope consistency ─────────────────────
                self._validate_role_scope(result, title, role, scope, description)

        _log.info("compile_done", ok=result.ok, errors=len(result.errors),
                  warnings=len(result.warnings))
        return result

    def _validate_source_split(
        self,
        result: CompileResult,
        plan: dict,
        env: ExecutionEnvironment,
        feature_description: str,
        target_repo_root: Path | None = None,
    ) -> None:
        """Reject split/refactor plans that omit the original source file from scope."""
        if not feature_description:
            return

        intents = detect_source_split_intents(feature_description, plan, env)
        if not intents:
            return

        # Collect all files in scope across all packets + global frozen scope
        all_scope_files: set[str] = set()
        for wave in plan.get("waves", []):
            for pkt in wave.get("packets", []):
                for s in pkt.get("scope", []) or []:
                    all_scope_files.add(s)
        # Plan-level frozen_scope also counts — files that are explicitly
        # protected from modification don't need to be in packet scope.
        for fs in plan.get("constraints", {}).get("frozen_scope", []) or []:
            all_scope_files.add(fs)

        for intent in intents:
            src = intent.source_path
            old_imp = intent.old_import_path

            # Skip intents for files that don't exist in the repo — these
            # are new files being created, not source files being refactored.
            source_exists = False
            if target_repo_root and target_repo_root.exists():
                test_path = target_repo_root / src
                if test_path.exists():
                    source_exists = True
            if not source_exists and target_repo_root:
                # Fallback: check relative paths without target repo root
                if Path(src).exists():
                    source_exists = True

            # E_SOURCE_SPLIT_ORIGIN_MISSING: source file must be in scope
            if intent.requires_source_modification and src not in all_scope_files:
                # Only flag if source file ACTUALLY EXISTS — new files being
                # created don't need an origin source to be in scope.
                if not source_exists:
                    continue
                _add_error(
                    result, "E_SOURCE_SPLIT_ORIGIN_MISSING",
                    "scope",
                    f"Task requires split/refactor of {src}, but this file is not "
                    f"in any coder packet's write scope. Creating new modules is not "
                    f"enough; the original file must become a shim/delegator or be updated.",
                    None,
                    f"Add {src} to an implementation packet's scope, or explicitly declare "
                    f"this as a create-only preparation phase that does not require old "
                    f"imports to be removed.",
                )

            # E_IMPORT_MIGRATION_SCOPE_INCOMPLETE: old imports outside scope
            if intent.requires_import_migration and old_imp and target_repo_root and source_exists:
                refs = collect_repo_references(target_repo_root, old_imp)
                if refs:
                    outside: set[str] = set()
                    for r in refs:
                        if r.path not in all_scope_files and "docs/" not in r.path and "archive" not in r.path:
                            outside.add(r.path)
                    if outside:
                        ref_paths = sorted(outside)[:10]
                        import_details = {
                            "old_import": old_imp,
                            "source_path": src,
                            "outside_refs": sorted(outside),
                        }
                        _add_error(
                            result, "E_IMPORT_MIGRATION_SCOPE_INCOMPLETE",
                            "scope",
                            f"Plan requires old import {old_imp} from {src} to be "
                            f"removed, but {len(outside)} active references remain "
                            f"outside write scope: {ref_paths}",
                            None,
                            "Include all active reference files in scope, split import "
                            "migration into another packet, or keep old module as shim "
                            "and relax T0 to allow shim-only reference.",
                            details=import_details,
                        )

    def _validate_cmd(
        self,
        result: CompileResult,
        cmd: str,
        env: ExecutionEnvironment,
        title: str,
        field_path: str,
        allow_planned_venv: bool = False,
        target_repo_root: Path | None = None,
    ) -> None:
        shell_is_bash = Path(env.shell).name == "bash"
        python_candidates = set(env.python_candidates)
        known_scripts = _known_script_paths(env)

        # Shell incompatibility: source under dash
        if not shell_is_bash and _contains_unquoted_shell_word(cmd, "source"):
            _add_error(
                result, "E_SHELL_SOURCE_UNDER_DASH",
                field_path, f"command uses 'source' but shell is {env.shell} (not bash)",
                title, "use '.' (dot) instead or run under bash",
            )

        # Source in general → warn (should use .)
        if "source .venv" in cmd or "source venv" in cmd:
            _add_warning(
                result, "W_SHELL_SOURCE",
                field_path, "command uses 'source' for venv activation (bash-only)",
                title, "use '. .venv/bin/activate' or run python directly",
            )

        # Missing venv reference
        references_venv_activation = ".venv/bin/activate" in cmd
        references_venv_python = ".venv/bin/python" in cmd
        if references_venv_activation or references_venv_python:
            has_discovered_venv = any(
                candidate.endswith(".venv/bin/python")
                for candidate in python_candidates
            )
            if not has_discovered_venv and not allow_planned_venv:
                _add_error(
                    result, "E_VENV_MISSING",
                    field_path,
                    "command references venv but target repo has no .venv",
                    title,
                    "use a Python path reported by runtime discovery or create the venv explicitly",
                )
            elif allow_planned_venv and not has_discovered_venv:
                _add_warning(
                    result, "W_VENV_PLANNED_BOOTSTRAP",
                    field_path,
                    "command references a project venv created by an earlier bootstrap packet",
                    title,
                    "keep the bootstrap packet before all packets that use this venv",
                )
            elif references_venv_activation:
                _add_warning(
                    result, "W_VENV_ACTIVATE_IN_WORKTREE",
                    field_path,
                    "venv exists in target repo but may not exist in worktree; "
                    "activation will fail at runtime in worktree",
                    title,
                    "run the discovered repository-relative Python directly instead of activation: "
                    f"{next(iter(env.python_candidates), '.venv/bin/python')} -m pytest ...",
                )

        # Deterministic executable, script, module, and absolute-path checks.
        for segment in _command_segments(cmd):
            program_index = _first_program_index(segment)
            if program_index is None:
                continue
            program = segment[program_index]
            program_name = Path(program).name

            for token in segment:
                if not token.startswith("/") or token in _SYSTEM_ABSOLUTE_PATHS:
                    continue
                relative = _relative_command_path(token, target_repo_root)
                if relative is not None:
                    allowed_paths = python_candidates | known_scripts | set(env.config_sources)
                    if relative not in allowed_paths:
                        _add_error(
                            result,
                            "E_TARGET_ABSOLUTE_PATH_UNDISCOVERED",
                            field_path,
                            f"absolute target path '{token}' was not reported by runtime discovery",
                            title,
                            "use a repository-relative path reported in deterministic environment facts",
                        )
                elif token.startswith(("/opt/", "/home/", "/workspace/")):
                    _add_error(
                        result,
                        "E_TARGET_ABSOLUTE_PATH_UNDISCOVERED",
                        field_path,
                        f"absolute target-specific path '{token}' does not belong to the probed repository",
                        title,
                        "use repository-relative paths from deterministic environment facts",
                    )

            is_python = bool(re.fullmatch(r"python\d*(?:\.\d+)?", program_name))
            if is_python:
                normalized_program = _relative_command_path(program, target_repo_root)
                program_is_known = (
                    program in python_candidates
                    or normalized_program in python_candidates
                )
                if not program_is_known and not allow_planned_venv:
                    _add_error(
                        result,
                        "E_EXECUTABLE_NOT_DISCOVERED",
                        field_path,
                        f"Python executable '{program}' was not reported by runtime discovery",
                        title,
                        "use one of ExecutionEnvironment.python_candidates",
                    )
                    continue
                if program_is_known and "/" in program and not allow_planned_venv:
                    executable_relative = _relative_command_path(program, target_repo_root)
                    executable_path = (
                        target_repo_root / executable_relative
                        if target_repo_root is not None and executable_relative is not None
                        else None
                    )
                    if (
                        executable_path is None
                        or not executable_path.is_file()
                        or not os.access(executable_path, os.X_OK)
                    ):
                        _add_error(
                            result,
                            "E_EXECUTABLE_PATH_MISSING",
                            field_path,
                            f"Python executable path '{program}' does not exist or is not executable",
                            title,
                            "fix the grace/project.yaml override or use a discovered executable",
                        )
                        continue

                arguments = segment[program_index + 1:]
                if "-m" in arguments:
                    module_index = arguments.index("-m") + 1
                    if module_index < len(arguments):
                        module = arguments[module_index]
                        if not allow_planned_venv and not _python_module_exists(
                            module,
                            program,
                            target_repo_root,
                        ):
                            _add_error(
                                result,
                                "E_PYTHON_MODULE_MISSING",
                                field_path,
                                f"Python module '{module}' does not exist in the probed environment",
                                title,
                                "use an existing module or a discovered verification script path",
                            )
                    continue

                script = next(
                    (
                        argument for argument in arguments
                        if not argument.startswith("-") and argument.endswith(_SCRIPT_SUFFIXES)
                    ),
                    None,
                )
                if script is not None:
                    self._validate_script_path(
                        result,
                        script,
                        known_scripts,
                        title,
                        field_path,
                        target_repo_root,
                    )
                continue

            script: str | None = None
            if program.endswith(_SCRIPT_SUFFIXES):
                script = program
            elif program_name in {"sh", "bash"}:
                script = next(
                    (
                        argument for argument in segment[program_index + 1:]
                        if not argument.startswith("-") and argument.endswith(_SCRIPT_SUFFIXES)
                    ),
                    None,
                )
            if script is not None:
                self._validate_script_path(
                    result,
                    script,
                    known_scripts,
                    title,
                    field_path,
                    target_repo_root,
                    require_executable=script == program,
                    executable_scripts=set(env.executable_scripts),
                )
            elif "/" in program:
                relative_program = _relative_command_path(program, target_repo_root)
                executable_path = (
                    target_repo_root / relative_program
                    if target_repo_root is not None and relative_program is not None
                    else None
                )
                if (
                    executable_path is None
                    or not executable_path.is_file()
                    or not os.access(executable_path, os.X_OK)
                ):
                    _add_error(
                        result,
                        "E_EXECUTABLE_PATH_MISSING",
                        field_path,
                        f"executable path '{program}' does not exist or is not executable",
                        title,
                        "use a discovered executable script or a command available on PATH",
                    )

        test_targets = _negative_search_test_targets(cmd)
        if test_targets:
            _add_error(
                result,
                "E_NEGATIVE_SEARCH_SCANS_TESTS",
                field_path,
                "shell-negated absence search scans test paths and can match its own regression assertion: "
                + ", ".join(test_targets),
                title,
                "scan implementation/configuration paths only; prove the same absence separately in tests",
            )

        # Unsafe grep splitting
        if cmd.startswith("grep ") or cmd.startswith("egrep "):
            # Check the raw string for unquoted multi-word patterns
            # Pattern: grep -c word1 word2 file → word1+word2 is an unquoted pattern
            # The command runner will see word2 as a filename argument
            words = cmd.split()
            if len(words) >= 4:
                # After grep + flags, check if there are 2+ consecutive non-flag
                # non-file words before the last argument (the file path)
                idx = 1
                while idx < len(words) and words[idx].startswith("-"):
                    idx += 1
                # words[idx] is the first non-flag word (pattern start)
                # If words[idx+1] looks like a pattern continuation (not a path, not quoted)
                if idx + 2 < len(words):
                    next_word = words[idx + 1]
                    last_word = words[-1]
                    # If next_word doesn't look like a file path and isn't quoted
                    if (not ("/" in next_word or next_word.endswith((".py",".yml",".yaml",".json",".md",".sh")))
                        and not (next_word.startswith("'") or next_word.startswith('"'))):
                        pattern_combined = " ".join(words[idx:idx+2])
                        _add_warning(
                            result, "W_GREP_UNQUOTED_SPACE",
                            field_path,
                            f"grep pattern '{pattern_combined}' has spaces without quotes "
                            f"— '{words[idx+1]}' will be treated as a filename argument",
                            title, f"use single quotes: '...{pattern_combined}...'",
                        )

        # Invalid Python one-liners
        if cmd.startswith("python3 -c ") or cmd.startswith("python -c "):
            code = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            # Try to extract code (may be quoted)
            if code.startswith("'") and "'" in code[1:]:
                code = code.split("'")[1]
            elif code.startswith('"') and '"' in code[1:]:
                code = code.split('"')[1]
            for pat in _INVALID_PY_PATTERNS:
                if pat.search(code):
                    _add_error(
                        result, "E_PYTHON_INVALID_ONELINER",
                        field_path, f"inline Python has invalid one-liner syntax: {pat.pattern[:40]}...",
                        title, "for/while/if/class/def cannot be one-liners; use comprehensions or wrap in exec()",
                    )
                    break

            # Check for missing quotes around -c argument
            non_quoted = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            if not (non_quoted.startswith("'") or non_quoted.startswith('"')):
                _add_warning(
                    result, "W_PYTHON_C_UNQUOTED",
                    field_path, "python3 -c argument is not quoted; only first word will be executed",
                    title, f"use single quotes: python3 -c '{non_quoted[:50]}...'",
                )

        # Bash-only syntax under sh
        if not shell_is_bash:
            for pattern, feature, fix in _BASH_ONLY_PATTERNS:
                matched = (
                    _contains_unquoted_shell_word(cmd, "source")
                    if feature == "source"
                    else pattern.search(cmd) is not None
                )
                if matched:
                    # Skip 'source' when it's for venv activation (caught by E_VENV_MISSING)
                    if feature == "source" and ("venv" in cmd.lower() or "activate" in cmd.lower()):
                        continue
                    _add_error(
                        result, "E_BASH_SYNTAX_UNDER_SH",
                        field_path, f"command uses bash-only feature '{feature}' but shell is {env.shell}",
                        title, fix,
                    )

        # Shell operators that need shell=True
        if _SHELL_OPS_IN_CMDS.search(cmd):
            pass  # shell=True is now default for non-python3, so this is fine

    def _validate_script_path(
        self,
        result: CompileResult,
        script: str,
        known_scripts: set[str],
        title: str,
        field_path: str,
        target_repo_root: Path | None,
        *,
        require_executable: bool = False,
        executable_scripts: set[str] | None = None,
    ) -> None:
        relative = _relative_command_path(script, target_repo_root)
        script_path = (
            target_repo_root / relative
            if target_repo_root is not None and relative is not None
            else None
        )
        is_known = relative in known_scripts if relative is not None else False
        exists = script_path.is_file() if script_path is not None else is_known
        executable = (
            relative in (executable_scripts or set())
            if require_executable
            else True
        )
        if is_known and exists and executable:
            return
        _add_error(
            result,
            "E_SCRIPT_PATH_UNKNOWN",
            field_path,
            f"script path '{script}' is missing, unknown, or not executable",
            title,
            "use a script listed in ExecutionEnvironment.verification_entrypoints",
        )

    def _validate_scope_acceptance(
        self,
        result: CompileResult,
        title: str,
        scope: list[str],
        t1: list[str],
        acceptance: list[str],
        coder_instructions: list[str],
        role: str,
        target_repo_root: Path | None,
    ) -> None:
        # A recursive GRACE lint target must itself be writable scope.  A packet
        # that owns selected files under ``app/bidder`` cannot repair failures
        # in every other Python file reached by linting the whole directory.
        # Reject that contract before materialization instead of exhausting the
        # coder recovery ladder on deterministic, out-of-scope baseline errors.
        if role == "coder":
            normalized_scope = {str(item).rstrip("/") for item in scope}
            for command_index, raw_command in enumerate(t1 if isinstance(t1, list) else []):
                command = str(raw_command) if isinstance(raw_command, str) else " ".join(raw_command)
                if "grace_lint.py" not in command:
                    continue
                try:
                    import shlex

                    tokens = shlex.split(command)
                except ValueError:
                    tokens = command.split()
                try:
                    lint_index = next(
                        index for index, token in enumerate(tokens)
                        if token.endswith("grace_lint.py")
                    )
                except StopIteration:
                    continue
                for target in tokens[lint_index + 1:]:
                    target_path = target.rstrip("/")
                    if (
                        not target_path
                        or target_path.startswith("-")
                        or target_path.endswith(".py")
                        or target_path in normalized_scope
                    ):
                        continue
                    covered_files = sorted(
                        item for item in normalized_scope
                        if item.startswith(f"{target_path}/")
                    )
                    lint_root = target_repo_root / target_path if target_repo_root else None
                    linted_python_files: set[str] = set()
                    if lint_root and lint_root.is_dir():
                        try:
                            linted_python_files = {
                                str(path.relative_to(target_repo_root))
                                for path in lint_root.rglob("*.py")
                                if path.is_file()
                            }
                        except OSError:
                            linted_python_files = set()
                    outside_scope = sorted(linted_python_files - normalized_scope)
                    if covered_files and (outside_scope or not linted_python_files):
                        _add_error(
                            result,
                            "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
                            f"verification.t1[{command_index}]",
                            f"GRACE lint target '{target_path}' is broader than packet "
                            f"write scope; out-of-scope Python files: {outside_scope}",
                            title,
                            "list the exact scoped Python files in the lint command, "
                            "or include the directory itself in packet scope",
                        )

        # Check if T1 runs tests on files outside scope
        test_files_in_t1: set[str] = set()
        for cmd in (t1 if isinstance(t1, list) else []):
            cmd_s = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
            import re as _re
            test_refs = _re.findall(r'tests?/[\w/_.-]+\.py', cmd_s)
            test_files_in_t1.update(test_refs)

        test_files_in_scope: set[str] = set()
        for s in scope:
            if "test" in s.lower():
                test_files_in_scope.add(s)

        tests_outside = test_files_in_t1 - test_files_in_scope

        # Check if the packet deletes/renames symbols
        deletes_symbol = False
        all_text = " ".join(coder_instructions + [str(acceptance)])
        if any(
            kw in all_text.lower()
            for kw in ("remove", "delete", "rename", "move ", "extract from")
        ):
            # Negative patterns: phrases like "do not delete", "no renames"
            # should NOT trigger the detection.
            neg = re.compile(
                r'\b(do not|don.t|no|without|never|avoid|prevent)\s+'
                r'(remove|delet|renam|mov|extract)\w*\b',
                re.IGNORECASE,
            )
            has_negative = neg.search(all_text)
            if not has_negative:
                deletes_symbol = True

        # Error only when: tests outside scope + delete/rename + no shim
        if tests_outside and deletes_symbol and role == "coder":
            has_shim = any(
                kw in all_text.lower()
                for kw in ("shim", "compatibility wrapper", "keep old", "deprecated stub",
                          "re-export", "backward compat")
            )
            if not has_shim:
                _add_error(
                    result, "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
                    f"verification.t1",
                    f"T1 runs tests {tests_outside} outside write scope {scope}, "
                    f"packet deletes/renames/moves symbols, and no compatibility "
                    f"shim is described",
                    title,
                    "keep compatibility shim/wrapper/re-export for old symbol, "
                    "or include test files in write scope",
                )

    def _validate_evidence(
        self,
        result: CompileResult,
        title: str,
        evidence: list[dict],
        role: str,
        description: str,
        scope: list[str],
        verification: dict | list,
    ) -> None:
        for ei, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind", "")
            patterns = ev.get("artifact_patterns", [])
            required = ev.get("required", True)

            if kind not in SUPPORTED_EVIDENCE_KINDS:
                _add_error(
                    result, "E_EVIDENCE_KIND_UNKNOWN",
                    f"expected_evidence[{ei}].kind",
                    f"unknown evidence kind '{kind}' — "
                    f"valid values: {sorted(SUPPORTED_EVIDENCE_KINDS)}",
                    title,
                    f"use one of: {', '.join(sorted(SUPPORTED_EVIDENCE_KINDS))}",
                )

            for pattern in patterns if isinstance(patterns, list) else [patterns]:
                if isinstance(pattern, str) and pattern.startswith("/"):
                    _add_error(
                        result, "E_EVIDENCE_ABSOLUTE_PATTERN",
                        f"expected_evidence[{ei}].artifact_patterns",
                        f"artifact pattern '{pattern}' is absolute; evidence artifacts "
                        "must be repository-relative",
                        title,
                        "use a repository-relative artifact path or leave artifact_patterns empty",
                        details={"pattern": pattern},
                    )
                if isinstance(pattern, str) and self._is_descriptive_artifact_pattern(pattern):
                    _add_error(
                        result, "E_EVIDENCE_DESCRIPTIVE_PATTERN",
                        f"expected_evidence[{ei}].artifact_patterns",
                        f"artifact pattern '{pattern}' is a description, not a relative artifact glob",
                        title,
                        "use a run-relative artifact path such as t1/cmd_002_stdout.log",
                        details={
                            "pattern": pattern,
                            "evidence_id": ev.get("id", ""),
                            "producer": ev.get("producer", ""),
                            "verification": verification,
                        },
                    )
                if (
                    isinstance(pattern, str)
                    and re.fullmatch(
                        r"\.grace-t\d[^/]*\.(?:stdout|stderr|log)",
                        pattern.strip(),
                        flags=re.IGNORECASE,
                    )
                ):
                    _add_error(
                        result, "E_EVIDENCE_EPHEMERAL_ROOT_ARTIFACT",
                        f"expected_evidence[{ei}].artifact_patterns",
                        f"artifact pattern '{pattern}' would persist controller command "
                        "output in the target repository",
                        title,
                        "use the controller's run-relative artifact path, for example "
                        "t1/cmd_001_stdout.log",
                        details={"pattern": pattern},
                    )

            # Validate expectation enum
            expectation = ev.get("expectation", "") or "exists"
            if expectation not in self._VALID_EXPECTATIONS:
                _add_error(
                    result, "E_EVIDENCE_EXPECTATION_UNKNOWN",
                    f"expected_evidence[{ei}].expectation",
                    f"unknown expectation '{expectation}' — "
                    f"valid values: {sorted(self._VALID_EXPECTATIONS)}",
                    title,
                    f"use one of: {', '.join(sorted(self._VALID_EXPECTATIONS))}",
                )

            # kind=diff with pattern=agent.patch → wrong
            if kind == "diff" and required:
                if patterns:
                    _add_error(
                        result, "E_EVIDENCE_DIFF_HAS_PATTERN",
                        f"expected_evidence[{ei}].artifact_patterns",
                        "kind=diff is produced by the controller's captured patch and must not "
                        "depend on a worktree file or command-stdout pattern",
                        title, "leave artifact_patterns empty for kind=diff",
                    )
                if "agent.patch" in str(patterns):
                    _add_warning(
                        result, "W_EVIDENCE_DIFF_AGENT_PATCH",
                        f"expected_evidence[{ei}]",
                        "expected_evidence uses kind=diff with pattern=agent.patch — "
                        "agent.patch never matches changed_files from git diff",
                        title, "use kind=diff without pattern, or kind=file with specific filenames",
                    )

            # Verification-only packet requiring diff
            if kind == "diff" and required and role == "coder":
                no_code = "no code changes" in description.lower() or "no files need modification" in description.lower()
                if no_code:
                    _add_error(
                        result, "E_EVIDENCE_DIFF_VERIFICATION_ONLY",
                        f"expected_evidence[{ei}]",
                        "packet is verification-only but requires diff evidence",
                        title, "remove diff evidence requirement or change role to verifier",
                    )

            # No scope files but requires diff
            if kind == "diff" and required and not scope:
                _add_error(
                    result, "E_EVIDENCE_DIFF_EMPTY_SCOPE",
                    f"expected_evidence[{ei}]",
                    "packet requires diff evidence but has empty write scope",
                    title, "add target files to scope or remove diff evidence",
                )

    @staticmethod
    def _is_descriptive_artifact_pattern(pattern: str) -> bool:
        """Return whether an artifact pattern is prose instead of a path glob."""
        value = pattern.strip().lower()
        command_prefixes = (
            "git ", "npm ", "node ", "python ", "python3 ", "pytest ",
            "grep ", "egrep ", "rg ", "test ", "make ", "just ", "sh ",
            "bash ", "curl ", "get ", "post ", "patch ", "delete ",
        )
        looks_like_single_path = (
            "/" in value
            and bool(re.search(r"\.[a-z0-9*?]+$", value))
            and not any(token in value for token in (" --", " &&", " ||", "|", ">", ";"))
        )
        return (
            " stdout" in value
            or value.endswith(" output")
            or value.startswith("run: ")
            or value.startswith(command_prefixes)
            or value.startswith("coder note ")
            or " requirement-by-requirement " in value
            or " version and " in value
            or " description or " in value
            or " screenshot reference " in value
            or (len(value.split()) >= 4 and not looks_like_single_path)
        )

    # ── Remove/delete keywords for contradiction detection ─────────────
    _REMOVE_INTENT_KEYWORDS = [
        "remove", "delete", "consolidate", "drop", "eliminate",
        "get rid of", "clean up", "delete the file",
        # Russian
        "удалить", "убрать", "избавиться", "удали",
        "удаление", "удаляем",
    ]

    def _has_remove_intent(self, texts: list[str]) -> list[str]:
        """Check if any text expresses intent to remove files.
        Returns list of matched keywords for context."""
        matched: list[str] = []
        for text in texts:
            t = text.lower()
            for kw in self._REMOVE_INTENT_KEYWORDS:
                if kw in t:
                    matched.append(kw)
                    break  # one match per text is enough
        return matched

    def _extract_target_paths_for_removal(
        self, texts: list[str], evidence_paths: list[str],
    ) -> list[str]:
        """Extract file paths from instructions that match evidence paths
        and are explicitly being removed. Looks for patterns like:
        'delete models.py', 'remove src/foo.py', 'consolidate bar.py into'

        A remove verb elsewhere in the same sentence is insufficient.  For
        example, "update development-plan.xml and remove stale log links"
        removes links, not the XML file.  The target path must immediately
        follow the removal phrase (apart from a few harmless qualifiers).
        """
        targets: list[str] = []
        for text in texts:
            t = text.lower()
            for ep in evidence_paths:
                ep_lower = ep.lower()
                ep_name = Path(ep).name.lower()
                for kw in self._REMOVE_INTENT_KEYWORDS:
                    keyword = re.escape(kw)
                    qualifiers = r"(?:(?:the|this|old|obsolete|target)\s+){0,3}"
                    file_word = r"(?:file\s+)?"
                    target = rf"(?:{re.escape(ep_lower)}|{re.escape(ep_name)})"
                    explicit_removal = re.search(
                        rf"(?:^|[\s:;,(]){keyword}\s+{qualifiers}{file_word}"
                        rf"[`'\"]?{target}(?=$|[\s`'\".,;:)])",
                        t,
                    )
                    if explicit_removal:
                        targets.append(ep)
                        break
        return list(set(targets))

    def _validate_evidence_contradiction(
        self,
        result: CompileResult,
        title: str,
        evidence: list[dict],
        coder_instructions: list[str],
        description: str,
        validation_hint: str,
    ) -> None:
        """Detect when expected_evidence expects a file to exist ('exists')
        but instructions tell the coder to delete/remove that same file."""
        if not evidence:
            return

        # Collect evidence paths + their expectations
        ev_paths: list[str] = []
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            patterns = ev.get("artifact_patterns", ev.get("pattern", []))
            if isinstance(patterns, str):
                patterns = [patterns]
            ev_paths.extend(p for p in patterns if p.endswith(".py") or "." in p)

        if not ev_paths:
            return

        # Check all text sources for remove intent
        all_texts = coder_instructions + [description, validation_hint]
        remove_kws = self._has_remove_intent(all_texts)
        removal_targets = self._extract_target_paths_for_removal(
            all_texts, ev_paths
        ) if remove_kws else []

        # expectation=deleted is an operation claim, not merely an end state.
        # Require the packet text to name the exact file as a deletion target.
        for ev in evidence:
            if not isinstance(ev, dict) or ev.get("expectation") != "deleted":
                continue
            patterns = ev.get("artifact_patterns", ev.get("pattern", []))
            if isinstance(patterns, str):
                patterns = [patterns]
            for pattern in patterns:
                if pattern in removal_targets:
                    continue
                _add_error(
                    result,
                    "E_EVIDENCE_DELETION_NOT_EXPLICIT",
                    "expected_evidence",
                    f"Evidence '{ev.get('id', '?')}' expects '{pattern}' to be deleted, "
                    "but the packet does not explicitly define that file deletion operation.",
                    title,
                    f"explicitly instruct the coder to delete {pattern}, or use expectation='absent'",
                    details={
                        "evidence_id": ev.get("id", "?"),
                        "file": pattern,
                        "remove_target_explicit": False,
                    },
                )

        if not remove_kws:
            return

        # Find which evidence paths are targeted for removal
        if not removal_targets:
            return

        # For each removal target, check if evidence says 'exists' (default)
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            patterns = ev.get("artifact_patterns", ev.get("pattern", []))
            if isinstance(patterns, str):
                patterns = [patterns]
            expectation = ev.get("expectation", "") or "exists"
            ev_id = ev.get("id", "?")
            for p in patterns:
                if p in removal_targets and expectation == "exists":
                    _add_error(
                        result, "E_EVIDENCE_CONTRADICTS_INSTRUCTIONS",
                        f"expected_evidence",
                        f"Evidence '{ev_id}' expects '{p}' to exist (expectation='exists'), "
                        f"but instructions say to remove/delete it (keywords: {remove_kws}). "
                        f"Change expectation to 'deleted' or 'absent', or remove this evidence entry.",
                        title,
                        f"Set expectation: 'deleted' for file being removed, or "
                        f"'absent' if the file does not need to be removed by this packet.",
                        details={
                            "evidence_id": ev_id,
                            "file": p,
                            "current_expectation": expectation,
                            "remove_keywords": remove_kws,
                            "remove_target_explicit": True,
                            "suggested_fix": "deleted",
                        },
                    )
                elif p in removal_targets and expectation in ("deleted", "absent"):
                    pass  # explicit deletion expectation — no contradiction

    def _validate_role_scope(
        self,
        result: CompileResult,
        title: str,
        role: str,
        scope: list[str],
        description: str,
    ) -> None:
        # W02: Empty coder scope is now checked in compile_plan() main loop
        # with more detail (wave/packet index). Keep the old check as a
        # safety net for direct _validate_role_scope() callers.
        if role == "coder" and not scope:
            _add_error(
                result, "E_CODER_EMPTY_SCOPE",
                "scope", "coder packet has empty write scope — nothing to write",
                title, "add target files to scope or change role to verifier",
            )

        # Coder packets described as verification-only
        if role == "coder" and (
            "no code changes" in description.lower()
            or "no files need modification" in description.lower()
            or "verification-only" in description.lower()
        ):
            _add_error(
                result, "E_VERIFICATION_ONLY_CODER",
                "role", "coder packet described as verification-only",
                title, "change role to 'verifier' or add files to modify",
            )

        # W02: Frozen scope vs scope overlap is now checked in compile_plan()
        # main loop as E_SCOPE_FROZEN_OVERLAP (not silently stripped).


# ── Public convenience function ────────────────────────────────────────

def compile_plan(
    plan: dict,
    env: ExecutionEnvironment | None = None,
    *,
    feature_description: str = "",
    target_repo_root: Path | None = None,
) -> CompileResult:
    return PlanCompiler().compile_plan(
        plan, env,
        feature_description=feature_description,
        target_repo_root=target_repo_root,
    )
