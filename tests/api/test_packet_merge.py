"""Tests for packet merge endpoint — P0-2 from review-004."""

import pytest


@pytest.mark.asyncio
async def test_merge_requires_worktree_and_branch(api):
    """P1-2: merge endpoint returns 400 without worktree_path/branch_name."""
    r = await api.post("/api/packets/nonexistent/merge", json={})
    assert r.status_code == 400
    assert "worktree_path" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_merge_404_for_nonexistent_packet(api):
    """Merge endpoint returns 404 for non-existent packet."""
    r = await api.post("/api/packets/pkt-nonexistent/merge", json={
        "worktree_path": "/tmp/wt", "branch_name": "agent/test"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_merge_400_if_not_accepted(api):
    """Merge endpoint returns 400 for non-ACCEPTED packet."""
    from grace_control.db import get_db, init_db as _init_db
    from grace_control.db.schema import Packet
    import os

    # Create packet directly via DB
    with get_db() as db:
        db.add(Packet(id="pkt-draft", feature_id="F1", wave_id="W01",
                      slug="draft", title="Draft",
                      spec_json={"scope": ["x.py"]},
                      state="draft", attempt_count=0, max_attempts=3,
                      acceptance_profile="NORMAL"))
    r = await api.post("/api/packets/pkt-draft/merge", json={
        "worktree_path": "/tmp/wt", "branch_name": "agent/test"})
    assert r.status_code == 400
    assert "ACCEPTED" in r.json()["detail"]


@pytest.mark.asyncio
async def test_merge_accepted_packet_missing_inputs_400(api):
    """ACCEPTED packet without worktree_path/branch_name returns 400."""
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "MergeGuard", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})

    r = await api.post(f"/api/packets/{pid}/merge", json={})
    assert r.status_code == 400
    assert "worktree_path" in r.json()["detail"]
