"""W14.2 — API token auth tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app as _app
from grace_control.config.settings import settings
from grace_control.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    db_url = f"sqlite:///{tmp_path}/auth_test.db"
    monkeypatch.setenv("GRACE_DB_URL", db_url)
    init_db(db_url)
    return TestClient(_app)


@pytest.fixture
def auth_app():
    """Patched app with auth enabled for test."""
    settings.api_auth_enabled = True
    settings.api_auth_token = "test-token-42"
    settings.api_auth_allow_unauthenticated_localhost = False
    from grace_control.api.app_factory import create_app
    app = create_app(settings)
    return app


@pytest.fixture
def auth_client(auth_app, tmp_path):
    db_url = f"sqlite:///{tmp_path}/auth_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return TestClient(auth_app)


def test_auth_disabled_still_works(client):
    """Default (auth off): existing API tests still pass."""
    r = client.get("/api/agents/profiles")
    assert r.status_code == 200


def test_auth_enabled_missing_token_returns_401(auth_client):
    r = auth_client.get("/api/agents/profiles")
    assert r.status_code == 401


def test_auth_enabled_wrong_token_returns_401(auth_client):
    r = auth_client.get("/api/agents/profiles", headers={"authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_auth_enabled_correct_token_passes(auth_client):
    r = auth_client.get("/api/agents/profiles", headers={"authorization": "Bearer test-token-42"})
    assert r.status_code == 200


def test_auth_enabled_health_is_public(auth_client):
    r = auth_client.get("/health")
    assert r.status_code == 200


def test_auth_enabled_x_grace_token_works(auth_client):
    r = auth_client.get("/api/agents/profiles", headers={"x-grace-api-token": "test-token-42"})
    assert r.status_code == 200
