# ############################################################################
# AI_HEADER: single_live_packet_pilot
# ROLE: Guarded single-packet pilot runner with managed execution and Git mutation gate.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute one packet through managed runner and Git mutation gate with fail-closed opt-in.
# inputs: Packet path, project config, roots, opt-in flags, mutation flags, and optional test hooks.
# returns: SingleLivePacketPilotResult with bounded audit fields.
# side_effects: May create worktree, run agent, and apply Git mutations when all gates pass.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for missing opt-ins or gate failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: SingleLivePacketPilotResult
#   - function: run_single_live_packet_pilot
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.managed_packet_runner import run_managed_packet
from prefect_grace.platform.git_mutation_gate import run_git_mutation_gate
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.project_adapter import load_project_adapter


@dataclass
class SingleLivePacketPilotResult:
    """Result of single live packet pilot execution."""
    ok: bool
    packet_id: str
    status: str
    dry_run: bool
    live_opt_in_confirmed: bool
    git_mutation_requested: bool
    managed_runner_status: str | None = None
    scope_status: str | None = None
    evidence_status: str | None = None
    review_status: str | None = None
    git_gate_status: str | None = None
    worktree_path: str = ""
    branch_name: str = ""
    live_agents_started: int = 0
    prefect_runs_created: int = 0
    blocker_reason: str | None = None
    blockers: list[dict[str, Any]] = field(default_factory=list)
    managed_runner_result: dict[str, Any] = field(default_factory=dict)
    git_gate_result: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert pilot result to a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing bounded audit fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _add_blocker(result: SingleLivePacketPilotResult, code: str, message: str, **extra: Any) -> None:
    result.blockers.append(_block(code, message, **extra))
    if result.blocker_reason is None:
        result.blocker_reason = code


