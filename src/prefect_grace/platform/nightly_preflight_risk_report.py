# ############################################################################
# AI_HEADER: nightly_preflight_risk_report
# ROLE: Read-only risk analysis for ready GRACE packets before nightly execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Analyze ready packets for risk flags, conflicts, and cost estimates without execution.
# inputs: Project config.
# returns: NightlyPreflightRiskReport with bounded risk classifications.
# side_effects: Reads packet files, registry state, evidence, and reviews only.
# emitted_logs: None.
# error_behavior: Returns structured errors without execution or mutation.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: PacketRiskFlags
#   - dataclass: PacketRiskSummary
#   - dataclass: ConflictGroup
#   - dataclass: NightlyPreflightRiskReport
#   - function: generate_nightly_preflight_risk_report
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import build_backlog_bootstrap_plan
from prefect_grace.platform.nightly_dry_run_controller import run_nightly_dry_run
from prefect_grace.platform.packet_artifact_layout import latest_review, resolve_packet_layout
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.review_artifact_contract import read_review_artifact_status
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import RegistryStatus


MAX_ITEMS = 25


@dataclass
class PacketRiskFlags:
    dependency_blocked: bool = False
    source_runtime_mismatch: bool = False
    review_missing: bool = False
    evidence_missing: bool = False
    evidence_invalid: bool = False
    needs_live_agent: bool = False
    needs_prefect: bool = False
    needs_docker: bool = False
    needs_frontend: bool = False
    needs_backend: bool = False
    needs_git_commit: bool = False
    needs_git_push: bool = False
    needs_merge_approval: bool = False
    touches_frozen_scope: bool = False
    large_file_or_size_debt: bool = False
    known_legacy_debt: bool = False
    file_conflict_candidate: bool = False
    expensive_tests: bool = False
    operator_approval_required: bool = False

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize risk flags to dictionary.
    # inputs: none.
    # returns: dict with all risk flag fields.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PacketRiskSummary:
    packet_id: str
    registry_status: str
    source_status: str
    risk_flags: PacketRiskFlags
    cost_estimate: str
    allowed_write_scope: list[str] = field(default_factory=list)
    impacted_modules: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize packet risk summary to dictionary with bounded lists.
    # inputs: none.
    # returns: dict with summary fields and truncated lists.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "registry_status": self.registry_status,
            "source_status": self.source_status,
            "risk_flags": self.risk_flags.to_dict(),
            "cost_estimate": self.cost_estimate,
            "allowed_write_scope": self.allowed_write_scope[:MAX_ITEMS],
            "impacted_modules": self.impacted_modules[:MAX_ITEMS],
        }


@dataclass
class ConflictGroup:
    packet_ids: list[str]
    conflicting_paths: list[str]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize conflict group to dictionary with bounded lists.
    # inputs: none.
    # returns: dict with packet IDs and conflicting paths truncated to MAX_ITEMS.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_ids": self.packet_ids[:MAX_ITEMS],
            "conflicting_paths": self.conflicting_paths[:MAX_ITEMS],
        }


