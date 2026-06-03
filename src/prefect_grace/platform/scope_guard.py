# ############################################################################
# AI_HEADER: scope_guard
# ROLE: Validate changed files against packet scope without LLM calls.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Deterministic scope validation for packet changed files.
# inputs: Changed file paths, allowed scope patterns, frozen scope patterns, repo root.
# returns: ScopeGuardResult with violations and validation status.
# side_effects: None - pure validation, no state mutation.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Fail closed on invalid paths or pattern errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ScopeGuardViolation
#   - dataclass: ScopeGuardResult
#   - function: validate_scope
#   - function: _normalize_path
#   - function: _matches_pattern
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from prefect_grace.platform.structured_logger import log_event


@dataclass(frozen=True)
class ScopeGuardViolation:
    """Represents a single scope violation."""
    file_path: str
    reason: str
    matched_pattern: str | None = None


@dataclass(frozen=True)
class ScopeGuardResult:
    """Result of scope validation."""
    ok: bool
    changed_files: list[str]
    allowed_files: list[str]
    outside_allowed: list[ScopeGuardViolation]
    frozen_violations: list[ScopeGuardViolation]
    invalid_paths: list[ScopeGuardViolation]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert ScopeGuardResult to JSON-safe dictionary.
    # inputs: None (instance method).
    # returns: dict[str, Any] - JSON-safe dictionary representation.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dictionary."""
        return {
            "ok": self.ok,
            "changed_files": self.changed_files,
            "allowed_files": self.allowed_files,
            "outside_allowed": [
                {
                    "file_path": v.file_path,
                    "reason": v.reason,
                    "matched_pattern": v.matched_pattern,
                }
                for v in self.outside_allowed
            ],
            "frozen_violations": [
                {
                    "file_path": v.file_path,
                    "reason": v.reason,
                    "matched_pattern": v.matched_pattern,
                }
                for v in self.frozen_violations
            ],
            "invalid_paths": [
                {
                    "file_path": v.file_path,
                    "reason": v.reason,
                    "matched_pattern": v.matched_pattern,
                }
                for v in self.invalid_paths
            ],
        }


# START_FUNCTION_CONTRACT
# name: _normalize_path
# purpose: Normalize file path to repo-relative POSIX format.
# inputs:
#   file_path: str - Path to normalize (repo-relative, absolute, or ./relative).
#   repo_root: Path - Repository root directory.
# returns: str - Normalized repo-relative POSIX path, or None if invalid.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None for invalid paths (traversal, outside repo, empty, NUL).
# END_FUNCTION_CONTRACT
def _normalize_path(file_path: str, repo_root: Path) -> str | None:
    """
    Normalize file path to repo-relative POSIX format.

    Returns None for invalid paths:
    - Path traversal escaping repo root
    - Absolute paths outside repo root
    - Empty paths
    - Paths containing NUL bytes
    """
    if not file_path or "\0" in file_path:
        return None

    try:
        # Convert to Path and resolve
        path = Path(file_path)

        # Handle absolute paths
        if path.is_absolute():
            resolved = path.resolve()
        else:
            # Relative path - resolve against repo_root
            resolved = (repo_root / path).resolve()

        # Check if path is under repo_root
        repo_resolved = repo_root.resolve()
        try:
            relative = resolved.relative_to(repo_resolved)
        except ValueError:
            # Path is outside repo root
            return None

        # Convert to POSIX-style string
        return relative.as_posix()

    except (OSError, ValueError, RuntimeError):
        # Any path resolution error - fail closed
        return None


