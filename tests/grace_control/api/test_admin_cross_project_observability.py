# ############################################################################
# AI_HEADER: test_admin_cross_project_observability — Stage 03 Hub acceptance
# ROLE: Proves cross-project overview, events, logs, search, diagnostics and
#       attention using independent fake project-local APIs and a real Hub ASGI
#       application. No project database or filesystem is opened by the tests.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify Stage 03 service/router aggregation, isolation, ordering,
#          bounded continuation and operator attention contracts.
# inputs: Temporary project identities, immutable registry and fake clients.
# returns: Passing assertions for healthy, offline, malformed and concurrent
#          project responses.
# side_effects: Performs in-memory async API calls only.
# emitted_logs: None directly; service logs are captured by the test runner.
# error_behavior: Fails if one project corrupts another project's result or if
#                 a source timestamp/project attribution is lost.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _Barrier
#     methods:
#       - enter
#   - class: _FakeProjectClient
#     methods:
#       - get_health
#       - get_json
#   - function: test_overview_aggregates_healthy_projects_and_attention
#   - function: test_offline_project_is_partial_and_not_counted_as_zero
#   - function: test_default_overview_includes_disabled_without_remote_fanout
#   - function: test_health_only_diagnostics_are_partial_not_zero_aggregates
#   - function: test_events_forward_filters_order_and_continue_deterministically
#   - function: test_event_and_log_continuation_uses_each_project_prefix
#   - function: test_malformed_event_and_log_project_does_not_corrupt_healthy_data
#   - function: test_search_diagnostics_and_project_aware_routes
#   - function: test_search_project_metadata_survives_remote_search_failure
#   - function: test_fanout_concurrency_and_no_cross_project_cache
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("test_admin_cross_project_observability")


# START_BLOCK_FIXTURES
class _Barrier:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.entered = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()

    # START_FUNCTION_CONTRACT
    # name: enter
    # purpose: Hold a fake request until every expected project has entered.
    # inputs: None.
    # returns: None after the test releases the barrier.
    # side_effects: Updates in-memory counters/events.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def enter(self) -> None:
        self.entered += 1
        if self.entered >= self.expected:
            self.all_entered.set()
        await self.release.wait()


class _FakeProjectClient:
    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        health: dict[str, Any] | ProjectApiResult,
        barrier: _Barrier | None = None,
        offline: bool = False,
    ) -> None:
        self.payloads = payloads
        self.health = health
        self.barrier = barrier
        self.offline = offline
        self.calls: list[tuple[str, dict[str, list[str]]]] = []
        self.version = 0

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Return this fake project's independent health identity.
    # inputs: None.
    # returns: Health mapping or normalized transport error.
    # side_effects: Records calls and participates in the concurrency barrier.
    # emitted_logs: None.
    # error_behavior: Returns configured offline error without raising.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> dict[str, Any] | ProjectApiResult:
        self.calls.append(("health", {}))
        if self.barrier is not None:
            await self.barrier.enter()
        if self.offline:
            return ProjectApiResult(
                project_key="offline",
                ok=False,
                error_class="timeout",
                error="project timed out",
            )
        return self.health

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Return one fake project-local JSON endpoint and record its query.
    # inputs: path — project-local API path with optional query string.
    # returns: Endpoint payload or normalized transport error.
    # side_effects: Records path/query and increments the fake response version.
    # emitted_logs: None.
    # error_behavior: Offline mode returns a typed failure for every endpoint.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> dict[str, Any] | ProjectApiResult:
        parsed = urlsplit(path)
        query = parse_qs(parsed.query)
        self.calls.append((parsed.path, query))
        self.version += 1
        if self.offline:
            return ProjectApiResult(
                project_key="offline",
                ok=False,
                error_class="api_offline",
                error="project is offline",
            )
        payload = self.payloads.get(parsed.path)
        if callable(payload):
            payload = payload(query)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _entry(key: str, root: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "key": key,
        "name": key.title(),
        "enabled": enabled,
        "unix_user": f"user-{key}",
        "project_root": root,
        "api_url": f"http://{key}.example.test:8142",
        "description": f"{key} project",
        "tags": [key, "stage03"],
    }


