"""
# ============================================================================
# AI_HEADER: GRACE Artifact Validator Module
# ============================================================================
#
# This module provides deterministic validation of artifact references claimed
# in evidence manifests. LLM output is not trusted as existence proof - the
# platform must verify that claimed artifact paths actually exist.
#
# Key Concepts:
# - Artifact paths must be relative or under allowed artifact roots
# - Files must exist if evidence status is "collected"
# - Missing files convert evidence status to "artifact_reference_invalid"
# - Invalid artifact references route to verifier/pipeline (not coder)
# - Validation records file size and hash metadata
#
# Module Dependencies:
# - prefect_grace.platform.evidence_manifest (EvidenceManifest)
# - No Prefect imports (pure validation logic)
#
# ============================================================================
"""

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
import hashlib

# START_MODULE_CONTRACT
# Module: artifact_validator
# Purpose: Validate artifact paths claimed in evidence manifests
# Exports: ArtifactReference, ArtifactValidationResult, validate_artifact_references
# Dependencies: evidence_manifest (EvidenceManifest)
# Constraints: No Prefect imports, deterministic validation, fail-closed
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - Artifact reference and validation result dataclasses
# Block: validator - Validate artifact paths exist and are accessible
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class ArtifactReference:
    """Validated artifact reference.

    Fields:
    - path: Artifact file path (relative or absolute)
    - exists: Whether file exists
    - size: File size in bytes (None if does not exist)
    - hash: SHA-256 hash of file (None if does not exist)
    """
    path: str
    exists: bool
    size: int | None
    hash: str | None

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize ArtifactReference to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with path, exists, size, hash
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "path": self.path,
            "exists": self.exists,
            "size": self.size,
            "hash": self.hash,
        }


@dataclass(frozen=True)
class ArtifactValidationResult:
    """
    Result of artifact validation.

    Fields:
    - ok: Whether all artifacts exist
    - validated_artifacts: List of validated artifact references
    - missing_artifacts: List of missing artifact paths
    """
    ok: bool
    validated_artifacts: list[ArtifactReference] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize ArtifactValidationResult to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with ok, validated_artifacts, missing_artifacts
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "ok": self.ok,
            "validated_artifacts": [ref.to_dict() for ref in self.validated_artifacts],
            "missing_artifacts": list(self.missing_artifacts),
        }

#END_BLOCK_MODELS
#START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# Function: validate_artifact_references
# Purpose: Validate artifact paths claimed in manifest
# Args:
#   - manifest: EvidenceManifest with artifact paths
#   - artifact_roots: List of allowed artifact root directories
# Returns: ArtifactValidationResult with validated artifacts and missing list
# Inputs: EvidenceManifest, list of Path objects
# Side_effects: Reads files from disk to check existence and compute hashes
# Emitted_logs: None
# Error_behavior: Returns validation result with errors, never raises
# Behavior:
#   - For each artifact_path in evidence items with status=collected:
#     - Check path is relative or under allowed artifact roots
#     - Check file exists
#     - Record size and hash if available
#     - Mark as missing if file does not exist
#   - Returns validation result with all checked artifacts
#   - Deterministic validation, fail-closed
# END_FUNCTION_CONTRACT
def validate_artifact_references(
    manifest: Any,  # EvidenceManifest
    artifact_roots: list[Path],
) -> ArtifactValidationResult:
    """
    Validate artifact paths claimed in manifest.

    For each artifact_path in evidence items with status=collected:
    - Check path is relative or under allowed artifact roots
    - Check file exists
    - Record size and hash if available
    - Mark as missing if file does not exist

    Returns validation result with all checked artifacts.
    """
    validated_artifacts = []
    missing_artifacts = []

    # Collect all artifact paths from evidence items with status=collected
    for evidence_item in manifest.evidence:
        if evidence_item.status != "collected":
            continue

        for artifact_path in evidence_item.artifact_paths:
            # Validate artifact path
            artifact_ref = _validate_single_artifact(artifact_path, artifact_roots)
            validated_artifacts.append(artifact_ref)

            if not artifact_ref.exists:
                missing_artifacts.append(artifact_path)

    return ArtifactValidationResult(
        ok=len(missing_artifacts) == 0,
        validated_artifacts=validated_artifacts,
        missing_artifacts=missing_artifacts,
    )


def _validate_single_artifact(
    artifact_path: str,
    artifact_roots: list[Path],
) -> ArtifactReference:
    """
    Validate single artifact path.

    Returns ArtifactReference with exists flag, size, and hash.
    """
    path = Path(artifact_path)

    # Check if path is absolute
    if path.is_absolute():
        # Check if under any allowed artifact root after resolving symlinks and
        # traversal segments.
        under_root = False
        for root in artifact_roots:
            try:
                path.resolve().relative_to(root.resolve())
                under_root = True
                break
            except ValueError:
                continue

        if not under_root and artifact_roots:
            # Path is absolute but not under any allowed root
            return ArtifactReference(
                path=artifact_path,
                exists=False,
                size=None,
                hash=None,
            )

        # Check if absolute path exists
        if not path.exists():
            return ArtifactReference(
                path=artifact_path,
                exists=False,
                size=None,
                hash=None,
            )

        # File exists - record metadata
        size = path.stat().st_size if path.is_file() else None
        file_hash = _compute_file_hash(path) if path.is_file() else None

        return ArtifactReference(
            path=artifact_path,
            exists=True,
            size=size,
            hash=file_hash,
        )
    else:
        # Relative path - try to resolve against each artifact root
        for root in artifact_roots:
            resolved_path = root / path
            try:
                # Check that resolved path is still under root (no traversal)
                resolved_path.resolve().relative_to(root.resolve())
            except ValueError:
                # Path traverses outside root
                continue

            if resolved_path.exists():
                # File exists - record metadata
                size = resolved_path.stat().st_size if resolved_path.is_file() else None
                file_hash = _compute_file_hash(resolved_path) if resolved_path.is_file() else None

                return ArtifactReference(
                    path=artifact_path,
                    exists=True,
                    size=size,
                    hash=file_hash,
                )

        # File not found in any artifact root
        return ArtifactReference(
            path=artifact_path,
            exists=False,
            size=None,
            hash=None,
        )


def _compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

#END_BLOCK_VALIDATOR
