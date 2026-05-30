# ############################################################################
# AI_HEADER: packet_yaml_sidecar_audit
# ROLE: Audits EXECUTION_PACKET.yaml sidecar state without mutating sources.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Report canonical YAML sidecar state for strict EXECUTION_PACKET.md packets.
# inputs: Packet root directory and report example limit.
# returns: PacketYamlSidecarAuditResult with class counts, bounded examples, and errors.
# side_effects: Reads packet markdown and adjacent sidecars only.
# emitted_logs: None.
# error_behavior: Fails closed for missing/unreadable roots; records packet findings otherwise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketYamlSidecarAuditResult
#   - function: audit_packet_yaml_sidecars
# END_MODULE_MAP

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_parser import (
    PACKET_SIDECAR_NAME,
    load_packet_sidecar_payload,
    packet_to_canonical_sidecar_payload,
    parse_packet_markdown,
)


AUDIT_CLASSES = (
    "canonical",
    "no_sidecar",
    "stale_sidecar",
    "invalid_sidecar",
    "skipped",
)
DEFAULT_EXAMPLE_LIMIT = 20
MAX_EXAMPLE_LIMIT = 100


@dataclass
class PacketYamlSidecarAuditResult:
    ok: bool
    packet_root: str
    packets_total: int = 0
    limit: int = DEFAULT_EXAMPLE_LIMIT
    counts: dict[str, int] = field(default_factory=dict)
    examples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    source_mutations: list[str] = field(default_factory=list)
    prefect_runs_created: int = 0
    live_agents_started: int = 0

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert the audit result into a JSON-safe dictionary.
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


def _empty_examples() -> dict[str, list[dict[str, Any]]]:
    return {class_name: [] for class_name in AUDIT_CLASSES}


def _bounded_limit(limit: int) -> int:
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0")
    return min(limit, MAX_EXAMPLE_LIMIT)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _packet_example(
    *,
    classification: str,
    packet_path: Path,
    sidecar_path: Path,
    packet_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "classification": classification,
        "packet": str(packet_path),
        "sidecar": str(sidecar_path),
        "packet_id": packet_id,
        "reason": reason,
    }


def _record(
    *,
    counts: dict[str, int],
    examples: dict[str, list[dict[str, Any]]],
    limit: int,
    classification: str,
    example: dict[str, Any],
) -> None:
    counts[classification] += 1
    if len(examples[classification]) < limit:
        examples[classification].append(example)


def _build_desired_payload(packet_path: Path) -> dict[str, Any]:
    content = packet_path.read_text(encoding="utf-8")
    parsed_markdown_only = parse_packet_markdown(content, mode="strict")
    return packet_to_canonical_sidecar_payload(parsed_markdown_only)


def _discover_packet_paths(packet_root: Path) -> list[Path]:
    return sorted(path for path in packet_root.rglob("EXECUTION_PACKET.md") if path.is_file())


