# ############################################################################
# AI_HEADER: feature_recovery
# ROLE: Deterministic recovery/escalation policy for failed packets.
# Phase 1: library + tests only, no live orchestration integration.
# ############################################################################

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("feature_recovery")


class FailureClass(str, Enum):
    RETRYABLE_CODER = "retryable_coder"
    RETRYABLE_VERIFIER = "retryable_verifier"
    RETRYABLE_REVIEWER = "retryable_reviewer"
    ARCHITECT_REPACK_NEEDED = "architect_repack_needed"
    ARCHITECT_ESCALATION_NEEDED = "architect_escalation_needed"
    MERGE_RETRYABLE = "merge_retryable"
    TRUE_BLOCKER = "true_blocker"
    UNKNOWN_RETRYABLE = "unknown_retryable"


class RecoveryAction(str, Enum):
    RETRY_SAME_CODER = "retry_same_coder"
    SWITCH_CODER = "switch_coder"
    RETURN_TO_ARCHITECT = "return_to_architect"
    ESCALATE_ARCHITECT = "escalate_architect"
    RETRY_VERIFIER = "retry_verifier"
    RETRY_REVIEWER = "retry_reviewer"
    RETRY_MERGE = "retry_merge"
    BLOCK_FEATURE = "block_feature"
    NEW_ARCHITECT = "new_architect"
    NO_ACTION = "no_action"


class RecoveryDecision(BaseModel):
    action: RecoveryAction
    failure_class: FailureClass
    reason: str
    next_executor_hint: str | None = None
    next_acceptance_profile: str | None = None
    architect_instruction: str | None = None
    reviewer_instruction: str | None = None
    max_attempts_reached: bool = False
    audit_payload: dict[str, Any] = Field(default_factory=dict)
    resume_session_id: str | None = None  # TZ_SESSION_RESUME.md Phase 3
    fork_session: bool = False            # TZ_SESSION_RESUME.md Phase 3


class FailureSignal(BaseModel):
    feature_id: str = ""
    packet_id: str = ""
    packet_state: str = ""
    domain_status: str | None = None
    reason: str | None = None
    acceptance_verdict: str | None = None
    evidence_verifier_verdict: str | None = None
    reviewer_verdict: str | None = None
    merge_error: str | None = None
    blocked_reason: str | None = None
    acceptance_profile: str | None = None
    attempt_count: int = 0
    coder_attempt_count: int = 0
    architect_repair_count: int = 0
    architect_switch_count: int = 0
    reviewer_reject_count: int = 0
    verifier_reject_count: int = 0
    merge_attempt_count: int = 0
    current_executor_id: str | None = None
    previous_executor_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)


class RecoveryPolicy(BaseModel):
    max_same_coder_attempts: int = 2
    max_total_coder_attempts: int = 4
    max_architect_repairs: int = 2
    max_reviewer_retries: int = 2
    max_verifier_retries: int = 2
    max_merge_retries: int = 2
    allow_profile_escalation: bool = True
    allow_model_switch: bool = True
    never_downgrade_strict: bool = True


NO_CHANGES_PATTERNS = ("no changes", "no_changes", "no_changes_produced", "no changes produced")


def _safe_next_profile(current: str | None, proposed: str | None, policy: RecoveryPolicy) -> str | None:
    if proposed is None:
        return None
    if policy.never_downgrade_strict and current == "STRICT" and proposed != "STRICT":
        return "STRICT"
    return proposed


def classify_failure(signal: FailureSignal) -> FailureClass:
    reason = (signal.reason or "").lower()
    state = signal.packet_state.lower()
    domain = (signal.domain_status or "").lower()
    merge_err = (signal.merge_error or "").lower()
    ev_verdict = signal.evidence_verifier_verdict
    rv_verdict = signal.reviewer_verdict

    fc = _classify(signal, reason, state, domain, merge_err, ev_verdict, rv_verdict)

    _log.info("classify_failure",
        packet_id=signal.packet_id,
        failure_class=fc.value,
        packet_state=state,
        reason=signal.reason or "",
        ev_verdict=ev_verdict or "",
        rv_verdict=rv_verdict or "",
        merge_error=signal.merge_error or "",
    )
    return fc


