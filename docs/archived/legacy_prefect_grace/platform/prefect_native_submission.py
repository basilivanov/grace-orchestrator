# ############################################################################
# AI_HEADER: prefect_native_submission
# ROLE: Submit ready packets as individual Prefect E2E flow runs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Submit ready packets to Prefect as E2E packet runner flow runs by default.
# inputs: ProjectAdapterConfig, dry_run flag, limit, execute_agent flag, submitter callable.
# returns: NativeSubmissionResult with submission records and registry updates.
# side_effects: Updates packet registry state on successful submission.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Returns structured errors in result objects.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketSubmissionRecord
#   - class: NativeSubmissionResult
#   - function: submit_ready_packets_to_prefect
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.structured_logger import log_event
from prefect_grace.tasks.prefect_submitter import (
    E2E_PACKET_DEPLOYMENT_NAME,
    MANAGED_PACKET_DEPLOYMENT_NAME,
    e2e_packet_flow_parameters,
    e2e_packet_flow_run_name,
    managed_packet_flow_parameters,
    managed_packet_flow_run_name,
)

#START_BLOCK_MODELS
@dataclass(frozen=True)
class PacketSubmissionRecord:
    packet_id: str
    feature_id: str
    wave_id: str
    attempt: int
    source_hash: str
    idempotency_key: str
    flow_run_id: str | None
    flow_run_name: str
    deployment_name: str
    work_queue_name: str | None
    status: Literal["submitted", "dry_run", "skipped", "failed"]
    runner_kind: Literal["e2e", "managed"] = "e2e"
    url: str | None = None
    error: str | None = None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize packet submission record to JSON-safe dict.
    # inputs:
    #   self: PacketSubmissionRecord instance.
    # returns: dict[str, Any] with all record fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "feature_id": self.feature_id,
            "wave_id": self.wave_id,
            "attempt": self.attempt,
            "source_hash": self.source_hash,
            "idempotency_key": self.idempotency_key,
            "flow_run_id": self.flow_run_id,
            "flow_run_name": self.flow_run_name,
            "deployment_name": self.deployment_name,
            "work_queue_name": self.work_queue_name,
            "status": self.status,
            "runner_kind": self.runner_kind,
            "url": self.url,
            "error": self.error,
        }


@dataclass(frozen=True)
class NativeSubmissionResult:
    ok: bool
    project_key: str
    dry_run: bool
    packets_planned: list[str]
    packets_submitted: list[str]
    records: list[PacketSubmissionRecord]
    blocked_packets: list[str]
    warnings: list[str]
    errors: list[dict[str, Any]]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize native submission result to JSON-safe dict.
    # inputs:
    #   self: NativeSubmissionResult instance.
    # returns: dict[str, Any] with all result fields and serialized records.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "dry_run": self.dry_run,
            "packets_planned": self.packets_planned,
            "packets_submitted": self.packets_submitted,
            "records": [r.to_dict() for r in self.records],
            "blocked_packets": self.blocked_packets,
            "warnings": self.warnings,
            "errors": self.errors,
        }


#END_BLOCK_MODELS
#START_BLOCK_SUBMISSION
# START_FUNCTION_CONTRACT
# name: build_idempotency_key
# purpose: Build deterministic idempotency key for packet submission.
# inputs:
#   project_key: Project identifier.
#   packet_id: Packet identifier.
#   attempt: Attempt number.
#   source_hash: Source hash from packet registry.
#   idempotency_namespace: Optional proof-run namespace for synthetic submissions.
# returns: Idempotency key string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def build_idempotency_key(
    project_key: str,
    packet_id: str,
    attempt: int,
    source_hash: str,
    idempotency_namespace: str | None = None,
) -> str:
    base = f"grace-packet:{project_key}:{packet_id}:attempt-{attempt:04d}:{source_hash}"
    if not idempotency_namespace:
        return base
    namespace = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(idempotency_namespace))
    namespace = namespace[:96]
    return f"{base}:namespace:{namespace}"


