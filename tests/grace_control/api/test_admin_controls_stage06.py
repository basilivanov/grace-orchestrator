# ############################################################################
# AI_HEADER: test_admin_controls_stage06 — Stage 06 mutation/security acceptance
# ROLE: Proves selected-project control isolation, auth/confirmation/origin
#       enforcement, unknown outcomes, masking and discovered API mutation gates.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Exercise the Stage 06 Hub control boundary deterministically with
#          two independent fake project runtimes.
# inputs: Immutable registry, ASGI app and fake project clients.
# returns: Pytest assertions for the required security/mutation contracts.
# side_effects: In-memory ASGI calls only; no project DB or filesystem mutation.
# emitted_logs: Runtime structured logs captured by the test runner.
# error_behavior: Fails on cross-project routing, fake success, secret leakage
#                 or missing server-side authorization/confirmation.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _MutationClient
#     methods:
#       - get_health
#       - get_json
#       - request_json
#   - function: test_read_token_cannot_mutate
#   - function: test_control_token_is_project_scoped_and_confirmed
#   - function: test_timeout_is_unknown_without_retry
#   - function: test_openapi_mutation_requires_discovery_and_control_mode
#   - function: test_masking_covers_nested_credentials_and_urls
#   - function: test_cross_origin_control_is_rejected
#   - function: test_local_control_requires_confirmation_and_audits
#   - function: test_maintenance_dry_run_keeps_live_worktrees
#   - function: test_api_get_selection_never_mutates
#   - function: test_strong_confirmation_requires_identity
#   - function: test_planned_mutation_is_unavailable
#   - function: test_supervisor_failure_stays_failed
#   - function: test_merge_wait_requires_state_verification
#   - function: test_maintenance_lease_safety_fails_closed
#   - function: test_control_center_form_preserves_openapi_path_parameters
#   - function: test_control_catalog_is_capability_and_state_aware
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.responses import JSONResponse

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import ProjectRegistry
from grace_control.config.settings import GraceSettings, settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, Feature, Packet, PacketState, Wave
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_maintenance_control_service import AdminMaintenanceControlService
from grace_control.services.admin_mutation_service import normalize_mutation_result
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("test_admin_controls_stage06")


