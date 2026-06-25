"""WebSocket broadcast for real-time dashboard updates."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect

_clients: list[WebSocket] = []

RECOVERY_EVENTS = frozenset([
    "recovery_classified",
    "recovery_decision_made",
    "recovery_retry_same_coder",
    "recovery_switch_coder",
    "recovery_return_to_architect",
    "recovery_escalate_architect",
    "recovery_retry_verifier",
    "recovery_retry_reviewer",
    "recovery_retry_merge",
    "recovery_block_feature",
    "recovery_no_action",
    "recovery_apply_failed",
])


async def handle_websocket(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _clients.remove(ws)
    except Exception:
        if ws in _clients:
            _clients.remove(ws)


async def broadcast_event(event_type: str, data: dict):
    dead = []
    payload = json.dumps({"type": event_type, **data}, default=str)
    for ws in _clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)
    if event_type.startswith("recovery_"):
        await _broadcast_recovery(event_type, data)


async def _broadcast_recovery(event_type: str, data: dict):
    recovery_payload = json.dumps({
        "type": "recovery_update",
        "data": data,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
    }, default=str)
    dead = []
    for ws in _clients:
        try:
            await ws.send_text(recovery_payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)

# START_FUNCTION_CONTRACT
# purpose: Broadcast packet cancellation to all connected WebSocket clients.
# inputs: packet_id (str), reason (str)
# returns: None
# side_effects: Sends WebSocket messages, logs event.
# error_behavior: Errors during sending are handled by broadcast_event.
# END_FUNCTION_CONTRACT
async def broadcast_packet_cancel(packet_id: str, reason: str = ""):
    try:
        from grace_control.core.structured_logger import log_event
        log_event("ws_broadcast", {"action": "cancel", "packet_id": packet_id, "reason": reason})
    except ImportError:
        pass
    await broadcast_event("state_change", {
        "packet_id": packet_id,
        "state": "cancelled",
        "reason": reason
    })

# START_FUNCTION_CONTRACT
# purpose: Broadcast packet merge to all connected WebSocket clients.
# inputs: packet_id (str), commit_sha (str)
# returns: None
# side_effects: Sends WebSocket messages, logs event.
# error_behavior: Errors during sending are handled by broadcast_event.
# END_FUNCTION_CONTRACT
async def broadcast_packet_merge(packet_id: str, commit_sha: str = ""):
    try:
        from grace_control.core.structured_logger import log_event
        log_event("ws_broadcast", {"action": "merge", "packet_id": packet_id, "commit_sha": commit_sha})
    except ImportError:
        pass
    await broadcast_event("state_change", {
        "packet_id": packet_id,
        "state": "merged",
        "commit_sha": commit_sha
    })


async def broadcast_stage_started(packet_id: str, stage_key: str, stage_run_id: str, attempt: int, loop_round: int, started_at: str, executor_id: str | None = None, model: str | None = None):
    await broadcast_event("stage_started", {
        "packet_id": packet_id,
        "stage_key": stage_key,
        "stage_run_id": stage_run_id,
        "attempt": attempt,
        "loop_round": loop_round,
        "started_at": started_at,
        "executor_id": executor_id,
        "model": model,
    })


async def broadcast_stage_finished(packet_id: str, stage_key: str, stage_run_id: str, status: str, finished_at: str, duration_ms: int | None = None, error: str | None = None, tokens_in: int | None = None, tokens_out: int | None = None, cost_usd: float | None = None):
    await broadcast_event("stage_finished", {
        "packet_id": packet_id,
        "stage_key": stage_key,
        "stage_run_id": stage_run_id,
        "status": status,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "error": error,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
    })


async def broadcast_stage_log_line(packet_id: str, stage_key: str, source: str, line: str, level: str, ts: str, trace_id: str | None = None):
    await broadcast_event("stage_log_line", {
        "packet_id": packet_id,
        "stage_key": stage_key,
        "source": source,
        "line": line,
        "level": level,
        "ts": ts,
        "trace_id": trace_id,
    })


async def broadcast_stage_artifact_added(packet_id: str, stage_key: str, path: str, size: int, type: str):
    await broadcast_event("stage_artifact_added", {
        "packet_id": packet_id,
        "stage_key": stage_key,
        "path": path,
        "size": size,
        "type": type,
    })


async def broadcast_stage_returned(packet_id: str, from_stage: str, to_stage: str, reason: str, decision: str, loop_round: int, parent_stage_run_id: str | None = None):
    await broadcast_event("stage_returned", {
        "packet_id": packet_id,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "reason": reason,
        "decision": decision,
        "loop_round": loop_round,
        "parent_stage_run_id": parent_stage_run_id,
    })


async def broadcast_worker_heartbeat(worker_id: str, current_packet_id: str | None, current_stage_key: str | None, last_heartbeat: str, lease_expires_at: str | None):
    await broadcast_event("worker_heartbeat", {
        "worker_id": worker_id,
        "current_packet_id": current_packet_id,
        "current_stage_key": current_stage_key,
        "last_heartbeat": last_heartbeat,
        "lease_expires_at": lease_expires_at,
    })


async def broadcast_metrics_updated(stage_keys: list[str], period: str, computed_at: str):
    await broadcast_event("metrics_updated", {
        "stage_keys": stage_keys,
        "period": period,
        "computed_at": computed_at,
    })
