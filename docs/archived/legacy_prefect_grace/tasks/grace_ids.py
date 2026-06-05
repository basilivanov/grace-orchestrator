from __future__ import annotations

from typing import Any


def grace_feature_ref(feature_id: str) -> str:
    return f"feature:{feature_id}"


def grace_wave_ref(feature_id: str, wave_id: str) -> str:
    return f"{grace_feature_ref(feature_id)}:wave:{wave_id}"


def grace_packet_ref(feature_id: str, wave_id: str, packet_id: str) -> str:
    return f"{grace_wave_ref(feature_id, wave_id)}:packet:{packet_id}"


def grace_refs_for_packet(packet: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(packet or {})
    feature_id = str(payload.get("feature_id") or "").strip()
    wave_id = str(payload.get("wave_id") or "").strip()
    packet_id = str(payload.get("packet_id") or "").strip()
    return {
        "grace_feature_ref": grace_feature_ref(feature_id),
        "grace_wave_ref": grace_wave_ref(feature_id, wave_id),
        "grace_packet_ref": grace_packet_ref(feature_id, wave_id, packet_id),
    }
