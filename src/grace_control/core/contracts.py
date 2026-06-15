# ############################################################################
# AI_HEADER: contracts
# ROLE: Canonical dataclasses and enums for acceptance pipeline contracts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Define FinalVerdict, StageResult, AcceptanceReport, CommandResult,
#          ScopeViolation, ExecutionPacketContract, EvidenceRequirement,
#          and validation functions.
# inputs: None (pure dataclasses).
# returns: Dataclass instances.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Validation functions return error lists, never raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: AcceptanceProfile
#   - enum: StageName (T0, T1, T2, T2_BROWSER, T3_VISUAL)
#   - enum: StageStatus
#   - enum: PacketVerdict
#   - enum: FinalVerdict
#   - dataclass: CommandResult
#   - dataclass: ScopeViolation
#   - dataclass: StageResult
#   - dataclass: EvidenceRequirement
#   - dataclass: ExecutionPacketContract
#   - dataclass: AcceptanceReport
#   - function: validate_packet_contract
#   - function: validate_stage_result
#   - function: validate_acceptance_report
#   - function: build_packet_contract
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
    T2_BROWSER_E2E = "T2_BROWSER_E2E"              # TZ_FRONTEND_ACCEPTANCE P0
    T2_BROWSER_A11Y = "T2_BROWSER_A11Y"            # TZ_FRONTEND_ACCEPTANCE P2
    T3_VISUAL_REGRESSION = "T3_VISUAL_REGRESSION"  # TZ_FRONTEND_ACCEPTANCE P0


class StageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PacketVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    ESCALATE_TO_ARCHITECT = "escalate_to_architect"


class FinalVerdict(str, Enum):
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CommandResult:
    command: str
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
    command_origins: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationSpec:
    t0: list[list[str]] = field(default_factory=list)
    t1: list[list[str]] = field(default_factory=list)
    t2: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRequirement:
    id: str
    kind: str  # command | file | diff | log | screenshot | dom_snapshot | console_log | network_log | visual_diff | a11y_report | artifact_manifest
    required: bool = True
    pattern: str | None = None


@dataclass(frozen=True)
class ExecutionPacketContract:
    packet_id: str
    title: str
    allowed_write_scope: list[str]
    frozen_scope: list[str]
    acceptance_profile: AcceptanceProfile
    verification: dict[str, list[str]] = field(default_factory=dict)
    expected_evidence: list[EvidenceRequirement] = field(default_factory=list)
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
    final_verdict: FinalVerdict
    profile: AcceptanceProfile
    stages: list[StageResult]
    scope_violations: list[str] = field(default_factory=list)
    evidence_issues: list[str] = field(default_factory=list)
    legacy_domain_status: str = ""
    legacy_ok: bool = False
    summary: str = ""
    evidence_paths: list[str] = field(default_factory=list)

    @property
    def is_accepted(self) -> bool:
        return self.final_verdict == FinalVerdict.ACCEPTED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# TZ_FRONTEND_ACCEPTANCE P1 — multimodal evidence + visual regression dataclasses

@dataclass(frozen=True)
class ScreenshotRef:
    """Reference to a screenshot artifact for multimodal verifier prompts."""
    path: str
    viewport: str = ""
    url: str = ""
    description: str = ""


@dataclass(frozen=True)
class DomSnapshotRef:
    """Reference to a DOM/AX-tree snapshot artifact."""
    path: str
    selector: str = ""
    aria_role: str = ""


@dataclass
class MultimodalEvidencePack:
    """Bundle of browser/visual evidence for the verifier LLM.

    When executor is multimodal: paths become image_url/image tags.
    Otherwise: fall back to text descriptions ("2 screenshots saved at ...").
    """
    screenshots: list[ScreenshotRef] = field(default_factory=list)
    dom_snapshots: list[DomSnapshotRef] = field(default_factory=list)
    console_log_path: str = ""
    network_log_path: str = ""
    visual_diff_path: str = ""
    visual_diff_pct: float = 0.0
    multimodal_executor: bool = False


def _has_abs_or_parent(path: str) -> bool:
    """W02: Check for absolute or parent-traversal paths in scope."""
    return path.startswith("/") or ".." in Path(path).parts


def _strip_guardrails(cmds: list) -> None:
    """Remove commands that run guardrails.sh or check_frontmatter in-place."""
    i = 0
    while i < len(cmds):
        cmd = cmds[i]
        if isinstance(cmd, str):
            joined = cmd
        else:
            joined = " ".join(cmd)
        if "guardrails.sh" in joined or "check_frontmatter" in joined:
            cmds.pop(i)
        else:
            i += 1


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
        if _has_python_import_path(p):
            errors.append(f"allowed_write_scope is Python import path: {p} — use filesystem path")
    for p in packet.frozen_scope:
        if _has_abs_or_parent(p):
            errors.append(f"frozen_scope path invalid: {p}")
    # W02: scope/frozen overlap is an error
    overlap = set(packet.allowed_write_scope) & set(packet.frozen_scope)
    if overlap:
        errors.append(f"scope/frozen_scope overlap: {sorted(overlap)} — cannot be both writable and frozen")
    # NORMAL/STRICT no longer requires verification.t1 — auto defaults
    # from gate_resolver fill in when architect does not provide them.
    # validate_packet_contract is called before resolution, so skip
    # the t1-required check here. The pipeline will fail at T1 stage
    # if no defaults and no explicit commands exist.
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
        if not report.summary:
            errors.append("non-accepted report must have summary")
    for stage in report.stages:
        errors.extend(validate_stage_result(stage))
    return errors


