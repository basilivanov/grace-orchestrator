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

from fastapi import APIRouter

from grace_control.core.dag_validator import validate_dag
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, Wave
from grace_control.services.feature_intake_service import FeatureIntakeService
from grace_control.services.feature_planning_service import FeaturePlanningService

router = APIRouter()
_log = GraceLogger("architect")

from grace_control.config.settings import settings


@router.post("/plan")
async def create_plan(request: dict) -> dict:
    spec = request["feature_spec"]
    title = spec.get("title", "")
    if not title:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="title is required")

    has_waves = bool(spec.get("waves"))
    target_repo_root = spec.get("target_repo_root", "") or settings.target_repo_root
    is_async = spec.get("background", True)
    _origin = spec.get("origin", "")
    _session_id = spec.get("session_id", "")
    _self_improvement = spec.get("self_improvement", False)

    slug = _slugify(title)

    # FeatureIntakeService + FeaturePlanningService path
    with get_db() as db:
        intake = FeatureIntakeService(db)
        mode = "draft_plan" if not has_waves else "draft_plan"
        result = intake.create_feature(
            title=title,
            description=spec.get("description", ""),
            target_repo_root=target_repo_root,
            mode=mode,
            origin=_origin or "business",
            self_improvement=_self_improvement or _origin == "self_evolution",
            trace_id=_session_id,
        )
        feature_id = result["feature_id"]

    if has_waves:
        # ── Pre-defined waves: validate DAG, store as plan, approve ──
        plan = {
            "waves": spec.get("waves", []),
            "constraints": spec.get("constraints", {}),
            "verification": spec.get("verification", {"t0": [], "t1": [], "t2": []}),
        }

        # Validate DAG
        dag_packets = []
        for wave_spec in plan["waves"]:
            for pkt_spec in wave_spec.get("packets", []):
                action = _extract_action(pkt_spec["title"])
                dag_packets.append({
                    "id": action,
                    "depends_on": pkt_spec.get("depends_on", []),
                    "scope": pkt_spec.get("scope", []),
                })
        if dag_packets:
            vresult = validate_dag(dag_packets)
            if not vresult.valid:
                from fastapi import HTTPException
                detail = {}
                if vresult.conflicts:
                    detail["errors"] = [str(c) for c in vresult.conflicts]
                if vresult.cycles:
                    detail["cycles"] = vresult.cycles
                raise HTTPException(status_code=422, detail=detail)

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
                await planning.run_architect(feature_id, context, target_repo_root)
                _log.info("architect_bg_completed", feature_id=feature_id)
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
        plan = await planning.run_architect(feature_id, context, target_repo_root)
        approval = planning.approve_plan(feature_id)

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
