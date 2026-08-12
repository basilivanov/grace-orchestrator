# ############################################################################
# AI_HEADER: admin_packet_run_resolver — canonical packet-run selector resolution
# ROLE: Owns the shared packet-run lookup semantics used by admin artifact and
#       log readers. It is a lower-level database read collaborator with no
#       dependency on the admin facade or other read services.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve a packet/run selector to its persisted PacketRun row.
# inputs: SQLAlchemy Session, packet_id and a canonical, legacy or numeric
#         run selector.
# returns: Matching PacketRun or None when the selector is unknown/invalid.
# side_effects: Reads PacketRun rows from the database.
# emitted_logs: None.
# error_behavior: Invalid/non-numeric selectors return None; database errors
#                 propagate unchanged.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketRunResolver
#     methods:
#       - resolve_run
# END_MODULE_MAP

from __future__ import annotations

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketRun

_log = GraceLogger("admin_packet_run_resolver")


# START_BLOCK_SERVICE
class PacketRunResolver:
    """Resolve packet-scoped run selectors without higher-level dependencies."""

    # START_FUNCTION_CONTRACT
    # name: resolve_run
    # purpose: Resolve a persisted PacketRun by canonical ID, legacy composed
    #          ID or numeric run number in the established order.
    # inputs: db — active SQLAlchemy Session; packet_id — owning packet ID;
    #         run_id — canonical, legacy composed or numeric selector.
    # returns: PacketRun or None when no packet-scoped run matches.
    # side_effects: Reads up to three PacketRun selectors from the database.
    # emitted_logs: None.
    # error_behavior: TypeError/ValueError from a non-numeric selector is
    #                 converted to None; query errors propagate.
    # END_FUNCTION_CONTRACT
    def resolve_run(self, db: Session, packet_id: str, run_id: str) -> PacketRun | None:
        selector = str(run_id)
        run = db.query(PacketRun).filter_by(packet_id=packet_id, id=selector).first()
        if run:
            return run
        run = db.query(PacketRun).filter_by(id=f"{packet_id}-{selector}").first()
        if run:
            return run
        try:
            return db.query(PacketRun).filter_by(
                packet_id=packet_id,
                run_number=int(selector),
            ).first()
        except (TypeError, ValueError):
            return None


# END_BLOCK_SERVICE
