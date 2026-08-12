# AI_HEADER: lifecycle router — public HTTP surface for supervisor state
# START_MODULE_CONTRACT
# purpose: Expose supervisor state and control operations through the public
#          API. Mutations pass the canonical project-local control and audit
#          boundary before any supervisor socket operation.
# inputs: HTTP requests; reads $WT/supervisor.json + DB Worker table.
# returns: structured JSON describing the runtime or the result of a
#          proxied supervisor action.
# side_effects: Confirmed restart/reload operations may proxy to the
#               supervisor; legacy cleanup/shutdown aliases are audited and
#               unavailable.
# emitted_logs: lifecycle_proxy_failed (when supervisor is unreachable).
# error_behavior: 401/403 for control/origin failures; 400/501 for invalid or
#                 unavailable legacy operations; 503 if state is missing; 502
#                 if the supervisor socket is unreachable.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:
#   - function: read_state_file
#   - function: get_git_sha
#   - function: get_db_workers
#   - function: _proxy_supervisor
# END_MODULE_MAP

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request

from grace_control.api.routers.admin_controls import legacy_admin_action
from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Worker

_log = GraceLogger("lifecycle_router")

router = APIRouter(
    prefix="/api/admin/lifecycle",
    tags=["lifecycle"],
    responses={
        401: {"description": "Unauthorized"},
        502: {"description": "Supervisor socket unreachable"},
        503: {"description": "Supervisor not running"},
    },
)

DEFAULT_TARGET_DIR = "/tmp/grace-live-wt"
PROXY_TIMEOUT_SECONDS = 30.0


def _target_dir() -> Path:
    """Find the supervisor state directory.

    Order: GRACE_TARGET_DIR env → settings field → default. The state file
    lives at $target/supervisor.json; the socket lives at $target/supervisor.sock.
    """
    return Path(os.environ.get("GRACE_TARGET_DIR") or getattr(settings, "target_dir", "") or DEFAULT_TARGET_DIR)


def _socket_path() -> Path:
    return _target_dir() / "supervisor.sock"


def read_state_file(target_dir: Path | None = None) -> dict[str, Any] | None:
    state_path = (target_dir or _target_dir()) / "supervisor.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def get_git_sha(source_dir: Path | None = None) -> str:
    """Return current git HEAD sha (short). Empty string if not a git repo."""
    candidates = [
        source_dir,
        _target_dir(),
        Path.cwd(),
    ]
    for c in candidates:
        if c is None:
            continue
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(c), capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
    return ""


def get_db_workers() -> list[dict[str, Any]]:
    """Snapshot of Worker rows known to the API."""
    with get_db() as db:
        rows = db.query(Worker).all()
        return [
            {
                "worker_id": w.id,
                "status": w.status,
                "current_packet_id": w.current_packet_id,
                "last_heartbeat": w.last_heartbeat.isoformat() + "Z" if w.last_heartbeat else None,
                "started_at": w.started_at.isoformat() + "Z" if w.started_at else None,
            }
            for w in rows
        ]


