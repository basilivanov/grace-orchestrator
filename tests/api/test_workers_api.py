"""Block I: Workers API tests — 6 tests."""
import pytest


@pytest.mark.asyncio
async def test_register_and_list(api):
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.get("/api/workers/")
    assert r.status_code == 200
    workers = r.json()["data"]
    assert len(workers) == 1
    assert workers[0]["id"] == "w1"
    assert workers[0]["status"] == "active"


@pytest.mark.asyncio
async def test_register_twice_is_idempotent(api):
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.get("/api/workers/")
    assert len(r.json()["data"]) == 1


@pytest.mark.asyncio
async def test_heartbeat_updates_timestamp(api):
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/workers/heartbeat", json={"worker_id": "w1"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_heartbeat_unknown_worker_404(api):
    r = await api.post("/api/workers/heartbeat", json={"worker_id": "ghost"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_worker_idle_after_release(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "T", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    claim = (await api.post("/api/packets/claim", json={"worker_id": "w1"})).json()["data"]
    await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "lease_id": claim["lease_id"],
        "claimed_attempt": claim["claimed_attempt"], "status": "accepted",
        "result": {"accepted": True}})
    r = await api.get("/api/workers/")
    w = r.json()["data"][0]
    assert w["current_packet_id"] is None


@pytest.mark.asyncio
async def test_worker_idle_after_cancel(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "T2", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test"})
    r = await api.get("/api/workers/")
    assert r.json()["data"][0]["current_packet_id"] is None
