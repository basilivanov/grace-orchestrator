# ############################################################################
# AI_HEADER: scope_guard
# ROLE: Validate changed files against allowed/frozen scope via git diff + glob matching.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Get changed files from git, validate against allowed_write_scope and frozen_scope.
# inputs: repo_root (Path), base_ref/head_ref (str|None).
# returns: list[ScopeViolation].
# side_effects: Runs git diff subprocess.
# emitted_logs: None.
# error_behavior: Returns violations list; never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ScopeGuard
# END_MODULE_MAP

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Literal

from grace_control.core.contracts import ScopeViolation


class ScopeGuard:

    def __init__(self, repo_root: Path) -> None:
        self._root = repo_root.resolve()

    def get_changed_files(
        self,
        base_ref: str | None = None,
        head_ref: str | None = None,
    ) -> list[str]:
        try:
            if base_ref and head_ref:
                cmd = ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"]
            else:
                cmd = ["git", "diff", "--name-only", "HEAD"]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self._root), timeout=15)
            changed = [p.strip() for p in r.stdout.split("\n") if p.strip()]
            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, cwd=str(self._root), timeout=10,
            )
            changed += [p.strip() for p in untracked.stdout.split("\n") if p.strip()]
            return sorted(set(changed))
        except Exception:
            return []

    def validate_changed_files(
        self,
        *,
        changed_files: list[str],
        allowed_write_scope: list[str],
        frozen_scope: list[str],
    ) -> list[ScopeViolation]:
        violations: list[ScopeViolation] = []
        if not allowed_write_scope:
            for path in changed_files:
                violations.append(ScopeViolation(
                    path=path, reason="missing allowed_write_scope",
                    violation_type="missing_allowed_scope",
                ))
            return violations

        for path in changed_files:
            if _is_abs_or_parent(path):
                violations.append(ScopeViolation(
                    path=path, reason="absolute or parent path not allowed",
                    violation_type="invalid_path",
                ))
                continue

            frozen = _matches_any(path, frozen_scope)
            if frozen:
                violations.append(ScopeViolation(
                    path=path, reason=f"path matches frozen scope",
                    violation_type="frozen_scope",
                ))
                continue

            allowed = _matches_any(path, allowed_write_scope)
            if not allowed:
                violations.append(ScopeViolation(
                    path=path, reason=f"path not in allowed write scope",
                    violation_type="out_of_scope",
                ))

        return violations


def _is_abs_or_parent(path: str) -> bool:
    return path.startswith("/") or ".." in Path(path).parts


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if _match(path, pattern):
            return True
    return False


def _match(path: str, pattern: str) -> bool:
    # exact match
    if path == pattern:
        return True
    # prefix match (e.g., src/grace_control/core/ matches src/grace_control/core/contracts.py)
    if pattern.endswith("/") and path.startswith(pattern):
        return True
    # ** glob
    if "**" in pattern:
        return fnmatch.fnmatch(path, pattern)
    # simple glob
    if "*" in pattern:
        return fnmatch.fnmatch(path, pattern)
    return False
