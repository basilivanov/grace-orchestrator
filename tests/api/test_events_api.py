"""Block J: Events API tests — 7 tests."""
import pytest


@pytest.mark.asyncio
async def test_events_empty(api):
    r = await api.get("/api/events")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_claim_generates_event(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": f"Evt{__import__('uuid').uuid4().hex[:6]}", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})

    r = await api.get(f"/api/events?entity_type=packet&entity_id={pid}")
    events = r.json()["data"]
    assert len(events) >= 1, f"Expected at least 1 event for {pid}, got {len(events)}"
    assert any(e["event_type"] == "packet_claimed" for e in events)


@pytest.mark.asyncio
async def test_release_generates_event(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Evt2", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "accepted", "result": {"accepted": True}})

    r = await api.get(f"/api/events?entity_type=packet&entity_id={pid}")
    events = r.json()["data"]
    event_types = [e["event_type"] for e in events]
    assert "packet_released" in event_types


@pytest.mark.asyncio
async def test_merge_generates_event(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Evt3", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    r_merge = await api.post(f"/api/packets/{pid}/merge", json={
        "worktree_path": "/tmp/fake-wt", "branch_name": "agent/test"})

    r = await api.get(f"/api/events?entity_type=packet&entity_id={pid}")
    event_types = [e["event_type"] for e in r.json()["data"]]
    if r_merge.status_code == 200:
        assert "packet_merged" in event_types
    else:
        assert "packet_merged" not in event_types


@pytest.mark.asyncio
async def test_cancel_generates_event(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Evt4", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test cancel"})

    r = await api.get(f"/api/events?entity_type=packet&entity_id={pid}")
    assert "packet_cancelled" in [e["event_type"] for e in r.json()["data"]]


@pytest.mark.asyncio
async def test_events_filter_by_entity_type(api):
    r = await api.get("/api/events?entity_type=nonexistent")
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_events_filter_by_entity_id(api):
    r = await api.get("/api/events?entity_id=NONEXISTENT-PACKET")
    assert r.json()["data"] == []
