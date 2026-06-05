"""OpenAPI regression test for W1 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.

Asserts that the FastAPI app exposes the base runtime groups listed in
`docs/grace/API_FIRST_CONTROL_PLANE.md`. As W4 lands trace endpoints and
W5..W11 split out more routers, this test is extended to cover the
expanded surface.
"""
import os

import pytest
from httpx import ASGITransport, AsyncClient

from grace_control.api.main import app


BASE_RUNTIME_PATHS = {
    "/api/features",
    "/api/packets",
    "/api/workers",
    "/api/architect",
    "/api/recovery",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Per-test unique SQLite DB so lifespan can call init_db."""
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/openapi_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def test_openapi_document_is_served():
    """/openapi.json must be reachable and contain the basic OpenAPI fields."""
    from fastapi.testclient import TestClient
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    c = TestClient(app)
    resp = c.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("openapi", "").startswith("3.")
    assert "paths" in body
    assert "info" in body


def test_openapi_contains_base_runtime_groups():
    """Each base runtime group must be present in /openapi.json paths."""
    from fastapi.testclient import TestClient
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    c = TestClient(app)
    resp = c.get("/openapi.json")
    assert resp.status_code == 200
    paths = set(resp.json().get("paths", {}).keys())
    missing = {p for p in BASE_RUNTIME_PATHS if not any(path.startswith(p) for path in paths)}
    assert not missing, (
        f"Missing base runtime groups in OpenAPI: {missing}. "
        f"Found paths sample: {sorted(p for p in paths if p.startswith('/api/'))[:10]}"
    )


def test_openapi_path_count_increases_with_routers():
    """Sanity: the FastAPI app exposes more than the minimum set of paths.

    If a router is dropped accidentally, this catches the regression.
    """
    from fastapi.testclient import TestClient
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    c = TestClient(app)
    resp = c.get("/openapi.json")
    paths = resp.json().get("paths", {})
    assert len(paths) >= 5, f"OpenAPI has only {len(paths)} paths; expected >=5"
