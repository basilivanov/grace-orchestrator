# ############################################################################
# AI_HEADER: packet_yaml_sidecar_migration_apply
# ROLE: Applies guarded EXECUTION_PACKET.yaml sidecar migration selections.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan or apply bounded YAML sidecar migrations behind explicit operator gates.
# inputs: Packet root, project config, selection flags, limit, apply mode, and approval tokens.
# returns: PacketYamlSidecarMigrationApplyResult with selected items, writes, and errors.
# side_effects: Writes only adjacent EXECUTION_PACKET.yaml sidecars when apply=True and gates pass.
# emitted_logs: None.
# error_behavior: Fails closed for unfiltered selection, invalid selected sidecars, and missing gates.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketYamlSidecarMigrationApplyResult
#   - function: apply_packet_yaml_sidecar_migration
# END_MODULE_MAP

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_yaml_sidecar_migration_plan import (
    MAX_ITEM_LIMIT,
    plan_packet_yaml_sidecar_migration,
)
from prefect_grace.platform.packet_yaml_sidecar_sync import sync_packet_yaml_sidecars


APPROVAL_ENV_NAME = "GRACE_PACKET_YAML_MIGRATION_APPROVED"
APPROVAL_ENV_VALUE = "source_hash_change"
DEFAULT_DRY_RUN_LIMIT = 20
DEFAULT_APPLY_LIMIT = 1
MAX_APPLY_LIMIT = 10


@dataclass
class PacketYamlSidecarMigrationApplyResult:
    ok: bool
    dry_run: bool
    apply: bool
    packet_root: str
    project: str
    stale_only: bool = False
    packet_ids: list[str] = field(default_factory=list)
    limit: int = DEFAULT_DRY_RUN_LIMIT
    apply_limit: int = MAX_APPLY_LIMIT
    packets_total: int = 0
    plan_count: int = 0
    selected_count: int = 0
    selected_items: list[dict[str, Any]] = field(default_factory=list)
    selected_items_truncated: bool = False
    selected_risk_counts: dict[str, int] = field(default_factory=dict)
    source_hash_change_count: int = 0
    source_hash_change_approval_required: bool = False
    plan_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    source_mutations: list[str] = field(default_factory=list)
    markdown_mutations: list[str] = field(default_factory=list)
    registry_mutations: list[str] = field(default_factory=list)
    prefect_runs_created: int = 0
    live_agents_started: int = 0

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert the migration apply result into a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _unique_packet_ids(packet_ids: list[str] | None) -> list[str]:
    if not packet_ids:
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for packet_id in packet_ids:
        normalized = str(packet_id).strip()
        if normalized and normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)
    return unique


