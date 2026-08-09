# ############################################################################
# AI_HEADER: test_db_schema
# ROLE: Unit tests for GRACE Control Plane DB schema and SQLite baseline.
# ############################################################################

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Event,
    Feature,
    Lease,
    Packet,
    PacketRun,
    PacketState,
    Wave,
    Worker,
)


@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield


def test_all_tables_exist(test_db):
    from grace_control.db.schema import Base
    tables = sorted(Base.metadata.tables.keys())
    assert tables == [
        "agent_sessions", "events", "feature_planning_runs", "features",
        "leases", "packet_runs", "packets", "self_evolution_sessions",
        "stage_metrics", "stage_runs", "waves", "workers",
    ], f"Expected 12 tables, got {tables}"


def test_create_feature(test_db):
    with get_db() as db:
        f = Feature(id="feat_test", slug="test", title="Test", spec_json={})
        db.add(f)
    with get_db() as db:
        found = db.query(Feature).filter_by(id="feat_test").first()
        assert found is not None
        assert found.title == "Test"
        assert found.slug == "test"


def test_create_wave(test_db):
    with get_db() as db:
        w = Wave(id="wave_test", feature_id="feat_test", slug="w1", title="Wave 1", order=1)
        db.add(w)
    with get_db() as db:
        found = db.query(Wave).filter_by(id="wave_test").first()
        assert found is not None
        assert found.order == 1


def test_create_packet(test_db):
    with get_db() as db:
        p = Packet(
            id="pkt_test",
            feature_id="feat_test",
            wave_id="wave_test",
            slug="create",
            title="Create test",
            spec_json={"scope": "src/test.py"},
            state=PacketState.DRAFT.value,
        )
        db.add(p)
    with get_db() as db:
        found = db.query(Packet).filter_by(id="pkt_test").first()
        assert found is not None
        assert found.state == PacketState.DRAFT.value
        assert found.acceptance_profile == "NORMAL"
        assert found.attempt_count == 0
        assert found.max_attempts == 3


def test_packet_state_transitions(test_db):
    with get_db() as db:
        p = Packet(
            id="PKT-001", feature_id="F1", wave_id="W01",
            slug="t", title="T", spec_json={}, state=PacketState.DRAFT.value,
        )
        db.add(p)
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        p.state = PacketState.READY.value
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value
        p.state = PacketState.RUNNING.value
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


def test_packet_run(test_db):
    with get_db() as db:
        p = Packet(id="PKT-001", feature_id="F1", wave_id="W01", slug="t", title="T", spec_json={})
        db.add(p)
        db.flush()
        r = PacketRun(id="PKT-001-R01", packet_id="PKT-001", run_number=1, status="accepted")
        db.add(r)
    with get_db() as db:
        runs = db.query(PacketRun).filter_by(packet_id="PKT-001").all()
        assert len(runs) == 1
        assert runs[0].run_number == 1
        assert runs[0].status == "accepted"


def test_worker(test_db):
    with get_db() as db:
        w = Worker(id="worker-1", status="active")
        db.add(w)
    with get_db() as db:
        w = db.query(Worker).filter_by(id="worker-1").first()
        assert w is not None
        assert w.status == "active"


def test_worker_heartbeat(test_db):
    with get_db() as db:
        db.add(Worker(id="worker-1"))
    with get_db() as db:
        w = db.query(Worker).filter_by(id="worker-1").first()
        w.last_heartbeat = datetime.now(UTC)
    with get_db() as db:
        w = db.query(Worker).filter_by(id="worker-1").first()
        assert w.last_heartbeat is not None


def test_lease_mechanism(test_db):
    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01", slug="t", title="T", spec_json={}))
        db.add(Worker(id="w1"))
    with get_db() as db:
        lease = Lease(
            packet_id="PKT-001", worker_id="w1",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db.add(lease)
    with get_db() as db:
        found = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert found is not None
        assert found.worker_id == "w1"
        assert found.expires_at > datetime.now(UTC).replace(tzinfo=None)


def test_lease_unique_constraint(test_db):
    from sqlalchemy.exc import IntegrityError
    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01", slug="t", title="T", spec_json={}))
        db.add(Worker(id="w1"))
        db.add(Worker(id="w2"))
    with get_db() as db:
        db.add(Lease(packet_id="PKT-001", worker_id="w1", expires_at=datetime.now(UTC) + timedelta(minutes=30)))
    with pytest.raises(IntegrityError):
        with get_db() as db:
            db.add(Lease(packet_id="PKT-001", worker_id="w2", expires_at=datetime.now(UTC) + timedelta(minutes=30)))


def test_event_log(test_db):
    with get_db() as db:
        e = Event(event_type="state_transition", entity_type="packet", entity_id="PKT-001",
                  payload_json={"from": "ready", "to": "running"})
        db.add(e)
    with get_db() as db:
        found = db.query(Event).filter_by(entity_id="PKT-001").first()
        assert found is not None
        assert found.event_type == "state_transition"


def test_in_memory_db(test_db):
    from grace_control.db.schema import Base
    tables = Base.metadata.tables.keys()
    assert len(tables) == 12
