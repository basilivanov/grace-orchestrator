from __future__ import annotations

import fnmatch
from pathlib import Path

from pydantic import BaseModel

from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode


class RuntimeScopeEnforcementResult(BaseModel):
    ok: bool
    changed_files: list[str]
    allowed_files: list[str]
    out_of_scope_files: list[str]
    frozen_touched_files: list[str]
    failure_code: str | None = None
    summary: str


class RuntimeScopeEnforcer:

    _EXCLUDE_PREFIXES: tuple[str, ...] = (
        ".git/", ".grace/", ".venv/", "venv/", "node_modules/",
        "__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
        ".next/", "dist/", "build/", ".tox/",
    )

    @staticmethod
    def enforce(
        changed_files: list[str],
        allowed_scope: list[str],
        frozen_scope: list[str],
        fail_on_no_changes: bool = False,
    ) -> RuntimeScopeEnforcementResult:
        # Validate scope config BEFORE checking changed files
        invalid_scope = _invalid_scope_paths(allowed_scope) + _invalid_scope_paths(frozen_scope)
        if invalid_scope:
            return RuntimeScopeEnforcementResult(
                ok=False, changed_files=[], allowed_files=[],
                out_of_scope_files=[], frozen_touched_files=[],
                failure_code=AgentRuntimeFailureCode.AGENT_SCOPE_ENFORCEMENT_FAILED,
                summary=f"Invalid scope paths (absolute/.. not allowed): {invalid_scope}",
            )

        # Filter out dev/build/cache directories before scope check
        changed = [f for f in _dedupe_ordered(changed_files)
                   if not any(f.startswith(p) or f"/{p}" in f for p in RuntimeScopeEnforcer._EXCLUDE_PREFIXES)]

        # Reject absolute and dotdot paths in changed_files (hardened)
        invalid = []
        for f in changed:
            nf = f.replace("\\", "/")
            if nf.startswith("/") or nf.startswith("..") or nf == ".." or "/../" in nf:
                invalid.append(f)
            elif len(nf) >= 2 and nf[1] == ":" and nf[0].isalpha():
                invalid.append(f)
        if invalid:
            return RuntimeScopeEnforcementResult(
                ok=False, changed_files=list(changed), allowed_files=[],
                out_of_scope_files=invalid, frozen_touched_files=[],
                failure_code=AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE,
                summary=f"Invalid paths in changed files: {invalid}",
            )

        if not changed:
            if fail_on_no_changes:
                return RuntimeScopeEnforcementResult(
                    ok=False, changed_files=[], allowed_files=[],
                    out_of_scope_files=[], frozen_touched_files=[],
                    failure_code=AgentRuntimeFailureCode.AGENT_NO_CHANGES_PRODUCED,
                    summary="Agent produced no changes",
                )
            return RuntimeScopeEnforcementResult(
                ok=True, changed_files=[], allowed_files=[],
                out_of_scope_files=[], frozen_touched_files=[],
                summary="No changes produced (allowed by config)",
            )

        frozen = _normalize_scope_list(frozen_scope)
        allow = _normalize_scope_list(allowed_scope)

        frozen_touched = [f for f in changed if _in_scope(f, frozenset(frozen))]
        out_of_scope = [f for f in changed if not _in_scope(f, frozenset(allow))]

        allowed = [f for f in changed if f not in out_of_scope and f not in frozen_touched]

        if frozen_touched:
            return RuntimeScopeEnforcementResult(
                ok=False, changed_files=list(changed), allowed_files=allowed,
                out_of_scope_files=out_of_scope, frozen_touched_files=frozen_touched,
                failure_code=AgentRuntimeFailureCode.AGENT_TOUCHED_FROZEN_SCOPE,
                summary=f"Agent touched frozen scope: {frozen_touched}",
            )

        if out_of_scope:
            return RuntimeScopeEnforcementResult(
                ok=False, changed_files=list(changed), allowed_files=allowed,
                out_of_scope_files=out_of_scope, frozen_touched_files=[],
                failure_code=AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE,
                summary=f"Agent changed files outside allowed scope: {out_of_scope}",
            )

        return RuntimeScopeEnforcementResult(
            ok=True, changed_files=list(changed), allowed_files=list(changed),
            out_of_scope_files=[], frozen_touched_files=[],
            summary=f"All {len(changed)} changed files are within scope",
        )


def _invalid_scope_paths(paths: list[str]) -> list[str]:
    invalid: list[str] = []
    for p in paths:
        normalized = p.replace("\\", "/")
        if normalized.startswith("/"):
            invalid.append(p)
        elif normalized.startswith("..") or normalized == "..":
            invalid.append(p)
        elif "/../" in normalized:
            invalid.append(p)
        elif len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
            # Windows drive path like C:\...
            invalid.append(p)
    return invalid


def _normalize_scope_list(scope: list[str]) -> list[str]:
    out: list[str] = []
    for p in scope:
        normalized = Path(p).as_posix().rstrip("/")
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _in_scope(file_path: str, scope_set: frozenset[str]) -> bool:
    normalized = file_path.replace("\\", "/")
    # Exact file match
    if normalized in scope_set:
        return True
    # Directory prefix match (scope "src/foo" matches "src/foo/bar.py")
    for sp in scope_set:
        if any(marker in sp for marker in ("*", "?", "[")):
            if fnmatch.fnmatchcase(normalized, sp):
                return True
            continue
        if normalized == sp or normalized.startswith(sp + "/"):
            return True
        # Also match if file is exactly a directory scope entry (e.g. "src/foo" matches itself)
    return False


def _dedupe_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
