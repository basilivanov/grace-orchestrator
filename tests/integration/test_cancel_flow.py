"""Block M: Cancel Flow integration tests — 3 tests."""
import pytest


async def _setup(api, count=2):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": f"CNL{count}", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["a.py"]}, {"title": "B", "scope": ["b.py"]}]}]}})
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    return r.json()["data"]["packets"]


@pytest.mark.asyncio
async def test_cancelled_packet_skipped_by_worker(api):
    pids = await _setup(api, 1)
    await api.post(f"/api/packets/{pids[0]}/cancel", json={"reason": "skip"})

    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.json()["data"]["packet_id"] == pids[1]


@pytest.mark.asyncio
async def test_cancel_running_next_claim_works(api):
    pids = await _setup(api, 2)
    await api.post("/api/packets/claim", json={"worker_id": "w1"})  # claims P1
    await api.post(f"/api/packets/{pids[0]}/cancel", json={"reason": "test"})

    r = await api.get(f"/api/packets/{pids[0]}")
    assert r.json()["data"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_cascades_worker_state(api):
    pids = await _setup(api, 3)
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pids[0]}/cancel", json={"reason": "test"})

    r = await api.get("/api/workers/")
    w = r.json()["data"][0]
    assert w["current_packet_id"] is None
