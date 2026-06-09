import pytest
from fastapi.testclient import TestClient
from grace_control.api.app_factory import create_app
from grace_control.config.settings import GraceSettings

def test_openapi_schema_contains_dev_replay_endpoints():
    settings = GraceSettings()
    # Ensure it's registered in OpenAPI regardless of runtime enable flags
    app = create_app(settings)
    client = TestClient(app)
    
    r = client.get("/openapi.json")
    assert r.status_code == 200
    
    openapi = r.json()
    paths = openapi.get("paths", {})
    
    # Check that paths exist
    assert "/api/dev/runs/{run_id}/replay-acceptance" in paths
    assert "/api/dev/runs/{run_id}/rerun-verifier" in paths
    assert "/api/dev/runs/{run_id}/rerun-reviewer" in paths
    
    # Check that methods are POST
    assert "post" in paths["/api/dev/runs/{run_id}/replay-acceptance"]
    assert "post" in paths["/api/dev/runs/{run_id}/rerun-verifier"]
    assert "post" in paths["/api/dev/runs/{run_id}/rerun-reviewer"]
