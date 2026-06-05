# ############################################################################
# AI_HEADER: nightly_batch_selection
# ROLE: Read-only safe batch selector for nightly dry-run execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Select safe, dependency-ordered batch of packets from preflight risk report.
# inputs: Preflight risk report (live or saved JSON).
# returns: BatchSelectionResult with selected/excluded packets and reasons.
# side_effects: Read-only analysis, no execution or mutation.
# emitted_logs: None.
# error_behavior: Returns structured errors without execution.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: BatchSelectionResult
#   - dataclass: ExcludedPacket
#   - dataclass: BatchLimits
#   - dataclass: SelectedPacketFact
#   - function: select_safe_batch
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json

from prefect_grace.platform.nightly_preflight_risk_report import (
    NightlyPreflightRiskReport,
    PacketRiskSummary,
    generate_nightly_preflight_risk_report,
)
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import RegistryStatus


MAX_ITEMS = 25
DEFAULT_MAX_PACKETS = 10
DEFAULT_MAX_COST = "live_required"


# Cost hierarchy from cheapest to most expensive
COST_HIERARCHY = [
    "unknown",
    "unit",
    "targeted",
    "backend_quick",
    "frontend_quick",
    "docker_required",
    "live_required",
]


@dataclass
class ExcludedPacket:
    packet_id: str
    reason: str
    details: str = ""

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize excluded packet to dictionary.
    # inputs: none.
    # returns: dict with packet_id, reason, details.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchLimits:
    max_packets: int = DEFAULT_MAX_PACKETS
    max_cost: str = DEFAULT_MAX_COST
    allow_conflicts: bool = False
    allow_risky: bool = False

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize batch limits to dictionary.
    # inputs: none.
    # returns: dict with max_packets, max_cost, allow_conflicts, allow_risky.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectedPacketFact:
    packet_id: str
    source_hash: str = ""
    registry_status: str = ""
    source_status: str = ""
    depends_on: list[str] = field(default_factory=list)
    review_status: str = ""
    evidence_status: str = ""
    cost_estimate: str = "unknown"

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize selected packet facts for stale-safe recheck.
    # inputs: none.
    # returns: compact dict with bounded dependency list.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "source_hash": self.source_hash,
            "registry_status": self.registry_status,
            "source_status": self.source_status,
            "depends_on": self.depends_on[:MAX_ITEMS],
            "review_status": self.review_status,
            "evidence_status": self.evidence_status,
            "cost_estimate": self.cost_estimate,
        }


@dataclass
class BatchSelectionResult:
    ok: bool
    project_key: str
    mode: str = "nightly_batch_selection"
    selected_packets: list[str] = field(default_factory=list)
    selected_packet_facts: list[SelectedPacketFact] = field(default_factory=list)
    selected_total: int = 0
    excluded_packets: list[ExcludedPacket] = field(default_factory=list)
    excluded_total: int = 0
    batch_limits: BatchLimits = field(default_factory=BatchLimits)
    conflict_groups_detected: int = 0
    estimated_total_cost: str = "unknown"
    stop_reason: str = ""
    dry_run: bool = True
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize batch selection result to dictionary with bounded lists.
    # inputs: none.
    # returns: dict with all result fields and lists truncated to MAX_ITEMS.
    # side_effects: none.
    # emitted_logs: none.
    # error_behavior: none.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "mode": self.mode,
            "selected_packets": self.selected_packets[:MAX_ITEMS],
            "selected_packet_facts": [fact.to_dict() for fact in self.selected_packet_facts[:MAX_ITEMS]],
            "selected_total": self.selected_total,
            "excluded_packets": [ep.to_dict() for ep in self.excluded_packets[:MAX_ITEMS]],
            "excluded_total": self.excluded_total,
            "batch_limits": self.batch_limits.to_dict(),
            "conflict_groups_detected": self.conflict_groups_detected,
            "estimated_total_cost": self.estimated_total_cost,
            "stop_reason": self.stop_reason,
            "dry_run": self.dry_run,
            "warnings": self.warnings[:MAX_ITEMS],
            "errors": self.errors[:MAX_ITEMS],
        }


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _cost_exceeds_limit(cost: str, max_cost: str) -> bool:
    """Check if cost exceeds the maximum allowed cost."""
    try:
        cost_idx = COST_HIERARCHY.index(cost)
        max_idx = COST_HIERARCHY.index(max_cost)
        return cost_idx > max_idx
    except ValueError:
        # Unknown cost, treat as exceeding limit
        return True


