# ############################################################################
# AI_HEADER: contracts
# ROLE: Canonical dataclasses and enums for acceptance pipeline contracts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define PacketVerdict, StageResult, AcceptanceReport, CommandResult,
#          ScopeViolation, ExecutionPacketContract, and validation functions.
# inputs: None (pure dataclasses).
# returns: Dataclass instances.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Validation functions return error lists, never raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: AcceptanceProfile
#   - enum: StageName
#   - enum: StageStatus
#   - enum: PacketVerdict
#   - dataclass: CommandResult
#   - dataclass: ScopeViolation
#   - dataclass: StageResult
#   - dataclass: ExecutionPacketContract
#   - dataclass: AcceptanceReport
#   - function: validate_packet_contract
#   - function: validate_stage_result
#   - function: validate_acceptance_report
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class AcceptanceProfile(str, Enum):
    FAST = "FAST"
    NORMAL = "NORMAL"
    STRICT = "STRICT"


class StageName(str, Enum):
    T0_SCOPE_AND_LINT = "T0_SCOPE_AND_LINT"
    T1_TARGETED_TESTS = "T1_TARGETED_TESTS"
    T2_FULL_TESTS = "T2_FULL_TESTS"


class StageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PacketVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    ESCALATE_TO_ARCHITECT = "escalate_to_architect"


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    timed_out: bool = False
    duration_ms: int | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class ScopeViolation:
    path: str
    reason: str
    violation_type: Literal["out_of_scope", "frozen_scope", "missing_allowed_scope", "invalid_path"]


@dataclass(frozen=True)
class StageResult:
    name: StageName
    status: StageStatus
    summary: str
    commands: list[CommandResult] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


@dataclass(frozen=True)
class VerificationSpec:
    t0: list[list[str]] = field(default_factory=list)
    t1: list[list[str]] = field(default_factory=list)
    t2: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionPacketContract:
    packet_id: str
    title: str
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    acceptance_profile: AcceptanceProfile
    verification: VerificationSpec = field(default_factory=VerificationSpec)
    expected_evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierReport:
    packet_id: str
    verdict: "PacketVerdict"
    requirement_results: list[dict[str, Any]] = field(default_factory=list)
    test_verdict: Literal["passed", "failed", "not_run"] = "not_run"
    commands_run: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewerVerdict:
    packet_id: str
    packet_verdict: "PacketVerdict"
    follow_up_action: Literal["none", "localized_rework", "architect_decision"] = "none"
    route_classification: Literal["self_resolvable_rework", "requires_user_decision", "requires_planner", "accepted"] = "accepted"
    rework_mode: Literal["none", "light_resume", "bounded_fresh", "decision_required"] = "none"
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AcceptanceReport:
    packet_id: str
    final_verdict: PacketVerdict
    stages: list[StageResult]
    scope_violations: list[ScopeViolation] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    verifier_report: VerifierReport | None = None
    reviewer_verdict: ReviewerVerdict | None = None

    @property
    def is_accepted(self) -> bool:
        return self.final_verdict == PacketVerdict.ACCEPTED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has_abs_or_parent(path: str) -> bool:
    return path.startswith("/") or ".." in Path(path).parts


def validate_packet_contract(packet: ExecutionPacketContract) -> list[str]:
    errors: list[str] = []
    if not packet.packet_id or not packet.packet_id.strip():
        errors.append("packet_id is empty")
    if not packet.title or not packet.title.strip():
        errors.append("title is empty")
    if not packet.allowed_write_scope:
        errors.append("allowed_write_scope is empty")
    for p in packet.allowed_write_scope:
        if _has_abs_or_parent(p):
            errors.append(f"allowed_write_scope path invalid: {p}")
    for p in packet.frozen_scope:
        if _has_abs_or_parent(p):
            errors.append(f"frozen_scope path invalid: {p}")
    if packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT):
        if not packet.verification.t1:
            errors.append(f"{packet.acceptance_profile.value} requires verification.t1")
    return errors


def validate_stage_result(stage: StageResult) -> list[str]:
    errors: list[str] = []
    if stage.status == StageStatus.FAILED:
        if not stage.blocking_issues and not any(c.exit_code != 0 for c in stage.commands):
            errors.append("FAILED stage must have blocking_issues or failed commands")
    if stage.status == StageStatus.SKIPPED:
        if not stage.skipped_reason:
            errors.append("SKIPPED stage must have skipped_reason")
    if stage.status == StageStatus.PASSED:
        if stage.blocking_issues:
            errors.append("PASSED stage must not have blocking_issues")
    return errors


def validate_acceptance_report(report: AcceptanceReport) -> list[str]:
    errors: list[str] = []
    if report.is_accepted:
        if report.scope_violations:
            errors.append("accepted report must not have scope violations")
        if not any(s.status == StageStatus.PASSED for s in report.stages if s.name == StageName.T0_SCOPE_AND_LINT):
            errors.append("accepted report requires T0 passed")
    else:
        if not report.reasons:
            errors.append("non-accepted report must have reasons")
    for stage in report.stages:
        errors.extend(validate_stage_result(stage))
    return errors
