# ############################################################################
# AI_HEADER: managed_packet_runner
# ROLE: Launch and monitor packet execution in isolated worktree with scope validation.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute single packet in isolated worktree with agent execution and scope guard validation.
# inputs: Packet file, repo root, worktree root, project key, packet ID, attempt, base ref, execution flags.
# returns: ManagedPacketRunResult with domain status and execution details.
# side_effects: Creates worktree, launches agent, evaluates scope, preserves worktree by default.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Fails closed on parse/worktree/launcher/lifecycle errors, returns domain status.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ManagedPacketRunResult
#   - function: run_managed_packet
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.structured_logger import log_event
from prefect_grace.platform.worktree_manager import WorktreeManager
from prefect_grace.platform.worktree_scope_lifecycle import evaluate_worktree_scope
from prefect_grace.platform.status_model import DomainStatus, normalize_domain_status
from prefect_grace.tasks.codex_launcher import launch_codex_for_packet


@dataclass(frozen=True)
class ManagedPacketRunResult:
    """Result of managed packet execution with domain status."""
    ok: bool
    domain_status: str  # "passed", "scope_blocked", "agent_failed", "runner_error" - normalized via DomainStatus
    packet_id: str
    attempt: int
    worktree_path: str
    branch_name: str
    changed_files: list[str]
    agent_result: dict[str, Any]
    lifecycle_result: dict[str, Any]
    scope_guard: dict[str, Any]
    artifact_ids: list[str] = field(default_factory=list)
    blocker_reason: str | None = None

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert ManagedPacketRunResult to dictionary for serialization.
    # inputs: None (instance method)
    # returns: dict[str, Any] - Dictionary with all result fields.
    # side_effects: None
    # emitted_logs: None
    # error_behavior: None
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "domain_status": self.domain_status,
            "packet_id": self.packet_id,
            "attempt": self.attempt,
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "changed_files": list(self.changed_files),
            "agent_result": dict(self.agent_result),
            "lifecycle_result": dict(self.lifecycle_result),
            "scope_guard": dict(self.scope_guard),
            "artifact_ids": list(self.artifact_ids),
            "blocker_reason": self.blocker_reason,
        }


