# AI_HEADER: lifecycle router — public HTTP surface for supervisor state
# START_MODULE_CONTRACT
# purpose: Expose supervisor state AND control operations through the public
#          API so any client (curl, monitoring, scripts) can drive the
#          runtime without needing direct access to the supervisor unix
#          socket. GET endpoints are read-only; POST endpoints are thin
#          proxies that forward to the supervisor's private control socket
#          (see supervisor.py). Authorization is delegated to the existing
#          AuthMiddleware — non-localhost callers must present a valid
#          Bearer token when GRACE_API_AUTH_ENABLED=true.
# inputs: HTTP requests; reads $WT/supervisor.json + DB Worker table.
# returns: structured JSON describing the runtime or the result of a
#          proxied supervisor action.
# side_effects: POST /restart and POST /cleanup trigger supervisor-level
#               state changes (kill+respawn subprocesses, delete files).
#               Idempotency: POST /cleanup is safe to repeat; POST /restart
#               is not — repeated restarts respawn every time.
# emitted_logs: lifecycle_proxy_failed (when supervisor is unreachable).
# error_behavior: 503 if supervisor state file is missing; 502 if
#                 supervisor socket is unreachable; 401 from AuthMiddleware
#                 when auth fails.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

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
            "`scripts/live_supervisor.sh` or `python -m grace_control.cli start`.",
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
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        _log.warn("lifecycle_proxy_failed", method=method, path=path, error=str(e)[:200])
        raise HTTPException(502, f"supervisor proxy failed: {e!s}")


@router.get("/status")
async def status() -> dict[str, Any]:
    """Combined snapshot: supervisor state + DB workers + code version."""
    state = read_state_file()
    if state is None:
        raise HTTPException(
            503,
            "supervisor state not found — is the supervisor running? "
            "Start it with `scripts/live_supervisor.sh` or `python -m grace_control.cli start`.",
        )
    return {
        "supervisor_state": state,
        "db_workers": get_db_workers(),
        "code_sha": get_git_sha(),
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.get("/versions")
async def versions() -> dict[str, Any]:
    """Code version of the running API vs the supervisor's children.

    If a child was spawned before the latest code change, it will report an
    older sha (or no sha at all if launched before this field was tracked).
    Use `grace_ctl restart workers` (or `POST /api/admin/lifecycle/restart/workers`)
    to bring them in sync.
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
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mutating endpoints — proxy to the supervisor's private control socket.
# Localhost callers bypass auth (see AuthMiddleware). External callers
# must present a valid Bearer token when GRACE_API_AUTH_ENABLED=true.
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/restart/{target}")
async def restart_endpoint(
    target: str,
) -> dict[str, Any]:
    """Restart API, workers, or both. Proxies to supervisor.sock.

    Args:
        target: one of `api`, `workers`, `all`.

    Returns:
        supervisor's `{"ok": true, "target": target}` on success.
    """
    if target not in {"api", "workers", "all"}:
        raise HTTPException(400, f"target must be api|workers|all, got {target!r}")
    return await _proxy_supervisor("POST", f"/control/restart/{target}")


@router.post("/cleanup")
async def cleanup_endpoint(
    worktrees: bool = Query(True, description="Clean orphaned git worktrees."),
    state_files: bool = Query(True, description="Remove .grace_state/ entries older than `stale_state_days`."),
    stale_leases: bool = Query(True, description="Release DB leases older than `stale_lease_minutes`."),
    stale_lease_minutes: int = Query(30, ge=1, description="Lease age threshold in minutes."),
    stale_state_days: int = Query(7, ge=1, description="State-file age threshold in days."),
) -> dict[str, Any]:
    """Idempotent cleanup. Proxies to supervisor.sock.

    Safe to call repeatedly. Returns a structured report of what was removed.
    """
    return await _proxy_supervisor(
        "POST",
        "/control/cleanup",
        params={
            "worktrees": str(worktrees).lower(),
            "state_files": str(state_files).lower(),
            "stale_leases": str(stale_leases).lower(),
            "stale_lease_minutes": stale_lease_minutes,
            "stale_state_days": stale_state_days,
        },
    )


@router.post("/reload")
async def reload_endpoint() -> dict[str, Any]:
    """Re-prime the mtime watcher. Proxies to supervisor.sock.

    Use after `git pull` so the next mtime scan picks up new files. Does
    NOT restart children — see `/restart/{target}` for that.
    """
    return await _proxy_supervisor("POST", "/control/reload")


@router.post("/shutdown")
async def shutdown_endpoint() -> dict[str, Any]:
    """Stop the supervisor and all children (graceful). Proxies to supervisor.sock.

    The supervisor sends SIGTERM to children, waits `terminate_grace`
    seconds (default 5s), then SIGKILL. The supervisor itself exits.
    """
    return await _proxy_supervisor("POST", "/control/stop")
