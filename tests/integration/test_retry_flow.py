"""Block L: Retry Flow integration tests — 4 tests."""
import pytest


async def _setup(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "RETRY", "waves": [{"title": "W1", "packets": [
            {"title": "P1", "scope": ["x.py"], "acceptance_profile": "NORMAL"}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    return pid


@pytest.mark.asyncio
async def test_rejected_then_accepted(api):
    pid = await _setup(api)

    # Attempt 1 — reject
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "rejected", "result": {}})
    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "rejected"

    # Retry: mark ready, claim again
    from grace_control.core.packet_operations import retry_packet
    retry_packet(pid)
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    await api.post(f"/api/packets/{pid}/merge", json={})

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "merged"
    assert r.json()["data"]["attempt_count"] == 2


@pytest.mark.asyncio
async def test_max_retries_fails(api):
    pid = await _setup(api)

    for attempt in range(3):
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{pid}/release",
                       json={"worker_id": "w1", "status": "rejected", "result": {}})
        if attempt < 2:
            from grace_control.core.packet_operations import retry_packet
            retry_packet(pid)

    from grace_control.core.state_machine import StateTransitionError
    with pytest.raises(StateTransitionError, match="Max attempts"):
        from grace_control.core.packet_operations import retry_packet
        retry_packet(pid)

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["attempt_count"] == 3


@pytest.mark.asyncio
async def test_two_run_records_created(api):
    pid = await _setup(api)

    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "rejected", "result": {}})

    from grace_control.core.packet_operations import retry_packet
    retry_packet(pid)
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})

    r = await api.get(f"/api/packets/{pid}")
    runs = r.json()["data"]["runs"]
    assert len(runs) >= 2


@pytest.mark.asyncio
async def test_attempt_count_tracks(api):
    pid = await _setup(api)

    for _ in range(2):
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{pid}/release",
                       json={"worker_id": "w1", "status": "rejected", "result": {}})
        from grace_control.core.packet_operations import retry_packet
        retry_packet(pid)

    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["attempt_count"] == 3
