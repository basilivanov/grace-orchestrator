"""
# ============================================================================
# AI_HEADER: GRACE Evidence Manifest Module
# ============================================================================
#
# This module provides typed evidence manifest models for GRACE verifier output.
# Evidence manifests are structured JSON documents that record what evidence
# was collected, what's missing, what's deferred, and what blockers exist.
#
# Key Concepts:
# - Evidence manifests are JSON (not free-form prose)
# - Each evidence item has: id, status, stage, producer, artifact_paths, summary
# - Statuses: collected, missing, deferred, not_applicable, failed, artifact_reference_invalid, contract_invalid
# - Manifests are validated against evidence contracts
# - Verifier produces manifest, platform validates it
#
# Module Dependencies:
# - prefect_grace.platform.evidence_contract (EvidenceContract, EvidenceContractValidation)
# - No Prefect imports (pure validation logic)
#
# ============================================================================
"""

from dataclasses import dataclass, field, replace
from typing import Any
from pathlib import Path
import json

from prefect_grace.platform.structured_logger import REQUIRED_ENVELOPE_FIELDS

# START_MODULE_CONTRACT
# Module: evidence_manifest
# Purpose: Parse and validate evidence manifests from verifier output
# Exports: EvidenceItem, EvidenceManifest, parse_evidence_manifest, validate_evidence_manifest, validate_execution_trace_jsonl
# Dependencies: evidence_contract (EvidenceContract, EvidenceContractValidation)
# Constraints: No Prefect imports, deterministic validation, fail-closed
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - Evidence item and manifest dataclasses
# Block: validation_constants - Allowed evidence statuses
# Block: parser - Parse evidence manifest from JSON
# Block: validator - Validate manifest against contract and structured trace artifacts
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class EvidenceItem:
    """Single evidence item in manifest.

    Fields:
    - id: Evidence requirement ID
    - status: Evidence status (collected, missing, deferred, not_applicable, failed, artifact_reference_invalid, contract_invalid)
    - stage: Evidence stage (packet_local, wave_final, release_final)
    - producer: How evidence was produced (agent, pytest, playwright, cli, etc.)
    - artifact_paths: List of artifact file paths
    - summary: Human-readable summary of evidence
    """
    id: str
    status: str
    stage: str
    producer: str
    artifact_paths: list[str]
    summary: str

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize EvidenceItem to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with all fields
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "id": self.id,
            "status": self.status,
            "stage": self.stage,
            "producer": self.producer,
            "artifact_paths": list(self.artifact_paths),
            "summary": self.summary,
        }

    # START_FUNCTION_CONTRACT
    # Function: from_dict
    # Purpose: Deserialize EvidenceItem from dict
    # Args: data dict with evidence item fields
    # Returns: EvidenceItem instance
    # Inputs: Dict from JSON
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Raises KeyError if required fields missing
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        """Deserialize from dict."""
        return cls(
            id=data.get("id", ""),
            status=data.get("status", ""),
            stage=data.get("stage", ""),
            producer=data.get("producer", ""),
            artifact_paths=data.get("artifact_paths", []),
            summary=data.get("summary", ""),
        )


@dataclass(frozen=True)
class EvidenceManifest:
    """Evidence manifest from verifier output.

    Fields:
    - packet_id: Packet identifier
    - generated_by: Who generated manifest (verifier, pipeline, etc.)
    - evidence: List of evidence items
    - blockers: List of blocker dicts
    """
    packet_id: str
    generated_by: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    manifest_dir: str | None = field(default=None, repr=False, compare=False)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize EvidenceManifest to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with packet_id, generated_by, evidence, blockers
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "packet_id": self.packet_id,
            "generated_by": self.generated_by,
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": list(self.blockers),
        }

    # START_FUNCTION_CONTRACT
    # Function: from_dict
    # Purpose: Deserialize EvidenceManifest from dict
    # Args: data dict with manifest fields
    # Returns: EvidenceManifest instance
    # Inputs: Dict from JSON
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Raises KeyError if required fields missing
    # END_FUNCTION_CONTRACT
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceManifest":
        """Deserialize from dict."""
        evidence_items = data.get("evidence") if "evidence" in data else data.get("requirement_results", [])
        if evidence_items is None:
            evidence_items = []
        return cls(
            packet_id=data.get("packet_id", ""),
            generated_by=data.get("generated_by", ""),
            evidence=[EvidenceItem.from_dict(item) for item in evidence_items],
            blockers=data.get("blockers", []),
            manifest_dir=data.get("manifest_dir"),
        )

#END_BLOCK_MODELS
#START_BLOCK_VALIDATION_CONSTANTS
# Allowed evidence statuses
ALLOWED_STATUSES = {
    "collected",
    "missing",
    "deferred",
    "not_applicable",
    "failed",
    "artifact_reference_invalid",
    "contract_invalid",
}