def _classify(signal, reason, state, domain, merge_err, ev_verdict, rv_verdict) -> FailureClass:
    if merge_err and "dirty_target_repo" in merge_err:
        return FailureClass.TRUE_BLOCKER
    if merge_err and "conflict" in merge_err:
        return FailureClass.TRUE_BLOCKER

    if any(kw in reason for kw in ["missing cli", "missing api key", "auth failed",
                                    "quota exceeded", "permission denied", "repository inaccessible",
                                    "user decision required", "user approval required",
                                    "security required", "billing required", "data-loss approval"]):
        return FailureClass.TRUE_BLOCKER

    # Reviewer is the later gate and must override an earlier verifier PASS.
    if rv_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if rv_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if rv_verdict and rv_verdict != "PASS":
        return FailureClass.RETRYABLE_REVIEWER

    # ── Evidence Verifier ───────────────────────────────────────────
    if ev_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if ev_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if ev_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE
    if ev_verdict:
        return FailureClass.RETRYABLE_VERIFIER

    # ── Reviewer ────────────────────────────────────────────────────
    if rv_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if rv_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if rv_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE
    if rv_verdict:
        return FailureClass.RETRYABLE_REVIEWER

    # ── Blocked state ──────────────────────────────────────────────
    if state == "blocked":
        if "scope impossible" in reason or "cannot be done" in reason:
            return FailureClass.ARCHITECT_REPACK_NEEDED
        return FailureClass.TRUE_BLOCKER

    # ── Merge failures ─────────────────────────────────────────────
    if merge_err:
        if "branch" in merge_err or "worktree" in merge_err:
            return FailureClass.MERGE_RETRYABLE
        if "timeout" in merge_err or "connection" in merge_err or "transient" in merge_err:
            return FailureClass.MERGE_RETRYABLE
        return FailureClass.TRUE_BLOCKER

    # ── Scope guard violations ──────────────────────────────────────
    if state in ("rejected", "failed") and "scope" in reason:
        if "impossible" in reason or "cannot" in reason:
            return FailureClass.ARCHITECT_REPACK_NEEDED
        return FailureClass.RETRYABLE_CODER

    # ── Agent runtime timeouts ─────────────────────────────────────
    if "timed out" in reason or "timeout" in reason:
        return FailureClass.RETRYABLE_CODER

    # ── Deterministic acceptance ────────────────────────────────────
    if state in ("rejected", "failed") and domain in ("rejected", "runner_error"):
        if any(p in reason for p in NO_CHANGES_PATTERNS) or "test" in reason or "command" in reason or "evidence" in reason:
            return FailureClass.RETRYABLE_CODER
        if "pycompile" in reason or "syntax" in reason:
            return FailureClass.RETRYABLE_CODER
        if "blocked" in domain or "blocked" in state:
            return FailureClass.ARCHITECT_REPACK_NEEDED
        return FailureClass.RETRYABLE_CODER

    # ── Default ─────────────────────────────────────────────────────
    if signal.attempt_count <= 1:
        return FailureClass.UNKNOWN_RETRYABLE
    return FailureClass.ARCHITECT_ESCALATION_NEEDED


