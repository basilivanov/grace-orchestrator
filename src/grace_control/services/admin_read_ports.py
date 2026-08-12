# ############################################################################
# AI_HEADER: admin_read_ports — narrow collaborator contracts for admin reads
# ROLE: Defines only the evidence and session read methods shared across the
#       focused admin read services. These protocols keep construction explicit
#       without mirroring the public aggregation facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide narrow structural contracts for focused admin read
#          collaborators.
# inputs: SQLAlchemy Session, packet identifiers and optional run selectors.
# returns: Existing evidence or session DTO dictionaries.
# side_effects: Implementations may read database-backed evidence/session data.
# emitted_logs: Determined by the implementing service.
# error_behavior: Implementations preserve their existing missing-data
#                 fallback behavior.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ArtifactEvidenceReader
#     methods:
#       - get_packet_evidence
#   - class: PacketSessionReader
#     methods:
#       - get_packet_sessions
# END_MODULE_MAP

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_read_ports")


# START_BLOCK_PROTOCOLS
class ArtifactEvidenceReader(Protocol):
    """Read the evidence projection required by the pipeline service."""

    # START_FUNCTION_CONTRACT
    # name: get_packet_evidence
    # purpose: Return the selected packet run's acceptance evidence DTO.
    # inputs: db — active SQLAlchemy Session; packet_id — packet ID;
    #         run_id — optional packet-run selector.
    # returns: Evidence dictionary with verdict, summary and stages.
    # side_effects: Reads persisted run result JSON.
    # emitted_logs: Implementation-defined.
    # error_behavior: Missing runs return the implementation's empty evidence
    #                 DTO.
    # END_FUNCTION_CONTRACT
    def get_packet_evidence(
        self,
        db: Session,
        packet_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]: ...


class PacketSessionReader(Protocol):
    """Read the packet session summary required by packet detail."""

    # START_FUNCTION_CONTRACT
    # name: get_packet_sessions
    # purpose: Return the session summary for one packet.
    # inputs: db — active SQLAlchemy Session; packet_id — packet ID.
    # returns: Existing session summary dictionary.
    # side_effects: Reads the optional session table.
    # emitted_logs: Implementation-defined.
    # error_behavior: Missing session storage returns the implementation's
    #                 existing fallback DTO.
    # END_FUNCTION_CONTRACT
    def get_packet_sessions(self, db: Session, packet_id: str) -> dict[str, Any]: ...


# END_BLOCK_PROTOCOLS