def _registry(tmp_path, *, disabled: str | None = None) -> ProjectRegistry:
    return ProjectRegistry.from_mapping({
        "projects": [
            _entry("alpha", str(tmp_path / "alpha"), enabled=disabled != "alpha"),
            _entry("beta", str(tmp_path / "beta"), enabled=disabled != "beta"),
        ]
    })


def _payloads(key: str, root: str) -> tuple[dict[str, Any], dict[str, Any]]:
    event_rows = [
        {
            "id": f"{key}-event-1",
            "timestamp": "2026-08-10T10:00:00+00:00" if key == "alpha" else "2026-08-10T09:00:00+00:00",
            "event_type": "packet_failed" if key == "alpha" else "packet_done",
            "entity_type": "packet",
            "entity_id": f"pkt-{key}",
            "trace_id": f"trace-{key}",
            "payload_json": {"component": "worker", "reason": f"{key}-reason", "full": {"n": 1}},
        },
        {
            "id": f"{key}-event-2",
            "timestamp": "2026-08-09T10:00:00+00:00",
            "event_type": "packet_started",
            "entity_type": "packet",
            "entity_id": f"pkt-{key}",
            "trace_id": f"trace-{key}",
            "payload": {"component": "worker", "reason": "started"},
        },
        {
            "id": f"{key}-event-3",
            "timestamp": "2026-08-08T10:00:00+00:00",
            "event_type": "packet_wait",
            "entity_type": "packet",
            "entity_id": f"pkt-{key}",
            "trace_id": f"trace-{key}",
            "payload": {"reason": "wait"},
        },
    ]
    snapshot = {
        "packets_by_state": {"BLOCKED_FINAL": 1, "done": 2} if key == "alpha" else {"done": 3},
        "features_by_status": {"DONE": 1},
        "workers": {"total": 2, "idle": 1, "busy": 1},
        "runs_total": 3,
        "ordinary_leases": [{"packet_id": f"pkt-{key}", "worker_id": f"worker-{key}"}],
        "active_parallel_leases": [{"packet_id": f"pkt-{key}", "conflict_keys": [f"db:{key}"]}],
        "active_parallel_lease_count": 1,
        "active_merge_leases": [{"packet_id": f"pkt-{key}", "worker_id": f"worker-{key}"}],
        "active_merge_lease_holder": {"packet_id": f"pkt-{key}", "worker_id": f"worker-{key}"},
        "effective_max_concurrency": 2,
        "parallel_scope_guard": True,
        "merge_serialization": True,
        "stale_base_recheck": True,
        "waits": [],
    }
    health = {
        "status": "ok",
        "project_key": key,
        "project_name": key.title(),
        "project_root": root,
        "code_sha": f"sha-{key}",
        "version": "0.1.0",
        "db_ok": True,
        "api_alive": True,
    }
    payloads = {
        "/api/diagnostics/state": {"data": snapshot, "timestamp": "2026-08-10T10:00:00Z"},
        "/api/events": {"data": {"total": len(event_rows), "limit": 3, "offset": 0, "events": event_rows}},
        "/api/admin/system/logs": {
            "source": "worker",
            "lines": [
                {
                    "timestamp": "2026-08-10T10:01:00+00:00",
                    "level": "ERROR" if key == "alpha" else "INFO",
                    "component": "worker",
                    "packet_id": f"pkt-{key}",
                    "trace_id": f"trace-{key}",
                    "message": f"{key} log",
                },
                f'{{"timestamp":"2026-08-09T10:01:00+00:00","level":"INFO","message":"{key} json log"}}',
            ],
        },
        "/api/admin/search": {
            "results": [{"kind": "packet", "id": f"pkt-{key}", "title": f"{key} packet"}]
        },
    }
    return payloads, health


