# ############################################################################
# AI_HEADER: test_admin_hub_project_foundation — Stage 01 Hub acceptance tests
# ROLE: Proves registry validation, immutable context isolation, bounded
#       project transport and failure-isolated Admin Hub API fan-out.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify TZ01 Admin Hub project foundation behavior with independent
#          fake project APIs and a real ASGI Hub application.
# inputs: Pytest temporary paths, fake clients and HTTPX ASGI transport.
# returns: Passing assertions for registry, client, service and router contracts.
# side_effects: Performs in-memory HTTP calls only; no project DB/filesystem access.
# emitted_logs: None directly; runtime logs are captured by the test runner.
# error_behavior: Fails on contract, isolation, resilience or secret leakage.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _FakeProjectApi
#     methods:
#       - get_health
#   - function: test_registry_parses_two_valid_projects
#   - function: test_duplicate_project_key_is_rejected
#   - function: test_invalid_project_configuration_is_rejected
#   - function: test_project_context_is_immutable_and_request_scoped
#   - function: test_disabled_project_is_listed_without_remote_request
#   - function: test_health_fanout_is_concurrent_and_isolated
#   - function: test_concurrent_hub_requests_keep_contexts_isolated
#   - function: test_identity_mismatch_is_degraded
#   - function: test_browser_dto_masks_transport_secrets
#   - function: test_project_client_decodes_health_and_rejects_malformed_json
#   - function: test_admin_hub_routes_have_required_namespace
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_project_service import AdminProjectService
from grace_control.services.project_client import ProjectApiResult, ProjectClient

_log = GraceLogger("test_admin_hub_project_foundation")


# START_BLOCK_FIXTURES
class _SharedCallBarrier:
    def __init__(self, expected: int = 2) -> None:
        self.expected = expected
        self.entered = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def _enter(self) -> None:
        self.entered += 1
        if self.entered >= self.expected:
            self.all_entered.set()
        await self.release.wait()


class _FakeProjectApi:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        result: ProjectApiResult | None = None,
        delay: float = 0,
        barrier: _SharedCallBarrier | None = None,
    ) -> None:
        self.payload = payload or {}
        self.result = result
        self.delay = delay
        self.barrier = barrier
        self.calls = 0
        self.active = 0
        self.max_active = 0

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Return one independent fake project's health payload.
    # inputs: None.
    # returns: Mapping or normalized ProjectApiResult.
    # side_effects: Records request count and active concurrency in memory.
    # emitted_logs: None.
    # error_behavior: Returns the configured failure result when provided.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> dict[str, Any] | ProjectApiResult:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.barrier is not None:
                await self.barrier._enter()
            await asyncio.sleep(self.delay)
            return self.result or self.payload
        finally:
            self.active -= 1


def _entry(
    key: str,
    root: str,
    *,
    name: str | None = None,
    enabled: bool = True,
    api_url: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": key,
        "name": name or key.title(),
        "enabled": enabled,
        "unix_user": f"user-{key}",
        "project_root": root,
        "api_url": api_url or f"http://{key}.example.test:8142",
        "description": f"{key} project",
        "tags": ["test", key],
    }
    if api_token is not None:
        entry["api_token"] = api_token
    return entry


def _registry(tmp_path, *, disabled: bool = False) -> ProjectRegistry:
    return ProjectRegistry.from_mapping({
        "projects": [
            _entry("alpha", str(tmp_path / "alpha")),
            _entry("beta", str(tmp_path / "beta"), enabled=not disabled),
        ]
    })


def _healthy_payload(key: str, root: str, name: str | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "project_key": key,
        "project_name": name or key.title(),
        "project_root": root,
        "code_sha": f"sha-{key}",
    }


# END_BLOCK_FIXTURES


# START_BLOCK_REGISTRY_TESTS
# START_FUNCTION_CONTRACT
# name: test_registry_parses_two_valid_projects
# purpose: Prove two independent valid registry entries parse into contexts.
# inputs: tmp_path — isolated test project-root identities.
# returns: None; assertions fail on invalid registry parsing.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if keys, roots or transports are not preserved.
# END_FUNCTION_CONTRACT
def test_registry_parses_two_valid_projects(tmp_path):
    registry = _registry(tmp_path)
    contexts = registry.list_projects()
    assert [context.key for context in contexts] == ["alpha", "beta"]
    assert contexts[0].project_root != contexts[1].project_root
    assert contexts[0].api_url != contexts[1].api_url


