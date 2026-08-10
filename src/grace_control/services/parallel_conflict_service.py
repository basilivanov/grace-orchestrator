# ############################################################################
# AI_HEADER: parallel_conflict_service — Canonical runtime scope/key conflicts
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Normalize packet scopes and decide whether a candidate can coexist
#          with active parallel lease snapshots.
# inputs: Relative scope paths, glob patterns, conflict keys, and lease-like
#         objects containing normalized scope/key snapshots.
# returns: Canonical lists and boolean conflict decisions.
# side_effects: None; this service is a pure runtime policy component.
# emitted_logs: scope_conflict_detected, conflict_key_detected.
# error_behavior: Raises ValueError for absolute or parent-traversing paths and
#                 malformed non-string scope/key entries.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ParallelConflictService
#     methods:
#       - normalize_scope
#       - normalize_scopes
#       - normalize_conflict_keys
#       - scopes_overlap
#       - conflict_keys_overlap
#       - can_run_together
# END_MODULE_MAP

from __future__ import annotations

import fnmatch
import posixpath
from collections.abc import Iterable
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("parallel_conflict")


# START_BLOCK_PARALLEL_CONFLICT_SERVICE
class ParallelConflictService:
    """Conservative scope and semantic-resource conflict policy."""

    _GLOB_CHARS = frozenset("*?[")

    # START_FUNCTION_CONTRACT
    # name: normalize_scope
    # purpose: Normalize one relative scope path without weakening its boundary.
    # inputs: scope — one relative file, directory, or glob pattern.
    # returns: Canonical slash-separated scope string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for invalid absolute or parent paths.
    # END_FUNCTION_CONTRACT
    @classmethod
    def normalize_scope(cls, scope: str) -> str:
        if not isinstance(scope, str):
            raise ValueError("scope entries must be strings")
        value = scope.strip().replace("\\", "/")
        if not value:
            return ""
        if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
            raise ValueError(f"scope must be relative: {scope!r}")
        if any(part == ".." for part in value.split("/")):
            raise ValueError(f"scope cannot traverse parent directories: {scope!r}")
        normalized = posixpath.normpath(value)
        if normalized in ("", "."):
            return ""
        return normalized.rstrip("/")

    # START_FUNCTION_CONTRACT
    # name: normalize_scopes
    # purpose: Normalize, deduplicate, and deterministically order scope paths.
    # inputs: scopes — iterable of relative paths, one string, or None.
    # returns: Sorted unique canonical scope paths.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for malformed paths.
    # END_FUNCTION_CONTRACT
    @classmethod
    def normalize_scopes(cls, scopes: Iterable[str] | str | None) -> list[str]:
        if scopes is None:
            return []
        values = [scopes] if isinstance(scopes, str) else list(scopes)
        return sorted({normalized for item in values if (normalized := cls.normalize_scope(item))})

    # START_FUNCTION_CONTRACT
    # name: normalize_conflict_keys
    # purpose: Normalize, deduplicate, and deterministically order semantic keys.
    # inputs: conflict_keys — iterable of strings, one string, or None.
    # returns: Sorted unique trimmed conflict keys.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for malformed keys.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def normalize_conflict_keys(conflict_keys: Iterable[str] | str | None) -> list[str]:
        if conflict_keys is None:
            return []
        values = [conflict_keys] if isinstance(conflict_keys, str) else list(conflict_keys)
        normalized: set[str] = set()
        for key in values:
            if not isinstance(key, str):
                raise ValueError("conflict_keys entries must be strings")
            value = key.strip()
            if value:
                normalized.add(value)
        return sorted(normalized)

    # START_FUNCTION_CONTRACT
    # name: scopes_overlap
    # purpose: Detect exact, file/directory, directory/child, or conservative glob overlap.
    # inputs: left, right — scope collections or individual scope strings.
    # returns: True when the two scope sets may touch; otherwise False.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for malformed paths.
    # END_FUNCTION_CONTRACT
    @classmethod
    def scopes_overlap(
        cls,
        left: Iterable[str] | str | None,
        right: Iterable[str] | str | None,
    ) -> bool:
        left_scopes = cls.normalize_scopes(left)
        right_scopes = cls.normalize_scopes(right)
        return any(cls._scope_entry_overlap(a, b) for a in left_scopes for b in right_scopes)

    # START_FUNCTION_CONTRACT
    # name: conflict_keys_overlap
    # purpose: Detect shared semantic resources between two key collections.
    # inputs: left, right — conflict key collections or individual keys.
    # returns: True when at least one normalized key is shared.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for malformed keys.
    # END_FUNCTION_CONTRACT
    @classmethod
    def conflict_keys_overlap(
        cls,
        left: Iterable[str] | str | None,
        right: Iterable[str] | str | None,
    ) -> bool:
        return bool(
            set(cls.normalize_conflict_keys(left))
            & set(cls.normalize_conflict_keys(right))
        )

    # START_FUNCTION_CONTRACT
    # name: can_run_together
    # purpose: Check a candidate against active parallel lease snapshots.
    # inputs: candidate_scope, candidate_conflict_keys, active_leases — either
    #         explicit candidate snapshot plus leases, or candidate packet/dict
    #         plus leases in the two-argument convenience form.
    # returns: True only when scope and conflict-key sets are disjoint.
    # side_effects: None.
    # emitted_logs: scope_conflict_detected or conflict_key_detected on conflict.
    # error_behavior: Raises ValueError for malformed candidate or lease snapshots.
    # END_FUNCTION_CONTRACT
    @classmethod
    def can_run_together(
        cls,
        candidate_scope: Iterable[str] | str | Any | None,
        candidate_conflict_keys: Iterable[str] | str | Any | None = None,
        active_leases: Iterable[Any] | None = None,
    ) -> bool:
        if active_leases is None:
            active_leases = candidate_conflict_keys or []
            candidate = candidate_scope
            if isinstance(candidate, dict):
                candidate_scope = cls._lease_value(candidate, "scope", "scope_json")
                candidate_conflict_keys = cls._lease_value(
                    candidate, "conflict_keys", "conflict_keys_json"
                )
            else:
                spec = getattr(candidate, "spec_json", None)
                if isinstance(spec, dict):
                    candidate_scope = spec.get("scope", [])
                    candidate_conflict_keys = spec.get("conflict_keys", [])
                else:
                    candidate_scope = cls._lease_value(candidate, "scope", "scope_json")
                    candidate_conflict_keys = cls._lease_value(
                        candidate, "conflict_keys", "conflict_keys_json"
                    )
        normalized_candidate_scope = cls.normalize_scopes(candidate_scope)
        normalized_candidate_keys = cls.normalize_conflict_keys(candidate_conflict_keys)
        for lease in active_leases:
            lease_scope = cls._lease_value(lease, "scope_json", "scope")
            lease_keys = cls._lease_value(lease, "conflict_keys_json", "conflict_keys")
            if cls.scopes_overlap(normalized_candidate_scope, lease_scope):
                _log.info("scope_conflict_detected", reason="scope_overlap")
                return False
            if cls.conflict_keys_overlap(normalized_candidate_keys, lease_keys):
                _log.info("conflict_key_detected", reason="conflict_key_overlap")
                return False
        return True

    # START_FUNCTION_CONTRACT
    # name: _scope_entry_overlap
    # purpose: Compare two already normalized scope entries conservatively.
    # inputs: left, right — canonical scope strings.
    # returns: True when entries may address the same resource.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for canonical entries.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _scope_entry_overlap(cls, left: str, right: str) -> bool:
        if left == right or cls._path_prefix(left, right) or cls._path_prefix(right, left):
            return True

        left_glob = cls._has_glob(left)
        right_glob = cls._has_glob(right)
        if not left_glob and not right_glob:
            return False

        if left_glob and not right_glob:
            return cls._glob_and_exact_overlap(left, right)
        if right_glob and not left_glob:
            return cls._glob_and_exact_overlap(right, left)

        left_prefix = cls._static_prefix(left)
        right_prefix = cls._static_prefix(right)
        if left_prefix and right_prefix and cls._definitely_disjoint(left_prefix, right_prefix):
            return False
        # Shared or empty static prefixes are intentionally conservative: two
        # patterns may match the same generated or hidden file.
        return True

    # START_FUNCTION_CONTRACT
    # name: _glob_and_exact_overlap
    # purpose: Compare a glob pattern with an exact path conservatively.
    # inputs: pattern — canonical glob; exact — canonical non-glob path.
    # returns: True when the exact path can match or is the pattern's directory.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None for canonical entries.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _glob_and_exact_overlap(cls, pattern: str, exact: str) -> bool:
        if pattern.count("[") != pattern.count("]"):
            return True
        static_prefix = cls._static_prefix(pattern)
        if static_prefix and cls._path_prefix(exact, static_prefix):
            return True
        if static_prefix and cls._definitely_disjoint(static_prefix, exact):
            return False
        if fnmatch.fnmatchcase(exact, pattern):
            return True
        if "**" in pattern:
            return True
        return False

    # START_FUNCTION_CONTRACT
    # name: _lease_value
    # purpose: Read a scope/key field from an ORM row or mapping.
    # inputs: lease — ORM object or mapping; names — preferred field aliases.
    # returns: Stored field value or an empty list.
    # side_effects: None.
    # error_behavior: None; missing fields are treated as empty snapshots.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _lease_value(lease: Any, *names: str) -> Any:
        for name in names:
            if isinstance(lease, dict) and name in lease:
                return lease[name]
            value = getattr(lease, name, None)
            if value is not None:
                return value
        return []

    # START_FUNCTION_CONTRACT
    # name: _has_glob
    # purpose: Identify shell-style pattern syntax in a canonical scope.
    # inputs: value — canonical scope string.
    # returns: True when value contains a supported glob marker.
    # side_effects: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _has_glob(cls, value: str) -> bool:
        return any(character in value for character in cls._GLOB_CHARS)

    # START_FUNCTION_CONTRACT
    # name: _static_prefix
    # purpose: Extract the non-pattern directory prefix of a scope pattern.
    # inputs: value — canonical scope string.
    # returns: Canonical directory prefix before the first glob segment.
    # side_effects: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _static_prefix(cls, value: str) -> str:
        parts = value.split("/")
        prefix: list[str] = []
        for part in parts:
            if cls._has_glob(part):
                break
            prefix.append(part)
        return "/".join(prefix)

    # START_FUNCTION_CONTRACT
    # name: _path_prefix
    # purpose: Compare paths using component boundaries, never raw string prefixes.
    # inputs: parent, child — canonical path entries.
    # returns: True when child is parent or below parent.
    # side_effects: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _path_prefix(parent: str, child: str) -> bool:
        return child.startswith(parent + "/")

    # START_FUNCTION_CONTRACT
    # name: _definitely_disjoint
    # purpose: Prove that two static prefixes cannot touch.
    # inputs: left, right — canonical non-glob prefixes or exact paths.
    # returns: True only when their first path components are disjoint.
    # side_effects: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @classmethod
    def _definitely_disjoint(cls, left: str, right: str) -> bool:
        return not (
            left == right
            or cls._path_prefix(left, right)
            or cls._path_prefix(right, left)
        )


# END_BLOCK_PARALLEL_CONFLICT_SERVICE
