# ############################################################################
# AI_HEADER: context_bundle
# ROLE: Builds minimal context file lists for GRACE packet execution roles.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build minimal context bundles for coder/reviewer/architect roles.
# inputs: Packet directory path, role name, mode (normal/audit).
# returns: List of file paths to include in context.
# side_effects: None (pure path resolution).
# emitted_logs: None.
# error_behavior: Returns empty list if packet directory invalid.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: build_context_bundle
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from prefect_grace.platform.packet_artifact_layout import (
    resolve_packet_layout,
    latest_review,
    latest_evidence_manifest,
    latest_rework,
)


_REVIEW_SUFFIXES = {".yaml", ".yml", ".md"}

#START_BLOCK_CONTEXT_BUNDLE
# START_FUNCTION_CONTRACT
# name: build_context_bundle
# purpose: Build minimal file list for a role's context.
# inputs:
#   packet_dir: Path to packet directory.
#   role: Role name (coder, reviewer, architect).
#   mode: Context mode (normal, audit).
# returns: List of file paths to include in context.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns empty list if packet_dir invalid.
# END_FUNCTION_CONTRACT
def build_context_bundle(
    packet_dir: Path,
    role: str = "coder",
    mode: str = "normal",
) -> list[Path]:
    if not packet_dir.exists():
        return []

    layout = resolve_packet_layout(packet_dir)
    bundle: list[Path] = []

    # Always include source packet and summary
    if layout.source_packet.exists():
        bundle.append(layout.source_packet)
    if layout.summary.exists():
        bundle.append(layout.summary)

    if mode == "audit":
        # Audit mode: include full history
        if layout.reviews_dir.exists():
            bundle.extend(
                path for path in sorted(layout.reviews_dir.glob("review-*"))
                if path.suffix.lower() in _REVIEW_SUFFIXES
            )
        if layout.evidence_dir.exists():
            for attempt_dir in sorted(layout.evidence_dir.glob("attempt-*")):
                manifest = attempt_dir / "evidence_manifest.json"
                if manifest.exists():
                    bundle.append(manifest)
        if layout.rework_dir.exists():
            bundle.extend(sorted(layout.rework_dir.glob("attempt-*.md")))
    else:
        # Normal mode: latest files only
        if role == "coder":
            # Coder needs: latest review, latest rework, latest evidence
            review = latest_review(layout)
            if review:
                bundle.append(review)
            rework = latest_rework(layout)
            if rework:
                bundle.append(rework)
            evidence = latest_evidence_manifest(layout)
            if evidence:
                bundle.append(evidence)

        elif role == "reviewer":
            # Reviewer needs: latest evidence manifest
            evidence = latest_evidence_manifest(layout)
            if evidence:
                bundle.append(evidence)

        elif role == "architect":
            # Architect needs: latest review, latest rework
            review = latest_review(layout)
            if review:
                bundle.append(review)
            rework = latest_rework(layout)
            if rework:
                bundle.append(rework)

    return bundle

#END_BLOCK_CONTEXT_BUNDLE
