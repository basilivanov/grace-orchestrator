from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.models import FrontendVisualVerdict, ObservabilityVerdict, TestVerdict, VerificationRecord
from prefect_grace.tasks.grace_ids import grace_refs_for_packet
from prefect_grace.tasks.state_store import find_record, update_record, upsert_record

FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"


def record_verification(
    *,
    packet_id: str,
    test_verdict: str,
    observability_verdict: str,
    frontend_visual_verdict: str,
    commands_run: list[str],
    evidence_paths: list[str],
    blocking_issues: list[str],
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    feature_id = packet["feature_id"]
    grace_refs = grace_refs_for_packet(packet)
    evidence_dir = FEATURES_DIR / feature_id / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    verification_path = evidence_dir / f"{packet_id}.verification.md"
    commands_text = "\n".join(f"- {command}" for command in commands_run) or "- none"
    evidence_text = "\n".join(f"- {path}" for path in evidence_paths) or "- none"
    issues_text = "\n".join(f"- {issue}" for issue in blocking_issues) or "- none"
    verification_path.write_text(
        f"# Verifier Evidence: {packet_id}\n\n"
        f"## GRACE IDs\n"
        f"- feature_ref: `{grace_refs['grace_feature_ref']}`\n"
        f"- wave_ref: `{grace_refs['grace_wave_ref']}`\n"
        f"- packet_ref: `{grace_refs['grace_packet_ref']}`\n\n"
        f"## Test Verdict\n{test_verdict}\n\n"
        f"## Observability Verdict\n{observability_verdict}\n\n"
        f"## Frontend Visual Verdict\n{frontend_visual_verdict}\n\n"
        f"## Commands Run\n{commands_text}\n\n"
        f"## Evidence Reviewed\n{evidence_text}\n\n"
        f"## Blocking Issues\n{issues_text}\n",
        encoding="utf-8",
    )
    record = VerificationRecord(
        packet_id=packet_id,
        feature_id=feature_id,
        wave_id=str(packet.get("wave_id") or ""),
        grace_feature_ref=grace_refs["grace_feature_ref"],
        grace_wave_ref=grace_refs["grace_wave_ref"],
        grace_packet_ref=grace_refs["grace_packet_ref"],
        test_verdict=TestVerdict(test_verdict),
        observability_verdict=ObservabilityVerdict(observability_verdict),
        frontend_visual_verdict=FrontendVisualVerdict(frontend_visual_verdict),
        commands_run=commands_run,
        evidence_paths=evidence_paths,
        blocking_issues=blocking_issues,
        verification_path=str(verification_path),
    ).to_dict()
    upsert_record("verifications", "verifications", "packet_id", record, state_root=resolved_state_root)
    update_record(
        "packets",
        "packets",
        "packet_id",
        packet_id,
        {
            "last_verification": record,
        },
        state_root=resolved_state_root,
    )
    return record
