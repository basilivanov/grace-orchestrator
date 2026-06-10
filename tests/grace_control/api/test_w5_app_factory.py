"""W5 acceptance tests for source/codex/tz-api-first-cleanup-waves-w0-w11.md §W5.

Asserts:
1. `api/main.py` is wiring-only (<150 lines) and contains no DB-aggregation.
2. `create_app()` is the entrypoint; main.py delegates to it.
3. Lifespan moved out of main.py into api/lifespan.py.
4. Artifact path traversal is still blocked.

NOTE: dashboard router/service tests were deleted in admin v2 (TZ_ADMIN_PANEL)
because the old dashboard was replaced with the new `/admin` SPA + `/api/admin/*`
API. See src/grace_control/api/routers/admin.py and tests/grace_control/api/test_admin_router.py.
"""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
MAIN_PY = ROOT / "src" / "grace_control" / "api" / "main.py"
APP_FACTORY = ROOT / "src" / "grace_control" / "api" / "app_factory.py"
LIFESPAN_PY = ROOT / "src" / "grace_control" / "api" / "lifespan.py"


# ── Structural assertions ────────────────────────────────────────────────────


def test_main_py_is_wiring_only():
    """main.py is <150 lines and contains no DB queries or business loops."""
    text = MAIN_PY.read_text()
    lines = text.splitlines()
    assert len(lines) < 150, f"main.py has {len(lines)} lines; W5 requires <150."
    assert "db.query" not in text, "main.py must not contain db.query calls"
    assert "asyncio.sleep" not in text
    assert "init_db(" not in text


def test_main_py_delegates_to_create_app():
    text = MAIN_PY.read_text()
    assert "from grace_control.api.app_factory import create_app" in text
    assert "app = create_app()" in text


def test_app_factory_wires_admin_router():
    text = APP_FACTORY.read_text()
    assert "admin.router" in text, "app_factory must include admin.router"
    assert "/api/admin" in text, "app_factory must expose /api/admin/* routes"
    # Admin SPA shell + static mount.
    assert "/admin" in text
    assert "StaticFiles" in text


def test_lifespan_moved_out_of_main_py():
    assert LIFESPAN_PY.exists()
    text = LIFESPAN_PY.read_text()
    assert "init_db(settings.database_url)" in text
    assert "lease_expiration_loop" in text
    assert "check_wave_gates" in text
    assert "check_feature_completion" in text
    assert "settings.wave_gate_interval_seconds" in text
    assert "settings.feature_gate_interval_seconds" in text


def test_artifact_path_traversal_blocked(tmp_path, monkeypatch):
    """`/api/packets/.../artifacts/file?path=../etc` must be 403, never 200."""
    from grace_control.api.main import app
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import (
        Feature, Packet, PacketRun, PacketState, Wave,
    )
    from datetime import UTC, datetime

    db_url = f"sqlite:///{tmp_path}/w5_traversal.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)

    # Build a packet/run with a real evidence directory inside tmp_path.
    evidence = tmp_path / "evidence" / "p1-1"
    evidence.mkdir(parents=True)
    (evidence / "log.txt").write_text("ok\n")
    with get_db() as db:
        db.add(Feature(id="F1", slug="f1", title="F1", spec_json={}, status="IN_PROGRESS"))
        db.add(Wave(id="W01", feature_id="F1", slug="w01", title="W01", order=1, status="IN_PROGRESS"))
        db.add(Packet(
            id="p1", feature_id="F1", wave_id="W01", slug="p1", title="p1",
            spec_json={}, state=PacketState.ACCEPTED.value,
            attempt_count=1, max_attempts=3, acceptance_profile="NORMAL",
        ))
        db.add(PacketRun(
            id="p1-1", packet_id="p1", run_number=1, status="accepted",
            evidence_path=str(evidence),
            started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            duration_ms=10,
        ))
        db.commit()

    client = TestClient(app)
    # Legit file — must succeed.
    r_ok = client.get("/api/packets/p1/runs/1/artifacts/file?path=log.txt")
    assert r_ok.status_code == 200, r_ok.text
    assert "ok" in r_ok.text
    # Traversal — must be forbidden.
    r_bad = client.get("/api/packets/p1/runs/1/artifacts/file?path=../../../../../etc/passwd")
    assert r_bad.status_code == 403, r_bad.text


def test_admin_routes_still_respond(tmp_path, monkeypatch):
    """Admin v2 endpoints answer 200 after the cutover from dashboard."""
    from grace_control.api.main import app
    db_url = f"sqlite:///{tmp_path}/w5_admin.db"
    os.environ["GRACE_DB_URL"] = db_url
    from grace_control.db import init_db
    init_db(db_url)
    client = TestClient(app)
    assert client.get("/api/admin/overview").status_code == 200
    assert client.get("/api/admin/system/health").status_code == 200
    assert client.get("/api/admin/system/workers").status_code == 200
    assert client.get("/api/admin/search").status_code == 200
    # Admin shell.
    r = client.get("/admin")
    assert r.status_code == 200
    assert "<html" in r.text


def test_openapi_contains_admin_endpoints():
    """All new admin endpoints must be in /openapi.json after v2 cutover."""
    from grace_control.api.main import app
    client = TestClient(app)
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    must_have = [
        "/api/admin/overview",
        "/api/admin/packet/{packet_id}/detail",
        "/api/admin/packet/{packet_id}/blocking_decision",
        "/api/admin/packet/{packet_id}/timeline",
        "/api/admin/packet/{packet_id}/runs",
        "/api/admin/packet/{packet_id}/sessions",
        "/api/admin/packet/{packet_id}/runs/{run_id}/artifacts",
        "/api/admin/packet/{packet_id}/runs/{run_id}/artifacts/file",
        "/api/admin/packet/{packet_id}/runs/{run_id}/logs",
        "/api/admin/feature/{feature_id}/summary",
        "/api/admin/search",
        "/api/admin/system/health",
        "/api/admin/system/workers",
        "/admin",
    ]
    for p in must_have:
        assert p in paths, f"OpenAPI missing {p}"
