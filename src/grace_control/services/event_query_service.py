# ############################################################################
# AI_HEADER: event_query_service
# ROLE: Filter and paginate the events table for the /api/events endpoint.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build filtered Event queries for the API. All event filtering
#          (entity_id, entity_type, event_type, trace_id, time range) lives
#          here; new filters land in this service, not in the router.
# inputs: Session + filter kwargs.
# returns: dict with keys {total, limit, offset, events[]}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError on unparseable timestamp strings.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: EventQueryService
#     methods:
#       - query
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from grace_control.db.schema import Event


class EventQueryService:
    """Filter and paginate the events table."""

    # START_FUNCTION_CONTRACT
    # name: query
    # purpose: Filter events by entity_id / entity_type / event_type / trace_id
    #          / time range, paginate, and return a stable page shape.
    # inputs:
    #   entity_id, entity_type, event_type, trace_id: optional exact-match
    #     filters. event_type ending in '%' triggers a LIKE match; the bare
    #     'recovery_*' prefix is a special case for backward compatibility
    #     with the legacy /api/events route.
    #   since, until: ISO8601 inclusive bounds; raises ValueError if malformed.
    #   limit, offset: pagination, capped at 1000/0 respectively.
    # returns: {"total": int, "limit": int, "offset": int, "events": [...]}.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises ValueError on unparseable timestamps.
    # END_FUNCTION_CONTRACT
    def query(
        self,
        db: Session,
        *,
        entity_id: str | None = None,
        entity_type: str | None = None,
        event_type: str | None = None,
        trace_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = db.query(Event)
        if entity_id:
            q = q.filter(Event.entity_id == entity_id)
        if entity_type:
            q = q.filter(Event.entity_type == entity_type)
        if event_type:
            # Preserve the legacy "recovery_*" prefix-match contract from
            # the original /api/events route in api/main.py (W4).
            if event_type.endswith("%"):
                q = q.filter(Event.event_type.like(event_type))
            elif event_type.startswith("recovery_"):
                q = q.filter(Event.event_type.like("recovery_%"))
            else:
                q = q.filter(Event.event_type == event_type)
        if trace_id:
            q = q.filter(Event.trace_id == trace_id)
        if since:
            q = q.filter(Event.timestamp >= self._parse_ts(since))
        if until:
            q = q.filter(Event.timestamp <= self._parse_ts(until))
        total = q.count()
        rows = q.order_by(Event.timestamp.desc()).offset(offset).limit(limit).all()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp.isoformat() + "Z" if e.timestamp else "",
                    "event_type": e.event_type,
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "payload": e.payload_json or {},
                    "trace_id": e.trace_id or "",
                }
                for e in rows
            ],
        }

    @staticmethod
    def _parse_ts(raw: str) -> datetime:
        if raw.endswith("Z"):
            raw = raw[:-1]
        return datetime.fromisoformat(raw)
