# ############################################################################
# AI_HEADER: worktree_scope_artifacts
# ROLE: Publish worktree scope lifecycle results as Prefect markdown artifacts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Publish worktree scope lifecycle evaluation results as operator-visible Prefect artifacts.
# inputs: Lifecycle result dict from evaluate_worktree_scope.
# returns: List of artifact IDs (empty if Prefect unavailable).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: publish_worktree_scope_lifecycle_artifact
#   - function: _build_artifact_markdown
#   - function: _get_create_markdown_artifact
# END_MODULE_MAP

from __future__ import annotations

import importlib
from typing import Any, Callable


# START_FUNCTION_CONTRACT
# name: _get_create_markdown_artifact
# purpose: Lazy import of Prefect create_markdown_artifact function.
# inputs: None.
# returns: Callable | None - create_markdown_artifact function or None if unavailable.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None if Prefect unavailable, does not raise.
# END_FUNCTION_CONTRACT
def _get_create_markdown_artifact() -> Callable[..., Any] | None:
    """
    Lazy import of Prefect create_markdown_artifact function.

    Returns None if Prefect is not available.
    Uses importlib to avoid direct prefect import at module level.
    """
    try:
        prefect_artifacts = importlib.import_module("prefect.artifacts")
        return getattr(prefect_artifacts, "create_markdown_artifact", None)
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


# START_FUNCTION_CONTRACT
# name: _build_artifact_markdown
# purpose: Build markdown content for worktree scope lifecycle artifact.
# inputs:
#   result: dict[str, Any] - Lifecycle result dict.
# returns: str - Markdown content for artifact.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_artifact_markdown(result: dict[str, Any]) -> str:
    """
    Build markdown content for worktree scope lifecycle artifact.

    Includes:
    - Packet ID and attempt
    - Domain status (passed/scope_blocked/worktree_error)
    - Worktree path and branch name
    - Changed files list
    - Scope violations (frozen, outside allowed, invalid paths)
    - Blocker reason if present
    """
    packet_id = result.get("packet_id", "unknown")
    attempt = result.get("attempt", 0)
    status = result.get("status", "unknown")
    worktree_path = result.get("worktree_path", "")
    branch_name = result.get("branch_name", "")
    changed_files = result.get("changed_files", [])
    scope_guard = result.get("scope_guard", {})
    blocker_reason = result.get("blocker_reason")

    # Status emoji
    status_emoji = {
        "passed": "✅",
        "scope_blocked": "🚫",
        "worktree_error": "❌",
    }.get(status, "❓")

    lines = [
        f"# Worktree Scope Lifecycle: {status_emoji} {status.upper()}",
        "",
        f"**Packet ID:** `{packet_id}`  ",
        f"**Attempt:** `{attempt}`  ",
        f"**Status:** `{status}`  ",
        "",
    ]

    # Worktree details
    if worktree_path:
        lines.extend([
            "## Worktree",
            "",
            f"**Path:** `{worktree_path}`  ",
            f"**Branch:** `{branch_name}`  ",
            "",
        ])

    # Changed files
    lines.extend([
        "## Changed Files",
        "",
    ])

    if changed_files:
        lines.append(f"**Total:** {len(changed_files)}")
        lines.append("")
        for file_path in changed_files[:20]:  # Limit to first 20
            lines.append(f"- `{file_path}`")
        if len(changed_files) > 20:
            lines.append(f"- ... and {len(changed_files) - 20} more")
    else:
        lines.append("*No changed files*")

    lines.append("")

    # Scope violations
    frozen_violations = scope_guard.get("frozen_violations", [])
    outside_allowed = scope_guard.get("outside_allowed", [])
    invalid_paths = scope_guard.get("invalid_paths", [])

    if frozen_violations or outside_allowed or invalid_paths:
        lines.extend([
            "## Scope Violations",
            "",
        ])

        if frozen_violations:
            lines.append(f"### 🚫 Frozen Violations ({len(frozen_violations)})")
            lines.append("")
            for v in frozen_violations[:10]:
                file_path = v.get("file_path", "unknown")
                matched_pattern = v.get("matched_pattern")
                if matched_pattern:
                    lines.append(f"- `{file_path}` (matched: `{matched_pattern}`)")
                else:
                    lines.append(f"- `{file_path}`")
            if len(frozen_violations) > 10:
                lines.append(f"- ... and {len(frozen_violations) - 10} more")
            lines.append("")

        if outside_allowed:
            lines.append(f"### ⚠️ Outside Allowed Scope ({len(outside_allowed)})")
            lines.append("")
            for v in outside_allowed[:10]:
                file_path = v.get("file_path", "unknown")
                lines.append(f"- `{file_path}`")
            if len(outside_allowed) > 10:
                lines.append(f"- ... and {len(outside_allowed) - 10} more")
            lines.append("")

        if invalid_paths:
            lines.append(f"### ❌ Invalid Paths ({len(invalid_paths)})")
            lines.append("")
            for v in invalid_paths[:10]:
                file_path = v.get("file_path", "unknown")
                reason = v.get("reason", "unknown")
                lines.append(f"- `{file_path}`: {reason}")
            if len(invalid_paths) > 10:
                lines.append(f"- ... and {len(invalid_paths) - 10} more")
            lines.append("")

    # Blocker reason
    if blocker_reason:
        lines.extend([
            "## Blocker Reason",
            "",
            f"```",
            blocker_reason,
            f"```",
            "",
        ])

    # Footer
    lines.extend([
        "---",
        "",
        "*Generated by GRACE Worktree Scope Lifecycle Flow*",
    ])

    return "\n".join(lines)


# START_FUNCTION_CONTRACT
# name: publish_worktree_scope_lifecycle_artifact
# purpose: Publish worktree scope lifecycle result as Prefect markdown artifact.
# inputs:
#   result: dict[str, Any] - Lifecycle result dict from evaluate_worktree_scope.
# returns: list[str] - List of artifact IDs (empty if Prefect unavailable or publication failed).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_FUNCTION_CONTRACT
def publish_worktree_scope_lifecycle_artifact(result: dict[str, Any]) -> list[str]:
    """
    Publish worktree scope lifecycle result as Prefect markdown artifact.

    Best-effort publication:
    - Returns empty list if Prefect artifacts are unavailable
    - Returns empty list if publication fails
    - Does not raise exceptions

    Args:
        result: Lifecycle result dict from evaluate_worktree_scope

    Returns:
        List of artifact IDs (empty if unavailable/failed)
    """
    create_markdown_artifact = _get_create_markdown_artifact()
    if create_markdown_artifact is None:
        # Prefect not available
        return []

    try:
        markdown = _build_artifact_markdown(result)

        packet_id = result.get("packet_id", "unknown")
        attempt = result.get("attempt", 0)
        status = result.get("status", "unknown")

        artifact_id = create_markdown_artifact(
            key=f"worktree-scope-{packet_id}-attempt-{attempt}",
            markdown=markdown,
            description=f"Worktree scope lifecycle: {status}",
        )

        return [artifact_id] if artifact_id else []

    except Exception:
        # Publication failed, return empty list
        return []