def _service(
    tmp_path,
    *,
    barrier: _Barrier | None = None,
    offline: str | None = None,
    disabled: str | None = None,
):
    registry = _registry(tmp_path, disabled=disabled)
    clients: dict[str, _FakeProjectClient] = {}
    for context in registry.list_projects():
        payloads, health = _payloads(context.key, str(context.project_root))
        clients[context.key] = _FakeProjectClient(
            payloads,
            health=health,
            barrier=barrier,
            offline=context.key == offline,
        )
    service = AdminCrossProjectService(
        registry,
        client_factory=lambda context: clients[context.key],
        max_concurrency=2,
    )
    return service, clients, registry


# END_BLOCK_FIXTURES


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_overview_aggregates_healthy_projects_and_attention
# purpose: Prove healthy project cards, aggregate packet/worker counts,
#          lease metadata, attribution and blocked attention classification.
# inputs: tmp_path — independent project roots.
# returns: None.
# side_effects: Performs bounded fake project API reads.
# emitted_logs: None.
# error_behavior: Fails on lost project identity, lease state or attention.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_overview_aggregates_healthy_projects_and_attention(tmp_path):
    service, _clients, _registry = _service(tmp_path)
    body = await service.get_projects_overview()
    assert body["coverage"] == {
        "projects_total": 2,
        "projects_responded": 2,
        "projects_failed": 0,
        "projects_disabled": 0,
        "projects_partial": 0,
        "partial": False,
    }
    assert {row["project_key"] for row in body["projects"]} == {"alpha", "beta"}
    assert body["aggregate"]["packets_by_state"]["done"] == 5
    assert body["aggregate"]["workers"]["total"] == 4
    assert body["projects"][0]["active_parallel_leases"]
    assert any(item["project_key"] == "alpha" and item["kind"] == "packet_state" for item in body["attention"])
    assert not any(item["project_key"] == "beta" and item["kind"] == "packet_state" for item in body["attention"])
    assert body["projects"][0]["latest_event"]["project_key"] in {"alpha", "beta"}


# START_FUNCTION_CONTRACT
# name: test_offline_project_is_partial_and_not_counted_as_zero
# purpose: Prove offline data is isolated, coverage is explicit and aggregate
#          counts include only the responding project.
# inputs: tmp_path — independent project roots.
# returns: None.
# side_effects: Performs fake transport calls.
# emitted_logs: None.
# error_behavior: Fails if offline is rendered as healthy zero-valued data.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_offline_project_is_partial_and_not_counted_as_zero(tmp_path):
    service, _clients, _registry = _service(tmp_path, offline="beta")
    body = await service.get_projects_overview()
    beta = next(row for row in body["projects"] if row["project_key"] == "beta")
    assert beta["status"] == "offline"
    assert beta["packets_by_state"] is None
    assert body["coverage"]["projects_responded"] == 1
    assert body["coverage"]["projects_failed"] == 1
    assert body["aggregate"]["projects_in_aggregate"] == 1
    assert any(error["project_key"] == "beta" for error in body["errors"])
    diagnostics = await service.get_diagnostics()
    assert diagnostics["coverage"]["projects_total"] == 2
    assert diagnostics["coverage"]["projects_responded"] == 1
    assert diagnostics["coverage"]["projects_failed"] == 1
    assert diagnostics["aggregate"]["projects_in_aggregate"] == 1


# START_FUNCTION_CONTRACT
# name: test_default_overview_includes_disabled_without_remote_fanout
# purpose: Prove disabled registry projects remain visible as disabled cards but
#          never receive a ProjectClient request in the default overview.
# inputs: tmp_path — enabled and disabled project roots.
# returns: None.
# side_effects: Performs one enabled fake project overview read.
# emitted_logs: None.
# error_behavior: Fails if disabled projects disappear or count as failures.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_default_overview_includes_disabled_without_remote_fanout(tmp_path):
    service, clients, _registry = _service(tmp_path, disabled="beta")
    body = await service.get_projects_overview()
    beta = next(row for row in body["projects"] if row["project_key"] == "beta")
    assert beta["status"] == "disabled"
    assert clients["beta"].calls == []
    assert body["coverage"]["projects_total"] == 2
    assert body["coverage"]["projects_responded"] == 1
    assert body["coverage"]["projects_failed"] == 0
    assert body["coverage"]["projects_disabled"] == 1
    assert body["aggregate"]["projects_in_aggregate"] == 1


