"""WebSocket broadcast for real-time dashboard updates."""
from __future__ import annotations

import json
from fastapi import WebSocket, WebSocketDisconnect

_clients: list[WebSocket] = []


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
    for ws in _clients:
        try:
            await ws.send_text(json.dumps({"type": event_type, **data}, default=str))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)