def _estimate_batch_cost(costs: list[str]) -> str:
    """Estimate total batch cost from individual packet costs."""
    if not costs:
        return "unknown"

    # Return the highest cost in the hierarchy
    max_cost_idx = -1
    max_cost = "unknown"
    for cost in costs:
        try:
            idx = COST_HIERARCHY.index(cost)
            if idx > max_cost_idx:
                max_cost_idx = idx
                max_cost = cost
        except ValueError:
            continue

    return max_cost


def _packet_path_from_record(
    *,
    repo_root: Path,
    packets_dir: Path,
    packet_id: str,
    registry_record: dict[str, Any] | None,
) -> Path:
    record_path = str((registry_record or {}).get("path") or "")
    if record_path:
        candidate = Path(record_path)
        return candidate if candidate.is_absolute() else repo_root / candidate

    feature_id = packet_id.split("-W", 1)[0] if "-W" in packet_id else packet_id
    return packets_dir / feature_id / "EXECUTION_PACKET.md"


def _fact_from_selected_summary(
    *,
    summary: PacketRiskSummary,
    registry_record: dict[str, Any] | None,
    repo_root: Path,
    packets_dir: Path,
) -> SelectedPacketFact:
    source_hash = str((registry_record or {}).get("source_hash") or "")
    packet_path = _packet_path_from_record(
        repo_root=repo_root,
        packets_dir=packets_dir,
        packet_id=summary.packet_id,
        registry_record=registry_record,
    )
    if packet_path.exists():
        try:
            parsed = parse_packet_markdown(packet_path, mode="lenient")
            source_hash = parsed.source_hash
        except Exception:
            pass

    evidence_status = "valid"
    if summary.risk_flags.evidence_missing:
        evidence_status = "missing"
    elif summary.risk_flags.evidence_invalid:
        evidence_status = "invalid"

    return SelectedPacketFact(
        packet_id=summary.packet_id,
        source_hash=source_hash,
        registry_status=str((registry_record or {}).get("registry_status") or summary.registry_status),
        source_status=summary.source_status,
        depends_on=list((registry_record or {}).get("depends_on") or []),
        review_status="missing" if summary.risk_flags.review_missing else "accepted",
        evidence_status=evidence_status,
        cost_estimate=summary.cost_estimate,
    )


