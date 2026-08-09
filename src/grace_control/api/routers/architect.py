# ############################################################################
# AI_HEADER: architect_router
# ROLE: FastAPI compatibility wrapper — delegates to FeatureIntakeService +
#       FeaturePlanningService. No duplicate planning implementation.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Thin compatibility wrapper for old /api/architect/plan callers.
#          For pre-defined waves: creates feature, validates DAG, materializes.
#          For business text: creates feature, starts background planning.
# inputs: HTTP POST with feature_spec dict.
# returns: JSON with feature_id, waves/packets, context.
# side_effects: DB inserts via FeatureIntakeService / FeaturePlanningService.
# error_behavior: 422 on DAG failure, 500 on service error.
# END_MODULE_CONTRACT

from __future__ import annotations

import asyncio
import re as _re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from grace_control.core.dag_validator import validate_dag
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, Wave
from grace_control.services.feature_intake_service import FeatureIntakeService
from grace_control.services.feature_planning_service import (
    FeaturePlanningService,
    normalize_architect_plan,
)

router = APIRouter()
_log = GraceLogger("architect")

from grace_control.config.settings import settings


@router.post("/plan")
async def create_plan(request: dict) -> dict:
    spec = request["feature_spec"]
    title = spec.get("title", "")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    has_waves = bool(spec.get("waves"))
    target_repo_root = spec.get("target_repo_root", "") or settings.target_repo_root
    is_async = spec.get("background", True)
    _origin = spec.get("origin", "")
    _session_id = spec.get("session_id", "")
    _self_improvement = spec.get("self_improvement", False)

    _approval_mode = spec.get("approval_mode", "auto")

    slug = _slugify(title)

    if has_waves:
        # ── Pre-defined waves: validate before creating durable feature state ──
        plan = {
            "waves": spec.get("waves", []),
            "constraints": spec.get("constraints", {}),
            "verification": spec.get("verification", {"t0": [], "t1": [], "t2": []}),
        }
        try:
            plan = normalize_architect_plan(plan)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"errors": [str(exc)]}) from exc

        dag_packets = _build_predefined_dag_packets(plan["waves"])
        if dag_packets:
            vresult = validate_dag(
                dag_packets,
                strict_wave_order=not bool(plan.get("_legacy_packet_contract")),
            )
            if not vresult.valid:
                detail = {"errors": vresult.errors}
                if vresult.cycles:
                    detail["cycles"] = vresult.cycles
                raise HTTPException(status_code=422, detail=detail)

    # FeatureIntakeService + FeaturePlanningService path.  Pre-defined plans
    # reach this point only after deterministic DAG validation succeeds.
    with get_db() as db:
        intake = FeatureIntakeService(db)
        result = intake.create_feature(
            title=title,
            description=spec.get("description", ""),
            target_repo_root=target_repo_root,
            mode="draft_plan",
            origin=_origin or "business",
            self_improvement=_self_improvement or _origin == "self_evolution",
            trace_id=_session_id,
            approval_mode=_approval_mode,
        )
        feature_id = result["feature_id"]

    if has_waves:
        with get_db() as db:
            feat = db.query(Feature).filter_by(id=feature_id).first()
            spec_json = dict(feat.spec_json) if feat.spec_json else {}
            spec_json["plan_json"] = plan
            feat.spec_json = spec_json
            feat.status = "PLAN_READY"
            db.commit()

            planning = FeaturePlanningService(db)
            approval = planning.approve_plan(feature_id)

        # Build packet_summaries and packet_ids from approval
        wave_ids = []
        with get_db() as db:
            waves = db.query(Wave).filter_by(feature_id=feature_id).order_by(Wave.order).all()
            wave_ids = [w.id for w in waves]

        packet_ids = list(approval.get("packet_ids", []))
        packet_summaries = []
        if packet_ids:
            with get_db() as db:
                pkts = db.query(Packet).filter(Packet.id.in_(packet_ids)).all()
                pkt_map = {p.id: p for p in pkts}
                for pid in packet_ids:
                    pkt = pkt_map.get(pid)
                    if pkt:
                        packet_summaries.append({
                            "id": pkt.id,
                            "slug": pkt.slug,
                            "title": pkt.title,
                            "wave_id": pkt.wave_id,
                        })

        return {
            "data": {
                "feature_id": feature_id,
                "feature_slug": slug,
                "slug": slug,
                "waves_count": approval.get("waves_count", len(plan["waves"])),
                "packets_count": len(packet_ids),
                "packets": packet_ids,
                "packet_ids": packet_ids,
                "packet_summaries": packet_summaries,
                "context": {},
                "generated": False,
            },
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }

    # ── Business text: background or sync planning ──
    async def _background_planning():
        try:
            with get_db() as bg_db:
                planning = FeaturePlanningService(bg_db)
                context = await planning.run_context_builder(feature_id, target_repo_root)
                if context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO":
                    _log.error("architect_skipped_due_to_mutation", feature_id=feature_id)
                    return
                await planning.run_architect(feature_id, context, target_repo_root)
                _log.info("architect_bg_completed", feature_id=feature_id)
            if _approval_mode == "auto":
                with get_db() as auto_db:
                    auto_planning = FeaturePlanningService(auto_db)
                    result = auto_planning.approve_plan(feature_id)
                    _log.info("architect_bg_auto_approved", feature_id=feature_id,
                              approval_mode="auto", status=result.get("status"))
        except Exception as e:
            _log.error("architect_bg_failed", feature_id=feature_id, error=str(e)[:200])
            with get_db() as err_db:
                feat = err_db.query(Feature).filter_by(id=feature_id).first()
                if feat:
                    feat.status = "PLAN_FAILED"

    if is_async:
        asyncio.create_task(_background_planning())
        return {"feature_id": feature_id, "slug": slug, "status": "planning", "immediate": True}

    # Synchronous: run context + architect now
    with get_db() as db:
        planning = FeaturePlanningService(db)
        context = await planning.run_context_builder(feature_id, target_repo_root)
        if context.get("error") == "CONTEXT_BUILDER_MUTATED_TARGET_REPO":
            raise HTTPException(status_code=409, detail="context-builder mutated target repo; planning stopped before architect")
        plan = await planning.run_architect(feature_id, context, target_repo_root)
        if _approval_mode == "auto":
            approval = planning.approve_plan(feature_id)
        else:
            approval = {"status": "PLAN_READY", "waves_count": len(plan.get("waves", [])), "packet_ids": []}

    packet_ids = list(approval.get("packet_ids", []))
    packet_summaries = []
    if packet_ids:
        with get_db() as db:
            pkts = db.query(Packet).filter(Packet.id.in_(packet_ids)).all()
            pkt_map = {p.id: p for p in pkts}
            for pid in packet_ids:
                pkt = pkt_map.get(pid)
                if pkt:
                    packet_summaries.append({
                        "id": pkt.id,
                        "slug": pkt.slug,
                        "title": pkt.title,
                        "wave_id": pkt.wave_id,
                    })

    return {
        "data": {
            "feature_id": feature_id,
            "feature_slug": slug,
            "slug": slug,
            "waves_count": approval.get("waves_count", len(plan.get("waves", []))),
            "packets_count": len(packet_ids),
            "packets": packet_ids,
            "packet_ids": packet_ids,
            "packet_summaries": packet_summaries,
            "context": context,
            "generated": True,
        },
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }


def _slugify(text: str) -> str:
    text = _re.sub(r'[^\w\s-]', '', text)
    return text.lower().strip().replace(" ", "-").replace("_", "-")


def _extract_action(title: str) -> str:
    words = title.split()
    if not words:
        return "ACTION"
    action = words[0].upper()
    rest = "-".join(words[1:3]).upper().replace(" ", "-") if len(words) > 1 else ""
    return f"{action}-{rest}" if rest else action


def _build_predefined_dag_packets(waves: list[dict]) -> list[dict]:
    """Normalize title and legacy action dependency references for DAG checks."""
    packet_specs = [
        (wave_index, packet)
        for wave_index, wave in enumerate(waves)
        for packet in wave.get("packets", [])
    ]
    aliases: dict[str, str] = {}
    for _wave_index, packet in packet_specs:
        title = packet["title"]
        canonical_id = packet.get("id") or packet.get("packet_id") or title
        aliases[title] = canonical_id
        aliases[_extract_action(title)] = canonical_id
        aliases[canonical_id] = canonical_id

    normalized: list[dict] = []
    for wave_index, packet in packet_specs:
        title = packet["title"]
        canonical_id = packet.get("id") or packet.get("packet_id") or title
        raw_dependencies = packet.get("depends_on", [])
        if isinstance(raw_dependencies, str):
            raw_dependencies = [raw_dependencies]
        elif not isinstance(raw_dependencies, list):
            raw_dependencies = [raw_dependencies]
        normalized.append({
            "id": canonical_id,
            "title": title,
            "depends_on": [
                aliases.get(dependency, dependency) if isinstance(dependency, str) else dependency
                for dependency in raw_dependencies
            ],
            "scope": packet.get("scope", []),
            "wave_index": wave_index,
        })
    return normalized
