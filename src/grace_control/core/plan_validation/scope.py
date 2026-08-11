# ############################################################################
# AI_HEADER: plan_validation_scope — packet scope and acceptance validation
# ROLE: Own fail-closed write-scope, frozen-scope, file-limit, acceptance, and
#       role consistency checks for PlanCompiler packets.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate packet filesystem scope and whether verification fits that scope.
# inputs: Packet scope, plan constraints, verification commands, role, and target root.
# returns: Normalized scope list and diagnostics appended to CompileResult.
# side_effects: Reads target-repository Python files for bounded scope checks.
# emitted_logs: None.
# error_behavior: Invalid or infeasible scope is reported as compiler diagnostics.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: validate_packet_scope
#   - function: validate_scope_acceptance
#   - function: validate_role_scope
# END_MODULE_MAP

from __future__ import annotations

import re
import shlex
from pathlib import Path

from grace_control.core.plan_validation.models import CompileResult, _add_error
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.scope")


# START_BLOCK_CONSTANTS
_FILE_EXTENSIONS = (
    ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".md",
    ".cfg", ".ini", ".sh", ".bash", ".sql", ".html", ".css",
    ".js", ".ts", ".tsx", ".jsx", ".rs", ".go",
)
# END_BLOCK_CONSTANTS


# START_BLOCK_SCOPE
# START_FUNCTION_CONTRACT
# name: validate_packet_scope
# purpose: Validate and normalize one packet's writable scope and frozen overlaps.
# inputs: result — CompileResult; plan and packet — plan objects; scope, role, title, indexes, file limit, and target root — packet context.
# returns: Scope list safe for subsequent compiler validators.
# side_effects: Reads target-repository directories when a Python-file limit is declared.
# emitted_logs: None.
# error_behavior: Invalid scope entries append fail-closed diagnostics.
# END_FUNCTION_CONTRACT
def validate_packet_scope(
    result: CompileResult,
    plan: dict,
    packet: dict,
    scope: object,
    role: str,
    title: str,
    wave_index: int,
    packet_index: int,
    python_file_limit: int | None,
    target_repo_root: Path | None,
) -> list[str]:
    if scope is not None and not isinstance(scope, list):
        _add_error(
            result, "E_SCOPE_NOT_LIST",
            f"waves[{wave_index}].packets[{packet_index}].scope",
            f"scope must be a list of strings, got {type(scope).__name__} — "
            "string scope iterates as characters instead of file paths",
            title,
            "use a list of strings: ['path/to/file.py', 'path/to/dir/']",
        )
        scope = []
    if scope is None:
        scope = []

    if role == "coder" and not scope:
        _add_error(
            result, "E_CODER_EMPTY_SCOPE",
            f"waves[{wave_index}].packets[{packet_index}].scope",
            f"coder packet '{title}' has no write scope — "
            "every coder packet must specify explicit repo-relative scope",
            title,
            "add target files/directories to scope (e.g. ['src/grace_control/services/'])",
        )

    for scope_index, scope_path in enumerate(scope):
        if not isinstance(scope_path, str):
            _add_error(
                result, "E_SCOPE_PATH_NOT_STRING",
                f"waves[{wave_index}].packets[{packet_index}].scope[{scope_index}]",
                f"scope entry must be a string, got {type(scope_path).__name__}",
                title,
            )
            continue

        if scope_path.startswith("/"):
            _add_error(
                result, "E_SCOPE_ABSOLUTE_PATH",
                f"waves[{wave_index}].packets[{packet_index}].scope[{scope_index}]",
                f"scope path '{scope_path}' is absolute — scope must be repo-relative",
                title,
                f"remove leading '/': '{scope_path.lstrip('/')}'",
            )

        if ".." in Path(scope_path).parts:
            _add_error(
                result, "E_SCOPE_PARENT_PATH",
                f"waves[{wave_index}].packets[{packet_index}].scope[{scope_index}]",
                f"scope path '{scope_path}' contains '..' — scope must be within repo",
                title,
                "use repo-relative path without parent references",
            )

        if (
            "." in scope_path
            and "/" not in scope_path
            and not scope_path.startswith(".")
            and not scope_path.endswith(_FILE_EXTENSIONS)
        ):
            _add_error(
                result, "E_SCOPE_PYTHON_IMPORT_PATH",
                f"waves[{wave_index}].packets[{packet_index}].scope[{scope_index}]",
                f"scope path '{scope_path}' looks like a Python import path — "
                "scope must be filesystem paths (e.g. 'src/grace_control/services/')",
                title,
                "convert to filesystem path: replace dots with '/' and add '.py' or '/'",
            )

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
                f"waves[{wave_index}].packets[{packet_index}].scope",
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

    frozen = packet.get("frozen_scope", []) or []
    if scope and frozen:
        overlap = set(scope) & set(frozen)
        if overlap:
            _add_error(
                result, "E_SCOPE_FROZEN_OVERLAP",
                f"waves[{wave_index}].packets[{packet_index}].scope",
                f"scope and frozen_scope overlap: {sorted(overlap)} — "
                "a file cannot be both writable and frozen",
                title,
                "remove overlapping paths from either scope or frozen_scope",
            )

    root_constraints = plan.get("constraints", {})
    root_frozen = root_constraints.get("frozen_scope", []) or []
    if scope and root_frozen:
        root_overlap = set(scope) & set(root_frozen)
        if root_overlap:
            _add_error(
                result, "E_ROOT_FROZEN_SCOPE_OVERLAP",
                f"waves[{wave_index}].packets[{packet_index}].scope",
                f"scope overlaps with root constraints.frozen_scope: "
                f"{sorted(root_overlap)} — root frozen paths are applied "
                "during materialization and cannot be writable",
                title,
                "remove overlapping paths from packet scope or root constraints.frozen_scope",
            )
    return scope


