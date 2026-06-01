"""Block O: Worker Crash integration tests — 3 tests."""
import pytest
from datetime import datetime, timedelta

from grace_control.db import get_db
from grace_control.db.schema import Lease, PacketState


@pytest.mark.asyncio
async def test_expired_lease_requeued(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "CRASH", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["a.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})

    # Simulate crash: expire lease
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id=pid).first()
        lease.expires_at = datetime.utcnow() - timedelta(minutes=1)

    from grace_control.core.lease_manager import check_expired_leases
    expired = check_expired_leases()
    assert expired >= 1

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "ready"


@pytest.mark.asyncio
async def test_second_worker_takes_expired_packet(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "CRASH2", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["a.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})

    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id=pid).first()
        lease.expires_at = datetime.utcnow() - timedelta(minutes=1)

    from grace_control.core.lease_manager import check_expired_leases
    check_expired_leases()

    await api.post("/api/workers/register", json={"worker_id": "w2"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w2"})
    assert r.json()["data"]["packet_id"] == pid

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["attempt_count"] == 2


@pytest.mark.asyncio
async def test_two_workers_no_duplicate_claim(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "CRASH3", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["a.py"]}]}]}})
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/workers/register", json={"worker_id": "w2"})

    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.status_code == 200

    r = await api.post("/api/packets/claim", json={"worker_id": "w2"})
    assert r.status_code == 404
