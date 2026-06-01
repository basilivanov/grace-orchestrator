# ############################################################################
# AI_HEADER: event_recorder
# ROLE: Write events to the events table on state transitions and lifecycle changes.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Record structured events for audit trail.
# inputs: event_type, entity_type, entity_id, payload, trace_id.
# returns: None.
# side_effects: DB insert into events table.
# emitted_logs: None.
# error_behavior: Catches and ignores errors — audit must never block operations.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: record_event
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime, timezone

from grace_control.db import get_db
from grace_control.db.schema import Event


def record_event(
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
    trace_id: str | None = None,
    db=None,
) -> None:
    try:
        if db is not None:
            db.add(Event(
                timestamp=datetime.now(timezone.utc),
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload_json=payload,
                trace_id=trace_id,
            ))
        else:
            with get_db() as db2:
                db2.add(Event(
                    timestamp=datetime.now(timezone.utc),
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    payload_json=payload,
                    trace_id=trace_id,
                ))
    except Exception:
        pass
