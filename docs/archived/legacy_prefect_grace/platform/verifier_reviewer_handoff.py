"""
# ============================================================================
# AI_HEADER: GRACE Verifier Reviewer Handoff Module
# ============================================================================
#
# This module implements the formal handoff from completed coder packet run
# to verifier and reviewer agents. It controls context shape, marker parsing,
# manifest validation, artifact existence checks, and routing semantics.
#
# Key Concepts:
# - Verifier and reviewer remain LLM agents (not replaced by scripts)
# - Platform validates contracts, artifacts, and routing only
# - Evidence validation happens before reviewer acceptance
# - Domain statuses are data outcomes (not Python exceptions)
# - Handoff writes artifacts but does not mutate packet registry
#
# Module Dependencies:
# - prefect_grace.platform.evidence_contract
# - prefect_grace.platform.evidence_manifest
# - prefect_grace.platform.artifact_validator
# - prefect_grace.platform.blocker_routing
# - prefect_grace.platform.packet_artifacts
# - No Prefect imports at module level
#
# ============================================================================
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from pathlib import Path
import json
import re

from prefect_grace.platform.status_model import DomainStatus, normalize_domain_status

# START_MODULE_CONTRACT
# Module: verifier_reviewer_handoff
# Purpose: Formal handoff from coder to verifier to reviewer agents
# Exports: HandoffAgentResult, PacketHandoffResult, run_verifier_reviewer_handoff
# Dependencies: evidence_contract, evidence_manifest, artifact_validator, blocker_routing, packet_artifacts
# Constraints: No Prefect imports, agents remain agents, fail-closed validation
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - HandoffAgentResult and PacketHandoffResult dataclasses
# Block: marker_parsing - Parse FINAL_VERIFIER_EVIDENCE_JSON and FINAL_PACKET_DECISION_JSON
# Block: evidence_validation - Validate evidence manifest against contract
# Block: handoff_controller - Main run_verifier_reviewer_handoff function
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class HandoffAgentResult:
    """Result from verifier or reviewer agent execution.

    Fields:
    - ok: Whether agent execution succeeded
    - role: Agent role (verifier or reviewer)
    - packet_id: Packet identifier
    - raw_output: Full agent output text
    - parsed_json: Parsed JSON from final marker (None if parsing failed)
    - marker_found: Whether final marker was found
    - errors: List of error messages
    """
    ok: bool
    role: Literal["verifier", "reviewer"]
    packet_id: str
    raw_output: str
    parsed_json: dict[str, Any] | None
    marker_found: bool
    errors: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize HandoffAgentResult to dict for JSON output
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
            "ok": self.ok,
            "role": self.role,
            "packet_id": self.packet_id,
            "raw_output": self.raw_output,
            "parsed_json": self.parsed_json,
            "marker_found": self.marker_found,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class PacketHandoffResult:
    """Result of complete verifier-reviewer handoff.

    Fields:
    - ok: Whether handoff succeeded (accepted or rework_required)
    - domain_status: Handoff outcome status
    - packet_id: Packet identifier
    - attempt: Attempt number
    - verifier: Verifier agent result
    - reviewer: Reviewer agent result (None if verifier failed)
    - evidence_manifest_path: Path to written evidence manifest
    - review_path: Path to written review file
    - rework_path: Path to written rework file (None if not rework)
    - route_classification: Routing classification from reviewer
    - rework_mode: Rework mode from reviewer
    - blocker_reason: Blocker reason if blocked
    """
    ok: bool
    domain_status: Literal[
        "accepted",
        "rework_required",
        "blocked",
        "escalate_to_architect",
        "verifier_failed",
        "reviewer_failed",
        "handoff_error",
    ]
    packet_id: str
    attempt: int
    verifier: HandoffAgentResult
    reviewer: HandoffAgentResult | None
    evidence_manifest_path: str | None
    review_path: str | None
    rework_path: str | None
    route_classification: str | None = None
    rework_mode: str | None = None
    blocker_reason: str | None = None

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize PacketHandoffResult to dict for JSON output
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
            "ok": self.ok,
            "domain_status": self.domain_status,
            "packet_id": self.packet_id,
            "attempt": self.attempt,
            "verifier": self.verifier.to_dict(),
            "reviewer": self.reviewer.to_dict() if self.reviewer else None,
            "evidence_manifest_path": self.evidence_manifest_path,
            "review_path": self.review_path,
            "rework_path": self.rework_path,
            "route_classification": self.route_classification,
            "rework_mode": self.rework_mode,
            "blocker_reason": self.blocker_reason,
        }

#END_BLOCK_MODELS
#START_BLOCK_MARKER_PARSING
# START_FUNCTION_CONTRACT
# Function: parse_verifier_evidence_marker
# Purpose: Parse FINAL_VERIFIER_EVIDENCE_JSON marker from verifier output
# Args: raw_output (str) - Full verifier output text
# Returns: Tuple of (parsed_json dict or None, marker_found bool, errors list)
# Inputs: Verifier agent output text
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Returns (None, False, errors) if marker missing or JSON invalid
# END_FUNCTION_CONTRACT
def parse_verifier_evidence_marker(raw_output: str) -> tuple[dict[str, Any] | None, bool, list[str]]:
    """Parse FINAL_VERIFIER_EVIDENCE_JSON marker from verifier output."""
    errors = []

    # Look for marker
    pattern = r'FINAL_VERIFIER_EVIDENCE_JSON\s*\n(.*?)\nEND_FINAL_VERIFIER_EVIDENCE_JSON'
    match = re.search(pattern, raw_output, re.DOTALL)

    if not match:
        errors.append("FINAL_VERIFIER_EVIDENCE_JSON marker not found in verifier output")
        return None, False, errors

    json_text = match.group(1).strip()

    try:
        parsed = json.loads(json_text)
        return parsed, True, []
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON in verifier evidence marker: {e}")
        return None, True, errors


# START_FUNCTION_CONTRACT
# Function: parse_reviewer_decision_marker
# Purpose: Parse FINAL_PACKET_DECISION_JSON marker from reviewer output
# Args: raw_output (str) - Full reviewer output text
# Returns: Tuple of (parsed_json dict or None, marker_found bool, errors list)
# Inputs: Reviewer agent output text
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Returns (None, False, errors) if marker missing or JSON invalid
# END_FUNCTION_CONTRACT
def parse_reviewer_decision_marker(raw_output: str) -> tuple[dict[str, Any] | None, bool, list[str]]:
    """Parse FINAL_PACKET_DECISION_JSON marker from reviewer output."""
    errors = []

    # Look for marker
    pattern = r'FINAL_PACKET_DECISION_JSON\s*\n(.*?)\nEND_FINAL_PACKET_DECISION_JSON'
    match = re.search(pattern, raw_output, re.DOTALL)

    if not match:
        errors.append("FINAL_PACKET_DECISION_JSON marker not found in reviewer output")
        return None, False, errors

    json_text = match.group(1).strip()

    try:
        parsed = json.loads(json_text)
        return parsed, True, []
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON in reviewer decision marker: {e}")
        return None, True, errors

#END_BLOCK_MARKER_PARSING
#START_BLOCK_EVIDENCE_VALIDATION
# START_FUNCTION_CONTRACT
# Function: validate_verifier_evidence
# Purpose: Validate verifier evidence manifest against contract and artifacts
# Args:
#   evidence_json (dict) - Parsed verifier evidence JSON
#   packet_dir (Path) - Packet directory path
#   allowed_artifact_roots (list[Path]) - Allowed artifact root directories
# Returns: Tuple of (ok bool, errors list)
# Inputs: Evidence JSON, packet directory, artifact roots
# Side_effects: Reads artifact files to check existence via artifact_validator
# Emitted_logs: None
# Error_behavior: Returns (False, errors) if validation fails
# END_FUNCTION_CONTRACT
def validate_verifier_evidence(
    evidence_json: dict[str, Any],
    packet_dir: Path,
    allowed_artifact_roots: list[Path],
) -> tuple[bool, list[str]]:
    """Validate verifier evidence manifest."""
    from prefect_grace.platform.artifact_validator import validate_artifact_references
    from prefect_grace.platform.evidence_manifest import EvidenceItem, EvidenceManifest

    errors = []

    # Check required fields
    if "requirement_results" not in evidence_json:
        errors.append("Missing required field: requirement_results")
        return False, errors

    requirement_results = evidence_json.get("requirement_results", [])

    # Validate each requirement result schema
    for req in requirement_results:
        req_id = req.get("id", "unknown")
        status = req.get("status", "")
        stage = req.get("stage", "")

        # Validate status
        allowed_statuses = [
            "collected", "missing", "deferred", "not_applicable",
            "failed", "artifact_reference_invalid", "contract_invalid"
        ]
        if status not in allowed_statuses:
            errors.append(f"Invalid status '{status}' for requirement {req_id}")

        # Validate stage
        allowed_stages = ["packet_local", "wave_final", "release_final"]
        if stage not in allowed_stages:
            errors.append(f"Invalid stage '{stage}' for requirement {req_id}")

    # Use artifact_validator to validate artifact paths
    # Convert requirement_results to EvidenceManifest format
    evidence_items = []
    for req in requirement_results:
        evidence_items.append(EvidenceItem(
            id=req.get("id", "unknown"),
            status=req.get("status", "unknown"),
            stage=req.get("stage", "packet_local"),
            producer=req.get("producer", "unknown"),
            artifact_paths=req.get("artifact_paths", []),
            summary=req.get("summary", ""),
        ))

    manifest = EvidenceManifest(
        packet_id=evidence_json.get("packet_id", "unknown"),
        generated_by=evidence_json.get("generated_by", "verifier"),
        evidence=evidence_items,
        blockers=[],
    )

    # Validate artifact references using artifact_validator
    artifact_validation = validate_artifact_references(manifest, allowed_artifact_roots)

    if not artifact_validation.ok:
        for missing_path in artifact_validation.missing_artifacts:
            # Find which requirement this artifact belongs to
            for req in requirement_results:
                if missing_path in req.get("artifact_paths", []):
                    req_id = req.get("id", "unknown")
                    errors.append(f"Artifact does not exist: {missing_path} (requirement {req_id})")
                    break

    return len(errors) == 0, errors

#END_BLOCK_EVIDENCE_VALIDATION
#START_BLOCK_HANDOFF_CONTROLLER
# START_FUNCTION_CONTRACT
# Function: run_verifier_reviewer_handoff
# Purpose: Execute complete verifier-reviewer handoff for a packet
# Args:
#   packet_dir (Path) - Packet directory path
#   packet_file (Path) - Path to EXECUTION_PACKET.md
#   attempt (int) - Attempt number
#   coder_result (dict) - Coder managed packet result
#   verifier_launcher (Callable) - Function to launch verifier agent
#   reviewer_launcher (Callable) - Function to launch reviewer agent
#   project (Any) - Optional project context
#   dry_run (bool) - Whether to run in dry-run mode (default True)
# Returns: PacketHandoffResult with handoff outcome
# Inputs: Packet paths, coder result, launcher functions
# Side_effects: Writes evidence/review/rework artifacts, launches agents
# Emitted_logs: None
# Error_behavior: Returns handoff_error status on unexpected errors
# END_FUNCTION_CONTRACT
def run_verifier_reviewer_handoff(
    *,
    packet_dir: Path,
    packet_file: Path,
    attempt: int,
    coder_result: dict[str, Any],
    verifier_launcher: Callable[..., dict[str, Any]],
    reviewer_launcher: Callable[..., dict[str, Any]],
    project: Any | None = None,
    dry_run: bool = True,
) -> PacketHandoffResult:
    """Execute complete verifier-reviewer handoff."""
    from prefect_grace.platform.packet_artifacts import write_evidence, write_review, write_rework

    packet_id = coder_result.get("packet_id", "unknown")

    # Determine allowed artifact roots
    allowed_artifact_roots = [packet_dir]
    worktree_path = coder_result.get("worktree_path")
    if worktree_path:
        allowed_artifact_roots.append(Path(worktree_path))

    # Step 1: Launch verifier
    try:
        verifier_output = verifier_launcher(
            packet_dir=packet_dir,
            packet_file=packet_file,
            attempt=attempt,
            coder_result=coder_result,
        )
    except Exception as e:
        return PacketHandoffResult(
            ok=False,
            domain_status=DomainStatus.HANDOFF_ERROR.value,
            packet_id=packet_id,
            attempt=attempt,
            verifier=HandoffAgentResult(
                ok=False,
                role="verifier",
                packet_id=packet_id,
                raw_output="",
                parsed_json=None,
                marker_found=False,
                errors=[f"Verifier launcher failed: {e}"],
            ),
            reviewer=None,
            evidence_manifest_path=None,
            review_path=None,
            rework_path=None,
            blocker_reason=f"Verifier launcher failed: {e}",
        )

    # Parse verifier output
    raw_verifier_output = verifier_output.get("raw_output", "")
    parsed_evidence, marker_found, parse_errors = parse_verifier_evidence_marker(raw_verifier_output)

    verifier_result = HandoffAgentResult(
        ok=marker_found and parsed_evidence is not None and len(parse_errors) == 0,
        role="verifier",
        packet_id=packet_id,
        raw_output=raw_verifier_output,
        parsed_json=parsed_evidence,
        marker_found=marker_found,
        errors=parse_errors,
    )

    # If verifier failed, return early
    if not verifier_result.ok:
        return PacketHandoffResult(
            ok=False,
            domain_status=DomainStatus.VERIFIER_FAILED.value,
            packet_id=packet_id,
            attempt=attempt,
            verifier=verifier_result,
            reviewer=None,
            evidence_manifest_path=None,
            review_path=None,
            rework_path=None,
            blocker_reason="Verifier evidence marker parsing failed",
        )

    # Validate evidence
    evidence_ok, evidence_errors = validate_verifier_evidence(
        parsed_evidence,
        packet_dir,
        allowed_artifact_roots,
    )

    if not evidence_ok:
        return PacketHandoffResult(
            ok=False,
            domain_status=DomainStatus.VERIFIER_FAILED.value,
            packet_id=packet_id,
            attempt=attempt,
            verifier=HandoffAgentResult(
                ok=False,
                role="verifier",
                packet_id=packet_id,
                raw_output=raw_verifier_output,
                parsed_json=parsed_evidence,
                marker_found=True,
                errors=evidence_errors,
            ),
            reviewer=None,
            evidence_manifest_path=None,
            review_path=None,
            rework_path=None,
            blocker_reason="Evidence validation failed",
        )

    # Write evidence manifest
    evidence_manifest_path = write_evidence(
        packet_dir=packet_dir,
        attempt=attempt,
        manifest=parsed_evidence,
    )

    # Step 2: Launch reviewer
    try:
        reviewer_output = reviewer_launcher(
            packet_dir=packet_dir,
            packet_file=packet_file,
            attempt=attempt,
            coder_result=coder_result,
            verifier_result=parsed_evidence,
        )
    except Exception as e:
        return PacketHandoffResult(
            ok=False,
            domain_status=DomainStatus.HANDOFF_ERROR.value,
            packet_id=packet_id,
            attempt=attempt,
            verifier=verifier_result,
            reviewer=HandoffAgentResult(
                ok=False,
                role="reviewer",
                packet_id=packet_id,
                raw_output="",
                parsed_json=None,
                marker_found=False,
                errors=[f"Reviewer launcher failed: {e}"],
            ),
            evidence_manifest_path=str(evidence_manifest_path),
            review_path=None,
            rework_path=None,
            blocker_reason=f"Reviewer launcher failed: {e}",
        )

    # Parse reviewer output
    raw_reviewer_output = reviewer_output.get("raw_output", "")
    parsed_decision, decision_marker_found, decision_parse_errors = parse_reviewer_decision_marker(raw_reviewer_output)

    reviewer_result = HandoffAgentResult(
        ok=decision_marker_found and parsed_decision is not None and len(decision_parse_errors) == 0,
        role="reviewer",
        packet_id=packet_id,
        raw_output=raw_reviewer_output,
        parsed_json=parsed_decision,
        marker_found=decision_marker_found,
        errors=decision_parse_errors,
    )

    # If reviewer failed, return early
    if not reviewer_result.ok:
        return PacketHandoffResult(
            ok=False,
            domain_status=DomainStatus.REVIEWER_FAILED.value,
            packet_id=packet_id,
            attempt=attempt,
            verifier=verifier_result,
            reviewer=reviewer_result,
            evidence_manifest_path=str(evidence_manifest_path),
            review_path=None,
            rework_path=None,
            blocker_reason="Reviewer decision marker parsing failed",
        )

    # Extract reviewer decision
    packet_verdict = parsed_decision.get("packet_verdict", "blocked")
    route_classification = parsed_decision.get("route_classification")
    rework_mode = parsed_decision.get("rework_mode")
    reasons = parsed_decision.get("reasons", [])

    # Map verdict to domain status using DomainStatus enum
    domain_status_map = {
        "accepted": DomainStatus.ACCEPTED.value,
        "rework_required": DomainStatus.REWORK_REQUIRED.value,
        "blocked": DomainStatus.BLOCKED.value,
        "escalate_to_architect": "escalate_to_architect",  # Keep legacy value for now
    }
    domain_status = domain_status_map.get(packet_verdict, DomainStatus.BLOCKED.value)

    # Write review artifact
    review_body = f"## Verdict\n\n{packet_verdict}\n\n## Reasons\n\n"
    for reason in reasons:
        review_body += f"- {reason}\n"

    review_path = write_review(
        packet_dir=packet_dir,
        verdict=packet_verdict,
        body=review_body,
        metadata={
            "attempt": attempt,
            "route_classification": route_classification,
            "rework_mode": rework_mode,
        },
    )

    # Write rework artifact if needed
    rework_path = None
    if packet_verdict == "rework_required":
        rework_body = f"## Rework Required\n\n**Attempt:** {attempt}\n\n**Route Classification:** {route_classification}\n\n**Rework Mode:** {rework_mode}\n\n## Reasons\n\n"
        for reason in reasons:
            rework_body += f"- {reason}\n"

        rework_path = write_rework(
            packet_dir=packet_dir,
            attempt=attempt,
            body=rework_body,
            blockers=reasons,
        )

    return PacketHandoffResult(
        ok=domain_status in ["accepted", "rework_required"],
        domain_status=domain_status,
        packet_id=packet_id,
        attempt=attempt,
        verifier=verifier_result,
        reviewer=reviewer_result,
        evidence_manifest_path=str(evidence_manifest_path),
        review_path=str(review_path),
        rework_path=str(rework_path) if rework_path else None,
        route_classification=route_classification,
        rework_mode=rework_mode,
        blocker_reason=None if domain_status in ["accepted", "rework_required"] else reasons[0] if reasons else "Unknown blocker",
    )

#END_BLOCK_HANDOFF_CONTROLLER
