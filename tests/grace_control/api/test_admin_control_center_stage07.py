# ############################################################################
# AI_HEADER: test_admin_control_center_stage07 — final Admin Hub integration acceptance
# ROLE: Proves Stage 07 against two independent project runtimes, real SQLite
#       databases, filesystem roots and Git repositories, then covers failure,
#       control, UI and boundedness behavior at the Hub boundary.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute the final Admin Control Center integration and acceptance
#          proof required by TZ07 without opening project state from the Hub.
# inputs: Pytest temporary roots, real project API subprocesses, immutable Hub
#          registry contexts and deterministic failure clients.
# returns: Passing assertions for topology, journeys, security, OpenAPI,
#          controls, UI and performance contracts.
# side_effects: Creates temporary SQLite databases, Git repositories, runtime
#               files and short-lived local API/browser subprocesses.
# emitted_logs: Structured service logs are captured by pytest; this module
#               emits no application log events itself.
# error_behavior: Fails on cross-project data/routing, unsafe reads, fake
#                 control success, unbounded responses or missing acceptance.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_stage07_real_topology_isolation_and_control
#   - function: test_stage07_complete_read_surface_and_operator_journeys
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import inspect

from grace_control.api.app_factory import create_app
from grace_control.config.project_registry import ProjectRegistry
from grace_control.config.settings import GraceSettings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    AgentSession,
    Event,
    Feature,
    FeaturePlanningRun,
    Lease,
    MergeLease,
    Packet,
    PacketRun,
    ParallelLease,
    StageRun,
    Wave,
    Worker,
)
from grace_control.services.admin_cross_project_service import AdminCrossProjectService
from grace_control.services.project_client import ProjectApiResult, ProjectClient

_log = GraceLogger("test_admin_control_center_stage07")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED_PACKET_ID = "pkt-shared-stage07"
_CONTROL_PACKET_ID = "pkt-control-stage07"
_RUN_SUFFIX = "-run-1"


# START_BLOCK_REAL_TOPOLOGY
# START_FUNCTION_CONTRACT
# name: _git
# purpose: Run one Git fixture command in a temporary target repository.
# inputs: repo — temporary repository root; args — Git command arguments.
# returns: Completed subprocess result.
# side_effects: Updates only the temporary fixture repository during setup.
# emitted_logs: None.
# error_behavior: Raises CalledProcessError when fixture setup cannot continue.
# END_FUNCTION_CONTRACT
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )


# START_FUNCTION_CONTRACT
# name: _free_port
# purpose: Return an unused loopback port for one temporary API process.
# inputs: None.
# returns: Positive loopback port number.
# side_effects: Briefly binds and closes one temporary socket.
# emitted_logs: None.
# error_behavior: Propagates socket errors.
# END_FUNCTION_CONTRACT
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# START_FUNCTION_CONTRACT
# name: _write_project_config
# purpose: Write one project-local config consumed by the real runtime process.
# inputs: root, key, port and database — isolated project values.
# returns: None.
# side_effects: Writes a temporary `.grace/config.yaml`.
# emitted_logs: None.
# error_behavior: Filesystem errors propagate.
# END_FUNCTION_CONTRACT
def _write_project_config(root: Path, key: str, port: int, database: Path) -> None:
    config = {
        "project": {"key": key, "name": key.title()},
        "api": {"host": "127.0.0.1", "port": port},
        "database": {"url": f"sqlite:///{database}"},
        "git": {"remote": "origin", "base_branch": "main", "target_branch": "main"},
        "execution": {
            "backend": "mock",
            "state_root": ".grace/state",
            "worktree_root": ".grace/worktrees",
            "target_repo_root": str(root),
        },
    }
    (root / ".grace" / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8",
    )


