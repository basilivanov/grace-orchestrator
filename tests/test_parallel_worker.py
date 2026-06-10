# ############################################################################
# AI_HEADER: test_parallel_worker
# ROLE: Integration tests for multi-worker parallel execution.
# ############################################################################

from __future__ import annotations

import pytest

from grace_control.core.dag_validator import detect_scope_conflicts, topological_sort, validate_dag
from grace_control.db import get_db, init_db
from grace_control.db.schema import Packet, PacketState


@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield


def test_two_workers_claim_different_packets(test_db):
    """Two workers should claim different READY packets."""
    with get_db() as db:
        db.add(Packet(id="PKT-A", feature_id="F1", wave_id="W01", slug="a",
                       title="A", spec_json={}, state=PacketState.READY.value))
        db.add(Packet(id="PKT-B", feature_id="F1", wave_id="W01", slug="b",
                       title="B", spec_json={}, state=PacketState.READY.value))

    from grace_control.db import SessionLocal
    from grace_control.db.schema import Lease
    from datetime import UTC, datetime, timedelta

    def claim(worker_id):
        db = SessionLocal()
        try:
            ready = db.query(Packet).filter_by(state=PacketState.READY.value).all()
            for pkt in ready:
                existing = db.query(Lease).filter_by(packet_id=pkt.id).first()
                if existing and existing.expires_at > datetime.now(UTC):
                    continue
                if existing:
                    db.delete(existing)
                db.add(Lease(packet_id=pkt.id, worker_id=worker_id,
                             expires_at=datetime.now(UTC) + timedelta(minutes=30)))
                pkt.state = PacketState.RUNNING.value
                pkt.attempt_count += 1
                db.commit()
                return pkt.id
        finally:
            db.close()
        return None

    # Sequential claims (SQLite serializes anyway)
    a = claim("w1")
    b = claim("w2")

    assert a is not None
    assert b is not None
    assert a != b, f"Workers claimed same packet: {a}"
    print(f"OK: w1→{a}, w2→{b}")


def test_dag_ordered_execution():
    """Packets should execute in dependency order."""
    packets = [
        {"id": "P-BASE", "depends_on": [], "scope": ["src/base.py"]},
        {"id": "P-AUTH", "depends_on": ["P-BASE"], "scope": ["src/auth.py"]},
        {"id": "P-API", "depends_on": ["P-BASE"], "scope": ["src/api.py"]},
        {"id": "P-E2E", "depends_on": ["P-AUTH", "P-API"], "scope": ["src/e2e.py"]},
    ]
    result = validate_dag(packets)
    assert result.valid
    order = result.ordered_packets
    assert order.index("P-BASE") < order.index("P-AUTH")
    assert order.index("P-BASE") < order.index("P-API")
    assert order.index("P-AUTH") < order.index("P-E2E")
    assert order.index("P-API") < order.index("P-E2E")
    print(f"OK: execution order={order}")


def test_scope_conflict_detection():
    """Overlapping scopes should be flagged."""
    scope_map = {
        "P1": ["src/auth.py", "src/shared.py"],
        "P2": ["src/api.py", "src/shared.py"],
        "P3": ["src/db.py"],
    }
    conflicts = detect_scope_conflicts(scope_map)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert "P1" in (c.packet_a, c.packet_b)
    assert "P2" in (c.packet_a, c.packet_b)
    assert c.overlapping_files == ["src/shared.py"]
    print(f"OK: conflict={c}")


def test_no_conflicts_disjoint_scopes():
    """Non-overlapping scopes should have no conflicts."""
    scope_map = {"P1": ["src/a.py"], "P2": ["src/b.py"], "P3": ["src/c.py"]}
    assert detect_scope_conflicts(scope_map) == []
    print("OK: no conflicts")


def test_cycle_detection():
    """Mutual dependencies should form a cycle."""
    packets = [
        {"id": "P1", "depends_on": ["P2"], "scope": []},
        {"id": "P2", "depends_on": ["P3"], "scope": []},
        {"id": "P3", "depends_on": ["P1"], "scope": []},
    ]
    result = validate_dag(packets)
    assert not result.valid
    assert len(result.cycles) == 1
    print(f"OK: cycle={result.cycles[0]}")


def test_no_cycles_linear_deps():
    """Linear dependencies should have no cycles."""
    packets = [
        {"id": "P1", "depends_on": [], "scope": []},
        {"id": "P2", "depends_on": ["P1"], "scope": []},
        {"id": "P3", "depends_on": ["P2"], "scope": []},
    ]
    assert validate_dag(packets).valid
    print("OK: linear, no cycles")
