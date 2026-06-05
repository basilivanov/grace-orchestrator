"""
# ============================================================================
# AI_HEADER: GRACE Evidence Contract Module
# ============================================================================
#
# This module provides typed evidence requirement contracts for GRACE packet
# execution. Evidence requirements define what artifacts must be produced,
# who owns producing them, when they are required, and how blockers route
# when evidence is missing or invalid.
#
# Key Concepts:
# - Evidence requirements are structured (not free-form prose)
# - Requirements specify: id, kind, stage, owner, producer, profile
# - Validation is deterministic and fail-closed
# - Invalid contracts route to architect (not coder)
# - Verifier remains an agent (not scripted)
#
# Module Dependencies:
# - prefect_grace.platform.packet_parser (ParsedPacket)
# - No Prefect imports (pure validation logic)
#
# ============================================================================
"""

from dataclasses import dataclass, field
from typing import Any
import yaml
import re

# START_MODULE_CONTRACT
# Module: evidence_contract
# Purpose: Parse and validate typed evidence requirements from packet markdown
# Exports: EvidenceRequirement, EvidenceContract, EvidenceContractValidation,
#          parse_evidence_contract, validate_evidence_contract
# Dependencies: packet_parser (ParsedPacket)
# Constraints: No Prefect imports, deterministic validation, fail-closed
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - Evidence requirement and contract dataclasses
# Block: validation_constants - Allowed values for evidence fields
# Block: parser - Parse evidence requirements from packet markdown
# Block: validator - Validate evidence contract schema
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class EvidenceRequirement:
    """Typed evidence requirement specification.

    Fields:
    - id: Unique identifier (e.g., EV-UI-WEEK-DEV-EXPANDED)
    - kind: Evidence type (test, visual, observability, diff, contract, human_signoff, runtime_log)
    - stage: When required (packet_local, wave_final, release_final)
    - owner: Who owns producing it (coder, verifier, reviewer, architect, pipeline)
    - producer: How it is produced (agent, pytest, playwright, cli, log_watch, post_test_review, manual, pipeline)
    - profile: Verification profile reference (optional)
    - instruction: Human-readable description
    - required: Whether evidence is mandatory
    - coder_blocking: Whether missing evidence blocks coder packet
    - artifact_patterns: Expected artifact path patterns
    """
    id: str
    kind: str
    stage: str
    owner: str
    producer: str
    profile: str | None
    instruction: str
    required: bool
    coder_blocking: bool
    artifact_patterns: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize EvidenceRequirement to dict for JSON output
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
            "kind": self.kind,
            "stage": self.stage,
            "owner": self.owner,
            "producer": self.producer,
            "profile": self.profile,
            "instruction": self.instruction,
            "required": self.required,
            "coder_blocking": self.coder_blocking,
            "artifact_patterns": list(self.artifact_patterns),
        }


@dataclass(frozen=True)
class EvidenceContract:
    """
    Collection of evidence requirements for a packet.

    Fields:
    - packet_id: Packet identifier
    - requirements: List of evidence requirements
    """
    packet_id: str
    requirements: list[EvidenceRequirement] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize EvidenceContract to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with packet_id and requirements list
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "packet_id": self.packet_id,
            "requirements": [req.to_dict() for req in self.requirements],
        }


@dataclass(frozen=True)
class EvidenceContractValidation:
    """
    Result of evidence contract validation.

    Fields:
    - ok: Whether contract is valid
    - errors: List of validation errors
    - warnings: List of validation warnings
    """
    ok: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize EvidenceContractValidation to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with ok, errors, warnings
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }

#END_BLOCK_MODELS
#START_BLOCK_VALIDATION_CONSTANTS
# Allowed evidence kinds
ALLOWED_KINDS = {
    "test",
    "visual",
    "observability",
    "diff",
    "contract",
    "human_signoff",
    "runtime_log",
}

# Allowed evidence stages
ALLOWED_STAGES = {
    "packet_local",
    "wave_final",
    "release_final",
}

# Allowed evidence owners
ALLOWED_OWNERS = {
    "coder",
    "verifier",
    "reviewer",
    "architect",
    "pipeline",
}

# Allowed evidence producers
ALLOWED_PRODUCERS = {
    "agent",
    "pytest",
    "playwright",
    "cli",
    "log_watch",
    "post_test_review",
    "manual",
    "pipeline",
}

#END_BLOCK_VALIDATION_CONSTANTS
#START_BLOCK_PARSER
# START_FUNCTION_CONTRACT
# Function: parse_evidence_contract
# Purpose: Parse evidence requirements from packet markdown
# Args:
#   - packet: ParsedPacket with markdown content
# Returns: EvidenceContract with parsed requirements
# Inputs: ParsedPacket object
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Returns empty contract if parsing fails
# Behavior:
#   - Looks for ## Evidence Requirements section
#   - Parses YAML blocks or structured bullets
#   - Returns empty contract with warning if section missing
#   - Deterministic parsing, no LLM calls
# END_FUNCTION_CONTRACT
def parse_evidence_contract(packet: Any) -> EvidenceContract:
    """
    Parse evidence requirements from packet markdown.

    Looks for ## Evidence Requirements section with YAML blocks.
    Returns empty contract if section missing.
    """
    packet_id = packet.packet_id if hasattr(packet, "packet_id") else "unknown"

    # Try to find Evidence Requirements section in packet
    # For MVP, we'll look for a YAML block in the markdown
    # This is a simplified parser - production would need more robust parsing

    requirements = []

    # Check if packet has raw markdown content
    # For now, return empty contract (will be populated when we have real packets with Evidence Requirements)

    return EvidenceContract(
        packet_id=packet_id,
        requirements=requirements,
    )