# START_FUNCTION_CONTRACT
# name: run_managed_packet
# purpose: Execute packet in isolated worktree with agent and scope validation.
# inputs:
#   packet_file: Path to EXECUTION_PACKET.md.
#   repo_root: Repository root directory.
#   worktree_root: Worktree root directory for isolation.
#   project_key: Project identifier.
#   packet_id: Packet identifier.
#   attempt: Execution attempt number.
#   base_ref: Git base reference for worktree.
#   dry_run: Safe default, no agent execution.
#   execute_agent: Explicitly allow live agent execution.
#   timeout_seconds: Agent timeout.
#   keep_worktree: Preserve worktree after execution.
#   runtime_state_root: Optional registry state root for launcher packet lookup.
#   launcher: Optional launcher callable (default: launch_codex_for_packet).
#   project: Optional project config for executor selection.
#   trace_context: Optional structured logging trace context.
# returns: ManagedPacketRunResult with domain status and execution details.
# side_effects: Creates worktree, launches agent if execute_agent=True and dry_run=False, evaluates scope, preserves worktree if keep_worktree=True.
# emitted_logs: structured execution_trace.jsonl when trace_context is provided.
# error_behavior: Fails closed on parse/worktree/launcher/lifecycle errors, returns runner_error domain status. Scope violations return scope_blocked. Agent failures return agent_failed. Success returns passed.
# END_FUNCTION_CONTRACT
def run_managed_packet(
    *,
    packet_file: Path,
    repo_root: Path,
    worktree_root: Path,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    dry_run: bool = True,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
    runtime_state_root: str | Path | None = None,
    launcher: Callable[..., dict[str, Any]] | None = None,
    project: Any | None = None,
    trace_context: Any | None = None,
) -> ManagedPacketRunResult:
    """
    Execute packet in isolated worktree with agent and scope validation.

    Sequence:
    1. Parse EXECUTION_PACKET.md
    2. Select executor (if project provided)
    3. Create or resolve packet worktree
    4. Run agent in worktree (if execute_agent=True and dry_run=False)
    5. Evaluate worktree scope
    6. Return ManagedPacketRunResult

    Domain status priority:
    - runner_error: setup/parsing/worktree/launcher failed before reliable post-scope result
    - scope_blocked: post-agent lifecycle scope check found violations
    - agent_failed: agent returned non-zero/stalled/failed, but scope is clean
    - passed: agent returned success and scope is clean

    Args:
        packet_file: Path to EXECUTION_PACKET.md
        repo_root: Repository root directory
        worktree_root: Worktree root directory
        project_key: Project identifier
        packet_id: Packet identifier
        attempt: Execution attempt number
        base_ref: Git base reference
        dry_run: Safe default, no agent execution
        execute_agent: Explicitly allow live agent execution
        timeout_seconds: Agent timeout
        keep_worktree: Preserve worktree after execution
        runtime_state_root: Optional runtime state root for launcher registry lookup
        launcher: Optional launcher callable (default: launch_codex_for_packet)
        project: Optional project config for executor selection

    Returns:
        ManagedPacketRunResult with domain status and execution details
    """
    def _log(event: str, result: str = "ok", **extra: Any) -> None:
        log_event(
            trace_context,
            module="M-GRACE-MANAGED-PACKET-RUNNER",
            fn="run_managed_packet",
            block="AGENT_EXECUTION",
            event=event,
            result=result,
            **extra,
        )

    # Default launcher
    if launcher is None:
        launcher = launch_codex_for_packet

    # Parse packet
    try:
        packet = parse_packet_markdown(packet_file)
    except Exception as e:
        _log("packet_parse_failed", "fail", error=str(e))
        return ManagedPacketRunResult(
            ok=False,
            domain_status=DomainStatus.RUNNER_ERROR.value,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path="",
            branch_name="",
            changed_files=[],
            agent_result={},
            lifecycle_result={},
            scope_guard={},
            blocker_reason=f"Packet parse failed: {e}",
        )

    # Select executor if project provided
    selected_executor = None
    if project is not None:
        from prefect_grace.platform.executor_registry import select_executor_for_packet, record_executor_attempt
        from prefect_grace.platform.state_store import ExecutorHistoryStore

        history_store = ExecutorHistoryStore(Path(project.runtime_state_root))
        history = history_store.list_executions()

        role = "coder"  # Default role, ParsedPacket doesn't have role field
        selection = select_executor_for_packet(
            project=project,
            packet=packet,
            history=history,
            requested_executor=None,  # ParsedPacket doesn't have requested_executor field
        )

        if not selection.ok:
            _log("executor_selection_failed", "fail", reason=selection.reason)
            return ManagedPacketRunResult(
                ok=False,
                domain_status="runner_error",
                packet_id=packet_id,
                attempt=attempt,
                worktree_path="",
                branch_name="",
                changed_files=[],
                agent_result={},
                lifecycle_result={},
                scope_guard={},
                blocker_reason=f"no_executor_available: {selection.reason}",
            )

        selected_executor = selection.selected

        # Fail closed if executor kind is unsupported
        if selected_executor.kind not in ["codex", "mock"]:
            # Record skipped attempt
            record_executor_attempt(
                state_root=Path(project.runtime_state_root),
                packet_id=packet_id,
                role=role,
                executor_id=selected_executor.executor_id,
                result={
                    "status": "skipped",
                    "selection_reason": "unsupported_executor_kind",
                    "executor_kind": selected_executor.kind,
                },
                attempt=attempt,
            )
            _log("executor_selection_failed", "fail", executor_kind=selected_executor.kind)
            return ManagedPacketRunResult(
                ok=False,
                domain_status="runner_error",
                packet_id=packet_id,
                attempt=attempt,
                worktree_path="",
                branch_name="",
                changed_files=[],
                agent_result={},
                lifecycle_result={},
                scope_guard={},
                blocker_reason=f"unsupported_executor_kind:{selected_executor.kind}",
            )

    # Create or resolve worktree
    try:
        manager = WorktreeManager(
            repo_root=repo_root,
            worktree_root=worktree_root,
            project_key=project_key,
        )

        # Check if worktree already exists for this packet_id/attempt
        worktree_status = manager.status(packet_id=packet_id, attempt=attempt)

        if worktree_status.exists:
            # Reuse existing worktree
            worktree_path = worktree_status.path
            branch_name = worktree_status.branch_name
            _log("worktree_created", "ok", reused=True, worktree_path=str(worktree_path), branch_name=branch_name)
        else:
            # Create new worktree
            worktree_result = manager.create_packet_worktree(
                packet_id=packet_id,
                attempt=attempt,
                base_ref=base_ref,
            )
            worktree_path = worktree_result.worktree_path
            branch_name = worktree_result.branch_name
            _log("worktree_created", "ok", reused=False, worktree_path=str(worktree_path), branch_name=branch_name)
    except Exception as e:
        _log("worktree_created", "fail", error=str(e))
        return ManagedPacketRunResult(
            ok=False,
            domain_status=DomainStatus.RUNNER_ERROR.value,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path="",
            branch_name="",
            changed_files=[],
            agent_result={},
            lifecycle_result={},
            scope_guard={},
            blocker_reason=f"Worktree creation failed: {e}",
        )

    # Run agent in worktree
    agent_result: dict[str, Any] = {}
    agent_ok = True
    if execute_agent and not dry_run:
        try:
            _log("agent_started", "ok", dry_run=dry_run, execute_agent=execute_agent)
            # Determine runtime_state_root from explicit flow parameter or project.
            effective_runtime_state_root = runtime_state_root
            if project is not None:
                effective_runtime_state_root = effective_runtime_state_root or getattr(project, "runtime_state_root", None)

            agent_result = launcher(
                packet_id,
                dry_run=False,
                timeout_seconds=timeout_seconds,
                workdir_override=worktree_path,
                runtime_state_root=effective_runtime_state_root,
                project_root=repo_root,
            )
            agent_ok = agent_result.get("returncode", 1) == 0
            _log(
                "agent_completed",
                "ok" if agent_ok else "fail",
                returncode=agent_result.get("returncode"),
                termination_reason=agent_result.get("termination_reason"),
            )
        except Exception as e:
            _log("agent_completed", "fail", error=str(e))
            return ManagedPacketRunResult(
                ok=False,
                domain_status="runner_error",
                packet_id=packet_id,
                attempt=attempt,
                worktree_path=str(worktree_path),
                branch_name=branch_name,
                changed_files=[],
                agent_result={},
                lifecycle_result={},
                scope_guard={},
                blocker_reason=f"Agent launch failed: {e}",
            )
    else:
        # Dry run or no agent execution
        _log("agent_started", "skip", dry_run=dry_run, execute_agent=execute_agent)
        agent_result = {
            "returncode": 0,
            "termination_reason": "dry_run" if dry_run else "no_agent_execution",
            "packet_id": packet_id,
            "dry_run": dry_run,
            "execute_agent": execute_agent,
        }
        agent_ok = True
        _log("agent_completed", "skip", termination_reason=agent_result["termination_reason"])

    # Include executor metadata in agent_result
    if selected_executor is not None:
        agent_result["executor_id"] = selected_executor.executor_id
        agent_result["executor_kind"] = selected_executor.kind

    # Evaluate worktree scope
    try:
        _log("scope_validation_started", "ok")
        lifecycle_result = evaluate_worktree_scope(
            packet_file=packet_file,
            packet_id=packet_id,
            attempt=attempt,
            worktree_root=worktree_root,
            repo_root=repo_root,
            project_key=project_key,
            base_ref=base_ref,
            keep_on_failure=keep_worktree,
        )
    except Exception as e:
        _log("scope_validation_completed", "fail", error=str(e))
        return ManagedPacketRunResult(
            ok=False,
            domain_status=DomainStatus.RUNNER_ERROR.value,
            packet_id=packet_id,
            attempt=attempt,
            worktree_path=str(worktree_path),
            branch_name=branch_name,
            changed_files=[],
            agent_result=agent_result,
            lifecycle_result={},
            scope_guard={},
            blocker_reason=f"Lifecycle evaluation failed: {e}",
        )

    lifecycle_status = lifecycle_result.status
    changed_files = lifecycle_result.changed_files
    scope_guard = lifecycle_result.scope_guard
    lifecycle_result_dict = lifecycle_result.to_dict()
    _log(
        "scope_validation_completed",
        "ok" if lifecycle_status == "passed" else "fail",
        lifecycle_status=lifecycle_status,
        changed_file_count=len(changed_files),
    )

    # Determine domain status (priority: runner_error > scope_blocked > agent_failed > passed)
    # Use DomainStatus enum for normalization
    if lifecycle_status == "scope_blocked":
        domain_status = DomainStatus.SCOPE_BLOCKED.value
        ok = False
        blocker_reason = lifecycle_result.blocker_reason
    elif not agent_ok:
        domain_status = DomainStatus.AGENT_FAILED.value
        ok = False
        blocker_reason = f"Agent failed: returncode={agent_result.get('returncode')}, reason={agent_result.get('termination_reason')}"
    elif lifecycle_status == "passed":
        domain_status = DomainStatus.CHECK_PASSED.value
        ok = True
        blocker_reason = None
    else:
        domain_status = DomainStatus.RUNNER_ERROR.value
        ok = False
        blocker_reason = f"Unexpected lifecycle status: {lifecycle_status}"
    _log(
        "domain_status_determined",
        "ok" if ok else "fail",
        domain_status=domain_status,
        blocker_reason=blocker_reason,
    )

    # Record executor attempt if project provided
    if selected_executor is not None and project is not None:
        from prefect_grace.platform.executor_registry import record_executor_attempt

        role = "coder"  # Default role, ParsedPacket doesn't have role field
        agent_result_with_domain = dict(agent_result)
        agent_result_with_domain["domain_status"] = domain_status
        agent_result_with_domain["feature_id"] = packet.feature_id
        agent_result_with_domain["wave_id"] = packet.wave_id
        agent_result_with_domain["source_hash"] = packet.source_hash

        record_executor_attempt(
            state_root=Path(project.runtime_state_root),
            packet_id=packet_id,
            role=role,
            executor_id=selected_executor.executor_id,
            result=agent_result_with_domain,
            attempt=attempt,
        )

    return ManagedPacketRunResult(
        ok=ok,
        domain_status=domain_status,
        packet_id=packet_id,
        attempt=attempt,
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        changed_files=changed_files,
        agent_result=agent_result,
        lifecycle_result=lifecycle_result_dict,
        scope_guard=scope_guard,
        blocker_reason=blocker_reason,
    )
