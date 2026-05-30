# ############################################################################
# AI_HEADER: packet_yaml_sidecar_sync
# ROLE: Plans and applies guarded EXECUTION_PACKET.yaml sidecar synchronization.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate canonical YAML sidecars for explicit execution packet markdown paths.
# inputs: Explicit EXECUTION_PACKET.md paths and dry-run/apply mode.
# returns: PacketYamlSidecarSyncResult containing per-packet plans, writes, and errors.
# side_effects: Writes only adjacent EXECUTION_PACKET.yaml files when apply=True.
# emitted_logs: None.
# error_behavior: Fails closed per packet and never overwrites invalid existing sidecars.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketYamlSidecarSyncResult
#   - function: sync_packet_yaml_sidecars
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_parser import (
    PACKET_SIDECAR_NAME,
    dump_packet_sidecar_payload,
    load_packet_sidecar_payload,
    packet_to_canonical_sidecar_payload,
    parse_packet_markdown,
)


@dataclass
class PacketYamlSidecarSyncResult:
    ok: bool
    dry_run: bool = True
    apply: bool = False
    packets_total: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    markdown_mutations: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert the sync result into a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _packet_result(
    *,
    packet_path: Path,
    sidecar_path: Path | None,
    planned_action: str,
    packet_id: str = "",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "packet": str(packet_path),
        "sidecar": str(sidecar_path) if sidecar_path is not None else "",
        "packet_id": packet_id,
        "planned_action": planned_action,
        "writes": [],
        "markdown_mutations": [],
        "error": error,
    }


def _validate_packet_path(packet_path: Path) -> None:
    if not str(packet_path).strip():
        raise ValueError("Packet path must not be blank")
    if packet_path.name != "EXECUTION_PACKET.md":
        raise ValueError("Packet path basename must be EXECUTION_PACKET.md")
    if not packet_path.exists():
        raise FileNotFoundError(f"Packet file not found: {packet_path}")
    if not packet_path.is_file():
        raise ValueError(f"Packet path is not a file: {packet_path}")


def _build_desired_payload(packet_path: Path) -> dict[str, Any]:
    content = packet_path.read_text(encoding="utf-8")
    parsed_markdown_only = parse_packet_markdown(content, mode="strict")
    return packet_to_canonical_sidecar_payload(parsed_markdown_only)


def _plan_one(packet: str | Path, *, apply: bool) -> tuple[dict[str, Any], list[str], dict[str, Any] | None]:
    if isinstance(packet, str) and not packet.strip():
        error = _error("PACKET_YAML_SIDECAR_SYNC_ERROR", "Packet path must not be blank", packet=packet)
        result = _packet_result(
            packet_path=Path(packet),
            sidecar_path=None,
            planned_action="error",
            error=error,
        )
        return result, [], error

    packet_path = Path(packet)
    sidecar_path: Path | None = None
    try:
        _validate_packet_path(packet_path)
        sidecar_path = packet_path.with_name(PACKET_SIDECAR_NAME)
        desired_payload = _build_desired_payload(packet_path)
        desired_yaml = dump_packet_sidecar_payload(desired_payload)

        if sidecar_path.exists():
            existing_payload = load_packet_sidecar_payload(sidecar_path)
            parse_packet_markdown(packet_path, mode="strict")
            planned_action = "noop" if existing_payload == desired_payload else "update"
        else:
            planned_action = "create"

        result = _packet_result(
            packet_path=packet_path,
            sidecar_path=sidecar_path,
            planned_action=planned_action,
            packet_id=str(desired_payload["packet_id"]),
        )

        writes: list[str] = []
        if apply and planned_action in {"create", "update"}:
            sidecar_path.write_text(desired_yaml, encoding="utf-8")
            writes.append(str(sidecar_path))
            result["writes"] = writes
        return result, writes, None
    except Exception as exc:
        error = _error("PACKET_YAML_SIDECAR_SYNC_ERROR", str(exc), packet=str(packet_path))
        result = _packet_result(
            packet_path=packet_path,
            sidecar_path=sidecar_path,
            planned_action="error",
            error=error,
        )
        return result, [], error


# START_FUNCTION_CONTRACT
# name: sync_packet_yaml_sidecars
# purpose: Plan or apply canonical YAML sidecar synchronization for explicit packets.
# inputs:
#   packets: explicit EXECUTION_PACKET.md paths.
#   apply: when true, write create/update sidecars; otherwise dry-run only.
# returns: PacketYamlSidecarSyncResult with bounded per-packet results.
# side_effects: Writes adjacent EXECUTION_PACKET.yaml files only when apply=True.
# emitted_logs: None.
# error_behavior: Captures per-packet errors and reports ok=False without raising.
# END_FUNCTION_CONTRACT
def sync_packet_yaml_sidecars(
    packets: list[str | Path],
    *,
    apply: bool = False,
) -> PacketYamlSidecarSyncResult:
    results: list[dict[str, Any]] = []
    writes: list[str] = []
    errors: list[dict[str, Any]] = []

    if not packets:
        errors.append(_error("PACKET_REQUIRED", "At least one --packet is required"))

    for packet in packets:
        packet_result, packet_writes, packet_error = _plan_one(packet, apply=apply)
        results.append(packet_result)
        writes.extend(packet_writes)
        if packet_error is not None:
            errors.append(packet_error)

    return PacketYamlSidecarSyncResult(
        ok=not errors,
        dry_run=not apply,
        apply=apply,
        packets_total=len(packets),
        results=results,
        writes=writes,
        markdown_mutations=[],
        errors=errors,
    )
