# ############################################################################
# AI_HEADER: test_project_read_surface — Stage 02 project read acceptance
# ROLE: Proves the project-local read boundary for raw diagnostics, events,
#       leases, safe filesystem reads, Git reads, OpenAPI and capabilities.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Exercise the complete Task 008 read surface with real temporary
#          directories, symlinks, SQLite rows and a temporary Git repository.
# inputs: Pytest temporary paths and isolated local application state.
# returns: Passing acceptance assertions for the project-local API contract.
# side_effects: Creates temporary files, a temporary SQLite database and Git
#               repository; all are removed by pytest fixtures.
# emitted_logs: None directly; service logs are captured by the test runner.
# error_behavior: Fails when data is incomplete, unsafe paths are accepted or
#                 optional capabilities break the project response.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_project_raw_models_preserve_result_json_and_logical_stage_paths
#   - function: test_events_and_diagnostics_are_complete_without_fencing_token
#   - function: test_safe_filesystem_service_enforces_realpath_and_limits
#   - function: test_safe_filesystem_api_returns_typed_expected_errors
#   - function: test_git_read_service_uses_real_repository_and_rejects_unsafe_inputs
#   - function: test_project_client_retrieves_openapi
#   - function: test_optional_capability_is_unavailable_not_broken
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db, init_db
from grace_control.db.schema import Event, MergeLease, Packet, PacketRun, ParallelLease, StageRun
from grace_control.services.admin_git_read_service import AdminGitReadService, GitReadError
from grace_control.services.capability_service import CapabilityService
from grace_control.services.project_client import ProjectClient
from grace_control.services.safe_filesystem_service import (
    FilesystemReadError,
    SafeFilesystemService,
)

_log = GraceLogger("test_project_read_surface")


# START_BLOCK_FIXTURES
# START_FUNCTION_CONTRACT
# name: read_surface
# purpose: Build an isolated application and safe operational root for tests.
# inputs: tmp_path, monkeypatch — pytest temporary/config fixtures.
# returns: (FastAPI app, Path) test resources.
# side_effects: Initializes a temporary SQLite database and local directories.
# emitted_logs: None.
# error_behavior: Fixture setup propagates initialization failures.
# END_FUNCTION_CONTRACT
@pytest.fixture
def read_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    db_url = f"sqlite:///{tmp_path / 'project-read.db'}"
    monkeypatch.setenv("GRACE_DB_URL", db_url)
    init_db(db_url)
    root = tmp_path / "operational"
    root.mkdir()
    app = create_app()
    app.__dict__["state"].project_filesystem_service = SafeFilesystemService(
        {"state": root},
        max_preview_bytes=32,
        max_tail_lines=4,
        max_tail_bytes=64,
    )
    return app, root


