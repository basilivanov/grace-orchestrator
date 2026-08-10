# ############################################################################
# AI_HEADER: test_admin_control_center_explorers — Stage 05 explorer acceptance
# ROLE: Exercises the read-only Events, Logs, Evidence, Artifacts, Files, Git,
#       leases, stale-base, Raw and OpenAPI Control Center surfaces via ASGI.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove Stage 05 bounded explorer behavior without project SSH, direct
#          database access or browser-supplied arbitrary paths/commands.
# inputs: Deterministic independent fake project APIs and ASGI requests.
# returns: Pytest acceptance assertions.
# side_effects: In-memory HTTP requests only; no project state mutations.
# emitted_logs: None directly; service logs are captured by the test runner.
# error_behavior: Fails on cross-project links, unsafe previews, token leakage,
#                 unbounded reads or OpenAPI execution outside the allowlist.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _ExplorerClient
#     methods:
#       - get_json
#   - function: test_stage05_global_events_keep_payload_and_project_links
#   - function: test_stage05_global_events_and_logs_continue_with_context
#   - function: test_stage05_logs_are_source_selectable_and_bounded
#   - function: test_stage05_packet_evidence_artifacts_and_html_are_read_only
#   - function: test_stage05_files_reject_absolute_and_traversal_paths
#   - function: test_stage05_git_worktrees_and_stale_base_are_display_only
#   - function: test_stage05_leases_mask_tokens_and_raw_keeps_unknown_fields
#   - function: test_stage05_openapi_is_dynamic_get_only_and_allowlisted
#   - function: explorer_browser
#   - function: test_stage05_logs_follow_browser_preserves_scrolled_position
# END_MODULE_MAP

from __future__ import annotations

import base64
import os
from html import unescape
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.project_client import ProjectApiResult
from tests.ui.test_admin_control_center import _app, _FakeProjectClient

_log = GraceLogger("test_admin_control_center_explorers")


