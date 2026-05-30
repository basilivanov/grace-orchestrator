# ############################################################################
# AI_HEADER: controller_backlog_bootstrap
# ROLE: Deterministic bootstrap planner for GRACE controller packet backlog.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build and optionally apply a safe runtime registry bootstrap plan.
# inputs: ProjectAdapterConfig, strict packet corpus, bounded packet artifacts.
# returns: BacklogBootstrapPlan with candidates, warnings, and errors.
# side_effects: Reads packet files and artifacts; writes registry only in apply mode.
# emitted_logs: None.
# error_behavior: Returns structured errors in the bootstrap plan.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: BacklogBootstrapCandidate
#   - class: BacklogBootstrapPlan
#   - function: dataclass_to_dict
#   - function: summarize_skip_warnings
#   - function: build_backlog_bootstrap_plan
# END_MODULE_MAP

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_artifact_layout import (
    latest_review,
    resolve_packet_layout,
)
from prefect_grace.platform.packet_parser import ParsedPacket, parse_packet_markdown
from prefect_grace.platform.review_artifact_contract import read_review_artifact_status
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.status_model import RegistryStatus, normalize_source_status

#START_BLOCK_MODELS
@dataclass
class BacklogBootstrapCandidate:
    packet_id: str
    source_path: str
    source_hash: str
    current_registry_status: str | None
    inferred_status: str | None
    inference_reason: str
    evidence_paths: list[str] = field(default_factory=list)
    planned_action: str = "noop"
    warnings: list[str] = field(default_factory=list)


@dataclass
class BacklogBootstrapPlan:
    project_key: str
    dry_run: bool
    packet_ids: list[str] = field(default_factory=list)
    candidates: list[BacklogBootstrapCandidate] = field(default_factory=list)
    apply_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class _StrictPacketRecord:
    parsed: ParsedPacket
    source_path: Path
    source_rel_path: str


@dataclass
class _ArtifactInference:
    status: str | None
    reason: str
    evidence_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


#END_BLOCK_MODELS
#START_BLOCK_SERIALIZATION
# START_FUNCTION_CONTRACT
# name: dataclass_to_dict
# purpose: Convert bootstrap dataclass instances into JSON-safe dictionaries.
# inputs:
#   obj: BacklogBootstrapPlan, BacklogBootstrapCandidate, or nested dataclass.
# returns: dict with dataclass fields converted recursively.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Propagates dataclasses.asdict errors for unsupported inputs.
# END_FUNCTION_CONTRACT
def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


#END_BLOCK_SERIALIZATION
#START_BLOCK_WARNING_SUMMARY
def _classify_skip_warning(warning: str) -> str:
    if "missing packet_id=" in warning:
        return "missing_controller_ids"
    if "legacy packet" in warning or "missing strict controller sections" in warning:
        return "legacy_missing_strict_sections"
    if "Failed to parse" in warning:
        return "parse_errors"
    return "other_skips"


# START_FUNCTION_CONTRACT
# name: summarize_skip_warnings
# purpose: Compact large repeated packet skip warning lists into operator-readable classes.
# inputs:
#   warnings: list of warning strings.
#   detail_threshold: maximum warning count to preserve verbatim.
# returns: list of warning strings, either original details or class summaries.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def summarize_skip_warnings(
    warnings: list[str],
    *,
    detail_threshold: int = 20,
) -> list[str]:
    if len(warnings) <= detail_threshold:
        return warnings

    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    passthrough: list[str] = []

    for warning in warnings:
        klass = _classify_skip_warning(warning)
        if klass == "other_skips":
            passthrough.append(warning)
            continue
        counts[klass] = counts.get(klass, 0) + 1
        examples.setdefault(klass, warning)

    summary = [
        f"Skipped {count} markdown file(s) classified as {klass}; example: {examples[klass]}"
        for klass, count in sorted(counts.items())
    ]
    summary.extend(passthrough[:detail_threshold])
    if len(passthrough) > detail_threshold:
        summary.append(
            f"Skipped {len(passthrough) - detail_threshold} additional markdown file(s) classified as other_skips"
        )
    return summary


