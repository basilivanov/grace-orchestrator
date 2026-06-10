# ############################################################################
# AI_HEADER: api_routers_events
# ROLE: Events API — /api/events. Filterable event log access (W4).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Thin FastAPI binding to EventQueryService. No DB queries here.
# inputs: HTTP request with query params (entity_id, entity_type, event_type,
#         trace_id, since, until, limit, offset).
# returns: dict {"data": <page>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 422 on unparseable timestamps (Pydantic validation).
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET "" (events)
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from grace_control.db import get_db
from grace_control.services.event_query_service import EventQueryService

router = APIRouter()
_svc = EventQueryService()


# START_FUNCTION_CONTRACT
# name: list_events
# purpose: HTTP wrapper around EventQueryService.query.
# inputs: entity_id, entity_type, event_type, trace_id, since, until
#         (all optional str), limit (1..1000, default 100), offset (>=0).
# returns: dict {"data": {"total", "limit", "offset", "events[]"}, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 422 on bad timestamps (Pydantic).
# END_FUNCTION_CONTRACT
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
    return {"data": page, "timestamp": datetime.now(UTC).isoformat() + "Z"}