# START_FUNCTION_CONTRACT
# name: audit_packet_yaml_sidecars
# purpose: Audit adjacent EXECUTION_PACKET.yaml sidecars for strict packet markdown files.
# inputs:
#   packet_root: root directory to search under.
#   limit: maximum examples/errors retained per class, capped at 100.
# returns: PacketYamlSidecarAuditResult with non-mutating audit findings.
# side_effects: Reads files only.
# emitted_logs: None.
# error_behavior: Returns ok=False for root-level failures; packet issues are findings.
# END_FUNCTION_CONTRACT
def audit_packet_yaml_sidecars(
    packet_root: str | Path = Path("prefect_grace/packets"),
    *,
    limit: int = DEFAULT_EXAMPLE_LIMIT,
) -> PacketYamlSidecarAuditResult:
    root = Path(packet_root)
    capped_limit = _bounded_limit(limit)
    counts = _empty_counts()
    examples = _empty_examples()
    errors: list[dict[str, Any]] = []

    if not root.exists():
        errors.append(_error("PACKET_ROOT_NOT_FOUND", f"Packet root not found: {root}", packet_root=str(root)))
        return PacketYamlSidecarAuditResult(
            ok=False,
            packet_root=str(root),
            limit=capped_limit,
            counts=counts,
            examples=examples,
            errors=errors,
        )
    if not root.is_dir():
        errors.append(_error("PACKET_ROOT_NOT_DIRECTORY", f"Packet root is not a directory: {root}", packet_root=str(root)))
        return PacketYamlSidecarAuditResult(
            ok=False,
            packet_root=str(root),
            limit=capped_limit,
            counts=counts,
            examples=examples,
            errors=errors,
        )
    if not os.access(root, os.R_OK | os.X_OK):
        errors.append(_error("PACKET_ROOT_UNREADABLE", f"Packet root is not readable: {root}", packet_root=str(root)))
        return PacketYamlSidecarAuditResult(
            ok=False,
            packet_root=str(root),
            limit=capped_limit,
            counts=counts,
            examples=examples,
            errors=errors,
        )

    try:
        packet_paths = _discover_packet_paths(root)
    except Exception as exc:
        errors.append(_error("PACKET_ROOT_SCAN_FAILED", str(exc), packet_root=str(root)))
        return PacketYamlSidecarAuditResult(
            ok=False,
            packet_root=str(root),
            limit=capped_limit,
            counts=counts,
            examples=examples,
            errors=errors,
        )

    for packet_path in packet_paths:
        sidecar_path = packet_path.with_name(PACKET_SIDECAR_NAME)
        try:
            desired_payload = _build_desired_payload(packet_path)
        except Exception as exc:
            _record(
                counts=counts,
                examples=examples,
                limit=capped_limit,
                classification="skipped",
                example=_packet_example(
                    classification="skipped",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    reason=str(exc),
                ),
            )
            continue

        packet_id = str(desired_payload.get("packet_id") or "")
        if not sidecar_path.exists():
            _record(
                counts=counts,
                examples=examples,
                limit=capped_limit,
                classification="no_sidecar",
                example=_packet_example(
                    classification="no_sidecar",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    packet_id=packet_id,
                    reason="Adjacent EXECUTION_PACKET.yaml is missing",
                ),
            )
            continue

        try:
            existing_payload = load_packet_sidecar_payload(sidecar_path)
            parse_packet_markdown(packet_path, mode="strict")
        except Exception as exc:
            error = _error(
                "INVALID_PACKET_YAML_SIDECAR",
                str(exc),
                packet=str(packet_path),
                sidecar=str(sidecar_path),
                packet_id=packet_id,
            )
            if len(errors) < capped_limit:
                errors.append(error)
            _record(
                counts=counts,
                examples=examples,
                limit=capped_limit,
                classification="invalid_sidecar",
                example=_packet_example(
                    classification="invalid_sidecar",
                    packet_path=packet_path,
                    sidecar_path=sidecar_path,
                    packet_id=packet_id,
                    reason=str(exc),
                ),
            )
            continue

        classification = "canonical" if existing_payload == desired_payload else "stale_sidecar"
        reason = (
            "Adjacent EXECUTION_PACKET.yaml matches canonical payload"
            if classification == "canonical"
            else "Adjacent EXECUTION_PACKET.yaml differs from canonical payload"
        )
        _record(
            counts=counts,
            examples=examples,
            limit=capped_limit,
            classification=classification,
            example=_packet_example(
                classification=classification,
                packet_path=packet_path,
                sidecar_path=sidecar_path,
                packet_id=packet_id,
                reason=reason,
            ),
        )

    return PacketYamlSidecarAuditResult(
        ok=True,
        packet_root=str(root),
        packets_total=len(packet_paths),
        limit=capped_limit,
        counts=counts,
        examples=examples,
        errors=errors,
        writes=[],
        source_mutations=[],
        prefect_runs_created=0,
        live_agents_started=0,
    )