#END_BLOCK_WARNING_SUMMARY
#START_BLOCK_SCANNING
def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_strict_controller_packet(parsed: ParsedPacket) -> bool:
    required_sections = [
        parsed.allowed_write_scope,
        parsed.frozen_scope,
        parsed.must_preserve,
        parsed.verification,
        parsed.expected_evidence,
        parsed.escalation_triggers,
    ]
    return bool(parsed.packet_id and parsed.feature_id and parsed.wave_id and all(required_sections))


def _scan_strict_packets(project: Any) -> tuple[list[_StrictPacketRecord], list[str], list[str]]:
    repo_root = Path(project.repo_root)
    packets_dir = repo_root / project.packets_dir
    warnings: list[str] = []
    errors: list[str] = []
    records: list[_StrictPacketRecord] = []

    if not packets_dir.exists():
        return records, warnings, [f"Packets directory not found: {packets_dir}"]

    for path in sorted(packets_dir.glob("**/*.md")):
        try:
            parsed = parse_packet_markdown(path, mode="legacy_warn")
        except Exception as exc:
            warnings.append(f"Failed to parse {path}: {exc}")
            continue

        if not parsed.packet_id or not parsed.feature_id or not parsed.wave_id:
            warnings.append(
                f"Skipping non-runnable packet {path.name}: "
                f"missing packet_id={bool(parsed.packet_id)}, "
                f"feature_id={bool(parsed.feature_id)}, "
                f"wave_id={bool(parsed.wave_id)}"
            )
            continue

        if not _is_strict_controller_packet(parsed):
            warnings.append(
                f"Skipping legacy packet {path.name}: "
                f"has IDs but missing strict controller sections"
            )
            continue

        records.append(
            _StrictPacketRecord(
                parsed=parsed,
                source_path=path,
                source_rel_path=_relative_path(path, repo_root),
            )
        )

    return records, summarize_skip_warnings(warnings), errors


#END_BLOCK_SCANNING
#START_BLOCK_PACKET_FILTER
PACKET_FILTER_INVALID_PREFIX = "PACKET_FILTER_INVALID:"
PACKET_FILTER_NOT_FOUND_PREFIX = "PACKET_FILTER_NOT_FOUND:"


