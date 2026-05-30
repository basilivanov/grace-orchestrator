# ############################################################################
# AI_HEADER: backlog_controller
# ROLE: Deterministic backlog controller for GRACE packet orchestration.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Scan controller packets, validate dependencies, update registry, plan submissions.
# inputs: ProjectAdapterConfig, dry_run flag, retry/rerun flags.
# returns: BacklogSyncResult and BacklogSubmissionPlan.
# side_effects: Updates packet registry state on disk.
# emitted_logs: None.
# error_behavior: Returns structured errors in result objects.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: BacklogSyncResult
#   - class: BacklogSubmissionPlan
#   - class: BacklogController
#   - function: sync
#   - function: plan_submission
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.dag import validate_packet_dag
from prefect_grace.platform.controller_backlog_bootstrap import summarize_skip_warnings
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import (
    RegistryStatus,
    SourcePacketStatus,
    normalize_registry_status,
    normalize_source_status,
    is_terminal_registry_status,
    is_runnable_registry_status,
)

#START_BLOCK_MODELS
@dataclass
class BacklogSyncResult:
    project_key: str
    packets_total: int
    registry_updates: int = 0
    ready: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    changed_after_acceptance: list[str] = field(default_factory=list)
    ready_for_retry: list[str] = field(default_factory=list)
    cascading_blocked: list[str] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BacklogSubmissionPlan:
    project_key: str
    packets_to_submit: list[str] = field(default_factory=list)
    submission_order: list[str] = field(default_factory=list)
    blocked_packets: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

#END_BLOCK_MODELS
#START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: update_dependent_packets
# purpose: Update cascading status when a dependency changes state.
# inputs:
#   packet_id: ID of the dependency packet that changed.
#   new_status: New status of the dependency (blocked or accepted).
#   registry: PacketRegistryStore for reading/writing registry state.
#   all_packets: Full list of packets to check for dependents.
# returns: List of updated packet IDs.
# side_effects: Updates registry state for dependent packets.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def update_dependent_packets(
    packet_id: str,
    new_status: str,
    registry: PacketRegistryStore,
    all_packets: list[dict[str, Any]],
) -> list[str]:
    updated = []

    if new_status == RegistryStatus.BLOCKED.value:
        # Find packets that depend on this one
        for p in all_packets:
            if packet_id in p.get("depends_on", []):
                existing = registry.load_packet(p["packet_id"])
                if existing:
                    registry.upsert_packet({
                        **existing,
                        "registry_status": RegistryStatus.CASCADING_BLOCKED.value,
                        "registry_reason": f"dependency_{packet_id}_blocked",
                    })
                    updated.append(p["packet_id"])

    elif new_status == RegistryStatus.ACCEPTED.value:
        # Unblock dependents if all their deps are now satisfied
        for p in all_packets:
            if packet_id in p.get("depends_on", []):
                existing = registry.load_packet(p["packet_id"])
                if existing and existing.get("registry_status") in (RegistryStatus.CASCADING_BLOCKED.value, RegistryStatus.WAITING_FOR_DEPENDENCIES.value):
                    deps = p.get("depends_on", [])
                    all_deps_ok = all(
                        registry.load_packet(d) and registry.load_packet(d).get("registry_status") == RegistryStatus.ACCEPTED.value
                        for d in deps
                    )
                    if all_deps_ok:
                        registry.upsert_packet({
                            **existing,
                            "registry_status": RegistryStatus.READY.value,
                            "registry_reason": "dependencies_satisfied",
                        })
                        updated.append(p["packet_id"])

    return updated

#END_BLOCK_HELPERS
def _is_unchanged_accepted_registry_record(
    packet: dict[str, Any],
    registry_record: dict[str, Any] | None,
) -> bool:
    return bool(
        registry_record
        and registry_record.get("registry_status") == RegistryStatus.ACCEPTED.value
        and registry_record.get("source_hash") == packet.get("source_hash")
    )


def _is_accepted_registry_record(packet: dict[str, Any]) -> bool:
    return packet.get("registry_status") == RegistryStatus.ACCEPTED.value


