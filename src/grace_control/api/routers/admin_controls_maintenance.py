# ############################################################################
# AI_HEADER: admin_controls_maintenance — bounded local maintenance owners
# ROLE: Owns project-local maintenance snapshot and cleanup route bodies while
#       the admin-controls facade keeps route registration and compatibility seams.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build safe maintenance snapshots and execute bounded stale-worktree
#          cleanup using the existing maintenance control service.
# inputs: Requests, bounded cleanup bodies and explicit facade callbacks.
# returns: Snapshot dictionaries or audited maintenance JSON responses.
# side_effects: Reads local state; confirmed cleanup may remove stale worktrees.
# emitted_logs: Existing maintenance and supplied admin audit messages.
# error_behavior: Auth, confirmation, audit and maintenance failures stay
#                 explicit and fail closed.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: local_maintenance_snapshot_impl
#   - function: local_maintenance_cleanup_impl
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data

_log = GraceLogger("admin_controls_maintenance")


# START_BLOCK_MAINTENANCE
# START_FUNCTION_CONTRACT
# name: local_maintenance_snapshot_impl
# purpose: Build a dry-run maintenance snapshot with bounded ownership data.
# inputs: Maintenance and state readers plus the accepted control service.
# returns: Safe maintenance snapshot DTO.
# side_effects: Reads local DB, filesystem and maintenance state only.
# emitted_logs: Existing maintenance service read logs.
# error_behavior: Reader behavior is preserved; no cleanup is performed.
# END_FUNCTION_CONTRACT
def local_maintenance_snapshot_impl(
    *,
    maintenance_service_fn: Callable[[], Any],
    maintenance_state_fn: Callable[[], tuple[dict[str, str], dict[str, list[dict[str, Any]]]]],
    maintenance_control_service: Any,
    state_directory_summary_fn: Callable[[Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    service = maintenance_service_fn()
    packet_states, leases = maintenance_state_fn()
    safe_states = maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
    snapshot = service.snapshot(packet_states=safe_states).to_dict()
    accepted_abandoned = [
        row for row in leases["parallel"]
        if str(packet_states.get(str(row.get("packet_id")), "")).casefold() == "accepted"
        and row.get("stale_candidate")
    ]
    return {
        "ok": True,
        "data": {
            "dry_run": True,
            "snapshot": snapshot,
            "state_directories": state_directory_summary_fn(
                getattr(service, "state_root", None)
            ),
            "ordinary_leases": leases["ordinary"],
            "parallel_leases": leases["parallel"],
            "merge_leases": leases["merge"],
            "accepted_abandoned_reservations": accepted_abandoned,
            "cleanup_protected": [
                row["slug"] for row in snapshot.get("worktrees", [])
                if not row.get("is_stale")
            ],
            "plan": {
                "would_remove_worktrees": [
                    row["slug"] for row in snapshot.get("worktrees", [])
                    if row.get("is_stale")
                ],
                "would_release_leases": [
                    row["packet_id"] for row in leases["ordinary"] if row.get("stale_candidate")
                ],
                "accepted_abandoned_reservations": accepted_abandoned,
            },
        },
    }


# START_FUNCTION_CONTRACT
# name: local_maintenance_cleanup_impl
# purpose: Execute or dry-run only the bounded stale-worktree cleanup.
# inputs: Authenticated request, cleanup body and explicit facade callbacks.
# returns: Safe deleted/kept/errors/bytes response.
# side_effects: Confirmed non-dry-run cleanup removes only service-selected
#               terminal-like stale worktrees.
# emitted_logs: Supplied canonical admin audit events and maintenance logs.
# error_behavior: Invalid authorization, audit, confirmation or maintenance
#                 state fails closed without claiming success.
# END_FUNCTION_CONTRACT
async def local_maintenance_cleanup_impl(
    request: Request,
    body: dict[str, Any],
    *,
    require_control_request: Callable[[Request], Any],
    audit_identity: Callable[..., dict[str, Any]],
    audit_or_failure: Callable[..., JSONResponse | None],
    confirmation_allowed: Callable[..., bool],
    maintenance_service_fn: Callable[[], Any],
    maintenance_state_fn: Callable[[], tuple[dict[str, str], dict[str, list[dict[str, Any]]]]],
    maintenance_control_service: Any,
    mask_data: Callable[[Any], Any] = mask_operator_data,
) -> JSONResponse:
    require_control_request(request)
    audit = audit_identity(body, request, action="cleanup", entity_type="project")
    if failure := audit_or_failure(
        "admin_action_requested", audit, reason="maintenance cleanup requested", phase="before mutation",
    ):
        return failure
    if not confirmation_allowed("cleanup", audit["project_key"], "project", None, body.get("confirmation")):
        failure = {
            **audit, "ok": False, "result": "failed",
            "error_code": "CONFIRMATION_REQUIRED",
            "reason": "server-side confirmation was missing or invalid",
            "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason=failure["reason"], phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    dry_run = bool(body.get("dry_run", False))
    packet_states, leases = maintenance_state_fn()
    try:
        maintenance = maintenance_service_fn()
        safe_states = maintenance_control_service.safe_cleanup_packet_states(packet_states, leases)
        snapshot = maintenance.snapshot(packet_states=safe_states).to_dict()
        protected = {
            str(row.get("slug")): "live_or_uncertain_ownership"
            for row in snapshot.get("worktrees", [])
            if not row.get("is_stale")
        }
        result = maintenance.cleanup_stale_worktrees(
            packet_states=safe_states,
            dry_run=dry_run,
        ).to_dict()
    except Exception as exc:
        failure = {
            **audit, "ok": False, "result": "failed",
            "error": mask_data(str(exc)[:240]),
            "reason": "maintenance failed closed", "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason=failure["reason"], phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=502, content=failure)
    response = {
        **audit,
        "ok": not bool(result.get("errors")),
        "result": "success" if not result.get("errors") else "failed",
        "response": mask_data({
            "dry_run": dry_run,
            "deleted": result.get("worktrees_removed", []),
            "kept": sorted(protected),
            "kept_reasons": protected,
            "errors": result.get("errors", []),
            "bytes_freed": result.get("bytes_freed", 0),
        }),
        "reason": "maintenance dry run completed" if dry_run else "maintenance cleanup completed",
        "retry_allowed": False,
    }
    if audit_failure := audit_or_failure(
        "admin_action_completed" if response["ok"] else "admin_action_failed",
        audit,
        reason=response["reason"],
        result=response["result"],
        phase="after mutation",
        outcome=response,
    ):
        return audit_failure
    return JSONResponse(status_code=200 if response["ok"] else 502, content=response)


# END_BLOCK_MAINTENANCE
