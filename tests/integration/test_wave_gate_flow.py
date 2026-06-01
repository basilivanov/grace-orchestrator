"""Block N: Wave Gate Flow integration tests — 3 tests."""
import pytest


@pytest.mark.asyncio
async def test_full_two_wave_e2e(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WGATE", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}, {"title": "B", "scope": ["b.py"]}]},
            {"title": "W2", "packets": [{"title": "C", "scope": ["c.py"]}]}]}})
    pids = r.json()["data"]["packets"]
    w1_pids = [p for p in pids if "W01" in p]
    w2_pids = [p for p in pids if "W02" in p]

    # Verify W1 ready, W2 draft
    for p in w1_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "ready"
    for p in w2_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "draft"

    # Execute W1
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    for p in w1_pids:
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{p}/release",
                       json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
        await api.post(f"/api/packets/{p}/merge", json={})

    # Trigger wave gate
    from grace_control.core.wave_gate import check_wave_gates
    check_wave_gates()

    for p in w2_pids:
        r = await api.get(f"/api/packets/{p}")
        assert r.json()["data"]["state"] == "ready"

    # Execute W2
    for p in w2_pids:
        await api.post("/api/packets/claim", json={"worker_id": "w1"})
        await api.post(f"/api/packets/{p}/release",
                       json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
        await api.post(f"/api/packets/{p}/merge", json={})

    # Trigger feature gate
    from grace_control.core.feature_gate import check_feature_completion
    check_feature_completion()

    r = await api.get("/api/features/FEAT-WGATE")
    assert r.json()["data"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_wave2_not_claimable_before_wave1_done(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WG2", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}]},
            {"title": "W2", "packets": [{"title": "B", "scope": ["b.py"]}]}]}})
    pids = r.json()["data"]["packets"]

    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    claimed = r.json()["data"]["packet_id"]
    assert claimed == pids[0]  # W1 packet


@pytest.mark.asyncio
async def test_wave_gate_check_idempotent_via_api(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "WG3", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}]},
            {"title": "W2", "packets": [{"title": "B", "scope": ["b.py"]}]}]}})
    pids = r.json()["data"]["packets"]
    w2_pid = [p for p in pids if "W02" in p][0]

    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pids[0]}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    await api.post(f"/api/packets/{pids[0]}/merge", json={})

    from grace_control.core.wave_gate import check_wave_gates
    check_wave_gates()
    check_wave_gates()  # second call

    r = await api.get(f"/api/packets/{w2_pid}")
    assert r.json()["data"]["state"] == "ready"
