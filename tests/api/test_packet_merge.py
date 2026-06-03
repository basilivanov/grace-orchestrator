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