def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy | None = None) -> RecoveryDecision:
    policy = policy or RecoveryPolicy()
    fc = classify_failure(signal)

    # ── TRUE_BLOCKER ────────────────────────────────────────────────
    if fc == FailureClass.TRUE_BLOCKER:
        decision = RecoveryDecision(
            action=RecoveryAction.BLOCK_FEATURE,
            failure_class=fc,
            reason=signal.reason or "true blocker",
            max_attempts_reached=True,
        )

    # ── ARCHITECT_ESCALATION_NEEDED ─────────────────────────────────
    elif fc == FailureClass.ARCHITECT_ESCALATION_NEEDED:
        decision = RecoveryDecision(
            action=RecoveryAction.ESCALATE_ARCHITECT,
            failure_class=fc,
            reason=signal.reason or "repeated unknown failure",
        )

    # ── ARCHITECT_REPACK_NEEDED ─────────────────────────────────────
    elif fc == FailureClass.ARCHITECT_REPACK_NEEDED:
        if signal.architect_repair_count >= policy.max_architect_repairs:
            decision = RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"architect repair repeated {signal.architect_repair_count}x, escalating",
                max_attempts_reached=True,
            )
        else:
            decision = RecoveryDecision(
                action=RecoveryAction.RETURN_TO_ARCHITECT,
                failure_class=fc,
                reason=signal.reason or "architect repack needed",
                architect_instruction=f"Packet {signal.packet_id} failed: {signal.reason}",
            )

    # ── Coder ladders ──────────────────────────────────────────────
    elif fc == FailureClass.RETRYABLE_CODER:
        if signal.coder_attempt_count >= policy.max_total_coder_attempts:
            decision = RecoveryDecision(
                action=RecoveryAction.RETURN_TO_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_REPACK_NEEDED,
                reason=f"coder failed {signal.coder_attempt_count}x, returning to architect",
                max_attempts_reached=True,
            )
        elif signal.coder_attempt_count >= policy.max_same_coder_attempts:
            if policy.allow_model_switch:
                decision = RecoveryDecision(
                    action=RecoveryAction.SWITCH_CODER,
                    failure_class=fc,
                    reason=f"coder failed {signal.coder_attempt_count}x, switching model",
                    next_executor_hint=_next_executor_hint(signal),
                )
            else:
                decision = RecoveryDecision(
                    action=RecoveryAction.RETRY_SAME_CODER,
                    failure_class=fc,
                    reason=f"coder failed {signal.coder_attempt_count}x, model switch disabled, retrying same",
                    next_executor_hint=signal.current_executor_id,
                )
        else:
            decision = RecoveryDecision(
                action=RecoveryAction.RETRY_SAME_CODER,
                failure_class=fc,
                reason=f"coder failed (attempt {signal.coder_attempt_count + 1}), retrying same",
                next_executor_hint=signal.current_executor_id,
            )

    # ── Verifier ladders ────────────────────────────────────────────
    elif fc == FailureClass.RETRYABLE_VERIFIER:
        if signal.verifier_reject_count >= policy.max_verifier_retries:
            decision = RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"verifier failed {signal.verifier_reject_count}x, escalating",
                max_attempts_reached=True,
            )
        else:
            decision = RecoveryDecision(
                action=RecoveryAction.RETRY_VERIFIER,
                failure_class=fc,
                reason=f"verifier retry #{signal.verifier_reject_count + 1}",
            )

    # ── Reviewer ladders ────────────────────────────────────────────
    elif fc == FailureClass.RETRYABLE_REVIEWER:
        if signal.reviewer_reject_count >= policy.max_reviewer_retries:
            decision = RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"reviewer failed {signal.reviewer_reject_count}x, escalating",
                max_attempts_reached=True,
            )
        else:
            decision = RecoveryDecision(
                action=RecoveryAction.RETRY_REVIEWER,
                failure_class=fc,
                reason=f"reviewer retry #{signal.reviewer_reject_count + 1}",
            )

    # ── Merge ladders ───────────────────────────────────────────────
    elif fc == FailureClass.MERGE_RETRYABLE:
        if signal.merge_attempt_count >= policy.max_merge_retries:
            decision = RecoveryDecision(
                action=RecoveryAction.BLOCK_FEATURE,
                failure_class=FailureClass.TRUE_BLOCKER,
                reason=f"merge failed {signal.merge_attempt_count}x, blocking",
                max_attempts_reached=True,
            )
        else:
            decision = RecoveryDecision(
                action=RecoveryAction.RETRY_MERGE,
                failure_class=fc,
                reason=f"merge retry #{signal.merge_attempt_count + 1}",
            )

    # ── UNKNOWN_RETRYABLE ──────────────────────────────────────────
    else:
        decision = RecoveryDecision(
            action=RecoveryAction.RETRY_SAME_CODER,
            failure_class=fc,
            reason=f"unknown failure, retrying (attempt {signal.attempt_count + 1})",
        )

    # ── Post-process: enforce never_downgrade_strict + populate audit ─
    decision.next_acceptance_profile = _safe_next_profile(
        signal.acceptance_profile, decision.next_acceptance_profile, policy
    )
    branch_map = {
        RecoveryAction.RETRY_SAME_CODER: "coder_ladder.retry_same",
        RecoveryAction.SWITCH_CODER: "coder_ladder.switch_coder",
        RecoveryAction.RETURN_TO_ARCHITECT: "architect_repack",
        RecoveryAction.ESCALATE_ARCHITECT: "architect_escalate",
        RecoveryAction.RETRY_VERIFIER: "verifier_retry",
        RecoveryAction.RETRY_REVIEWER: "reviewer_retry",
        RecoveryAction.RETRY_MERGE: "merge_retry",
        RecoveryAction.BLOCK_FEATURE: "true_blocker",
        RecoveryAction.NO_ACTION: "no_action",
    }
    decision.audit_payload.setdefault("policy", "default")
    decision.audit_payload.setdefault("coder_attempt_count", signal.coder_attempt_count)
    decision.audit_payload.setdefault("matched_branch", branch_map.get(decision.action, "unknown"))

    _log.info("decide_recovery",
        packet_id=signal.packet_id,
        action=decision.action.value,
        failure_class=decision.failure_class.value,
        reason=decision.reason or "",
        next_executor_hint=decision.next_executor_hint or "",
        coder_attempt_count=signal.coder_attempt_count,
        max_attempts_reached=decision.max_attempts_reached,
    )
    return decision