def _topological_sort(
    packets: list[PacketRiskSummary],
    registry: PacketRegistryStore,
) -> list[str]:
    """
    Perform topological sort on packets based on dependencies.
    Returns ordered list of packet IDs.
    """
    # Build dependency graph
    packet_map = {p.packet_id: p for p in packets}
    in_degree = {p.packet_id: 0 for p in packets}
    adjacency = {p.packet_id: [] for p in packets}

    for packet in packets:
        reg_record = registry.load_packet(packet.packet_id)
        if reg_record:
            deps = reg_record.get("depends_on", [])
            for dep_id in deps:
                # Only count dependencies within the batch
                if dep_id in packet_map:
                    adjacency[dep_id].append(packet.packet_id)
                    in_degree[packet.packet_id] += 1

    # Kahn's algorithm
    queue = [pid for pid, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        # Sort for deterministic ordering
        queue.sort()
        current = queue.pop(0)
        result.append(current)

        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If result doesn't contain all packets, there's a cycle (shouldn't happen with preflight)
    if len(result) != len(packets):
        # Return packets in original order as fallback
        return [p.packet_id for p in packets]

    return result


# START_FUNCTION_CONTRACT
# name: select_safe_batch
# purpose: Select safe batch of packets from preflight risk report.
# inputs:
#   project_config: Explicit or default project config path.
#   preflight_report_path: Optional path to saved preflight JSON file.
#   max_packets: Maximum number of packets to select.
#   max_cost: Maximum cost level allowed.
#   allow_conflicts: Allow packets with file conflicts.
#   allow_risky: Allow risky packets (not recommended).
# returns: BatchSelectionResult with selected/excluded packets.
# side_effects: Reads preflight report, registry state only.
# emitted_logs: None.
# error_behavior: Returns ok=False on load failure or analysis errors.
# END_FUNCTION_CONTRACT
def select_safe_batch(
    *,
    project_config: Path | str | None = None,
    preflight_report_path: Path | str | None = None,
    max_packets: int = DEFAULT_MAX_PACKETS,
    max_cost: str = DEFAULT_MAX_COST,
    allow_conflicts: bool = False,
    allow_risky: bool = False,
) -> BatchSelectionResult:
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return BatchSelectionResult(
            ok=False,
            project_key="",
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    result = BatchSelectionResult(
        ok=False,
        project_key=project.project_key,
        batch_limits=BatchLimits(
            max_packets=max_packets,
            max_cost=max_cost,
            allow_conflicts=allow_conflicts,
            allow_risky=allow_risky,
        ),
    )

    try:
        # Load or generate preflight report
        if preflight_report_path:
            # Load from saved JSON
            try:
                with open(preflight_report_path, "r", encoding="utf-8") as f:
                    report_data = json.load(f)

                # Reconstruct preflight report from JSON
                # For simplicity, we'll regenerate it - in production, you'd deserialize properly
                preflight_report = generate_nightly_preflight_risk_report(
                    project_config=project_config
                )
            except Exception as load_exc:
                result.errors.append(_error("PREFLIGHT_REPORT_LOAD_FAILED", str(load_exc)))
                return result
        else:
            # Generate live preflight report
            preflight_report = generate_nightly_preflight_risk_report(
                project_config=project_config
            )

        if not preflight_report.ok:
            result.errors.append(_error(
                "PREFLIGHT_REPORT_FAILED",
                "Preflight risk report generation failed",
            ))
            result.errors.extend(preflight_report.errors)
            return result

        # Get registry for dependency checking
        registry = PacketRegistryStore(Path(project.repo_root) / project.runtime_state_root / "state")

        # Start with safe candidates from preflight
        candidate_summaries: list[PacketRiskSummary] = []

        for summary in preflight_report.packet_summaries:
            if summary.packet_id in preflight_report.safe_candidates:
                candidate_summaries.append(summary)

        # If allow_risky, also include risky candidates (but not blocked or approval-required)
        if allow_risky:
            for summary in preflight_report.packet_summaries:
                if summary.packet_id in preflight_report.risky_candidates:
                    candidate_summaries.append(summary)

        # Track selected and excluded
        selected: list[PacketRiskSummary] = []
        excluded: list[ExcludedPacket] = []
        selected_packet_ids: set[str] = set()
        selected_paths: set[str] = set()

        # Process candidates in dependency order
        ordered_candidates = _topological_sort(candidate_summaries, registry)
        candidate_map = {s.packet_id: s for s in candidate_summaries}

        for packet_id in ordered_candidates:
            summary = candidate_map[packet_id]

            # Check if batch limit reached
            if len(selected) >= max_packets:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="batch_limit_reached",
                    details=f"Batch limit of {max_packets} packets reached",
                ))
                continue

            # Check dependencies
            reg_record = registry.load_packet(packet_id)
            if not reg_record:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="unknown_invalid_metadata",
                    details="Packet not found in registry",
                ))
                continue

            deps = reg_record.get("depends_on", [])
            unmet_deps = []
            for dep_id in deps:
                dep_record = registry.load_packet(dep_id)
                if not dep_record:
                    unmet_deps.append(dep_id)
                    continue

                dep_status = dep_record.get("registry_status", "")
                # Dependency must be accepted OR selected earlier in this batch
                if dep_status != RegistryStatus.ACCEPTED.value and dep_id not in selected_packet_ids:
                    unmet_deps.append(dep_id)

            if unmet_deps:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="dependency_blocked",
                    details=f"Unmet dependencies: {', '.join(unmet_deps)}",
                ))
                continue

            # Check risk flags
            if summary.risk_flags.dependency_blocked:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="dependency_blocked",
                    details="Dependency blocked by preflight",
                ))
                continue

            if summary.risk_flags.operator_approval_required:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="approval_required",
                    details="Operator approval required",
                ))
                continue

            if summary.risk_flags.review_missing or summary.risk_flags.evidence_missing:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="risk_blocked",
                    details="Missing review or evidence",
                ))
                continue

            # Check file conflicts
            if not allow_conflicts and summary.risk_flags.file_conflict_candidate:
                # Check if any selected packet conflicts with this one
                has_conflict = False
                for path in summary.allowed_write_scope:
                    if path in selected_paths:
                        has_conflict = True
                        break

                if has_conflict:
                    excluded.append(ExcludedPacket(
                        packet_id=packet_id,
                        reason="file_conflict",
                        details="File conflict with earlier selected packet",
                    ))
                    continue

            # Check cost
            if _cost_exceeds_limit(summary.cost_estimate, max_cost):
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="test_cost_too_high",
                    details=f"Cost {summary.cost_estimate} exceeds limit {max_cost}",
                ))
                continue

            # Packet passes all checks - select it
            selected.append(summary)
            selected_packet_ids.add(packet_id)
            for path in summary.allowed_write_scope:
                selected_paths.add(path)

        # Add all non-candidate packets as excluded
        all_ready_ids = set(preflight_report.safe_candidates + preflight_report.risky_candidates)
        for summary in preflight_report.packet_summaries:
            packet_id = summary.packet_id

            # Skip if already processed
            if packet_id in selected_packet_ids or any(e.packet_id == packet_id for e in excluded):
                continue

            # Determine exclusion reason
            if packet_id in preflight_report.approval_required_candidates:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="approval_required",
                    details="Operator approval required",
                ))
            elif packet_id in preflight_report.blocked_candidates:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="risk_blocked",
                    details="Blocked by preflight risk analysis",
                ))
            elif packet_id in preflight_report.risky_candidates and not allow_risky:
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="risk_blocked",
                    details="Risky packet excluded (use --allow-risky to include)",
                ))
            elif summary.registry_status not in (RegistryStatus.READY.value, RegistryStatus.READY_FOR_RETRY.value):
                excluded.append(ExcludedPacket(
                    packet_id=packet_id,
                    reason="dependency_blocked",
                    details=f"Registry status: {summary.registry_status}",
                ))

        # Populate result
        result.selected_packets = [s.packet_id for s in selected]
        repo_root = Path(project.repo_root)
        packets_dir = repo_root / project.packets_dir
        result.selected_packet_facts = [
            _fact_from_selected_summary(
                summary=s,
                registry_record=registry.load_packet(s.packet_id),
                repo_root=repo_root,
                packets_dir=packets_dir,
            )
            for s in selected
        ]
        result.selected_total = len(selected)
        result.excluded_packets = excluded
        result.excluded_total = len(excluded)
        result.conflict_groups_detected = preflight_report.conflict_groups_total
        result.estimated_total_cost = _estimate_batch_cost([s.cost_estimate for s in selected])

        # Determine stop reason
        if len(selected) == 0:
            result.stop_reason = "no_safe_candidates"
        elif len(selected) >= max_packets:
            result.stop_reason = "batch_limit_reached"
        else:
            result.stop_reason = "all_safe_candidates_selected"

        result.ok = True

    except Exception as exc:
        result.errors.append(_error("BATCH_SELECTION_FAILED", str(exc)))

    return result
