# ############################################################################
# AI_HEADER: packet_artifact_layout
# ROLE: Resolves packet artifact directory layout for GRACE orchestration.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide typed model and helpers for packet artifact directory layout.
# inputs: Packet directory path.
# returns: PacketArtifactLayout with resolved paths.
# side_effects: None (pure path resolution).
# emitted_logs: None.
# error_behavior: Returns None for missing artifacts.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketArtifactLayout
#   - function: resolve_packet_layout
#   - function: latest_review
#   - function: latest_evidence_manifest
#   - function: latest_rework
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_REVIEW_STEM_RE = re.compile(r"^review-(\d+)$")
_REVIEW_SUFFIX_RANK = {
    ".yaml": 0,
    ".yml": 1,
    ".md": 2,
}

#START_BLOCK_MODELS
@dataclass
class PacketArtifactLayout:
    """
    Typed model for packet artifact directory layout.

    Separates source contract (EXECUTION_PACKET.md) from runtime artifacts
    (SUMMARY.md, REVIEWS/, EVIDENCE/, REWORK/).
    """
    packet_dir: Path
    source_packet: Path
    summary: Path
    reviews_dir: Path
    evidence_dir: Path
    rework_dir: Path

#END_BLOCK_MODELS
#START_BLOCK_RESOLVERS
# START_FUNCTION_CONTRACT
# name: resolve_packet_layout
# purpose: Resolve packet artifact directory layout from packet directory.
# inputs:
#   packet_dir: Path to packet directory.
# returns: PacketArtifactLayout with resolved paths.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def resolve_packet_layout(packet_dir: Path) -> PacketArtifactLayout:
    return PacketArtifactLayout(
        packet_dir=packet_dir,
        source_packet=packet_dir / "EXECUTION_PACKET.md",
        summary=packet_dir / "SUMMARY.md",
        reviews_dir=packet_dir / "REVIEWS",
        evidence_dir=packet_dir / "EVIDENCE",
        rework_dir=packet_dir / "REWORK",
    )


# START_FUNCTION_CONTRACT
# name: latest_review
# purpose: Find latest review file in REVIEWS/ directory, preferring YAML artifacts.
# inputs:
#   layout: PacketArtifactLayout with resolved paths.
# returns: Path to latest review file, or None if no reviews exist.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None if REVIEWS/ does not exist or has no numeric review artifacts.
# END_FUNCTION_CONTRACT
def latest_review(layout: PacketArtifactLayout) -> Path | None:
    if not layout.reviews_dir.exists():
        return None

    candidates: list[tuple[int, int, Path]] = []
    for path in layout.reviews_dir.glob("review-*"):
        rank = _REVIEW_SUFFIX_RANK.get(path.suffix.lower())
        if rank is None:
            continue
        match = _REVIEW_STEM_RE.match(path.stem)
        if not match:
            continue
        candidates.append((int(match.group(1)), rank, path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1], item[2].name))
    return candidates[0][2]


# START_FUNCTION_CONTRACT
# name: latest_evidence_manifest
# purpose: Find latest evidence manifest in EVIDENCE/ directory.
# inputs:
#   layout: PacketArtifactLayout with resolved paths.
# returns: Path to latest evidence manifest, or None if no evidence exists.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None if EVIDENCE/ does not exist or is empty.
# END_FUNCTION_CONTRACT
def latest_evidence_manifest(layout: PacketArtifactLayout) -> Path | None:
    if not layout.evidence_dir.exists():
        return None

    attempt_dirs = sorted(layout.evidence_dir.glob("attempt-*"))
    if not attempt_dirs:
        return None

    latest_attempt = attempt_dirs[-1]
    manifest = latest_attempt / "evidence_manifest.json"
    return manifest if manifest.exists() else None


# START_FUNCTION_CONTRACT
# name: latest_rework
# purpose: Find latest rework instruction file in REWORK/ directory.
# inputs:
#   layout: PacketArtifactLayout with resolved paths.
# returns: Path to latest rework file, or None if no rework exists.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns None if REWORK/ does not exist or is empty.
# END_FUNCTION_CONTRACT
def latest_rework(layout: PacketArtifactLayout) -> Path | None:
    if not layout.rework_dir.exists():
        return None

    rework_files = sorted(layout.rework_dir.glob("attempt-*.md"))
    return rework_files[-1] if rework_files else None

#END_BLOCK_RESOLVERS