async def _proxy_supervisor(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Forward an HTTP request to the supervisor's unix-socket control app.

    Raises:
        HTTPException 503: supervisor state file missing (not started).
        HTTPException 502: supervisor socket exists but request failed.
    """
    sock = _socket_path()
    state_path = _target_dir() / "supervisor.json"
    if not state_path.exists():
        raise HTTPException(
            503,
            "supervisor not running — start it with "
            "`scripts/live_supervisor.sh`; use the HTTP API after bootstrap.",
        )
    if not sock.exists():
        raise HTTPException(502, f"supervisor state present but socket missing: {sock}")
    try:
        transport = httpx.AsyncHTTPTransport(uds=str(sock))
        async with httpx.AsyncClient(transport=transport, timeout=PROXY_TIMEOUT_SECONDS) as client:
            r = await client.request(method, f"http://localhost{path}", params=params or {})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        # Surface the supervisor's own error verbatim
        raise HTTPException(e.response.status_code, e.response.text) from e
    except Exception as e:
        _log.warn("lifecycle_proxy_failed", method=method, path=path, error=str(e)[:200])
        raise HTTPException(502, f"supervisor proxy failed: {e!s}") from e


@router.get("/status")
async def status() -> dict[str, Any]:
    """Combined snapshot: supervisor state + DB workers + code version."""
    state = read_state_file()
    if state is None:
        raise HTTPException(
            503,
            "supervisor state not found — is the supervisor running? "
            "Start it with `scripts/live_supervisor.sh`; use the HTTP API after bootstrap.",
        )
    return {
        "supervisor_state": state,
        "db_workers": get_db_workers(),
        "code_sha": get_git_sha(),
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


@router.get("/versions")
async def versions() -> dict[str, Any]:
    """Code version of the running API vs the supervisor's children.

    If a child was spawned before the latest code change, it will report an
    older sha (or no sha at all if launched before this field was tracked).
    Use `POST /api/admin/lifecycle/restart/workers` to bring them in sync.
    """
    state = read_state_file()
    if state is None:
        raise HTTPException(503, "supervisor not running")
    current_sha = get_git_sha()
    api_pid = (state.get("api") or {}).get("pid")
    workers = state.get("workers", [])
    return {
        "current_sha": current_sha,
        "api": {"pid": api_pid, "in_sync": True},  # api in-process
        "workers": [
            {"pid": w.get("pid"), "started_at": w.get("started_at")}
            for w in workers
        ],
        "recommendation": (
            "POST /api/admin/lifecycle/restart/workers to bring children in sync"
            if workers else "no workers to restart"
        ),
    }


@router.get("/health/full")
async def health_full() -> dict[str, Any]:
    """One-shot deep health: supervisor + workers + code + db.

    Designed to be polled by external monitoring (e.g. uptime checks).
    Returns 200 even when degraded; inspect `healthy` for the boolean.
    """
    state = read_state_file()
    db_workers = get_db_workers()
    issues: list[str] = []
    if state is None:
        issues.append("supervisor state missing")
    if state and not state.get("api"):
        issues.append("api not running")
    if state and not state.get("workers"):
        issues.append("no workers running")
    if not db_workers:
        issues.append("no workers registered in DB")
    return {
        "healthy": not issues,
        "issues": issues,
        "supervisor_alive": state is not None,
        "api_alive": bool(state and state.get("api")),
        "workers_alive": len(state.get("workers", [])) if state else 0,
        "db_workers": len(db_workers),
        "code_sha": get_git_sha(),
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mutating endpoints — proxy to the supervisor's private control socket.
# Localhost callers bypass auth (see AuthMiddleware). External callers
# must present a valid Bearer token when GRACE_API_AUTH_ENABLED=true.
# ─────────────────────────────────────────────────────────────────────────────


async def _restart_local(target: str) -> dict[str, Any]:
    if target not in {"api", "workers", "all"}:
        raise HTTPException(400, f"target must be api|workers|all, got {target!r}")
    return await _proxy_supervisor("POST", f"/control/restart/{target}")


@router.post("/restart/{target}")
async def restart_endpoint(
    request: Request,
    target: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    """Restart API, workers, or both through canonical control and audit."""
    action = {
        "api": "restart_api",
        "workers": "restart_workers",
        "all": "restart_all",
    }.get(target)
    if action is None:
        from grace_control.services.admin_control_security import require_control_request
        require_control_request(request)
        raise HTTPException(400, f"target must be api|workers|all, got {target!r}")
    return await legacy_admin_action(
        request,
        action=action,
        entity_type="project",
        entity_id=None,
        body=body,
    )


@router.post("/cleanup")
async def cleanup_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    worktrees: bool = Query(True, description="Clean orphaned git worktrees."),
    state_files: bool = Query(True, description="Remove .grace_state/ entries older than `stale_state_days`."),
    stale_leases: bool = Query(True, description="Release DB leases older than `stale_lease_minutes`."),
    stale_lease_minutes: int = Query(30, ge=1, description="Lease age threshold in minutes."),
    stale_state_days: int = Query(7, ge=1, description="State-file age threshold in days."),
) -> Any:
    """Keep the pre-Control-Center supervisor cleanup alias unavailable."""
    return await legacy_admin_action(
        request,
        action="lifecycle_cleanup",
        entity_type="project",
        entity_id=None,
        body=body,
        parameters={
            "worktrees": str(worktrees).lower(),
            "state_files": str(state_files).lower(),
            "stale_leases": str(stale_leases).lower(),
            "stale_lease_minutes": stale_lease_minutes,
            "stale_state_days": stale_state_days,
        },
    )


async def _reload_local() -> dict[str, Any]:
    return await _proxy_supervisor("POST", "/control/reload")


@router.post("/shutdown")
async def shutdown_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    """Keep the destructive pre-Control-Center shutdown alias unavailable."""
    return await legacy_admin_action(
        request,
        action="shutdown",
        entity_type="project",
        entity_id=None,
        body=body,
    )


@router.post("/reload")
async def reload_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    """Re-prime the watcher through canonical control and audit."""
    return await legacy_admin_action(
        request,
        action="reload",
        entity_type="project",
        entity_id=None,
        body=body,
    )