# START_FUNCTION_CONTRACT
# name: test_health_only_diagnostics_are_partial_not_zero_aggregates
# purpose: Prove a health-only project snapshot remains visible but contributes
#          no unavailable diagnostic counters to global aggregates.
# inputs: tmp_path — two independent fake project APIs.
# returns: None.
# side_effects: Replaces only beta's diagnostics endpoint with a typed failure.
# emitted_logs: None.
# error_behavior: Fails if beta's missing counters become aggregate zeroes.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_health_only_diagnostics_are_partial_not_zero_aggregates(tmp_path):
    service, clients, _registry = _service(tmp_path)
    clients["beta"].payloads["/api/diagnostics/state"] = ProjectApiResult(
        project_key="beta",
        ok=False,
        error_class="api_offline",
        error="diagnostics unavailable",
    )
    body = await service.get_diagnostics()
    beta = next(row for row in body["snapshots"] if row["project_key"] == "beta")
    assert beta["diagnostics_available"] is False
    assert body["coverage"]["projects_responded"] == 2
    assert body["coverage"]["projects_failed"] == 0
    assert body["coverage"]["projects_partial"] == 1
    assert body["aggregate"]["projects_in_aggregate"] == 1
    assert body["aggregate"]["packets_by_state"] == {"BLOCKED_FINAL": 1, "done": 2}
    assert any(error["project_key"] == "beta" for error in body["errors"])


# START_FUNCTION_CONTRACT
# name: test_events_forward_filters_order_and_continue_deterministically
# purpose: Prove canonical filters reach each project, source timestamps remain
#          unchanged, rows merge newest-first and cursor continuation is stable.
# inputs: tmp_path — two independent fake event APIs.
# returns: None.
# side_effects: Performs two bounded event pages.
# emitted_logs: None.
# error_behavior: Fails on naive per-project pagination or filter loss.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_events_forward_filters_order_and_continue_deterministically(tmp_path):
    service, clients, _registry = _service(tmp_path)
    first = await service.query_events(
        project=["alpha", "beta"],
        entity_type="packet",
        event_type="packet%",
        trace_id="trace-alpha",
        since="2026-08-01T00:00:00+00:00",
        until="2026-08-11T00:00:00+00:00",
        limit=2,
    )
    assert [row["project_key"] for row in first["events"]] == ["alpha", "beta"]
    assert first["events"][0]["timestamp"] == "2026-08-10T10:00:00+00:00"
    assert first["events"][0]["payload_json"]["full"]["n"] == 1
    assert first["partial"] is True
    assert first["continuation"]["strategy"] == "bounded_offset"
    assert first["next_cursor"]
    alpha_event_calls = [query for path, query in clients["alpha"].calls if path == "/api/events"]
    assert alpha_event_calls[0]["entity_type"] == ["packet"]
    assert alpha_event_calls[0]["event_type"] == ["packet%"]
    assert alpha_event_calls[0]["trace_id"] == ["trace-alpha"]
    second = await service.query_events(
        project=["alpha", "beta"],
        entity_type="packet",
        event_type="packet%",
        trace_id="trace-alpha",
        since="2026-08-01T00:00:00+00:00",
        until="2026-08-11T00:00:00+00:00",
        limit=2,
        cursor=first["next_cursor"],
    )
    assert second["offset"] == 2
    assert second["events"][0]["timestamp"] == "2026-08-09T10:00:00+00:00"