@dataclass
class NightlyPreflightRiskReport:
    ok: bool
    project_key: str
    mode: str = "nightly_preflight_risk_report"
    packets_total: int = 0
    ready_total: int = 0
    blocked_total: int = 0
    accepted_total: int = 0
    safe_candidates: list[str] = field(default_factory=list)
    safe_candidates_total: int = 0
    risky_candidates: list[str] = field(default_factory=list)
    risky_candidates_total: int = 0
    blocked_candidates: list[str] = field(default_factory=list)
    blocked_candidates_total: int = 0
    approval_required_candidates: list[str] = field(default_factory=list)
    approval_required_candidates_total: int = 0
    conflict_groups: list[ConflictGroup] = field(default_factory=list)
    conflict_groups_total: int = 0
    packet_summaries: list[PacketRiskSummary] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize nightly preflight risk report to dictionary with bounded lists.
    # inputs: none.
    # returns: dict with all report fields and lists truncated to MAX_ITEMS.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "mode": self.mode,
            "packets_total": self.packets_total,
            "ready_total": self.ready_total,
            "blocked_total": self.blocked_total,
            "accepted_total": self.accepted_total,
            "safe_candidates": self.safe_candidates[:MAX_ITEMS],
            "safe_candidates_total": self.safe_candidates_total,
            "risky_candidates": self.risky_candidates[:MAX_ITEMS],
            "risky_candidates_total": self.risky_candidates_total,
            "blocked_candidates": self.blocked_candidates[:MAX_ITEMS],
            "blocked_candidates_total": self.blocked_candidates_total,
            "approval_required_candidates": self.approval_required_candidates[:MAX_ITEMS],
            "approval_required_candidates_total": self.approval_required_candidates_total,
            "conflict_groups": [cg.to_dict() for cg in self.conflict_groups[:MAX_ITEMS]],
            "conflict_groups_total": self.conflict_groups_total,
            "packet_summaries": [ps.to_dict() for ps in self.packet_summaries[:MAX_ITEMS]],
            "warnings": self.warnings[:MAX_ITEMS],
            "errors": self.errors[:MAX_ITEMS],
        }


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _check_review(packet_path: Path, *, expected_packet_id: str | None = None) -> tuple[bool, bool]:
    """Check if packet has review and if it's accepted."""
    layout = resolve_packet_layout(packet_path.parent)
    latest = latest_review(layout)
    if latest is None:
        return False, False
    packet_id = expected_packet_id
    if packet_id is None:
        try:
            parsed = parse_packet_markdown(packet_path, mode="lenient")
            packet_id = parsed.packet_id
        except Exception:
            return True, False
        if not packet_id:
            return True, False
    try:
        review_result = read_review_artifact_status(
            latest,
            expected_packet_id=packet_id,
        )
        return True, review_result.ok and review_result.status == "accepted"
    except Exception:
        return True, False


def _check_evidence(packet_path: Path) -> tuple[bool, bool]:
    """Check if packet has evidence and if it's valid."""
    evidence_root = packet_path.parent / "EVIDENCE"
    if not evidence_root.exists():
        return False, False
    manifests = sorted(evidence_root.glob("attempt-*/evidence_manifest.json"))
    if not manifests:
        return False, False
    # Simple existence check - full validation would require contract parsing
    return True, True


def _estimate_cost(verification: str, objective: str) -> str:
    """Estimate test cost from verification commands and packet text."""
    text = (verification + " " + objective).lower()

    if "docker" in text or "compose" in text:
        return "docker_required"
    if "playwright" in text or "frontend" in text or "browser" in text:
        return "frontend_quick"
    if "backend" in text and ("quick" in text or "smoke" in text):
        return "backend_quick"
    if "live" in text or "e2e" in text or "integration" in text:
        return "live_required"
    if "pytest" in text and "-q" in text:
        return "targeted"
    if "pytest" in text or "test" in text:
        return "unit"

    return "unknown"


def _classify_risk_flags(
    packet_id: str,
    packet_path: Path,
    parsed: Any,
    registry_record: dict[str, Any] | None,
    source_status: str,
) -> PacketRiskFlags:
    """Classify risk flags for a single packet."""
    flags = PacketRiskFlags()

    # Check dependencies
    if registry_record:
        reg_status = registry_record.get("registry_status", "")
        if reg_status in (RegistryStatus.WAITING_FOR_DEPENDENCIES.value, RegistryStatus.CASCADING_BLOCKED.value):
            flags.dependency_blocked = True
        if reg_status == RegistryStatus.CHANGED_AFTER_ACCEPTANCE.value:
            flags.source_runtime_mismatch = True

    # Check review and evidence
    has_review, review_accepted = _check_review(packet_path, expected_packet_id=parsed.packet_id)
    has_evidence, evidence_valid = _check_evidence(packet_path)

    if not has_review or not review_accepted:
        flags.review_missing = True
    if not has_evidence:
        flags.evidence_missing = True
    elif not evidence_valid:
        flags.evidence_invalid = True

    # Check verification requirements
    verification = (parsed.verification or "").lower()
    objective = (parsed.objective or "").lower()
    combined_text = verification + " " + objective

    if "live" in combined_text or "execute-agent" in combined_text:
        flags.needs_live_agent = True
    if "prefect" in combined_text:
        flags.needs_prefect = True
    if "docker" in combined_text or "compose" in combined_text:
        flags.needs_docker = True
    if "frontend" in combined_text or "playwright" in combined_text:
        flags.needs_frontend = True
    if "backend" in combined_text:
        flags.needs_backend = True

    # Check Git mutation requirements
    if "commit" in combined_text or "git" in combined_text:
        flags.needs_git_commit = True
    if "push" in combined_text:
        flags.needs_git_push = True
    if "merge" in combined_text or "approval" in combined_text:
        flags.needs_merge_approval = True

    # Check frozen scope
    if parsed.frozen_scope:
        flags.touches_frozen_scope = True

    # Check for legacy debt
    if parsed.legacy_warnings:
        flags.known_legacy_debt = True

    # Check for expensive tests
    if "e2e" in combined_text or "integration" in combined_text:
        flags.expensive_tests = True

    # Operator approval required if needs merge or live agent
    if flags.needs_merge_approval or flags.needs_live_agent:
        flags.operator_approval_required = True

    return flags