# START_FUNCTION_CONTRACT
# name: test_duplicate_project_key_is_rejected
# purpose: Prove duplicate keys are a configuration error, never last-one-wins.
# inputs: tmp_path — isolated project-root identity.
# returns: None; assertion passes when validation raises.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if duplicate project entries are silently accepted.
# END_FUNCTION_CONTRACT
def test_duplicate_project_key_is_rejected(tmp_path):
    entry = _entry("duplicate", str(tmp_path / "one"))
    duplicate = dict(entry)
    duplicate["project_root"] = str(tmp_path / "two")
    with pytest.raises(ProjectRegistryError, match="duplicate project key"):
        ProjectRegistry.from_mapping({"projects": [entry, duplicate]})


# START_FUNCTION_CONTRACT
# name: test_invalid_project_configuration_is_rejected
# purpose: Prove unsafe key/path and ambiguous transport configurations fail.
# inputs: tmp_path — isolated project-root identity.
# returns: None; assertions pass when each invalid mapping raises.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if invalid project config is accepted.
# END_FUNCTION_CONTRACT
def test_invalid_project_configuration_is_rejected(tmp_path):
    relative_root = _entry("alpha/beta", "relative/root")
    with pytest.raises(ProjectRegistryError):
        ProjectRegistry.from_mapping({"projects": [relative_root]})

    both_transports = _entry("alpha", str(tmp_path / "alpha"))
    both_transports["api_socket"] = "/run/grace/alpha.sock"
    with pytest.raises(ProjectRegistryError, match="exactly one"):
        ProjectRegistry.from_mapping({"projects": [both_transports]})

    no_transport = _entry("beta", str(tmp_path / "beta"))
    no_transport.pop("api_url")
    with pytest.raises(ProjectRegistryError, match="transport"):
        ProjectRegistry.from_mapping({"projects": [no_transport]})


# END_BLOCK_REGISTRY_TESTS


# START_BLOCK_ISOLATION_TESTS
# START_FUNCTION_CONTRACT
# name: test_project_context_is_immutable_and_request_scoped
# purpose: Prove concurrent project lookups retain distinct frozen contexts.
# inputs: tmp_path — isolated project roots.
# returns: None; assertions prove no selected-project global is used.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails on context leakage or mutation.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_project_context_is_immutable_and_request_scoped(tmp_path):
    registry = _registry(tmp_path)
    service = AdminProjectService(
        registry,
        client_factory=lambda context: _FakeProjectApi(
            _healthy_payload(context.key, str(context.project_root), context.name)
        ),
    )
    alpha, beta = await asyncio.gather(
        service.get_project_health("alpha"),
        service.get_project_health("beta"),
    )
    assert alpha["project_key"] == "alpha"
    assert beta["project_key"] == "beta"
    assert alpha["runtime"]["project_key"] != beta["runtime"]["project_key"]
    with pytest.raises(FrozenInstanceError):
        registry.get("alpha").key = "beta"


# START_FUNCTION_CONTRACT
# name: test_disabled_project_is_listed_without_remote_request
# purpose: Prove disabled projects remain visible but are skipped by default.
# inputs: tmp_path — isolated project roots.
# returns: None; assertions prove no disabled remote call.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if disabled project fan-out calls its API.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_disabled_project_is_listed_without_remote_request(tmp_path):
    registry = _registry(tmp_path, disabled=True)
    clients = {context.key: _FakeProjectApi() for context in registry.list_projects()}
    service = AdminProjectService(registry, client_factory=lambda context: clients[context.key])
    body = await service.list_projects()
    assert {project["key"] for project in body["projects"]} == {"alpha", "beta"}
    disabled = next(project for project in body["projects"] if project["key"] == "beta")
    assert disabled["status"] == "disabled"
    assert disabled["health_status"] == "disabled"
    assert clients["beta"].calls == 0