class ScopeContractError(ValueError):
    """W02: Raised when scope contract validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _has_python_import_path(path: str) -> bool:
    """W02: Check for Python import-style paths (dot-separated, no slashes)."""
    return "." in path and "/" not in path and not path.startswith(".")


def validate_scope_paths(scope_list: list[str], frozen_list: list[str] | None = None) -> list[str]:
    """W02: Validate scope and frozen paths. Returns list of error strings.

    Checks:
    - Absolute paths -> error (not silently stripped)
    - Parent paths (..) -> error
    - Python import paths -> error
    - Scope/frozen overlap -> error (not silently stripped)
    """
    errors: list[str] = []

    for p in scope_list:
        if p.startswith("/"):
            errors.append(f"absolute path in scope: {p} — must be repo-relative")
        if ".." in Path(p).parts:
            errors.append(f"parent path in scope: {p} — must be within repo")
        if _has_python_import_path(p):
            errors.append(f"Python import path in scope: {p} — use filesystem path instead")

    if frozen_list:
        for p in frozen_list:
            if p.startswith("/"):
                errors.append(f"absolute path in frozen_scope: {p} — must be repo-relative")
            if ".." in Path(p).parts:
                errors.append(f"parent path in frozen_scope: {p} — must be within repo")

        # W02: Overlap is an error, not silently stripped
        overlap = set(scope_list) & set(frozen_list)
        if overlap:
            errors.append(f"scope/frozen_scope overlap: {sorted(overlap)} — a file cannot be both writable and frozen")

    return errors


def build_packet_contract(packet_data: dict) -> ExecutionPacketContract:
    spec = packet_data.get("spec_json") or {}
    scope_list = spec.get("scope", [])
    if isinstance(scope_list, str):
        scope_list = [scope_list]

    # W02: No default fallback to src/grace_control/ — if scope is empty,
    # it stays empty. The plan compiler will catch it as E_CODER_EMPTY_SCOPE.
    # Callers that need non-empty scope must provide it explicitly.

    frozen = spec.get("frozen_scope", [])
    if isinstance(frozen, str):
        frozen = [frozen]

    # W02: Validate scope paths — reject instead of silently stripping
    scope_errors = validate_scope_paths(scope_list, frozen)
    if scope_errors:
        raise ScopeContractError(scope_errors)

    # W02: No longer silently strip absolute paths from scope or frozen.
    # Absolute paths are rejected above via ScopeContractError.
    # No longer silently remove frozen_scope overlap — rejected above.

    verification_raw = spec.get("verification", {})
    if isinstance(verification_raw, list):
        t0: list[list[str]] = []
        t1: list[list[str]] = []
        t2: list[list[str]] = []
        for cmd in verification_raw:
            if isinstance(cmd, str):
                t1.append(cmd.split())
            else:
                t1.append(list(cmd))
    elif isinstance(verification_raw, dict):
        t0 = verification_raw.get("t0", [])
        if isinstance(t0, dict) and "commands" in t0:
            t0 = t0["commands"]
        t1 = verification_raw.get("t1", []) or spec.get("verification_commands", [])
        if isinstance(t1, dict) and "commands" in t1:
            t1 = t1["commands"]
        t2 = verification_raw.get("t2", [])
        if isinstance(t2, dict) and "commands" in t2:
            t2 = t2["commands"]
        # Strip guardrails.sh and check_frontmatter from T0/T1/T2 —
        # these are full-suite gates that pick up pre-existing failures
        # unrelated to the packet. Architect keeps generating them despite
        # prompt rules, so we enforce it at the contract level.
        _strip_guardrails(t0)
        _strip_guardrails(t1)
        _strip_guardrails(t2)
    else:
        t0 = []
        t1 = spec.get("verification_commands", [])
        t2 = []

    expected_raw = spec.get("expected_evidence", [])
    expected_evidence = []
    for item in expected_raw:
        if isinstance(item, dict):
            expected_evidence.append(EvidenceRequirement(
                id=item.get("id", ""),
                kind=item.get("kind", "command"),
                required=item.get("required", True),
                pattern=item.get("pattern"),
            ))
        elif isinstance(item, str):
            expected_evidence.append(EvidenceRequirement(id=item, kind="command"))

    return ExecutionPacketContract(
        packet_id=packet_data.get("id", packet_data.get("packet_id", "")),
        title=packet_data.get("title", ""),
        allowed_write_scope=scope_list,
        frozen_scope=frozen,
        acceptance_profile=AcceptanceProfile(
            packet_data.get("acceptance_profile", "NORMAL")
        ),
        verification={
            "t0": t0, "t1": t1, "t2": t2,
            "t2_browser": verification_raw.get("t2_browser", []) if isinstance(verification_raw, dict) else [],
            "t2_a11y": verification_raw.get("t2_a11y", []) if isinstance(verification_raw, dict) else [],
            "t3_visual": verification_raw.get("t3_visual", []) if isinstance(verification_raw, dict) else [],
        },
        expected_evidence=expected_evidence,
        metadata={
            "origin": spec.get("origin", ""),
            "session_id": spec.get("session_id", ""),
            "frontend": spec.get("frontend"),  # TZ_FRONTEND_ACCEPTANCE P0
            "target_repo_root": spec.get("target_repo_root", ""),
            "workspace_mode": spec.get("workspace_mode", ""),
        },
    )