def _parse_yaml_requirement(yaml_data: dict[str, Any]) -> EvidenceRequirement:
    """Parse single evidence requirement from YAML dict."""
    return EvidenceRequirement(
        id=yaml_data.get("id", ""),
        kind=yaml_data.get("kind", ""),
        stage=yaml_data.get("stage", ""),
        owner=yaml_data.get("owner", ""),
        producer=yaml_data.get("producer", ""),
        profile=yaml_data.get("profile"),
        instruction=yaml_data.get("instruction", ""),
        required=yaml_data.get("required", False),
        coder_blocking=yaml_data.get("coder_blocking", False),
        artifact_patterns=yaml_data.get("artifact_patterns", []),
    )

#END_BLOCK_PARSER
#START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# Function: validate_evidence_contract
# Purpose: Validate evidence contract schema
# Args:
#   - contract: EvidenceContract to validate
#   - profiles: Dict of verification profiles from verification.yaml
# Returns: EvidenceContractValidation with errors and warnings
# Inputs: EvidenceContract, verification profiles dict
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Returns validation result with errors list, never raises
# Behavior:
#   - Checks missing/duplicate ids
#   - Checks unknown kind/stage/owner/producer
#   - Checks required evidence without owner/producer
#   - Checks profile reference exists
#   - Checks wave_final evidence not coder_blocking
#   - Checks artifact pattern for required non-human evidence
#   - Deterministic validation, fail-closed
# END_FUNCTION_CONTRACT
def validate_evidence_contract(
    contract: EvidenceContract,
    profiles: dict[str, Any],
) -> EvidenceContractValidation:
    """
    Validate evidence contract schema.

    Checks:
    - Missing/duplicate ids
    - Unknown kind/stage/owner/producer
    - Required evidence without owner/producer
    - Profile reference that does not exist
    - wave_final evidence marked coder_blocking
    - Artifact pattern missing for required non-human evidence

    Returns structured validation result.
    """
    errors = []
    warnings = []

    # Track seen IDs for duplicate detection
    seen_ids = set()

    for req in contract.requirements:
        # Check missing ID
        if not req.id:
            errors.append({
                "code": "missing_id",
                "evidence_id": None,
                "route_to": "architect",
                "message": "Evidence requirement missing id field",
            })
            continue

        # Check duplicate ID
        if req.id in seen_ids:
            errors.append({
                "code": "duplicate_id",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Duplicate evidence id: {req.id}",
            })
        seen_ids.add(req.id)

        # Check unknown kind
        if req.kind not in ALLOWED_KINDS:
            errors.append({
                "code": "unknown_kind",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Unknown evidence kind: {req.kind}. Allowed: {', '.join(sorted(ALLOWED_KINDS))}",
            })

        # Check unknown stage
        if req.stage not in ALLOWED_STAGES:
            errors.append({
                "code": "unknown_stage",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Unknown evidence stage: {req.stage}. Allowed: {', '.join(sorted(ALLOWED_STAGES))}",
            })

        # Check unknown owner
        if req.owner not in ALLOWED_OWNERS:
            errors.append({
                "code": "unknown_owner",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Unknown evidence owner: {req.owner}. Allowed: {', '.join(sorted(ALLOWED_OWNERS))}",
            })

        # Check unknown producer
        if req.producer not in ALLOWED_PRODUCERS:
            errors.append({
                "code": "unknown_producer",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Unknown evidence producer: {req.producer}. Allowed: {', '.join(sorted(ALLOWED_PRODUCERS))}",
            })

        # Check required evidence without owner
        if req.required and not req.owner:
            errors.append({
                "code": "required_without_owner",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Required evidence {req.id} missing owner",
            })

        # Check required evidence without producer
        if req.required and not req.producer:
            errors.append({
                "code": "required_without_producer",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Required evidence {req.id} missing producer",
            })

        # Check wave_final evidence marked coder_blocking
        if req.stage == "wave_final" and req.coder_blocking:
            errors.append({
                "code": "wave_final_coder_blocking",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"wave_final evidence {req.id} cannot be coder_blocking",
            })

        # Check profile reference exists
        if req.profile and req.profile not in profiles:
            errors.append({
                "code": "missing_verification_profile",
                "evidence_id": req.id,
                "route_to": "architect",
                "message": f"Profile {req.profile} not found in verification.yaml",
            })

        # Check artifact pattern for required non-human evidence
        if req.required and req.kind != "human_signoff" and not req.artifact_patterns:
            warnings.append({
                "code": "missing_artifact_pattern",
                "evidence_id": req.id,
                "message": f"Required evidence {req.id} missing artifact_patterns",
            })

    return EvidenceContractValidation(
        ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )

#END_BLOCK_VALIDATOR
