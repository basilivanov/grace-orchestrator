# ############################################################################
# AI_HEADER: prefect_e2e_batch_smoke
# ROLE: Controlled batch smoke harness for Prefect E2E packet queue submission.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Create and submit a bounded batch of low-risk E2E packet smoke runs through native Prefect submission.
# inputs: Project config path, smoke state/worktree/packet roots, batch size, optional submitter.
# returns: PrefectE2EBatchSmokeResult with JSON-safe queue metadata.
# side_effects: Writes smoke packets under packet_root and registry entries under state_root.
# emitted_logs: None.
# error_behavior: Returns structured guard/submission errors; does not raise for expected operator blocks.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PrefectE2EBatchSmokeResult
#   - class: _SmokeProject
#   - function: run_prefect_e2e_batch_smoke
#   - function: _build_batch_packet_content
#   - function: _guard_batch_size
#   - function: _smoke_project
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import ProjectAdapterConfig, load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

BATCH_SMOKE_FEATURE_ID = "FEAT-GRACE-PREFECT-BATCH-E2E-QUEUE-SMOKE-MVP"
BATCH_SMOKE_WAVE_ID = "W01"
BATCH_SMOKE_MODE = "prefect_agent_dry_run"
BATCH_SMOKE_MIN_PACKETS = 2
BATCH_SMOKE_MAX_PACKETS = 3


#START_BLOCK_MODELS
@dataclass(frozen=True)
class PrefectE2EBatchSmokeResult:
    ok: bool
    mode: str
    batch_size: int
    runner_kind: str
    deployment_name: str
    work_queue_name: str | None
    packets_planned: list[str]
    packets_submitted: list[str]
    records: list[dict[str, Any]]
    errors: list[dict[str, Any]]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize batch smoke result to a JSON-safe dict.
    # inputs:
    #   self: PrefectE2EBatchSmokeResult instance.
    # returns: dict[str, Any] with result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "batch_size": self.batch_size,
            "runner_kind": self.runner_kind,
            "deployment_name": self.deployment_name,
            "work_queue_name": self.work_queue_name,
            "packets_planned": list(self.packets_planned),
            "packets_submitted": list(self.packets_submitted),
            "records": [dict(record) for record in self.records],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class _SmokeProject:
    project_key: str
    repo_root: str
    runtime_state_root: str
    worktree_root: str
    packets_dir: str


#END_BLOCK_MODELS
#START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _result
# purpose: Build a batch smoke result with stable default metadata.
# inputs:
#   ok: Success flag.
#   batch_size: Requested batch size.
#   packets_planned: Planned packet IDs.
#   packets_submitted: Submitted packet IDs.
#   records: JSON-safe submission records.
#   errors: Structured errors.
#   work_queue_name: Optional queue name.
# returns: PrefectE2EBatchSmokeResult.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _result(
    *,
    ok: bool,
    batch_size: int,
    packets_planned: list[str] | None = None,
    packets_submitted: list[str] | None = None,
    records: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
    work_queue_name: str | None = None,
) -> PrefectE2EBatchSmokeResult:
    return PrefectE2EBatchSmokeResult(
        ok=ok,
        mode=BATCH_SMOKE_MODE,
        batch_size=batch_size,
        runner_kind="e2e",
        deployment_name=E2E_PACKET_DEPLOYMENT_NAME,
        work_queue_name=work_queue_name,
        packets_planned=list(packets_planned or []),
        packets_submitted=list(packets_submitted or []),
        records=list(records or []),
        errors=list(errors or []),
    )


# START_FUNCTION_CONTRACT
# name: _guard_batch_size
# purpose: Validate operator-safe batch size.
# inputs:
#   batch_size: Requested number of smoke packets.
# returns: Structured errors list; empty means safe.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _guard_batch_size(batch_size: int) -> list[dict[str, Any]]:
    if batch_size < BATCH_SMOKE_MIN_PACKETS:
        return [{
            "code": "BATCH_SMOKE_TOO_SMALL",
            "message": "Batch smoke requires 2-3 packets; use run-prefect-e2e-live-smoke for one packet.",
        }]
    if batch_size > BATCH_SMOKE_MAX_PACKETS:
        return [{
            "code": "BATCH_SMOKE_TOO_LARGE",
            "message": "Batch smoke is limited to at most 3 packets.",
        }]
    return []


# START_FUNCTION_CONTRACT
# name: _packet_id
# purpose: Build deterministic smoke packet IDs for a batch index.
# inputs:
#   index: One-based packet index.
# returns: Packet ID string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _packet_id(index: int) -> str:
    return f"{BATCH_SMOKE_FEATURE_ID}-W01-BATCH-E2E-QUEUE-SMOKE-{index:02d}"


# START_FUNCTION_CONTRACT
# name: _build_batch_packet_content
# purpose: Render a strict low-risk batch smoke packet.
# inputs:
#   packet_id: Packet identifier.
# returns: Markdown packet content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_batch_packet_content(packet_id: str) -> str:
    return f"""# Execution Packet: {packet_id}

- packet_id: {packet_id}
- feature_id: {BATCH_SMOKE_FEATURE_ID}
- wave_id: {BATCH_SMOKE_WAVE_ID}
- status: ready
- phase: PHASE-GRACE-ORCHESTRATOR-PORTABLE-MVP

## Objective
Submit one member of a controlled Prefect E2E batch queue smoke. The packet is a
no-op scratch-only execution used to prove E2E deployment queue submission
wiring.

## Allowed Write Scope
- scratch/grace-batch-smoke/**

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
- No live-agent batch execution.
- No merge, push, squash, accept, or worktree cleanup.

## Verification
Confirm that native submission created an independent E2E Prefect flow run for
this batch smoke packet.

## Expected Evidence
- Prefect flow run id
- Prefect deployment name
- Registry submission metadata
- Submitted order in batch smoke result

## Escalation Triggers
- More than three packets would be submitted
- Live agent execution requested for batch mode
- Write scope outside scratch/grace-batch-smoke/**
"""


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


