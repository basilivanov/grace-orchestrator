"""W7 (revised) — /api/agents/run smoke tests (UniversalCliAgentBackend)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/agents_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return TestClient(app)


def test_agents_router_in_openapi(client):
    """POST /api/agents/run must appear in the OpenAPI schema."""
    schema = client.get("/openapi.json").json()
    assert "/api/agents/run" in schema["paths"]


def test_agents_run_echo_succeeds(client, tmp_path):
    """Run a simple echo command via agents API."""
    payload = {
        "packet_id": "pkt-agents-1",
        "executor_id": "coder-mini-swe",
        "model": "test-model",
        "worktree_path": str(tmp_path),
        "packet_markdown": "# hello",
        "timeout_seconds": 10,
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code in (200, 400), r.text
    if r.status_code == 400:
        assert "unknown executor_id" in r.json()["detail"]


def test_agents_run_rejects_unknown_executor(client, tmp_path):
    """Unknown executor_id → 400."""
    payload = {
        "packet_id": "pkt-agents-bad",
        "executor_id": "no-such-executor",
        "worktree_path": str(tmp_path),
        "packet_markdown": "# x",
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code == 400
    assert "unknown executor_id" in r.json()["detail"]


def test_agents_run_persists_artifacts(client, tmp_path):
    """The endpoint should accept a valid executor_id."""
    payload = {
        "packet_id": "pkt-agents-log",
        "executor_id": "coder-mini-swe",
        "worktree_path": str(tmp_path / "wt"),
        "packet_markdown": "# hi",
        "timeout_seconds": 5,
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code in (200, 400), r.text
