from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.models import DecisionRecord, PacketStatus, ReasoningProfile, ReviewRecord, ReviewVerdict, WaveReviewRecord, WaveVerdict
from prefect_grace.tasks.feature_bootstrap import create_packet, sync_packet_file
from prefect_grace.tasks.grace_ids import grace_refs_for_packet
from prefect_grace.tasks.state_store import find_record, load_state, update_record, upsert_record

FEATURES_DIR = Path(__file__).resolve().parents[1] / "packets"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
STATE_ROOT = Path(__file__).resolve().parents[1] / "state"
LIGHT_RESUME_MAX_ATTEMPTS = 1
_LIGHT_RESUME_BLOCKER_MARKERS = (
    "architect decision",
    "business",
    "compliance",
    "decomposition",
    "dependency graph",
    "legal",
    "multi-wave",
    "multiple waves",
    "planner",
    "pricing",
    "product decision",
    "schema migration",
    "scope expansion",
    "slice boundary",
    "split packet",
    "user decision",
    "wave graph",
)


def _normalize_rework_mode(value: Any) -> str:
    resolved = str(value or "bounded_fresh").strip().lower().replace("-", "_")
    aliases = {
        "light": "light_resume",
        "resume": "light_resume",
        "packet_local_resume": "light_resume",
        "small_fix": "light_resume",
        "smallfix": "light_resume",
        "fresh": "bounded_fresh",
        "bounded": "bounded_fresh",
        "fresh_packet": "bounded_fresh",
        "execution": "bounded_fresh",
        "rework": "bounded_fresh",
        "gate": "decision_required",
        "decision": "decision_required",
        "gate_decision": "decision_required",
        "gate-decision": "decision_required",
        "architect_decision": "decision_required",
    }
    resolved = aliases.get(resolved, resolved)
    return resolved if resolved in {"light_resume", "bounded_fresh", "decision_required"} else "bounded_fresh"


def _light_resume_attempt_count(source_packet_id: str, *, state_root: Path | str | None = None) -> int:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packets = list(load_state("packets", state_root=resolved_state_root).get("packets") or [])
    persisted_attempt = 0
    try:
        source_packet = find_record("packets", "packets", "packet_id", source_packet_id, state_root=resolved_state_root)
        persisted_attempt = int(
            source_packet.get("light_resume_attempt")
            or dict(source_packet.get("execution_hints") or {}).get("light_resume_attempt")
            or 0
        )
    except (KeyError, TypeError, ValueError):
        persisted_attempt = 0
    derived_attempts = sum(
        1
        for packet in packets
        if str(packet.get("light_resume_source_packet_id") or "") == source_packet_id
        and str(packet.get("rework_mode") or "") == "light_resume"
    )
    return max(persisted_attempt, derived_attempts)


def _light_resume_downgrade_reason(
    packet: dict[str, Any],
    reasons: list[str],
    *,
    write_scope: list[str] | None = None,
    state_root: Path | str | None = None,
) -> str | None:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet_id = str(packet.get("packet_id") or "").strip()
    if str(packet.get("role") or "").strip().lower() != "coder":
        return "light_resume is only allowed for coder packets"
    if str(packet.get("parent_packet_id") or "").strip():
        return "light_resume cannot target an existing rework packet"
    cleaned_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if len(cleaned_reasons) > 2:
        return "light_resume is limited to at most two small blocker reasons"
    lowered = " ".join(cleaned_reasons).lower()
    if any(marker in lowered for marker in _LIGHT_RESUME_BLOCKER_MARKERS):
        return "light_resume is not allowed for decomposition, business, or broad-scope blockers"
    cleaned_write_scope = [str(item).strip() for item in write_scope or [] if str(item).strip()]
    if len(cleaned_write_scope) > 3:
        return "light_resume is limited to narrow packet-local write scope"
    if packet_id and _light_resume_attempt_count(packet_id, state_root=resolved_state_root) >= LIGHT_RESUME_MAX_ATTEMPTS:
        return "light_resume attempt limit reached for the source packet"
    return None


