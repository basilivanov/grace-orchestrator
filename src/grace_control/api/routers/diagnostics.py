"""Diagnostics API — /api/diagnostics/state."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from grace_control.db import get_db
from grace_control.services.diagnostics_service import DiagnosticsService

router = APIRouter()
_svc = DiagnosticsService()


@router.get("/state")
def get_state() -> dict:
    with get_db() as db:
        state = _svc.get_state(db)
    return {"data": state, "timestamp": datetime.utcnow().isoformat() + "Z"}