# START_BLOCK_FIXTURES
# START_FUNCTION_CONTRACT
# name: __init__
# purpose: Add deterministic Stage 05 payloads to the accepted project fake.
# inputs: key — project key.
# returns: None.
# side_effects: Initializes a bounded call ledger.
# emitted_logs: None.
# error_behavior: Never raises for known fixture selectors.
# END_FUNCTION_CONTRACT
class _ExplorerClient(_FakeProjectClient):
    def __init__(self, key: str, *, event_count: int = 1) -> None:
        super().__init__(key)
        self.calls: list[str] = []
        self.secret_token = f"full-fencing-token-{key}"
        self.event_count = event_count

    # START_FUNCTION_CONTRACT
    # name: get_json
    # purpose: Return independent synthetic Stage 05 project-local read DTOs.
    # inputs: path — project-local path plus bounded query parameters.
    # returns: JSON mapping or typed project API failure.
    # side_effects: Records the exact requested path for allowlist assertions.
    # emitted_logs: None.
    # error_behavior: Unknown paths delegate to the Stage 04 fake.
    # END_FUNCTION_CONTRACT
    async def get_json(self, path: str) -> dict | ProjectApiResult:
        route = urlsplit(path).path
        query = parse_qs(urlsplit(path).query)
        self.calls.append(path)
        if route == "/api/events":
            requested_limit = int(query.get("limit", [100])[0])
            events = [
                {
                    "id": f"event-{self.key}-{index}",
                    "timestamp": f"2026-08-11T10:00:{index:02d}Z",
                    "event_type": "shared_event",
                    "entity_type": "packet",
                    "entity_id": "same-packet",
                    "component": "worker",
                    "trace_id": f"trace-{self.key}",
                    "reason": f"reason-{self.key}-{index}",
                    "payload_json": {"unknown_extra": self.key, "secret": self.secret_token},
                }
                for index in range(min(self.event_count, requested_limit))
            ]
            return {
                "data": {
                    "total": self.event_count,
                    "events": events,
                }
            }
        if route == "/api/admin/system/logs":
            requested_tail = int(query.get("tail", [100])[0])
            return {
                "lines": [
                    {"timestamp": f"2026-08-11T10:00:{index:02d}Z", "source": ("stderr", "api", "worker")[index % 3], "level": "ERROR", "message": f"line-{index}", "worker_id": f"worker-{self.key}"}
                    for index in range(requested_tail)
                ],
                "total": requested_tail + 50,
                "truncated": True,
                "source": "stderr.log",
            }
        if route == "/openapi.json":
            return {
                "openapi": "3.1.0",
                "paths": {
                    "/api/synthetic-new-endpoint": {
                        "get": {"summary": "Synthetic GET", "responses": {"200": {"description": "ok"}}},
                    },
                    "/api/items/{item_id}": {
                        "get": {
                            "summary": "Synthetic item GET",
                            "parameters": [
                                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
                                {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                            ],
                            "responses": {"200": {"description": "ok"}},
                        },
                    },
                    "/api/mutation": {
                        "post": {"summary": "Mutation", "responses": {"200": {"description": "changed"}}},
                    },
                },
            }
        if route == "/api/synthetic-new-endpoint":
            return ProjectApiResult(
                self.key,
                True,
                {"new_field": "discovered", "nested": {"ok": True}},
                http_status=200,
                headers={"content-type": "application/json"},
            )
        if route.startswith("/api/items/"):
            return ProjectApiResult(
                self.key,
                True,
                {"item_id": route.rsplit("/", 1)[-1], "query": query},
                http_status=200,
                headers={"content-type": "application/json"},
            )
        if route == "/api/admin/capabilities":
            return {"capabilities": {"filesystem": True, "git_read": True, "api_explorer": True}}
        if route == "/api/admin/fs/roots":
            return {"roots": [{"root": "state", "exists": True, "kind": "directory"}]}
        if route == "/api/admin/fs/list":
            requested_path = query.get("path", [""])[0]
            if requested_path == "symlink":
                return ProjectApiResult(self.key, False, error_class="SYMLINK_ESCAPE", error="path escapes root", http_status=403)
            return {"root": "state", "path": requested_path, "entries": [{"name": "readme.md", "path": "readme.md", "kind": "file", "size": 12, "mime": "text/markdown"}], "truncated": False}
        if route == "/api/admin/fs/file":
            return {"root": "state", "path": "readme.md", "size": 12, "mime": "text/markdown", "binary": False, "content": "# safe\n", "truncated": False}
        if route == "/api/admin/fs/tail":
            return {"root": "state", "path": "stdout.log", "size": 20, "mime": "text/plain", "binary": False, "content": "tail\n", "truncated": True}
        if route == "/api/admin/git/repository":
            return {"repo_root": "/srv/secret-project", "current_branch": "main", "head": "head-1", "target_branch": "main", "target_branch_head": "head-2", "clean": True}
        if route == "/api/admin/git/worktrees":
            return {"worktrees": [{"path": "/srv/secret-project/.grace/wt/pkt", "branch": "grace/pkt", "head": "head-1", "registered": True, "exists": True}]}
        if route == "/api/admin/git/changed-files":
            return {"changed_files": [{"status": "M", "path": "src/service.py"}]}
        if route == "/api/admin/git/diff-stat":
            return {"stat": "1 file changed", "text": "1 file changed", "path": query.get("path", [None])[0], "truncated": False}
        if route == "/api/admin/git/diff":
            return {"diff": "@@ -1 +1 @@\n-old\n+new\n", "text": "@@ -1 +1 @@\n-old\n+new\n", "path": query.get("path", [None])[0], "truncated": False}
        if route.endswith("/evidence"):
            return {"verdict": "failed", "summary": "T1 failed", "stages": [{"name": "T1", "status": "failed", "summary": "test failure", "blocking_issues": ["assertion"], "commands_summary": {"failed": 1}, "exit_code": 1, "stdout_tail": "out", "stderr_tail": "err", "screenshots": ["shot.png"], "visual": {"diff": True}, "browser": {"url": "http://test"}}], "unknown_evidence_field": {"keep": True}}
        if route.endswith("/artifacts") and not route.endswith("/preview"):
            return {"tree": [{"name": "report.json", "relative_path": "report.json", "size": 20, "mime": "application/json", "kind": "json", "preview_capable": True}, {"name": "page.html", "relative_path": "page.html", "size": 30, "mime": "text/html", "kind": "html", "preview_capable": True}, {"name": "nested", "type": "dir", "children": [{"name": "child.txt", "size": 12, "mime": "text/plain", "type": "file"}]}]}
        if route.endswith("/artifacts/preview"):
            requested_path = query.get("path", [""])[0]
            if requested_path.endswith(".html"):
                content = "<script>window.__project_html_executed = true</script>"
                return {"path": requested_path, "size": len(content), "mime": "text/html", "binary": False, "content": content, "truncated": False}
            if requested_path.endswith(".bin"):
                return {"path": requested_path, "size": 10_000_000, "mime": "application/octet-stream", "binary": True, "content": None, "content_base64": base64.b64encode(b"\x00\x01").decode(), "truncated": True}
            if requested_path.endswith(".png"):
                return {"path": requested_path, "size": 67, "mime": "image/png", "binary": True, "content": None, "content_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "truncated": False}
            if requested_path.endswith(".md"):
                return {"path": requested_path, "size": 10, "mime": "text/markdown", "binary": False, "content": "# heading\n", "truncated": False}
            if requested_path.endswith(".txt"):
                return {"path": requested_path, "size": 12, "mime": "text/plain", "binary": False, "content": "plain text\n", "truncated": False}
            return {"path": requested_path, "size": 20, "mime": "application/json", "binary": False, "content": '{"ok": true}', "truncated": False}
        if route.endswith("/logs") and "/runs/" in route:
            return {"lines": [{"source": "stderr", "level": "ERROR", "msg": "run failure"}], "source_file": "stderr.log", "truncated": True}
        if route == "/api/diagnostics/state":
            return {"data": {"packets_by_state": {"accepted": 1}, "ordinary_leases": [{"packet_id": "same-packet", "lease_token": self.secret_token}], "active_parallel_leases": [{"packet_id": "same-packet", "token_fingerprint": "fp-parallel", "conflict_keys": ["db:users"]}], "active_merge_leases": [{"packet_id": "same-packet", "fencing_token": self.secret_token, "token_fingerprint": "fp-merge"}], "stale_base_recheck": "passed"}}
        if route.endswith("/detail"):
            detail = await super().get_json(path)
            if isinstance(detail, dict):
                detail["packet"]["base_sha"] = "head-2"
                detail["packet"]["integration_base_sha"] = "head-2"
                detail["packet"]["failure_class"] = "integration_verification_failed"
            return detail
        if route.endswith("/raw") and "/runs/" not in route:
            return {"packet": {"id": "shared-packet", "unknown_extra": {"keep": True}}, "stages": self.stages}
        return await super().get_json(path)


# END_BLOCK_FIXTURES


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_stage05_global_events_keep_payload_and_project_links
# purpose: Prove cross-project filtering, same-entity attribution, payload
#          inspection and canonical project-aware links.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails on payload loss or cross-project link ambiguity.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_global_events_keep_payload_and_project_links():
    app, clients = _app(alpha_client=_ExplorerClient("alpha"))
    clients["beta"] = _ExplorerClient("beta")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        response = await client.get("/admin/events", params={"project": "alpha,beta", "entity_id": "same-packet", "text": "reason"})
    assert response.status_code == 200
    assert "/admin/p/alpha/packet/same-packet" in response.text
    assert "/admin/p/beta/packet/same-packet" in response.text
    assert "unknown_extra" in response.text
    assert "full-fencing-token" not in response.text


# START_FUNCTION_CONTRACT
# name: test_stage05_global_events_and_logs_continue_with_context
# purpose: Prove rendered opaque Next controls reach rows beyond page one while
#          preserving project and active filter state without an offset mix.
# inputs: None.
# returns: None.
# side_effects: Performs bounded ASGI page and continuation requests.
# emitted_logs: None.
# error_behavior: Fails if a cursor is not navigable or filter context changes.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_global_events_and_logs_continue_with_context():
    event_client = _ExplorerClient("alpha", event_count=205)
    app, _ = _app(alpha_client=event_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        first_events = await client.get(
            "/admin/events",
            params={"project": "alpha", "entity_id": "same-packet", "text": "reason", "limit": 100},
        )
        event_href = first_events.text.split('data-testid="events-next" href="', 1)[1].split('"', 1)[0]
        event_query = {key: values[0] for key, values in parse_qs(urlsplit(unescape(event_href)).query).items()}
        assert event_query["project"] == "alpha"
        assert event_query["entity_id"] == "same-packet"
        assert event_query["text"] == "reason"
        assert "offset" not in event_query
        second_events = await client.get("/admin/events", params=event_query)

        first_logs = await client.get(
            "/admin/logs",
            params={"project": "alpha", "source": "all", "contains": "line", "tail": 100},
        )
        log_href = first_logs.text.split('data-testid="logs-next" href="', 1)[1].split('"', 1)[0]
        log_query = {key: values[0] for key, values in parse_qs(urlsplit(unescape(log_href)).query).items()}
        assert log_query["project"] == "alpha"
        assert log_query["source"] == "all"
        assert log_query["contains"] == "line"
        assert "offset" not in log_query
        second_logs = await client.get("/admin/logs", params=log_query)

    assert "reason-alpha-100" in second_events.text
    assert "line-100" in second_logs.text


# START_FUNCTION_CONTRACT
# name: test_stage05_logs_are_source_selectable_and_bounded
# purpose: Prove explicit source/tail/filter controls and follow-off viewport
#          semantics are represented without loading complete logs.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails if tail or follow controls disappear.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_logs_are_source_selectable_and_bounded():
    explorer = _ExplorerClient("alpha")
    app, clients = _app(alpha_client=explorer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        response = await client.get("/admin/logs", params={"project": "alpha", "source": "stderr", "tail": 100, "contains": "line-99"})
        all_response = await client.get("/admin/logs", params={"project": "alpha", "source": "all", "tail": 100})
        api_response = await client.get("/admin/logs", params={"project": "alpha", "source": "api", "tail": 100, "contains": "line-97"})
        follow_fragment = await client.get(
            "/admin/logs",
            params={"project": "alpha", "source": "all", "tail": 100, "follow": "true"},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "data-follow=\"off\"" in response.text
    assert "stderr" in response.text
    system_calls = [call for call in explorer.calls if urlsplit(call).path == "/api/admin/system/logs"]
    assert system_calls and int(parse_qs(urlsplit(system_calls[-1]).query)["tail"][0]) == 100
    assert not any(urlsplit(call).path == "/api/admin/system/logs" for call in clients["beta"].calls)

    assert "line-97" in all_response.text and "line-98" in all_response.text
    assert "line-97" in api_response.text and "line-98" not in api_response.text
    assert "<html" not in follow_fragment.text and 'hx-trigger="every 5s"' in follow_fragment.text


# START_FUNCTION_CONTRACT
# name: test_stage05_packet_evidence_artifacts_and_html_are_read_only
# purpose: Prove normalized evidence, JSON/HTML/binary bounded artifact
#          behavior and escaped non-executing HTML source previews.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails if project HTML is injected into Admin origin.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_packet_evidence_artifacts_and_html_are_read_only():
    app, _ = _app(alpha_client=_ExplorerClient("alpha"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        evidence = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "evidence", "run_id": "run-1"})
        raw_evidence = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "evidence", "run_id": "run-1"})
        html = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "page.html"})
        image = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "plot.png"})
        markdown = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "notes.md"})
        text = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "output.txt"})
        structured = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "report.json"})
        binary = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "artifacts", "run_id": "run-1", "artifact_path": "large.bin"})
    assert evidence.status_code == 200 and "T1 failed" in evidence.text
    assert raw_evidence.status_code == 200 and "unknown_evidence_field" in raw_evidence.text and "View raw evidence JSON" in raw_evidence.text
    assert html.status_code == 200 and "&lt;script&gt;" in html.text and "window.__project_html_executed" in html.text and "child.txt" in html.text
    assert image.status_code == 200 and "cc-bounded-image" in image.text and "data:image/png;base64" in image.text
    assert markdown.status_code == 200 and "Markdown rendered safely" in markdown.text and "# heading" in markdown.text
    assert text.status_code == 200 and "plain text" in text.text
    assert structured.status_code == 200 and '"ok": true' in structured.text
    assert "srcdoc" not in html.text and "large.bin" in binary.text and "metadata/download only" in binary.text


