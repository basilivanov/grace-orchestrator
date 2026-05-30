# ############################################################################
# AI_HEADER: prefect_e2e_live_smoke
# ROLE: Controlled smoke harness for Prefect E2E packet submission.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create and submit one low-risk E2E packet smoke run through native Prefect submission.
# inputs: Project config path, smoke state/worktree/packet roots, dry-run/live-agent flags, optional submitter.
# returns: PrefectE2ELiveSmokeResult with JSON-safe run metadata.
# side_effects: Writes a smoke packet under packet_root and a registry entry under state_root.
# emitted_logs: None.
# error_behavior: Returns structured guard/submission errors; does not raise for expected operator blocks.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PrefectE2ELiveSmokeResult
#   - class: _SmokeProject
#   - function: run_prefect_e2e_live_smoke
#   - function: _build_smoke_packet_content
#   - function: _guard_live_agent_mode
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import ProjectAdapterConfig, load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

SMOKE_FEATURE_ID = "FEAT-GRACE-PREFECT-E2E-LIVE-SMOKE-MVP"
SMOKE_PACKET_ID = "FEAT-GRACE-PREFECT-E2E-LIVE-SMOKE-MVP-W01-E2E-LIVE-SMOKE"
SMOKE_WAVE_ID = "W01"


#START_BLOCK_MODELS
@dataclass(frozen=True)
class PrefectE2ELiveSmokeResult:
    ok: bool
    mode: str
    packet_id: str
    flow_run_id: str | None
    flow_run_name: str | None
    deployment_name: str
    runner_kind: str
    idempotency_key: str | None
    submitted: bool
    status: str
    feature_id: str
    work_queue_name: str | None
    url: str | None
    errors: list[dict[str, Any]]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize smoke result to a JSON-safe dict.
    # inputs:
    #   self: PrefectE2ELiveSmokeResult instance.
    # returns: dict[str, Any] with result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "packet_id": self.packet_id,
            "flow_run_id": self.flow_run_id,
            "flow_run_name": self.flow_run_name,
            "deployment_name": self.deployment_name,
            "runner_kind": self.runner_kind,
            "idempotency_key": self.idempotency_key,
            "submitted": self.submitted,
            "status": self.status,
            "feature_id": self.feature_id,
            "work_queue_name": self.work_queue_name,
            "url": self.url,
            "errors": list(self.errors),
        }


#END_BLOCK_MODELS
#START_BLOCK_HELPERS
@dataclass(frozen=True)
class _SmokeProject:
    project_key: str
    repo_root: str
    runtime_state_root: str
    worktree_root: str
    packets_dir: str


# START_FUNCTION_CONTRACT
# name: _result
# purpose: Build a smoke result with stable default metadata.
# inputs:
#   ok: Success flag.
#   mode: Smoke mode.
#   status: Smoke status.
#   submitted: Whether a flow run was submitted.
#   errors: Structured errors.
#   flow_run_id: Optional flow run ID.
#   flow_run_name: Optional flow run name.
#   idempotency_key: Optional idempotency key.
#   work_queue_name: Optional queue name.
#   url: Optional run URL.
# returns: PrefectE2ELiveSmokeResult.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _result(
    *,
    ok: bool,
    mode: str,
    status: str,
    submitted: bool = False,
    errors: list[dict[str, Any]] | None = None,
    flow_run_id: str | None = None,
    flow_run_name: str | None = None,
    idempotency_key: str | None = None,
    work_queue_name: str | None = None,
    url: str | None = None,
) -> PrefectE2ELiveSmokeResult:
    return PrefectE2ELiveSmokeResult(
        ok=ok,
        mode=mode,
        packet_id=SMOKE_PACKET_ID,
        flow_run_id=flow_run_id,
        flow_run_name=flow_run_name,
        deployment_name=E2E_PACKET_DEPLOYMENT_NAME,
        runner_kind="e2e",
        idempotency_key=idempotency_key,
        submitted=submitted,
        status=status,
        feature_id=SMOKE_FEATURE_ID,
        work_queue_name=work_queue_name,
        url=url,
        errors=list(errors or []),
    )