# START_FUNCTION_CONTRACT
# name: test_event_and_log_continuation_uses_each_project_prefix
# purpose: Prove continuation traverses the merged bounded prefixes from both
#          projects instead of stopping at one project's cap.
# inputs: tmp_path — two independent APIs with more than one per-project cap.
# returns: None.
# side_effects: Performs bounded fake event and log reads over continuation pages.
# emitted_logs: None.
# error_behavior: Fails if rows from the second project become unreachable.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_event_and_log_continuation_uses_each_project_prefix(tmp_path):
    service, clients, _registry = _service(tmp_path)
    for key in ("alpha", "beta"):
        day = "2026-08-11" if key == "alpha" else "2026-08-10"
        clients[key].payloads["/api/events"] = {
            "data": {
                "total": 1001,
                "events": [
                    {
                        "id": f"{key}-event-{index}",
                        "timestamp": f"{day}T10:00:00+00:00",
                        "event_type": "packet_done",
                        "entity_type": "packet",
                        "entity_id": f"pkt-{key}",
                        "payload": {"index": index},
                    }
                    for index in range(1001)
                ],
            }
        }
        clients[key].payloads["/api/admin/system/logs"] = {
            "total": 5001,
            "source": "worker",
            "lines": [
                {
                    "timestamp": f"{day}T11:00:00+00:00",
                    "level": "INFO",
                    "message": f"{key}-{index}",
                }
                for index in range(5001)
            ],
        }

    event_page = await service.query_events(limit=200)
    for _index in range(5):
        assert event_page["next_cursor"]
        event_page = await service.query_events(limit=200, cursor=event_page["next_cursor"])
    assert event_page["offset"] == 1000
    assert any(row["project_key"] == "beta" for row in event_page["events"])
    assert event_page["next_cursor"]

    log_page = await service.query_logs(tail=500)
    for _index in range(10):
        assert log_page["next_cursor"]
        log_page = await service.query_logs(tail=500, cursor=log_page["next_cursor"])
    assert log_page["offset"] == 5000
    assert any(row["project_key"] == "beta" for row in log_page["logs"])
    assert log_page["next_cursor"]


# START_FUNCTION_CONTRACT
# name: test_malformed_event_and_log_project_does_not_corrupt_healthy_data
# purpose: Prove malformed responses become per-project errors while the other
#          project's events/logs remain normalized and usable.
# inputs: tmp_path — two independent fake APIs.
# returns: None.
# side_effects: Replaces only alpha's fake endpoint payloads.
# emitted_logs: None.
# error_behavior: Fails if malformed data becomes a global 500 or drops beta.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_malformed_event_and_log_project_does_not_corrupt_healthy_data(tmp_path):
    service, clients, _registry = _service(tmp_path)
    clients["alpha"].payloads["/api/events"] = {"data": {"events": "not-a-list"}}
    clients["alpha"].payloads["/api/admin/system/logs"] = {"lines": "not-a-list"}
    events = await service.query_events()
    logs = await service.query_logs()
    assert any(error["project_key"] == "alpha" and error["error_class"] == "malformed_response" for error in events["errors"])
    assert any(row["project_key"] == "beta" for row in events["events"])
    assert any(error["project_key"] == "alpha" and error["error_class"] == "malformed_response" for error in logs["errors"])
    assert any(row["project_key"] == "beta" and row["source"] == "worker" for row in logs["logs"])