# START_FUNCTION_CONTRACT
# name: seeded_read_surface
# purpose: Seed packet/run/stage/lease/event rows for read-surface tests.
# inputs: read_surface — isolated app/root fixture.
# returns: (FastAPI app, Path) with persisted diagnostic data.
# side_effects: Inserts temporary SQLite rows and writes small test artifacts.
# emitted_logs: None.
# error_behavior: Fixture setup propagates database errors.
# END_FUNCTION_CONTRACT
@pytest.fixture
def seeded_read_surface(read_surface):
    app, root = read_surface
    now = datetime.now(UTC).replace(tzinfo=None)
    with get_db() as db:
        packet = Packet(
            id="pkt-read-01",
            feature_id="feat-read-01",
            wave_id="wave-read-01",
            slug="read",
            title="Read packet",
            spec_json={
                "scope": ["src/service/"],
                "conflict_keys": ["db:users"],
                "depends_on": ["pkt-upstream"],
            },
            state="running",
            attempt_count=2,
            max_attempts=5,
            acceptance_profile="NORMAL",
        )
        run = PacketRun(
            id="pkt-read-01-r1",
            packet_id=packet.id,
            run_number=1,
            status="failed",
            executor_id="executor-read",
            worker_id="worker-read",
            result_json={
                "opaque_result": {"keep": True, "nested": [1, 2, 3]},
                "parallel_execution": {"integration_recheck": "passed"},
            },
            prompt="prompt metadata",
            command_preview=["pytest", "-q"],
            tokens_in=11,
            tokens_out=22,
            cost_usd=1.25,
            base_sha="base-read",
            integration_base_sha="integration-read",
            evidence_path=str(root),
        )
        stage = StageRun(
            id="stage-read-01",
            packet_id=packet.id,
            run_id=run.id,
            feature_id=packet.feature_id,
            wave_id=packet.wave_id,
            stage_key="coder",
            status="failed",
            executor_id="executor-read",
            worker_id="worker-read",
            model="model-read",
            stdout_path=str(root / "stdout.log"),
            stderr_path=str(root / "stderr.log"),
            result_path=str(root / "result.json"),
            artifacts_dir=str(root / "artifacts"),
            recovery_reason="test recovery",
        )
        parallel = ParallelLease(
            id="pleas-read-01",
            packet_id=packet.id,
            feature_id=packet.feature_id,
            wave_id=packet.wave_id,
            worker_id="worker-read",
            claimed_attempt=2,
            scope_json=["src/service/"],
            conflict_keys_json=["db:users"],
            base_sha="base-read",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            heartbeat_at=now,
        )
        merge = MergeLease(
            target_repo_key="repo-read",
            lease_token="secret-fencing-token-must-not-leak",
            packet_id=packet.id,
            worker_id="worker-read",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            heartbeat_at=now,
        )
        event = Event(
            event_type="packet_failed",
            entity_type="packet",
            entity_id=packet.id,
            trace_id="trace-read-01",
            payload_json={
                "component": "worker",
                "reason": "bounded test failure",
                "complete": {"value": 7},
            },
        )
        db.add_all([packet, run, stage, parallel, merge, event])
        db.commit()
    (root / "stdout.log").write_text("stdout\n", encoding="utf-8")
    (root / "stderr.log").write_text("stderr\n", encoding="utf-8")
    (root / "result.json").write_text('{"ok": true}\n', encoding="utf-8")
    (root / "artifacts").mkdir()
    return app, root


# END_BLOCK_FIXTURES


# START_BLOCK_API_TESTS
# START_FUNCTION_CONTRACT
# name: test_project_raw_models_preserve_result_json_and_logical_stage_paths
# purpose: Prove raw packet/run/stage data keeps spec/result/cost and logical
#          resources without returning physical stage paths.
# inputs: seeded_read_surface fixture.
# returns: None.
# side_effects: Performs local ASGI requests.
# emitted_logs: None.
# error_behavior: Fails on dropped raw fields or absolute path leakage.
# END_FUNCTION_CONTRACT
def test_project_raw_models_preserve_result_json_and_logical_stage_paths(seeded_read_surface):
    app, _root = seeded_read_surface
    client = TestClient(app)
    packet = client.get("/api/admin/packet/pkt-read-01/raw")
    assert packet.status_code == 200
    body = packet.json()
    assert body["packet"]["conflict_keys"] == ["db:users"]
    assert body["packet"]["depends_on"] == ["pkt-upstream"]
    assert body["runs"][0]["result_json"]["opaque_result"]["keep"] is True
    run = client.get("/api/admin/packet/pkt-read-01/runs/r1/raw")
    assert run.status_code == 200
    assert run.json()["tokens_out"] == 22
    stage = client.get("/api/admin/stage/stage-read-01/raw")
    assert stage.status_code == 200
    stage_body = stage.json()
    assert stage_body["logical_paths"]["stdout"]["resource"] == "stage_stdout"
    assert str(_root) not in str(stage_body)