# START_FUNCTION_CONTRACT
# name: _prepare_project
# purpose: Build one independent target Git repository and its state,
#          worktree, artifact and evidence roots.
# inputs: root — isolated project root; key — registry key; port — API port.
# returns: Fixture mapping with absolute database and operational paths.
# side_effects: Creates files, commits Git history and adds one worktree.
# emitted_logs: None.
# error_behavior: Propagates setup errors; no external repository is touched.
# END_FUNCTION_CONTRACT
def _prepare_project(root: Path, key: str, port: int) -> dict[str, Any]:
    root.mkdir(parents=True)
    grace_root = root / ".grace"
    state_root = grace_root / "state"
    worktree_root = grace_root / "worktrees"
    runs_root = grace_root / "runs"
    logs_root = grace_root / "logs"
    for path in (state_root, worktree_root, runs_root, logs_root):
        path.mkdir(parents=True)
    (logs_root / "service.log").write_text(f"log-{key}\n" * 20, encoding="utf-8")
    database = root / f"{key}.db"
    _write_project_config(root, key, port, database)
    (root / ".gitignore").write_text(
        ".grace/state/\n.grace/worktrees/\n.grace/runs/\n.grace/logs/\n", encoding="utf-8",
    )
    source = root / "src"
    source.mkdir()
    (source / f"{key}.txt").write_text(f"base-{key}\n", encoding="utf-8")
    (root / "README.md").write_text(f"# {key.title()} Stage 07 fixture\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "stage07@example.test")
    _git(root, "config", "user.name", "Stage 07 Fixture")
    _git(root, "add", ".gitignore", ".grace/config.yaml", "README.md", "src")
    _git(root, "commit", "-qm", f"base {key}")
    (source / f"{key}.txt").write_text(f"changed-{key}\n", encoding="utf-8")
    (root / "large.txt").write_text("0123456789abcdef\n" * 140000, encoding="utf-8")
    _git(root, "add", "src", "large.txt")
    _git(root, "commit", "-qm", f"change {key}")
    _git(root, "worktree", "add", "--detach", str(worktree_root / f"{key}-inspect"), "HEAD~1")

    run_root = runs_root / f"{key}-run-1"
    run_root.mkdir()
    (run_root / "stdout.log").write_text(f"stdout-{key}\n" * 40, encoding="utf-8")
    (run_root / "stderr.log").write_text(f"stderr-{key}\n" * 40, encoding="utf-8")
    (run_root / "agent_output.log").write_text(f"agent-{key}\n" * 40, encoding="utf-8")
    (run_root / "report.md").write_text(f"# Evidence {key}\n\npassed\n", encoding="utf-8")
    (run_root / "raw-evidence.json").write_text(
        '{"source":"stage07","project":"' + key + '","bounded":true}\n', encoding="utf-8",
    )
    (run_root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"image")
    (run_root / "binary.bin").write_bytes(b"\x00\x01\x02\xff" * 32)
    (run_root / "large-artifact.log").write_text("artifact\n" * 4000, encoding="utf-8")

    outside = root.parent / f"{key}-outside"
    outside.mkdir()
    (outside / "private.txt").write_text(f"private-{key}\n", encoding="utf-8")
    (state_root / ".env").write_text("TOKEN=must-not-read\n", encoding="utf-8")
    (state_root / "id_rsa").write_text("PRIVATE KEY\n", encoding="utf-8")
    (state_root / "large.log").write_text("line\n" * 5000, encoding="utf-8")
    (state_root / "binary.bin").write_bytes(b"\x00\xff" * 256)
    escape = state_root / "escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        escape = None

    return {
        "key": key,
        "name": key.title(),
        "root": root,
        "database": database,
        "state_root": state_root,
        "worktree_root": worktree_root,
        "run_root": run_root,
        "outside": outside,
        "escape": escape,
        "port": port,
        "api_url": f"http://127.0.0.1:{port}",
        "process": None,
    }


# START_FUNCTION_CONTRACT
# name: _seed_project_database
# purpose: Populate one independent SQLite database with Feature/Wave/Packet,
#          runs/stages/sessions/events, leases and stale-base evidence.
# inputs: fixture — mapping returned by `_prepare_project`.
# returns: None.
# side_effects: Inserts rows into only the selected fixture database.
# emitted_logs: Database initialization logs may be emitted by the runtime.
# error_behavior: Propagates migration or insert errors.
# END_FUNCTION_CONTRACT
def _seed_project_database(fixture: dict[str, Any]) -> None:
    key = str(fixture["key"])
    run_root = Path(fixture["run_root"])
    init_db(f"sqlite:///{fixture['database']}")
    now = datetime.now(UTC).replace(tzinfo=None)
    feature_id = f"feat-{key}-stage07"
    wave_id = f"wave-{key}-stage07"
    session_external_id = f"ses_{key}07"

    def packet(packet_id: str, title: str, state: str, spec: dict[str, Any]) -> Packet:
        return Packet(
            id=packet_id, feature_id=feature_id, wave_id=wave_id,
            slug=packet_id.lower(), title=title, description=f"Stage 07 {key} packet",
            spec_json=spec, state=state, acceptance_profile="STRICT",
            attempt_count=1, max_attempts=3,
        )

    shared = packet(
        _SHARED_PACKET_ID, f"Shared merged packet {key.title()}", "merged",
        {"scope": [f"src/{key}.txt"], "conflict_keys": [f"db:{key}", f"repo:{key}"],
         "base_sha": f"base-{key}", "integration_base_sha": f"head-{key}",
         "integration_recheck": "passed"},
    )
    control = packet(
        _CONTROL_PACKET_ID, f"Control packet {key}", "blocked_recoverable",
        {"scope": [f"src/{key}.txt"], "conflict_keys": [f"control:{key}"],},
    )
    blocked_id = f"pkt-{key}-blocked"
    blocked = packet(
        blocked_id, f"Blocked diagnosis packet {key}", "blocked_final",
        {"scope": [f"src/{key}.txt"], "conflict_keys": [f"failure:{key}"],},
    )
    stale_id = f"pkt-{key}-stale"
    stale = packet(
        stale_id, f"Stale base packet {key}", "accepted",
        {"scope": [f"src/{key}.txt"], "conflict_keys": [f"stale:{key}"],
         "base_sha": f"base-{key}", "integration_base_sha": f"head-{key}",
         "stale_base": True, "stale_base_recheck": "failed",
         "integration_recheck": "failed", "failure_class": "stale_base_conflict"},
    )
    running_id = f"pkt-{key}-running"
    running = packet(
        running_id, f"Running parallel packet {key}", "running",
        {"scope": [f"src/{key}.txt"], "conflict_keys": [f"parallel:{key}"],},
    )

    passed_result = {
        "acceptance_report": {"final_verdict": "PASS", "summary": f"healthy {key} acceptance",
            "stages": [{"name": "T1_UNIT_TESTS", "status": "passed", "summary": "all tests passed",
                         "commands": [{"command": "pytest -q", "exit_code": 0, "stdout": "passed"}]}]},
        "parallel_execution": {"base_sha": f"base-{key}", "integration_base_sha": f"head-{key}",
                                "integration_recheck": "passed"},
        "legacy_result": {"exit_code": 0, "evidence": {"session_id": session_external_id}},
    }
    failure_result = {
        "recovery": {"failure_class": "acceptance_failure", "action": "block", "reason": f"{key} failed T1"},
        "acceptance_report": {"final_verdict": "FAIL", "summary": f"{key} T1 failed", "stages": [{
            "name": "T1_UNIT_TESTS", "status": "failed", "summary": "assertion failure",
            "blocking_issues": ["test assertion failed"],
            "commands": [{"command": "pytest -q", "exit_code": 1,
                           "stderr": f"stderr-{key} failure tail", "stdout": f"stdout-{key} failure tail"}],
            "stderr_tail": f"stderr-{key} failure tail",
        }]},
        "legacy_result": {"exit_code": 1, "stderr": f"stderr-{key} failure tail"},
    }
    stale_result = {"parallel_execution": {
        "base_sha": f"base-{key}", "integration_base_sha": f"head-{key}",
        "integration_recheck": "failed", "failure_class": "stale_base_conflict",
        "integration_recheck_evidence": {"reason": "target advanced"},
    }}

    def run_row(
        packet_row: Packet,
        status: str,
        result: dict[str, Any],
        *,
        run_number: int = 1,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        base_sha: str | None = None,
        integration_base_sha: str | None = None,
    ) -> PacketRun:
        return PacketRun(
            id=f"{packet_row.id}-run-{run_number}", packet_id=packet_row.id, run_number=run_number,
            executor_id=f"executor-{key}", worker_id=f"worker-{key}", status=status,
            result_json=result, evidence_path=str(run_root),
            started_at=started_at or now - timedelta(minutes=2), finished_at=finished_at,
            duration_ms=1000, base_sha=base_sha, integration_base_sha=integration_base_sha,
            model="stage07-model", command_preview=["pytest", "-q"], prompt=f"prompt-{key}",
            tokens_in=100, tokens_out=50, cost_usd=0.25,
        )

    shared_run = run_row(shared, "accepted", passed_result, started_at=now - timedelta(seconds=20),
                          finished_at=now - timedelta(seconds=5),
                          base_sha=f"base-{key}", integration_base_sha=f"head-{key}")
    shared_run.duration_ms = 15000
    control_run = run_row(control, "failed", {"reason": "retryable control fixture"})
    blocked_run = run_row(blocked, "failed", failure_result)
    stale_run = run_row(stale, "accepted", stale_result, finished_at=now - timedelta(minutes=1),
                         base_sha=f"base-{key}", integration_base_sha=f"head-{key}")
    running_run = run_row(running, "running", {}, finished_at=None)

    common_stage = {
        "feature_id": feature_id, "wave_id": wave_id, "attempt_number": 1, "loop_round": 1,
        "executor_id": f"executor-{key}", "worker_id": f"worker-{key}", "model": "stage07-model",
        "stdout_path": str(run_root / "stdout.log"), "stderr_path": str(run_root / "stderr.log"),
        "result_path": str(run_root / "raw-evidence.json"), "artifacts_dir": str(run_root),
        "trace_id": f"trace-{key}",
    }
    stages = [
        StageRun(id=f"stage-{key}-shared", packet_id=shared.id, run_id=shared_run.id,
                 stage_key="coder", status="completed", duration_ms=15000, **common_stage),
        StageRun(id=f"stage-{key}-blocked", packet_id=blocked.id, run_id=blocked_run.id,
                 stage_key="t1_tests", status="failed", duration_ms=1000,
                 error=f"{key} assertion failure", recovery_reason="block after failed T1", **common_stage),
        StageRun(id=f"stage-{key}-stale", packet_id=stale.id, run_id=stale_run.id,
                 stage_key="integration_recheck", status="failed", duration_ms=1000,
                 error="target advanced", recovery_reason="stale base", **common_stage),
    ]
    feature = Feature(id=feature_id, slug=f"feature-{key}", title=f"Feature {key}",
                      description=f"Rich Stage 07 feature for {key}", spec_json={"operator_journey": True}, status="DONE")
    wave = Wave(id=wave_id, feature_id=feature_id, slug=f"wave-{key}", title=f"Wave {key}",
                description="Stage 07 wave", order=1, status="DONE")
    worker = Worker(id=f"worker-{key}", status="active", current_packet_id=running.id,
                    last_heartbeat=now, started_at=now - timedelta(minutes=10))
    planning = [
        FeaturePlanningRun(id=f"plan-{key}-architect", feature_id=feature_id, stage="architect", status="done",
                           started_at=now - timedelta(minutes=10), finished_at=now - timedelta(minutes=9),
                           duration_ms=1000, executor_id=f"architect-{key}", result_json={"status": "planned"}),
        FeaturePlanningRun(id=f"plan-{key}-context", feature_id=feature_id, stage="context_builder", status="done",
                           started_at=now - timedelta(minutes=11), finished_at=now - timedelta(minutes=10),
                           duration_ms=1000, executor_id=f"context-{key}", result_json={"status": "built"}),
    ]
    session = AgentSession(id=f"ses-{key}-internal", external_id=session_external_id, packet_id=shared.id,
                           run_id=shared_run.id, role="coder", executor_id=f"executor-{key}", backend="cli",
                           attempt_number=1, status="completed", created_at=now - timedelta(seconds=25),
                           finished_at=now - timedelta(seconds=5))
    ordinary = Lease(packet_id=running.id, worker_id=worker.id, claimed_attempt=1,
                     acquired_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=4), heartbeat_at=now)
    parallel = ParallelLease(id=f"parallel-{key}", packet_id=running.id, feature_id=feature_id, wave_id=wave_id,
                             worker_id=worker.id, claimed_attempt=1, scope_json=[f"src/{key}.txt"],
                             conflict_keys_json=[f"parallel:{key}"], base_sha=f"base-{key}",
                             acquired_at=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=4), heartbeat_at=now)
    merge = MergeLease(target_repo_key=f"repo-{key}", lease_token=f"secret-fencing-{key}", packet_id=running.id,
                       worker_id=worker.id, acquired_at=now - timedelta(minutes=1),
                       expires_at=now + timedelta(minutes=4), heartbeat_at=now)
    event_rows = [
        Event(timestamp=now - timedelta(seconds=30), event_type="packet_started", entity_type="packet",
              entity_id=shared.id, trace_id=f"trace-{key}",
              payload_json={"component": "worker", "reason": f"{key} started", "full": {"project": key}}),
        Event(timestamp=now - timedelta(seconds=20), event_type="packet_transition", entity_type="packet",
              entity_id=shared.id, trace_id=f"trace-{key}",
              payload_json={"component": "merge", "reason": "release:accepted", "from": "accepted", "to": "merged"}),
        Event(timestamp=now - timedelta(seconds=10), event_type="packet_merged", entity_type="packet",
              entity_id=shared.id, trace_id=f"trace-{key}",
              payload_json={"component": "merge", "reason": f"{key} merged", "commit_sha": f"commit-{key}"}),
        Event(timestamp=now - timedelta(minutes=5), event_type="recovery_decision_made", entity_type="packet",
              entity_id=blocked.id, trace_id=f"trace-{key}-blocked",
              payload_json={"component": "feature_recovery", "reason": f"{key} T1 failed", "decision": "block"}),
        Event(timestamp=now - timedelta(minutes=4), event_type="packet_failed", entity_type="packet",
              entity_id=blocked.id, trace_id=f"trace-{key}-blocked",
              payload_json={"component": "acceptance_pipeline", "reason": "failed stage", "stderr": f"stderr-{key}"}),
        Event(timestamp=now - timedelta(minutes=2), event_type="stale_base_detected", entity_type="packet",
              entity_id=stale.id, trace_id=f"trace-{key}-stale",
              payload_json={"component": "merge", "reason": "target advanced", "base_sha": f"base-{key}"}),
        Event(timestamp=now - timedelta(minutes=1), event_type="integration_recheck", entity_type="packet",
              entity_id=stale.id, trace_id=f"trace-{key}-stale",
              payload_json={"component": "merge", "reason": "recheck failed", "status": "failed"}),
    ]
    with get_db() as db:
        db.add_all([feature, wave, shared, control, blocked, stale, running,
                    shared_run, control_run, blocked_run, stale_run, running_run,
                    *stages, worker, *planning, session, ordinary, parallel, merge, *event_rows])
        db.commit()
        assert inspect(db.get_bind()).has_table("agent_sessions")