#END_BLOCK_VALIDATION_CONSTANTS
#START_BLOCK_PARSER
# START_FUNCTION_CONTRACT
# Function: parse_evidence_manifest
# Purpose: Load evidence manifest from JSON file
# Args:
#   - path: Path to evidence_manifest.json
# Returns: EvidenceManifest with parsed data
# Inputs: Path to JSON file
# Side_effects: Reads file from disk
# Emitted_logs: None
# Error_behavior: Raises FileNotFoundError or JSONDecodeError on failure
# Behavior:
#   - Reads JSON file
#   - Deserializes to EvidenceManifest
#   - Raises exception if file not found or invalid JSON
# END_FUNCTION_CONTRACT
def parse_evidence_manifest(path: Path) -> "EvidenceManifest":
    """Load evidence manifest from JSON file."""
    with open(path, "r") as f:
        data = json.load(f)
    manifest = EvidenceManifest.from_dict(data)
    return replace(manifest, manifest_dir=str(path.parent))

#END_BLOCK_PARSER
#START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# Function: validate_execution_trace_jsonl
# Purpose: Validate structured execution trace JSONL envelope format
# Args:
#   - path: Path to execution_trace.jsonl
# Returns: list[dict[str, Any]] validation errors
# Inputs: Path
# Side_effects: Reads JSONL trace file
# Emitted_logs: None
# Error_behavior: Returns errors for missing, invalid JSON, missing fields, or non-object lines
# END_FUNCTION_CONTRACT
def validate_execution_trace_jsonl(path: Path) -> list[dict[str, Any]]:
    """Validate structured execution trace JSONL envelope format."""
    if not path.exists():
        return [{
            "code": "execution_trace_missing",
            "path": str(path),
            "message": f"execution_trace.jsonl not found: {path}",
        }]

    errors: list[dict[str, Any]] = []
    required = set(REQUIRED_ENVELOPE_FIELDS) | {"packet_id", "attempt"}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [{
            "code": "execution_trace_unreadable",
            "path": str(path),
            "message": str(exc),
        }]

    if not lines:
        errors.append({
            "code": "execution_trace_empty",
            "path": str(path),
            "message": "execution_trace.jsonl has no events",
        })

    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({
                "code": "execution_trace_invalid_json",
                "path": str(path),
                "line": index,
                "message": str(exc),
            })
            continue
        if not isinstance(entry, dict):
            errors.append({
                "code": "execution_trace_non_object",
                "path": str(path),
                "line": index,
                "message": "Trace line must be a JSON object",
            })
            continue
        missing = sorted(required - set(entry.keys()))
        if missing:
            errors.append({
                "code": "execution_trace_missing_fields",
                "path": str(path),
                "line": index,
                "fields": missing,
                "message": f"Trace line missing fields: {', '.join(missing)}",
            })
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            errors.append({
                "code": "execution_trace_invalid_timestamp",
                "path": str(path),
                "line": index,
                "message": "Trace timestamp must be ISO-8601 UTC with trailing Z",
            })
    return errors


# START_FUNCTION_CONTRACT
# Function: resolve_execution_trace_artifact
# Purpose: Resolve trace artifact path through allowed artifact roots
# Args:
#   - artifact_path: Path string from evidence manifest
#   - artifact_roots: allowed roots for manifest-local and artifact-root paths
# Returns: Path or None
# Inputs: artifact path and artifact roots
# Side_effects: None
# Emitted_logs: None
# Error_behavior: Returns None for missing or traversal/outside-root paths
# END_FUNCTION_CONTRACT
def resolve_execution_trace_artifact(
    artifact_path: str,
    artifact_roots: list[Path],
) -> Path | None:
    """Resolve an execution trace artifact using artifact-validator roots."""
    path = Path(artifact_path)
    roots = [root.resolve() for root in artifact_roots]

    if path.is_absolute():
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            return None
        if not roots:
            return resolved if resolved.exists() else None
        for root in roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return resolved if resolved.exists() else None
        return None

    for root in roots:
        candidate = root / path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved.exists():
            return resolved
    return None