# START_FUNCTION_CONTRACT
# name: _build_smoke_packet_content
# purpose: Render a strict low-risk smoke packet.
# inputs: None.
# returns: Markdown packet content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_smoke_packet_content() -> str:
    return f"""# Execution Packet: {SMOKE_PACKET_ID}

- packet_id: {SMOKE_PACKET_ID}
- feature_id: {SMOKE_FEATURE_ID}
- wave_id: {SMOKE_WAVE_ID}
- status: ready
- phase: PHASE-GRACE-ORCHESTRATOR-PORTABLE-MVP

## Objective
Submit one controlled Prefect E2E live smoke packet. The packet is a no-op
scratch-only execution used to prove E2E deployment submission wiring.

## Allowed Write Scope
- scratch/grace-live-smoke/**

## Frozen Scope
- backend/**
- frontend/**
- prefect_grace/**
- .env
- docker-compose*.yml
- scripts/**
- tools/**

## Must Preserve
- No product backend or frontend code changes.
- No feature pipeline execution.
- No merge, push, squash, accept, or worktree cleanup.

## Verification
Confirm that native submission created exactly one E2E Prefect flow run.

## Expected Evidence
- Prefect flow run id
- Prefect deployment name
- Registry submission metadata

## Escalation Triggers
- More than one packet would be submitted
- Live agent execution requested without all explicit guards
- Write scope outside scratch/grace-live-smoke/**
"""


# START_FUNCTION_CONTRACT
# name: _guard_live_agent_mode
# purpose: Validate safe dry-run/live-agent mode combinations.
# inputs:
#   dry_run: Whether E2E flow should run in agent dry-run mode.
#   execute_agent: Whether live agent execution was requested.
#   allow_live_agent_smoke: Explicit operator allow flag.
#   limit: Submission limit.
# returns: Structured errors list; empty means safe.
# side_effects: Reads GRACE_ALLOW_LIVE_AGENT_SMOKE environment variable.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _guard_live_agent_mode(
    *,
    dry_run: bool,
    execute_agent: bool,
    allow_live_agent_smoke: bool,
    limit: int,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if limit != 1:
        errors.append({
            "code": "LIVE_SMOKE_LIMIT_NOT_ONE",
            "message": "Prefect E2E live smoke must submit exactly one packet.",
        })
    if dry_run and not execute_agent:
        return errors
    if dry_run and execute_agent:
        errors.append({
            "code": "LIVE_AGENT_SMOKE_GUARD_FAILED",
            "message": (
                "Live-agent smoke requires --execute-agent, --no-dry-run, "
                "--allow-live-agent-smoke, GRACE_ALLOW_LIVE_AGENT_SMOKE=1, and limit=1."
            ),
        })
        return errors
    if not dry_run and execute_agent and allow_live_agent_smoke and os.environ.get("GRACE_ALLOW_LIVE_AGENT_SMOKE") == "1":
        return errors
    errors.append({
        "code": "LIVE_AGENT_SMOKE_GUARD_FAILED",
        "message": (
            "Live-agent smoke requires --execute-agent, --no-dry-run, "
            "--allow-live-agent-smoke, GRACE_ALLOW_LIVE_AGENT_SMOKE=1, and limit=1."
        ),
    })
    return errors


