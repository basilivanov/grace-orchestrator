"""Block F: Lease Manager extended unit tests — 4 tests."""
from datetime import datetime, timedelta

from grace_control.core.lease_manager import check_expired_leases
from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketState, Worker
from tests.conftest import make_packet


def test_lease_expired_by_1_second(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
        d.add(Worker(id="w1"))
        d.add(Lease(packet_id="P1", worker_id="w1",
                     expires_at=datetime.utcnow() - timedelta(seconds=1)))
    assert check_expired_leases() == 1
    with get_db() as d:
        assert d.query(Packet).filter_by(id="P1").first().state == PacketState.READY.value


def test_lease_expires_in_future_not_touched(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
        d.add(Lease(packet_id="P1", worker_id="w1",
                     expires_at=datetime.utcnow() + timedelta(seconds=1)))
    assert check_expired_leases() == 0


def test_expired_lease_clears_worker_current_packet(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
        d.add(Worker(id="w1", current_packet_id="P1"))
        d.add(Lease(packet_id="P1", worker_id="w1",
                     expires_at=datetime.utcnow() - timedelta(minutes=1)))
    check_expired_leases()
    with get_db() as d:
        w = d.query(Worker).filter_by(id="w1").first()
        assert w.current_packet_id is None


def test_expired_lease_deleted_from_table(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
        d.add(Worker(id="w1"))
        d.add(Lease(packet_id="P1", worker_id="w1",
                     expires_at=datetime.utcnow() - timedelta(minutes=1)))
    check_expired_leases()
    with get_db() as d:
        assert d.query(Lease).filter_by(packet_id="P1").first() is None
