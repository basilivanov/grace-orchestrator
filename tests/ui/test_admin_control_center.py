# ############################################################################
# AI_HEADER: test_admin_control_center — Stage 04 project-aware UI acceptance
# ROLE: Exercises the Jinja2/HTMX Control Center through ASGI with independent
#       fake project APIs, proving URL-scoped isolation and graceful gaps.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove the Stage 04 project dashboard, project tree, packet detail,
#          runs/stages/sessions, waits, blocked panel and polling URLs.
# inputs: Independent immutable ProjectRegistry contexts and fake clients.
# returns: Pytest assertions.
# side_effects: In-memory ASGI requests only.
# emitted_logs: None.
# error_behavior: Fails when project data crosses URL boundaries or a missing
#                 project capability breaks the rendered page.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _FakeProjectClient
#     methods:
#       - get_health
#       - get_json
#   - function: test_control_center_dashboard_is_project_aware
#   - function: test_control_center_deep_links_do_not_cross_wire_packets
#   - function: test_control_center_packet_debugging_views
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import ProjectRegistry
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("test_admin_control_center")


# START_BLOCK_FIXTURES
class _FakeProjectClient:
    """Independent read-only fake for one configured project."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure one independent project's health and API payloads.
    # inputs: key — project key; offline — typed transport failure toggle.
    # returns: None.
    # side_effects: Initializes an in-memory call ledger.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def __init__(self, key: str, *, offline: bool = False) -> None:
        self.key = key
        self.offline = offline
        self.calls: list[str] = []

    # START_FUNCTION_CONTRACT
    # name: get_health
    # purpose: Return identity-matching health or an explicit offline result.
    # inputs: None.
    # returns: Health mapping or ProjectApiResult.
    # side_effects: Records a health read.
    # emitted_logs: None.
    # error_behavior: Offline mode returns a typed API failure.
    # END_FUNCTION_CONTRACT
    async def get_health(self) -> dict | ProjectApiResult:
        self.calls.append("health")
        if self.offline:
            return ProjectApiResult(
                project_key=self.key,
                ok=False,
                error_class="api_offline",
                error="project is offline",
            )
        return {
            "status": "ok",
            "project_key": self.key,
            "project_name": self.key.title(),
            "project_root": f"/srv/{self.key}",
            "target_branch": "main",
            "target_head": f"head-{self.key}",
            "code_sha": f"grace-{self.key}",
            "version": "0.1.0",
            "api_status": "ready",
            "supervisor_status": "running",
            "db_ok": True,
            "api_alive": True,
            "api_token": "do-not-render",
        }

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Return one independent project-local read model by API path.
    # inputs: path — absolute project-local API path with optional query.
    # returns: JSON mapping or typed capability/transport result.
    # side_effects: Records a project-local read.
    # emitted_logs: None.
    # error_behavior: Offline mode returns a typed API failure; sessions are
    #                 intentionally unavailable for capability coverage.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> dict | ProjectApiResult:
        route = urlsplit(path).path
        self.calls.append(route)
        if self.offline:
            return ProjectApiResult(
                project_key=self.key,
                ok=False,
                error_class="api_offline",
                error="project is offline",
            )
        if route == "/api/diagnostics/state":
            return {"data": {"packets_by_state": {"ready": 1}, "workers": {"total": 1, "idle": 1, "busy": 0}, "ordinary_leases": [{"packet_id": "shared-packet"}], "active_parallel_leases": [{"packet_id": "shared-packet", "conflict_keys": [f"db:{self.key}"]}], "active_merge_leases": [], "effective_max_concurrency": 2, "waits": [{"packet_id": "shared-packet", "reason": "waiting_for_concurrency_slot"}]}}
        if route == "/api/events":
            return {"data": {"events": [], "total": 0}}
        if route == "/api/admin/features":
            return {"features": [_feature(self.key)]}
        if route.endswith("/blocking_decision"):
            return {
                "has_blocking": True,
                "state": "blocked_final",
                "decided_by": "feature_recovery",
                "reason": f"{self.key} primary failure",
                "last_failure": {
                    "failure_class": "acceptance",
                    "failure_stage": "T1",
                    "blocking_issues": ["ruff failed"],
                    "command_preview": ["ruff", "check", "src"],
                    "exit_code": 1,
                    "stderr": "E501 stderr tail",
                },
            }
        if route.endswith("/detail"):
            return {
                "packet": {
                    "id": "shared-packet",
                    "feature_id": f"feature-{self.key}",
                    "wave_id": f"wave-{self.key}",
                    "title": f"Packet {self.key}",
                    "state": "blocked_final",
                    "attempt_count": 2,
                    "max_attempts": 3,
                    "acceptance_profile": "STRICT",
                    "spec_json": {
                        "scope": ["src/service.py"],
                        "conflict_keys": [f"db:{self.key}"],
                        "depends_on": [],
                    },
                },
                "worker_id": f"worker-{self.key}",
                "model": "model-test",
                "elapsed_seconds": 4,
                "stages": [{"stage_key": "future_stage", "status": "failed", "trace_id": f"trace-{self.key}"}],
            }
        if route.endswith("/timeline"):
            return {"events": [{"timestamp": "2026-08-11T10:00:00Z", "event_type": "future_event", "trace_id": "trace-full", "payload_json": {"reason": "unknown is retained", "secret": "hidden"}}], "total": 1}
        if route.endswith("/runs"):
            return {"runs": [{"id": "run-1", "run_number": 1, "status": "failed", "worker_id": f"worker-{self.key}", "model": "model-test", "base_sha": "base-1", "integration_base_sha": "integration-1"}]}
        if route.endswith("/raw"):
            return {"packet": {"id": "shared-packet", "spec_json": {"secret": "hidden"}}, "stages": [{"id": "stage-1", "stage_key": "future_stage", "status": "failed"}]}
        if route.endswith("/sessions"):
            return ProjectApiResult(project_key=self.key, ok=False, error_class="capability_unavailable", error="sessions endpoint missing", http_status=404)
        if route == "/api/admin/system/workers":
            return {"workers": [{"id": f"worker-{self.key}", "status": "idle"}]}
        return {}


# START_FUNCTION_CONTRACT
# name: _feature
# purpose: Build an independent Feature/Wave/Packet tree for one project.
# inputs: project key.
# returns: Feature mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _feature(key: str) -> dict:
    return {
        "id": f"feature-{key}",
        "slug": f"feature-{key}",
        "title": f"Feature {key}",
        "status": "ACTIVE",
        "wave_count": 1,
        "total_packets": 1,
        "waves": [{
            "id": f"wave-{key}",
            "slug": f"wave-{key}",
            "title": f"Wave {key}",
            "order": 1,
            "status": "ACTIVE",
            "packets": [{
                "id": "shared-packet",
                "title": f"Packet {key}",
                "state": "ready",
                "attempt_count": 0,
                "max_attempts": 3,
                "wait_reason": "waiting_for_concurrency_slot",
                "scope": ["src/service.py"],
                "conflict_keys": [f"db:{key}"],
            }],
        }],
    }


# START_FUNCTION_CONTRACT
# name: _app
# purpose: Create a two-project app with one disabled and one offline fake.
# inputs: None.
# returns: FastAPI app and fake clients.
# side_effects: None beyond app construction.
# emitted_logs: None.
# error_behavior: Never raises for valid test registry data.
# END_FUNCTION_CONTRACT
def _app():
    registry = ProjectRegistry.from_mapping({
        "projects": [
            {"key": "alpha", "name": "Alpha", "project_root": "/srv/alpha", "api_url": "http://alpha.test"},
            {"key": "beta", "name": "Beta", "project_root": "/srv/beta", "api_url": "http://beta.test"},
            {"key": "offline", "name": "Offline", "project_root": "/srv/offline", "api_url": "http://offline.test"},
            {"key": "disabled", "name": "Disabled", "enabled": False, "project_root": "/srv/disabled", "api_url": "http://disabled.test"},
        ]
    })
    clients = {
        "alpha": _FakeProjectClient("alpha"),
        "beta": _FakeProjectClient("beta"),
        "offline": _FakeProjectClient("offline", offline=True),
        "disabled": _FakeProjectClient("disabled"),
    }
    app = create_app(
        project_registry=registry,
        project_client_factory=lambda context: clients[context.key],
    )
    return app, clients


# END_BLOCK_FIXTURES


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_control_center_dashboard_is_project_aware
# purpose: Prove two healthy cards, isolated offline/disabled statuses and no
#          remote call to a disabled project's client.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI reads against in-memory fake projects.
# emitted_logs: None.
# error_behavior: Fails on missing cards, page-level offline failure or disabled
#                 project fan-out.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_center_dashboard_is_project_aware():
    app, clients = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        response = await client.get("/admin")
    assert response.status_code == 200
    assert "Alpha" in response.text and "Beta" in response.text
    assert "■ OFFLINE" in response.text
    assert "○ DISABLED" in response.text
    assert clients["disabled"].calls == []
    assert "filter=attention" in response.text


# START_FUNCTION_CONTRACT
# name: test_control_center_deep_links_do_not_cross_wire_packets
# purpose: Prove the same packet ID resolves independently under each explicit
#          project URL and the selected tree contains only that project.
# inputs: None.
# returns: None.
# side_effects: Performs project-scoped ASGI reads.
# emitted_logs: None.
# error_behavior: Fails on cross-project entity leakage.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_center_deep_links_do_not_cross_wire_packets():
    app, _clients = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.test") as client:
        alpha = await client.get("/admin/p/alpha/packet/shared-packet")
        beta = await client.get("/admin/p/beta")
        feature = await client.get("/admin/p/alpha/feature/feature-alpha")
    assert alpha.status_code == 200
    assert "Packet alpha" in alpha.text
    assert "Packet beta" not in alpha.text
    assert "WAIT: waiting_for_concurrency_slot" in beta.text
    assert "Feature alpha" in feature.text
    assert "Feature beta" not in feature.text
    assert "/admin/p/alpha" in alpha.text


# START_FUNCTION_CONTRACT
# name: test_control_center_packet_debugging_views
# purpose: Prove typed waits, immediate blocking details, unknown stage cards,
#          run selection, sessions capability banner and polling context.
# inputs: None.
# returns: None.
# side_effects: Performs packet tab ASGI reads.
# emitted_logs: None.
# error_behavior: Fails when a primary failure requires opening Logs or when
#                 tab context loses project/packet identity.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_center_packet_debugging_views():
    app, _clients = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.test") as client:
        packet = await client.get("/admin/p/alpha/packet/shared-packet")
        timeline = await client.get("/admin/p/alpha/packet/shared-packet?tab=timeline")
        pipeline = await client.get("/admin/p/alpha/packet/shared-packet?tab=pipeline")
        runs = await client.get("/admin/p/alpha/packet/shared-packet?tab=runs&run_id=run-1")
        sessions = await client.get("/admin/p/alpha/packet/shared-packet?tab=sessions")
        partial = await client.get("/admin/p/alpha/_partial/content?entity_type=packet&entity_id=shared-packet&tab=runs&run_id=run-1")
    assert packet.status_code == 200
    assert "Blocking" in packet.text
    assert "alpha primary failure" in packet.text
    assert "ruff check src" in packet.text
    assert "WAIT:" in packet.text
    assert "future_event" in timeline.text and "trace-full" in timeline.text and "unknown is retained" in timeline.text
    assert "future stage" in pipeline.text.lower()
    assert "run-1" in runs.text and "base-1" in runs.text
    assert "Sessions unavailable" in sessions.text
    assert partial.status_code == 200
    assert 'data-project-key="alpha"' in partial.text
    assert 'data-tab="runs"' in partial.text
    assert 'data-entity-id="shared-packet"' in partial.text


# START_FUNCTION_CONTRACT
# name: test_control_center_system_masks_secrets_and_shows_safety_state
# purpose: Prove System renders worker/lease/wait/concurrency diagnostics while
#          masking credential-shaped runtime configuration values.
# inputs: None.
# returns: None.
# side_effects: Performs one project-scoped System ASGI read.
# emitted_logs: None.
# error_behavior: Fails if a secret is rendered or safety state disappears.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_control_center_system_masks_secrets_and_shows_safety_state():
    app, _clients = _app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.test") as client:
        response = await client.get("/admin/p/alpha/system")
    assert response.status_code == 200
    assert "do-not-render" not in response.text
    assert "active_parallel_leases" in response.text
    assert "waiting_for_concurrency_slot" in response.text
    assert "effective_max_concurrency" in response.text


# START_FUNCTION_CONTRACT
# name: test_control_center_mobile_css_is_single_column
# purpose: Prove the Stage 04 stylesheet contains the required narrow viewport
#          single-column responsive behavior.
# inputs: None.
# returns: None.
# side_effects: Reads one repository CSS asset.
# emitted_logs: None.
# error_behavior: Fails when the mobile layout forces desktop columns.
# END_FUNCTION_CONTRACT
def test_control_center_mobile_css_is_single_column():
    css = Path("src/grace_control/ui/static/css/admin_control_center.css").read_text(encoding="utf-8")
    assert "@media (max-width: 700px)" in css
    assert ".cc-project-grid, .cc-project-layout, .cc-system-grid { grid-template-columns: 1fr; }" in css


# END_BLOCK_ACCEPTANCE
