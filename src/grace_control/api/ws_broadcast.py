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