# START_FUNCTION_CONTRACT
# name: _deployment_name_for_runner
# purpose: Return the Prefect deployment name for a packet runner kind.
# inputs:
#   runner_kind: Packet runner kind.
# returns: Deployment name string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError for unsupported runner kinds.
# END_FUNCTION_CONTRACT
def _deployment_name_for_runner(runner_kind: Literal["e2e", "managed"]) -> str:
    if runner_kind == "e2e":
        return E2E_PACKET_DEPLOYMENT_NAME
    if runner_kind == "managed":
        return MANAGED_PACKET_DEPLOYMENT_NAME
    raise ValueError(f"Unsupported runner_kind: {runner_kind}")


# START_FUNCTION_CONTRACT
# name: _flow_run_name_for_runner
# purpose: Build a local flow run name for a packet runner kind.
# inputs:
#   runner_kind: Packet runner kind.
#   packet_id: Packet identifier.
#   attempt: Attempt number.
#   title: Optional packet title.
# returns: Flow run name string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError for unsupported runner kinds.
# END_FUNCTION_CONTRACT
def _flow_run_name_for_runner(
    runner_kind: Literal["e2e", "managed"],
    packet_id: str,
    attempt: int,
    title: str | None,
) -> str:
    if runner_kind == "e2e":
        return e2e_packet_flow_run_name(packet_id, attempt, title)
    if runner_kind == "managed":
        return managed_packet_flow_run_name(packet_id, title)
    raise ValueError(f"Unsupported runner_kind: {runner_kind}")


# START_FUNCTION_CONTRACT
# name: _tags_for_packet
# purpose: Build Prefect tags for submitted packet runner flow.
# inputs:
#   runner_kind: Packet runner kind.
#   packet_id: Packet identifier.
#   feature_id: Feature identifier.
#   wave_id: Wave identifier.
# returns: Ordered list of tags.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _tags_for_packet(
    *,
    runner_kind: Literal["e2e", "managed"],
    packet_id: str,
    feature_id: str,
    wave_id: str,
) -> list[str]:
    runner_tag = "e2e" if runner_kind == "e2e" else "managed-runner"
    tags = ["grace", "packet", runner_tag, f"packet:{packet_id}"]
    if feature_id:
        tags.append(f"feature:{feature_id}")
    if wave_id:
        tags.append(f"wave:{wave_id}")
    return tags


def _managed_result_payload_paths(
    *,
    runtime_state_root: Path,
    packet_id: str,
    attempt: int,
) -> tuple[Path, Path]:
    root = runtime_state_root / "managed-runner-results"
    safe_packet_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in packet_id)
    payload_path = root / safe_packet_id / f"attempt-{int(attempt):04d}" / "result_payload.json"
    return payload_path, root


