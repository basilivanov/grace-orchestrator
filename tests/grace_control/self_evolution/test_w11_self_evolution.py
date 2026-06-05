"""W11 — Self-evolution safety: service DTOs, risk classification, rollback,
and the no-subprocess-spawn constraint."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.db import init_db
from grace_control.services.self_evolution_service import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SelfEvolutionService,
    SessionCreateRequest,
)


@pytest.fixture
def db_session(tmp_path):
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/w11_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)


@pytest.fixture
def client_w11(tmp_path, db_session):
    return TestClient(app)


# ── 1. Session creation returns session_id, not spawn ──────────────────


def test_create_session_returns_id_not_process(db_session):
    """Session creation returns a session_id, not a worker/PID."""
    svc = SelfEvolutionService()
    req = SessionCreateRequest(title="test evolution", description="refactor utils")
    resp = svc.create_session(req)
    assert resp.session_id.startswith("se-")
    assert resp.status == "session_created"
    assert resp.risk_class in (RISK_LOW, RISK_MEDIUM, RISK_HIGH)


# ── 2. Risk classification ──────────────────────────────────────────────


def test_docs_only_session_low_risk():
    """Description containing only .md/docs references is low risk."""
    svc = SelfEvolutionService()
    risk = svc.classify("update README.md and docs/architecture.md")
    assert risk == RISK_LOW


def test_code_change_medium_risk():
    """Code changes (scope: src/) default to medium risk."""
    svc = SelfEvolutionService()
    risk = svc.classify("refactor packet executor",
                        constraints={"allowed_scope": ["src/"]})
    assert risk == RISK_MEDIUM


def test_config_change_high_risk():
    """Changes to config/ or security/ are high risk."""
    svc = SelfEvolutionService()
    risk = svc.classify("update settings",
                        constraints={"frozen_scope": ["config/"]})
    assert risk == RISK_HIGH


# ── 3. Low-risk sessions can skip approval ──────────────────────────────


def test_low_risk_does_not_require_approval():
    """Docs-only sessions have requires_approval=False."""
    svc = SelfEvolutionService()
    req = SessionCreateRequest(title="docs update", description="fix README.md")
    resp = svc.create_session(req)
    assert resp.risk_class == RISK_LOW
    assert resp.requires_approval is False


# ── 4. Rollback metadata created with session ───────────────────────────


def test_rollback_metadata_stored(db_session):
    """Rollback plan stores base_commit and rollback_command."""
    svc = SelfEvolutionService()
    req = SessionCreateRequest(title="test", description="change")
    resp = svc.create_session(req, project_root=Path("."))
    rp = svc.get_rollback(resp.session_id)
    assert rp is not None
    assert rp.rollback_command  # contains git reset --hard <sha> or similar


def test_rollback_after_merge_stores_merge_commit(db_session):
    """commit_after_merge records merge_commit and changed files."""
    svc = SelfEvolutionService()
    req = SessionCreateRequest(title="test", description="change")
    resp = svc.create_session(req)
    svc.commit_after_merge(resp.session_id, "abc123", ["src/x.py"])
    rp = svc.get_rollback(resp.session_id)
    assert rp is not None
    assert rp.merge_commit == "abc123"
    assert "src/x.py" in rp.changed_files
    assert "git revert" in rp.rollback_command


# ── 5. API: session is created via POST /evolve ─────────────────────────


def test_api_create_session_returns_session_id(client_w11):
    """POST /self/evolve returns session_id without spawning."""
    resp = client_w11.post("/api/self/evolve", json={
        "title": "refactor utils",
        "description": "clean up src/utils.py",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "session_id" in body
    assert body["status"] == "session_created"
    assert "risk_class" in body
    assert body["session_id"].startswith("se-")


def test_api_list_sessions(client_w11):
    """GET /self/sessions returns created sessions."""
    client_w11.post("/api/self/evolve", json={"title": "s1"})
    resp = client_w11.get("/api/self/sessions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["title"] == "s1"


def test_api_get_session(client_w11):
    """GET /self/sessions/{id} returns full session including rollback_plan."""
    create = client_w11.post("/api/self/evolve", json={"title": "show-me"}).json()
    sid = create["session_id"]
    resp = client_w11.get(f"/api/self/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == sid
    assert "rollback_plan" in body
    assert "risk_class" in body


def test_api_cancel_session(client_w11):
    """POST /self/sessions/{id}/cancel sets status to cancelled."""
    create = client_w11.post("/api/self/evolve", json={"title": "cancel-me"}).json()
    sid = create["session_id"]
    resp = client_w11.post(f"/api/self/sessions/{sid}/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True
    get = client_w11.get(f"/api/self/sessions/{sid}").json()["data"]
    assert get["status"] == "cancelled"


# ── 6. No subprocess spawn in router source ─────────────────────────────


def test_router_has_no_subprocess_spawn():
    """The self-evolution router must not import subprocess or asyncio.create_subprocess."""
    import grace_control.api.routers.self_evolution as se_router
    text = Path(se_router.__file__).read_text()
    assert "import subprocess" not in text
    assert "asyncio.create_subprocess" not in text
    assert "subprocess.run" not in text
    assert "subprocess.Popen" not in text
