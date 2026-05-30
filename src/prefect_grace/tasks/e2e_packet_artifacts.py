# ############################################################################
# AI_HEADER: e2e_packet_artifacts
# ROLE: Publish E2E packet runner results as Prefect markdown artifacts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Publish E2E packet runner results as operator-visible Prefect artifacts.
# inputs: E2E packet runner result dict.
# returns: List of artifact IDs (empty if Prefect unavailable).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: publish_e2e_packet_run_artifact
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
    """Return Prefect create_markdown_artifact if available."""
    try:
        prefect_artifacts = importlib.import_module("prefect.artifacts")
        return getattr(prefect_artifacts, "create_markdown_artifact", None)
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None


# START_FUNCTION_CONTRACT
# name: _lines_for_paths
# purpose: Build a bounded markdown list for artifact path sections.
# inputs:
#   title: str - Markdown section title.
#   paths: list[Any] - Paths or path-like values to render.
# returns: list[str] - Markdown lines.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _lines_for_paths(title: str, paths: list[Any]) -> list[str]:
    lines = [title, ""]
    if paths:
        for path in paths[:20]:
            lines.append(f"- `{path}`")
        if len(paths) > 20:
            lines.append(f"- ... and {len(paths) - 20} more")
    else:
        lines.append("*None*")
    lines.append("")
    return lines


# START_FUNCTION_CONTRACT
# name: _build_artifact_markdown
# purpose: Build markdown content for E2E packet run artifact.
# inputs:
#   result: dict[str, Any] - E2E packet runner result dict.
# returns: str - Markdown content for artifact.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_artifact_markdown(result: dict[str, Any]) -> str:
    """Build markdown content for an E2E packet run artifact."""
    packet_id = result.get("packet_id", "unknown")
    attempt = result.get("attempt", 0)
    runtime_status = result.get("runtime_status", "unknown")
    domain_status = result.get("domain_status", "unknown")
    registry_status = result.get("registry_status", "unknown")
    registry_reason = result.get("registry_reason", "unknown")
    worktree_path = result.get("worktree_path")
    executor_id = result.get("executor_id")
    managed_runner_result = result.get("managed_runner_result") or {}
    handoff_result = result.get("handoff_result") or {}
    artifact_paths = result.get("artifact_paths") or []
    errors = result.get("errors") or []

    managed_status = managed_runner_result.get("domain_status") or managed_runner_result.get("status") or "not_run"
    handoff_status = handoff_result.get("domain_status") or "not_run"
    blocker_reason = (
        result.get("blocker_reason")
        or managed_runner_result.get("blocker_reason")
        or handoff_result.get("blocker_reason")
    )

    lines = [
        f"# E2E Packet Run: {str(domain_status).upper()}",
        "",
        f"**Packet ID:** `{packet_id}`  ",
        f"**Attempt:** `{attempt}`  ",
        f"**Runtime Status:** `{runtime_status}`  ",
        f"**Domain Status:** `{domain_status}`  ",
        f"**Registry Status:** `{registry_status}`  ",
        f"**Registry Reason:** `{registry_reason}`  ",
        "",
        "## Runtime",
        "",
        f"**Worktree Path:** `{worktree_path or 'None'}`  ",
        f"**Executor ID:** `{executor_id or 'None'}`  ",
        f"**Managed Runner Status:** `{managed_status}`  ",
        f"**Handoff Status:** `{handoff_status}`  ",
        "",
    ]

    if blocker_reason:
        lines.extend([
            "## Blocker / Rework Reason",
            "",
            "```",
            str(blocker_reason),
            "```",
            "",
        ])

    lines.extend(_lines_for_paths("## Artifact Paths", artifact_paths))

    lines.extend(["## Errors", ""])
    if errors:
        for error in errors[:20]:
            lines.append(f"- `{error}`")
        if len(errors) > 20:
            lines.append(f"- ... and {len(errors) - 20} more")
    else:
        lines.append("*None*")
    lines.append("")

    lines.extend([
        "---",
        "",
        "*Generated by GRACE E2E Packet Runner Flow*",
    ])

    return "\n".join(lines)


# START_FUNCTION_CONTRACT
# name: publish_e2e_packet_run_artifact
# purpose: Publish E2E packet run result as Prefect markdown artifact.
# inputs:
#   result: dict[str, Any] - E2E packet runner result dict.
# returns: list[str] - List of artifact IDs (empty if Prefect unavailable or publication failed).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None.
# error_behavior: Returns empty list on failure, does not raise.
# END_FUNCTION_CONTRACT
def publish_e2e_packet_run_artifact(result: dict[str, Any]) -> list[str]:
    """Publish an E2E packet runner result as a best-effort Prefect artifact."""
    create_markdown_artifact = _get_create_markdown_artifact()
    if create_markdown_artifact is None:
        return []

    try:
        markdown = _build_artifact_markdown(result)
        packet_id = result.get("packet_id", "unknown")
        attempt = result.get("attempt", 0)
        domain_status = result.get("domain_status", "unknown")

        artifact_id = create_markdown_artifact(
            key=f"e2e-packet-{packet_id}-attempt-{attempt}",
            markdown=markdown,
            description=f"E2E packet run: {domain_status}",
        )
        return [artifact_id] if artifact_id else []
    except Exception:
        return []
