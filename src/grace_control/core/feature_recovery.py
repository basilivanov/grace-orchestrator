# ############################################################################
# AI_HEADER: feature_recovery
# ROLE: Deterministic recovery/escalation policy for failed packets.
# Phase 1: library + tests only, no live orchestration integration.
# ############################################################################

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


def classify_failure(signal: FailureSignal) -> FailureClass:
    reason = (signal.reason or "").lower()
    state = signal.packet_state.lower()
    domain = (signal.domain_status or "").lower()
    merge_err = (signal.merge_error or "").lower()
    ev_verdict = signal.evidence_verifier_verdict
    rv_verdict = signal.reviewer_verdict

    # ── True blockers ──────────────────────────────────────────────
    if merge_err and "dirty_target_repo" in merge_err:
        return FailureClass.TRUE_BLOCKER
    if merge_err and "conflict" in merge_err:
        return FailureClass.TRUE_BLOCKER

    if any(kw in reason for kw in ["missing cli", "missing api key", "auth failed",
                                    "quota exceeded", "permission denied", "repository inaccessible"]):
        return FailureClass.TRUE_BLOCKER

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

    # ── Evidence Verifier ───────────────────────────────────────────
    if ev_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if ev_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if ev_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE

    # ── Reviewer ────────────────────────────────────────────────────
    if rv_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if rv_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if rv_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE

    # ── Scope guard violations ──────────────────────────────────────
    if state in ("rejected", "failed") and "scope" in reason:
        if "impossible" in reason or "cannot" in reason:
            return FailureClass.ARCHITECT_REPACK_NEEDED
        return FailureClass.RETRYABLE_CODER

    # ── Deterministic acceptance ────────────────────────────────────
    if state in ("rejected", "failed") and domain in ("rejected", "runner_error"):
        if "no changes" in reason or "test" in reason or "command" in reason or "evidence" in reason:
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


def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy) -> RecoveryDecision:
    fc = classify_failure(signal)

    # ── TRUE_BLOCKER ────────────────────────────────────────────────
    if fc == FailureClass.TRUE_BLOCKER:
        return RecoveryDecision(
            action=RecoveryAction.BLOCK_FEATURE,
            failure_class=fc,
            reason=signal.reason or "true blocker",
            max_attempts_reached=True,
        )

    # ── ARCHITECT_ESCALATION_NEEDED ─────────────────────────────────
    if fc == FailureClass.ARCHITECT_ESCALATION_NEEDED:
        return RecoveryDecision(
            action=RecoveryAction.ESCALATE_ARCHITECT,
            failure_class=fc,
            reason=signal.reason or "repeated unknown failure",
        )

    # ── ARCHITECT_REPACK_NEEDED ─────────────────────────────────────
    if fc == FailureClass.ARCHITECT_REPACK_NEEDED:
        if signal.architect_repair_count >= policy.max_architect_repairs:
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"architect repair repeated {signal.architect_repair_count}x, escalating",
                max_attempts_reached=True,
            )
        return RecoveryDecision(
            action=RecoveryAction.RETURN_TO_ARCHITECT,
            failure_class=fc,
            reason=signal.reason or "architect repack needed",
            architect_instruction=f"Packet {signal.packet_id} failed: {signal.reason}",
        )

    # ── Coder ladders ──────────────────────────────────────────────
    if fc == FailureClass.RETRYABLE_CODER:
        if signal.coder_attempt_count >= policy.max_total_coder_attempts:
            return RecoveryDecision(
                action=RecoveryAction.RETURN_TO_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_REPACK_NEEDED,
                reason=f"coder failed {signal.coder_attempt_count}x, returning to architect",
                max_attempts_reached=True,
            )
        if signal.coder_attempt_count >= policy.max_same_coder_attempts:
            return RecoveryDecision(
                action=RecoveryAction.SWITCH_CODER,
                failure_class=fc,
                reason=f"coder failed {signal.coder_attempt_count}x, switching model",
                next_executor_hint=_next_executor_hint(signal),
            )
        return RecoveryDecision(
            action=RecoveryAction.RETRY_SAME_CODER,
            failure_class=fc,
            reason=f"coder failed (attempt {signal.coder_attempt_count + 1}), retrying same",
            next_executor_hint=signal.current_executor_id,
        )

    # ── Verifier ladders ────────────────────────────────────────────
    if fc == FailureClass.RETRYABLE_VERIFIER:
        if signal.verifier_reject_count >= policy.max_verifier_retries:
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"verifier failed {signal.verifier_reject_count}x, escalating",
                max_attempts_reached=True,
            )
        return RecoveryDecision(
            action=RecoveryAction.RETRY_VERIFIER,
            failure_class=fc,
            reason=f"verifier retry #{signal.verifier_reject_count + 1}",
        )

    # ── Reviewer ladders ────────────────────────────────────────────
    if fc == FailureClass.RETRYABLE_REVIEWER:
        if signal.reviewer_reject_count >= policy.max_reviewer_retries:
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_ARCHITECT,
                failure_class=FailureClass.ARCHITECT_ESCALATION_NEEDED,
                reason=f"reviewer failed {signal.reviewer_reject_count}x, escalating",
                max_attempts_reached=True,
            )
        return RecoveryDecision(
            action=RecoveryAction.RETRY_REVIEWER,
            failure_class=fc,
            reason=f"reviewer retry #{signal.reviewer_reject_count + 1}",
        )

    # ── Merge ladders ───────────────────────────────────────────────
    if fc == FailureClass.MERGE_RETRYABLE:
        if signal.merge_attempt_count >= policy.max_merge_retries:
            return RecoveryDecision(
                action=RecoveryAction.BLOCK_FEATURE,
                failure_class=FailureClass.TRUE_BLOCKER,
                reason=f"merge failed {signal.merge_attempt_count}x, blocking",
                max_attempts_reached=True,
            )
        return RecoveryDecision(
            action=RecoveryAction.RETRY_MERGE,
            failure_class=fc,
            reason=f"merge retry #{signal.merge_attempt_count + 1}",
        )

    # ── UNKNOWN_RETRYABLE ──────────────────────────────────────────
    return RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=fc,
        reason=f"unknown failure, retrying (attempt {signal.attempt_count + 1})",
    )


def _next_executor_hint(signal: FailureSignal) -> str:
    prev = set(signal.previous_executor_ids)
    ladder = ["coder-agy-sonnet", "coder-agy-flash", "coder-flash"]
    for choice in ladder:
        if choice not in prev:
            return choice
    return "coder-agy-sonnet"
