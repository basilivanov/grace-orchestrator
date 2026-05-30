# ############################################################################
# AI_HEADER: packet_yaml_sidecar_migration_plan
# ROLE: Plans read-only EXECUTION_PACKET.yaml sidecar migration source-hash impact.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Produce a bounded JSON migration plan for canonical EXECUTION_PACKET.yaml sidecars.
# inputs: Packet root directory, optional project config, and display item limit.
# returns: PacketYamlSidecarMigrationPlanResult with counts, risks, findings, and capped items.
# side_effects: Reads packet markdown, adjacent sidecars, project config, and runtime registry only.
# emitted_logs: None.
# error_behavior: Fails closed for root scan errors; records packet-level issues as findings.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketYamlSidecarMigrationPlanResult
#   - function: plan_packet_yaml_sidecar_migration
# END_MODULE_MAP

from __future__ import annotations

import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_parser import (
    PACKET_SIDECAR_NAME,
    compute_packet_source_hash,
    load_packet_sidecar_payload,
    packet_to_canonical_sidecar_payload,
    parse_packet_markdown,
)
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore


AUDIT_CLASSES = (
    "canonical",
    "no_sidecar",
    "stale_sidecar",
    "invalid_sidecar",
    "skipped",
)
DEFAULT_ITEM_LIMIT = 20
MAX_ITEM_LIMIT = 100


@dataclass
class PacketYamlSidecarMigrationPlanResult:
    ok: bool
    packet_root: str
    project: str
    project_key: str | None = None
    registry_loaded: bool = False
    packets_total: int = 0
    limit: int = DEFAULT_ITEM_LIMIT
    counts: dict[str, int] = field(default_factory=dict)
    plan_count: int = 0
    full_item_count: int = 0
    risk_counts: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    items_truncated: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)
    full_finding_count: int = 0
    findings_truncated: bool = False
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    source_mutations: list[str] = field(default_factory=list)
    prefect_runs_created: int = 0
    live_agents_started: int = 0

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert the migration plan result into a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _empty_counts() -> dict[str, int]:
    return {class_name: 0 for class_name in AUDIT_CLASSES}


def _bounded_limit(limit: int) -> int:
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0")
    return min(limit, MAX_ITEM_LIMIT)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _discover_packet_paths(packet_root: Path) -> list[Path]:
    return sorted(path for path in packet_root.rglob("EXECUTION_PACKET.md") if path.is_file())


def _load_registry_statuses(project: Path | str) -> tuple[dict[str, str], str | None, bool, list[dict[str, Any]]]:
    try:
        adapter = load_project_adapter(project)
        registry = PacketRegistryStore(Path(adapter.runtime_state_root) / "state")
        statuses: dict[str, str] = {}
        for record in registry.list_packets(adapter.project_key):
            packet_id = str(record.get("packet_id") or "").strip()
            if not packet_id:
                continue
            status = str(record.get("registry_status") or record.get("status") or "").strip()
            statuses[packet_id] = status
        return statuses, adapter.project_key, True, []
    except Exception as exc:
        warning = _issue(
            "PROJECT_CONFIG_UNAVAILABLE",
            f"Project config could not be loaded; registry_status will be null: {exc}",
            project=str(project),
        )
        return {}, None, False, [warning]


def _desired_payload_from_markdown(content: str) -> dict[str, Any]:
    parsed_markdown_only = parse_packet_markdown(content, mode="strict")
    return packet_to_canonical_sidecar_payload(parsed_markdown_only)


def _risk_for(registry_status: str | None, source_hash_changes: bool) -> str:
    if not registry_status:
        return "no_registry_entry"
    if source_hash_changes and registry_status == "accepted":
        return "accepted_source_hash_change"
    if source_hash_changes:
        return "non_terminal_source_hash_change"
    return "no_source_hash_change"


def _finding(
    *,
    classification: str,
    packet_path: Path,
    sidecar_path: Path,
    packet_id: str = "",
    reason: str,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "packet_id": packet_id,
        "packet_path": str(packet_path),
        "sidecar_path": str(sidecar_path),
        "reason": reason,
    }


def _plan_item(
    *,
    packet_path: Path,
    sidecar_path: Path,
    packet_id: str,
    planned_action: str,
    registry_status: str | None,
    current_source_hash: str,
    planned_source_hash: str,
) -> dict[str, Any]:
    source_hash_changes = current_source_hash != planned_source_hash
    risk = _risk_for(registry_status, source_hash_changes)
    return {
        "packet_id": packet_id,
        "packet_path": str(packet_path),
        "sidecar_path": str(sidecar_path),
        "planned_action": planned_action,
        "registry_status": registry_status,
        "current_source_hash": current_source_hash,
        "planned_source_hash": planned_source_hash,
        "source_hash_changes": source_hash_changes,
        "risk": risk,
    }


def _root_error_result(
    *,
    root: Path,
    project: Path | str,
    limit: int,
    error: dict[str, Any],
) -> PacketYamlSidecarMigrationPlanResult:
    return PacketYamlSidecarMigrationPlanResult(
        ok=False,
        packet_root=str(root),
        project=str(project),
        limit=limit,
        counts=_empty_counts(),
        errors=[error],
    )


