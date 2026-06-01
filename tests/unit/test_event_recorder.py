"""Block D: Event Recorder unit tests — 5 tests."""
from grace_control.core.event_recorder import record_event
from grace_control.db import get_db
from grace_control.db.schema import Event


def test_record_event_writes_to_db(db):
    record_event("packet_claimed", "packet", "PKT-001", {"worker": "w1"})
    with get_db() as d:
        e = d.query(Event).filter_by(entity_id="PKT-001").first()
        assert e is not None
        assert e.event_type == "packet_claimed"
        assert e.entity_type == "packet"
        assert e.payload_json["worker"] == "w1"
        assert e.timestamp is not None


def test_record_event_with_trace_id(db):
    record_event("x", "packet", "PKT-001", trace_id="trace-42")
    with get_db() as d:
        e = d.query(Event).filter_by(entity_id="PKT-001").first()
        assert e.trace_id == "trace-42"


def test_record_event_never_raises():
    record_event("x", "y", "z", {})  # No exception


def test_record_multiple_events_in_order(db):
    record_event("e1", "packet", "P1")
    record_event("e2", "packet", "P1")
    record_event("e3", "packet", "P1")
    with get_db() as d:
        events = d.query(Event).filter_by(entity_id="P1").order_by(Event.id).all()
        assert [e.event_type for e in events] == ["e1", "e2", "e3"]


def test_record_event_null_payload_ok(db):
    record_event("x", "packet", "P1", payload=None)
    with get_db() as d:
        e = d.query(Event).filter_by(entity_id="P1").first()
        assert e is not None
        assert e.payload_json is None
