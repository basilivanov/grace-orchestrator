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
#   - function: validate_evidence_for_profile  (W05)
#   - function: route_missing_evidence  (W05)
#   - function: check_artifact_patterns  (W05)
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
    # W06: Process supervisor / command runner diagnostics
    killed_pgid: int | None = None
    wait_after_kill_timed_out: bool = False
    command_preview: str = ""
    shell_mode: bool = False

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
    stage: str = ""  # t0 | t1 | t2 | t3 | post_merge — which verification stage produces this
    owner: str = "coder"  # coder | architect | verifier — who is responsible for producing this evidence
    producer: str = ""  # agent that produces this (e.g. coder_run, verifier, browser_runner)
    profile: str = ""  # acceptance profile this evidence applies to (FAST, NORMAL, STRICT, or blank = all)
    required: bool = True
    coder_blocking: bool = True  # if missing, does this block the coder rework loop?
    artifact_patterns: list[str] = field(default_factory=list)  # glob patterns for artifact files
    description: str = ""  # human-readable description of what this evidence proves
    validation_hint: str = ""  # hint for the verifier on how to validate this evidence
    # W05: Legacy field mapping — 'pattern' maps to 'artifact_patterns'
    # Kept for transition compatibility; canonicalize before use.
    pattern: str | None = None  # DEPRECATED — use artifact_patterns instead


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
    _evidence_warnings: list[str] = []  # W05: collect canonicalization warnings

    for item in expected_raw:
        if isinstance(item, dict):
            # W05: Map legacy 'pattern' to 'artifact_patterns' with warning
            artifact_patterns = item.get("artifact_patterns", [])
            if not artifact_patterns and isinstance(artifact_patterns, list):
                # artifact_patterns was provided as empty list — that's fine
                pass
            if not artifact_patterns:
                legacy_pattern = item.get("pattern")
                if legacy_pattern:
                    if isinstance(legacy_pattern, str):
                        artifact_patterns = [legacy_pattern]
                    elif isinstance(legacy_pattern, list):
                        artifact_patterns = legacy_pattern
                    _evidence_warnings.append(
                        f"Evidence '{item.get('id', '?')}': legacy field 'pattern' "
                        f"canonicalized to 'artifact_patterns' — use 'artifact_patterns' in future plans"
                    )

            expected_evidence.append(EvidenceRequirement(
                id=item.get("id", ""),
                kind=item.get("kind", "command"),
                stage=item.get("stage", ""),
                owner=item.get("owner", "coder"),
                producer=item.get("producer", ""),
                profile=item.get("profile", ""),
                required=item.get("required", True),
                coder_blocking=item.get("coder_blocking", True),
                artifact_patterns=artifact_patterns if isinstance(artifact_patterns, list) else [artifact_patterns],
                description=item.get("description", ""),
                validation_hint=item.get("validation_hint", ""),
                pattern=item.get("pattern"),  # W05: preserve legacy for transition
            ))
        elif isinstance(item, str):
            # W05: String evidence is allowed in transition mode but gets a warning.
            # STRICT profiles should reject it; see validate_evidence_for_profile().
            _evidence_warnings.append(
                f"Evidence '{item}': string evidence is a legacy shape — "
                f"use a dict with 'id', 'kind', 'owner', 'artifact_patterns' etc."
            )
            expected_evidence.append(EvidenceRequirement(id=item, kind="command"))

    # W05 rework: Validate evidence shape against profile in the build path.
    # STRICT profiles reject string/legacy evidence at build time.
    acceptance_profile = AcceptanceProfile(
        packet_data.get("acceptance_profile", "NORMAL")
    )
    evidence_errors = validate_evidence_for_profile(expected_evidence, acceptance_profile)
    if evidence_errors:
        raise ScopeContractError(evidence_errors)

    return ExecutionPacketContract(
        packet_id=packet_data.get("id", packet_data.get("packet_id", "")),
        title=packet_data.get("title", ""),
        allowed_write_scope=scope_list,
        frozen_scope=frozen,
        acceptance_profile=acceptance_profile,
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
            # W05: evidence canonicalization warnings persisted in contract metadata
            "_evidence_schema_warnings": _evidence_warnings,
        },
    )


