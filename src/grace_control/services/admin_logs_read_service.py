# ############################################################################
# AI_HEADER: admin_logs_read_service — packet logs and sessions
# ROLE: Owns bounded packet log selection/filtering and the optional session
#       registry read used by the admin UI. It delegates run identity to the
#       packet read service and never mutates logs or sessions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build packet log and session DTOs for the admin facade.
# inputs: SQLAlchemy Session, packet/run selectors and log filters.
# returns: Existing logs/sessions dictionaries.
# side_effects: Reads bounded local log files and the optional session table.
# emitted_logs: SessionStore retains its existing logs.
# error_behavior: Missing runs/files return the existing empty log DTO.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminLogsReadService
#     methods:
#       - get_packet_logs
#       - get_packet_sessions
# END_MODULE_MAP

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketRun

_log = GraceLogger("admin_logs_read")


# START_BLOCK_SERVICE
class AdminLogsReadService:
    """Read-only owner for packet log and session DTOs."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the canonical packet-run selector callback.
    # inputs: run_resolver — callable resolving packet/run selectors.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises during configuration.
    # END_FUNCTION_CONTRACT
    def __init__(self, run_resolver: Callable[..., PacketRun | None]) -> None:
        self._run_resolver = run_resolver

    # START_FUNCTION_CONTRACT
    # name: get_packet_logs
    # purpose: Select a packet run's stdout/stderr/agent log, return a bounded
    #          tail and optionally filter it with a regular expression.
    # inputs: db, packet_id, run_id, stream, tail and filter_regex.
    # returns: Existing lines/total/truncated/source_file DTO.
    # side_effects: Reads a local log file.
    # emitted_logs: None.
    # error_behavior: Missing/invalid files return an empty log DTO; invalid
    #                 regex leaves the selected tail unfiltered.
    # END_FUNCTION_CONTRACT
    def get_packet_logs(
        self,
        db: Session,
        packet_id: str,
        run_id: str,
        stream: str = "stderr",
        tail: int = 200,
        filter_regex: str = "",
    ) -> dict[str, Any]:
        run = self._run_resolver(db, packet_id, run_id)
        if not run:
            return {"lines": [], "total": 0, "truncated": False, "source_file": ""}
        evidence_dir = Path(run.evidence_path) if run.evidence_path else None
        candidates: list[Path] = []
        if evidence_dir and evidence_dir.exists():
            for name in (
                "agent_output.log", "agent_stderr.log", "agent_stdout.log",
                "stderr.log", "stdout.log",
            ):
                candidate = evidence_dir / name
                if candidate.exists():
                    candidates.append(candidate)
        result_json = run.result_json or {}
        legacy_result = result_json.get("legacy_result")
        if isinstance(legacy_result, dict):
            for key in ("stdout_path", "stderr_path"):
                configured_path = legacy_result.get(key)
                if configured_path:
                    candidate = Path(configured_path)
                    if candidate.exists():
                        candidates.append(candidate)
        if stream == "stdout":
            chosen = next((candidate for candidate in candidates if "stdout" in candidate.name.lower()), None)
        elif stream == "agent":
            chosen = next((candidate for candidate in candidates if candidate.name == "agent_output.log"), None)
        else:
            chosen = next(
                (candidate for candidate in candidates if "stderr" in candidate.name.lower()),
                candidates[0] if candidates else None,
            )
        if chosen is None or not chosen.exists():
            return {"lines": [], "total": 0, "truncated": False, "source_file": ""}
        text_content = chosen.read_text(errors="replace")
        lines = text_content.splitlines()
        total = len(lines)
        selected = lines[-tail:] if tail > 0 else lines
        if filter_regex:
            try:
                regex = re.compile(filter_regex)
                selected = [line for line in selected if regex.search(line)]
            except re.error:
                pass
        return {
            "lines": selected,
            "total": total,
            "truncated": total > len(selected),
            "source_file": str(chosen),
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_sessions
    # purpose: Return the session-store summary for a packet.
    # inputs: db and packet_id.
    # returns: Existing sessions/reason dictionary.
    # side_effects: Reads the optional agent_sessions table.
    # emitted_logs: SessionStore's existing session query logs.
    # error_behavior: SessionStore returns table_missing/empty fallbacks.
    # END_FUNCTION_CONTRACT
    def get_packet_sessions(self, db: Session, packet_id: str) -> dict[str, Any]:
        from grace_control.services.session_store import SessionStore
        return SessionStore().get_sessions_for_packet(db, packet_id)


# END_BLOCK_SERVICE