# START_FUNCTION_CONTRACT
# name: _runtime_environment
# purpose: Build isolated environment variables for one real project API
#          process; the Hub never writes selected project state globally.
# inputs: fixture — prepared project mapping.
# returns: Environment mapping for the local uvicorn process.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for prepared fixture values.
# END_FUNCTION_CONTRACT
def _runtime_environment(fixture: dict[str, Any]) -> dict[str, str]:
    root = Path(fixture["root"])
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": f"{_REPO_ROOT / 'src'}:{env.get('PYTHONPATH', '')}",
        "GRACE_PROJECT_ROOT": str(root), "GRACE_TARGET_REPO_ROOT": str(root), "GRACE_TARGET_DIR": str(root),
        "GRACE_DB_URL": f"sqlite:///{fixture['database']}", "GRACE_DATABASE_URL": f"sqlite:///{fixture['database']}",
        "GRACE_API_HOST": "127.0.0.1", "GRACE_API_PORT": str(fixture["port"]),
        "GRACE_API_AUTH_ENABLED": "false", "GRACE_API_AUTH_ALLOW_UNAUTHENTICATED_LOCALHOST": "true",
        "GRACE_STATE_ROOT": ".grace/state", "GRACE_WORKTREE_ROOT": ".grace/worktrees",
        "GRACE_RUNTIME_ARTIFACTS_ROOT": ".grace/runs", "GRACE_PLANNING_LOGS_ROOT": ".grace/logs",
        "GRACE_BASE_BRANCH": "main", "GRACE_TARGET_BRANCH": "main", "GRACE_GIT_REMOTE": "origin",
        "GRACE_EXECUTION_BACKEND": "mock", "GRACE_CONTEXT_DISABLED": "true",
        "GRACE_WAVE_GATE_INTERVAL_SECONDS": "3600", "GRACE_FEATURE_GATE_INTERVAL_SECONDS": "3600",
        "GRACE_MAX_CONCURRENCY": "1", "GRACE_PARALLEL_SCOPE_GUARD_ENABLED": "true",
        "GRACE_MERGE_SERIALIZATION_ENABLED": "true",
    })
    for name in ("GRACE_PROJECTS_CONFIG", "GRACE_PROJECT_REGISTRY", "GRACE_PROJECTS_FILE"):
        env.pop(name, None)
    return env