# START_FUNCTION_CONTRACT
# name: normalize_packet_ids
# purpose: Normalize optional operator packet id filters for deterministic scoped bootstrap planning.
# inputs:
#   packet_ids: Optional packet id sequence from API or CLI.
# returns: Tuple of sorted unique packet ids and fail-closed validation error strings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns PACKET_FILTER_INVALID-prefixed errors for blank ids.
# END_FUNCTION_CONTRACT
def normalize_packet_ids(packet_ids: list[str] | tuple[str, ...] | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if packet_ids is None:
        return [], errors

    normalized: set[str] = set()
    for value in packet_ids:
        packet_id = str(value or "").strip()
        if not packet_id:
            errors.append(f"{PACKET_FILTER_INVALID_PREFIX} packet id must not be blank")
            continue
        normalized.add(packet_id)

    return sorted(normalized), errors


def _filter_records(
    records: list[_StrictPacketRecord],
    packet_ids: list[str],
) -> tuple[list[_StrictPacketRecord], list[str]]:
    if not packet_ids:
        return records, []

    by_packet_id = {record.parsed.packet_id: record for record in records}
    missing = [packet_id for packet_id in packet_ids if packet_id not in by_packet_id]
    if missing:
        return [], [
            (
                f"{PACKET_FILTER_NOT_FOUND_PREFIX} requested packet id(s) not found "
                f"in source candidates: {', '.join(missing)}"
            )
        ]
    return [by_packet_id[packet_id] for packet_id in packet_ids], []


#END_BLOCK_PACKET_FILTER
#START_BLOCK_ARTIFACT_INFERENCE
TERMINAL_REGISTRY_STATUSES = {
    RegistryStatus.ACCEPTED.value,
    RegistryStatus.BLOCKED.value,
}


def _normalize_artifact_status(value: Any) -> str | None:
    token = str(value or "").strip().lower()
    token = token.strip("`'\". ")
    token = token.replace("-", "_")
    token = re.sub(r"^[^a-z0-9_]+", "", token)
    if token in {"accepted", "accept"}:
        return RegistryStatus.ACCEPTED.value
    if token in {"blocked", "scope_blocked", "rework_required", "failed"}:
        return RegistryStatus.BLOCKED.value
    if token in {"ready", "open"}:
        return RegistryStatus.READY.value
    return None


def _extract_key_value_status(content: str, keys: set[str]) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        match = re.match(r"^-?\s*(?:\*\*)?([a-zA-Z0-9_\- ]+)(?:\*\*)?\s*:\s*(.+?)\s*$", stripped)
        if not match:
            continue
        key = match.group(1).strip().lower().replace("-", "_").replace(" ", "_")
        if key in keys:
            status = _normalize_artifact_status(match.group(2))
            if status:
                return status
    return None


def _extract_verdict_section_status(content: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#+\s+verdict\b", line.strip(), re.IGNORECASE):
            for candidate in lines[index + 1:index + 8]:
                stripped = candidate.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                status = _normalize_artifact_status(stripped)
                if status:
                    return status
                break
    return None


def _status_from_json(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None

    packet_level_keys = (
        "registry_status",
        "domain_status",
        "current_status",
        "packet_status",
        "packet_verdict",
        "review_verdict",
        "verdict",
    )
    for key in packet_level_keys:
        if key in data:
            status = _normalize_artifact_status(data.get(key))
            if status in TERMINAL_REGISTRY_STATUSES:
                return status
    return None


def _read_text_status(path: Path, *, keys: set[str], verdict_section: bool = False) -> str | None:
    content = path.read_text(encoding="utf-8")
    status = _extract_key_value_status(content, keys)
    if status:
        return status
    if verdict_section:
        return _extract_verdict_section_status(content)
    return None


def _latest_attempt_dir(evidence_dir: Path) -> Path | None:
    if not evidence_dir.exists():
        return None
    attempt_dirs = sorted(path for path in evidence_dir.glob("attempt-*") if path.is_dir())
    return attempt_dirs[-1] if attempt_dirs else None


def _latest_evidence_files(layout: Any) -> list[tuple[Path, str]]:
    attempt_dir = _latest_attempt_dir(layout.evidence_dir)
    if attempt_dir is None:
        return []

    candidates = [
        (attempt_dir / "evidence_manifest.json", "json_manifest"),
        (attempt_dir / "evidence_manifest.md", "markdown_manifest"),
        (attempt_dir / "SUMMARY.md", "attempt_summary"),
        (attempt_dir / "REWORK_SUMMARY.md", "rework_evidence"),
        (attempt_dir / "REWORK_REPORT.md", "rework_evidence"),
    ]
    return [(path, kind) for path, kind in candidates if path.exists()]


def _review_status_to_registry_status(status: str | None) -> str | None:
    if status == "accepted":
        return RegistryStatus.ACCEPTED.value
    if status in {"blocked", "rework_required"}:
        return RegistryStatus.BLOCKED.value
    return None


def _infer_from_artifacts(
    packet_dir: Path,
    repo_root: Path,
    *,
    expected_packet_id: str | None,
) -> _ArtifactInference:
    layout = resolve_packet_layout(packet_dir)
    statuses: list[tuple[str, str, str]] = []
    evidence_paths: list[str] = []
    warnings: list[str] = []

    if layout.summary.exists():
        rel = _relative_path(layout.summary, repo_root)
        evidence_paths.append(rel)
        try:
            status = _read_text_status(layout.summary, keys={"current_status", "status"}, verdict_section=True)
            if status in {RegistryStatus.ACCEPTED.value, RegistryStatus.BLOCKED.value}:
                statuses.append((status, "summary_current_status", rel))
        except Exception as exc:
            warnings.append(f"Failed to read summary artifact {rel}: {exc}")

    review_path = latest_review(layout)
    if review_path:
        review_result = read_review_artifact_status(
            review_path,
            expected_packet_id=expected_packet_id,
        )
        rel = _relative_path(review_result.path or review_path, repo_root)
        evidence_paths.append(rel)
        status = _review_status_to_registry_status(review_result.status)
        if review_result.ok and status in {RegistryStatus.ACCEPTED.value, RegistryStatus.BLOCKED.value}:
            statuses.append((status, "latest_review", rel))
        else:
            warnings.append(
                f"Review artifact has no valid terminal status: {rel}"
            )

    for evidence_path, evidence_kind in _latest_evidence_files(layout):
        rel = _relative_path(evidence_path, repo_root)
        evidence_paths.append(rel)
        if evidence_kind == "rework_evidence":
            warnings.append(f"Rework evidence is non-terminal for bootstrap acceptance: {rel}")
            continue
        try:
            if evidence_kind == "json_manifest":
                status = _status_from_json(json.loads(evidence_path.read_text(encoding="utf-8")))
            else:
                status = _read_text_status(
                    evidence_path,
                    keys={"current_status", "packet_status", "status", "verdict"},
                    verdict_section=True,
                )
            if status in TERMINAL_REGISTRY_STATUSES:
                statuses.append((status, evidence_kind, rel))
            elif evidence_kind in {"markdown_manifest", "attempt_summary"}:
                warnings.append(f"Evidence artifact has no packet-level terminal status: {rel}")
        except Exception as exc:
            warnings.append(f"Failed to read evidence artifact {rel}: {exc}")

    terminal_statuses = {status for status, _reason, _path in statuses}
    if len(terminal_statuses) > 1:
        warnings.append("Conflicting terminal bootstrap evidence; packet remains waiting")
        return _ArtifactInference(
            status=RegistryStatus.WAITING_FOR_DEPENDENCIES.value,
            reason="conflicting_artifact_evidence",
            evidence_paths=evidence_paths,
            warnings=warnings,
        )

    if statuses:
        status, reason, path = statuses[-1]
        return _ArtifactInference(
            status=status,
            reason=f"{reason}:{path}",
            evidence_paths=evidence_paths,
            warnings=warnings,
        )

    return _ArtifactInference(
        status=None,
        reason="no_terminal_artifact_evidence",
        evidence_paths=evidence_paths,
        warnings=warnings,
    )


#END_BLOCK_ARTIFACT_INFERENCE
#START_BLOCK_BOOTSTRAP
def _packet_registry_record(
    record: _StrictPacketRecord,
    status: str,
    reason: str,
) -> dict[str, Any]:
    parsed = record.parsed
    return {
        "packet_id": parsed.packet_id,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "title": parsed.title,
        "objective": parsed.objective,
        "status": normalize_source_status(parsed.status).value,
        "phase": parsed.phase,
        "depends_on": parsed.depends_on,
        "source_hash": parsed.source_hash,
        "path": record.source_rel_path,
        "registry_status": status,
        "registry_reason": reason,
    }


def _planned_action(
    current_record: dict[str, Any] | None,
    inferred_status: str | None,
    source_hash: str,
) -> str:
    if inferred_status is None:
        return "skip"
    if current_record is None:
        return "create"
    if (
        current_record.get("registry_status") == inferred_status
        and current_record.get("source_hash") == source_hash
    ):
        return "noop"
    return "update"


def _terminal_registry_status(record: dict[str, Any] | None) -> str | None:
    if record is None:
        return None
    status = str(record.get("registry_status") or "")
    return status if status in TERMINAL_REGISTRY_STATUSES else None


def _dependency_statuses(
    packet: ParsedPacket,
    inferred: dict[str, str],
    registry: PacketRegistryStore,
) -> tuple[bool, list[str]]:
    missing_or_waiting: list[str] = []
    for dep_id in packet.depends_on:
        dep_status = inferred.get(dep_id)
        if dep_status is None:
            dep_record = registry.load_packet(dep_id)
            dep_status = dep_record.get("registry_status") if dep_record else None
        if dep_status != RegistryStatus.ACCEPTED.value:
            missing_or_waiting.append(dep_id)
    return not missing_or_waiting, missing_or_waiting


# START_FUNCTION_CONTRACT
# name: build_backlog_bootstrap_plan
# purpose: Build and optionally apply a runtime registry bootstrap plan from strict packets and artifacts.
# inputs:
#   project: ProjectAdapterConfig-like object with repo_root, packets_dir, runtime_state_root, project_key.
#   dry_run: if True, do not write registry state.
# returns: BacklogBootstrapPlan with candidate actions and apply count.
# side_effects: Reads packet/artifact files; writes packet registry when dry_run is False.
# emitted_logs: None.
# error_behavior: Captures scan/apply errors in the returned plan.
# END_FUNCTION_CONTRACT
def build_backlog_bootstrap_plan(
    project: Any,
    *,
    dry_run: bool = True,
    packet_ids: list[str] | tuple[str, ...] | None = None,
) -> BacklogBootstrapPlan:
    normalized_packet_ids, packet_filter_errors = normalize_packet_ids(packet_ids)
    plan = BacklogBootstrapPlan(
        project_key=project.project_key,
        dry_run=dry_run,
        packet_ids=normalized_packet_ids,
    )
    if packet_filter_errors:
        plan.errors.extend(packet_filter_errors)
        return plan

    repo_root = Path(project.repo_root)
    registry = PacketRegistryStore(Path(project.runtime_state_root) / "state")

    records, warnings, errors = _scan_strict_packets(project)
    plan.warnings.extend(warnings)
    plan.errors.extend(errors)
    if errors:
        return plan

    selected_records, packet_filter_errors = _filter_records(records, normalized_packet_ids)
    if packet_filter_errors:
        plan.errors.extend(packet_filter_errors)
        return plan

    inferred: dict[str, str] = {}
    artifact_inferences: dict[str, _ArtifactInference] = {}

    for record in records:
        artifact_inference = _infer_from_artifacts(
            record.source_path.parent,
            repo_root,
            expected_packet_id=record.parsed.packet_id,
        )
        artifact_inferences[record.parsed.packet_id] = artifact_inference
        if artifact_inference.status in {RegistryStatus.ACCEPTED.value, RegistryStatus.BLOCKED.value}:
            inferred[record.parsed.packet_id] = artifact_inference.status

    for record in selected_records:
        packet_id = record.parsed.packet_id
        artifact_inference = artifact_inferences[packet_id]
        current_record = registry.load_packet(packet_id)
        current_status = current_record.get("registry_status") if current_record else None
        candidate_warnings = list(artifact_inference.warnings)
        terminal_current_status = _terminal_registry_status(current_record)
        same_source_hash = bool(
            current_record
            and current_record.get("source_hash") == record.parsed.source_hash
        )

        if (
            terminal_current_status
            and same_source_hash
            and artifact_inference.status not in TERMINAL_REGISTRY_STATUSES
        ):
            inferred_status = terminal_current_status
            inference_reason = "existing_terminal_registry_source_hash_unchanged"
        elif artifact_inference.status in {
            RegistryStatus.ACCEPTED.value,
            RegistryStatus.BLOCKED.value,
            RegistryStatus.WAITING_FOR_DEPENDENCIES.value,
        }:
            inferred_status = artifact_inference.status
            inference_reason = artifact_inference.reason
            if terminal_current_status and same_source_hash and inferred_status != terminal_current_status:
                candidate_warnings.append(
                    "Terminal artifact evidence differs from existing registry status"
                )
        else:
            deps_ok, waiting_deps = _dependency_statuses(record.parsed, inferred, registry)
            if deps_ok:
                inferred_status = RegistryStatus.READY.value
                inference_reason = "strict_source_ready_no_terminal_artifact_evidence"
            else:
                inferred_status = RegistryStatus.WAITING_FOR_DEPENDENCIES.value
                inference_reason = f"waiting_for_dependency_evidence:{', '.join(waiting_deps)}"
                candidate_warnings.append("Terminal evidence missing; packet is not inferred accepted")
            inferred[packet_id] = inferred_status

        action = _planned_action(current_record, inferred_status, record.parsed.source_hash)
        candidate = BacklogBootstrapCandidate(
            packet_id=packet_id,
            source_path=record.source_rel_path,
            source_hash=record.parsed.source_hash,
            current_registry_status=current_status,
            inferred_status=inferred_status,
            inference_reason=inference_reason,
            evidence_paths=artifact_inference.evidence_paths,
            planned_action=action,
            warnings=candidate_warnings,
        )
        plan.candidates.append(candidate)

        if not dry_run and action in {"create", "update"} and inferred_status:
            try:
                registry.upsert_packet(
                    _packet_registry_record(record, inferred_status, inference_reason)
                )
                plan.apply_count += 1
            except Exception as exc:
                plan.errors.append(f"Failed to apply bootstrap for {packet_id}: {exc}")

    return plan


#END_BLOCK_BOOTSTRAP
