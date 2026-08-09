from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from grace_control.core.uid import generate_unique_id, new_packet_uid
from grace_control.db.schema import Event, Feature, Packet, PacketState, Wave
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("rework_packet_service")

RUNTIME_FAILURE_CODES = frozenset({
    "auth_error",
    "timeout",
    "worktree_missing",
    "not_git",
    "AGENT_WORKTREE_NOT_GIT",
    "AGENT_NO_CHANGES_PRODUCED",
    "AGENT_DIFF_INSPECTION_FAILED",
    "AGENT_CHANGED_OUT_OF_SCOPE",
})

REWORK_ORIGINS = frozenset({"review_rework", "architect_repack"})
REPACKABLE_TERMINAL_STATES = frozenset({
    PacketState.FAILED.value,
    PacketState.BLOCKED_FINAL.value,
    PacketState.BLOCKED.value,
    PacketState.CANCELLED.value,
})
VERIFICATION_STAGES = frozenset({
    "t0", "t1", "t2", "t2_browser", "t2_a11y", "t3_visual",
})


class ArchitectRepackValidationError(ValueError):
    """Raised when an architect repack would weaken or corrupt a packet contract."""


class ArchitectRepackConflictError(ValueError):
    """Raised when a packet already has a different active replacement child."""


def _is_runtime_failure(result_json: dict[str, Any] | None) -> bool:
    if not result_json:
        return False
    diagnostics = result_json.get("diagnostics") or {}
    failure_code = diagnostics.get("failure_code", "") or result_json.get("failure_code", "")
    if failure_code in RUNTIME_FAILURE_CODES:
        return True
    return False


# START_FUNCTION_CONTRACT
# name: create_rework_packet
# purpose: Create a ready replacement packet while preserving the source contract.
# inputs: Original packet identity/specification, verdict context, and optional lineage origin/prompt.
# returns: Persisted-ready Packet ORM object attached to the caller's DB session.
# side_effects: Adds a Packet row and emits rework_packet_created.
# emitted_logs: rework_packet_created.
# error_behavior: Propagates DB/UID errors; callers own commit/rollback.
# END_FUNCTION_CONTRACT
def create_rework_packet(
    db,
    *,
    original_packet_id: str,
    feature_id: str,
    wave_id: str,
    original_spec: dict[str, Any],
    acceptance_profile: str,
    title: str,
    slug: str,
    max_attempts: int,
    verdict_source: str,
    summary: str,
    blocking_issues: list[str],
    coder_instructions: list[str] | None = None,
    origin: str = "review_rework",
    rework_prompt: str | None = None,
    rework_base_sha: str = "",
    parent_attempt_count: int = 1,
) -> Packet:
    pkt_id = generate_unique_id(db, Packet, new_packet_uid)

    allowed_write_scope = original_spec.get("scope", []) or original_spec.get("allowed_write_scope", [])
    frozen_scope = original_spec.get("frozen_scope", [])

    if not allowed_write_scope:
        allowed_write_scope = original_spec.get("allowed_paths", ["src/grace_control/"])
    if not frozen_scope:
        frozen_scope = original_spec.get("restricted_paths",
                                          original_spec.get("forbidden_paths", ["docs/archived/"]))

    # A rework packet is a replacement execution of the same contract, not a
    # weaker ad-hoc task.  Preserve exact verification, evidence, dependencies,
    # acceptance criteria, target/workspace settings, and any spec-specific
    # fields; replace only lineage and rework instructions.
    rework_spec: dict[str, Any] = deepcopy(original_spec)
    original_instructions = original_spec.get("coder_instructions", [])
    if isinstance(original_instructions, str):
        original_instructions = [original_instructions]
    merged_instructions = list(dict.fromkeys([
        *original_instructions,
        *(coder_instructions or []),
    ]))
    title_prefix = "Repack" if origin == "architect_repack" else "Rework"
    try:
        parent_ladder_base = max(int(original_spec.get("coder_ladder_base_attempt", 1)), 1)
    except (TypeError, ValueError):
        parent_ladder_base = 1
    coder_ladder_base_attempt = parent_ladder_base + max(int(parent_attempt_count), 1)
    rework_spec.update({
        "origin": origin,
        "parent_packet_id": original_packet_id,
        "original_packet_id": original_spec.get("original_packet_id", original_packet_id),
        "title": f"{title_prefix}: {title}",
        "description": f"{title_prefix} replacement for {original_packet_id}",
        "scope": allowed_write_scope,
        "frozen_scope": frozen_scope,
        "priority": "immediate",
        "acceptance_profile": acceptance_profile,
        "conflict_keys": original_spec.get("conflict_keys", []),
        "rework_source": verdict_source,
        "rework_summary": summary,
        "coder_ladder_base_attempt": coder_ladder_base_attempt,
        "blocking_issues": blocking_issues,
        "coder_instructions": merged_instructions,
        "rework_prompt": rework_prompt or (
            "This is a review rework packet.\n"
            "Do not redesign.\n"
            "Only fix the reviewer blocking issues.\n"
            "Stay inside allowed scope.\n"
            "Preserve original intent."
        ),
    })
    if rework_base_sha:
        rework_spec["rework_base_sha"] = rework_base_sha
    # Runtime-only retry selectors must not leak into a fresh rework chain.
    rework_spec.pop("recovery", None)
    rework_spec.pop("rerun_stage", None)
    rework_spec.pop("architect_repair", None)

    packet = Packet(
        id=pkt_id,
        feature_id=feature_id,
        wave_id=wave_id,
        slug=f"{slug}-rework",
        title=f"{title_prefix}: {title}",
        spec_json=rework_spec,
        state=PacketState.READY.value,
        acceptance_profile=acceptance_profile,
        attempt_count=0,
        max_attempts=max_attempts,
    )
    db.add(packet)

    _log.info("rework_packet_created",
              original_packet_id=original_packet_id,
              rework_packet_id=pkt_id,
              verdict_source=verdict_source,
              summary=summary[:200] if summary else "")

    return packet


