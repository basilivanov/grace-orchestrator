# ############################################################################
# AI_HEADER: test_admin_controls_stage06_review — Stage 06 review regressions
# ROLE: Proves the four review blockers remain fail-closed: uncertain cleanup,
#       runtime identity routing, canonical audit integrity and OpenAPI paths.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Exercise deterministic Stage 06 review fixes against isolated fake
#          project runtimes and temporary maintenance roots.
# inputs: Shared Stage 06 fixtures, SQLite test DB and ASGI apps.
# returns: Pytest assertions for safety and mutation-boundary contracts.
# side_effects: Temporary directory cleanup, in-memory ASGI calls and Event rows.
# emitted_logs: Structured mutation/audit/maintenance logs captured by pytest.
# error_behavior: Fails on fail-open ownership, identity misbinding, silent
#                 audit loss or unsafe OpenAPI selector routing.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_malformed_lease_evidence_never_deletes_terminal_worktree
#   - function: test_misbinding_rejects_before_domain_mutation
#   - function: test_local_identity_cannot_be_forged
#   - function: test_audit_failure_before_dispatch_is_fail_closed
#   - function: test_audit_failure_after_dispatch_is_visible
#   - function: test_parameterized_local_openapi_mutation_materializes_once
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import Request

from grace_control.api.app_factory import create_app
from grace_control.config.settings import GraceSettings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event
from grace_control.services.admin_maintenance_control_service import AdminMaintenanceControlService
from grace_control.services.maintenance_service import MaintenanceService
from tests.grace_control.api.test_admin_controls_stage06 import (
    _MutationClient,
    _registry,
    _set_runtime_identity,
)

_log = GraceLogger("test_admin_controls_stage06_review")


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_malformed_lease_evidence_never_deletes_terminal_worktree
# purpose: Prove real destructive cleanup receives an empty safe-candidate map
#          when ownership evidence is malformed, while complete evidence still
#          permits ordinary stale cleanup.
# inputs: tmp_path — isolated maintenance roots.
# returns: None.
# side_effects: Creates/removes only temporary test directories.
# emitted_logs: Maintenance cleanup logs.
# error_behavior: Fails if uncertain ownership deletes a terminal worktree.
# END_FUNCTION_CONTRACT
def test_malformed_lease_evidence_never_deletes_terminal_worktree(tmp_path: Path):
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    uncertain = worktree_root / "pkt-uncertain-attempt-0001"
    complete = worktree_root / "pkt-complete-attempt-0001"
    uncertain.mkdir()
    complete.mkdir()
    service = MaintenanceService(
        state_root=tmp_path / "state",
        worktree_root=worktree_root,
        project_root=tmp_path,
    )
    control = AdminMaintenanceControlService()
    states = {"pkt-uncertain": "failed", "pkt-complete": "failed"}
    malformed = {"ordinary": [{"packet_id": None}], "parallel": [], "merge": []}
    safe_states = control.safe_cleanup_packet_states(states, malformed)
    result = service.cleanup_stale_worktrees(packet_states=safe_states, dry_run=False)
    assert result.worktrees_removed == []
    assert uncertain.exists()
    complete_result = service.cleanup_stale_worktrees(
        packet_states={"pkt-complete": "failed"},
        dry_run=False,
    )
    assert "pkt-complete-attempt-0001" in complete_result.worktrees_removed
    assert not complete.exists()


# START_FUNCTION_CONTRACT
# name: test_misbinding_rejects_before_domain_mutation
# purpose: Prove a registry alpha context wired to a beta-identifying runtime
#          fails identity preflight without sending a mutation request.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI control request and health read only.
# emitted_logs: Mutation identity rejection log.
# error_behavior: Fails if a misbound runtime can mutate selected project state.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_misbinding_rejects_before_domain_mutation():
    alpha_runtime = _MutationClient("beta")
    beta_runtime = _MutationClient("beta")
    settings_obj = GraceSettings(
        api_auth_enabled=True,
        api_auth_token="read-token",
        api_auth_control_token="control-token",
        api_auth_allow_unauthenticated_localhost=False,
    )
    app = create_app(
        settings_obj,
        project_registry=_registry(),
        project_client_factory=lambda context: {
            "alpha": alpha_runtime,
            "beta": beta_runtime,
        }[context.key],
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "control-token"},
            json={
                "action": "retry",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 409
    assert response.json()["error_code"] == "PROJECT_IDENTITY_MISMATCH"
    assert alpha_runtime.calls == []
    assert beta_runtime.calls == []


# START_FUNCTION_CONTRACT
# name: test_local_identity_cannot_be_forged
# purpose: Prove a direct authorized local caller cannot label an alpha runtime
#          audit or action as another project.
# inputs: db — isolated local Event database.
# returns: None.
# side_effects: In-memory local control request and Event query.
# emitted_logs: None.
# error_behavior: Fails if forged identity reaches audit or domain dispatch.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_local_identity_cannot_be_forged(db):
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app, "alpha")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "beta",
                "action": "retry",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 409
    with get_db() as session:
        assert session.query(Event).filter_by(event_type="admin_action_requested").count() == 0