def record_review(
    *,
    packet_id: str,
    verdict: ReviewVerdict,
    reasons: list[str],
    reviewer: str = "reviewer",
    follow_up_action: str = "none",
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    feature_id = packet["feature_id"]
    grace_refs = grace_refs_for_packet(packet)
    review_dir = FEATURES_DIR / feature_id / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / f"{packet_id}.review.md"
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- none"
    review_path.write_text(
        f"# Packet Review: {packet_id}\n\n"
        f"## GRACE IDs\n"
        f"- feature_ref: `{grace_refs['grace_feature_ref']}`\n"
        f"- wave_ref: `{grace_refs['grace_wave_ref']}`\n"
        f"- packet_ref: `{grace_refs['grace_packet_ref']}`\n\n"
        f"## Verdict\n{verdict.value}\n\n"
        f"## Acceptance Check\n- see packet acceptance criteria\n\n"
        f"## Blockers\n{reason_text}\n\n"
        f"## Follow-up Action\n{follow_up_action}\n",
        encoding="utf-8",
    )
    record = ReviewRecord(
        packet_id=packet_id,
        feature_id=feature_id,
        wave_id=str(packet.get("wave_id") or ""),
        grace_feature_ref=grace_refs["grace_feature_ref"],
        grace_wave_ref=grace_refs["grace_wave_ref"],
        grace_packet_ref=grace_refs["grace_packet_ref"],
        verdict=verdict,
        reasons=reasons,
        reviewer=reviewer,
        follow_up_action=follow_up_action,
        review_path=str(review_path),
    ).to_dict()
    upsert_record("reviews", "reviews", "packet_id", record, state_root=resolved_state_root)
    update_record(
        "packets",
        "packets",
        "packet_id",
        packet_id,
        {
            "status": verdict.value,
            "last_review": record,
        },
        state_root=resolved_state_root,
    )
    return record


def create_rework_from_review(packet_id: str, reasons: list[str], *, state_root: Path | str | None = None) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    inherited_execution_hints = dict(packet.get("execution_hints") or {})
    blocker_summary = "; ".join(reasons) if reasons else "Reviewer requested localized rework."
    return create_packet(
        feature_id=packet["feature_id"],
        wave_id=packet["wave_id"],
        title=f"Rework {packet['title']}",
        role=packet.get("role") or "coder",
        reasoning=ReasoningProfile(packet.get("reasoning") or ReasoningProfile.HIGH.value),
        summary=f"Address reviewer blockers from {packet_id}: {blocker_summary}",
        write_scope=[
            f"Only the files required to address blockers from `{packet_id}`.",
        ],
        inputs=[
            f"Parent packet `{packet_id}`.",
            "Reviewer blocker notes.",
        ],
        acceptance_criteria=[
            "Reviewer blockers are addressed directly.",
            "No unrelated scope expansion.",
            "Updated verification evidence is ready for re-review.",
        ],
        verification_profile={
            "backend": "rerun the minimally sufficient backend profile if backend code changed",
            "frontend": "rerun targeted Playwright if UI changed",
            "observability": "repeat post-test evidence review for the affected flow",
        },
        reviewer_gate=[
            "All blocker reasons are addressed.",
            "No new regressions are introduced in the scoped flow.",
        ],
        dependencies=[packet_id],
        packet_type="rework",
        notes=[
            "This is a localized rework packet created from reviewer blockers.",
        ],
        parent_packet_id=packet_id,
        execution_hints=inherited_execution_hints,
        status=PacketStatus.READY,
        state_root=resolved_state_root,
    )


def create_direct_rework_from_architect(
    packet_id: str,
    reasons: list[str],
    *,
    reviewer_packet_id: str | None = None,
    rework_mode: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    write_scope: list[str] | None = None,
    inputs: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    verification_profile: dict[str, Any] | None = None,
    reviewer_gate: list[str] | None = None,
    notes: list[str] | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    inherited_execution_hints = dict(packet.get("execution_hints") or {})
    requested_rework_mode = _normalize_rework_mode(rework_mode)
    resolved_rework_mode = requested_rework_mode
    light_resume_downgrade_reason = None
    if requested_rework_mode == "light_resume":
        light_resume_downgrade_reason = _light_resume_downgrade_reason(
            packet,
            reasons,
            write_scope=write_scope,
            state_root=resolved_state_root,
        )
        if light_resume_downgrade_reason:
            resolved_rework_mode = "bounded_fresh"
    if requested_rework_mode == "light_resume" and resolved_rework_mode == "light_resume":
        blocker_summary = "; ".join(reasons) if reasons else "Architect requested bounded light resume."
        rework_title = str(title or f"Light Resume {packet['title']}").strip()
        rework_summary = str(summary or f"Resume the existing coder packet for {packet_id}: {blocker_summary}").strip()
        attempt = _light_resume_attempt_count(packet_id, state_root=resolved_state_root) + 1
        updated_execution_hints = {
            **inherited_execution_hints,
            "resume_strategy": "packet_parent",
            "resume_parent_packet_id": packet_id,
            "rework_mode": resolved_rework_mode,
            "light_resume_stage": True,
            "light_resume_scope": "packet_local",
            "light_resume_source_packet_id": packet_id,
            "light_resume_attempt": attempt,
            "light_resume_max_attempts": LIGHT_RESUME_MAX_ATTEMPTS,
            "light_resume_title": rework_title,
            "light_resume_summary": rework_summary,
            "light_resume_write_scope": list(
                write_scope
                or [f"Only the files required to address architect-bounded blockers from `{packet_id}`."]
            ),
            "light_resume_inputs": list(
                inputs
                or [
                    f"Parent packet `{packet_id}`.",
                    "Reviewer blocker notes.",
                    "Architect direct rework packet.",
                ]
            ),
            "light_resume_acceptance_criteria": list(
                acceptance_criteria
                or [
                    "Architect-bounded blockers are addressed directly.",
                    "No unrelated scope expansion.",
                    "Updated verification evidence is ready for re-review.",
                ]
            ),
            "light_resume_reviewer_gate": list(
                reviewer_gate
                or [
                    "All architect-bounded blocker reasons are addressed.",
                    "No new regressions are introduced in the scoped flow.",
                ]
            ),
            "light_resume_notes": list(
                notes
                or [
                    "This packet was resumed in-place as an architect-bounded light rework stage.",
                ]
            ),
            "light_resume_reasons": [str(reason).strip() for reason in reasons if str(reason).strip()],
            "light_resume_verification_profile": dict(
                verification_profile
                or {
                    "backend": "rerun the minimally sufficient backend profile if backend code changed",
                    "frontend": "rerun targeted Playwright if UI changed",
                    "observability": "repeat post-test evidence review for the affected flow",
                }
            ),
        }
        updated_packet = update_record(
            "packets",
            "packets",
            "packet_id",
            packet_id,
            {
                "execution_hints": updated_execution_hints,
                "review_target_packet_id": packet_id,
                "origin_reviewer_packet_id": str(reviewer_packet_id or "").strip() or None,
                "route_classification": "self_resolvable_rework",
                "requested_rework_mode": requested_rework_mode,
                "rework_mode": resolved_rework_mode,
                "light_resume_stage": True,
                "light_resume_source_packet_id": packet_id,
                "light_resume_attempt": attempt,
                "light_resume_max_attempts": LIGHT_RESUME_MAX_ATTEMPTS,
            },
            state_root=resolved_state_root,
        )
        return sync_packet_file(updated_packet)
    if resolved_rework_mode != "light_resume":
        inherited_execution_hints = {
            **inherited_execution_hints,
            "rework_mode": resolved_rework_mode,
        }
        if requested_rework_mode != resolved_rework_mode:
            inherited_execution_hints["requested_rework_mode"] = requested_rework_mode
            inherited_execution_hints["light_resume_downgrade_reason"] = light_resume_downgrade_reason
    blocker_summary = "; ".join(reasons) if reasons else "Architect requested bounded direct rework."
    rework_title = str(title or f"Direct Rework {packet['title']}").strip()
    rework_summary = str(summary or f"Address architect-bounded rework for {packet_id}: {blocker_summary}").strip()
    rework_packet = create_packet(
        feature_id=packet["feature_id"],
        wave_id=packet["wave_id"],
        title=rework_title,
        role=packet.get("role") or "coder",
        reasoning=ReasoningProfile(packet.get("reasoning") or ReasoningProfile.HIGH.value),
        summary=rework_summary,
        write_scope=write_scope
        or [
            f"Only the files required to address architect-bounded blockers from `{packet_id}`.",
        ],
        inputs=inputs
        or [
            f"Parent packet `{packet_id}`.",
            "Reviewer blocker notes.",
            "Architect direct rework packet.",
        ],
        acceptance_criteria=acceptance_criteria
        or [
            "Architect-bounded blockers are addressed directly.",
            "No unrelated scope expansion.",
            "Updated verification evidence is ready for re-review.",
        ],
        verification_profile=verification_profile
        or {
            "backend": "rerun the minimally sufficient backend profile if backend code changed",
            "frontend": "rerun targeted Playwright if UI changed",
            "observability": "repeat post-test evidence review for the affected flow",
        },
        reviewer_gate=reviewer_gate
        or [
            "All architect-bounded blocker reasons are addressed.",
            "No new regressions are introduced in the scoped flow.",
        ],
        dependencies=[packet_id],
        packet_type="rework",
        notes=notes
        or [
            "This is an architect-bounded direct rework packet created after reviewer blockers.",
        ],
        parent_packet_id=packet_id,
        execution_hints=inherited_execution_hints,
        status=PacketStatus.READY,
        state_root=resolved_state_root,
    )
    updated_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        rework_packet["packet_id"],
        {
            "review_target_packet_id": packet_id,
            "origin_reviewer_packet_id": str(reviewer_packet_id or "").strip() or None,
            "route_classification": "self_resolvable_rework",
            "requested_rework_mode": requested_rework_mode,
            "rework_mode": resolved_rework_mode,
            "light_resume_source_packet_id": packet_id if resolved_rework_mode == "light_resume" else None,
            "light_resume_attempt": (
                inherited_execution_hints.get("light_resume_attempt")
                if resolved_rework_mode == "light_resume"
                else None
            ),
            "light_resume_max_attempts": LIGHT_RESUME_MAX_ATTEMPTS if resolved_rework_mode == "light_resume" else None,
            "light_resume_downgrade_reason": light_resume_downgrade_reason,
        },
        state_root=resolved_state_root,
    )
    return sync_packet_file(updated_packet)


def create_architect_rework_packet_from_review(
    packet_id: str,
    reviewer_packet_id: str,
    reasons: list[str],
    *,
    route_classification: str | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    inherited_execution_hints = dict(packet.get("execution_hints") or {})
    blocker_summary = "; ".join(reasons) if reasons else "Reviewer requested architect routing."
    title = f"Architect Rework {packet['title']}"
    summary = (
        f"Review reviewer blockers for {packet_id} and decide whether to issue a bounded direct coder rework, "
        f"escalate to the user, or request planner decomposition: {blocker_summary}"
    )
    architect_packet = create_packet(
        feature_id=packet["feature_id"],
        wave_id=packet["wave_id"],
        title=title,
        role="architect",
        reasoning=ReasoningProfile.XHIGH,
        summary=summary,
        write_scope=[
            "Architect routing decision and direct rework specification only.",
        ],
        inputs=[
            f"Target coder packet `{packet_id}`.",
            f"Reviewer packet `{reviewer_packet_id}`.",
            "Reviewer blocker notes and latest verifier evidence.",
        ],
        acceptance_criteria=[
            "Architect classifies the blocker as self-resolvable, requires_user_decision, or requires_planner.",
            "If self-resolvable, architect returns a bounded direct rework packet for coder.",
            "If escalation is required, architect states the narrowest blocking reason.",
        ],
        verification_profile={
            "backend": "not required",
            "frontend": "not required",
            "observability": "artifact review only",
        },
        reviewer_gate=[
            "Do not widen scope beyond the reviewer blockers.",
            "Prefer bounded coder rework over user escalation when the blocker is self-resolvable.",
        ],
        dependencies=[packet_id, reviewer_packet_id],
        packet_type="rework",
        notes=[
            "Return FINAL_DIRECT_REWORK_PACKET_JSON.",
            "Use route_classification=self_resolvable_rework when the next step is a bounded coder packet.",
            "Use rework_mode=light_resume only for small packet-local fixes that can safely reuse coder context.",
            "Use rework_mode=bounded_fresh for bounded fixes that still need a fresh coder packet.",
            "Use rework_mode=decision_required when the blocker should not resume coder work directly.",
            "Use requires_user_decision only for true business/product/user decisions.",
            "Use requires_planner only when packet graph or decomposition must change.",
        ],
        parent_packet_id=packet_id,
        execution_hints=inherited_execution_hints,
        status=PacketStatus.READY,
        state_root=resolved_state_root,
    )
    updated_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        architect_packet["packet_id"],
        {
            "review_target_packet_id": packet_id,
            "origin_reviewer_packet_id": reviewer_packet_id,
            "route_classification_hint": str(route_classification or "").strip() or None,
        },
        state_root=resolved_state_root,
    )
    return sync_packet_file(updated_packet)


def create_rework_bundle_from_review(
    *,
    packet_id: str,
    reviewer_packet_id: str,
    reasons: list[str],
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    rework_packet = create_rework_from_review(packet_id, reasons, state_root=resolved_state_root)
    reviewer_packet = find_record("packets", "packets", "packet_id", reviewer_packet_id, state_root=resolved_state_root)
    verifier_packet_id = next(
        (
            dependency
            for dependency in reviewer_packet.get("dependencies") or []
            if str(find_record("packets", "packets", "packet_id", dependency, state_root=resolved_state_root).get("role") or "") == "verifier"
        ),
        None,
    )
    verifier_hints = dict(rework_packet.get("execution_hints") or {})
    verifier_profile = {}
    if verifier_packet_id:
        verifier_source = find_record("packets", "packets", "packet_id", verifier_packet_id, state_root=resolved_state_root)
        verifier_hints = {**verifier_hints, **dict(verifier_source.get("execution_hints") or {})}
        verifier_profile = dict(verifier_source.get("verification_profile") or {})

    verifier_packet = create_packet(
        feature_id=rework_packet["feature_id"],
        wave_id=rework_packet["wave_id"],
        title=f"Verifier Rework {rework_packet['title']}",
        role="verifier",
        reasoning=ReasoningProfile.MEDIUM,
        summary=f"Validate the localized rework for `{packet_id}` and capture fresh evidence.",
        write_scope=["Verification notes and evidence references only."],
        inputs=[rework_packet["packet_id"], reviewer_packet_id],
        acceptance_criteria=[
            "Commands run are recorded for the rework packet.",
            "Evidence paths are refreshed for the reworked scope.",
            "Observability verdict is explicit for the rework.",
        ],
        verification_profile=verifier_profile
        or {
            "backend": "rerun minimally sufficient backend checks for the reworked scope",
            "frontend": "rerun targeted frontend checks if UI changed",
            "observability": "repeat post-test digest, trace, and replay review",
        },
        reviewer_gate=[
            "Evidence must correspond to the rework packet, not the original attempt.",
            "Missing visual proof remains a blocker for UI work.",
        ],
        dependencies=[rework_packet["packet_id"]],
        packet_type="rework",
        notes=["This verifier packet was auto-created from reviewer blockers."],
        parent_packet_id=packet_id,
        execution_hints=verifier_hints,
        status=PacketStatus.READY,
        state_root=resolved_state_root,
    )

    rework_reviewer_packet = create_packet(
        feature_id=rework_packet["feature_id"],
        wave_id=rework_packet["wave_id"],
        title=f"Reviewer Rework {rework_packet['title']}",
        role="reviewer",
        reasoning=ReasoningProfile.XHIGH,
        summary=f"Review whether the localized rework for `{packet_id}` addressed the reviewer blockers.",
        write_scope=["Review verdict and blocker notes only."],
        inputs=[rework_packet["packet_id"], verifier_packet["packet_id"]],
        acceptance_criteria=[
            "Exactly one verdict is returned.",
            "The original blockers are either resolved or explicitly remain.",
            "No unrelated scope expansion is accepted.",
        ],
        verification_profile={
            "backend": "consume verifier evidence",
            "frontend": "consume verifier evidence",
            "observability": "consume verifier evidence",
        },
        reviewer_gate=[
            "Assess only the original blocker scope.",
            "Escalate only if blockers imply decomposition or business changes.",
        ],
        dependencies=[rework_packet["packet_id"], verifier_packet["packet_id"]],
        packet_type="gate_decision",
        notes=["This reviewer packet was auto-created from reviewer blockers."],
        parent_packet_id=packet_id,
        status=PacketStatus.READY,
        state_root=resolved_state_root,
    )
    rework_reviewer_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        rework_reviewer_packet["packet_id"],
        {
            "review_target_packet_id": rework_packet["packet_id"],
            "execution_hints": dict(rework_packet.get("execution_hints") or {}),
        },
        state_root=resolved_state_root,
    )
    rework_reviewer_packet = sync_packet_file(rework_reviewer_packet)
    return {
        "rework": rework_packet,
        "verifier": verifier_packet,
        "reviewer": rework_reviewer_packet,
    }


def create_architect_decision_from_review(
    packet_id: str,
    reasons: list[str],
    *,
    requested_action: str | None = None,
    route_classification: str | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=resolved_state_root)
    feature_id = packet["feature_id"]
    decision_id = f"{packet_id}-ARCH-DECISION"
    decision_dir = FEATURES_DIR / feature_id / "decisions"
    decision_dir.mkdir(parents=True, exist_ok=True)
    decision_path = decision_dir / f"{decision_id}.md"
    classification = str(route_classification or "").strip() or None
    action = (
        str(requested_action).strip()
        if requested_action
        else (
            "Prepare a new bounded direct rework packet for coder if the blocker is self-resolvable without user/product input."
            if classification == "self_resolvable_rework"
            else (
                "Escalate to the user because the blocker requires architect/business decision."
                if classification == "requires_user_decision"
                else "Update GRACE artifacts and reslice packets if planner decomposition is required."
            )
        )
    )
    summary = f"Architect routing decision required for {packet_id}"
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- reviewer did not provide explicit reasons"
    decision_path.write_text(
        f"# Architect Decision: {decision_id}\n\n"
        f"## Source Packet\n{packet_id}\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Route Classification\n{classification or '-'}\n\n"
        f"## Reasons\n{reason_text}\n\n"
        f"## Requested Action\n- {action}\n",
        encoding="utf-8",
    )
    record = DecisionRecord(
        decision_id=decision_id,
        feature_id=feature_id,
        source_packet_id=packet_id,
        summary=summary,
        reasons=reasons,
        decision_path=str(decision_path),
    ).to_dict()
    record["route_classification"] = classification
    record["requested_action"] = action
    return upsert_record("decisions", "decisions", "decision_id", record, state_root=resolved_state_root)


def record_wave_review(
    *,
    feature_id: str,
    wave_id: str,
    architect_packet_id: str,
    verdict: WaveVerdict,
    reasons: list[str],
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    review_dir = FEATURES_DIR / feature_id / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / f"{wave_id}.architect-review.md"
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- none"
    review_path.write_text(
        f"# Wave Architect Review: {wave_id}\n\n"
        f"## Architect Packet\n{architect_packet_id}\n\n"
        f"## Verdict\n{verdict.value}\n\n"
        f"## Reasons\n{reason_text}\n\n"
        f"## Scope\n- wave acceptance including UX, visual proof, and business fit\n",
        encoding="utf-8",
    )
    record = WaveReviewRecord(
        feature_id=feature_id,
        wave_id=wave_id,
        architect_packet_id=architect_packet_id,
        verdict=verdict,
        reasons=reasons,
        review_path=str(review_path),
    ).to_dict()
    upsert_record("wave_reviews", "wave_reviews", "architect_packet_id", record, state_root=resolved_state_root)
    update_record(
        "packets",
        "packets",
        "packet_id",
        architect_packet_id,
        {
            "last_wave_review": record,
        },
        state_root=resolved_state_root,
    )
    return record