# START_FUNCTION_CONTRACT
# name: test_search_diagnostics_and_project_aware_routes
# purpose: Prove canonical search links, per-project diagnostics/lease state,
#          attention behavior and real Hub route wiring.
# inputs: tmp_path — two independent fake project APIs.
# returns: None.
# side_effects: Performs service calls and in-memory ASGI requests.
# emitted_logs: None.
# error_behavior: Fails on lost project attribution or route isolation.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_search_diagnostics_and_project_aware_routes(tmp_path):
    service, clients, registry = _service(tmp_path)
    search = await service.search("packet")
    packet = next(row for row in search["results"] if row["kind"] == "packet")
    assert packet["project_key"] in {"alpha", "beta"}
    assert packet["target_url"].startswith(f"/admin/p/{packet['project_key']}/packet/")
    diagnostics = await service.get_diagnostics()
    assert {row["project_key"] for row in diagnostics["snapshots"]} == {"alpha", "beta"}
    assert {row["system_health"]["project_key"] for row in diagnostics["snapshots"]} == {"alpha", "beta"}
    alpha = await service.get_diagnostics("alpha")
    assert alpha["snapshot"]["active_parallel_leases"][0]["conflict_keys"] == ["db:alpha"]
    assert alpha["snapshot"]["active_merge_lease_holder"]["packet_id"] == "pkt-alpha"
    logs = await service.query_logs()
    assert {row["project_key"] for row in logs["logs"]} == {"alpha", "beta"}
    assert {row["source"] for row in logs["logs"]} >= {"worker"}

    app = create_app(
        project_registry=registry,
        project_client_factory=lambda context: clients[context.key],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hub.test") as client:
        response = await client.get("/api/admin-hub/search", params={"q": "packet"})
        diagnostics_response = await client.get("/api/admin-hub/projects/alpha/diagnostics")
    assert response.status_code == 200
    assert diagnostics_response.status_code == 200
    assert diagnostics_response.json()["project_key"] == "alpha"


# START_FUNCTION_CONTRACT
# name: test_search_project_metadata_survives_remote_search_failure
# purpose: Prove registry metadata search remains available when one project's
#          canonical search endpoint is unavailable.
# inputs: tmp_path — two independent fake project APIs.
# returns: None.
# side_effects: Replaces beta's search endpoint with a typed failure.
# emitted_logs: None.
# error_behavior: Fails if metadata is dropped with the remote error.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_search_project_metadata_survives_remote_search_failure(tmp_path):
    service, clients, _registry = _service(tmp_path)
    clients["beta"].payloads["/api/admin/search"] = ProjectApiResult(
        project_key="beta",
        ok=False,
        error_class="capability_unavailable",
        error="search unavailable",
        http_status=404,
    )
    body = await service.search("beta")
    assert any(row["kind"] == "project" and row["project_key"] == "beta" for row in body["results"])
    assert any(error["project_key"] == "beta" for error in body["errors"])


# START_FUNCTION_CONTRACT
# name: test_fanout_concurrency_and_no_cross_project_cache
# purpose: Prove two project requests enter a deterministic barrier concurrently
#          and repeated reads do not leak or cache one project's data into the other.
# inputs: tmp_path — two independent fake project APIs and barrier.
# returns: None.
# side_effects: Performs concurrent overview reads and a repeated diagnostics read.
# emitted_logs: None.
# error_behavior: Fails on serial fan-out or project-key cache leakage.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_fanout_concurrency_and_no_cross_project_cache(tmp_path):
    barrier = _Barrier(expected=2)
    service, clients, _registry = _service(tmp_path, barrier=barrier)
    task = asyncio.create_task(service.get_projects_overview())
    try:
        await asyncio.wait_for(barrier.all_entered.wait(), timeout=1)
        assert barrier.entered == 2
    finally:
        barrier.release.set()
    first = await task
    assert {row["project_key"] for row in first["projects"]} == {"alpha", "beta"}
    before_alpha = clients["alpha"].version
    before_beta = clients["beta"].version
    diagnostics = await service.get_diagnostics()
    assert {row["project_key"] for row in diagnostics["snapshots"]} == {"alpha", "beta"}
    assert clients["alpha"].version > before_alpha
    assert clients["beta"].version > before_beta
    alpha_only = await service.get_diagnostics("alpha")
    beta_only = await service.get_diagnostics("beta")
    assert alpha_only["snapshot"]["project_key"] == "alpha"
    assert beta_only["snapshot"]["project_key"] == "beta"
    assert alpha_only["snapshot"]["active_parallel_leases"][0]["conflict_keys"] == ["db:alpha"]
    assert beta_only["snapshot"]["active_parallel_leases"][0]["conflict_keys"] == ["db:beta"]


# END_BLOCK_ACCEPTANCE