# START_FUNCTION_CONTRACT
# name: validate_scope_acceptance
# purpose: Reject verification commands and symbol moves that cannot be satisfied within packet scope.
# inputs: result, packet title, scope, T1 commands, acceptance, coder instructions, role, target root.
# returns: None; diagnostics are appended to result.
# side_effects: Reads target-repository Python files for recursive lint feasibility.
# emitted_logs: None.
# error_behavior: Out-of-scope acceptance appends E_SCOPE_ACCEPTANCE_IMPOSSIBLE.
# END_FUNCTION_CONTRACT
def validate_scope_acceptance(
    result: CompileResult,
    title: str,
    scope: list[str],
    t1: list[str],
    acceptance: list[str],
    coder_instructions: list[str],
    role: str,
    target_repo_root: Path | None,
) -> None:
    if role == "coder":
        normalized_scope = {str(item).rstrip("/") for item in scope}
        for command_index, raw_command in enumerate(t1 if isinstance(t1, list) else []):
            command = str(raw_command) if isinstance(raw_command, str) else " ".join(raw_command)
            if "grace_lint.py" not in command:
                continue
            try:
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

    test_files_in_t1: set[str] = set()
    for command in (t1 if isinstance(t1, list) else []):
        command_text = str(command) if isinstance(command, str) else " ".join(command)
        test_files_in_t1.update(re.findall(r"tests?/[\w/_.-]+\.py", command_text))

    test_files_in_scope: set[str] = set()
    for scope_path in scope:
        if "test" in scope_path.lower():
            test_files_in_scope.add(scope_path)

    tests_outside = test_files_in_t1 - test_files_in_scope
    all_text = " ".join(coder_instructions + [str(acceptance)])
    deletes_symbol = False
    if any(
        keyword in all_text.lower()
        for keyword in ("remove", "delete", "rename", "move ", "extract from")
    ):
        negative = re.compile(
            r"\b(do not|don.t|no|without|never|avoid|prevent)\s+"
            r"(remove|delet|renam|mov|extract)\w*\b",
            re.IGNORECASE,
        )
        deletes_symbol = negative.search(all_text) is None

    if tests_outside and deletes_symbol and role == "coder":
        has_shim = any(
            keyword in all_text.lower()
            for keyword in (
                "shim", "compatibility wrapper", "keep old", "deprecated stub",
                "re-export", "backward compat",
            )
        )
        if not has_shim:
            _add_error(
                result, "E_SCOPE_ACCEPTANCE_IMPOSSIBLE", "verification.t1",
                f"T1 runs tests {tests_outside} outside write scope {scope}, "
                "packet deletes/renames/moves symbols, and no compatibility "
                "shim is described",
                title,
                "keep compatibility shim/wrapper/re-export for old symbol, "
                "or include test files in write scope",
            )


# START_FUNCTION_CONTRACT
# name: validate_role_scope
# purpose: Enforce coder role semantics after scope and acceptance checks.
# inputs: result, packet title, role, scope, and description.
# returns: None; diagnostics are appended to result.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Verification-only coder packets are rejected.
# END_FUNCTION_CONTRACT
def validate_role_scope(
    result: CompileResult,
    title: str,
    role: str,
    scope: list[str],
    description: str,
) -> None:
    if role == "coder" and not scope:
        _add_error(
            result, "E_CODER_EMPTY_SCOPE", "scope",
            "coder packet has empty write scope — nothing to write",
            title, "add target files to scope or change role to verifier",
        )

    if role == "coder" and (
        "no code changes" in description.lower()
        or "no files need modification" in description.lower()
        or "verification-only" in description.lower()
    ):
        _add_error(
            result, "E_VERIFICATION_ONLY_CODER", "role",
            "coder packet described as verification-only",
            title, "change role to 'verifier' or add files to modify",
        )
# END_BLOCK_SCOPE
