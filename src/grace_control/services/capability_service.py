# ############################################################################
# AI_HEADER: capability_service — optional project API capability document
# ROLE: Normalizes optional project-local features from the actual database
#       schema and static read-surface availability. Missing optional tables are
#       reported as unavailable instead of breaking the project API.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a capability document for Admin Hub discovery.
# inputs: SQLAlchemy Session bound to the local project database.
# returns: JSON-safe capabilities/availability document.
# side_effects: Inspects local database table names only.
# emitted_logs: None.
# error_behavior: Returns unavailable optional capabilities on inspection errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CapabilityService
#     methods:
#       - document
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("capability_service")


# START_BLOCK_SERVICE
class CapabilityService:
    """Compute optional feature availability from local schema/API support."""

    # START_FUNCTION_CONTRACT
    # name: document
    # purpose: Return capabilities and explicit unavailable optional features.
    # inputs: db (Session).
    # returns: Dict with capabilities, unavailable and fetched_at.
    # side_effects: Inspects the Session's local database bind.
    # emitted_logs: None.
    # error_behavior: Never raises; inspection failures become unavailable flags.
    # END_FUNCTION_CONTRACT
    def document(self, db: Session) -> dict[str, Any]:
        try:
            tables = set(inspect(db.get_bind()).get_table_names())
        except Exception:
            tables = set()
        capabilities = {
            "sessions": "agent_sessions" in tables,
            "stage_runs": "stage_runs" in tables,
            "filesystem": True,
            "git_read": True,
            "api_explorer": True,
            "events": "events" in tables,
            "diagnostics": "packets" in tables,
            "controls": [
                "retry", "resume", "cancel", "stop", "archive", "unarchive",
                "merge", "cleanup", "maintenance_snapshot", "restart_api",
                "restart_workers", "restart_all", "reload", "openapi_mutation",
            ],
        }
        unavailable = [
            name for name, enabled in capabilities.items()
            if isinstance(enabled, bool) and not enabled
        ]
        return {
            "capabilities": capabilities,
            "unavailable": unavailable,
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }


# END_BLOCK_SERVICE