# START_FUNCTION_CONTRACT
# name: _stop_process
# purpose: Stop one temporary API/browser subprocess and release its resources.
# inputs: process — subprocess handle or None.
# returns: None.
# side_effects: Terminates only the fixture-owned child process.
# emitted_logs: None.
# error_behavior: Ignores already-exited processes and bounds the wait.
# END_FUNCTION_CONTRACT
def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# START_FUNCTION_CONTRACT
# name: _wait_for_server
# purpose: Wait for a temporary API readiness response without fixed sleeps.
# inputs: port — loopback port; process — child process to monitor.
# returns: None when `/health/readiness` returns HTTP 200.
# side_effects: Performs bounded loopback HTTP probes.
# emitted_logs: None.
# error_behavior: Raises RuntimeError with bounded child output on startup fail.
# END_FUNCTION_CONTRACT
def _wait_for_server(port: int, process: subprocess.Popen[str]) -> None:
    url = f"http://127.0.0.1:{port}/health/readiness"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read()[-2000:] if process.stdout is not None else ""
            raise RuntimeError(f"Stage 07 API process stopped during startup: {output}")
        try:
            if httpx.get(url, timeout=0.25, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    _stop_process(process)
    raise RuntimeError(f"Stage 07 API process did not become ready: {url}")


# START_FUNCTION_CONTRACT
# name: _start_project_server
# purpose: Start one real project-local GRACE API process with its own
#          database, root and Git repository.
# inputs: fixture — prepared and seeded project mapping.
# returns: Updated fixture mapping with running process.
# side_effects: Binds a loopback port and starts uvicorn.
# emitted_logs: Child logs are captured for bounded startup diagnostics.
# error_behavior: Raises RuntimeError if readiness cannot be established.
# END_FUNCTION_CONTRACT
def _start_project_server(fixture: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "grace_control.api.main:app", "--host", "127.0.0.1",
         "--port", str(fixture["port"]), "--log-level", "error"],
        cwd=_REPO_ROOT, env=_runtime_environment(fixture),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    fixture["process"] = process
    _wait_for_server(int(fixture["port"]), process)
    return fixture


# START_FUNCTION_CONTRACT
# name: _start_hub_server
# purpose: Start a real Hub API process using the fixture registry and one
#          intentionally unreachable project for browser offline-card checks.
# inputs: topology — prepared Stage 07 project fixtures and registry path.
# returns: Tuple of child process and loopback Hub URL.
# side_effects: Binds a loopback port and writes a temporary browser registry.
# emitted_logs: Child logs are captured for bounded startup diagnostics.
# error_behavior: Raises RuntimeError when the Hub readiness probe fails.
# END_FUNCTION_CONTRACT
def _start_hub_server(topology: dict[str, Any]) -> tuple[subprocess.Popen[str], str]:
    port = _free_port()
    fixtures = topology["fixtures"]
    browser_registry_path = Path(topology["root"]) / "browser-hub-projects.yaml"
    entries = [
        {"key": fixture["key"], "name": fixture["name"], "enabled": True,
         "unix_user": f"grace-{fixture['key']}", "project_root": str(fixture["root"]),
         "api_url": fixture["api_url"], "tags": ["stage07", fixture["key"]]}
        for fixture in fixtures
    ]
    entries.append({
        "key": "offline", "name": "Offline project", "enabled": True,
        "unix_user": "grace-offline", "project_root": str(Path(topology["root"]) / "offline"),
        "api_url": f"http://127.0.0.1:{_free_port()}", "tags": ["stage07", "offline"],
    })
    browser_registry_path.write_text(
        yaml.safe_dump({"projects": entries}, sort_keys=False), encoding="utf-8",
    )
    env = _runtime_environment(fixtures[0])
    env["GRACE_PROJECTS_CONFIG"] = str(browser_registry_path)
    env["GRACE_API_PORT"] = str(port)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "grace_control.api.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "error"],
        cwd=_REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    _wait_for_server(port, process)
    return process, f"http://127.0.0.1:{port}"


# START_FUNCTION_CONTRACT
# name: _registry_for
# purpose: Build immutable Hub contexts pointing only to selected project APIs.
# inputs: fixtures — independent project mappings.
# returns: ProjectRegistry.
# side_effects: None; Hub services do not open fixture databases/filesystems.
# emitted_logs: None.
# error_behavior: Registry validation errors propagate.
# END_FUNCTION_CONTRACT
def _registry_for(fixtures: list[dict[str, Any]]) -> ProjectRegistry:
    return ProjectRegistry.from_mapping({"projects": [
        {"key": fixture["key"], "name": fixture["name"], "enabled": True,
         "unix_user": f"grace-{fixture['key']}", "project_root": str(fixture["root"]),
         "api_url": fixture["api_url"], "description": f"Stage 07 {fixture['key']}",
         "tags": ["stage07", fixture["key"]]}
        for fixture in fixtures
    ]})


# START_FUNCTION_CONTRACT
# name: stage07_topology
# purpose: Provide the final acceptance topology with independent SQLite, Git,
#          state/worktree roots and real project API processes.
# inputs: tmp_path_factory — pytest temporary directory factory.
# returns: Mapping containing fixtures, registry and registry YAML path.
# side_effects: Creates and later stops two temporary API processes.
# emitted_logs: Child runtime logs are captured in subprocess pipes.
# error_behavior: Stops started children before propagating setup errors.
# END_FUNCTION_CONTRACT
@pytest.fixture(scope="module")
def stage07_topology(tmp_path_factory):
    root = tmp_path_factory.mktemp("admin-control-center-stage07")
    fixtures: list[dict[str, Any]] = []
    try:
        for key in ("alpha", "beta"):
            fixture = _prepare_project(root / key, key, _free_port())
            _seed_project_database(fixture)
            fixtures.append(_start_project_server(fixture))
        registry = _registry_for(fixtures)
        registry_path = root / "hub-projects.yaml"
        registry_path.write_text(yaml.safe_dump({"projects": [
            {"key": fixture["key"], "name": fixture["name"], "enabled": True,
             "unix_user": f"grace-{fixture['key']}", "project_root": str(fixture["root"]),
             "api_url": fixture["api_url"], "tags": ["stage07", fixture["key"]]}
            for fixture in fixtures
        ]}, sort_keys=False), encoding="utf-8")
        yield {"root": root, "fixtures": fixtures, "registry": registry, "registry_path": registry_path}
    finally:
        for fixture in reversed(fixtures):
            _stop_process(fixture.get("process"))


# START_FUNCTION_CONTRACT
# name: stage07_hub_url
# purpose: Provide a real loopback Hub URL for browser desktop/mobile and
#          deep-link/polling acceptance.
# inputs: stage07_topology — module-scoped real project topology.
# returns: Hub base URL string.
# side_effects: Starts and stops one fixture-owned Hub subprocess.
# emitted_logs: Child logs are captured for bounded startup diagnostics.
# error_behavior: Propagates bounded startup failures and always stops the Hub.
# END_FUNCTION_CONTRACT
@pytest.fixture
def stage07_hub_url(stage07_topology):
    process, url = _start_hub_server(stage07_topology)
    try:
        yield url
    finally:
        _stop_process(process)


# END_BLOCK_REAL_TOPOLOGY


# START_BLOCK_HUB_HELPERS
# START_FUNCTION_CONTRACT
# name: _hub_app
# purpose: Build the Hub ASGI app with production ProjectClient transport for
#          immutable registry contexts.
# inputs: registry — immutable registry; client_factory — optional test client.
# returns: FastAPI application.
# side_effects: Constructs Hub service state only.
# emitted_logs: None directly.
# error_behavior: Invalid registry/client configuration propagates.
# END_FUNCTION_CONTRACT
def _hub_app(registry: ProjectRegistry, *, client_factory=None):
    factory = client_factory or (
        lambda context: ProjectClient(context, connect_timeout=0.6, read_timeout=1.5)
    )
    return create_app(
        GraceSettings(api_auth_enabled=False, api_auth_allow_unauthenticated_localhost=True),
        project_registry=registry, project_client_factory=factory,
    )


# START_FUNCTION_CONTRACT
# name: _remote_get
# purpose: Perform one bounded production ProjectClient GET against a selected
#          project-local API.
# inputs: context — immutable project context; path — validated API path.
# returns: ProjectApiResult.
# side_effects: Performs one loopback HTTP request.
# emitted_logs: ProjectClient request/error logs.
# error_behavior: Transport/status/JSON failures are normalized by the client.
# END_FUNCTION_CONTRACT
async def _remote_get(context: Any, path: str) -> ProjectApiResult:
    return await ProjectClient(context, connect_timeout=0.6, read_timeout=1.5).get_json(path)


# END_BLOCK_HUB_HELPERS


# START_BLOCK_ACCEPTANCE
# START_FUNCTION_CONTRACT
# name: test_stage07_real_topology_isolation_and_control
# purpose: Prove two real project runtimes retain independent DB/runtime/Git
#          identity under concurrent Hub requests and a selected control.
# inputs: stage07_topology — real two-project fixture.
# returns: None.
# side_effects: Loopback Hub reads and one confirmed retry in Alpha only.
# emitted_logs: Hub/project structured request and audit logs.
# error_behavior: Fails on same-ID leakage, cross-project routing or rerouting.
# END_FUNCTION_CONTRACT
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stage07_real_topology_isolation_and_control(stage07_topology):
    registry = stage07_topology["registry"]
    app = _hub_app(registry)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.stage07") as client:
        projects = await client.get("/api/admin-hub/projects")
        assert projects.status_code == 200
        rows = {row["key"]: row for row in projects.json()["projects"]}
        assert set(rows) == {"alpha", "beta"}
        assert rows["alpha"]["status"] == "online" and rows["beta"]["status"] == "online"
        assert rows["alpha"]["health"]["runtime"]["project_key"] == "alpha"
        assert rows["beta"]["health"]["runtime"]["project_key"] == "beta"
        assert rows["alpha"]["project_root"] != rows["beta"]["project_root"]

        alpha_context = registry.get("alpha")
        beta_context = registry.get("beta")
        alpha_health, beta_health = await asyncio.gather(
            client.get("/api/admin-hub/projects/alpha/health"),
            client.get("/api/admin-hub/projects/beta/health"),
        )
        assert alpha_health.json()["runtime"]["project_key"] == "alpha"
        assert beta_health.json()["runtime"]["project_key"] == "beta"

        alpha_raw, beta_raw = await asyncio.gather(
            _remote_get(alpha_context, f"/api/admin/packet/{_SHARED_PACKET_ID}/raw"),
            _remote_get(beta_context, f"/api/admin/packet/{_SHARED_PACKET_ID}/raw"),
        )
        assert alpha_raw.ok and beta_raw.ok
        assert alpha_raw.payload["packet"]["title"] == "Shared merged packet Alpha"
        assert beta_raw.payload["packet"]["title"] == "Shared merged packet Beta"
        assert alpha_raw.payload["packet"]["title"] != beta_raw.payload["packet"]["title"]

        overview = await client.get("/api/admin-hub/overview")
        assert overview.status_code == 200
        cards = {row["project_key"]: row for row in overview.json()["projects"]}
        assert cards["alpha"]["project_key"] == "alpha"
        assert cards["beta"]["project_key"] == "beta"
        alpha_tree = await _remote_get(alpha_context, "/api/admin/features")
        beta_tree = await _remote_get(beta_context, "/api/admin/features")
        assert alpha_tree.ok and beta_tree.ok
        assert alpha_tree.payload["features"][0]["id"] == "feat-alpha-stage07"
        assert beta_tree.payload["features"][0]["id"] == "feat-beta-stage07"

        alpha_stdout = await _remote_get(alpha_context, "/api/admin/fs/file?root=runs&path=alpha-run-1/stdout.log&max_bytes=64")
        beta_stdout = await _remote_get(beta_context, "/api/admin/fs/file?root=runs&path=beta-run-1/stdout.log&max_bytes=64")
        assert alpha_stdout.ok and beta_stdout.ok
        assert alpha_stdout.payload["content"] != beta_stdout.payload["content"]
        outside_attempt = await _remote_get(
            beta_context,
            f"/api/admin/fs/file?root=state&path={stage07_topology['fixtures'][0]['root']}/.grace/state/.env",
        )
        assert not outside_attempt.ok and outside_attempt.http_status == 400

        alpha_git, beta_git = await asyncio.gather(
            _remote_get(alpha_context, "/api/admin/git/repository"),
            _remote_get(beta_context, "/api/admin/git/repository"),
        )
        assert alpha_git.ok and beta_git.ok
        assert alpha_git.payload["repo_root"] != beta_git.payload["repo_root"]
        alpha_show = await _remote_get(alpha_context, "/api/admin/git/show?ref=HEAD&path=src/alpha.txt")
        beta_show = await _remote_get(beta_context, "/api/admin/git/show?ref=HEAD&path=src/beta.txt")
        assert alpha_show.payload["content"] == "changed-alpha\n"
        assert beta_show.payload["content"] == "changed-beta\n"
        malicious_git = await _remote_get(beta_context, "/api/admin/git/show?ref=HEAD&path=../alpha/src/alpha.txt")
        assert not malicious_git.ok and malicious_git.http_status == 400

        alpha_page, beta_page = await asyncio.gather(
            client.get(f"/admin/p/alpha/packet/{_SHARED_PACKET_ID}"),
            client.get(f"/admin/p/beta/packet/{_SHARED_PACKET_ID}"),
        )
        assert alpha_page.status_code == 200 and beta_page.status_code == 200
        assert "Shared merged packet Alpha" in alpha_page.text
        assert "Shared merged packet Beta" in beta_page.text
        assert "Shared merged packet Beta" not in alpha_page.text
        assert "Shared merged packet Alpha" not in beta_page.text

        before_beta = await _remote_get(beta_context, f"/api/admin/packet/{_CONTROL_PACKET_ID}/detail")
        assert before_beta.payload["packet"]["state"] == "blocked_recoverable"
        control = await client.post(
            "/api/admin-hub/projects/alpha/controls",
            json={"action": "retry", "entity_type": "packet", "entity_id": _CONTROL_PACKET_ID,
                  "confirmation": {"intent": "confirm"}},
        )
        assert control.status_code == 200 and control.json()["ok"] is True
        after_alpha = await _remote_get(alpha_context, f"/api/admin/packet/{_CONTROL_PACKET_ID}/detail")
        after_beta = await _remote_get(beta_context, f"/api/admin/packet/{_CONTROL_PACKET_ID}/detail")
        assert after_alpha.payload["packet"]["state"] == "ready"
        assert after_beta.payload["packet"]["state"] == "blocked_recoverable"
        audit = await _remote_get(alpha_context, f"/api/events?entity_id={_CONTROL_PACKET_ID}&limit=100")
        assert any(row["event_type"] == "admin_action_completed" for row in audit.payload["data"]["events"])


# START_FUNCTION_CONTRACT
# name: test_stage07_complete_read_surface_and_operator_journeys
# purpose: Prove the rich project exposes feature/wave/packet/run/stage/session,
#          evidence/log/artifact/lease/stale-base/Git data through API/UI and
#          discovers an uncoded OpenAPI GET path.
# inputs: stage07_topology — real two-project fixture.
# returns: None.
# side_effects: Performs bounded reads only.
# emitted_logs: Project and Hub structured read logs.
# error_behavior: Fails when any required read surface or journey is hidden.
# END_FUNCTION_CONTRACT
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stage07_complete_read_surface_and_operator_journeys(stage07_topology):
    registry = stage07_topology["registry"]
    app = _hub_app(registry)
    context = registry.get("alpha")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://hub.stage07") as client:
        raw = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/raw")
        assert raw.ok
        assert raw.payload["runs"][0]["result_json"]["acceptance_report"]["final_verdict"] == "PASS"
        assert raw.payload["stages"][0]["stage_key"] == "coder"

        run_id = _SHARED_PACKET_ID + _RUN_SUFFIX
        run = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}")
        evidence = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/evidence")
        logs = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/logs?stream=stderr&tail=3")
        agent_logs = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/logs?stream=agent&tail=3")
        artifacts = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/artifacts")
        artifact_preview = await _remote_get(
            context, f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/artifacts/preview?path=report.md&max_bytes=64",
        )
        sessions = await _remote_get(context, f"/api/admin/packet/{_SHARED_PACKET_ID}/sessions")
        diagnostics = await _remote_get(context, "/api/diagnostics/state")
        events = await _remote_get(context, f"/api/events?entity_id={_SHARED_PACKET_ID}&limit=100")
        assert run.ok and run.payload["run"]["base_sha"] == "base-alpha"
        assert evidence.ok and evidence.payload["verdict"] == "PASS"
        assert logs.ok and len(logs.payload["lines"]) <= 3
        assert agent_logs.ok and "agent-alpha" in "\n".join(agent_logs.payload["lines"])
        assert artifacts.ok and all(
            any(node["name"] == name for node in artifacts.payload["tree"])
            for name in ("report.md", "image.png", "binary.bin")
        )
        assert artifact_preview.ok and artifact_preview.payload["content"].startswith("# Evidence")
        assert sessions.ok and sessions.payload["reason"] == "ok"
        assert sessions.payload["sessions"][0]["external_id"] == "ses_alpha07"
        assert diagnostics.ok and diagnostics.payload["data"]["active_parallel_leases"]
        assert events.ok and any(
            event["payload_json"].get("full", {}).get("project") == "alpha"
            for event in events.payload["data"]["events"]
        )

        blocked = await client.get(
            "/admin/p/alpha/packet/pkt-alpha-blocked",
            params={"tab": "evidence", "run_id": "pkt-alpha-blocked-run-1"},
        )
        assert blocked.status_code == 200
        assert "alpha T1 failed" in blocked.text
        assert "stderr-alpha failure tail" in blocked.text
        assert "Blocking" in blocked.text

        stale = await client.get(
            "/admin/p/alpha/packet/pkt-alpha-stale",
            params={"tab": "git", "ref": "HEAD~1"},
        )
        assert stale.status_code == 200
        assert "stale" in stale.text.casefold()
        assert "HEAD~1" in stale.text or "src/alpha.txt" in stale.text

        fs_preview = await _remote_get(
            context, "/api/admin/fs/file?root=runs&path=alpha-run-1/stdout.log&max_bytes=16",
        )
        fs_tail = await _remote_get(
            context, "/api/admin/fs/tail?root=runs&path=alpha-run-1/stderr.log&lines=2&max_bytes=32",
        )
        fs_binary = await _remote_get(
            context, "/api/admin/fs/file?root=state&path=binary.bin&max_bytes=8",
        )
        assert fs_preview.ok and fs_preview.payload["truncated"] is True
        assert fs_tail.ok and fs_tail.payload["tail_lines"] == 2
        assert fs_binary.ok and fs_binary.payload["binary"] is True
        for unsafe_path in ("../alpha-outside/private.txt", "/etc/passwd", ".env", "id_rsa"):
            unsafe = await _remote_get(context, f"/api/admin/fs/file?root=state&path={unsafe_path}")
            assert not unsafe.ok and unsafe.http_status in {400, 403}
        if stage07_topology["fixtures"][0]["escape"] is not None:
            symlink = await _remote_get(context, "/api/admin/fs/file?root=state&path=escape/private.txt")
            assert not symlink.ok and symlink.http_status == 403

        git_diff = await _remote_get(context, "/api/admin/git/diff?ref=HEAD~1")
        git_stat = await _remote_get(context, "/api/admin/git/diff-stat?ref=HEAD~1")
        git_worktrees = await _remote_get(context, "/api/admin/git/worktrees")
        git_large = await _remote_get(context, "/api/admin/git/show?ref=HEAD&path=large.txt&max_bytes=64")
        foreign_git = await _remote_get(
            registry.get("beta"), "/api/admin/git/show?ref=HEAD&path=src/alpha.txt",
        )
        assert git_diff.ok and git_diff.payload["truncated"] is True
        assert git_stat.ok and "large.txt" in git_stat.payload["stat"]
        assert git_worktrees.ok and len(git_worktrees.payload["worktrees"]) >= 2
        assert git_large.ok and git_large.payload["truncated"] is True
        assert not foreign_git.ok and foreign_git.http_status in {404, 422}

        binary_artifact = await _remote_get(
            context,
            f"/api/admin/packet/{_SHARED_PACKET_ID}/runs/{run_id}/artifacts/preview?path=binary.bin&max_bytes=8",
        )
        assert binary_artifact.ok and binary_artifact.payload["binary"] is True

        dashboard = await client.get("/admin/projects")
        assert dashboard.status_code == 200
        assert "Alpha" in dashboard.text and "Beta" in dashboard.text
        assert 'id="project-selector"' in dashboard.text
        assert "/admin/p/alpha" in dashboard.text and "/admin/p/beta" in dashboard.text

        global_events = await client.get(
            "/admin/events", params={"project": "alpha,beta", "entity_id": _SHARED_PACKET_ID},
        )
        global_logs = await client.get("/admin/logs", params={"project": "alpha,beta", "tail": 100})
        global_search = await client.get("/admin/search", params={"project": "beta", "q": "Packet beta"})
        assert global_events.status_code == global_logs.status_code == global_search.status_code == 200
        assert "/admin/p/alpha/packet/" in global_events.text
        assert "/admin/p/beta/packet/" in global_events.text
        assert "log-alpha" in global_logs.text and "log-beta" in global_logs.text
        assert "Packet beta" in global_search.text

        api_page = await client.get(
            "/admin/p/alpha/api",
            params={"path": "/api/debug/version", "method": "GET", "execute": "true"},
        )
        assert api_page.status_code == 200
        assert "api-response" in api_page.text
        assert "/api/debug/version" in api_page.text
        assert "build_id" in api_page.text

        for tab in ("pipeline", "events", "logs", "diagnostics", "raw", "sessions"):
            page = await client.get(
                f"/admin/p/alpha/packet/{_SHARED_PACKET_ID}", params={"tab": tab},
            )
            assert page.status_code == 200, tab
            assert 'data-project-key="alpha"' in page.text


