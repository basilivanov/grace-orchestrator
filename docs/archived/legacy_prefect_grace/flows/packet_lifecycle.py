from __future__ import annotations

from pathlib import Path

from prefect_grace.models import PacketStatus
from prefect_grace.prefect_compat import flow, get_run_logger, task
from prefect_grace.tasks.state_store import find_record, update_record


@task(task_run_name="packet-transition:{packet_id}:{status}")
def transition_packet(packet_id: str, status: str, *, state_root: Path | str) -> dict:
    logger = get_run_logger()
    PacketStatus(status)
    packet = find_record("packets", "packets", "packet_id", packet_id, state_root=state_root)
    updated = update_record("packets", "packets", "packet_id", packet_id, {"status": status}, state_root=state_root)
    logger.info("Packet %s transitioned from %s to %s", packet_id, packet.get("status"), status)
    return updated


@flow(name="prefect-grace-packet-transition", flow_run_name="packet-transition:{packet_id}:{status}")
def packet_transition_flow(packet_id: str, status: str, *, state_root: Path | str):
    return transition_packet(packet_id, status, state_root=state_root)