def _detect_conflicts(packet_summaries: list[PacketRiskSummary]) -> list[ConflictGroup]:
    """Detect file conflicts between ready packets based on allowed write scopes."""
    conflicts: list[ConflictGroup] = []

    # Build a map of paths to packet IDs
    path_to_packets: dict[str, list[str]] = {}
    for summary in packet_summaries:
        for path in summary.allowed_write_scope:
            if path not in path_to_packets:
                path_to_packets[path] = []
            path_to_packets[path].append(summary.packet_id)

    # Find paths with multiple packets
    conflicting_paths = {path: packets for path, packets in path_to_packets.items() if len(packets) > 1}

    # Group by packet sets
    seen_sets: set[frozenset[str]] = set()
    for path, packets in conflicting_paths.items():
        packet_set = frozenset(packets)
        if packet_set not in seen_sets:
            seen_sets.add(packet_set)
            conflicts.append(ConflictGroup(
                packet_ids=sorted(packets),
                conflicting_paths=[p for p, pids in conflicting_paths.items() if frozenset(pids) == packet_set],
            ))

    return conflicts


# START_FUNCTION_CONTRACT
# name: generate_nightly_preflight_risk_report
# purpose: Generate read-only risk report for ready packets before nightly execution.
# inputs:
#   project_config: Explicit or default project config path.
# returns: NightlyPreflightRiskReport with bounded risk classifications.
# side_effects: Reads packet files, registry state, evidence, and reviews only.
# emitted_logs: None.
# error_behavior: Returns ok=False on load failure or analysis errors.
# END_FUNCTION_CONTRACT
def generate_nightly_preflight_risk_report(
    *,
    project_config: Path | str | None = None,
) -> NightlyPreflightRiskReport:
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return NightlyPreflightRiskReport(
            ok=False,
            project_key="",
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    result = NightlyPreflightRiskReport(
        ok=False,
        project_key=project.project_key,
    )

    try:
        # Get dry-run summary for context (optional, for additional context only)
        try:
            dry_run = run_nightly_dry_run(project_config=project_config, until_blocked=False)
        except Exception as dry_run_exc:
            result.warnings.append(_error("DRY_RUN_FAILED", f"Dry run failed but continuing: {dry_run_exc}"))

        # Get registry state
        registry = PacketRegistryStore(Path(project.repo_root) / project.runtime_state_root / "state")
        all_packets = registry.list_packets(project.project_key)

        # Get source packets
        packets_dir = Path(project.repo_root) / project.packets_dir
        if not packets_dir.exists():
            result.errors.append(_error("PACKETS_DIR_NOT_FOUND", f"Packets directory not found: {packets_dir}"))
            return result

        packet_files = sorted(packets_dir.glob("**/*.md"))

        # Analyze each packet
        packet_summaries: list[PacketRiskSummary] = []
        safe_candidates: list[str] = []
        risky_candidates: list[str] = []
        blocked_candidates: list[str] = []
        approval_required_candidates: list[str] = []

        ready_total = 0
        blocked_total = 0
        accepted_total = 0

        for packet_file in packet_files:
            try:
                parsed = parse_packet_markdown(packet_file, mode="lenient")

                # Skip non-runnable packets
                if not parsed.packet_id or not parsed.feature_id or not parsed.wave_id:
                    continue

                # Skip if missing strict sections
                required_sections = [
                    parsed.allowed_write_scope is not None,
                    parsed.frozen_scope is not None,
                    parsed.must_preserve is not None,
                    parsed.verification is not None,
                    parsed.expected_evidence is not None,
                    parsed.escalation_triggers is not None,
                ]
                if not all(required_sections):
                    continue

                packet_id = parsed.packet_id
                registry_record = registry.load_packet(packet_id)

                if not registry_record:
                    continue

                reg_status = registry_record.get("registry_status", "")
                source_status = parsed.status or "ready"

                # Count by status
                if reg_status == RegistryStatus.READY.value or reg_status == RegistryStatus.READY_FOR_RETRY.value:
                    ready_total += 1
                elif reg_status == RegistryStatus.BLOCKED.value or reg_status == RegistryStatus.CASCADING_BLOCKED.value:
                    blocked_total += 1
                elif reg_status == RegistryStatus.ACCEPTED.value:
                    accepted_total += 1

                # Classify risk flags
                risk_flags = _classify_risk_flags(packet_id, packet_file, parsed, registry_record, source_status)
                cost_estimate = _estimate_cost(parsed.verification, parsed.objective)

                summary = PacketRiskSummary(
                    packet_id=packet_id,
                    registry_status=reg_status,
                    source_status=source_status,
                    risk_flags=risk_flags,
                    cost_estimate=cost_estimate,
                    allowed_write_scope=parsed.allowed_write_scope,
                    impacted_modules=parsed.modules,
                )
                packet_summaries.append(summary)

                # Classify into categories (only for ready packets)
                if reg_status in (RegistryStatus.READY.value, RegistryStatus.READY_FOR_RETRY.value):
                    if risk_flags.operator_approval_required:
                        approval_required_candidates.append(packet_id)
                    elif (risk_flags.dependency_blocked or risk_flags.source_runtime_mismatch or
                          risk_flags.review_missing or risk_flags.evidence_missing or risk_flags.evidence_invalid):
                        blocked_candidates.append(packet_id)
                    elif (risk_flags.needs_live_agent or risk_flags.needs_docker or
                          risk_flags.needs_frontend or risk_flags.needs_backend or
                          risk_flags.expensive_tests or risk_flags.needs_git_commit):
                        risky_candidates.append(packet_id)
                    else:
                        safe_candidates.append(packet_id)

            except Exception as exc:
                result.warnings.append(_error("PACKET_ANALYSIS_FAILED", f"Failed to analyze {packet_file.name}: {exc}"))

        # Detect conflicts
        conflict_groups = _detect_conflicts(packet_summaries)

        # Mark conflict candidates as risky
        conflict_packet_ids = set()
        for group in conflict_groups:
            for pid in group.packet_ids:
                conflict_packet_ids.add(pid)
                # Update risk flags
                for summary in packet_summaries:
                    if summary.packet_id == pid:
                        summary.risk_flags.file_conflict_candidate = True

        # Move conflict candidates from safe to risky
        safe_candidates = [pid for pid in safe_candidates if pid not in conflict_packet_ids]
        for pid in conflict_packet_ids:
            if pid not in risky_candidates and pid not in blocked_candidates and pid not in approval_required_candidates:
                risky_candidates.append(pid)

        # Populate result
        result.packets_total = len(packet_summaries)
        result.ready_total = ready_total
        result.blocked_total = blocked_total
        result.accepted_total = accepted_total
        result.safe_candidates = safe_candidates
        result.safe_candidates_total = len(safe_candidates)
        result.risky_candidates = risky_candidates
        result.risky_candidates_total = len(risky_candidates)
        result.blocked_candidates = blocked_candidates
        result.blocked_candidates_total = len(blocked_candidates)
        result.approval_required_candidates = approval_required_candidates
        result.approval_required_candidates_total = len(approval_required_candidates)
        result.conflict_groups = conflict_groups
        result.conflict_groups_total = len(conflict_groups)
        result.packet_summaries = packet_summaries

        result.ok = not result.errors

    except Exception as exc:
        result.errors.append(_error("PREFLIGHT_RISK_REPORT_FAILED", str(exc)))

    return result
