# ############################################################################
# AI_HEADER: managed_packet_artifacts
# ROLE: Publish managed packet run results as Prefect markdown artifacts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Publish managed packet run results as operator-visible Prefect artifacts.
# inputs: Managed packet run result dict.
# returns: List of artifact IDs (empty if Prefect unavailable).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: publish_managed_packet_run_artifact
#   - function: _build_artifact_markdown
#   - function: _get_create_markdown_artifact
# END_MODULE_MAP

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable


MAX_MANAGED_RESULT_PAYLOAD_BYTES = 1024 * 1024


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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_payload_path(payload_path: str, payload_root: str) -> Path:
    path = Path(payload_path)
    root = Path(payload_root)
    if not path.is_absolute() or not root.is_absolute():
        raise ValueError("managed result payload path and root must be absolute")

    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if not _is_relative_to(resolved_path, resolved_root):
        raise ValueError("managed result payload path is outside managed result payload root")
    if resolved_path.name != "result_payload.json":
        raise ValueError("managed result payload filename must be result_payload.json")
    return resolved_path


# START_FUNCTION_CONTRACT
# name: managed_result_scope_verdict
# purpose: Derive the pilot scope verdict from managed runner result fields.
# inputs:
#   result: Managed packet run result dictionary.
# returns: Scope verdict string or None when unavailable.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def managed_result_scope_verdict(result: dict[str, Any]) -> str | None:
    scope_verdict = result.get("scope_verdict")
    if scope_verdict:
        return str(scope_verdict)

    lifecycle = result.get("lifecycle_result")
    lifecycle_status = lifecycle.get("status") if isinstance(lifecycle, dict) else None
    if lifecycle_status == "passed":
        return "passed"
    if lifecycle_status == "scope_blocked":
        return "blocked"
    if lifecycle_status:
        return str(lifecycle_status)
    return None


# START_FUNCTION_CONTRACT
# name: managed_result_live_agents_started
# purpose: Derive live-agent launch count from managed runner result fields.
# inputs:
#   result: Managed packet run result dictionary.
# returns: Integer live-agent launch count.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if explicit count is not integer-compatible.
# END_FUNCTION_CONTRACT
def managed_result_live_agents_started(result: dict[str, Any]) -> int:
    explicit = result.get("live_agents_started", result.get("agent_launch_count"))
    if explicit is not None:
        return int(explicit)

    agent_result = result.get("agent_result")
    if not isinstance(agent_result, dict):
        return 0
    if agent_result.get("dry_run") is True:
        return 0
    if agent_result.get("termination_reason") in {"dry_run", "no_agent_execution"}:
        return 0
    return 1 if agent_result else 0


