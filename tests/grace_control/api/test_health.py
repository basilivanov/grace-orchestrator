"""Tests for health endpoints — /health, /health/liveness, /health/readiness, /health/diagnostic."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from grace_control.db import init_db


@pytest.fixture
def client():
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    init_db("sqlite:///:memory:")
    from grace_control.api.main import app
    return TestClient(app)


class TestHealthLightweight:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_health_does_not_call_check_health(self, client):
        """Regression: /health must not call DB-backed check_health()."""
        import grace_control.core.health as health_mod
        original = health_mod.check_health
        def raiser(*a, **kw):
            raise RuntimeError("check_health should not be called from /health")
        health_mod.check_health = raiser
        try:
            r = client.get("/health")
            assert r.status_code == 200
        finally:
            health_mod.check_health = original


class TestHealthLiveness:
    def test_liveness_returns_ok(self, client):
        r = client.get("/health/liveness")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestHealthReadiness:
    def test_readiness_ok_when_db_initialized(self, client):
        r = client.get("/health/readiness")
        assert r.status_code == 200
        assert r.json() == {"status": "ready"}

    def test_readiness_503_when_no_db(self):
        os.environ["GRACE_CONTEXT_DISABLED"] = "true"
        from grace_control.db import engine as db_engine
        # Force engine to None for this test
        saved = db_engine
        import grace_control.db as db_mod
        db_mod.engine = None
        try:
            from grace_control.api.main import app
            c = TestClient(app)
            r = c.get("/health/readiness")
            assert r.status_code == 503
        finally:
            db_mod.engine = saved


class TestHealthDiagnostic:
    def test_diagnostic_returns_legacy_shape(self, client):
        r = client.get("/health/diagnostic")
        assert r.status_code == 200
        data = r.json()
        # Legacy fields from check_health()
        assert "status" in data
        assert "workers" in data
        assert "queue_depth" in data
        assert "running" in data
        assert "timestamp" in data