# START_FUNCTION_CONTRACT
# name: test_audit_failure_before_dispatch_is_fail_closed
# purpose: Prove requested audit persistence failure prevents local domain
#          dispatch and returns an explicit audit-integrity result.
# inputs: db/monkeypatch — isolated DB and failing recorder.
# returns: None.
# side_effects: In-memory local control request only.
# emitted_logs: admin_audit_persist_failed.
# error_behavior: Fails if mutation runs without its requested audit event.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_audit_failure_before_dispatch_is_fail_closed(db, monkeypatch):
    from grace_control.api.routers import admin_controls

    dispatched: list[str] = []

    async def unexpected_dispatch(*_args, **_kwargs):
        dispatched.append("called")
        return {"changed": True}

    def failing_recorder(*_args, **_kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(admin_controls, "_dispatch_local_action", unexpected_dispatch)
    monkeypatch.setattr(admin_controls, "record_event", failing_recorder)
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app, "alpha")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "alpha",
                "action": "retry",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 503
    assert response.json()["error_code"] == "AUDIT_INTEGRITY_FAILURE"
    assert dispatched == []


# START_FUNCTION_CONTRACT
# name: test_audit_failure_after_dispatch_is_visible
# purpose: Prove completed audit persistence failure is surfaced after the
#          domain action rather than returned as ordinary success.
# inputs: db/monkeypatch — isolated DB, fake dispatch and recorder.
# returns: None.
# side_effects: In-memory local control dispatch and audit attempts.
# emitted_logs: admin_audit_persist_failed.
# error_behavior: Fails if post-action audit loss is hidden as success.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_audit_failure_after_dispatch_is_visible(db, monkeypatch):
    from grace_control.api.routers import admin_controls

    dispatched: list[str] = []
    attempts = {"count": 0}

    async def fake_dispatch(*_args, **_kwargs):
        dispatched.append("called")
        return {"changed": True}

    def fail_completed(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] >= 2:
            raise RuntimeError("audit store unavailable after mutation")

    monkeypatch.setattr(admin_controls, "_dispatch_local_action", fake_dispatch)
    monkeypatch.setattr(admin_controls, "record_event", fail_completed)
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app, "alpha")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "alpha",
                "action": "retry",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 503
    assert response.json()["error_code"] == "AUDIT_INTEGRITY_FAILURE"
    assert response.json()["mutation_outcome"]["ok"] is True
    assert dispatched == ["called"]


# START_FUNCTION_CONTRACT
# name: test_parameterized_local_openapi_mutation_materializes_once
# purpose: Prove a confirmed local OpenAPI mutation preserves declared path and
#          query values, while missing/undeclared selectors never reach route.
# inputs: db — isolated local Event database.
# returns: None.
# side_effects: In-memory same-app route calls and Event inserts.
# emitted_logs: Local admin audit events.
# error_behavior: Fails on lost path/query values or unsafe selector routing.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_parameterized_local_openapi_mutation_materializes_once(db):
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app, "alpha")
    route_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def item_route(item_id: str, mode: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        route_calls.append((item_id, mode, payload))
        return {"item_id": item_id, "mode": mode, "body": payload}

    app.add_api_route("/api/items/{item_id}", item_route, methods=["POST"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        success = await client.post(
            "/api/admin/control/openapi",
            json={
                "project_key": "alpha",
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"item_id": "item-7", "mode": "safe"},
                "body": {"value": "ok"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
        missing = await client.post(
            "/api/admin/control/openapi",
            json={
                "project_key": "alpha",
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"mode": "safe"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
        undeclared = await client.post(
            "/api/admin/control/openapi",
            json={
                "project_key": "alpha",
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"item_id": "item-7", "mode": "safe", "evil": "x"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
    success_body = success.json()["response"]["body"]
    assert success.status_code == 200
    assert success_body["item_id"] == "item-7"
    assert success_body["mode"] == "safe"
    assert success_body["body"] == {"value": "ok"}
    assert route_calls == [("item-7", "safe", {"value": "ok"})]
    assert missing.status_code == 400
    assert undeclared.status_code == 400


# END_BLOCK_ACCEPTANCE