# START_FUNCTION_CONTRACT
# name: test_events_and_diagnostics_are_complete_without_fencing_token
# purpose: Prove event filters/pagination/payload and lease diagnostics.
# inputs: seeded_read_surface fixture.
# returns: None.
# side_effects: Performs local ASGI requests.
# emitted_logs: None.
# error_behavior: Fails when payload or lease safety metadata is incomplete.
# END_FUNCTION_CONTRACT
def test_events_and_diagnostics_are_complete_without_fencing_token(seeded_read_surface):
    app, _root = seeded_read_surface
    client = TestClient(app)
    events = client.get(
        "/api/events",
        params={"entity_id": "pkt-read-01", "trace_id": "trace-read-01", "limit": 1, "offset": 0},
    )
    assert events.status_code == 200
    event = events.json()["data"]["events"][0]
    assert event["payload_json"]["complete"]["value"] == 7
    assert event["payload"] == event["payload_json"]
    diagnostics = client.get("/api/diagnostics/state")
    assert diagnostics.status_code == 200
    state = diagnostics.json()["data"]
    assert state["active_parallel_leases"][0]["conflict_keys"] == ["db:users"]
    assert state["active_merge_leases"][0]["target_repo_key"] == "repo-read"
    assert "secret-fencing-token" not in diagnostics.text


# END_BLOCK_API_TESTS


# START_BLOCK_FILESYSTEM_TESTS
# START_FUNCTION_CONTRACT
# name: test_safe_filesystem_service_enforces_realpath_and_limits
# purpose: Prove allowed roots, bounded previews/tails, binary handling,
#          traversal, secrets and symlink escape using real temporary paths.
# inputs: tmp_path — real temporary filesystem.
# returns: None.
# side_effects: Creates files and a symlink under tmp_path.
# emitted_logs: None.
# error_behavior: Fails if an unsafe path is readable or a limit is ignored.
# END_FUNCTION_CONTRACT
def test_safe_filesystem_service_enforces_realpath_and_limits(tmp_path):
    root = tmp_path / "state"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "large.log").write_text("line\n" * 100, encoding="utf-8")
    (root / "binary.bin").write_bytes(b"a\x00b\xff")
    (root / ".env").write_text("TOKEN=hidden", encoding="utf-8")
    symlink = root / "escape"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError:
        symlink = None
    service = SafeFilesystemService(
        {"state": root}, max_preview_bytes=16, max_tail_lines=3, max_tail_bytes=24
    )
    assert service.list_roots()[0]["root"] == "state"
    preview = service.read_file("state", "large.log")
    assert preview["truncated"] is True
    assert len(preview["content"].encode("utf-8")) <= 16
    tail = service.tail_file("state", "large.log", lines=2)
    assert len(tail["content"].splitlines()) == 2
    binary = service.read_file("state", "binary.bin")
    assert binary["binary"] is True and binary["content"] is None
    for path, code in (("../outside", "PATH_TRAVERSAL"), (".env", "SECRET_PATH_DENIED")):
        with pytest.raises(FilesystemReadError) as error:
            service.stat("state", path)
        assert error.value.code == code
    if symlink is not None:
        with pytest.raises(FilesystemReadError) as error:
            service.stat("state", "escape")
        assert error.value.code == "SYMLINK_ESCAPE"