# ── W05: Evidence contract validation and routing ─────────────────────────

def validate_evidence_for_profile(
    evidence: list[EvidenceRequirement],
    profile: AcceptanceProfile,
) -> list[str]:
    """W05: Validate evidence shape against acceptance profile.

    - FAST/NORMAL: string evidence gets a warning but is allowed (transition mode).
    - STRICT: string evidence (id-only, missing kind/owner) is rejected.
    - Legacy 'pattern' field is always warned regardless of profile.

    Returns list of error strings (empty = valid).
    """
    errors: list[str] = []
    for e in evidence:
        # STRICT: reject evidence that lacks structured fields
        if profile == AcceptanceProfile.STRICT:
            # Evidence created from a bare string has kind="command",
            # no stage, no description, no producer, no validation_hint.
            # Structured evidence will have at least description or stage set.
            if (e.kind == "command" and not e.stage and not e.description
                    and not e.producer and not e.validation_hint
                    and not e.artifact_patterns):
                errors.append(
                    f"Evidence '{e.id}': rejected in STRICT mode — "
                    f"must use structured dict with 'id', 'kind', 'owner', "
                    f"'artifact_patterns', 'description'"
                )
            if e.pattern and not e.artifact_patterns:
                errors.append(
                    f"Evidence '{e.id}': legacy 'pattern' field rejected in STRICT mode — "
                    f"use 'artifact_patterns' instead"
                )
    return errors


def route_missing_evidence(
    missing_evidence_ids: list[str],
    evidence_requirements: list[EvidenceRequirement],
) -> str:
    """W05: Route missing evidence by owner/profile.

    Returns the next owner for the rework loop:
    - 'coder' if any missing evidence is coder-owned and coder_blocking
    - 'architect' if any missing evidence is architect-owned
    - 'verifier' if missing evidence is verifier-owned only
    - 'coder' as default fallback

    This ensures architect-owned evidence issues don't become coder blame.
    """
    req_by_id = {e.id: e for e in evidence_requirements}

    has_coder_blocking = False
    has_architect_owned = False
    has_verifier_owned = False

    for ev_id in missing_evidence_ids:
        req = req_by_id.get(ev_id)
        if req is None:
            # Unknown evidence — default to coder rework
            has_coder_blocking = True
            continue
        if req.owner == "architect":
            has_architect_owned = True
        elif req.owner == "verifier":
            has_verifier_owned = True
        else:
            # coder-owned (default)
            if req.coder_blocking:
                has_coder_blocking = True
            # Non-blocking coder evidence doesn't force coder rework

    # Architect-owned evidence issue → return to architect
    if has_architect_owned:
        return "architect"

    # Coder-owned blocking evidence → rework to coder
    if has_coder_blocking:
        return "coder"

    # Verifier-owned issue → verifier/reviewer decision
    if has_verifier_owned:
        return "verifier"

    # Default fallback
    return "coder"


def check_artifact_patterns(
    evidence_requirements: list[EvidenceRequirement],
    available_artifacts: list[str],
) -> list[str]:
    """W05: Check artifact patterns by evidence kind.

    For each evidence requirement that has artifact_patterns, verify that
    at least one matching artifact exists for each pattern.

    Returns list of warnings for unmatched patterns.
    """
    import fnmatch

    warnings: list[str] = []
    for req in evidence_requirements:
        if not req.artifact_patterns:
            continue

        for pattern in req.artifact_patterns:
            matched = any(fnmatch.fnmatch(artifact, pattern) for artifact in available_artifacts)
            if not matched:
                kind_info = f" (kind={req.kind})" if req.kind else ""
                warnings.append(
                    f"Evidence '{req.id}'{kind_info}: artifact pattern '{pattern}' "
                    f"not matched by any available artifact"
                )
    return warnings