# END_BLOCK_ACCEPTANCE


# START_FUNCTION_CONTRACT
# name: test_stage07_global_logs_use_bounded_row_cursors
# purpose: Prove a real named-root log file whose byte size exceeds its row
#          count produces complete, duplicate-free Global Logs continuation.
# inputs: stage07_topology — independent project APIs with real log roots.
# returns: None.
# side_effects: Rewrites only fixture-owned service logs and performs bounded
#               cross-project API reads through AdminCrossProjectService.
# emitted_logs: Project and Hub structured read logs.
# error_behavior: Fails on byte-count totals, skipped/duplicate rows, or an
#                 opaque cursor that leads to an empty page.
# END_FUNCTION_CONTRACT
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stage07_global_logs_use_bounded_row_cursors(stage07_topology):
    expected: set[str] = set()
    for fixture in stage07_topology["fixtures"]:
        key = str(fixture["key"])
        rows = [f"{key}-row-{index}-" + ("x" * 96) for index in range(20)]
        expected.update(rows)
        logs_path = Path(fixture["root"]) / ".grace" / "logs" / "service.log"
        logs_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    registry = stage07_topology["registry"]
    for fixture in stage07_topology["fixtures"]:
        raw = await _remote_get(
            registry.get(str(fixture["key"])),
            "/api/admin/system/logs?tail=10",
        )
        assert raw.ok
        assert raw.payload["total"] == 10
        assert raw.payload["total_bytes"] > raw.payload["total"]

    service = AdminCrossProjectService(registry)
    page = await service.query_logs(project=["alpha", "beta"], tail=10)
    seen: list[str] = []
    page_count = 0
    while True:
        page_count += 1
        assert page["logs"] or not page["next_cursor"]
        seen.extend(str(row["message"]) for row in page["logs"])
        cursor = page["next_cursor"]
        if not cursor:
            break
        assert page_count < 8
        page = await service.query_logs(project=["alpha", "beta"], tail=10, cursor=cursor)

    assert page_count == 4
    assert len(seen) == len(expected) == 40
    assert len(set(seen)) == len(seen)
    assert set(seen) == expected