def _visible_dag_warnings(
    dag_warnings: list[str],
    missing_dependencies: dict[str, list[str]],
    suppressed_packet_ids: set[str],
) -> list[str]:
    visible_missing_count = len(
        [
            packet_id
            for packet_id in missing_dependencies
            if packet_id not in suppressed_packet_ids
        ]
    )
    filtered = [
        warning
        for warning in dag_warnings
        if "packet(s) have missing dependencies" not in warning
    ]
    if visible_missing_count:
        filtered.append(f"{visible_missing_count} packet(s) have missing dependencies")
    return filtered


def _visible_cascading_blocked(
    cascading_blocked: list[str],
    missing_dependencies: dict[str, list[str]],
    suppressed_packet_ids: set[str],
) -> list[str]:
    suppressible_missing = set(missing_dependencies).intersection(suppressed_packet_ids)
    return [
        packet_id
        for packet_id in cascading_blocked
        if packet_id not in suppressible_missing
    ]


#START_BLOCK_CONTROLLER
class BacklogController:
    # START_FUNCTION_CONTRACT
    # name: sync
    # purpose: Scan packets, validate dependencies, update registry state.
    # inputs:
    #   project: ProjectAdapterConfig with repo_root, packets_dir, runtime_state_root.
    #   dry_run: if True, do not write registry updates.
    #   retry_blocked: if True, mark blocked packets with changed hash as ready_for_retry.
    #   rerun_changed: if True, mark accepted packets with changed hash as ready.
    # returns: BacklogSyncResult with sync details.
    # side_effects: Updates packet_registry.yaml if not dry_run.
    # emitted_logs: None.
    # error_behavior: Returns errors in result object.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def sync(
        project: Any,
        dry_run: bool = False,
        retry_blocked: bool = False,
        rerun_changed: bool = False,
    ) -> BacklogSyncResult:
        result = BacklogSyncResult(
            project_key=project.project_key,
            packets_total=0,
        )

        packets_dir = Path(project.repo_root) / project.packets_dir
        if not packets_dir.exists():
            result.errors.append(f"Packets directory not found: {packets_dir}")
            return result

        registry = PacketRegistryStore(Path(project.runtime_state_root) / "state")

        packet_files = sorted(packets_dir.glob("**/*.md"))
        packets_data: list[dict[str, Any]] = []

        for path in packet_files:
            try:
                parsed = parse_packet_markdown(path, mode="lenient")

                # Filter out evidence markdown and non-runnable packets
                # A valid source controller packet must have non-empty packet_id, feature_id, and wave_id
                if not parsed.packet_id or not parsed.feature_id or not parsed.wave_id:
                    result.warnings.append(
                        f"Skipping non-runnable packet {path.name}: "
                        f"missing packet_id={bool(parsed.packet_id)}, "
                        f"feature_id={bool(parsed.feature_id)}, "
                        f"wave_id={bool(parsed.wave_id)}"
                    )
                    continue

                # Additionally check for strict controller packet schema
                # Legacy role packets may have IDs but lack required sections
                required_sections = [
                    parsed.allowed_write_scope,
                    parsed.frozen_scope,
                    parsed.must_preserve,
                    parsed.verification,
                    parsed.expected_evidence,
                    parsed.escalation_triggers,
                ]
                if not all(required_sections):
                    result.warnings.append(
                        f"Skipping legacy packet {path.name}: "
                        f"has IDs but missing strict controller sections "
                        f"(allowed_write_scope={bool(parsed.allowed_write_scope)}, "
                        f"frozen_scope={bool(parsed.frozen_scope)}, "
                        f"must_preserve={bool(parsed.must_preserve)}, "
                        f"verification={bool(parsed.verification)}, "
                        f"expected_evidence={bool(parsed.expected_evidence)}, "
                        f"escalation_triggers={bool(parsed.escalation_triggers)})"
                    )
                    continue

                packet_dict = {
                    "packet_id": parsed.packet_id,
                    "feature_id": parsed.feature_id,
                    "wave_id": parsed.wave_id,
                    "title": parsed.title,
                    "objective": parsed.objective,
                    "status": normalize_source_status(parsed.status).value,
                    "phase": parsed.phase,
                    "depends_on": parsed.depends_on,
                    "source_hash": parsed.source_hash,
                    "path": str(path.relative_to(project.repo_root)),
                }
                packets_data.append(packet_dict)
            except Exception as e:
                result.errors.append(f"Failed to parse {path}: {e}")

        result.warnings = summarize_skip_warnings(result.warnings)
        result.packets_total = len(packets_data)

        dag_result = validate_packet_dag(packets_data)
        accepted_dag_suppressed = {
            packet["packet_id"]
            for packet in packets_data
            if _is_unchanged_accepted_registry_record(
                packet,
                registry.load_packet(packet["packet_id"]),
            )
        }
        visible_cascading_blocked = _visible_cascading_blocked(
            dag_result.cascading_blocked,
            dag_result.missing_dependencies,
            accepted_dag_suppressed,
        )
        result.cycles = dag_result.cycles
        result.cascading_blocked = visible_cascading_blocked
        result.warnings.extend(
            _visible_dag_warnings(
                dag_result.warnings,
                dag_result.missing_dependencies,
                accepted_dag_suppressed,
            )
        )
        result.errors.extend(dag_result.errors)

        # Helper to check if all dependencies are accepted in registry
        def _dependencies_satisfied(packet: dict[str, Any]) -> bool:
            deps = packet.get("depends_on", [])
            if not deps:
                return True
            for dep_id in deps:
                dep_record = registry.load_packet(dep_id)
                if dep_record is None or dep_record.get("registry_status") != RegistryStatus.ACCEPTED.value:
                    return False
            return True

        for packet in packets_data:
            packet_id = packet["packet_id"]
            source_hash = packet["source_hash"]
            registry_record = registry.load_packet(packet_id)

            if packet_id in visible_cascading_blocked:
                result.blocked.append(packet_id)
                if not dry_run:
                    registry.upsert_packet({
                        **packet,
                        "registry_status": RegistryStatus.CASCADING_BLOCKED.value,
                        "registry_reason": "dependency_blocked",
                    })
                    result.registry_updates += 1
                continue

            # Check if dependencies are satisfied before marking as ready
            deps_satisfied = _dependencies_satisfied(packet)

            if registry_record is None:
                if deps_satisfied:
                    result.ready.append(packet_id)
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.READY.value,
                        })
                        result.registry_updates += 1
                else:
                    # New packet with unsatisfied dependencies
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.WAITING_FOR_DEPENDENCIES.value,
                            "registry_reason": f"waiting for: {', '.join(packet.get('depends_on', []))}",
                        })
                        result.registry_updates += 1
                continue

            registry_status = registry_record.get("registry_status", "")
            registry_hash = registry_record.get("source_hash", "")

            if registry_status == RegistryStatus.ACCEPTED.value:
                if source_hash != registry_hash:
                    if rerun_changed:
                        result.ready.append(packet_id)
                        if not dry_run:
                            registry.upsert_packet({
                                **packet,
                                "registry_status": RegistryStatus.READY.value,
                                "registry_reason": "changed_after_acceptance",
                                "resume_allowed": False,
                                "resume_block_reason": "contract_changed",
                                "recommended_rework_mode": "bounded_fresh",
                            })
                            result.registry_updates += 1
                    else:
                        result.changed_after_acceptance.append(packet_id)
                        if not dry_run:
                            registry.upsert_packet({
                                **packet,
                                "registry_status": RegistryStatus.CHANGED_AFTER_ACCEPTANCE.value,
                                "resume_allowed": False,
                                "resume_block_reason": "contract_changed",
                                "recommended_rework_mode": "bounded_fresh",
                            })
                            result.registry_updates += 1
                else:
                    result.accepted.append(packet_id)

            elif registry_status == RegistryStatus.BLOCKED.value:
                if source_hash != registry_hash:
                    if retry_blocked:
                        result.ready_for_retry.append(packet_id)
                        if not dry_run:
                            registry.upsert_packet({
                                **packet,
                                "registry_status": RegistryStatus.READY.value,
                                "registry_reason": "retry_after_change",
                                "resume_allowed": False,
                                "resume_block_reason": "contract_changed",
                                "recommended_rework_mode": "bounded_fresh",
                            })
                            result.registry_updates += 1
                    else:
                        result.ready_for_retry.append(packet_id)
                        if not dry_run:
                            registry.upsert_packet({
                                **packet,
                                "registry_status": RegistryStatus.READY_FOR_RETRY.value,
                                "resume_allowed": False,
                                "resume_block_reason": "contract_changed",
                                "recommended_rework_mode": "bounded_fresh",
                            })
                            result.registry_updates += 1
                else:
                    result.blocked.append(packet_id)

            elif registry_status in (RegistryStatus.WAITING_FOR_DEPENDENCIES.value, RegistryStatus.CASCADING_BLOCKED.value):
                # Re-check if dependencies are now satisfied
                if deps_satisfied:
                    result.ready.append(packet_id)
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.READY.value,
                            "registry_reason": "dependencies_satisfied",
                        })
                        result.registry_updates += 1
                else:
                    # Still waiting
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.WAITING_FOR_DEPENDENCIES.value,
                            "registry_reason": f"waiting for: {', '.join(packet.get('depends_on', []))}",
                        })
                        result.registry_updates += 1

            else:
                # Other statuses (ready, ready_for_retry, etc.)
                if deps_satisfied:
                    result.ready.append(packet_id)
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.READY.value,
                        })
                        result.registry_updates += 1
                else:
                    if not dry_run:
                        registry.upsert_packet({
                            **packet,
                            "registry_status": RegistryStatus.WAITING_FOR_DEPENDENCIES.value,
                            "registry_reason": f"waiting for: {', '.join(packet.get('depends_on', []))}",
                        })
                        result.registry_updates += 1

        return result

    # START_FUNCTION_CONTRACT
    # name: plan_submission
    # purpose: Compute which packets are ready to submit to runtime.
    # inputs:
    #   project: ProjectAdapterConfig.
    # returns: BacklogSubmissionPlan with packets to submit.
    # side_effects: Reads packet registry state.
    # emitted_logs: None.
    # error_behavior: Returns errors in result object.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def plan_submission(project: Any) -> BacklogSubmissionPlan:
        plan = BacklogSubmissionPlan(project_key=project.project_key)

        registry = PacketRegistryStore(Path(project.runtime_state_root) / "state")
        all_packets = registry.list_packets()

        ready_packets = [
            p for p in all_packets
            if p.get("registry_status") in (RegistryStatus.READY.value, RegistryStatus.READY_FOR_RETRY.value)
        ]

        blocked_packets = [
            p for p in all_packets
            if p.get("registry_status") in (RegistryStatus.BLOCKED.value, RegistryStatus.CASCADING_BLOCKED.value)
        ]

        # Validate DAG against full registry state, not just ready packets
        # This ensures we have complete dependency context
        dag_result = validate_packet_dag(all_packets)
        accepted_dag_suppressed = {
            packet["packet_id"]
            for packet in all_packets
            if _is_accepted_registry_record(packet)
        }
        visible_cascading_blocked = _visible_cascading_blocked(
            dag_result.cascading_blocked,
            dag_result.missing_dependencies,
            accepted_dag_suppressed,
        )

        # Filter to only runnable packets: ready status AND all dependencies accepted
        runnable_packets = []
        for packet in ready_packets:
            packet_id = packet["packet_id"]
            deps = packet.get("depends_on", [])

            # Check if all dependencies are accepted
            all_deps_accepted = True
            for dep_id in deps:
                dep_record = registry.load_packet(dep_id)
                if dep_record is None or dep_record.get("registry_status") != RegistryStatus.ACCEPTED.value:
                    all_deps_accepted = False
                    plan.warnings.append(
                        f"Packet {packet_id} has unmet dependency: {dep_id}"
                    )
                    break

            if all_deps_accepted and packet_id not in visible_cascading_blocked:
                runnable_packets.append(packet)

        plan.packets_to_submit = [p["packet_id"] for p in runnable_packets]

        # Build submission order from runnable packets only
        if runnable_packets:
            runnable_dag_result = validate_packet_dag(runnable_packets)
            plan.submission_order = runnable_dag_result.ordered_packets
            plan.warnings.extend(runnable_dag_result.warnings)
            plan.errors.extend(runnable_dag_result.errors)

        plan.blocked_packets = [p["packet_id"] for p in blocked_packets]
        plan.warnings.extend(
            _visible_dag_warnings(
                dag_result.warnings,
                dag_result.missing_dependencies,
                accepted_dag_suppressed,
            )
        )
        plan.errors.extend(dag_result.errors)

        return plan

#END_BLOCK_CONTROLLER
