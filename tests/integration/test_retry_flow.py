"""Block L: Retry Flow integration tests — 4 tests."""
import subprocess

import pytest


@pytest.fixture(autouse=True)
def disable_stale_base_recheck(monkeypatch):
    """Manual merge fixtures predate the persisted worker base snapshot."""
    from grace_control.config.settings import settings

    monkeypatch.setattr(settings, "integration_recheck_on_stale_base", False)


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True)
    # Ensure the initial branch is named 'main' (merge defaults to main)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], check=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


async def _claim(api):
    response = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    assert response.status_code == 200
    return response.json()["data"]


async def _setup(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "RETRY", "waves": [{"title": "W1", "packets": [
            {"title": "P1", "scope": ["x.py"], "acceptance_profile": "NORMAL"}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    return pid


@pytest.mark.asyncio
async def test_rejected_then_accepted(api, tmp_path):
    pid = await _setup(api)

    # Create a clean git repo for merge
    repo = tmp_path / "repo"
    _init_repo(repo)

    # Attempt 1 — reject
    claim = await _claim(api)
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "rejected", "result": {},
                         "lease_id": claim["lease_id"], "claimed_attempt": claim["claimed_attempt"]})
    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "rejected"

    # Retry: mark ready, claim again
    from grace_control.core.packet_operations import retry_packet
    retry_packet(pid)
    claim = await _claim(api)
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True},
                         "lease_id": claim["lease_id"], "claimed_attempt": claim["claimed_attempt"]})
    await api.post(f"/api/packets/{pid}/merge", json={
        "worktree_path": str(tmp_path / "worktree"),
        "branch_name": "HEAD",
        "target_repo_root": str(repo),
        "commit_sha": "abc" * 10,
    })

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["state"] == "merged"
    assert r.json()["data"]["attempt_count"] == 2


@pytest.mark.asyncio
async def test_max_retries_fails(api):
    pid = await _setup(api)

    for attempt in range(3):
        claim = await _claim(api)
        await api.post(f"/api/packets/{pid}/release",
                       json={"worker_id": "w1", "status": "rejected", "result": {},
                             "lease_id": claim["lease_id"], "claimed_attempt": claim["claimed_attempt"]})
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

    # Create runs manually (worker normally does this)
    from grace_control.db import get_db
    from grace_control.db.schema import PacketRun
    from datetime import datetime, timezone

    with get_db() as db:
        db.add(PacketRun(id=f"{pid}-R01", packet_id=pid, run_number=1, status="rejected"))
        db.add(PacketRun(id=f"{pid}-R02", packet_id=pid, run_number=2, status="accepted"))
        db.commit()

    r = await api.get(f"/api/packets/{pid}")
    runs = r.json()["data"]["runs"]
    assert len(runs) >= 2


@pytest.mark.asyncio
async def test_attempt_count_tracks(api):
    pid = await _setup(api)

    for _ in range(2):
        claim = await _claim(api)
        await api.post(f"/api/packets/{pid}/release",
                       json={"worker_id": "w1", "status": "rejected", "result": {},
                             "lease_id": claim["lease_id"], "claimed_attempt": claim["claimed_attempt"]})
        from grace_control.core.packet_operations import retry_packet
        retry_packet(pid)

    claim = await _claim(api)
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True},
                         "lease_id": claim["lease_id"], "claimed_attempt": claim["claimed_attempt"]})

    r = await api.get(f"/api/packets/{pid}")
    assert r.json()["data"]["attempt_count"] == 3
