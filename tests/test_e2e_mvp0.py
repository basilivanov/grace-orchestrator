# ############################################################################
# AI_HEADER: test_e2e_mvp0
# ROLE: MVP-0 vertical slice E2E test — architect plan → claim → release → merge.
# ############################################################################

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
import pytest_asyncio

from grace_control.api.main import app
from grace_control.db import init_db


@pytest.fixture
def e2e_db(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return db_url


@pytest_asyncio.fixture
async def api_client(e2e_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_mvp0_vertical_slice(api_client):
    """Full vertical slice: architect plan → claim → release → merge."""
    c = api_client

    # 1. Create plan → packets in READY
    spec = {
        "title": "E2E Test Feature",
        "waves": [{
            "title": "Foundation",
            "packets": [{"title": "Add test file", "scope": "src/test.py"}],
        }],
    }
    r = await c.post("/api/architect/plan", json={"feature_spec": spec})
    assert r.status_code == 200
    pid = r.json()["data"]["packets"][0]
    assert r.json()["data"]["feature_id"] == "FEAT-E2E-TEST-FEATURE"

    # Verify READY
    r = await c.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "ready"

    # 2. Register + claim (READY→RUNNING)
    await c.post("/api/workers/register", json={"worker_id": "w1"})
    r = await c.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.status_code == 200
    assert r.json()["data"]["packet_id"] == pid
    assert r.json()["data"]["lease_id"] is not None

    # Verify RUNNING
    r = await c.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "running"

    # 3. Release → ACCEPTED
    r = await c.post(f"/api/packets/{pid}/release",
                     json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "accepted"

    # 4. Merge → MERGED
    r = await c.post(f"/api/packets/{pid}/merge", json={"commit_sha": "abc"})
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "merged"

    # 5. Final verification
    r = await c.get(f"/api/packets/{pid}")
    data = r.json()["data"]
    assert data["state"] == "merged"
    assert data["attempt_count"] == 1
    assert len(data.get("runs", [])) >= 0


@pytest.mark.asyncio
async def test_e2e_claim_no_packets(api_client):
    await api_client.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api_client.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_e2e_health(api_client):
    r = await api_client.get("/health")
    assert r.status_code == 200
    assert "status" in r.json()


@pytest.mark.asyncio
async def test_dashboard(api_client):
    r = await api_client.get("/")
    assert r.status_code == 200
    assert "GRACE Control Plane" in r.text