def _next_executor_hint(signal: FailureSignal) -> str:
    prev = set(signal.previous_executor_ids)
    from grace_control.core.executor_selector import get_escalation
    for executor in get_escalation("coder"):
        eid = executor.get("executor_id", "")
        if eid and eid not in prev:
            return eid
    return "coder-mini-swe-deepseek"


# ── Phase 4: Session Resume Stubs ──────────────────────────────────────


class RecoverySessionSnapshot(BaseModel):
    """Snapshot of a failed session for future resume."""
    session_id: str = ""
    feature_id: str
    wave_id: str = ""
    packet_id: str
    run_id: str = ""
    attempt_number: int = 1
    role: str = "coder"
    executor_id: str = ""
    model: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str = ""
    summary_human: str = ""
    failure_reason: str = ""
    changed_files: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    acceptance_report_path: str = ""
    evidence_report_path: str = ""
    reviewer_report_path: str = ""
    recovery_decision_id: str = ""
    previous_attempts_summary: list[str] = Field(default_factory=list)
    full_context_json: dict[str, Any] = Field(default_factory=dict)


class TaskResumeContext(BaseModel):
    """Resume context for a specific task/packet retry."""
    task_id: str = ""
    packet_id: str
    feature_id: str
    role: str = "coder"
    previous_attempts: list[RecoverySessionSnapshot] = Field(default_factory=list)
    recovery_decision: dict[str, Any] = Field(default_factory=dict)
    executor_hint: str = ""
    failure_summary: str = ""
    architect_instruction: str = ""
    session_resume_available: bool = False
    build_resume_context: bool = False


class SessionResumeSummary(BaseModel):
    """Human-readable summary of session resume context for admin UI."""
    packet_id: str
    attempt_number: int
    previous_executors: list[str] = Field(default_factory=list)
    failure_reason: str = ""
    action: str = ""
    resume_available: bool = False
    context_size_kb: int = 0


def build_session_snapshot(packet_run: Any, packet: Any = None) -> RecoverySessionSnapshot:
    rj = packet_run.result_json or {}
    acc = rj.get("acceptance_report", {})
    rec = rj.get("recovery", {})

    return RecoverySessionSnapshot(
        feature_id=getattr(packet, "feature_id", "") if packet else "",
        wave_id=getattr(packet, "wave_id", "") if packet else "",
        packet_id=packet_run.packet_id,
        run_id=packet_run.id,
        attempt_number=packet_run.run_number,
        status=packet_run.status,
        executor_id=rj.get("executor_id", ""),
        model=rj.get("model", ""),
        started_at=getattr(packet_run, "started_at", None),
        finished_at=getattr(packet_run, "finished_at", None),
        failure_reason=rj.get("reason", ""),
        acceptance_report_path=rj.get("acceptance_report_path", ""),
        evidence_report_path=rj.get("evidence_verifier_report_path", ""),
        reviewer_report_path=rj.get("reviewer_report_path", ""),
        recovery_decision_id=rec.get("decision_id", ""),
        summary_human=f"Attempt {packet_run.run_number}: {packet_run.status} — {rj.get('reason', '')[:200]}",
    )


def build_task_resume_context(
    packet: Any,
    decision: RecoveryDecision | None = None,
    history: list[RecoverySessionSnapshot] | None = None,
) -> TaskResumeContext:
    return TaskResumeContext(
        packet_id=packet.id if hasattr(packet, "id") else "",
        feature_id=getattr(packet, "feature_id", ""),
        role="coder",
        previous_attempts=history or [],
        recovery_decision=decision.model_dump() if decision else {},
        executor_hint=(decision.next_executor_hint or "") if decision else "",
        failure_summary=(decision.reason or "") if decision else "",
        architect_instruction=(decision.architect_instruction or "") if decision else "",
        session_resume_available=False,
        build_resume_context=False,
    )


def render_resume_summary(context: TaskResumeContext) -> str:
    parts = [f"Packet {context.packet_id}: {len(context.previous_attempts)} previous attempts"]
    if context.failure_summary:
        parts.append(f"Failure: {context.failure_summary[:200]}")
    if context.executor_hint:
        parts.append(f"Next executor: {context.executor_hint}")
    if context.architect_instruction:
        parts.append(f"Architect: {context.architect_instruction[:200]}")
    return "\n".join(parts)