# START_FUNCTION_CONTRACT
# name: _matches_pattern
# purpose: Check if normalized path matches a scope pattern.
# inputs:
#   normalized_path: str - Normalized repo-relative POSIX path.
#   pattern: str - Scope pattern (exact path, directory glob, file glob, nested glob).
# returns: bool - True if path matches pattern.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns False on pattern matching errors.
# END_FUNCTION_CONTRACT
def _matches_pattern(normalized_path: str, pattern: str) -> bool:
    """
    Check if normalized path matches a scope pattern.

    Supported patterns:
    - Exact file path: "prefect_grace/cli.py"
    - Directory glob: "path/**"
    - File glob: "path/*.py"
    - Nested glob: "path/**/*.py"
    """
    try:
        import re

        # Exact match (no wildcards)
        if "*" not in pattern:
            # Directory prefix: "path/dir/" matches any file under it
            if pattern.endswith("/"):
                return normalized_path.startswith(pattern)
            return normalized_path == pattern

        # Handle directory glob: "path/**" matches anything under path/
        if pattern.endswith("/**"):
            prefix = pattern[:-3]  # Remove /**
            return normalized_path.startswith(prefix + "/") or normalized_path == prefix

        # Convert glob pattern to regex
        # Handle **/ specially - it matches zero or more path segments followed by /
        regex_pattern = pattern

        # Replace **/ with a placeholder (note: includes the slash)
        regex_pattern = regex_pattern.replace("**/", "\x00DOUBLESTARSLASH\x00")

        # Escape regex special characters
        regex_pattern = re.escape(regex_pattern)

        # Replace placeholder with regex that matches zero or more path segments
        # This should match: nothing, "dir/", "dir/subdir/", etc.
        regex_pattern = regex_pattern.replace("\x00DOUBLESTARSLASH\x00", "(?:.+/)?")

        # Replace single * with regex that matches anything except /
        regex_pattern = regex_pattern.replace(r"\*", "[^/]*")

        # Anchor the pattern
        regex_pattern = f"^{regex_pattern}$"

        # Special case: if pattern has (?:.+/)? in it, we need to also match when ** is zero segments
        # For example, "path/**/*.py" should match both "path/file.py" and "path/sub/file.py"
        if "(?:.+/)?" in regex_pattern:
            # Create alternate pattern where **/ matches zero segments (i.e., just remove it)
            alt_pattern = regex_pattern.replace("(?:.+/)?", "")
            return bool(re.match(regex_pattern, normalized_path)) or bool(re.match(alt_pattern, normalized_path))

        return bool(re.match(regex_pattern, normalized_path))

    except (ValueError, TypeError, re.error):
        # Pattern matching error - fail closed
        return False


