"""W7 — /api/agents/run smoke test (OpenAPI + happy path)."""
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


def test_agents_run_mock_succeeds(client, tmp_path):
    payload = {
        "packet_id": "pkt-agents-1",
        "role": "coder",
        "model": "mock-v1",
        "provider": "mock",
        "worktree_path": str(tmp_path),
        "packet_markdown": "# hello",
        "timeout_seconds": 10,
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True
    assert "[mock:mock-v1]" in body["stdout"]


def test_agents_run_rejects_unknown_provider(client, tmp_path):
    payload = {
        "packet_id": "pkt-agents-bad",
        "provider": "garbage",
        "worktree_path": str(tmp_path),
        "packet_markdown": "# x",
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code == 400
    assert "unknown provider" in r.json()["detail"]


def test_agents_run_persists_log(client, tmp_path):
    payload = {
        "packet_id": "pkt-agents-log",
        "provider": "mock",
        "model": "mock-v1",
        "worktree_path": str(tmp_path),
        "packet_markdown": "# hi",
    }
    r = client.post("/api/agents/run", json=payload)
    assert r.status_code == 200
    log = (tmp_path / ".agent_gateway.log")
    assert log.exists()
    assert "packet_id=pkt-agents-log" in log.read_text()