# START_FUNCTION_CONTRACT
# name: test_stage05_files_reject_absolute_and_traversal_paths
# purpose: Prove named-root Files uses safe relative paths and surfaces typed
#          traversal/symlink errors without arbitrary browser path access.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails if an unsafe path becomes a filesystem request.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_files_reject_absolute_and_traversal_paths():
    explorer = _ExplorerClient("alpha")
    app, _ = _app(alpha_client=explorer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        absolute = await client.get("/admin/p/alpha/files", params={"root": "state", "path": "/etc/passwd"})
        traversal = await client.get("/admin/p/alpha/files", params={"root": "state", "path": "../secret"})
        symlink = await client.get("/admin/p/alpha/files", params={"root": "state", "path": "symlink"})
    assert "ABSOLUTE_PATH_DENIED" in absolute.text
    assert "PATH_TRAVERSAL" in traversal.text
    assert "SYMLINK_ESCAPE" in symlink.text
    assert not any("/api/admin/fs/list?root=state&path=%2Fetc" in call for call in explorer.calls)


# START_FUNCTION_CONTRACT
# name: test_stage05_git_worktrees_and_stale_base_are_display_only
# purpose: Prove repository/HEAD/diff/worktree metadata and stale-base lifecycle
#          render without delete/control actions.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails on missing Git metadata or mutation controls.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_git_worktrees_and_stale_base_are_display_only():
    explorer = _ExplorerClient("alpha")
    app, _ = _app(alpha_client=explorer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        project_response = await client.get("/admin/p/alpha/git", params={"path": "src/service.py"})
        response = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "git", "git_path": "src/service.py"})
    assert project_response.status_code == 200 and "Repository and worktrees" in project_response.text and "@@ -1 +1 @@" in project_response.text
    assert "Selected file" in project_response.text and "src/service.py" in project_response.text
    assert response.status_code == 200
    assert "target HEAD" in response.text and "active" in response.text and "Selected file" in response.text
    assert "integration_verification_failed" in response.text
    assert "delete" not in response.text.casefold()
    diff_calls = [call for call in explorer.calls if urlsplit(call).path == "/api/admin/git/diff"]
    assert diff_calls and parse_qs(urlsplit(diff_calls[-1]).query)["path"] == ["src/service.py"]