# START_FUNCTION_CONTRACT
# name: build_managed_result_payload
# purpose: Build bounded status-reader evidence from a managed packet run result.
# inputs:
#   result: Managed packet run result dictionary.
# returns: JSON-safe bounded payload dictionary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if live-agent count is invalid.
# END_FUNCTION_CONTRACT
def build_managed_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Build bounded status-reader evidence from a managed packet run result."""
    payload_errors = result.get("errors")
    if payload_errors is None:
        payload_errors = []
    if payload_errors and not isinstance(payload_errors, list):
        payload_errors = [payload_errors]

    return {
        "schema_version": 1,
        "ok": bool(result.get("ok", False)),
        "domain_status": result.get("domain_status"),
        "scope_verdict": managed_result_scope_verdict(result),
        "packet_id": result.get("packet_id"),
        "attempt": result.get("attempt"),
        "live_agents_started": managed_result_live_agents_started(result),
        "changed_files": list(result.get("changed_files") or []),
        "errors": payload_errors,
        "blocker_reason": result.get("blocker_reason"),
        "artifact_ids": list(result.get("artifact_ids") or []),
        "worktree_path": result.get("worktree_path"),
        "branch_name": result.get("branch_name"),
    }


# START_FUNCTION_CONTRACT
# name: write_managed_result_payload
# purpose: Atomically write bounded managed runner evidence JSON under a declared root.
# inputs:
#   result: Managed packet run result dictionary.
#   payload_path: Absolute output JSON path.
#   payload_root: Absolute allowed root for payload_path.
# returns: Written payload path string, or None when payload_path is absent.
# side_effects: Creates parent directories and replaces payload file atomically.
# emitted_logs: None.
# error_behavior: Raises ValueError/OSError for invalid paths, oversized payloads, or write failures.
# END_FUNCTION_CONTRACT
def write_managed_result_payload(
    result: dict[str, Any],
    *,
    payload_path: str | None,
    payload_root: str | None,
) -> str | None:
    """Write managed runner evidence as bounded JSON using atomic replace."""
    if not payload_path:
        return None
    if not payload_root:
        raise ValueError("managed result payload root is required when payload path is set")

    resolved_path = _safe_payload_path(payload_path, payload_root)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_managed_result_payload(result)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_MANAGED_RESULT_PAYLOAD_BYTES:
        raise ValueError("managed result payload exceeds bounded size limit")

    temp_path = resolved_path.with_name(f".{resolved_path.name}.{os.getpid()}.tmp")
    temp_path.write_bytes(encoded)
    os.replace(temp_path, resolved_path)
    return str(resolved_path)


# START_FUNCTION_CONTRACT
# name: read_managed_result_payload
# purpose: Read bounded managed runner evidence JSON from a validated path.
# inputs:
#   payload_path: Absolute JSON payload path.
#   payload_root: Absolute allowed root for payload_path.
# returns: Parsed payload dictionary.
# side_effects: Reads payload file metadata and contents.
# emitted_logs: None.
# error_behavior: Raises ValueError/FileNotFoundError/JSONDecodeError for invalid or unreadable payloads.
# END_FUNCTION_CONTRACT
def read_managed_result_payload(
    *,
    payload_path: str | None,
    payload_root: str | None,
) -> dict[str, Any]:
    """Read bounded managed runner evidence from a validated payload file."""
    if not payload_path:
        raise ValueError("managed result payload path is missing")
    if not payload_root:
        raise ValueError("managed result payload root is missing")

    resolved_path = _safe_payload_path(payload_path, payload_root)
    size = resolved_path.stat().st_size
    if size > MAX_MANAGED_RESULT_PAYLOAD_BYTES:
        raise ValueError("managed result payload exceeds bounded size limit")
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("managed result payload must be a JSON object")
    return payload


# START_FUNCTION_CONTRACT
# name: _build_artifact_markdown
# purpose: Build markdown content for managed packet run artifact.
# inputs:
#   result: dict[str, Any] - Managed packet run result dict.
# returns: str - Markdown content for artifact.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_artifact_markdown(result: dict[str, Any]) -> str:
    """
    Build markdown content for managed packet run artifact.

    Includes:
    - Packet ID and attempt
    - Domain status (passed/scope_blocked/agent_failed/runner_error)
    - Worktree path and branch name
    - Changed files list
    - Agent result (returncode, termination reason, session mode)
    - Lifecycle status
    - Scope violations (frozen, outside allowed, invalid paths)
    - Blocker reason if present
    - Run directory / stdout / stderr paths if present
    """
    packet_id = result.get("packet_id", "unknown")
    attempt = result.get("attempt", 0)
    domain_status = result.get("domain_status", "unknown")
    worktree_path = result.get("worktree_path", "")
    branch_name = result.get("branch_name", "")
    changed_files = result.get("changed_files", [])
    agent_result = result.get("agent_result", {})
    lifecycle_result = result.get("lifecycle_result", {})
    scope_guard = result.get("scope_guard", {})
    blocker_reason = result.get("blocker_reason")

    # Status emoji
    status_emoji = {
        "passed": "✅",
        "scope_blocked": "🚫",
        "agent_failed": "❌",
        "runner_error": "⚠️",
    }.get(domain_status, "❓")

    lines = [
        f"# Managed Packet Run: {status_emoji} {domain_status.upper()}",
        "",
        f"**Packet ID:** `{packet_id}`  ",
        f"**Attempt:** `{attempt}`  ",
        f"**Domain Status:** `{domain_status}`  ",
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
        for file_path in changed_files[:20]:
            lines.append(f"- `{file_path}`")
        if len(changed_files) > 20:
            lines.append(f"- ... and {len(changed_files) - 20} more")
    else:
        lines.append("*No changed files*")

    lines.append("")

    # Agent result
    if agent_result:
        lines.extend([
            "## Agent Result",
            "",
        ])
        returncode = agent_result.get("returncode")
        if returncode is not None:
            lines.append(f"**Return Code:** `{returncode}`  ")
        termination_reason = agent_result.get("termination_reason")
        if termination_reason:
            lines.append(f"**Termination Reason:** `{termination_reason}`  ")
        session_mode = agent_result.get("session_mode")
        if session_mode:
            lines.append(f"**Session Mode:** `{session_mode}`  ")
        thread_id = agent_result.get("thread_id")
        if thread_id:
            lines.append(f"**Thread ID:** `{thread_id}`  ")

        # Run artifacts
        stdout_path = agent_result.get("stdout_path")
        stderr_path = agent_result.get("stderr_path")
        last_message_path = agent_result.get("last_message_path")
        if stdout_path or stderr_path or last_message_path:
            lines.append("")
            lines.append("**Run Artifacts:**")
            if stdout_path:
                lines.append(f"- Stdout: `{stdout_path}`")
            if stderr_path:
                lines.append(f"- Stderr: `{stderr_path}`")
            if last_message_path:
                lines.append(f"- Last Message: `{last_message_path}`")

        lines.append("")

    # Lifecycle status
    lifecycle_status = lifecycle_result.get("status")
    if lifecycle_status:
        lines.extend([
            "## Lifecycle Status",
            "",
            f"**Status:** `{lifecycle_status}`  ",
            "",
        ])

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
            "```",
            blocker_reason,
            "```",
            "",
        ])

    # Footer
    lines.extend([
        "---",
        "",
        "*Generated by GRACE Managed Packet Runner*",
    ])

    return "\n".join(lines)


# START_FUNCTION_CONTRACT
# name: publish_managed_packet_run_artifact
# purpose: Publish managed packet run result as Prefect markdown artifact.
# inputs:
#   result: dict[str, Any] - Managed packet run result dict.
# returns: list[str] - List of artifact IDs (empty if Prefect unavailable or publication failed).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_FUNCTION_CONTRACT
def publish_managed_packet_run_artifact(result: dict[str, Any]) -> list[str]:
    """
    Publish managed packet run result as Prefect markdown artifact.

    Best-effort publication:
    - Returns empty list if Prefect artifacts are unavailable
    - Returns empty list if publication fails
    - Does not raise exceptions

    Args:
        result: Managed packet run result dict

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
        domain_status = result.get("domain_status", "unknown")

        artifact_id = create_markdown_artifact(
            key=f"managed-packet-{packet_id}-attempt-{attempt}",
            markdown=markdown,
            description=f"Managed packet run: {domain_status}",
        )

        return [artifact_id] if artifact_id else []

    except Exception:
        # Publication failed, return empty list
        return []