# START_FUNCTION_CONTRACT
# name: _smoke_project
# purpose: Build a project-like config using smoke state/worktree roots.
# inputs:
#   project: Loaded ProjectAdapterConfig.
#   state_root: Smoke runtime state root.
#   worktree_root: Smoke worktree root.
# returns: _SmokeProject suitable for native submission planning.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _smoke_project(project: ProjectAdapterConfig, *, state_root: Path, worktree_root: Path) -> _SmokeProject:
    return _SmokeProject(
        project_key=project.project_key,
        repo_root=project.repo_root,
        runtime_state_root=str(state_root),
        worktree_root=str(worktree_root),
        packets_dir=project.packets_dir,
    )


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_prefect_e2e_live_smoke
# purpose: Create and submit exactly one low-risk E2E packet through native Prefect submission.
# inputs:
#   project_config: Path to project config.
#   state_root: Isolated smoke state root.
#   worktree_root: Isolated smoke worktree root.
#   packet_root: Directory for generated smoke packet.
#   dry_run: If True, E2E flow uses dry-run agent behavior.
#   execute_agent: If True, request live agent execution.
#   allow_live_agent_smoke: Explicit live-agent smoke approval flag.
#   limit: Must be 1.
#   submitter: Optional submitter callable for tests/offline validation.
# returns: PrefectE2ELiveSmokeResult.
# side_effects: Writes smoke packet and registry state, may submit a Prefect flow run.
# emitted_logs: None.
# error_behavior: Returns blocked/failed result with structured errors.
# END_FUNCTION_CONTRACT
def run_prefect_e2e_live_smoke(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    dry_run: bool = True,
    execute_agent: bool = False,
    allow_live_agent_smoke: bool = False,
    limit: int = 1,
    submitter: Callable[..., dict[str, Any]] | None = None,
) -> PrefectE2ELiveSmokeResult:
    mode = "prefect_live_agent_dry_run" if dry_run and not execute_agent else "prefect_live_agent_execute"
    guard_errors = _guard_live_agent_mode(
        dry_run=dry_run,
        execute_agent=execute_agent,
        allow_live_agent_smoke=allow_live_agent_smoke,
        limit=limit,
    )
    if guard_errors:
        return _result(ok=False, mode=mode, status="blocked", errors=guard_errors)

    project = load_project_adapter(project_config)
    smoke_project = _smoke_project(project, state_root=state_root, worktree_root=worktree_root)

    packet_dir = Path(packet_root) / SMOKE_FEATURE_ID
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "EXECUTION_PACKET.md"
    packet_path.write_text(_build_smoke_packet_content(), encoding="utf-8")
    parsed = parse_packet_markdown(packet_path, mode="strict")

    registry = PacketRegistryStore(Path(state_root) / "state")
    registry.upsert_packet({
        "packet_id": parsed.packet_id,
        "project_key": project.project_key,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "title": parsed.title,
        "path": str(packet_path),
        "source_hash": parsed.source_hash,
        "registry_status": "ready",
        "registry_reason": "prefect_e2e_live_smoke",
        "depends_on": [],
    })

    plan = BacklogController.plan_submission(smoke_project)
    if plan.errors:
        return _result(
            ok=False,
            mode=mode,
            status="blocked",
            errors=[{"code": "SUBMISSION_PLAN_ERROR", "message": message} for message in plan.errors],
        )
    if plan.packets_to_submit != [SMOKE_PACKET_ID]:
        return _result(
            ok=False,
            mode=mode,
            status="blocked",
            errors=[{
                "code": "LIVE_SMOKE_PACKET_COUNT_INVALID",
                "message": f"Expected only {SMOKE_PACKET_ID} to be submitted; got {plan.packets_to_submit}",
            }],
        )

    if submitter is None:
        from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
        submitter = E2EPacketSubmitter()

    submission_result = submit_ready_packets_to_prefect(
        project=smoke_project,
        dry_run=False,
        limit=1,
        execute_agent=execute_agent,
        timeout_seconds=3600,
        base_ref="HEAD",
        worktree_root=worktree_root,
        scheduled_for=None,
        continue_on_error=False,
        submitter=submitter,
        runner_kind="e2e",
    )
    if submission_result.errors or not submission_result.records:
        return _result(
            ok=False,
            mode=mode,
            status="failed",
            errors=submission_result.errors or [{"code": "NO_SUBMISSION_RECORD", "message": "No submission record returned"}],
        )

    record = submission_result.records[0]
    return _result(
        ok=record.status == "submitted",
        mode=mode,
        status=record.status,
        submitted=record.status == "submitted",
        errors=[] if record.status == "submitted" else [{"code": "SUBMISSION_NOT_SUBMITTED", "message": record.error or record.status}],
        flow_run_id=record.flow_run_id,
        flow_run_name=record.flow_run_name,
        idempotency_key=record.idempotency_key,
        work_queue_name=record.work_queue_name,
        url=record.url,
    )


#END_BLOCK_SMOKE