# START_FUNCTION_CONTRACT
# name: test_health_fanout_is_concurrent_and_isolated
# purpose: Prove fan-out overlaps independent APIs and retains healthy beta
#          when alpha returns a timeout. The shared barrier makes serial
#          execution fail deterministically before either call is released.
# inputs: tmp_path — isolated project roots.
# returns: None; assertions prove bounded concurrent isolation.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if one project aborts the complete health response.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_health_fanout_is_concurrent_and_isolated(tmp_path):
    registry = _registry(tmp_path)
    barrier = _SharedCallBarrier(expected=2)
    clients = {
        "alpha": _FakeProjectApi(
            result=ProjectApiResult(
                project_key="alpha",
                ok=False,
                error_class="timeout",
                error="connect/read timeout",
                last_attempt_at="now",
            ),
            barrier=barrier,
        ),
        "beta": _FakeProjectApi(
            _healthy_payload("beta", str(tmp_path / "beta")),
            barrier=barrier,
        ),
    }
    service = AdminProjectService(
        registry,
        client_factory=lambda context: clients[context.key],
        max_concurrency=2,
    )
    fanout_task = asyncio.create_task(service.get_projects_health())
    try:
        await asyncio.wait_for(barrier.all_entered.wait(), timeout=1)
        assert barrier.entered == 2
    finally:
        barrier.release.set()
    rows = await fanout_task
    assert clients["alpha"].calls == clients["beta"].calls == 1
    assert {row["project_key"] for row in rows} == {"alpha", "beta"}
    assert next(row for row in rows if row["project_key"] == "alpha")["status"] == "timeout"
    assert next(row for row in rows if row["project_key"] == "beta")["status"] == "online"


# END_BLOCK_ISOLATION_TESTS


# START_BLOCK_IDENTITY_AND_SECRET_TESTS
# START_FUNCTION_CONTRACT
# name: test_identity_mismatch_is_degraded
# purpose: Prove registry/runtime identity disagreement is reported, not rewritten.
# inputs: tmp_path — registry project root and a different runtime identity.
# returns: None; assertions inspect the degraded health DTO.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if mismatch is silently treated as online.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_identity_mismatch_is_degraded(tmp_path):
    registry = _registry(tmp_path)
    service = AdminProjectService(
        registry,
        client_factory=lambda context: _FakeProjectApi(
            _healthy_payload("other-project", str(context.project_root))
        ),
    )
    result = await service.get_project_health("alpha")
    assert result["status"] == "identity_mismatch"
    assert "other-project" in result["error"]
    assert registry.get("alpha").key == "alpha"


# START_FUNCTION_CONTRACT
# name: test_browser_dto_masks_transport_secrets
# purpose: Prove registry credentials, URL query secrets and runtime secrets
#          never appear in browser-facing project DTOs.
# inputs: tmp_path — isolated project root.
# returns: None; assertion scans serialized DTO.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if a token/password reaches the browser surface.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_browser_dto_masks_transport_secrets(tmp_path):
    entry = _entry(
        "alpha",
        str(tmp_path / "alpha"),
        api_url="https://alpha.example.test:8142/api?token=url-secret",
        api_token="transport-secret",
    )
    registry = ProjectRegistry.from_mapping({"projects": [entry]})
    service = AdminProjectService(
        registry,
        client_factory=lambda _context: _FakeProjectApi({
            "project_key": "alpha",
            "project_name": "Alpha",
            "project_root": str(tmp_path / "alpha"),
            "access_token": "runtime-secret",
        }),
    )
    body = await service.list_projects()
    encoded = str(body)
    assert "transport-secret" not in encoded
    assert "url-secret" not in encoded
    assert "runtime-secret" not in encoded
    assert body["projects"][0]["api_endpoint"] == "https://alpha.example.test:8142/api"


# END_BLOCK_IDENTITY_AND_SECRET_TESTS


# START_BLOCK_CLIENT_AND_ROUTE_TESTS
# START_FUNCTION_CONTRACT
# name: test_project_client_decodes_health_and_rejects_malformed_json
# purpose: Prove bounded ProjectClient JSON decoding and malformed response
#          normalization without raising through the Hub.
# inputs: None; HTTPX MockTransport supplies two independent responses.
# returns: None; assertions inspect normalized results.
# side_effects: Performs mock HTTP requests.
# emitted_logs: None.
# error_behavior: Fails if malformed JSON becomes an online health result.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_project_client_decodes_health_and_rejects_malformed_json():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.host == "good.example.test":
            return httpx.Response(200, json={"project_key": "good"})
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)
    good_context = ProjectRegistry.from_mapping({
        "projects": [_entry("good", "/srv/good", api_url="http://good.example.test")]
    }).get("good")
    bad_context = ProjectRegistry.from_mapping({
        "projects": [_entry("bad", "/srv/bad", api_url="http://bad.example.test")]
    }).get("bad")
    good = await ProjectClient(good_context, transport=transport).get_health()
    bad = await ProjectClient(bad_context, transport=transport).get_health()
    assert good.ok is True
    assert good.payload == {"project_key": "good"}
    assert bad.ok is False
    assert bad.error_class == "malformed_response"
    assert requests == ["/api/admin/system/health", "/api/admin/system/health"]