# START_FUNCTION_CONTRACT
# name: test_safe_filesystem_api_returns_typed_expected_errors
# purpose: Prove missing files and traversal are HTTP errors, not 500 responses.
# inputs: read_surface fixture.
# returns: None.
# side_effects: Performs local ASGI requests.
# emitted_logs: None.
# error_behavior: Fails if expected read errors become internal errors.
# END_FUNCTION_CONTRACT
def test_safe_filesystem_api_returns_typed_expected_errors(read_surface):
    app, root = read_surface
    (root / "ok.txt").write_text("ok\n", encoding="utf-8")
    client = TestClient(app)
    assert client.get("/api/admin/fs/list", params={"root": "state"}).status_code == 200
    missing = client.get("/api/admin/fs/file", params={"root": "state", "path": "missing"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "PATH_NOT_FOUND"
    traversal = client.get("/api/admin/fs/file", params={"root": "state", "path": "../ok.txt"})
    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "PATH_TRAVERSAL"


# END_BLOCK_FILESYSTEM_TESTS


# START_BLOCK_GIT_TESTS
# START_FUNCTION_CONTRACT
# name: test_git_read_service_uses_real_repository_and_rejects_unsafe_inputs
# purpose: Prove changed files/diff/stat/tracked file reads and unsafe input
#          rejection against a real isolated Git repository.
# inputs: tmp_path — temporary repository root.
# returns: None.
# side_effects: Runs Git commands in the temporary repository.
# emitted_logs: None.
# error_behavior: Fails if Git read validation or bounded outputs regress.
# END_FUNCTION_CONTRACT
def test_git_read_service_uses_real_repository_and_rejects_unsafe_inputs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)

    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    (repo / "src").mkdir()
    (repo / "src/a.txt").write_text("one\n", encoding="utf-8")
    run("git", "add", "src/a.txt")
    run("git", "commit", "-qm", "initial")
    (repo / "src/a.txt").write_text("two\n", encoding="utf-8")
    (repo / "src/b.txt").write_text("new\n", encoding="utf-8")
    run("git", "add", "src")
    run("git", "commit", "-qm", "second")

    service = AdminGitReadService(repo, target_branch="main", base_branch="HEAD~1")
    assert service.repository()["current_branch"] == "main"
    assert len(service.changed_files("HEAD~1")) == 2
    assert "src/a.txt" in service.diff_stat("HEAD~1")["text"]
    assert "+two" in service.diff("HEAD~1", "src/a.txt")["text"]
    assert "src/a.txt" in service.tracked_files()["files"]
    assert service.show_file("HEAD", "src/a.txt")["content"] == "two\n"
    with pytest.raises((GitReadError, ValueError)):
        service.changed_files("--output=/tmp/leak")
    with pytest.raises(GitReadError):
        service.show_file("HEAD", "../outside")


# END_BLOCK_GIT_TESTS


# START_BLOCK_DISCOVERY_TESTS
# START_FUNCTION_CONTRACT
# name: test_project_client_retrieves_openapi
# purpose: Prove OpenAPI retrieval crosses the same bounded ProjectClient API.
# inputs: None; uses an in-memory HTTPX transport.
# returns: None.
# side_effects: Performs one in-memory HTTP request.
# emitted_logs: None.
# error_behavior: Fails if get_openapi uses a hand-maintained registry or wrong path.
# END_FUNCTION_CONTRACT
def test_project_client_retrieves_openapi():
    context = ProjectContext(
        key="read",
        name="Read",
        enabled=True,
        unix_user=None,
        project_root=Path("/tmp/read-project"),
        api_url="http://read.example.test",
        api_socket=None,
        description="",
        tags=(),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openapi.json"
        return httpx.Response(200, json={"openapi": "3.1.0", "paths": {}})

    async def exercise() -> None:
        client = ProjectClient(context, transport=httpx.MockTransport(handler))
        result = await client.get_openapi()
        assert result.ok is True
        assert result.payload["openapi"] == "3.1.0"

    asyncio.run(exercise())


# START_FUNCTION_CONTRACT
# name: test_optional_capability_is_unavailable_not_broken
# purpose: Prove optional schema inspection failure returns explicit
#          unavailable capability flags and no exception.
# inputs: None; monkeypatches local inspection failure.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails if optional absence raises or is reported as available.
# END_FUNCTION_CONTRACT
def test_optional_capability_is_unavailable_not_broken(monkeypatch):
    def unavailable(_bind):
        raise RuntimeError("optional schema unavailable")

    monkeypatch.setattr("grace_control.services.capability_service.inspect", unavailable)
    document = CapabilityService().document(None)
    assert document["capabilities"]["sessions"] is False
    assert "sessions" in document["unavailable"]
    assert document["capabilities"]["filesystem"] is True


# END_BLOCK_DISCOVERY_TESTS