# START_FUNCTION_CONTRACT
# name: _work_queue_from_records
# purpose: Pick operator-visible queue metadata from submitted records.
# inputs:
#   records: Submission record dicts.
# returns: First non-empty work queue name, if present.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _work_queue_from_records(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        queue_name = record.get("work_queue_name")
        if queue_name:
            return str(queue_name)
    return None


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_prefect_e2e_batch_smoke
# purpose: Create and submit 2-3 low-risk E2E packets through native Prefect submission.
# inputs:
#   project_config: Path to project config.
#   state_root: Isolated smoke state root.
#   worktree_root: Isolated smoke worktree root.
#   packet_root: Directory for generated smoke packets.
#   batch_size: Number of packets to submit, must be 2 or 3.
#   submitter: Optional submitter callable for tests/offline validation.
# returns: PrefectE2EBatchSmokeResult.
# side_effects: Writes smoke packets and registry state, may submit Prefect flow runs.
# emitted_logs: None.
# error_behavior: Returns blocked/failed result with structured errors.
# END_FUNCTION_CONTRACT
def run_prefect_e2e_batch_smoke(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    batch_size: int = 2,
    submitter: Callable[..., dict[str, Any]] | None = None,
) -> PrefectE2EBatchSmokeResult:
    guard_errors = _guard_batch_size(batch_size)
    if guard_errors:
        return _result(ok=False, batch_size=batch_size, errors=guard_errors)

    project = load_project_adapter(project_config)
    smoke_project = _smoke_project(project, state_root=state_root, worktree_root=worktree_root)
    expected_packet_ids = [_packet_id(index) for index in range(1, batch_size + 1)]

    registry = PacketRegistryStore(Path(state_root) / "state")
    packet_dir = Path(packet_root) / BATCH_SMOKE_FEATURE_ID
    packet_dir.mkdir(parents=True, exist_ok=True)

    for packet_id in expected_packet_ids:
        packet_path = packet_dir / f"{packet_id}.md"
        packet_path.write_text(_build_batch_packet_content(packet_id), encoding="utf-8")
        parsed = parse_packet_markdown(packet_path, mode="strict")
        registry.upsert_packet({
            "packet_id": parsed.packet_id,
            "project_key": project.project_key,
            "feature_id": parsed.feature_id,
            "wave_id": parsed.wave_id,
            "title": parsed.title,
            "path": str(packet_path),
            "source_hash": parsed.source_hash,
            "registry_status": "ready",
            "registry_reason": "prefect_e2e_batch_smoke",
            "depends_on": [],
        })

    plan = BacklogController.plan_submission(smoke_project)
    if plan.errors:
        return _result(
            ok=False,
            batch_size=batch_size,
            packets_planned=plan.submission_order,
            errors=[{"code": "SUBMISSION_PLAN_ERROR", "message": message} for message in plan.errors],
        )
    if plan.packets_to_submit != expected_packet_ids or plan.submission_order != expected_packet_ids:
        return _result(
            ok=False,
            batch_size=batch_size,
            packets_planned=plan.submission_order,
            errors=[{
                "code": "BATCH_SMOKE_PACKET_SET_INVALID",
                "message": f"Expected only generated batch packets {expected_packet_ids}; got {plan.packets_to_submit}.",
            }],
        )

    if submitter is None:
        from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
        submitter = E2EPacketSubmitter()

    submission_result = submit_ready_packets_to_prefect(
        project=smoke_project,
        dry_run=False,
        limit=batch_size,
        execute_agent=False,
        timeout_seconds=3600,
        base_ref="HEAD",
        worktree_root=worktree_root,
        scheduled_for=None,
        continue_on_error=False,
        submitter=submitter,
        runner_kind="e2e",
    )
    records = [record.to_dict() for record in submission_result.records]
    count_ok = len(submission_result.packets_submitted) == batch_size and len(records) == batch_size
    submitted_ok = all(record.get("status") == "submitted" for record in records)
    if submission_result.errors or not count_ok or not submitted_ok:
        errors = list(submission_result.errors)
        if not count_ok:
            errors.append({
                "code": "BATCH_SMOKE_SUBMISSION_COUNT_INVALID",
                "message": f"Expected {batch_size} submitted records; got {len(submission_result.packets_submitted)}.",
            })
        if not submitted_ok:
            errors.append({
                "code": "BATCH_SMOKE_RECORD_NOT_SUBMITTED",
                "message": "One or more batch smoke records were not submitted.",
            })
        return _result(
            ok=False,
            batch_size=batch_size,
            packets_planned=submission_result.packets_planned,
            packets_submitted=submission_result.packets_submitted,
            records=records,
            errors=errors,
            work_queue_name=_work_queue_from_records(records),
        )

    return _result(
        ok=True,
        batch_size=batch_size,
        packets_planned=submission_result.packets_planned,
        packets_submitted=submission_result.packets_submitted,
        records=records,
        errors=[],
        work_queue_name=_work_queue_from_records(records),
    )


#END_BLOCK_SMOKE