# START_FUNCTION_CONTRACT
# name: is_rework_spec
# purpose: Identify packet specifications that participate in replacement lineage.
# inputs: spec — packet specification mapping or malformed/empty value.
# returns: True for supported review-rework or architect-repack origins.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed values return False.
# END_FUNCTION_CONTRACT
def is_rework_spec(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("origin") in REWORK_ORIGINS


def _normalize_replacement_verification(
    original: Any,
    replacement: Any,
) -> dict[str, list[str]]:
    if not isinstance(replacement, dict):
        raise ArchitectRepackValidationError("verification must be an object")
    unknown_stages = sorted(set(replacement) - VERIFICATION_STAGES)
    if unknown_stages:
        raise ArchitectRepackValidationError(
            f"unsupported verification stages: {unknown_stages}"
        )

    normalized: dict[str, list[str]] = {}
    for stage, commands in replacement.items():
        if not isinstance(commands, list):
            raise ArchitectRepackValidationError(
                f"verification.{stage} must be a command list"
            )
        normalized_commands: list[str] = []
        for command in commands:
            if not isinstance(command, str) or not command.strip():
                raise ArchitectRepackValidationError(
                    f"verification.{stage} contains an empty or non-string command"
                )
            if "\x00" in command or len(command) > 16_000:
                raise ArchitectRepackValidationError(
                    f"verification.{stage} contains an invalid or oversized command"
                )
            normalized_commands.append(command.strip())
        if len(normalized_commands) > 20:
            raise ArchitectRepackValidationError(
                f"verification.{stage} exceeds 20 commands"
            )
        normalized[stage] = normalized_commands

    if isinstance(original, dict):
        for stage, original_commands in original.items():
            if stage not in VERIFICATION_STAGES or not original_commands:
                continue
            original_count = len(original_commands) if isinstance(original_commands, list) else 1
            replacement_count = len(normalized.get(stage, []))
            if replacement_count < original_count:
                raise ArchitectRepackValidationError(
                    f"verification.{stage} cannot remove gates "
                    f"({replacement_count} replacement commands for {original_count} original commands)"
                )
    if not any(normalized.values()):
        raise ArchitectRepackValidationError("verification cannot be empty")
    return normalized


def _normalize_replacement_paths(
    original: Any,
    replacement: Any,
    *,
    field_name: str,
    allow_empty: bool,
    require_original: bool,
) -> list[str]:
    source = original if replacement is None else replacement
    if not isinstance(source, list):
        raise ArchitectRepackValidationError(f"{field_name} must be a path list")
    normalized: list[str] = []
    for value in source:
        if not isinstance(value, str) or not value.strip():
            raise ArchitectRepackValidationError(
                f"{field_name} contains an empty or non-string path"
            )
        path = value.strip().replace("\\", "/")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts or path in {".", ""}:
            raise ArchitectRepackValidationError(
                f"{field_name} contains a non-canonical path: {value}"
            )
        if path not in normalized:
            normalized.append(path)
    if not normalized and not allow_empty:
        raise ArchitectRepackValidationError(f"{field_name} cannot be empty")
    if require_original:
        original_paths = {
            value.strip().replace("\\", "/")
            for value in original
            if isinstance(value, str) and value.strip()
        } if isinstance(original, list) else set()
        removed = sorted(original_paths - set(normalized))
        if removed:
            raise ArchitectRepackValidationError(
                f"{field_name} cannot remove original paths: {removed}"
            )
    return normalized


def _normalize_replacement_evidence(
    original: Any,
    replacement: Any,
) -> list[dict[str, Any]]:
    source = original if replacement is None else replacement
    if not isinstance(source, list):
        raise ArchitectRepackValidationError(
            "expected_evidence must be an evidence list"
        )
    if not source:
        if isinstance(original, list) and original:
            raise ArchitectRepackValidationError(
                "expected_evidence cannot remove all original requirements"
            )
        return []
    if len(source) > 100:
        raise ArchitectRepackValidationError(
            "expected_evidence exceeds 100 requirements"
        )

    normalized: list[dict[str, Any]] = []
    replacement_by_id: dict[str, dict[str, Any]] = {}
    for value in source:
        if not isinstance(value, dict):
            raise ArchitectRepackValidationError(
                "expected_evidence contains a non-object requirement"
            )
        requirement = deepcopy(value)
        evidence_id = requirement.get("id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ArchitectRepackValidationError(
                "expected_evidence contains a requirement without an id"
            )
        evidence_id = evidence_id.strip()
        if evidence_id in replacement_by_id:
            raise ArchitectRepackValidationError(
                f"expected_evidence contains duplicate id: {evidence_id}"
            )
        requirement["id"] = evidence_id
        replacement_by_id[evidence_id] = requirement
        normalized.append(requirement)

    if isinstance(original, list):
        original_by_id = {
            value.get("id"): value
            for value in original
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        }
        removed = sorted(set(original_by_id) - set(replacement_by_id))
        if removed:
            raise ArchitectRepackValidationError(
                f"expected_evidence cannot remove original ids: {removed}"
            )
        for evidence_id, original_requirement in original_by_id.items():
            replacement_requirement = replacement_by_id[evidence_id]
            if original_requirement.get("required", True) and not replacement_requirement.get(
                "required", True
            ):
                raise ArchitectRepackValidationError(
                    f"expected_evidence cannot make required evidence optional: {evidence_id}"
                )
            if original_requirement.get(
                "coder_blocking", True
            ) and not replacement_requirement.get("coder_blocking", True):
                raise ArchitectRepackValidationError(
                    f"expected_evidence cannot weaken coder blocking: {evidence_id}"
                )
    return normalized


def _repack_fingerprint(
    verification: dict[str, list[str]],
    reason: str,
    coder_instructions: list[str],
    scope: list[str],
    frozen_scope: list[str],
    expected_evidence: list[dict[str, Any]],
) -> str:
    payload = {
        "verification": verification,
        "reason": reason,
        "coder_instructions": coder_instructions,
        "scope": scope,
        "frozen_scope": frozen_scope,
        "expected_evidence": expected_evidence,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_repackable_packet(packet: Packet) -> bool:
    if packet.state in REPACKABLE_TERMINAL_STATES:
        return True
    return (
        packet.state == PacketState.REJECTED.value
        and (packet.attempt_count or 0) >= (packet.max_attempts or 0)
    )


def _requeue_feature_for_repack(db, packet: Packet) -> None:
    feature = db.query(Feature).filter_by(id=packet.feature_id).first()
    if feature is not None and feature.status != "active":
        feature.status = "queued"
        feature.degraded_reason = None
    wave = db.query(Wave).filter_by(id=packet.wave_id).first()
    if wave is not None:
        wave.status = "IN_PROGRESS"


# START_FUNCTION_CONTRACT
# name: create_architect_repack_packet
# purpose: Create an audited replacement for a terminal packet whose execution contract is inconsistent.
# inputs: db, original packet id, complete replacement verification, reason, bounded coder instructions, and optional architect-approved scope/frozen-scope paths.
# returns: Tuple of replacement Packet and created flag; exact repeated requests are idempotent.
# side_effects: Adds Packet/Event rows and emits architect_repack_created or architect_repack_reused.
# emitted_logs: architect_repack_created, architect_repack_reused.
# error_behavior: Raises ArchitectRepackValidationError for unsafe requests, ArchitectRepackConflictError for competing lineage, or LookupError when the packet is absent.
# END_FUNCTION_CONTRACT
def create_architect_repack_packet(
    db,
    *,
    original_packet_id: str,
    verification: dict[str, list[str]],
    reason: str,
    coder_instructions: list[str] | None = None,
    scope: list[str] | None = None,
    frozen_scope: list[str] | None = None,
    expected_evidence: list[dict[str, Any]] | None = None,
) -> tuple[Packet, bool]:
    original = db.query(Packet).filter_by(id=original_packet_id).first()
    if original is None:
        raise LookupError(f"Packet not found: {original_packet_id}")
    if not _is_repackable_packet(original):
        raise ArchitectRepackValidationError(
            "architect repack requires failed/blocked or exhausted rejected packet, "
            f"got {original.state} at {original.attempt_count}/{original.max_attempts} attempts"
        )

    normalized_reason = reason.strip()
    if len(normalized_reason) < 10:
        raise ArchitectRepackValidationError("reason must contain at least 10 characters")
    instructions = [item.strip() for item in (coder_instructions or []) if item.strip()]
    if len(instructions) > 20 or any(len(item) > 4_000 for item in instructions):
        raise ArchitectRepackValidationError("coder_instructions exceed safe bounds")

    original_spec = deepcopy(original.spec_json) if isinstance(original.spec_json, dict) else {}
    normalized_verification = _normalize_replacement_verification(
        original_spec.get("verification", {}), verification,
    )
    normalized_scope = _normalize_replacement_paths(
        original_spec.get("scope", original_spec.get("allowed_write_scope", [])),
        scope,
        field_name="scope",
        allow_empty=False,
        require_original=True,
    )
    normalized_frozen_scope = _normalize_replacement_paths(
        original_spec.get("frozen_scope", []),
        frozen_scope,
        field_name="frozen_scope",
        allow_empty=True,
        require_original=False,
    )
    normalized_expected_evidence = _normalize_replacement_evidence(
        original_spec.get("expected_evidence", []),
        expected_evidence,
    )
    fingerprint = _repack_fingerprint(
        normalized_verification,
        normalized_reason,
        instructions,
        normalized_scope,
        normalized_frozen_scope,
        normalized_expected_evidence,
    )

    feature_packets = db.query(Packet).filter_by(feature_id=original.feature_id).all()
    for candidate in feature_packets:
        candidate_spec = candidate.spec_json if isinstance(candidate.spec_json, dict) else {}
        if (
            is_rework_spec(candidate_spec)
            and candidate_spec.get("parent_packet_id") == original.id
            and candidate.state != PacketState.CANCELLED.value
        ):
            if (
                candidate_spec.get("rework_source") == "architect_repack"
                and candidate_spec.get("architect_repack_fingerprint") == fingerprint
            ):
                _log.info(
                    "architect_repack_reused",
                    original_packet_id=original.id,
                    rework_packet_id=candidate.id,
                )
                _requeue_feature_for_repack(db, candidate)
                return candidate, False
            raise ArchitectRepackConflictError(
                f"Packet {original.id} already has active replacement {candidate.id}"
            )

    replacement_spec = deepcopy(original_spec)
    replacement_spec["verification"] = normalized_verification
    replacement_spec["scope"] = normalized_scope
    replacement_spec["frozen_scope"] = normalized_frozen_scope
    replacement_spec["expected_evidence"] = normalized_expected_evidence
    replacement_spec["architect_repack_fingerprint"] = fingerprint
    replacement_spec["architect_repack_reason"] = normalized_reason
    replacement_spec["rework_kind"] = "contract_repack"

    from grace_control.core.contracts import (
        ScopeContractError,
        build_packet_contract,
        validate_packet_contract,
    )

    try:
        contract = build_packet_contract({
            "id": original.id,
            "title": original.title,
            "acceptance_profile": original.acceptance_profile,
            "spec_json": replacement_spec,
        })
    except ScopeContractError as exc:
        raise ArchitectRepackValidationError(str(exc)) from exc
    contract_errors = validate_packet_contract(contract)
    if contract_errors:
        raise ArchitectRepackValidationError("; ".join(contract_errors))

    replacement = create_rework_packet(
        db,
        original_packet_id=original.id,
        feature_id=original.feature_id,
        wave_id=original.wave_id,
        original_spec=replacement_spec,
        acceptance_profile=original.acceptance_profile or "NORMAL",
        title=original.title or "",
        slug=original.slug or "",
        max_attempts=original.max_attempts or 3,
        verdict_source="architect_repack",
        summary=normalized_reason,
        blocking_issues=[normalized_reason],
        coder_instructions=instructions,
        # Keep the established replacement-lineage origin for compatibility
        # with older queue/wave-gate consumers.  rework_source/rework_kind
        # distinguish this explicit architect contract repair.
        origin="review_rework",
        parent_attempt_count=original.attempt_count or 1,
        rework_prompt=(
            "This is an architect-approved contract repack.\n"
            "Preserve all acceptance criteria, evidence, scope, and feature intent.\n"
            "Use the replacement verification commands because the original commands "
            "or scope conflicted with the required implementation.\n"
            "Do not redesign beyond the architect-approved replacement scope."
        ),
    )
    db.add(Event(
        event_type="architect_repack_created",
        entity_type="packet",
        entity_id=replacement.id,
        payload_json={
            "parent_packet_id": original.id,
            "reason": normalized_reason,
            "fingerprint": fingerprint,
        },
        timestamp=datetime.now(UTC),
    ))
    _requeue_feature_for_repack(db, replacement)
    _log.info(
        "architect_repack_created",
        original_packet_id=original.id,
        rework_packet_id=replacement.id,
    )
    return replacement, True


# START_FUNCTION_CONTRACT
# name: effective_rework_packets
# purpose: Resolve a packet collection to the active leaves of review-rework lineages.
# inputs: packets — packet ORM objects from one feature or wave.
# returns: Packets whose ids are not superseded by a non-cancelled rework child.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed lineage metadata is ignored conservatively.
# END_FUNCTION_CONTRACT
def effective_rework_packets(packets: list[Packet]) -> list[Packet]:
    """Return active lineage leaves while retaining all unrelated packets."""
    superseded_ids: set[str] = set()
    for packet in packets:
        spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
        parent_id = spec.get("parent_packet_id", "")
        if (
            is_rework_spec(spec)
            and isinstance(parent_id, str)
            and parent_id
            and packet.state != PacketState.CANCELLED.value
        ):
            superseded_ids.add(parent_id)
    return [packet for packet in packets if packet.id not in superseded_ids]


# START_FUNCTION_CONTRACT
# name: resolve_rework_spec
# purpose: Restore the complete inherited execution contract for a rework packet.
# inputs: db — active ORM session; packet — packet whose lineage is resolved.
# returns: Deep-copied packet spec with parent contracts and child rework metadata merged.
# side_effects: Database reads only.
# emitted_logs: rework_parent_not_found, rework_lineage_cycle.
# error_behavior: Missing or malformed parents stop inheritance and retain the safest known spec.
# END_FUNCTION_CONTRACT
def resolve_rework_spec(db, packet: Packet) -> dict[str, Any]:
    """Resolve stale and current review-rework specs without weakening contracts."""
    chain: list[dict[str, Any]] = []
    current = packet
    seen: set[str] = set()
    cycle_packet_id = ""
    while current is not None:
        if current.id in seen:
            cycle_packet_id = current.id
            break
        seen.add(current.id)
        spec = deepcopy(current.spec_json) if isinstance(current.spec_json, dict) else {}
        chain.append(spec)
        if not is_rework_spec(spec):
            break
        parent_id = spec.get("parent_packet_id", "")
        if not isinstance(parent_id, str) or not parent_id:
            break
        current = db.query(Packet).filter_by(id=parent_id).first()
        if current is None:
            _log.warn(
                "rework_parent_not_found",
                packet_id=packet.id,
                parent_packet_id=parent_id,
            )
            break
    if cycle_packet_id:
        _log.warn(
            "rework_lineage_cycle",
            packet_id=packet.id,
            repeated_packet_id=cycle_packet_id,
        )

    resolved: dict[str, Any] = {}
    merged_instructions: list[str] = []
    for spec in reversed(chain):
        instructions = spec.get("coder_instructions", [])
        if isinstance(instructions, str):
            instructions = [instructions]
        if isinstance(instructions, list):
            merged_instructions.extend(str(item) for item in instructions)
        resolved.update(spec)
    leaf_spec = chain[0] if chain else {}
    if is_rework_spec(leaf_spec):
        # Runtime recovery state belongs to the current packet only.  Missing
        # keys on a fresh child are an inheritance barrier, not permission to
        # replay a parent's coder selector, rerun stage, or architect marker.
        for runtime_key in ("recovery", "rerun_stage", "architect_repair"):
            if runtime_key not in leaf_spec:
                resolved.pop(runtime_key, None)
    if merged_instructions:
        resolved["coder_instructions"] = list(dict.fromkeys(merged_instructions))
    return resolved