# START_FUNCTION_CONTRACT
# name: plan_packet_yaml_sidecar_migration
# purpose: Plan canonical YAML sidecar create/update impact without writing files.
# inputs:
#   packet_root: root directory to search under.
#   project: project.yaml path used to read runtime registry status.
#   limit: maximum displayed plan items/findings, capped at 100.
# returns: PacketYamlSidecarMigrationPlanResult with bounded migration plan and findings.
# side_effects: Reads files only; never writes sidecars, source files, runtime state, or Prefect runs.
# emitted_logs: None.
# error_behavior: Returns ok=False for root-level failures and ok=True for completed scans.
# END_FUNCTION_CONTRACT
def plan_packet_yaml_sidecar_migration(
    packet_root: str | Path = Path("prefect_grace/packets"),
    *,
    project: str | Path = Path("prefect_grace/project.yaml"),
    limit: int = DEFAULT_ITEM_LIMIT,
) -> PacketYamlSidecarMigrationPlanResult:
    root = Path(packet_root)
    project_path = Path(project)
    capped_limit = _bounded_limit(limit)
    counts = _empty_counts()

    if not root.exists():
        return _root_error_result(
            root=root,
            project=project_path,
            limit=capped_limit,
            error=_issue("PACKET_ROOT_NOT_FOUND", f"Packet root not found: {root}", packet_root=str(root)),
        )
    if not root.is_dir():
        return _root_error_result(
            root=root,
            project=project_path,
            limit=capped_limit,
            error=_issue("PACKET_ROOT_NOT_DIRECTORY", f"Packet root is not a directory: {root}", packet_root=str(root)),
        )
    if not os.access(root, os.R_OK | os.X_OK):
        return _root_error_result(
            root=root,
            project=project_path,
            limit=capped_limit,
            error=_issue("PACKET_ROOT_UNREADABLE", f"Packet root is not readable: {root}", packet_root=str(root)),
        )

    try:
        packet_paths = _discover_packet_paths(root)
    except Exception as exc:
        return _root_error_result(
            root=root,
            project=project_path,
            limit=capped_limit,
            error=_issue("PACKET_ROOT_SCAN_FAILED", str(exc), packet_root=str(root)),
        )

    registry_statuses, project_key, registry_loaded, warnings = _load_registry_statuses(project_path)
    all_items: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []

    for packet_path in packet_paths:
        sidecar_path = packet_path.with_name(PACKET_SIDECAR_NAME)
        try:
            content = packet_path.read_text(encoding="utf-8")
        except Exception as exc:
            counts["skipped"] += 1
            all_findings.append(
                _finding(
                    classification="skipped",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    reason=str(exc),
                )
            )
            continue
        try:
            desired_payload = _desired_payload_from_markdown(content)
        except Exception as exc:
            counts["skipped"] += 1
            all_findings.append(
                _finding(
                    classification="skipped",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    reason=str(exc),
                )
            )
            continue

        packet_id = str(desired_payload.get("packet_id") or "")
        planned_source_hash = compute_packet_source_hash(content, desired_payload)
        registry_status = registry_statuses.get(packet_id)

        if not sidecar_path.exists():
            current_source_hash = parse_packet_markdown(content, mode="strict").source_hash
            counts["no_sidecar"] += 1
            all_items.append(
                _plan_item(
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    packet_id=packet_id,
                    planned_action="create",
                    registry_status=registry_status,
                    current_source_hash=current_source_hash,
                    planned_source_hash=planned_source_hash,
                )
            )
            continue

        try:
            existing_payload = load_packet_sidecar_payload(sidecar_path)
            current_parsed = parse_packet_markdown(packet_path, mode="strict")
        except Exception as exc:
            counts["invalid_sidecar"] += 1
            all_findings.append(
                _finding(
                    classification="invalid_sidecar",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    packet_id=packet_id,
                    reason=str(exc),
                )
            )
            continue

        if existing_payload == desired_payload:
            counts["canonical"] += 1
            continue

        counts["stale_sidecar"] += 1
        all_items.append(
            _plan_item(
                packet_path=packet_path,
                sidecar_path=sidecar_path,
                packet_id=packet_id,
                planned_action="update",
                registry_status=registry_status,
                current_source_hash=current_parsed.source_hash,
                planned_source_hash=planned_source_hash,
            )
        )

    risk_counts = dict(sorted(Counter(str(item["risk"]) for item in all_items).items()))
    return PacketYamlSidecarMigrationPlanResult(
        ok=True,
        packet_root=str(root),
        project=str(project_path),
        project_key=project_key,
        registry_loaded=registry_loaded,
        packets_total=len(packet_paths),
        limit=capped_limit,
        counts=counts,
        plan_count=len(all_items),
        full_item_count=len(all_items),
        risk_counts=risk_counts,
        items=all_items[:capped_limit],
        items_truncated=len(all_items) > capped_limit,
        findings=all_findings[:capped_limit],
        full_finding_count=len(all_findings),
        findings_truncated=len(all_findings) > capped_limit,
        warnings=warnings,
        errors=[],
        writes=[],
        source_mutations=[],
        prefect_runs_created=0,
        live_agents_started=0,
    )
