# ############################################################################
# AI_HEADER: api_routers_diagnostics
# ROLE: Diagnostics API — /api/diagnostics/state. W4.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Thin FastAPI binding to DiagnosticsService. No DB queries here.
# inputs: HTTP request.
# returns: dict {"data": <snapshot>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /state
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from grace_control.db import get_db
from grace_control.services.diagnostics_service import DiagnosticsService

router = APIRouter()
_svc = DiagnosticsService()


# START_FUNCTION_CONTRACT
# name: get_state
# purpose: HTTP wrapper around DiagnosticsService.get_state.
# inputs: none.
# returns: dict {"data": <snapshot>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/state")
def get_state() -> dict:
    with get_db() as db:
        state = _svc.get_state(db)
    return {"data": state, "timestamp": datetime.now(UTC).isoformat() + "Z"}