# START_FUNCTION_CONTRACT
# name: test_admin_hub_routes_have_required_namespace
# purpose: Prove all required Admin Hub routes expose isolated project DTOs.
# inputs: tmp_path — isolated project roots.
# returns: None; assertions inspect HTTP JSON responses.
# side_effects: Performs ASGI calls to the Hub only.
# emitted_logs: None.
# error_behavior: Fails if routes are missing, leak secrets or lose isolation.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_admin_hub_routes_have_required_namespace(tmp_path):
    registry = _registry(tmp_path)
    clients = {
        "alpha": _FakeProjectApi(_healthy_payload("alpha", str(tmp_path / "alpha"))),
        "beta": _FakeProjectApi(_healthy_payload("beta", str(tmp_path / "beta"))),
    }
    app = create_app(
        project_registry=registry,
        project_client_factory=lambda context: clients[context.key],
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://hub.test") as client:
        projects = await client.get("/api/admin-hub/projects")
        detail = await client.get("/api/admin-hub/projects/alpha")
        health = await client.get("/api/admin-hub/projects/beta/health")
        aggregate = await client.get("/api/admin-hub/health")
        identity = await client.get("/api/admin/project-identity")
        missing = await client.get("/api/admin-hub/projects/missing")
    assert projects.status_code == 200
    assert {item["key"] for item in projects.json()["projects"]} == {"alpha", "beta"}
    assert detail.status_code == 200
    assert detail.json()["key"] == "alpha"
    assert health.status_code == 200
    assert health.json()["project_key"] == "beta"
    assert aggregate.status_code == 200
    assert aggregate.json()["status"] == "online"
    assert identity.status_code == 200
    assert identity.json()["project_key"]
    assert identity.json()["ready"] is True
    assert missing.status_code == 404


# END_BLOCK_CLIENT_AND_ROUTE_TESTS


# START_BLOCK_HTTP_ISOLATION_TESTS
# START_FUNCTION_CONTRACT
# name: test_concurrent_hub_requests_keep_contexts_isolated
# purpose: Prove two simultaneous ASGI requests resolve independent project
#          contexts and runtime identities without shared selected-project state.
# inputs: tmp_path — isolated roots for two independent fake project APIs.
# returns: None; assertions inspect both concurrent Hub responses.
# side_effects: Performs concurrent in-memory ASGI requests.
# emitted_logs: None.
# error_behavior: Fails if either request leaks the other project's context.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_concurrent_hub_requests_keep_contexts_isolated(tmp_path):
    registry = _registry(tmp_path)
    barrier = _SharedCallBarrier(expected=2)
    clients = {
        "alpha": _FakeProjectApi(
            _healthy_payload("alpha", str(tmp_path / "alpha")),
            barrier=barrier,
        ),
        "beta": _FakeProjectApi(
            _healthy_payload("beta", str(tmp_path / "beta")),
            barrier=barrier,
        ),
    }
    app = create_app(
        project_registry=registry,
        project_client_factory=lambda context: clients[context.key],
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://hub.test",
    ) as client:
        alpha_task = asyncio.create_task(
            client.get("/api/admin-hub/projects/alpha/health")
        )
        beta_task = asyncio.create_task(
            client.get("/api/admin-hub/projects/beta/health")
        )
        try:
            await asyncio.wait_for(barrier.all_entered.wait(), timeout=1)
            assert barrier.entered == 2
        finally:
            barrier.release.set()
        alpha_response, beta_response = await asyncio.gather(alpha_task, beta_task)

    assert alpha_response.status_code == 200
    assert beta_response.status_code == 200
    alpha = alpha_response.json()
    beta = beta_response.json()
    assert alpha["project_key"] == "alpha"
    assert alpha["registry"]["key"] == "alpha"
    assert alpha["runtime"]["project_key"] == "alpha"
    assert beta["project_key"] == "beta"
    assert beta["registry"]["key"] == "beta"
    assert beta["runtime"]["project_key"] == "beta"
    assert "beta" not in str(alpha)
    assert "alpha" not in str(beta)


# END_BLOCK_HTTP_ISOLATION_TESTS