# START_FUNCTION_CONTRACT
# Function: validate_evidence_manifest
# Purpose: Validate manifest against contract
# Args:
#   - manifest: EvidenceManifest to validate
#   - contract: EvidenceContract to validate against
#   - artifact_roots: Optional roots used to resolve execution_trace.jsonl artifacts
# Returns: EvidenceContractValidation with errors and warnings
# Inputs: EvidenceManifest, EvidenceContract
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Returns validation result with errors list, never raises
# Behavior:
#   - Checks all required evidence has status collected or deferred (if wave_final)
#   - Checks evidence IDs match contract
#   - Checks statuses are valid
#   - Checks packet_local required evidence not missing
#   - Deterministic validation, fail-closed
# END_FUNCTION_CONTRACT
def validate_evidence_manifest(
    manifest: "EvidenceManifest",
    contract: Any,  # EvidenceContract
    artifact_roots: list[Path] | None = None,
) -> Any:  # EvidenceContractValidation
    """Validate manifest against contract.

    Checks:
    - All required evidence has status collected or deferred (if wave_final)
    - Evidence IDs match contract
    - Statuses are valid
    - packet_local required evidence not missing
    """
    from prefect_grace.platform.evidence_contract import EvidenceContractValidation

    errors = []
    warnings = []

    manifest_packet_id = str(manifest.packet_id or "").strip()
    contract_packet_id = str(getattr(contract, "packet_id", "") or "").strip()
    if not manifest_packet_id:
        errors.append({
            "code": "manifest_packet_id_missing",
            "route_to": "verifier",
            "message": "Evidence manifest packet_id is required",
        })
    elif manifest_packet_id.upper() == "UNKNOWN":
        errors.append({
            "code": "manifest_packet_id_unknown",
            "route_to": "verifier",
            "message": "Evidence manifest packet_id cannot be UNKNOWN",
        })
    elif manifest_packet_id != contract_packet_id:
        errors.append({
            "code": "manifest_packet_id_mismatch",
            "route_to": "verifier",
            "manifest_packet_id": manifest_packet_id,
            "contract_packet_id": contract_packet_id,
            "message": (
                "Evidence manifest packet_id does not match packet contract "
                f"packet_id: {manifest_packet_id} != {contract_packet_id}"
            ),
        })

    # Build map of contract requirements by ID
    contract_reqs = {req.id: req for req in contract.requirements}

    # Build map of manifest evidence by ID
    manifest_evidence = {item.id: item for item in manifest.evidence}

    # Check all required evidence is present
    for req_id, req in contract_reqs.items():
        if not req.required:
            continue

        evidence = manifest_evidence.get(req_id)

        if evidence is None:
            errors.append({
                "code": "evidence_not_generated",
                "evidence_id": req_id,
                "route_to": "verifier",
                "message": f"Required evidence {req_id} not in manifest",
            })
            continue

        # Check status is valid
        if evidence.status not in ALLOWED_STATUSES:
            errors.append({
                "code": "invalid_status",
                "evidence_id": req_id,
                "route_to": "verifier",
                "message": f"Invalid status for {req_id}: {evidence.status}",
            })
            continue

        # Check packet_local required evidence is collected
        if req.stage == "packet_local" and evidence.status not in ["collected", "not_applicable"]:
            if evidence.status == "deferred":
                errors.append({
                    "code": "packet_local_deferred",
                    "evidence_id": req_id,
                    "route_to": "verifier",
                    "message": f"packet_local evidence {req_id} cannot be deferred",
                })
            elif evidence.status == "missing":
                if req.coder_blocking:
                    errors.append({
                        "code": "implementation_failed",
                        "evidence_id": req_id,
                        "route_to": "coder",
                        "message": f"Required packet_local evidence {req_id} missing (coder_blocking)",
                    })
                else:
                    errors.append({
                        "code": "evidence_not_generated",
                        "evidence_id": req_id,
                        "route_to": "verifier",
                        "message": f"Required packet_local evidence {req_id} missing",
                    })

        # Check wave_final required evidence is collected or deferred
        if req.stage == "wave_final" and evidence.status not in ["collected", "deferred", "not_applicable"]:
            if evidence.status == "missing":
                warnings.append({
                    "code": "wave_final_evidence_pending",
                    "evidence_id": req_id,
                    "message": f"wave_final evidence {req_id} missing (not packet-blocking)",
                })

    # Check all manifest evidence IDs exist in contract
    for evidence_id in manifest_evidence.keys():
        if evidence_id not in contract_reqs:
            warnings.append({
                "code": "unknown_evidence_id",
                "evidence_id": evidence_id,
                "message": f"Evidence {evidence_id} not in contract",
            })

    trace_roots = list(artifact_roots or [])
    if not trace_roots and manifest.manifest_dir:
        trace_roots.append(Path(manifest.manifest_dir))

    # Validate structured trace artifacts through the same root model used by
    # artifact validation. Missing traces remain artifact validation's job.
    for evidence in manifest.evidence:
        for artifact_path in evidence.artifact_paths:
            if Path(artifact_path).name != "execution_trace.jsonl":
                continue
            path = resolve_execution_trace_artifact(artifact_path, trace_roots)
            if path is None:
                continue
            for trace_error in validate_execution_trace_jsonl(path):
                errors.append({
                    **trace_error,
                    "evidence_id": evidence.id,
                    "route_to": "coder",
                })

    return EvidenceContractValidation(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )

#END_BLOCK_VALIDATOR
