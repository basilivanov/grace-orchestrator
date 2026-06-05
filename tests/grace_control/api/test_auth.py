"""W14.2 — API token auth tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    db_url = f"sqlite:///{tmp_path}/auth_test.db"
    monkeypatch.setenv("GRACE_DB_URL", db_url)
    init_db(db_url)
    from grace_control.api.main import app
    return TestClient(app)


def _make_auth_app(db_url: str, token: str = "test-token-42", allow_localhost: bool = True):
    os.environ["GRACE_API_AUTH_ENABLED"] = "true"
    os.environ["GRACE_API_AUTH_TOKEN"] = token
    os.environ["GRACE_API_AUTH_ALLOW_UNAUTHENTICATED_LOCALHOST"] = str(allow_localhost).lower()
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    from grace_control.config.settings import _build_settings
    from grace_control.api.app_factory import create_app
    return create_app(_build_settings())


def test_auth_disabled_still_works(client):
    r = client.get("/api/agents/profiles")
    assert r.status_code == 200


def test_auth_enabled_missing_token_returns_401(tmp_path):
    db = f"sqlite:///{tmp_path}/noauth.db"
    app = _make_auth_app(db, allow_localhost=False)
    c = TestClient(app)
    r = c.get("/api/agents/profiles")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_auth_enabled_wrong_token_returns_401(tmp_path):
    db = f"sqlite:///{tmp_path}/wrong.db"
    app = _make_auth_app(db, allow_localhost=False)
    c = TestClient(app)
    r = c.get("/api/agents/profiles", headers={"authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_auth_enabled_correct_token_passes(tmp_path):
    db = f"sqlite:///{tmp_path}/correct.db"
    app = _make_auth_app(db, allow_localhost=False)
    c = TestClient(app)
    r = c.get("/api/agents/profiles", headers={"authorization": "Bearer test-token-42"})
    assert r.status_code == 200, r.text


def test_auth_enabled_health_is_public(tmp_path):
    db = f"sqlite:///{tmp_path}/health.db"
    app = _make_auth_app(db, allow_localhost=False)
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200


def test_auth_enabled_x_grace_token_works(tmp_path):
    db = f"sqlite:///{tmp_path}/xgrace.db"
    app = _make_auth_app(db, allow_localhost=False)
    c = TestClient(app)
    r = c.get("/api/agents/profiles", headers={"x-grace-api-token": "test-token-42"})
    assert r.status_code == 200
