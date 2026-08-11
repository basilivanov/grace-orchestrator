# ############################################################################
# AI_HEADER: test_admin_control_center_stage07_matrix — failure, scale and UI acceptance
# ROLE: Completes Stage 07 acceptance using the real topology fixture from the
#       companion module, covering failure isolation, bounded fan-out/cache and browser journeys.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Exercise the final Admin Hub failure matrix, representative-scale
#          behavior and desktop/mobile browser contract.
# inputs: Shared Stage 07 fixture/plugin and deterministic transport clients.
# returns: Passing acceptance assertions for resilience and UI safety.
# side_effects: Starts short-lived browser/Hub processes and makes fixture API calls.
# emitted_logs: Structured application logs are captured by pytest.
# error_behavior: Fails on rerouting, unbounded fan-out, cache leakage or UI context loss.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _FailureClient
#     methods:
#       - get_health
#       - get_json
#       - mutate_json
#   - function: test_stage07_failure_matrix_is_partial_and_never_reroutes
#   - function: test_stage07_performance_fanout_and_bounded_explorer
#   - function: test_stage07_browser_desktop_mobile_smoke
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from grace_control.config.project_registry import ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center import (
    _OPENAPI_CACHE_TTL_SECONDS,
    AdminControlCenterService,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.admin_project_service import AdminProjectService
from grace_control.services.project_client import ProjectApiResult
from tests.grace_control.api.test_admin_control_center_stage07 import (
    _CONTROL_PACKET_ID,
    _hub_app,
)

pytest_plugins = ("tests.grace_control.api.test_admin_control_center_stage07",)

_log = GraceLogger("test_admin_control_center_stage07_matrix")


# START_FUNCTION_CONTRACT
# name: _failure_registry
# purpose: Build a registry covering all required failure modes plus one
#          healthy project.
# inputs: root — temporary registry root.
# returns: ProjectRegistry.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Registry validation errors propagate.
# END_FUNCTION_CONTRACT
def _failure_registry(root: Path) -> ProjectRegistry:
    modes = ("healthy", "refused", "timeout", "http500", "malformed", "missing_capability", "mismatch")
    return ProjectRegistry.from_mapping({"projects": [
        {"key": mode, "name": mode.title(), "enabled": True,
         "project_root": str(root / mode), "api_url": f"http://{mode}.example.test"}
        for mode in modes
    ]})


# START_BLOCK_FAILURE_MATRIX
class _FailureClient:
    """Deterministic project-local transport failure matrix."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure one isolated failure mode and request ledger.
    # inputs: key — registry key; mode — healthy/refused/timeout/http500/
    #         malformed/missing_capability/mismatch.
    # returns: None.
    # side_effects: Initializes an in-memory request ledger.
    # emitted_logs: None.
    # error_behavior: Mode behavior is returned through ProjectApiResult.
    # END_FUNCTION_CONTRACT
    def __init__(self, key: str, mode: str) -> None:
        self.key = key
        self.mode = mode
        self.calls: list[dict[str, Any]] = []

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Return healthy identity or one explicit transport/identity failure.
    # inputs: None.
    # returns: Health mapping or ProjectApiResult.
    # side_effects: Records one health request.
    # emitted_logs: None.
    # error_behavior: Never raises; all failure modes are typed.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> dict[str, Any] | ProjectApiResult:
        self.calls.append({"method": "GET", "path": "health"})
        if self.mode in {"refused", "timeout", "http500", "malformed"}:
            return self._failure()
        runtime_key = "healthy" if self.mode == "mismatch" else self.key
        return {
            "status": "ok", "project_key": runtime_key,
            "project_name": runtime_key.title(), "target_head": f"head-{runtime_key}",
        }

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Return global-read payloads or typed failures for each mode.
    # inputs: path — project-local API path with optional query.
    # returns: JSON mapping or ProjectApiResult.
    # side_effects: Records the exact project-local read.
    # emitted_logs: None.
    # error_behavior: Failure modes never fall back to another project.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> dict[str, Any] | ProjectApiResult:
        route = urlsplit(path).path
        self.calls.append({"method": "GET", "path": route})
        if self.mode in {"refused", "timeout", "http500", "malformed"}:
            return self._failure()
        if self.mode == "missing_capability" and route == "/api/admin/capabilities":
            return ProjectApiResult(self.key, False, error_class="http_error", error="not found", http_status=404)
        if route == "/api/admin/system/health":
            return await self.get_health()
        if route == "/api/admin/features":
            return {"features": [{"id": f"feature-{self.key}", "title": f"Feature {self.key}", "waves": []}]}
        if route == "/api/events":
            return {"data": {"total": 1, "limit": 100, "offset": 0, "events": [{
                "id": f"event-{self.key}", "timestamp": "2026-08-11T10:00:00Z",
                "event_type": "healthy_event", "entity_type": "packet",
                "entity_id": f"packet-{self.key}", "trace_id": f"trace-{self.key}",
                "payload_json": {"reason": f"healthy-{self.key}"},
            }]}}
        if route == "/api/admin/system/logs":
            return {"lines": [{"project": self.key, "message": f"log-{self.key}"}], "total": 1, "source": "fixture"}
        if route == "/api/admin/search":
            return {"results": [{"kind": "packet", "id": f"packet-{self.key}", "title": f"Packet {self.key}"}]}
        if route == "/api/diagnostics/state":
            return {"data": {"packets_by_state": {"ready": 1}, "waits": [], "ordinary_leases": []}}
        if route == "/api/admin/capabilities":
            return {"capabilities": {"filesystem": True, "git_read": True, "api_explorer": True, "controls": ["retry"]}}
        if route == "/openapi.json":
            return {"openapi": "3.1.0", "paths": {"/api/synthetic": {"get": {"responses": {"200": {}}}}}}
        return {}

    # START_FUNCTION_CONTRACT
    # name: mutate_json
    # purpose: Record one selected-project mutation without rerouting it.
    # inputs: path, method, payload, request_id and actor.
    # returns: Typed failure or success for this project.
    # side_effects: Records the mutation call in this client only.
    # emitted_logs: None.
    # error_behavior: Failure modes return their own typed failure.
    # END_FUNCTION_CONTRACT
    async def mutate_json(
        self,
        path: str,
        *,
        method: str = "POST",
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        actor: str | None = None,
    ) -> ProjectApiResult:
        self.calls.append({"method": method, "path": path, "payload": payload or {}, "request_id": request_id, "actor": actor})
        if self.mode != "healthy":
            return self._failure()
        return ProjectApiResult(self.key, True, {"ok": True, "project_key": self.key, "state": "ready"}, http_status=200)

    # START_FUNCTION_CONTRACT
    # name: _failure
    # purpose: Build one typed non-success transport result for this client.
    # inputs: None.
    # returns: ProjectApiResult.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def _failure(self) -> ProjectApiResult:
        error_class = {
            "refused": "api_offline", "timeout": "timeout", "http500": "http_error",
            "malformed": "malformed_response", "mismatch": "identity_mismatch",
        }.get(self.mode, "api_offline")
        return ProjectApiResult(
            self.key, False, error_class=error_class, error=f"{self.key} {self.mode}",
            http_status=500 if self.mode == "http500" else None,
        )


# START_FUNCTION_CONTRACT
# name: test_stage07_failure_matrix_is_partial_and_never_reroutes
# purpose: Exercise refused, timeout, HTTP 500, malformed JSON, missing
#          capability and identity mismatch while retaining healthy data.
# inputs: tmp_path — isolated registry roots; no project DB is opened by Hub.
# returns: None.
# side_effects: In-memory ASGI Hub requests and failure-client ledger updates.
# emitted_logs: Hub partial/error structured logs.
# error_behavior: Fails if errors become healthy zeroes or mutations reroute.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage07_failure_matrix_is_partial_and_never_reroutes(tmp_path):
    registry = _failure_registry(tmp_path)
    modes = ("healthy", "refused", "timeout", "http500", "malformed", "missing_capability", "mismatch")
    clients = {mode: _FailureClient(mode, mode) for mode in modes}
    app = _hub_app(registry, client_factory=lambda context: clients[context.key])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.stage07") as client:
        project_page = await client.get("/api/admin-hub/projects")
        assert project_page.status_code == 200
        project_rows = {row["key"]: row for row in project_page.json()["projects"]}
        assert project_rows["healthy"]["status"] == "online"
        assert project_rows["refused"]["status"] == "offline"
        assert project_rows["timeout"]["status"] == "offline"
        assert project_rows["mismatch"]["health_status"] == "identity_mismatch"
        for path in (
            "/api/admin-hub/overview", "/api/admin-hub/events", "/api/admin-hub/logs",
            "/api/admin-hub/search?q=packet", "/api/admin-hub/diagnostics",
        ):
            response = await client.get(path)
            assert response.status_code == 200, path
            text = response.text
            assert "healthy" in text
            for mode in modes[1:]:
                assert mode in text, f"{mode} missing from isolated error response {path}"
        capability_page = await client.get("/admin/p/missing_capability/system")
        assert capability_page.status_code == 200 and "Capabilities" in capability_page.text
        assert any(call.get("path") == "/api/admin/capabilities" for call in clients["missing_capability"].calls)
        unavailable_control = await client.post(
            "/api/admin-hub/projects/refused/controls",
            json={"action": "retry", "entity_type": "packet", "entity_id": "packet-refused",
                  "confirmation": {"intent": "confirm"}},
        )
        assert unavailable_control.status_code in {409, 502, 503}
        assert not any(call.get("method") == "POST" for call in clients["healthy"].calls)
        assert not any(call.get("method") == "POST" for call in clients["mismatch"].calls)
        assert not any(call.get("method") == "POST" for call in clients["missing_capability"].calls)


# END_BLOCK_FAILURE_MATRIX


# START_BLOCK_PERFORMANCE
# START_FUNCTION_CONTRACT
# name: test_stage07_performance_fanout_and_bounded_explorer
# purpose: Prove representative-scale overlap, offline isolation, no eager
#          filesystem scan, bounded logs and project-keyed OpenAPI caching.
# inputs: tmp_path — registry roots; deterministic scale clients.
# returns: None.
# side_effects: In-memory async service calls only.
# emitted_logs: Fan-out start/done logs.
# error_behavior: Fails on serial fan-out, eager reads or cache leakage.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage07_performance_fanout_and_bounded_explorer(tmp_path):
    count = 12
    entries = [
        {"key": f"p{index:02d}", "name": f"Project {index:02d}", "enabled": True,
         "project_root": str(tmp_path / f"p{index:02d}"), "api_url": f"http://p{index:02d}.example.test"}
        for index in range(count)
    ]
    registry = ProjectRegistry.from_mapping({"projects": entries})
    active_requests = 0
    max_active_requests = 0

    class ScaleClient:
        def __init__(self, key: str) -> None:
            self.key = key
            self.fs_calls = 0
            self.tail_values: list[int] = []
            self.openapi_calls = 0

        async def get_health(self) -> dict[str, Any] | ProjectApiResult:
            nonlocal active_requests, max_active_requests
            active_requests += 1
            max_active_requests = max(max_active_requests, active_requests)
            await asyncio.sleep(0.01)
            active_requests -= 1
            if self.key in {"p10", "p11"}:
                return ProjectApiResult(self.key, False, error_class="api_offline", error="fixture offline")
            return {"status": "ok", "project_key": self.key, "project_name": self.key, "project_root": f"/srv/{self.key}"}

        async def get_json(self, path: str) -> dict[str, Any] | ProjectApiResult:
            route = urlsplit(path).path
            if route == "/openapi.json":
                self.openapi_calls += 1
                return {"openapi": "3.1.0", "paths": {"/api/synthetic": {"get": {"responses": {"200": {}}}}}}
            if self.key in {"p10", "p11"}:
                return ProjectApiResult(self.key, False, error_class="api_offline", error="fixture offline")
            if route == "/api/admin/system/health":
                return await self.get_health()
            if route == "/api/diagnostics/state":
                return {"data": {"packets_by_state": {"ready": 100}, "waits": []}}
            if route == "/api/events":
                return {"data": {"total": 2000, "limit": 100, "offset": 0, "events": []}}
            if route == "/api/admin/system/logs":
                tail = int(parse_qs(urlsplit(path).query).get("tail", [200])[0])
                self.tail_values.append(tail)
                return {"lines": [{"message": "bounded"}] * min(tail, 200), "total": 2000, "truncated": tail < 2000}
            if route.startswith("/api/admin/fs/"):
                self.fs_calls += 1
            return {}

    clients = {entry["key"]: ScaleClient(entry["key"]) for entry in entries}
    project_service = AdminProjectService(registry, client_factory=lambda context: clients[context.key], max_concurrency=count)
    rows = await project_service.get_projects_health()
    assert len(rows) == count and max_active_requests > 1
    cross_service = AdminCrossProjectService(registry, client_factory=lambda context: clients[context.key], max_concurrency=count)
    overview = await cross_service.get_projects_overview()
    assert overview["projects"] and {error["project_key"] for error in overview["errors"]} >= {"p10", "p11"}
    assert all(client.fs_calls == 0 for client in clients.values())
    logs = await cross_service.query_logs(tail=17)
    assert {error["project_key"] for error in logs["errors"]} == {"p10", "p11"}
    assert all(value <= 17 for client in clients.values() for value in client.tail_values)
    center = AdminControlCenterService(cross_service)
    assert _OPENAPI_CACHE_TTL_SECONDS <= 10
    assert (await center.api_page("p00"))["operations"]
    assert (await center.api_page("p00"))["operations"] and (await center.api_page("p01"))["operations"]
    assert clients["p00"].openapi_calls == 1 and clients["p01"].openapi_calls == 1


# END_BLOCK_PERFORMANCE


# START_BLOCK_BROWSER
# START_FUNCTION_CONTRACT
# name: test_stage07_browser_desktop_mobile_smoke
# purpose: Exercise real Hub desktop/mobile UI, accessibility labels, deep
#          links, browser history, polling context and an offline card.
# inputs: stage07_hub_url — real loopback Hub process.
# returns: None.
# side_effects: Starts headless Chromium and performs bounded HTTP reads.
# emitted_logs: Browser console output is not emitted by the application test.
# error_behavior: Skips only when Playwright or Chromium is absent.
# END_FUNCTION_CONTRACT
@pytest.mark.integration
def test_stage07_browser_desktop_mobile_smoke(stage07_hub_url):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip(f"Stage 07 browser smoke skipped: Playwright unavailable ({exc})")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Stage 07 browser smoke skipped: Chromium unavailable ({exc})")
        desktop = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            response = desktop.goto(f"{stage07_hub_url}/admin/projects", wait_until="domcontentloaded", timeout=10000)
            assert response is not None and response.status == 200
            assert desktop.locator("h1").filter(has_text="Projects").is_visible()
            selector = desktop.locator("#project-selector")
            assert selector.is_visible() and desktop.locator("label[for='project-selector']").is_visible()
            assert desktop.locator("nav[aria-label='Control Center navigation']").is_visible()
            assert desktop.locator("[data-project-key='alpha']").count() == 1
            assert desktop.locator("[data-project-key='offline']").get_attribute("data-project-status") == "offline"
            selector.focus()
            assert desktop.evaluate("document.activeElement && document.activeElement.id") == "project-selector"
            desktop.select_option("#project-selector", "/admin/p/alpha")
            desktop.wait_for_url("**/admin/p/alpha", wait_until="domcontentloaded")
            assert desktop.locator(".cc-tree").is_visible()
            packet_url = f"{stage07_hub_url}/admin/p/alpha/packet/pkt-shared-stage07?tab=raw"
            packet_response = desktop.goto(packet_url, wait_until="domcontentloaded", timeout=10000)
            assert packet_response is not None and packet_response.status == 200
            assert desktop.locator("nav[aria-label='Packet tabs']").is_visible()
            assert desktop.locator("a[href*='tab=timeline']").count() >= 1
            assert "Shared merged packet Alpha" in desktop.locator("body").inner_text()
            desktop.go_back(wait_until="domcontentloaded")
            assert "/admin/p/alpha" in desktop.url
            desktop.go_forward(wait_until="domcontentloaded")
            assert "tab=raw" in desktop.url
            control_response = desktop.goto(f"{stage07_hub_url}/admin/p/alpha/packet/{_CONTROL_PACKET_ID}", wait_until="domcontentloaded", timeout=10000)
            assert control_response is not None and control_response.status == 200
            assert desktop.locator("input[name='confirmation_value']").count() >= 1
            assert desktop.locator("button").filter(has_text="Retry packet").count() >= 1 or desktop.locator("button", has_text="Stop / cancel").count() >= 1
            logs_response = desktop.goto(f"{stage07_hub_url}/admin/p/alpha/logs?follow=true", wait_until="domcontentloaded", timeout=10000)
            assert logs_response is not None and logs_response.status == 200
            log_viewer = desktop.locator("[data-testid='bounded-log-viewer']")
            assert log_viewer.get_attribute("hx-trigger") == "every 5s" and "/admin/p/alpha/logs" in (log_viewer.get_attribute("hx-get") or "")
            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            try:
                mobile_response = mobile.goto(f"{stage07_hub_url}/admin/projects", wait_until="domcontentloaded", timeout=10000)
                assert mobile_response is not None and mobile_response.status == 200
                assert mobile.locator("#project-selector").is_visible()
                scroll_width, viewport_width = mobile.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
                assert scroll_width <= viewport_width
                mobile_packet = mobile.goto(packet_url, wait_until="domcontentloaded", timeout=10000)
                assert mobile_packet is not None and mobile_packet.status == 200
                assert mobile.locator("[data-project-key='alpha']").count() >= 1 and mobile.locator("nav[aria-label='Packet tabs']").is_visible()
            finally:
                mobile.close()
        finally:
            desktop.close()
            browser.close()


# END_BLOCK_BROWSER
