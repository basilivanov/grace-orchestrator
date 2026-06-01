"""Block H: Packets API tests — 14 tests."""
import pytest


async def _plan(api, title="Test", waves=None, suffix=""):
    if waves is None:
        wid = f"W{suffix}"
        waves = [{"title": wid, "packets": [{"title": f"P{suffix}", "scope": ["x.py"]}]}]
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": title + suffix, "waves": waves}
    })
    return r


@pytest.mark.asyncio
async def test_list_empty(api):
    r = await api.get("/api/packets/")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_list_filter_by_state(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})

    r = await api.get("/api/packets/?state=running")
    assert len(r.json()["data"]) == 1
    r = await api.get("/api/packets/?state=ready")
    assert len(r.json()["data"]) == 0


@pytest.mark.asyncio
async def test_list_filter_by_feature(api):
    await _plan(api, title="A")
    await _plan(api, title="B")
    r = await api.get("/api/packets/?feature_id=FEAT-A")
    for p in r.json()["data"]:
        assert p["feature_id"] == "FEAT-A"


@pytest.mark.asyncio
async def test_get_packet_structure(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    r = await api.get(f"/api/packets/{pid}")
    d = r.json()["data"]
    for field in ["id", "feature_id", "wave_id", "slug", "title", "state",
                  "acceptance_profile", "attempt_count", "max_attempts", "runs", "created_at"]:
        assert field in d, f"Missing field: {field}"
    assert d["state"] == "ready"


@pytest.mark.asyncio
async def test_get_packet_404(api):
    r = await api.get("/api/packets/NONEXISTENT")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_claim_returns_spec_and_lease(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    data = r.json()["data"]
    assert data["packet_id"] == pid
    assert data["lease_id"] is not None
    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_claim_no_packets_404(api):
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_release_accepted(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    assert r.json()["data"]["state"] == "accepted"


@pytest.mark.asyncio
async def test_release_rejected(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "rejected", "result": {}})
    assert r.json()["data"]["state"] == "rejected"


@pytest.mark.asyncio
async def test_release_unknown_status_is_failed(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "garbage", "result": {}})
    assert r.json()["data"]["state"] == "failed"


@pytest.mark.asyncio
async def test_cancel_ready(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    r = await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test"})
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_merged_is_400(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    await api.post(f"/api/packets/{pid}/merge", json={})
    r = await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_merge_requires_accepted_state(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    r = await api.post(f"/api/packets/{pid}/merge", json={})
    assert r.status_code == 400
