import pytest
from fastapi import status
from fastapi.testclient import TestClient
from unittest.mock import patch

from grace_control.api.app_factory import create_app
from grace_control.config.settings import GraceSettings

@pytest.fixture
def client_disabled():
    settings = GraceSettings()
    settings.dev_tools_enabled = False
    
    with patch("grace_control.config.settings.settings", settings):
        app = create_app(settings)
        yield TestClient(app)

def test_replay_acceptance_disabled(client_disabled):
    r = client_disabled.post("/api/dev/runs/pkt_t-R01/replay-acceptance", json={"stage": "t0"})
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert "DEV_TOOLS_DISABLED" in r.json()["detail"]["error"]

def test_rerun_verifier_disabled(client_disabled):
    r = client_disabled.post("/api/dev/runs/pkt_t-R01/rerun-verifier", json={})
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert "DEV_TOOLS_DISABLED" in r.json()["detail"]["error"]

def test_rerun_reviewer_disabled(client_disabled):
    r = client_disabled.post("/api/dev/runs/pkt_t-R01/rerun-reviewer", json={})
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert "DEV_TOOLS_DISABLED" in r.json()["detail"]["error"]
