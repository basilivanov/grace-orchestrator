"""Events API — /api/events.

Filterable event log access. Replaces ad-hoc DB queries from CLI trace.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from grace_control.db import get_db
from grace_control.services.event_query_service import EventQueryService

router = APIRouter()
_svc = EventQueryService()


@router.get("")
def list_events(
    entity_id: str | None = Query(None),
    entity_type: str | None = Query(None),
    event_type: str | None = Query(None),
    trace_id: str | None = Query(None),
    since: str | None = Query(None, description="ISO8601 timestamp (inclusive)"),
    until: str | None = Query(None, description="ISO8601 timestamp (inclusive)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with get_db() as db:
        page = _svc.query(
            db,
            entity_id=entity_id,
            entity_type=entity_type,
            event_type=event_type,
            trace_id=trace_id,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
    return {"data": page, "timestamp": datetime.utcnow().isoformat() + "Z"}
