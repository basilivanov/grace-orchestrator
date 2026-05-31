# ############################################################################
# AI_HEADER: architect_router
# ROLE: FastAPI router for /api/architect/plan — creates features/waves/packets in READY.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Accept feature spec, generate hierarchical IDs, persist Feature+Wave+Packet in DB.
# inputs: HTTP POST with feature_spec JSON.
# returns: JSON with feature_id, waves_count, packets_count, packet_ids.
# side_effects: DB inserts (3 tables).
# emitted_logs: None.
# error_behavior: Returns 422 on invalid spec structure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: create_plan
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from grace_control.core.dag_validator import validate_dag
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave

router = APIRouter()


@router.post("/plan")
async def create_plan(request: dict) -> dict:
    spec = request["feature_spec"]
    slug = _slugify(spec["title"])
    feature_id = f"FEAT-{slug.upper()}"

    # Build packet list for DAG validation
    dag_packets = []
    for i, wave_spec in enumerate(spec.get("waves", []), 1):
        for j, pkt_spec in enumerate(wave_spec.get("packets", []), 1):
            wave_slug = _slugify(wave_spec["title"])
            wave_id = f"W{i:02d}-{wave_slug.upper()}"
            action = _extract_action(pkt_spec["title"])
            pid = f"{feature_id}-{wave_id}-P{j:02d}-{action}"
            dag_packets.append({
                "id": pid,
                "depends_on": pkt_spec.get("depends_on", []),
                "scope": pkt_spec.get("scope", []),
            })

    dag_result = validate_dag(dag_packets)
    if not dag_result.valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={
            "errors": dag_result.errors,
            "cycles": dag_result.cycles,
            "conflicts": [[c.packet_a, c.packet_b, c.overlapping_files] for c in dag_result.conflicts],
        })

    packets_created = []

    with get_db() as db:
        db.add(Feature(
            id=feature_id, slug=slug, title=spec["title"],
            description=spec.get("description", ""),
            spec_json=spec, status="NOT_STARTED",
        ))

        for i, wave_spec in enumerate(spec.get("waves", []), 1):
            wave_slug = _slugify(wave_spec["title"])
            wave_id = f"W{i:02d}-{wave_slug.upper()}"

            db.add(Wave(
                id=wave_id, feature_id=feature_id, slug=wave_slug,
                title=wave_spec["title"],
                description=wave_spec.get("description", ""),
                order=i, status="NOT_STARTED",
            ))

            for j, pkt_spec in enumerate(wave_spec.get("packets", []), 1):
                pkt_slug = _slugify(pkt_spec["title"])
                action = _extract_action(pkt_spec["title"])
                packet_id = f"{feature_id}-{wave_id}-P{j:02d}-{action}"

                db.add(Packet(
                    id=packet_id, feature_id=feature_id, wave_id=wave_id,
                    slug=pkt_slug, title=pkt_spec["title"],
                    description=pkt_spec.get("description", ""),
                    spec_json=pkt_spec,
                    state=PacketState.READY.value,  # Сразу READY
                    acceptance_profile=pkt_spec.get("acceptance_profile", "NORMAL"),
                ))
                packets_created.append(packet_id)

    return {
        "data": {
            "feature_id": feature_id,
            "waves_count": len(spec.get("waves", [])),
            "packets_count": len(packets_created),
            "packets": packets_created,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _slugify(text: str) -> str:
    import re
    text = re.sub(r'[^\w\s-]', '', text)
    return text.lower().strip().replace(" ", "-").replace("_", "-")


def _extract_action(title: str) -> str:
    words = title.split()
    if not words:
        return "ACTION"
    action = words[0].upper()
    rest = "-".join(words[1:3]).upper().replace(" ", "-") if len(words) > 1 else ""
    return f"{action}-{rest}" if rest else action
