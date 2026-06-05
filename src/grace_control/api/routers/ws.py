# ############################################################################
# AI_HEADER: api_routers_ws
# ROLE: WebSocket router — /ws.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Mount the WebSocket endpoint that delegates to ws_broadcast.
# inputs: WebSocket.
# returns: None (the broadcast handler streams).
# side_effects: None at this layer.
# emitted_logs: None.
# error_behavior: Errors handled inside handle_websocket.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - WS /ws
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, WebSocket

from grace_control.api.ws_broadcast import handle_websocket

router = APIRouter(tags=["ws"])


# START_FUNCTION_CONTRACT
# name: websocket_endpoint
# purpose: Wrap the broadcast handler for the /ws route.
# inputs: ws (WebSocket).
# returns: None.
# side_effects: Streams events to the client.
# emitted_logs: None.
# error_behavior: Errors raised by handle_websocket propagate.
# END_FUNCTION_CONTRACT
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await handle_websocket(ws)