# START_FUNCTION_CONTRACT
# name: test_stage05_leases_mask_tokens_and_raw_keeps_unknown_fields
# purpose: Prove lease DTOs expose fingerprints only and packet Raw retains an
#          unknown source field.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails on secret token leakage or raw field loss.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_leases_mask_tokens_and_raw_keeps_unknown_fields():
    app, _ = _app(alpha_client=_ExplorerClient("alpha"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        system = await client.get("/admin/p/alpha/system")
        raw = await client.get("/admin/p/alpha/packet/shared-packet", params={"tab": "raw"})
    assert "full-fencing-token-alpha" not in system.text
    assert "fp-merge" in system.text
    assert "unknown_extra" in raw.text and '"keep": true' in raw.text


# START_FUNCTION_CONTRACT
# name: test_stage05_openapi_is_dynamic_get_only_and_allowlisted
# purpose: Prove newly discovered OpenAPI paths appear without hard-coded UI,
#          exact GET execution works, arbitrary paths do not execute and
#          mutation operations remain disabled.
# inputs: None.
# returns: None.
# side_effects: Performs ASGI GET requests.
# emitted_logs: None.
# error_behavior: Fails if arbitrary or mutating browser execution is allowed.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_stage05_openapi_is_dynamic_get_only_and_allowlisted():
    explorer = _ExplorerClient("alpha")
    app, _ = _app(alpha_client=explorer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub.test") as client:
        page = await client.get("/admin/p/alpha/api")
        executed = await client.get("/admin/p/alpha/api", params={"path": "/api/synthetic-new-endpoint", "execute": "true"})
        executed_item = await client.get(
            "/admin/p/alpha/api",
            params={
                "path": "/api/items/{item_id}",
                "execute": "true",
                "params": '{"item_id":"item-7","limit":"10"}',
            },
        )
        missing_item = await client.get(
            "/admin/p/alpha/api",
            params={"path": "/api/items/{item_id}", "execute": "true", "params": '{"limit":"10"}'},
        )
        undeclared_item = await client.get(
            "/admin/p/alpha/api",
            params={"path": "/api/items/{item_id}", "execute": "true", "params": '{"item_id":"item-7","evil":"x"}'},
        )
        rejected = await client.get("/admin/p/alpha/api", params={"path": "/api/not-discovered", "execute": "true"})
    assert "/api/synthetic-new-endpoint" in page.text and "POST" in page.text and "execution disabled" in page.text
    assert "discovered" in executed.text and "content-type" in executed.text
    assert "item-7" in executed_item.text and "limit" in executed_item.text and "/api/items/item-7" in executed_item.text
    assert "API_PATH_PARAM_REQUIRED" in missing_item.text
    assert "API_PARAMS_UNDECLARED" in undeclared_item.text
    assert "API_PATH_NOT_DISCOVERED" in rejected.text
    assert not any(urlsplit(call).path == "/api/not-discovered" for call in explorer.calls)
    assert not any(urlsplit(call).path == "/api/items/{item_id}" for call in explorer.calls)


# START_FUNCTION_CONTRACT
# name: explorer_browser
# purpose: Launch a bounded Playwright browser for the Stage 05 follow behavior
#          acceptance test.
# inputs: None.
# returns: Headless browser instance.
# side_effects: Starts and stops a local browser process.
# emitted_logs: None.
# error_behavior: Explicitly skips when Playwright, Chromium or the configured
#                 browser acceptance server is unavailable.
# END_FUNCTION_CONTRACT
@pytest.fixture(scope="module")
def explorer_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip(f"Stage 05 browser follow skipped: Playwright unavailable ({exc})")
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
    except Exception as exc:
        if "playwright" in locals():
            playwright.stop()
        pytest.skip(f"Stage 05 browser follow skipped: Chromium unavailable ({exc})")
    try:
        yield browser
    finally:
        browser.close()
        playwright.stop()


# START_FUNCTION_CONTRACT
# name: test_stage05_logs_follow_browser_preserves_scrolled_position
# purpose: Prove real Follow polling markup and the browser scroll guard preserve
#          an operator's away-from-bottom position during an HTMX swap.
# inputs: explorer_browser — headless browser fixture.
# returns: None.
# side_effects: Reads the configured local Control Center browser endpoint.
# emitted_logs: None.
# error_behavior: Explicitly skips when the local server does not expose Stage
#                 05 Logs; fails if follow polling jumps the viewport.
# END_FUNCTION_CONTRACT
def test_stage05_logs_follow_browser_preserves_scrolled_position(explorer_browser):
    base_url = os.environ.get("GRACE_BASE_URL", "http://127.0.0.1:8042")
    page = explorer_browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        try:
            response = page.goto(
                f"{base_url}/admin/logs?project=alpha&tail=100&follow=true",
                wait_until="domcontentloaded",
                timeout=5000,
            )
        except Exception as exc:
            pytest.skip(f"Stage 05 browser follow skipped: server unavailable at {base_url} ({exc})")
        if response is None or response.status >= 400:
            pytest.skip(f"Stage 05 browser follow skipped: Logs returned {response.status if response else 'no response'}")
        try:
            page.wait_for_selector('[data-testid="bounded-log-viewer"]', timeout=5000)
        except Exception as exc:
            pytest.skip(f"Stage 05 browser follow skipped: Logs viewer unavailable ({exc})")
        assert page.locator('[data-testid="bounded-log-viewer"]').get_attribute("data-follow") == "on"
        assert page.locator('[data-testid="bounded-log-viewer"]').get_attribute("hx-trigger") == "every 5s"
        state = page.evaluate(
            """() => {
              const viewer = document.querySelector('[data-testid="bounded-log-viewer"]');
              const list = viewer.querySelector('.cc-log-list');
              list.innerHTML = Array.from({length: 40}, (_, index) =>
                `<article class="log-row"><div style="height:24px">synthetic-${index}</div></article>`
              ).join('');
              list.style.height = '100px';
              list.style.maxHeight = '100px';
              list.style.overflowY = 'auto';
              list.scrollTop = Math.floor(list.scrollHeight / 2);
              const before = list.scrollTop;
              document.body.dispatchEvent(new CustomEvent('htmx:beforeSwap', {bubbles: true}));
              viewer.outerHTML = viewer.outerHTML;
              document.body.dispatchEvent(new CustomEvent('htmx:afterSwap', {bubbles: true}));
              return {
                before,
                after: document.querySelector('[data-testid="bounded-log-viewer"] .cc-log-list').scrollTop,
              };
            }"""
        )
        assert state["before"] > 0
        assert state["after"] == state["before"]
    finally:
        page.close()


# END_BLOCK_ACCEPTANCE