# START_BLOCK_FIXTURES
class _MutationClient:
    """Independent project-local fake with one mutation ledger."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure one fake project's mutation response.
    # inputs: key and optional timeout mode.
    # returns: None.
    # side_effects: Initializes an in-memory call ledger.
    # emitted_logs: None.
    # error_behavior: Timeout mode returns a typed no-response result.
    # END_FUNCTION_CONTRACT
    def __init__(self, key: str, *, timeout: bool = False) -> None:
        self.key = key
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Return identity-matching project health for Hub construction.
    # inputs: None.
    # returns: Health mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Always returns this fake project's identity.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "project_key": self.key,
            "project_name": self.key.title(),
            "project_root": f"/srv/{self.key}",
        }

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Return capability/OpenAPI documents for this fake project.
    # inputs: path — project-local GET path.
    # returns: JSON mapping.
    # side_effects: Records selected-project reads.
    # emitted_logs: None.
    # error_behavior: Unknown reads return an empty mapping.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> dict[str, Any]:
        self.calls.append({"method": "GET", "path": path})
        if path == "/api/admin/capabilities":
            return {"capabilities": {"controls": ["retry", "cancel", "openapi_mutation"]}}
        if path == "/openapi.json":
            return {
                "openapi": "3.0.0",
                "paths": {
                    "/api/synthetic-mutation": {
                        "post": {"responses": {"200": {"description": "ok"}}},
                    },
                    "/api/items/{item_id}": {
                        "post": {
                            "parameters": [
                                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
                                {"name": "mode", "in": "query", "required": True, "schema": {"type": "string"}},
                            ],
                            "responses": {"200": {"description": "ok"}},
                        },
                    },
                },
            }
        if path.endswith("/detail"):
            return {"packet": {"id": "pkt-test", "state": "rejected"}}
        return {}

    # START_FUNCTION_CONTRACT
    # name: request_json
    # purpose: Record one selected-project mutation and return success or a
    #          typed timeout without performing a retry.
    # inputs: path, method and JSON payload.
    # returns: ProjectApiResult.
    # side_effects: Appends one in-memory call.
    # emitted_logs: None.
    # error_behavior: Timeout mode returns error_class timeout with no status.
    # END_FUNCTION_CONTRACT
    async def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> ProjectApiResult:
        self.calls.append({"method": method, "path": path, "payload": payload or {}})
        if self.timeout:
            return ProjectApiResult(
                project_key=self.key,
                ok=False,
                error_class="timeout",
                error="project did not answer",
            )
        return ProjectApiResult(
            project_key=self.key,
            ok=True,
            payload={"ok": True, "project_key": self.key, "secret": "not rendered"},
            http_status=200,
        )


# START_FUNCTION_CONTRACT
# name: _registry
# purpose: Build two immutable project contexts for isolation tests.
# inputs: None.
# returns: ProjectRegistry.
# side_effects: None.
# error_behavior: Configuration is deterministic and valid.
# END_FUNCTION_CONTRACT
def _registry() -> ProjectRegistry:
    return ProjectRegistry.from_mapping({
        "projects": [
            {
                "key": "alpha", "name": "Alpha", "enabled": True,
                "unix_user": "grace-alpha", "project_root": "/srv/alpha",
                "api_url": "http://alpha.example.test",
            },
            {
                "key": "beta", "name": "Beta", "enabled": True,
                "unix_user": "grace-beta", "project_root": "/srv/beta",
                "api_url": "http://beta.example.test",
            },
        ]
    })


# START_FUNCTION_CONTRACT
# name: _client_app
# purpose: Build an authenticated ASGI app with independent fake clients.
# inputs: optional timeout project key.
# returns: (app, clients) pair.
# side_effects: None beyond app construction.
# emitted_logs: None.
# error_behavior: Never raises for valid test configuration.
# END_FUNCTION_CONTRACT
def _client_app(*, timeout_key: str | None = None):
    clients = {
        key: _MutationClient(key, timeout=key == timeout_key)
        for key in ("alpha", "beta")
    }
    settings = GraceSettings(
        api_auth_enabled=True,
        api_auth_token="read-token",
        api_auth_control_token="control-token",
        api_auth_allow_unauthenticated_localhost=False,
    )
    app = create_app(
        settings,
        project_registry=_registry(),
        project_client_factory=lambda context: clients[context.key],
    )
    return app, clients


# END_BLOCK_FIXTURES


# START_FUNCTION_CONTRACT
# name: _set_runtime_identity
# purpose: Bind a deterministic local runtime identity to an app used by direct
#          project-local endpoint tests.
# inputs: app and project key.
# returns: None.
# side_effects: Updates only the in-memory FastAPI app state.
# emitted_logs: None.
# error_behavior: Valid test keys are stored as supplied.
# END_FUNCTION_CONTRACT
def _set_runtime_identity(app: Any, key: str = "alpha") -> None:
    app.__dict__["state"].runtime_identity = {
        "project_key": key,
        "project_name": key.title(),
        "project_root": f"/srv/{key}",
    }


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_read_token_cannot_mutate
# purpose: Prove a valid read token is rejected at the server-side control gate.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI POST.
# emitted_logs: Auth failure/forbidden logs.
# error_behavior: Fails if read access can invoke mutation.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_read_token_cannot_mutate():
    app, clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "read-token"},
            json={
                "action": "retry", "entity_type": "packet", "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 403
    assert clients["alpha"].calls == []


# START_FUNCTION_CONTRACT
# name: test_read_token_cannot_reach_legacy_admin_mutations
# purpose: Inventory every live project-local /api/admin mutation and prove a
#          read-only credential is rejected before any legacy route can change
#          packet, feature, worker or audit state.
# inputs: db — isolated project database.
# returns: None.
# side_effects: In-memory authenticated ASGI POSTs, followed by one confirmed
#               canonical legacy retry and feature archive.
# emitted_logs: Auth/control and canonical admin audit logs.
# error_behavior: Fails if an alternate legacy URL accepts read access or if a
#                 confirmed legacy-compatible route bypasses canonical audit.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_read_token_cannot_reach_legacy_admin_mutations(db):
    with get_db() as session:
        session.add(Feature(
            id="feat-legacy", slug="feat-legacy", title="legacy",
            spec_json={}, status="NOT_STARTED",
        ))
        session.add(Wave(
            id="wave-legacy", feature_id="feat-legacy", slug="wave-legacy",
            title="legacy", order=1,
        ))
        session.add(Packet(
            id="pkt-legacy", feature_id="feat-legacy", wave_id="wave-legacy",
            slug="pkt-legacy", title="legacy", spec_json={},
            state=PacketState.BLOCKED_RECOVERABLE.value,
            attempt_count=0, max_attempts=3,
        ))
        session.commit()

    app, _clients = _client_app()
    _set_runtime_identity(app)
    mutating_paths = sorted(
        path
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/admin/")
        and any(method in operations for method in ("post", "put", "patch", "delete"))
    )
    expected_paths = {
        "/api/admin/feature/{feature_id}/archive",
        "/api/admin/feature/{feature_id}/unarchive",
        "/api/admin/packet/{packet_id}/resume",
        "/api/admin/packet/{packet_id}/delete",
        "/api/admin/packet/{packet_id}/stop",
        "/api/admin/packet/{packet_id}/retry",
        "/api/admin/packet/{packet_id}/cancel",
        "/api/admin/packet/{packet_id}/stages/{stage_key}/rerun",
        "/api/admin/workers/{worker_id}/stop",
        "/api/admin/packet/{packet_id}/dev-replay",
        "/api/admin/stages/metrics/recompute",
        "/api/admin/control/action",
        "/api/admin/control/openapi",
        "/api/admin/maintenance/cleanup",
    }
    assert expected_paths <= set(mutating_paths)

    before = {
        "packet": PacketState.BLOCKED_RECOVERABLE.value,
        "feature": "NOT_STARTED",
    }
    with get_db() as session:
        assert session.query(Packet).filter_by(id="pkt-legacy").one().state == before["packet"]
        assert session.query(Feature).filter_by(id="feat-legacy").one().status == before["feature"]
        before_event_count = session.query(Event).count()

    replacements = {
        "{feature_id}": "feat-legacy",
        "{packet_id}": "pkt-legacy",
        "{stage_key}": "verifier",
        "{worker_id}": "worker-legacy",
        "{target}": "api",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        for template in mutating_paths:
            path = template
            for placeholder, value in replacements.items():
                path = path.replace(placeholder, value)
            assert "{" not in path and "}" not in path
            response = await client.post(
                path,
                headers={"x-grace-api-token": "read-token"},
                json={},
            )
            assert response.status_code == 403, path

    with get_db() as session:
        assert session.query(Packet).filter_by(id="pkt-legacy").one().state == before["packet"]
        assert session.query(Feature).filter_by(id="feat-legacy").one().status == before["feature"]
        assert session.query(Event).count() == before_event_count

    headers = {"x-grace-api-token": "control-token"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        retry = await client.post(
            "/api/admin/packet/pkt-legacy/resume",
            headers=headers,
            json={"confirmation": {"intent": "confirm"}},
        )
        archive = await client.post(
            "/api/admin/feature/feat-legacy/archive",
            headers=headers,
            json={"confirmation": {"intent": "confirm"}},
        )
    assert retry.status_code == 200 and retry.json()["ok"] is True
    assert archive.status_code == 200 and archive.json()["ok"] is True
    with get_db() as session:
        assert session.query(Packet).filter_by(id="pkt-legacy").one().state == PacketState.READY.value
        assert session.query(Feature).filter_by(id="feat-legacy").one().status == "ARCHIVED"
        audit_types = {
            row.event_type
            for row in session.query(Event).filter(Event.event_type.like("admin_action_%"))
        }
    assert {"admin_action_requested", "admin_action_completed"} <= audit_types


# START_FUNCTION_CONTRACT
# name: test_control_token_is_project_scoped_and_confirmed
# purpose: Prove confirmation, request identity and selected-project isolation.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI POSTs to one fake project.
# emitted_logs: Mutation service structured logs.
# error_behavior: Fails on missing confirmation or cross-project calls.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_token_is_project_scoped_and_confirmed():
    app, clients = _client_app()
    headers = {"x-grace-api-token": "control-token"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        missing = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers=headers,
            json={"action": "retry", "entity_type": "packet", "entity_id": "pkt-test"},
        )
        success = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers=headers,
            json={
                "action": "retry", "entity_type": "packet", "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "CONFIRMATION_REQUIRED"
    assert success.status_code == 200
    assert success.json()["project_key"] == "alpha"
    assert success.json()["request_id"].startswith("admin-")
    assert len(clients["alpha"].calls) == 1
    assert clients["beta"].calls == []


# START_FUNCTION_CONTRACT
# name: test_timeout_is_unknown_without_retry
# purpose: Prove a remote timeout yields the exact unknown outcome and one
#          transport call, never a guessed success or automatic retry.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI POST.
# emitted_logs: Mutation failure/unknown logs.
# error_behavior: Fails if timeout is retried or reported as success.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_timeout_is_unknown_without_retry():
    app, clients = _client_app(timeout_key="alpha")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "control-token"},
            json={
                "action": "retry", "entity_type": "packet", "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    data = response.json()
    assert response.status_code == 504
    assert data["result"] == "unknown_after_timeout"
    assert data["display_message"] == "UNKNOWN OUTCOME — verify project state before retrying"
    assert data["retry_allowed"] is False
    assert len(clients["alpha"].calls) == 1


# START_FUNCTION_CONTRACT
# name: test_openapi_mutation_requires_discovery_and_control_mode
# purpose: Prove arbitrary OpenAPI paths are rejected and a discovered
#          mutation requires explicit control mode plus confirmation.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI POSTs and one fake discovery read.
# emitted_logs: Mutation validation logs.
# error_behavior: Fails if arbitrary URL/method executes.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_openapi_mutation_requires_discovery_and_control_mode():
    app, clients = _client_app()
    headers = {"x-grace-api-token": "control-token"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        arbitrary = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={"control_mode": True, "path": "//other-host/delete", "method": "POST", "confirmation": {"intent": "confirm", "value": "//other-host/delete"}},
        )
        disabled = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={"path": "/api/synthetic-mutation", "method": "POST", "confirmation": {"intent": "confirm", "value": "/api/synthetic-mutation"}},
        )
        known = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={"control_mode": True, "path": "/api/synthetic-mutation", "method": "POST", "confirmation": {"intent": "confirm", "value": "/api/synthetic-mutation"}},
        )
        parameterized = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={
                "control_mode": True,
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"item_id": "item-7", "mode": "safe"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
        missing = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={
                "control_mode": True,
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"mode": "safe"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
        undeclared = await client.post(
            "/api/admin-hub/projects/alpha/openapi-control",
            headers=headers,
            json={
                "control_mode": True,
                "path": "/api/items/{item_id}",
                "method": "POST",
                "parameters": {"item_id": "item-7", "mode": "safe", "evil": "x"},
                "confirmation": {"intent": "confirm", "value": "/api/items/{item_id}"},
            },
        )
    assert arbitrary.status_code == 400
    assert disabled.status_code == 400
    assert disabled.json()["error_code"] == "API_CONTROL_MODE_REQUIRED"
    assert known.status_code == 200
    assert parameterized.status_code == 200
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "API_PATH_PARAM_REQUIRED"
    assert undeclared.status_code == 400
    assert undeclared.json()["error_code"] == "API_PARAMS_UNDECLARED"
    parameterized_calls = [
        call for call in clients["alpha"].calls
        if call.get("path") == "/api/admin/control/openapi"
        and call.get("payload", {}).get("path") == "/api/items/{item_id}"
    ]
    assert parameterized_calls[-1]["payload"]["parameters"] == {"item_id": "item-7", "mode": "safe"}
    assert any(call.get("path") == "/openapi.json" for call in clients["alpha"].calls)


# START_FUNCTION_CONTRACT
# name: test_control_center_form_preserves_openapi_path_parameters
# purpose: Prove the Control Center mutation branch forwards both declared
#          path and query values into the selected-project mutation payload.
# inputs: None.
# returns: None.
# side_effects: In-memory authenticated form request and fake mutation ledger.
# emitted_logs: Mutation service logs.
# error_behavior: Fails if the UI drops the path placeholder before dispatch.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_center_form_preserves_openapi_path_parameters():
    app, clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/admin/p/alpha/api/control",
            headers={"x-grace-api-token": "control-token"},
            data={
                "path": "/api/items/{item_id}",
                "execute": "true",
                "params": '{"item_id":"item-7","mode":"safe"}',
                "method": "POST",
                "control_mode": "true",
                "body": "{}",
                "confirmation": '{"intent":"confirm","value":"/api/items/{item_id}"}',
            },
        )
    assert response.status_code == 200
    calls = [
        call for call in clients["alpha"].calls
        if call.get("path") == "/api/admin/control/openapi"
    ]
    assert calls[-1]["payload"]["parameters"] == {"item_id": "item-7", "mode": "safe"}
    assert "/api/items/item-7" in response.text


# START_FUNCTION_CONTRACT
# name: test_masking_covers_nested_credentials_and_urls
# purpose: Prove case-insensitive nested names, URL userinfo, headers and
#          fencing/private-key material are masked before display/audit.
# inputs: None.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if any secret survives serialized output.
# END_FUNCTION_CONTRACT
def test_masking_covers_nested_credentials_and_urls():
    masked = mask_operator_data({
        "Authorization": "Bearer top-secret",
        "nested": [{
            "BOT_TOKEN": "bot-secret",
            "apiKey": "camel-case-secret",
            "url": "https://user:pass@example.test/api?token=query-secret",
        }],
        "PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----secret-----END PRIVATE KEY-----",
        "fencing_token": "fence-secret",
    })
    text = repr(masked)
    assert "top-secret" not in text
    assert "bot-secret" not in text
    assert "camel-case-secret" not in text
    assert "user:pass" not in text
    assert "query-secret" not in text
    assert "fence-secret" not in text
    assert masked["PRIVATE_KEY"] == "***"


# START_FUNCTION_CONTRACT
# name: test_cross_origin_control_is_rejected
# purpose: Prove an authenticated browser mutation with a foreign Origin is
#          rejected before the selected project transport.
# inputs: None.
# returns: None.
# side_effects: In-memory ASGI POST.
# emitted_logs: Origin rejection response.
# error_behavior: Fails if cross-origin control reaches a project client.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_cross_origin_control_is_rejected():
    app, clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "control-token", "origin": "https://evil.example"},
            json={
                "action": "retry", "entity_type": "packet", "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm"},
            },
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CSRF_ORIGIN_DENIED"
    assert clients["alpha"].calls == []


# START_FUNCTION_CONTRACT
# name: test_local_control_requires_confirmation_and_audits
# purpose: Prove the project-local dispatcher rechecks confirmation and writes
#          requested/completed audit events around PacketService.retry.
# inputs: db — initialized isolated SQLite session.
# returns: None.
# side_effects: In-memory local packet transition and Event inserts.
# emitted_logs: Packet/domain logs.
# error_behavior: Fails if direct local control bypasses confirmation/audit.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_local_control_requires_confirmation_and_audits(db):
    with get_db() as session:
        session.add(Feature(id="feat-local", slug="feat-local", title="local", spec_json={}, status="NOT_STARTED"))
        session.add(Wave(id="wave-local", feature_id="feat-local", slug="wave-local", title="local", order=1))
        session.add(Packet(
            id="pkt-local", feature_id="feat-local", wave_id="wave-local", slug="pkt-local",
            title="local", spec_json={}, state=PacketState.REJECTED.value,
            attempt_count=0, max_attempts=3,
        ))
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        rejected = await client.post(
            "/api/admin/control/action",
            json={"project_key": "alpha", "action": "retry", "entity_type": "packet", "entity_id": "pkt-local"},
        )
        completed = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "alpha", "action": "retry", "entity_type": "packet", "entity_id": "pkt-local",
                "request_id": "admin-local-1", "confirmation": {"intent": "confirm"},
            },
        )
    assert rejected.status_code == 400
    assert completed.status_code == 200
    with get_db() as session:
        packet = session.query(Packet).filter_by(id="pkt-local").one()
        events = session.query(Event).filter(Event.event_type.in_(
            ("admin_action_requested", "admin_action_completed", "admin_action_failed")
        )).all()
    assert packet.state == PacketState.READY.value
    assert {event.event_type for event in events} == {"admin_action_requested", "admin_action_completed", "admin_action_failed"}
    assert all(event.payload_json.get("project_key") == "alpha" for event in events)
    assert any(event.payload_json.get("request_id") == "admin-local-1" for event in events)


# START_FUNCTION_CONTRACT
# name: test_maintenance_dry_run_keeps_live_worktrees
# purpose: Prove project-local dry-run cleanup reports terminal candidates but
#          preserves live ownership and performs no filesystem mutation.
# inputs: db and tmp_path — isolated packet/roots.
# returns: None.
# side_effects: Reads local DB and temporary directory metadata only.
# emitted_logs: Maintenance and audit logs.
# error_behavior: Fails if dry-run deletes or selects a live worktree.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_maintenance_dry_run_keeps_live_worktrees(db, tmp_path: Path):
    with get_db() as session:
        session.add_all([
            Packet(id="pkt-live", feature_id="f", wave_id="w", slug="pkt-live", title="live", spec_json={}, state=PacketState.RUNNING.value),
            Packet(id="pkt-dead", feature_id="f", wave_id="w", slug="pkt-dead", title="dead", spec_json={}, state=PacketState.FAILED.value),
        ])
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    live = worktree_root / "pkt-live-attempt-0001"
    dead = worktree_root / "pkt-dead-attempt-0001"
    live.mkdir()
    dead.mkdir()
    (live / "live.txt").write_text("live")
    (dead / "dead.txt").write_text("dead")
    old_values = (settings.target_repo_root, settings.worktree_root, settings.state_root)
    settings.target_repo_root = str(tmp_path)
    settings.worktree_root = str(worktree_root)
    settings.state_root = str(tmp_path / "state")
    try:
        app = create_app(
            GraceSettings(api_auth_enabled=False),
            project_registry=_registry(),
            project_client_factory=lambda _context: _MutationClient("alpha"),
        )
        _set_runtime_identity(app)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(
                "/api/admin/maintenance/cleanup",
                json={
                    "project_key": "alpha", "dry_run": True,
                    "confirmation": {"intent": "confirm", "value": "alpha"},
                },
            )
        data = response.json()
    finally:
        settings.target_repo_root, settings.worktree_root, settings.state_root = old_values
    assert response.status_code == 200
    assert data["response"]["dry_run"] is True
    assert "pkt-dead-attempt-0001" in data["response"]["deleted"]
    assert "pkt-live-attempt-0001" in data["response"]["kept"]
    assert live.exists() and dead.exists()


# START_FUNCTION_CONTRACT
# name: test_api_get_selection_never_mutates
# purpose: Prove the read-only API Explorer GET route cannot execute a selected
#          mutation even when a browser supplies mutation-looking query flags.
# inputs: None.
# returns: None.
# side_effects: Bounded in-memory project API reads only.
# emitted_logs: Project read logs.
# error_behavior: Fails if the local mutation proxy is called from GET.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_api_get_selection_never_mutates():
    app, clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/admin/p/alpha/api",
            headers={"x-grace-api-token": "control-token"},
            params={
                "path": "/api/synthetic-mutation",
                "method": "POST",
                "execute": "true",
                "control_mode": "true",
            },
        )
    assert response.status_code == 200
    assert not any(call.get("path") == "/api/admin/control/openapi" for call in clients["alpha"].calls)


# START_FUNCTION_CONTRACT
# name: test_strong_confirmation_requires_identity
# purpose: Prove a destructive packet action cannot use a generic confirmation
#          string in place of its packet/project identity.
# inputs: None.
# returns: None.
# side_effects: No project mutation transport.
# emitted_logs: Mutation validation logs.
# error_behavior: Fails if generic strong confirmation reaches a project.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_strong_confirmation_requires_identity():
    app, clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "control-token"},
            json={
                "action": "cancel",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm", "value": "confirm"},
            },
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == "CONFIRMATION_INVALID"
    assert clients["alpha"].calls == []


# START_FUNCTION_CONTRACT
# name: test_planned_mutation_is_unavailable
# purpose: Prove a project runtime's 501/planned response is rendered as an
#          unavailable failure rather than a successful control result.
# inputs: None.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if planned response is normalized as success.
# END_FUNCTION_CONTRACT
def test_planned_mutation_is_unavailable():
    result = normalize_mutation_result(
        ProjectApiResult(
            project_key="alpha",
            ok=False,
            payload={"detail": "planned for a later runtime"},
            error_class="http_error",
            error="project API returned HTTP 501",
            http_status=501,
        ),
        {
            "project_key": "alpha",
            "action": "cleanup",
            "entity_type": "project",
            "entity_id": None,
            "request_id": "admin-test-1",
            "actor": "operator",
        },
    )
    assert result["ok"] is False
    assert result["available"] is False
    assert result["error"] == "Not implemented / unavailable for this runtime"


# START_FUNCTION_CONTRACT
# name: test_supervisor_failure_stays_failed
# purpose: Prove a supervisor restart response marked failed is not converted
#          to a successful admin action.
# inputs: monkeypatch — fake supervisor endpoint.
# returns: None.
# side_effects: In-memory local control request only.
# emitted_logs: Admin action failure logs.
# error_behavior: Fails if failed supervisor state is reported as success.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_supervisor_failure_stays_failed(monkeypatch):
    async def failed_restart(_target: str) -> dict[str, Any]:
        return {"ok": False, "status": "failed", "error": "worker did not restart"}

    from grace_control.api.routers import admin_controls

    class _FailedLifecycle:
        async def restart(self, _target: str) -> dict[str, Any]:
            return await failed_restart(_target)

    monkeypatch.setattr(admin_controls, "build_lifecycle_service", _FailedLifecycle)
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "alpha",
                "action": "restart_all",
                "entity_type": "project",
                "confirmation": {"intent": "confirm", "value": "alpha"},
            },
        )
    assert response.status_code == 502
    assert response.json()["result"] == "failed"
    assert response.json()["ok"] is False


# START_FUNCTION_CONTRACT
# name: test_merge_wait_requires_state_verification
# purpose: Prove merge-slot WAIT is visible as a non-success outcome and never
#          invites a blind automatic retry.
# inputs: monkeypatch — fake project merge endpoint returning HTTP 202 WAIT.
# returns: None.
# side_effects: In-memory local control request and audit attempt.
# emitted_logs: Admin action failure logs.
# error_behavior: Fails if WAIT is rendered as success or retryable.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_merge_wait_requires_state_verification(monkeypatch):
    async def waiting_merge(_packet_id: str, _request: dict[str, Any]) -> JSONResponse:
        return JSONResponse(
            status_code=202,
            content={"state": "WAIT", "reason": "merge slot busy"},
        )

    from grace_control.api.routers import packets

    monkeypatch.setattr(packets, "merge_packet", waiting_merge)
    app = create_app(
        GraceSettings(api_auth_enabled=False),
        project_registry=_registry(),
        project_client_factory=lambda _context: _MutationClient("alpha"),
    )
    _set_runtime_identity(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/admin/control/action",
            json={
                "project_key": "alpha",
                "action": "merge",
                "entity_type": "packet",
                "entity_id": "pkt-test",
                "confirmation": {"intent": "confirm", "value": "pkt-test"},
            },
        )
    data = response.json()
    assert response.status_code == 202
    assert data["ok"] is False
    assert data["wait"] is True
    assert data["retry_allowed"] is False
    assert data["display_message"].startswith("WAIT —")


# START_FUNCTION_CONTRACT
# name: test_maintenance_lease_safety_fails_closed
# purpose: Prove active or malformed lease evidence keeps terminal-looking
#          packets out of the cleanup candidate state map.
# inputs: None.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if uncertain ownership is treated as cleanup-safe.
# END_FUNCTION_CONTRACT
def test_maintenance_lease_safety_fails_closed():
    service = AdminMaintenanceControlService()
    states = {"pkt-live": "FAILED", "pkt-stale": "FAILED"}
    leases = {
        "ordinary": [],
        "parallel": [{"packet_id": "pkt-live", "stale_candidate": False}],
        "merge": [],
    }
    assert service.safe_cleanup_packet_states(states, leases) == {"pkt-stale": "FAILED"}
    malformed = {"ordinary": [{"packet_id": None}], "parallel": [], "merge": []}
    assert service.safe_cleanup_packet_states(states, malformed) == {}


# START_FUNCTION_CONTRACT
# name: test_control_catalog_is_capability_and_state_aware
# purpose: Prove the selected project's advertised controls are intersected
#          with the current packet state before UI/API availability is exposed.
# inputs: None.
# returns: None.
# side_effects: In-memory selected-project capability/detail reads.
# emitted_logs: Hub read logs.
# error_behavior: Fails if an undiscovered or invalid-state action is offered.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_catalog_is_capability_and_state_aware():
    app, _clients = _client_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/api/admin-hub/projects/alpha/controls",
            headers={"x-grace-api-token": "read-token"},
            params={"entity_type": "packet", "entity_id": "pkt-test"},
        )
    assert response.status_code == 200
    actions = response.json()["control_actions"]
    assert actions["retry"] is True
    assert actions["cancel"] is True
    assert actions["merge"] is False


# END_BLOCK_ACCEPTANCE