# START_FUNCTION_CONTRACT
# name: _parameters_for_packet
# purpose: Build Prefect flow parameters for the selected packet runner kind.
# inputs:
#   runner_kind: Packet runner kind.
#   repo_root: Project repository root.
#   runtime_state_root: Project runtime state root.
#   packet_path: Packet file path.
#   worktree_root: Worktree root.
#   project_key: Project key.
#   packet_id: Packet identifier.
#   attempt: Attempt number.
#   base_ref: Git base reference.
#   dry_run: Flow dry-run flag.
#   execute_agent: Flow live-agent flag.
#   timeout_seconds: Timeout seconds.
# returns: Flow parameter dict for the selected runner.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError for unsupported runner kinds.
# END_FUNCTION_CONTRACT
def _parameters_for_packet(
    *,
    runner_kind: Literal["e2e", "managed"],
    repo_root: Path,
    runtime_state_root: Path,
    packet_path: Path,
    worktree_root: Path,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    dry_run: bool,
    execute_agent: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if runner_kind == "e2e":
        return e2e_packet_flow_parameters(
            project_root=str(repo_root),
            packet_path=str(packet_path),
            state_root=str(runtime_state_root),
            worktree_root=str(worktree_root),
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            dry_run=dry_run,
            execute_agent=execute_agent,
            timeout_seconds=timeout_seconds,
            keep_worktree=True,
        )
    if runner_kind == "managed":
        payload_path, payload_root = _managed_result_payload_paths(
            runtime_state_root=runtime_state_root,
            packet_id=packet_id,
            attempt=attempt,
        )
        return managed_packet_flow_parameters(
            packet_file=str(packet_path),
            repo_root=str(repo_root),
            worktree_root=str(worktree_root),
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            dry_run=dry_run,
            execute_agent=execute_agent,
            timeout_seconds=timeout_seconds,
            runtime_state_root=str(runtime_state_root),
            managed_result_payload_path=str(payload_path),
            managed_result_payload_root=str(payload_root),
        )
    raise ValueError(f"Unsupported runner_kind: {runner_kind}")


# START_FUNCTION_CONTRACT
# name: submit_ready_packets_to_prefect
# purpose: Submit ready packets as individual Prefect packet runner flow runs.
# inputs:
#   project: ProjectAdapterConfig with project_key, repo_root, runtime_state_root.
#   dry_run: If True, plan only without calling submitter.
#   limit: Optional max number of packets to submit.
#   execute_agent: If True, submitted runs use live agent mode.
#   timeout_seconds: Timeout for managed packet runner.
#   base_ref: Git base ref for worktree creation.
#   worktree_root: Optional worktree root override.
#   scheduled_for: Optional ISO8601 scheduled time.
#   continue_on_error: If True, continue submitting after failures.
#   submitter: Optional callable for submission (for testing).
#   runner_kind: Runner kind to submit, defaults to e2e.
#   idempotency_namespace: Optional namespace appended to idempotency keys.
#   trace_context: Optional structured logging trace context.
# returns: NativeSubmissionResult with submission records.
# side_effects: Updates packet registry on successful submission.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Returns structured errors in result.
# END_FUNCTION_CONTRACT
def submit_ready_packets_to_prefect(
    *,
    project: Any,
    dry_run: bool = True,
    limit: int | None = None,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    base_ref: str = "HEAD",
    worktree_root: Path | None = None,
    scheduled_for: str | None = None,
    continue_on_error: bool = False,
    submitter: Callable[..., dict[str, Any]] | None = None,
    runner_kind: Literal["e2e", "managed"] = "e2e",
    idempotency_namespace: str | None = None,
    trace_context: Any | None = None,
) -> NativeSubmissionResult:
    def _log(event: str, result: str = "ok", **extra: Any) -> None:
        log_event(
            trace_context,
            module="M-GRACE-PREFECT-NATIVE-SUBMISSION",
            fn="submit_ready_packets_to_prefect",
            block="PREFECT_SUBMISSION",
            event=event,
            result=result,
            runner_kind=runner_kind,
            **extra,
        )

    if runner_kind not in {"e2e", "managed"}:
        raise ValueError(f"Unsupported runner_kind: {runner_kind}")

    project_key = project.project_key
    repo_root = Path(project.repo_root)
    runtime_state_root = Path(project.runtime_state_root)
    registry = PacketRegistryStore(runtime_state_root / "state")

    # Use BacklogController to get submission plan
    plan = BacklogController.plan_submission(project)

    packets_planned = plan.submission_order[:]
    if limit is not None and limit > 0:
        packets_planned = packets_planned[:limit]

    warnings = plan.warnings[:]
    errors = []
    records = []
    packets_submitted = []

    # If dry-run, return plan without submission
    if dry_run:
        _log("submission_planned", "ok", packet_count=len(packets_planned), dry_run=True)
        for packet_id in packets_planned:
            packet_record = registry.load_packet(packet_id) or {}
            feature_id = str(packet_record.get("feature_id", "") or "")
            wave_id = str(packet_record.get("wave_id", "") or "")
            title = str(packet_record.get("title", "") or "")
            source_hash = str(packet_record.get("source_hash", "") or "")
            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    attempt=1,
                    source_hash=source_hash,
                    idempotency_key=build_idempotency_key(
                        project_key,
                        packet_id,
                        1,
                        source_hash,
                        idempotency_namespace=idempotency_namespace,
                    )
                    if source_hash
                    else "",
                    flow_run_id=None,
                    flow_run_name=_flow_run_name_for_runner(runner_kind, packet_id, 1, title),
                    deployment_name=_deployment_name_for_runner(runner_kind),
                    work_queue_name=None,
                    status="dry_run",
                    runner_kind=runner_kind,
                )
            )

        return NativeSubmissionResult(
            ok=True,
            project_key=project_key,
            dry_run=True,
            packets_planned=packets_planned,
            packets_submitted=[],
            records=records,
            blocked_packets=plan.blocked_packets,
            warnings=warnings,
            errors=errors,
        )

    # Execute mode: submit packets

    for packet_id in packets_planned:
        packet_record = registry.load_packet(packet_id)
        if not packet_record:
            _log("prefect_api_call_completed", "fail", packet_id_for_event=packet_id, error_code="PACKET_NOT_FOUND_IN_REGISTRY")
            error = {
                "code": "PACKET_NOT_FOUND_IN_REGISTRY",
                "packet_id": packet_id,
                "message": f"Packet {packet_id} not found in registry",
            }
            errors.append(error)
            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id="",
                    wave_id="",
                    attempt=1,
                    source_hash="",
                    idempotency_key="",
                    flow_run_id=None,
                    flow_run_name=_flow_run_name_for_runner(runner_kind, packet_id, 1, None),
                    deployment_name=_deployment_name_for_runner(runner_kind),
                    work_queue_name=None,
                    status="failed",
                    runner_kind=runner_kind,
                    error=error["message"],
                )
            )
            if not continue_on_error:
                break
            continue

        source_hash = packet_record.get("source_hash", "")
        if not source_hash:
            _log("prefect_api_call_completed", "fail", packet_id_for_event=packet_id, error_code="MISSING_SOURCE_HASH")
            error = {
                "code": "MISSING_SOURCE_HASH",
                "packet_id": packet_id,
                "message": f"Packet {packet_id} missing source_hash",
            }
            errors.append(error)
            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id=packet_record.get("feature_id", ""),
                    wave_id=packet_record.get("wave_id", ""),
                    attempt=1,
                    source_hash="",
                    idempotency_key="",
                    flow_run_id=None,
                    flow_run_name=_flow_run_name_for_runner(
                        runner_kind, packet_id, 1, packet_record.get("title", "")
                    ),
                    deployment_name=_deployment_name_for_runner(runner_kind),
                    work_queue_name=None,
                    status="failed",
                    runner_kind=runner_kind,
                    error=error["message"],
                )
            )
            if not continue_on_error:
                break
            continue

        feature_id = packet_record.get("feature_id", "")
        wave_id = packet_record.get("wave_id", "")
        title = packet_record.get("title", "")
        attempt = 1

        idempotency_key = build_idempotency_key(
            project_key,
            packet_id,
            attempt,
            source_hash,
            idempotency_namespace=idempotency_namespace,
        )

        packet_path = repo_root / packet_record.get("path", "")
        wt_root = worktree_root or (runtime_state_root / "worktrees")
        parameters = _parameters_for_packet(
            runner_kind=runner_kind,
            repo_root=repo_root,
            runtime_state_root=runtime_state_root,
            packet_path=packet_path,
            worktree_root=wt_root,
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            dry_run=not execute_agent,
            execute_agent=execute_agent,
            timeout_seconds=timeout_seconds,
        )

        tags = _tags_for_packet(
            runner_kind=runner_kind,
            packet_id=packet_id,
            feature_id=feature_id,
            wave_id=wave_id,
        )

        # Call submitter
        if submitter is None:
            _log("prefect_api_call_completed", "fail", packet_id_for_event=packet_id, error_code="NO_SUBMITTER_PROVIDED")
            error = {
                "code": "NO_SUBMITTER_PROVIDED",
                "packet_id": packet_id,
                "message": "No submitter callable provided",
            }
            errors.append(error)
            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    attempt=attempt,
                    source_hash=source_hash,
                    idempotency_key=idempotency_key,
                    flow_run_id=None,
                    flow_run_name=_flow_run_name_for_runner(runner_kind, packet_id, attempt, title),
                    deployment_name=_deployment_name_for_runner(runner_kind),
                    work_queue_name=None,
                    status="failed",
                    runner_kind=runner_kind,
                    error=error["message"],
                )
            )
            if not continue_on_error:
                break
            continue

        try:
            _log("prefect_api_call_started", "ok", packet_id_for_event=packet_id, deployment_name=_deployment_name_for_runner(runner_kind))
            submit_result = submitter(
                parameters=parameters,
                scheduled_for=scheduled_for,
                tags=tags,
                idempotency_key=idempotency_key,
            )

            flow_run_id = submit_result.get("flow_run_id")
            flow_run_name = submit_result.get(
                "flow_run_name",
                _flow_run_name_for_runner(runner_kind, packet_id, attempt, title),
            )
            deployment_name = submit_result.get("deployment_name", _deployment_name_for_runner(runner_kind))
            work_queue_name = submit_result.get("work_queue_name")
            url = submit_result.get("url")
            _log(
                "flow_run_created",
                "ok" if flow_run_id else "fail",
                packet_id_for_event=packet_id,
                flow_run_id=flow_run_id,
                flow_run_name=flow_run_name,
            )

            # Update registry with submission info
            now = datetime.now(timezone.utc).isoformat()
            registry.upsert_packet({
                **packet_record,
                "registry_status": "submitted",
                "registry_reason": "prefect_e2e_flow_run_submitted"
                if runner_kind == "e2e"
                else "prefect_flow_run_submitted",
                "prefect_flow_run_id": flow_run_id,
                "prefect_flow_run_name": flow_run_name,
                "prefect_deployment_name": deployment_name,
                "submission_runner_kind": runner_kind,
                "submission_idempotency_key": idempotency_key,
                "submitted_at": now,
            })

            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    attempt=attempt,
                    source_hash=source_hash,
                    idempotency_key=idempotency_key,
                    flow_run_id=flow_run_id,
                    flow_run_name=flow_run_name,
                    deployment_name=deployment_name,
                    work_queue_name=work_queue_name,
                    status="submitted",
                    runner_kind=runner_kind,
                    url=url,
                )
            )
            packets_submitted.append(packet_id)
            _log("prefect_api_call_completed", "ok", packet_id_for_event=packet_id, flow_run_id=flow_run_id)

        except Exception as e:
            _log("prefect_api_call_completed", "fail", packet_id_for_event=packet_id, error=str(e))
            error = {
                "code": "SUBMISSION_FAILED",
                "packet_id": packet_id,
                "message": str(e),
            }
            errors.append(error)
            records.append(
                PacketSubmissionRecord(
                    packet_id=packet_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    attempt=attempt,
                    source_hash=source_hash,
                    idempotency_key=idempotency_key,
                    flow_run_id=None,
                    flow_run_name=_flow_run_name_for_runner(runner_kind, packet_id, attempt, title),
                    deployment_name=_deployment_name_for_runner(runner_kind),
                    work_queue_name=None,
                    status="failed",
                    runner_kind=runner_kind,
                    error=str(e),
                )
            )
            if not continue_on_error:
                break

    ok = len(errors) == 0
    return NativeSubmissionResult(
        ok=ok,
        project_key=project_key,
        dry_run=False,
        packets_planned=packets_planned,
        packets_submitted=packets_submitted,
        records=records,
        blocked_packets=plan.blocked_packets,
        warnings=warnings,
        errors=errors,
    )


#END_BLOCK_SUBMISSION