def _resolve_limit(limit: int | None, *, apply: bool) -> tuple[int, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if limit is None:
        return (DEFAULT_APPLY_LIMIT if apply else DEFAULT_DRY_RUN_LIMIT), errors
    if limit < 0:
        errors.append(_issue("LIMIT_INVALID", "--limit must be greater than or equal to 0", limit=limit))
        return 0, errors
    if apply and limit > MAX_APPLY_LIMIT:
        errors.append(
            _issue(
                "APPLY_LIMIT_TOO_HIGH",
                f"--limit for apply must be <= {MAX_APPLY_LIMIT}",
                limit=limit,
                max_apply_limit=MAX_APPLY_LIMIT,
            )
        )
    if not apply:
        return min(limit, MAX_ITEM_LIMIT), errors
    return limit, errors


def _select_items(
    items: list[dict[str, Any]],
    *,
    stale_only: bool,
    packet_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    packet_id_set = set(packet_ids)
    selected: list[dict[str, Any]] = []
    planned_by_id = {str(item.get("packet_id") or ""): item for item in items}

    if not stale_only and not packet_ids:
        return selected, errors

    for item in items:
        item_packet_id = str(item.get("packet_id") or "")
        if packet_id_set and item_packet_id not in packet_id_set:
            continue
        if stale_only and item.get("planned_action") != "update":
            continue
        selected.append(item)

    if packet_ids:
        selected_ids = {str(item.get("packet_id") or "") for item in selected}
        for packet_id in packet_ids:
            planned = planned_by_id.get(packet_id)
            if planned is None:
                continue
            if stale_only and packet_id not in selected_ids:
                errors.append(
                    _issue(
                        "SELECTED_PACKET_NOT_STALE",
                        "Selected packet is not a stale sidecar update under --stale-only",
                        packet_id=packet_id,
                        planned_action=planned.get("planned_action"),
                    )
                )
    return selected, errors


def _selected_invalid_sidecar_errors(
    findings: list[dict[str, Any]],
    *,
    packet_ids: list[str],
) -> tuple[set[str], list[dict[str, Any]]]:
    invalid_packet_ids: set[str] = set()
    errors: list[dict[str, Any]] = []
    packet_id_set = set(packet_ids)
    if not packet_id_set:
        return invalid_packet_ids, errors

    for finding in findings:
        if finding.get("classification") != "invalid_sidecar":
            continue
        packet_id = str(finding.get("packet_id") or "")
        if packet_id and packet_id in packet_id_set:
            invalid_packet_ids.add(packet_id)
            errors.append(
                _issue(
                    "SELECTED_PACKET_INVALID_SIDECAR",
                    "Selected packet has an invalid existing EXECUTION_PACKET.yaml sidecar",
                    packet_id=packet_id,
                    sidecar_path=finding.get("sidecar_path"),
                    reason=finding.get("reason"),
                )
            )
    return invalid_packet_ids, errors


def _missing_packet_id_errors(
    items: list[dict[str, Any]],
    invalid_packet_ids: set[str],
    *,
    packet_ids: list[str],
) -> list[dict[str, Any]]:
    if not packet_ids:
        return []
    planned_ids = {str(item.get("packet_id") or "") for item in items}
    errors: list[dict[str, Any]] = []
    for packet_id in packet_ids:
        if packet_id in planned_ids or packet_id in invalid_packet_ids:
            continue
        errors.append(
            _issue(
                "SELECTED_PACKET_NOT_PLANNED",
                "Selected packet id is not in the sidecar migration plan",
                packet_id=packet_id,
            )
        )
    return errors


def _bounded_items(items: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    if limit < 0:
        return [], bool(items)
    return items[:limit], len(items) > limit


def _sync_selected_sidecars(items: list[dict[str, Any]], *, apply: bool) -> tuple[list[str], list[dict[str, Any]]]:
    packet_paths = [str(item["packet_path"]) for item in items]
    if not packet_paths:
        return [], []

    preflight = sync_packet_yaml_sidecars(packet_paths, apply=False)
    if not preflight.ok:
        return [], [
            _issue(
                "APPLY_PREFLIGHT_FAILED",
                "Selected sidecars failed sync preflight; no writes were attempted",
                sync_errors=preflight.errors,
            )
        ]

    applied = sync_packet_yaml_sidecars(packet_paths, apply=apply)
    if not applied.ok:
        return applied.writes, [
            _issue(
                "APPLY_WRITE_FAILED",
                "Selected sidecar sync failed during apply",
                sync_errors=applied.errors,
            )
        ]
    return applied.writes, []


# START_FUNCTION_CONTRACT
# name: apply_packet_yaml_sidecar_migration
# purpose: Plan or apply selected YAML sidecar migrations with source-hash approval gates.
# inputs:
#   packet_root: root directory to scan for EXECUTION_PACKET.md files.
#   project: project.yaml path used for registry-aware planning.
#   stale_only: select only stale sidecar update plan items.
#   packet_ids: explicit packet ids to select; combined with stale_only as an additional filter.
#   apply: when true, write selected sidecars after all gates pass.
#   limit: dry-run display limit or apply hard item limit.
#   understand_source_hash_change: operator acknowledgement flag.
#   approval_token: environment approval value for source-hash-changing apply.
# returns: PacketYamlSidecarMigrationApplyResult with bounded selected plan and writes.
# side_effects: Writes adjacent EXECUTION_PACKET.yaml sidecars only when apply=True and gates pass.
# emitted_logs: None.
# error_behavior: Returns ok=False with errors and no writes for unsafe selections.
# END_FUNCTION_CONTRACT
def apply_packet_yaml_sidecar_migration(
    packet_root: str | Path = Path("prefect_grace/packets"),
    *,
    project: str | Path = Path("prefect_grace/project.yaml"),
    stale_only: bool = False,
    packet_ids: list[str] | None = None,
    apply: bool = False,
    limit: int | None = None,
    understand_source_hash_change: bool = False,
    approval_token: str | None = None,
) -> PacketYamlSidecarMigrationApplyResult:
    normalized_packet_ids = _unique_packet_ids(packet_ids)
    effective_limit, errors = _resolve_limit(limit, apply=apply)
    warnings: list[dict[str, Any]] = []

    if not stale_only and not normalized_packet_ids:
        errors.append(
            _issue(
                "SELECTION_REQUIRED",
                "Select --stale-only or at least one --packet-id; unfiltered migration apply is forbidden",
            )
        )

    plan = plan_packet_yaml_sidecar_migration(packet_root, project=project, limit=MAX_ITEM_LIMIT)
    warnings.extend(plan.warnings)
    if plan.items_truncated:
        warning = _issue(
            "PLAN_ITEMS_TRUNCATED",
            "Planner returned truncated items; narrow --packet-root before applying",
            full_item_count=plan.full_item_count,
            displayed_item_count=len(plan.items),
        )
        warnings.append(warning)
        if apply:
            errors.append(warning)
    if not plan.ok:
        errors.extend(plan.errors)

    selected_items, selection_errors = _select_items(
        plan.items,
        stale_only=stale_only,
        packet_ids=normalized_packet_ids,
    )
    errors.extend(selection_errors)
    invalid_packet_ids, invalid_errors = _selected_invalid_sidecar_errors(
        plan.findings,
        packet_ids=normalized_packet_ids,
    )
    errors.extend(invalid_errors)
    errors.extend(
        _missing_packet_id_errors(
            plan.items,
            invalid_packet_ids,
            packet_ids=normalized_packet_ids,
        )
    )

    selected_count = len(selected_items)
    selected_risk_counts = dict(sorted(Counter(str(item["risk"]) for item in selected_items).items()))
    source_hash_change_count = sum(1 for item in selected_items if bool(item.get("source_hash_changes")))
    source_hash_change_approval_required = bool(apply and source_hash_change_count)

    if apply and selected_count > effective_limit:
        errors.append(
            _issue(
                "APPLY_LIMIT_EXCEEDED",
                "Selected migration items exceed --limit; no writes were attempted",
                selected_count=selected_count,
                limit=effective_limit,
            )
        )
    if source_hash_change_approval_required and not understand_source_hash_change:
        errors.append(
            _issue(
                "SOURCE_HASH_CHANGE_ACK_REQUIRED",
                "--i-understand-source-hash-change is required for source-hash-changing apply",
                source_hash_change_count=source_hash_change_count,
            )
        )
    if source_hash_change_approval_required and approval_token != APPROVAL_ENV_VALUE:
        errors.append(
            _issue(
                "SOURCE_HASH_CHANGE_APPROVAL_REQUIRED",
                f"{APPROVAL_ENV_NAME}={APPROVAL_ENV_VALUE} is required for source-hash-changing apply",
                source_hash_change_count=source_hash_change_count,
            )
        )

    writes: list[str] = []
    if apply and not errors:
        writes, write_errors = _sync_selected_sidecars(selected_items, apply=True)
        errors.extend(write_errors)

    bounded_selected_items, selected_items_truncated = _bounded_items(selected_items, effective_limit)
    return PacketYamlSidecarMigrationApplyResult(
        ok=not errors,
        dry_run=not apply,
        apply=apply,
        packet_root=str(packet_root),
        project=str(project),
        stale_only=stale_only,
        packet_ids=normalized_packet_ids,
        limit=effective_limit,
        apply_limit=MAX_APPLY_LIMIT,
        packets_total=plan.packets_total,
        plan_count=plan.plan_count,
        selected_count=selected_count,
        selected_items=bounded_selected_items,
        selected_items_truncated=selected_items_truncated,
        selected_risk_counts=selected_risk_counts,
        source_hash_change_count=source_hash_change_count,
        source_hash_change_approval_required=source_hash_change_approval_required,
        plan_counts=plan.counts,
        warnings=warnings,
        errors=errors,
        writes=writes,
        source_mutations=list(writes),
        markdown_mutations=[],
        registry_mutations=[],
        prefect_runs_created=0,
        live_agents_started=0,
    )
