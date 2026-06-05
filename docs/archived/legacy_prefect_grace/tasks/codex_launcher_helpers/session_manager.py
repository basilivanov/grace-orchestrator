# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prefect_grace.tasks.state_store import find_record, update_record

STATE_ROOT = Path(__file__).resolve().parents[2] / "state"

def _feature_role_session(feature_id: str, role: str, *, state_root: Path | str | None = None) -> dict[str, Any] | None:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    try:
        feature = find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root)
    except KeyError:
        return None
    role_threads = feature.get("role_threads") or {}
    session = role_threads.get(role)
    if isinstance(session, dict):
        return dict(session)
    return None

def _packet_parent_session(packet: dict[str, Any], *, state_root: Path | str | None = None) -> dict[str, Any] | None:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    execution_hints = dict(packet.get("execution_hints") or {})
    parent_packet_id = str(
        execution_hints.get("resume_parent_packet_id") or packet.get("parent_packet_id") or ""
    ).strip()
    if not parent_packet_id:
        return None
    try:
        parent_packet = find_record("packets", "packets", "packet_id", parent_packet_id, state_root=resolved_state_root)
    except KeyError:
        return None
    thread_id = str(parent_packet.get("last_thread_id") or "").strip()
    if not thread_id:
        last_run = (
            parent_packet.get("last_execution_run")
            or parent_packet.get("last_codex_run")
            or {}
        )
        thread_id = str(last_run.get("thread_id") or "").strip()
    if not thread_id:
        return None
    return {
        "thread_id": thread_id,
        "packet_id": parent_packet_id,
    }

def _store_feature_role_session(
    *,
    feature_id: str,
    role: str,
    thread_id: str,
    launcher: str,
    packet_id: str,
    reasoning: str,
    sandbox: str,
    approval: str,
    model: str,
    session_mode: str,
    run_dir: Path,
    resumed_from_thread_id: str | None,
    state_root: Path | str | None = None,
) -> dict[str, Any] | None:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    try:
        feature = find_record("features", "features", "feature_id", feature_id, state_root=resolved_state_root)
    except KeyError:
        return None
    role_threads = dict(feature.get("role_threads") or {})
    previous = role_threads.get(role) if isinstance(role_threads.get(role), dict) else {}
    session = {
        **previous,
        "thread_id": thread_id,
        "launcher": launcher,
        "packet_id": packet_id,
        "reasoning": reasoning,
        "sandbox": sandbox,
        "approval": approval,
        "model": model,
        "session_mode": session_mode,
        "resumed_from_thread_id": resumed_from_thread_id,
        "run_dir": str(run_dir),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    role_threads[role] = session
    update_record(
        "features",
        "features",
        "feature_id",
        feature_id,
        {"role_threads": role_threads},
        state_root=resolved_state_root,
    )
    return session