# START_FUNCTION_CONTRACT
# name: run_single_live_packet_pilot
# purpose: Execute one packet through managed runner and Git mutation gate with fail-closed opt-in.
# inputs:
#   packet: Path to EXECUTION_PACKET.md.
#   repo_root: Repository root directory.
#   worktree_root: Worktree root directory for isolation.
#   project_key: Project identifier.
#   attempt: Execution attempt number.
#   base_ref: Git base reference for worktree.
#   target_branch: Target branch for Git merge (not used in pilot).
#   remote: Remote name for Git push.
#   dry_run: Safe default, no agent execution or Git mutations.
#   execute_agent: Explicitly allow live agent execution.
#   acknowledge_live_agent: Required operator acknowledgement flag.
#   opt_in_token: Required token value or None to read GRACE_LIVE_AGENT_OPT_IN.
#   commit: Request guarded commit.
#   push: Request guarded push.
#   merge: Request guarded merge to target branch.
#   apply_git_mutations: Allow Git mutations to be applied.
#   timeout_seconds: Agent timeout.
#   managed_runner: Optional test hook for managed runner.
#   git_gate: Optional test hook for Git mutation gate.
# returns: SingleLivePacketPilotResult with bounded audit fields.
# side_effects: May create worktree, run agent if execute_agent=True and dry_run=False, and apply Git mutations if apply_git_mutations=True.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for missing opt-ins, scope violations, invalid evidence, missing review, or Git gate failures.
# END_FUNCTION_CONTRACT
def run_single_live_packet_pilot(
    *,
    packet: Path | str,
    repo_root: Path | str,
    worktree_root: Path | str,
    project_key: str,
    attempt: int,
    base_ref: str,
    target_branch: str,
    remote: str = "origin",
    dry_run: bool = True,
    execute_agent: bool = False,
    acknowledge_live_agent: bool = False,
    opt_in_token: str | None = None,
    commit: bool = False,
    push: bool = False,
    merge: bool = False,
    apply_git_mutations: bool = False,
    timeout_seconds: int = 3600,
    managed_runner: Callable[..., Any] | None = None,
    git_gate: Callable[..., Any] | None = None,
) -> SingleLivePacketPilotResult:
    """
    Execute one packet through managed runner and Git mutation gate with fail-closed opt-in.

    Sequence:
    1. Parse EXECUTION_PACKET.md to extract packet_id
    2. Check live agent opt-in gates (if execute_agent=True)
    3. Run managed packet runner (creates worktree, runs agent if approved)
    4. Check Git mutation gates (if commit or push requested)
    5. Run Git mutation gate (validates evidence/review, applies mutations if approved)
    6. Return SingleLivePacketPilotResult

    Args:
        packet: Path to EXECUTION_PACKET.md
        repo_root: Repository root directory
        worktree_root: Worktree root directory
        project_key: Project identifier
        attempt: Execution attempt number
        base_ref: Git base reference
        target_branch: Target branch for merge
        remote: Remote name for push
        dry_run: Safe default, no agent execution or Git mutations
        execute_agent: Explicitly allow live agent execution
        acknowledge_live_agent: Required operator acknowledgement flag
        opt_in_token: Required token value or None to read GRACE_LIVE_AGENT_OPT_IN
        commit: Request guarded commit
        push: Request guarded push
        merge: Request guarded merge to target branch
        apply_git_mutations: Allow Git mutations to be applied
        timeout_seconds: Agent timeout
        managed_runner: Optional test hook for managed runner
        git_gate: Optional test hook for Git mutation gate

    Returns:
        SingleLivePacketPilotResult with bounded audit fields
    """
    packet_path = Path(packet)
    repo = Path(repo_root)
    worktrees = Path(worktree_root)

    # Parse packet to get packet_id
    try:
        parsed = parse_packet_markdown(packet_path)
        packet_id = parsed.packet_id
    except Exception as e:
        result = SingleLivePacketPilotResult(
            ok=False,
            packet_id="unknown",
            status="blocked",
            dry_run=dry_run,
            live_opt_in_confirmed=False,
            git_mutation_requested=commit or push or merge,
            blocker_reason="packet_parse_failed",
        )
        _add_blocker(result, "packet_parse_failed", f"Failed to parse packet: {e}")
        return result

    result = SingleLivePacketPilotResult(
        ok=False,
        packet_id=packet_id,
        status="planned" if dry_run else "blocked",
        dry_run=dry_run,
        live_opt_in_confirmed=False,
        git_mutation_requested=commit or push or merge,
    )

    # Check live agent opt-in gates
    if execute_agent and not dry_run:
        token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_LIVE_AGENT_OPT_IN")

        if not acknowledge_live_agent:
            _add_blocker(result, "live_opt_in_ack_required", "--i-understand-live-agent is required for live agent execution")
        if token != "1":
            _add_blocker(result, "live_opt_in_token_required", "GRACE_LIVE_AGENT_OPT_IN=1 is required for live agent execution")

        if result.blockers:
            result.live_opt_in_confirmed = False
            result.status = "blocked"
            return result

        result.live_opt_in_confirmed = True
    else:
        # Dry run or no agent execution - opt-in not required
        result.live_opt_in_confirmed = True

    # Load project config to get runtime_state_root
    try:
        project = load_project_adapter()
    except Exception:
        project = None

    # Run managed packet runner
    if managed_runner is None:
        managed_runner = run_managed_packet

    try:
        runner_result = managed_runner(
            packet_file=packet_path,
            repo_root=repo,
            worktree_root=worktrees,
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            dry_run=dry_run,
            execute_agent=execute_agent,
            timeout_seconds=timeout_seconds,
            keep_worktree=True,
            project=project,
        )

        # Convert to dict if it's a dataclass
        if hasattr(runner_result, "to_dict"):
            result.managed_runner_result = runner_result.to_dict()
        else:
            result.managed_runner_result = dict(runner_result)

        result.managed_runner_status = result.managed_runner_result.get("domain_status")
        result.worktree_path = result.managed_runner_result.get("worktree_path", "")
        result.branch_name = result.managed_runner_result.get("branch_name", "")

        # Track live agents started
        if execute_agent and not dry_run:
            result.live_agents_started = 1

        # Check managed runner status
        if result.managed_runner_status == "scope_blocked":
            result.scope_status = "blocked"
            _add_blocker(result, "scope_guard_failed", "Managed runner scope check failed")
        elif result.managed_runner_status == "agent_failed":
            _add_blocker(result, "agent_failed", "Agent execution failed")
        elif result.managed_runner_status == "runner_error":
            _add_blocker(result, "runner_error", result.managed_runner_result.get("blocker_reason", "Runner error"))
        elif result.managed_runner_status == "passed":
            result.scope_status = "passed"
        else:
            _add_blocker(result, "unexpected_runner_status", f"Unexpected runner status: {result.managed_runner_status}")

    except Exception as e:
        _add_blocker(result, "managed_runner_failed", f"Managed runner execution failed: {e}")
        result.managed_runner_status = "runner_error"
        result.status = "blocked"
        return result

    # If no Git mutations requested, we're done
    if not commit and not push:
        if not result.blockers:
            result.ok = True
            result.status = "planned" if dry_run else "completed"
        else:
            result.status = "blocked"
        return result

    # Run Git mutation gate
    if git_gate is None:
        git_gate = run_git_mutation_gate

    try:
        gate_result = git_gate(
            packet=packet_path,
            repo_root=repo,
            worktree_root=worktrees,
            worktree_path=Path(result.worktree_path) if result.worktree_path else worktrees / f"{project_key}-{packet_id}-{attempt:04d}",
            project_key=project_key,
            packet_id=packet_id,
            attempt=attempt,
            base_ref=base_ref,
            target_branch=target_branch,
            remote=remote,
            dry_run=dry_run or not apply_git_mutations,
            apply=apply_git_mutations and not dry_run,
            commit=commit,
            push=push,
            merge=merge,
            understand_merge=merge,  # Pass through merge flag as understand_merge
        )

        # Convert to dict if it's a dataclass
        if hasattr(gate_result, "to_dict"):
            result.git_gate_result = gate_result.to_dict()
        else:
            result.git_gate_result = dict(gate_result)

        result.git_gate_status = result.git_gate_result.get("status")

        # Extract evidence and review status from git gate result
        evidence = result.git_gate_result.get("evidence", {})
        review = result.git_gate_result.get("review", {})

        if evidence.get("valid"):
            result.evidence_status = "valid"
        elif evidence.get("present"):
            result.evidence_status = "invalid"
        else:
            result.evidence_status = "missing"

        if review.get("accepted"):
            result.review_status = "accepted"
        elif review.get("present"):
            result.review_status = "not_accepted"
        else:
            result.review_status = "missing"

        # Check git gate blockers
        gate_blockers = result.git_gate_result.get("blockers", [])
        for blocker in gate_blockers:
            _add_blocker(result, blocker.get("code", "git_gate_blocker"), blocker.get("message", "Git gate blocked"))

        # Get ok status from result dict
        gate_ok = result.git_gate_result.get("ok", False)

        if not gate_ok:
            result.status = "blocked"
        elif result.git_gate_status == "applied":
            result.status = "applied"
            result.ok = True
        elif result.git_gate_status == "planned":
            result.status = "planned"
            result.ok = True
        else:
            result.status = "blocked"

    except Exception as e:
        _add_blocker(result, "git_gate_failed", f"Git mutation gate execution failed: {e}")
        result.git_gate_status = "error"
        result.status = "blocked"
        return result

    # Final status determination
    if not result.blockers:
        result.ok = True
        if result.git_gate_status == "applied":
            result.status = "applied"
        elif result.git_gate_status == "planned" or dry_run:
            result.status = "planned"
        else:
            result.status = "completed"
    else:
        result.ok = False
        result.status = "blocked"

    return result
