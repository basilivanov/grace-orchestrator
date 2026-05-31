# ############################################################################
# AI_HEADER: test_e2e_mvp0
# ROLE: MVP-0 vertical slice E2E test — architect plan → worker → accept.
# ############################################################################

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn


@pytest.fixture
def e2e_db(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    os.environ["GRACE_DB_URL"] = db_url
    from grace_control.db import init_db
    init_db(db_url)
    return db_url


@pytest.fixture
def e2e_dirs(tmp_path):
    project = tmp_path / "project"
    state = tmp_path / "state"
    worktrees = tmp_path / "worktrees"
    for d in (project, state, worktrees):
        d.mkdir(parents=True)
    (project / "grace" / "packets").mkdir(parents=True, exist_ok=True)
    return project, state, worktrees


@pytest_asyncio.fixture
async def api_server(tmp_path, e2e_db, e2e_dirs):
    project_root, state_root, _worktree_root = e2e_dirs
    db_url = e2e_db

    def run_server():
        os.environ["GRACE_DB_URL"] = db_url
        os.chdir(str(project_root))
        from grace_control.api.main import app
        uvicorn.run(app, host="127.0.0.1", port=8043, log_level="error")

    proc = multiprocessing.Process(target=run_server)
    proc.start()
    await asyncio.sleep(2)

    yield f"http://localhost:8043", db_url, project_root, state_root

    proc.terminate()
    proc.join(timeout=5)


@pytest.mark.asyncio
async def test_mvp0_vertical_slice(api_server):
    """Full vertical slice: architect plan → claim → release → accepted."""
    api_url, db_url, project_root, state_root = api_server

    async with httpx.AsyncClient(base_url=api_url) as client:
        # 1. Create plan → packets in READY
        spec = {
            "title": "E2E Test Feature",
            "waves": [{
                "title": "Foundation",
                "packets": [{"title": "Add test file", "scope": "src/test.py"}],
            }],
        }
        r = await client.post("/api/architect/plan", json={"feature_spec": spec})
        assert r.status_code == 200
        data = r.json()["data"]
        packet_id = data["packets"][0]
        assert data["feature_id"] == "FEAT-E2E-TEST-FEATURE"
        print(f"OK: feature={data['feature_id']} packet={packet_id}")

        # Verify packet is READY
        r = await client.get(f"/api/packets/{packet_id}")
        assert r.json()["data"]["state"] == "ready"
        print("OK: packet state=ready")

        # 2. Register worker + claim (READY→RUNNING)
        await client.post("/api/workers/register", json={"worker_id": "test-w1"})
        r = await client.post("/api/packets/claim", json={"worker_id": "test-w1"})
        assert r.status_code == 200
        claim_data = r.json()["data"]
        assert claim_data["packet_id"] == packet_id
        print(f"OK: claimed packet={packet_id}")

        # Verify RUNNING
        r = await client.get(f"/api/packets/{packet_id}")
        assert r.json()["data"]["state"] == "running"
        print("OK: packet state=running")

        # 3. Release → ACCEPTED
        r = await client.post(
            f"/api/packets/{packet_id}/release",
            json={"worker_id": "test-w1", "status": "accepted", "result": {"accepted": True}},
        )
        assert r.status_code == 200
        assert r.json()["data"]["state"] == "accepted"
        print("OK: packet state=accepted")

        # 4. Final verification
        r = await client.get(f"/api/packets/{packet_id}")
        data = r.json()["data"]
        assert data["state"] == "accepted"
        assert data["attempt_count"] == 1
        print(f"OK: E2E complete! state={data['state']}")


@pytest.mark.asyncio
async def test_e2e_claim_no_packets(api_server):
    """Claim returns 404 when no READY packets."""
    api_url, *_ = api_server

    async with httpx.AsyncClient(base_url=api_url) as client:
        await client.post("/api/workers/register", json={"worker_id": "w1"})
        r = await client.post("/api/packets/claim", json={"worker_id": "w1"})
        assert r.status_code == 404
        print("OK: claim=404 when queue empty")


@pytest.mark.asyncio
async def test_e2e_health(api_server):
    """Health endpoint responds."""
    api_url, *_ = api_server

    async with httpx.AsyncClient(base_url=api_url) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        print(f"OK: health status={data['status']}")
