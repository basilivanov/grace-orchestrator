# ############################################################################
# AI_HEADER: test_lease_manager
# ROLE: Unit tests for lease expiration checker.
# ############################################################################

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from grace_control.core.lease_manager import check_expired_leases
from grace_control.db import get_db, init_db
from grace_control.db.schema import Lease, Packet, PacketState, Worker


@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield


def test_no_expired_leases(test_db):
    assert check_expired_leases() == 0


def test_expired_lease_returns_packet(test_db):
    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01",
                       slug="t", title="T", spec_json={},
                       state=PacketState.RUNNING.value))
        db.add(Worker(id="w1", current_packet_id="PKT-001"))
        db.add(Lease(packet_id="PKT-001", worker_id="w1",
                      expires_at=datetime.now(UTC) - timedelta(minutes=5)))

    count = check_expired_leases()
    assert count == 1

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease is None
        w = db.query(Worker).filter_by(id="w1").first()
        assert w.current_packet_id is None


def test_active_lease_not_touched(test_db):
    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01",
                       slug="t", title="T", spec_json={},
                       state=PacketState.RUNNING.value))
        db.add(Worker(id="w1"))
        db.add(Lease(packet_id="PKT-001", worker_id="w1",
                      expires_at=datetime.now(UTC) + timedelta(minutes=25)))

    assert check_expired_leases() == 0

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease is not None


def test_multiple_expired_leases(test_db):
    with get_db() as db:
        for i in range(3):
            db.add(Packet(id=f"PKT-{i}", feature_id="F1", wave_id="W01",
                           slug=f"t{i}", title=f"T{i}", spec_json={},
                           state=PacketState.RUNNING.value))
            db.add(Worker(id=f"w{i}"))
            db.add(Lease(packet_id=f"PKT-{i}", worker_id=f"w{i}",
                          expires_at=datetime.now(UTC) - timedelta(minutes=10 + i)))

    assert check_expired_leases() == 3

    for i in range(3):
        with get_db() as db:
            p = db.query(Packet).filter_by(id=f"PKT-{i}").first()
            assert p.state == PacketState.READY.value