# START_FUNCTION_CONTRACT
# name: validate_scope
# purpose: Validate changed files against allowed and frozen scope.
# inputs:
#   changed_files: list[str] - List of changed file paths.
#   allowed_scope: list[str] - List of allowed scope patterns.
#   frozen_scope: list[str] - List of frozen scope patterns.
#   repo_root: Path - Repository root directory.
#   trace_context: Optional structured logging trace context.
# returns: ScopeGuardResult - Validation result with violations.
# side_effects: None - pure validation function.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Fail closed - invalid paths block validation.
# END_FUNCTION_CONTRACT
def validate_scope(
    changed_files: list[str],
    allowed_scope: list[str],
    frozen_scope: list[str],
    *,
    repo_root: Path,
    trace_context: Any | None = None,
) -> ScopeGuardResult:
    """
    Validate changed files against allowed and frozen scope.

    Rules:
    - Frozen scope wins over allowed scope
    - Empty allowed scope blocks all files
    - Invalid paths are blocked
    - Deterministic output ordering (sorted)

    Args:
        changed_files: List of changed file paths.
        allowed_scope: List of allowed scope patterns.
        frozen_scope: List of frozen scope patterns.
        repo_root: Repository root directory.

    Returns:
        ScopeGuardResult with validation status and violations.
    """
    def _log(event: str, result: str = "ok", **extra: Any) -> None:
        log_event(
            trace_context,
            module="M-GRACE-SCOPE-GUARD",
            fn="validate_scope",
            block="SCOPE_VALIDATION",
            event=event,
            result=result,
            **extra,
        )

    _log(
        "scope_check_started",
        "ok",
        changed_file_count=len(changed_files),
        allowed_scope_count=len(allowed_scope),
        frozen_scope_count=len(frozen_scope),
    )

    invalid_paths: list[ScopeGuardViolation] = []
    frozen_violations: list[ScopeGuardViolation] = []
    outside_allowed: list[ScopeGuardViolation] = []
    allowed_files: list[str] = []
    normalized_changed: list[str] = []

    # Normalize scope patterns (they might be absolute paths)
    normalized_allowed_scope: list[str] = []
    for pattern in allowed_scope:
        normalized_pattern = _normalize_path(pattern, repo_root)
        if normalized_pattern is not None:
            normalized_allowed_scope.append(normalized_pattern)
        else:
            # Pattern itself is a valid pattern string, keep as-is
            normalized_allowed_scope.append(pattern)

    normalized_frozen_scope: list[str] = []
    for pattern in frozen_scope:
        normalized_pattern = _normalize_path(pattern, repo_root)
        if normalized_pattern is not None:
            normalized_frozen_scope.append(normalized_pattern)
        else:
            # Pattern itself is a valid pattern string, keep as-is
            normalized_frozen_scope.append(pattern)

    # Normalize changed files
    for file_path in changed_files:
        normalized = _normalize_path(file_path, repo_root)
        if normalized is None:
            invalid_paths.append(ScopeGuardViolation(
                file_path=file_path,
                reason="Invalid path (traversal, outside repo, empty, or contains NUL)",
                matched_pattern=None,
            ))
        else:
            normalized_changed.append(normalized)

    # If there are invalid paths, fail immediately
    if invalid_paths:
        _log("scope_violation_detected", "fail", invalid_path_count=len(invalid_paths))
        return ScopeGuardResult(
            ok=False,
            changed_files=sorted(changed_files),
            allowed_files=[],
            outside_allowed=[],
            frozen_violations=[],
            invalid_paths=sorted(invalid_paths, key=lambda v: v.file_path),
        )

    # Check each normalized file
    for normalized_file in normalized_changed:
        # Check frozen scope first (frozen wins)
        frozen_match = None
        for pattern in normalized_frozen_scope:
            if _matches_pattern(normalized_file, pattern):
                frozen_match = pattern
                break

        if frozen_match:
            frozen_violations.append(ScopeGuardViolation(
                file_path=normalized_file,
                reason="File is in frozen scope",
                matched_pattern=frozen_match,
            ))
            continue

        # Check allowed scope
        allowed_match = None
        for pattern in normalized_allowed_scope:
            if _matches_pattern(normalized_file, pattern):
                allowed_match = pattern
                break

        if allowed_match:
            allowed_files.append(normalized_file)
        else:
            # Not in allowed scope
            outside_allowed.append(ScopeGuardViolation(
                file_path=normalized_file,
                reason="File is outside allowed write scope",
                matched_pattern=None,
            ))

    # Empty allowed scope blocks all files
    if not normalized_allowed_scope and normalized_changed:
        outside_allowed = [
            ScopeGuardViolation(
                file_path=f,
                reason="Allowed write scope is empty",
                matched_pattern=None,
            )
            for f in normalized_changed
        ]
        allowed_files = []

    # Determine overall status
    ok = (
        len(invalid_paths) == 0
        and len(frozen_violations) == 0
        and len(outside_allowed) == 0
    )
    if ok:
        _log("scope_check_passed", "ok", changed_file_count=len(normalized_changed))
    else:
        _log(
            "scope_violation_detected",
            "fail",
            frozen_violation_count=len(frozen_violations),
            outside_allowed_count=len(outside_allowed),
        )

    return ScopeGuardResult(
        ok=ok,
        changed_files=sorted(normalized_changed),
        allowed_files=sorted(allowed_files),
        outside_allowed=sorted(outside_allowed, key=lambda v: v.file_path),
        frozen_violations=sorted(frozen_violations, key=lambda v: v.file_path),
        invalid_paths=sorted(invalid_paths, key=lambda v: v.file_path),
    )
